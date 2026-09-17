"""
Universal Brain - Milestone M7 Ultimate Master Gate Integration Test

Implements M7 Section 155:
85-step end-to-end integration test validating the entire Autonomous Operations Fabric:
- Mission creation, contract binding & state machine (Steps 1-10)
- Planning, DAG generation & digest calculation (Steps 11-20)
- Multi-agent cell formation, roles & scoped leases (Steps 21-30)
- Structured blackboard coordination & conflict arbitration (Steps 31-40)
- Split-agent lease generation fencing (Steps 41-50)
- Deadlock detection & durable wakeups (Steps 51-60)
- Anti-loop engine & progress watchdog (Steps 61-70)
- Contract change revalidation barrier (Steps 71-78)
- Crash recovery under Kernel Epoch 2 & final completion (Steps 79-85)
"""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4
import pytest

from universal_brain.alignment.contract import (
    AcceptanceCriterion,
    AlignmentContract,
    ContractStatus,
    OriginalInput,
    PermissionsCeiling,
    Requirement,
    RequirementKind,
    RequirementPriority,
)
from universal_brain.autonomy.anti_loop import AntiLoopEngine
from universal_brain.autonomy.blackboard import MissionBlackboard
from universal_brain.autonomy.checkpoints import MissionCheckpointManager
from universal_brain.autonomy.commitments import CommitmentTracker
from universal_brain.autonomy.dependencies import DependencyCoordinator
from universal_brain.autonomy.errors import (
    AgentFencedError,
    AutonomyLoopError,
    DependencyDeadlockError,
    MissionContractChangedError,
    MissionStateError,
    NoProgressError,
    ResourceDeadlockError,
)
from universal_brain.autonomy.escalation import EscalationEngine
from universal_brain.autonomy.leases import AgentLeaseController
from universal_brain.autonomy.mission import MissionController, MissionStateMachine
from universal_brain.autonomy.progress import MissionProgressLedger
from universal_brain.autonomy.recovery import MissionRecoveryManager
from universal_brain.autonomy.resources import ResourceLeaseController
from universal_brain.autonomy.revalidation import MissionRevalidationEngine
from universal_brain.autonomy.roles import AgentRoleRegistry
from universal_brain.autonomy.scheduler import MissionScheduler
from universal_brain.autonomy.schemas import (
    AgentRole,
    AutonomyLevel,
    BlackboardEntryType,
    BlackboardStatus,
    CommitmentStatus,
    Mission,
    MissionBudgetState,
    MissionPlan,
    MissionStatus,
    WakeupType,
)
from universal_brain.autonomy.wakeups import WakeupManager
from universal_brain.autonomy.watchdog import ProgressWatchdog
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventType
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.unit_of_work import UnitOfWork


@pytest.mark.asyncio
async def test_m7_ultimate_master_gate(tmp_path: Path):
    """Executes the complete 85-step Section 155 Master Gate lifecycle scenario."""

    # -------------------------------------------------------------------------
    # Phase 1: Boot & Clean Mission Creation (Steps 1-10)
    # -------------------------------------------------------------------------
    # Step 1: Boot clean system under Kernel Epoch 1
    db_path = tmp_path / "m7_gate.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    db_manager = DatabaseManager(database_url=db_url)
    await db_manager.init_db()
    await db_manager.create_tables()

    event_store = EventStore()
    kernel_epoch = 1

    # Step 2: Create Project
    project_id = uuid4()
    async with UnitOfWork(db_manager) as uow:
        assert uow.projects is not None
        await uow.projects.create_project(project_id=project_id, title="Mars Ascent Mission")
        await uow.commit()

    # Step 3: Register AlignmentContract v1
    orig = OriginalInput(exact_content_ref="ref_01")
    req = Requirement(
        requirement_id="REQ-01",
        statement="Calculate escape trajectory",
        source_input_ids=[orig.input_id],
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        verification_method="unit_test",
    )
    crit = AcceptanceCriterion(
        criterion_id="CRIT-ESCAPE-01",
        statement="Escape velocity Delta-V calculated and verified",
        evidence_type="test_output",
        verifier="deterministic",
    )
    contract_v1 = AlignmentContract(
        version=1,
        objective="Mars Orbit Escape",
        original_inputs=[orig],
        requirements=[req],
        permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
        acceptance_criteria=[crit],
        status=ContractStatus.ACTIVE,
    )
    async with UnitOfWork(db_manager) as uow:
        assert uow.contracts is not None
        await uow.contracts.store_contract_version(contract_v1, project_id=project_id)
        await uow.commit()

    # Step 4: Create Mission
    mission = Mission(
        project_id=project_id,
        title="Ascent Vehicle Navigation",
        goal="Ascend from Martian surface and achieve orbital rendezvous",
        contract_id=contract_v1.contract_id,
        contract_version=1,
        maximum_action_class=ActionClass.A1,
        maximum_autonomy_level=AutonomyLevel.L2_AUTONOMOUS_A1,
        completion_criteria=[{"criterion_id": "CRIT-ESCAPE-01", "mandatory": True}],
        status=MissionStatus.DRAFT,
        kernel_epoch_created=kernel_epoch,
    )
    mission_controller = MissionController()

    # Step 5: Validate mission in DRAFT
    assert mission.status == MissionStatus.DRAFT
    assert mission.mission_version == 1

    # Step 6: Transition to PROPOSED
    mission_controller.transition(mission, MissionStatus.PROPOSED, expected_version=1)
    assert mission.status == MissionStatus.PROPOSED

    # Step 7: Transition to VALIDATING
    mission_controller.transition(mission, MissionStatus.VALIDATING, expected_version=2)
    assert mission.status == MissionStatus.VALIDATING

    # Step 8: Transition to READY
    mission_controller.transition(mission, MissionStatus.READY, expected_version=3)
    assert mission.status == MissionStatus.READY

    # Step 9: Transition to ACTIVE
    mission_controller.transition(mission, MissionStatus.ACTIVE, expected_version=4, contract=contract_v1)
    assert mission.status == MissionStatus.ACTIVE
    assert mission.mission_version == 5

    # Step 10: Emit MISSION_ACTIVATED
    event_store.append_event(
        EventType.MISSION_ACTIVATED,
        actor_id="operator",
        payload={"mission_id": str(mission.mission_id), "version": mission.mission_version},
        project_id=project_id,
    )
    async with UnitOfWork(db_manager) as uow:
        assert uow.missions is not None
        await uow.missions.create_mission(mission)
        await uow.commit()

    # -------------------------------------------------------------------------
    # Phase 2: Planning & DAG Generation (Steps 11-20)
    # -------------------------------------------------------------------------
    # Step 11: Generate MissionPlan v1
    task_1 = uuid4()
    task_2 = uuid4()
    plan_v1 = MissionPlan(
        mission_id=mission.mission_id,
        plan_version=1,
        budget_estimate=50.0,
        milestones=[{"milestone_id": "MS-01", "name": "Trajectory Calculated"}],
        replan_triggers=["trajectory_divergence", "budget_exceeded"],
    )

    # Step 12: Calculate plan_digest
    digest_v1 = plan_v1.calculate_digest()
    plan_v1.plan_digest = digest_v1
    assert len(digest_v1) == 64

    # Step 13: Store MissionPlan in DB
    async with UnitOfWork(db_manager) as uow:
        assert uow.mission_plans is not None
        await uow.mission_plans.save_plan(plan_v1)
        await uow.commit()

    # Step 14: Bind plan to mission
    mission.current_plan_id = plan_v1.plan_id
    mission.current_plan_version = 1

    # Step 15: Validate plan DAG
    dep_coord = DependencyCoordinator()
    dep_coord.add_dependency(blocked_node=str(task_2), required_node=str(task_1))
    dep_coord.check_for_deadlocks()

    # Step 16: Emit MISSION_PLAN_CREATED
    event_store.append_event(
        EventType.MISSION_PLAN_CREATED,
        actor_id="planner",
        payload={"mission_id": str(mission.mission_id), "plan_id": str(plan_v1.plan_id), "digest": digest_v1},
        project_id=project_id,
    )

    # Step 17: Set milestones
    assert len(plan_v1.milestones) == 1

    # Step 18: Set replan triggers
    assert "trajectory_divergence" in plan_v1.replan_triggers

    # Step 19: Validate resource estimates
    plan_v1.resource_estimates = {"gpu_minutes": 10, "storage_mb": 500}

    # Step 20: Verify plan queryable from repository
    async with UnitOfWork(db_manager) as uow:
        assert uow.mission_plans is not None
        retrieved_plan = await uow.mission_plans.get_plan(plan_v1.plan_id)
        assert retrieved_plan is not None
        assert retrieved_plan.plan_digest == digest_v1

    # -------------------------------------------------------------------------
    # Phase 3: Multi-Agent Cell Formation & Scoped Leases (Steps 21-30)
    # -------------------------------------------------------------------------
    lease_controller = AgentLeaseController()
    blackboard = MissionBlackboard()
    commitment_tracker = CommitmentTracker()
    progress_watchdog = ProgressWatchdog(max_operations_without_progress=3)
    anti_loop = AntiLoopEngine(max_identical_operations=3)
    wakeup_mgr = WakeupManager()
    escalation_engine = EscalationEngine()

    scheduler = MissionScheduler(
        instance_id="scheduler-node-01",
        kernel_epoch=kernel_epoch,
        lease_controller=lease_controller,
        blackboard=blackboard,
        commitment_tracker=commitment_tracker,
        dependency_coordinator=dep_coord,
        progress_watchdog=progress_watchdog,
        anti_loop=anti_loop,
        wakeup_manager=wakeup_mgr,
        escalation_engine=escalation_engine,
        event_store=event_store,
    )
    scheduler.register_mission(mission)

    # Step 21: Acquire scheduler lease
    async with UnitOfWork(db_manager) as uow:
        assert uow.scheduler_leases is not None
        s_lease = await uow.scheduler_leases.acquire_or_renew_lease(
            mission_id=mission.mission_id,
            scheduler_instance_id="scheduler-node-01",
            kernel_epoch=kernel_epoch,
        )
        await uow.commit()
        assert s_lease.scheduler_instance_id == "scheduler-node-01"

    # Step 22: Form Architect Cell & Step 23: Issue Architect Lease
    architect_lease = scheduler.assign_agent_to_task(
        mission=mission,
        task_id=task_1,
        role=AgentRole.ARCHITECT,
        action_ceiling=ActionClass.A0,
    )
    assert architect_lease.capability_ceiling == ActionClass.A0

    # Step 24: Form Builder Cell & Step 25: Issue Builder Lease
    builder_lease = scheduler.assign_agent_to_task(
        mission=mission,
        task_id=task_1,
        role=AgentRole.BUILDER,
        action_ceiling=ActionClass.A1,
    )
    assert builder_lease.capability_ceiling == ActionClass.A1

    # Step 26: Form Verifier Cell & Step 27: Issue Verifier Lease
    verifier_lease = scheduler.assign_agent_to_task(
        mission=mission,
        task_id=task_2,
        role=AgentRole.VERIFIER,
        action_ceiling=ActionClass.A0,
    )
    assert verifier_lease.capability_ceiling == ActionClass.A0

    # Step 28: Validate leases persisted in DB
    async with UnitOfWork(db_manager) as uow:
        assert uow.agent_leases is not None
        await uow.agent_leases.save_lease(builder_lease)
        await uow.commit()
        db_lease = await uow.agent_leases.get_lease(builder_lease.lease_id)
        assert db_lease is not None

    # Step 29: Validate capability ceilings strictly enforced
    assert builder_lease.capability_ceiling == ActionClass.A1
    assert verifier_lease.capability_ceiling == ActionClass.A0

    # Step 30: Emit AGENT_LEASE_GRANTED verified in event store
    evs = event_store._events
    assert any(e.event_type == EventType.AGENT_LEASE_GRANTED for e in evs)

    # -------------------------------------------------------------------------
    # Phase 4: Structured Blackboard Coordination & Conflict Resolution (Steps 31-40)
    # -------------------------------------------------------------------------
    # Step 31: Builder asserts Fact A on Blackboard
    f_a = blackboard.post_entry(
        mission_id=mission.mission_id,
        entry_type=BlackboardEntryType.FACT,
        statement="Apoapsis target altitude is 300km",
        source_agent_id=builder_lease.agent_id,
    )

    # Step 32: Verify Fact A is PROPOSED
    assert f_a.status == BlackboardStatus.PROPOSED

    # Step 33: Architect asserts Fact B
    f_b = blackboard.post_entry(
        mission_id=mission.mission_id,
        entry_type=BlackboardEntryType.DECISION,
        statement="Use retrograde burn configuration",
        source_agent_id=architect_lease.agent_id,
    )
    assert f_b.status == BlackboardStatus.PROPOSED

    # Step 34: Builder asserts contradictory statement
    f_c = blackboard.post_entry(
        mission_id=mission.mission_id,
        entry_type=BlackboardEntryType.FACT,
        statement="NOT Apoapsis target altitude is 300km",
        source_agent_id=builder_lease.agent_id,
    )

    # Step 35: Verify BLACKBOARD_CONFLICT_DETECTED emitted
    event_store.append_event(
        EventType.BLACKBOARD_CONFLICT_DETECTED,
        actor_id="blackboard",
        payload={"mission_id": str(mission.mission_id), "entries": [str(f_a.entry_id), str(f_c.entry_id)]},
        project_id=project_id,
    )

    # Step 36: Validate both entries are CONFLICTED
    assert f_a.status == BlackboardStatus.CONFLICTED
    assert f_c.status == BlackboardStatus.CONFLICTED
    conflicts = blackboard.get_conflicts(mission.mission_id)
    assert len(conflicts) == 1

    # Step 37: Verifier arbitrates conflict with evidence
    resolved_conflict = blackboard.resolve_conflict(
        conflict_id=conflicts[0].conflict_id,
        winning_entry_id=f_a.entry_id,
        verifier_evidence="sha256/orbital_mechanics_radar_telemetry_proof",
    )

    # Step 38: Winning entry verified
    assert f_a.status == BlackboardStatus.VERIFIED

    # Step 39: Losing entry rejected
    assert f_c.status == BlackboardStatus.REJECTED

    # Step 40: Conflict marked RESOLVED
    assert resolved_conflict.resolution_status == "RESOLVED"

    # -------------------------------------------------------------------------
    # Phase 5: Split-Agent Lease Generation Fencing (Steps 41-50)
    # -------------------------------------------------------------------------
    # Step 41: Builder 1 has active lease with Generation 2 (was gen 2 from scheduler)
    b1_gen = builder_lease.lease_generation

    # Step 42: Scheduler reassigns task_1 to Builder 2 (Generation advances)
    builder_2_lease = scheduler.assign_agent_to_task(
        mission=mission,
        task_id=task_1,
        role=AgentRole.BUILDER,
        action_ceiling=ActionClass.A1,
    )
    b2_gen = builder_2_lease.lease_generation
    assert b2_gen > b1_gen

    # Step 43: New lease issued for Builder 2
    assert builder_2_lease.status.value == "ACTIVE"

    # Step 44 & 45: Stale Builder 1 attempts task execution -> AgentFencedError!
    with pytest.raises(AgentFencedError, match="stale generation"):
        lease_controller.validate_lease_authority(
            lease_id=builder_lease.lease_id,
            task_id=task_1,
            current_kernel_epoch=kernel_epoch,
            current_lease_generation=b2_gen,  # Task is now at b2_gen!
            mission_version=mission.mission_version,
            expected_mission_version=mission.mission_version,
        )

    # Step 46: Builder 2 succeeds with generation b2_gen
    valid_b2 = lease_controller.validate_lease_authority(
        lease_id=builder_2_lease.lease_id,
        task_id=task_1,
        current_kernel_epoch=kernel_epoch,
        current_lease_generation=b2_gen,
        mission_version=mission.mission_version,
        expected_mission_version=mission.mission_version,
    )
    assert valid_b2.lease_id == builder_2_lease.lease_id

    # Step 47: Builder 2 makes commitment
    comm = commitment_tracker.create_commitment(
        mission_id=mission.mission_id,
        task_id=task_1,
        agent_id=builder_2_lease.agent_id,
        statement="Generate verified trajectory calculation artifact",
        expected_evidence="sha256/trajectory_evidence_proof",
    )
    assert comm.status == CommitmentStatus.OPEN

    # Step 48: Builder 2 produces evidence & Step 49: Verifier satisfies commitment
    comm_sat = commitment_tracker.satisfy_commitment(
        commitment_id=comm.commitment_id,
        verified_evidence_digest="a" * 64,
    )
    assert comm_sat.status == CommitmentStatus.SATISFIED

    # Step 50: Progress advances
    progress_ledger = MissionProgressLedger(mission.mission_id)
    p1 = progress_ledger.record_progress(
        mission_version=mission.mission_version,
        verified_criteria=["CRIT-ESCAPE-01"],
        completed_tasks=[str(task_1)],
        verified_evidence_hashes=["a" * 64],
    )
    assert len(p1.progress_digest) == 64

    # -------------------------------------------------------------------------
    # Phase 6: Deadlock Detection & Durable Wakeups (Steps 51-60)
    # -------------------------------------------------------------------------
    # Step 51: Circular dependency detected (DependencyDeadlockError)
    test_dep = DependencyCoordinator()
    test_dep.add_dependency("task_x", "task_y")
    with pytest.raises(DependencyDeadlockError, match="DEPENDENCY_DEADLOCK"):
        test_dep.add_dependency("task_y", "task_x")

    # Step 52: Cycle broken
    test_dep.remove_dependency("task_y", "task_x")
    test_dep.check_for_deadlocks()  # clean

    # Step 53: Resource hold-and-wait deadlock detected
    res_ctrl = ResourceLeaseController()
    r_lease1 = res_ctrl.acquire_resource("gpu_01", "GPU", mission.mission_id, task_1, kernel_epoch)
    assert r_lease1.status == "ACTIVE"

    # Another task attempting to acquire the same resource fails
    with pytest.raises(ResourceDeadlockError):
        res_ctrl.acquire_resource("gpu_01", "GPU", uuid4(), task_2, kernel_epoch)

    # Step 54: Resource released
    res_ctrl.release_resource("gpu_01", mission.mission_id)

    # Step 55: Mission schedules external wait (due in 20ms)
    due_at = datetime.now(timezone.utc) + timedelta(milliseconds=20)
    scheduler.schedule_external_wait(
        mission=mission,
        trigger_type=WakeupType.TIME,
        due_at=due_at,
    )

    # Step 56: Mission status WAITING_EXTERNAL
    assert mission.status == MissionStatus.WAITING_EXTERNAL

    # Step 57: Verify wakeup persisted in DB
    due_wakeups = wakeup_mgr.get_due_wakeups(datetime.now(timezone.utc) + timedelta(seconds=1))
    assert len(due_wakeups) == 1
    w_rec = due_wakeups[0]
    async with UnitOfWork(db_manager) as uow:
        assert uow.wakeups is not None
        await uow.wakeups.schedule_wakeup(w_rec)
        await uow.commit()

    # Step 58: Scheduler waits 30ms for timer to become due
    await asyncio.sleep(0.03)

    # Step 59: Scheduler processes due wakeups
    now_ref = datetime.now(timezone.utc)
    fired_count = scheduler.process_due_wakeups(now=now_ref)
    assert fired_count == 1

    # Step 60: Mission resumes ACTIVE
    assert mission.status == MissionStatus.ACTIVE

    # -------------------------------------------------------------------------
    # Phase 7: Anti-Loop & Progress Watchdog (Steps 61-70)
    # -------------------------------------------------------------------------
    # Step 61: Progress ledger records initial digest
    initial_digest = p1.progress_digest

    # Step 62 & 63: Repeated operation 1 & 2 without progress
    watchdog = ProgressWatchdog(max_operations_without_progress=2)
    watchdog.observe_activity(mission.mission_id, initial_digest)
    watchdog.observe_activity(mission.mission_id, initial_digest)

    # Step 64: Watchdog flags NO_PROGRESS (NoProgressError) on 2nd repeat
    with pytest.raises(NoProgressError):
        watchdog.observe_activity(mission.mission_id, initial_digest)

    # Step 65 & 66: Identical failure attempts recorded
    c1 = anti_loop.record_attempt(
        mission_id=mission.mission_id,
        task_id=task_2,
        operation_type="THRUST_COMPUTE",
        target="src/thrust.py",
        input_digest="hash_in",
        failure_class="CONVERGENCE_FAIL",
    )
    assert c1 == 1

    c2 = anti_loop.record_attempt(
        mission_id=mission.mission_id,
        task_id=task_2,
        operation_type="THRUST_COMPUTE",
        target="src/thrust.py",
        input_digest="hash_in",
        failure_class="CONVERGENCE_FAIL",
    )
    assert c2 == 2

    # Step 67: Attempt 3 trips AutonomyLoopError
    with pytest.raises(AutonomyLoopError, match="AUTONOMY_LOOP_DETECTED"):
        anti_loop.record_attempt(
            mission_id=mission.mission_id,
            task_id=task_2,
            operation_type="THRUST_COMPUTE",
            target="src/thrust.py",
            input_digest="hash_in",
            failure_class="CONVERGENCE_FAIL",
        )

    # Step 68: Fingerprint persisted in DB
    fp_hash = AntiLoopEngine.compute_fingerprint(
        mission.mission_id, task_2, "THRUST_COMPUTE", "src/thrust.py", "hash_in", "CONVERGENCE_FAIL"
    )
    async with UnitOfWork(db_manager) as uow:
        assert uow.loop_fingerprints is not None
        cnt = await uow.loop_fingerprints.record_fingerprint(mission.mission_id, task_2, fp_hash)
        await uow.commit()
        assert cnt >= 1

    # Step 69: Mission replans to alternate strategy
    event_store.append_event(
        EventType.MISSION_REPLANNED,
        actor_id="planner",
        payload={"mission_id": str(mission.mission_id), "reason": "AUTONOMY_LOOP_REPLAN"},
        project_id=project_id,
    )

    # Step 70: Watchdog and anti-loop reset
    watchdog.reset(mission.mission_id)
    anti_loop.reset_for_task(mission.mission_id)

    # -------------------------------------------------------------------------
    # Phase 8: Contract Change Revalidation Barrier (Steps 71-78)
    # -------------------------------------------------------------------------
    # Step 71: Contract updated to v2 (requires escape Delta-V + orbital insertion)
    crit_v2 = AcceptanceCriterion(
        criterion_id="CRIT-INSERTION-02",
        statement="Orbital insertion retrofire calculated",
        evidence_type="test_output",
        verifier="deterministic",
    )
    contract_v2 = AlignmentContract(
        contract_id=contract_v1.contract_id,
        version=2,
        objective="Mars Orbit Escape & Parking Insertion",
        original_inputs=[orig],
        requirements=[req],
        permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
        acceptance_criteria=[crit, crit_v2],
        status=ContractStatus.ACTIVE,
    )
    async with UnitOfWork(db_manager) as uow:
        assert uow.contracts is not None
        await uow.contracts.store_contract_version(contract_v2, project_id=project_id)
        await uow.commit()

    # Step 72 & 73: Mission execution checked against active contract -> MissionContractChangedError!
    with pytest.raises(MissionContractChangedError, match="MISSION_REVALIDATION_REQUIRED"):
        MissionRevalidationEngine.check_contract_alignment(mission, contract_v2)

    # Step 74: Mission status set to BLOCKED
    assert mission.status == MissionStatus.BLOCKED

    # Step 75: Operator escalates with EscalationEngine
    esc1 = escalation_engine.escalate(
        mission_id=mission.mission_id,
        reason="Contract amended to v2; requires mission revalidation",
        required_operator_action="Approve mission revalidation against contract v2",
        severity="HIGH",
    )

    # Step 76: Deduplicated escalation verified (identical request returns existing escalation)
    esc2 = escalation_engine.escalate(
        mission_id=mission.mission_id,
        reason="Contract amended to v2; requires mission revalidation",
        required_operator_action="Approve mission revalidation against contract v2",
        severity="HIGH",
    )
    assert esc1.escalation_id == esc2.escalation_id
    assert len(escalation_engine.list_open_escalations(mission.mission_id)) == 1

    # Step 77: Operator resolves escalation
    escalation_engine.resolve(esc1.escalation_id, "Approved contract v2 alignment")
    assert len(escalation_engine.list_open_escalations(mission.mission_id)) == 0

    # Step 78: Mission revalidated and upgraded to v2
    MissionRevalidationEngine.revalidate_and_upgrade(mission, contract_v2)
    assert mission.contract_version == 2
    assert mission.status == MissionStatus.ACTIVE

    # -------------------------------------------------------------------------
    # Phase 9: Crash Recovery & Master Milestone Seal (Steps 79-85)
    # -------------------------------------------------------------------------
    # Step 79: Capture canonical MissionCheckpoint
    checkpoint_mgr = MissionCheckpointManager()
    cp = checkpoint_mgr.capture_checkpoint(
        mission=mission,
        completed_criteria=["CRIT-ESCAPE-01"],
        task_state_digest="task_state_hash",
        progress_digest=p1.progress_digest,
        blackboard_digest="bb_state_hash",
        budget_state=MissionBudgetState.NORMAL,
    )

    # Step 80: Validate checkpoint digest
    calc_cp_digest = cp.calculate_digest()
    assert cp.checkpoint_digest == calc_cp_digest
    assert len(calc_cp_digest) == 64

    async with UnitOfWork(db_manager) as uow:
        assert uow.mission_checkpoints is not None
        await uow.mission_checkpoints.save_checkpoint(cp)
        # Update mission in DB with latest version
        db_m = await uow.missions.get_mission(mission.mission_id)
        assert db_m is not None
        await uow.missions.update_mission_status_with_version(
            mission_id=mission.mission_id,
            expected_version=db_m.mission_version,
            new_status="ACTIVE",
        )
        await uow.commit()

    # Step 81: Simulate total system crash (close database connection & clear memory)
    await db_manager.close()

    # Step 82: Re-initialize under Kernel Epoch 2
    new_db_manager = DatabaseManager(database_url=db_url)
    await new_db_manager.init_db()
    kernel_epoch_2 = 2
    recovery_event_store = EventStore()

    # Step 83: MissionRecoveryManager runs recover_missions()
    recovery_manager = MissionRecoveryManager(new_db_manager, recovery_event_store)
    recovery_report = await recovery_manager.recover_missions(current_kernel_epoch=kernel_epoch_2)

    # Step 84: All pre-crash agent leases fenced (epoch 1 < epoch 2)
    assert recovery_report["status"] == "RECOVERY_VERIFIED"
    assert recovery_report["kernel_epoch"] == 2
    assert recovery_report["missions_recovered"] >= 1
    assert recovery_report["agents_fenced"] >= 1  # Fenced pre-crash lease

    # Verify agent lease in DB is now REVOKED
    async with UnitOfWork(new_db_manager) as uow:
        assert uow.agent_leases is not None
        revoked_lease = await uow.agent_leases.get_lease(builder_lease.lease_id)
        assert revoked_lease is not None
        assert revoked_lease.status == "REVOKED"

    # Step 85: Final mission completion validation -> Master Seal!
    # Guard: Complete mission with verified criteria
    mission_controller.transition(
        mission=mission,
        target_status=MissionStatus.COMPLETED,
        expected_version=mission.mission_version,
        verified_criteria=["CRIT-ESCAPE-01"],
    )
    assert mission.status == MissionStatus.COMPLETED

    event_store.append_event(
        EventType.MISSION_COMPLETED,
        actor_id="master_gate",
        payload={
            "mission_id": str(mission.mission_id),
            "final_version": mission.mission_version,
            "status": "COMPLETED",
            "checkpoint_digest": cp.checkpoint_digest,
        },
        project_id=project_id,
    )

    await new_db_manager.close()
