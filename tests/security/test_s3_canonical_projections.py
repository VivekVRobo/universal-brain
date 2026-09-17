"""Restart parity tests for canonical event-backed runtime projections."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from universal_brain.api.actions import ActionManager, ActionStatus
from universal_brain.autonomy.anti_loop import AntiLoopEngine
from universal_brain.autonomy.blackboard import MissionBlackboard
from universal_brain.autonomy.commitments import CommitmentTracker
from universal_brain.autonomy.dependencies import DependencyCoordinator
from universal_brain.autonomy.escalation import EscalationEngine
from universal_brain.autonomy.leases import AgentLeaseController
from universal_brain.autonomy.scheduler import MissionScheduler
from universal_brain.autonomy.schemas import AgentRole, Mission, MissionStatus, WakeupType
from universal_brain.autonomy.wakeups import WakeupManager
from universal_brain.autonomy.watchdog import ProgressWatchdog
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass
from universal_brain.tools.workers.queue import EphemeralJobQueue
from universal_brain.tools.workers.schemas import JobStatus


def test_action_projection_survives_restart_with_idempotent_approval(tmp_path: Path):
    journal = tmp_path / "events.jsonl"
    store = EventStore.durable(journal)
    capabilities = CapabilityService(secret_key="x" * 64)
    manager = ActionManager(capabilities, event_store=store)

    proposal = manager.create_proposal(
        project_id=uuid4(),
        task_id=uuid4(),
        contract_id=uuid4(),
        contract_version=1,
        action_type="write_file",
        target_resource="src/main.py",
        action_class=ActionClass.A1,
        requested_effect="Update parser",
        payload={"content": "new"},
        required_capabilities=["write_file"],
        diff_preview="+new",
        rollback_plan="restore checkpoint",
        preflight_passed=True,
    )
    approved_at = datetime.now(timezone.utc)
    digest = proposal.compute_authorization_digest(approved_at=approved_at)
    token = manager.approve_action(
        action_id=proposal.action_id,
        proposal_version=proposal.proposal_version,
        operator_id="body-value-is-not-authority",
        authorization_digest=digest,
        nonce=proposal.nonce,
        idempotency_key="approve-1",
        approved_at=approved_at,
    )

    restarted_store = EventStore.durable(journal)
    restarted = ActionManager(capabilities, event_store=restarted_store)
    restored = restarted.get_proposal(proposal.action_id)

    assert restored is not None
    assert restored.status == ActionStatus.AUTHORIZED
    assert restored.approved_at == approved_at

    retry = restarted.approve_action(
        action_id=proposal.action_id,
        proposal_version=proposal.proposal_version,
        operator_id="ignored",
        authorization_digest=digest,
        nonce=proposal.nonce,
        idempotency_key="approve-1",
        approved_at=approved_at,
    )
    assert retry.token_id == token.token_id
    assert retry.signature == token.signature


def test_worker_job_projection_restores_lease_generation_and_checkpoint(tmp_path: Path):
    journal = tmp_path / "events.jsonl"
    store = EventStore.durable(journal)
    queue = EphemeralJobQueue(event_store=store)

    job = queue.enqueue_job(
        project_id=uuid4(),
        task_id=uuid4(),
        job_type="simulation_run",
        payload={"steps": 42},
        idempotency_key="worker-job-1",
    )
    worker = queue.register_worker("worker-1", "local_gpu")
    leased = queue.poll_and_lease("worker-1", worker.worker_session_id)
    assert leased is not None
    leased_job, lease = leased
    queue.record_progress(
        job_id=leased_job.job_id,
        worker_id="worker-1",
        lease_generation=lease.lease_generation,
        sequence=1,
        progress_pct=25.0,
    )

    restarted_store = EventStore.durable(journal)
    restarted = EphemeralJobQueue(event_store=restarted_store)
    restored = restarted.get_job(job.job_id)

    assert restored is not None
    assert restored.status == JobStatus.RUNNING
    assert restored.lease_generation == 1
    assert restored.last_checkpoint_seq == 1
    assert len(restored.checkpoints) == 1
    assert restored.checkpoints[0].progress_pct == 25.0
    assert restored.current_lease is not None
    assert restored.current_lease.worker_id == "worker-1"


def _scheduler(store: EventStore) -> MissionScheduler:
    return MissionScheduler(
        instance_id="scheduler-test",
        kernel_epoch=1,
        lease_controller=AgentLeaseController(),
        blackboard=MissionBlackboard(),
        commitment_tracker=CommitmentTracker(),
        dependency_coordinator=DependencyCoordinator(),
        progress_watchdog=ProgressWatchdog(max_operations_without_progress=3),
        anti_loop=AntiLoopEngine(max_identical_operations=3),
        wakeup_manager=WakeupManager(),
        escalation_engine=EscalationEngine(),
        event_store=store,
    )


def test_mission_scheduler_reconstructs_mission_agent_lease_and_wakeup(tmp_path: Path):
    journal = tmp_path / "events.jsonl"
    store = EventStore.durable(journal)
    scheduler = _scheduler(store)

    mission = Mission(
        project_id=uuid4(),
        title="Canonical mission",
        goal="Prove restart parity",
        contract_id=uuid4(),
        contract_version=1,
        status=MissionStatus.READY,
    )
    scheduler.register_mission(mission)
    initial_mission_version = mission.mission_version

    task_id = uuid4()
    lease = scheduler.assign_agent_to_task(
        mission=mission,
        task_id=task_id,
        role=AgentRole.BUILDER,
        action_ceiling=ActionClass.A1,
    )
    scheduler.schedule_external_wait(
        mission=mission,
        trigger_type=WakeupType.TIME,
        due_at=datetime.now(timezone.utc) + timedelta(hours=1),
        task_id=task_id,
    )

    restarted_store = EventStore.durable(journal)
    restarted = _scheduler(restarted_store)
    restored_mission = restarted.get_mission(mission.mission_id)

    assert restored_mission is not None
    assert restored_mission.status == MissionStatus.WAITING_EXTERNAL
    assert restored_mission.mission_version == initial_mission_version + 1
    assert restarted._task_generations[task_id] == 1
    assert lease.lease_id in restarted.lease_controller._leases
    assert len(restarted._agents) == 1
    assert len(restarted.wakeup_manager._wakeups) == 1
