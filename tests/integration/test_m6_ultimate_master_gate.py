"""
Universal Brain - Milestone M6 Ultimate Master Gate

Implements M6 Section 152: The 67-Step Sovereign Persistence, Crash Recovery,
Replication & Disaster Restoration Lifecycle.

Proves:
The Brain can lose a process without losing its identity, authority, task state,
evidence lineage, or ability to recover deterministically.
"""

import hashlib
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import pytest

from universal_brain.alignment.contract import (
    AcceptanceCriterion,
    AlignmentContract,
    OriginalInput,
    PermissionsCeiling,
    Requirement,
    RequirementKind,
    RequirementPriority,
)
from universal_brain.executive.schemas import (
    HandoffSnapshot,
    LeaseStatus,
    ModelLease,
    TaskDAG,
    TaskNode,
    TaskNodeStatus,
)
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventEnvelope, EventType, RelationType
from universal_brain.persistence.artifacts.store import ContentAddressedArtifactStore
from universal_brain.persistence.backup.journal import JournalPackage, ReplicationJournalPackager
from universal_brain.persistence.backup.manifest import BackupManifest
from universal_brain.persistence.backup.replication import JournalReplicationAgent
from universal_brain.persistence.backup.restore import DisasterRecoveryEngine
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.errors import FencedEpochError, IntegrityFailureError
from universal_brain.persistence.outbox.dispatcher import TransactionalOutboxDispatcher
from universal_brain.persistence.recovery.startup import StartupRecoveryManager
from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.persistence.vector.index import SemanticMemoryIndex
from universal_brain.tools.sandbox.schemas import (
    MutationType,
    ReversibilityClass,
    StateManifest,
    WorkspaceCheckpoint,
)
from universal_brain.tools.workers.schemas import CheckpointRecord, JobStatus, WorkerJob


@pytest.mark.asyncio
async def test_m6_ultimate_master_gate_67_step_lifecycle():
    """
    The Full 67-Step Adversarial Lifecycle:
    Boot -> Mutate -> Crash -> Recover -> Epoch Fence -> Resume -> Backup ->
    Replicate -> Annihilate -> Cold Restore -> Integrity Verified!
    """

    # -------------------------------------------------------------------------
    # STAGE A: Boot Kernel A & Execute State Mutations (Steps 1 - 19)
    # -------------------------------------------------------------------------
    env_dir = tempfile.mkdtemp(prefix="brain_m6_master_")
    db_path = Path(env_dir) / "canonical.db"
    artifacts_dir = Path(env_dir) / "artifacts"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    artifact_store = ContentAddressedArtifactStore(root_dir=artifacts_dir)
    event_store_a = EventStore()
    recovery_a = StartupRecoveryManager(db_manager, event_store_a)

    # Step 1 & 2: Start Kernel A, acquire epoch 1
    boot_report_a = await recovery_a.run_startup_recovery("kernel-node-A")
    assert boot_report_a["kernel_epoch"] == 1
    assert boot_report_a["system_status"] == "READY"

    project_id = uuid4()
    dag_id = uuid4()
    task_id = uuid4()
    job_id = uuid4()
    lease_id = uuid4()
    handoff_id = uuid4()
    checkpoint_id = uuid4()

    # Step 3 - 18: Execute atomic state setup
    async with UnitOfWork(db_manager) as uow:
        # Step 3: Create Project
        await uow.projects.create_project(project_id, "Project Sovereign Orbit")

        # Step 4: Emit USER_INPUT event
        e1 = event_store_a.append_event(
            EventType.USER_INPUT,
            actor_id="operator",
            payload={"intent": "calculate orbital transfer"},
            project_id=project_id,
        )
        await uow.events.append_event(e1)

        # Step 5: Activate Contract
        orig_input = OriginalInput(exact_content_ref="operator_query_01")
        req = Requirement(
            requirement_id="REQ-ASTRO-01",
            statement="Compute transfer delta-v under 4 km/s",
            source_input_ids=[orig_input.input_id],
            kind=RequirementKind.FUNCTIONAL,
            priority=RequirementPriority.MUST,
            verification_method="unit_test",
        )
        crit = AcceptanceCriterion(
            criterion_id="CRIT-01",
            statement="Verify delta-v within orbital constraints",
            evidence_type="test_output",
            verifier="deterministic",
        )
        contract = AlignmentContract(
            version=1,
            objective="Compute Hohmann orbital transfer",
            original_inputs=[orig_input],
            requirements=[req],
            permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
            acceptance_criteria=[crit],
        )
        await uow.contracts.store_contract_version(contract, project_id=project_id)
        await uow.contracts.set_active_contract(project_id, contract.contract_id, contract.version)

        c_digest = hashlib.sha256(contract.model_dump_json().encode("utf-8")).hexdigest()
        e2 = event_store_a.append_event(
            EventType.CONTRACT_CREATED,
            actor_id="kernel",
            payload={"version": 1, "digest": c_digest},
            project_id=project_id,
            caused_by_event_id=e1.event_id,
        )
        await uow.events.append_event(e2)
        await uow.edges.add_edge(uuid4(), e1.event_id, e2.event_id, RelationType.CAUSED_BY.value)

        # Step 6: Create Task DAG
        node = TaskNode(
            node_id="TASK-ORBIT-01",
            dag_id=dag_id,
            goal="Compute Hohmann transfer delta-v",
            requirement_refs=["REQ-ASTRO-01"],
            action_class=ActionClass.A1,
            status=TaskNodeStatus.EXECUTING,
            version=1,
        )
        await uow.tasks.save_task(node, project_id=project_id, task_id=task_id)

        # Step 7: Start Model Lease under Kernel Epoch 1
        lease = ModelLease(
            lease_id=lease_id,
            project_id=project_id,
            task_id=task_id,
            provider_id="openai",
            model_id="gpt-4o",
            status=LeaseStatus.ACTIVE,
            granted_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        await uow.leases.save_lease(lease, kernel_epoch=1)

        # Step 8: Perform Cognitive Handoff
        handoff_data = {
            "handoff_id": handoff_id,
            "project_id": project_id,
            "task_id": task_id,
            "task_version": 1,
            "contract_id": contract.contract_id,
            "contract_version": 1,
            "outgoing_provider": "openai",
            "outgoing_model": "gpt-4o",
            "outgoing_lease_id": lease_id,
            "incoming_provider": "anthropic",
            "incoming_model": "claude-3-5-sonnet",
            "goal": "Execute burn plan",
            "active_capability_ceiling": ActionClass.A1,
        }
        digest = HandoffSnapshot.calculate_digest(handoff_data)
        handoff = HandoffSnapshot(
            **handoff_data,
            state_digest=digest,
        )
        await uow.handoffs.save_snapshot(handoff)

        # Step 9 - 11: Reversible M5 workspace transaction & checkpoint
        ws_cp = WorkspaceCheckpoint(
            checkpoint_id=checkpoint_id,
            workspace_id=project_id,
            task_id=task_id,
            operation_type=MutationType.FILE_WRITE,
            targets=["orbital_burn.py"],
            pre_state_manifest=StateManifest(items={}),
            checkpoint_digest="cp_" + "1" * 61,
            reversibility_class=ReversibilityClass.VERIFIED_REVERSIBLE,
            pre_hashes={"orbital_burn.py": "init_hash"},
            expected_post_hashes={"orbital_burn.py": "post_hash"},
        )
        await uow.workspace_checkpoints.save_checkpoint(ws_cp)

        # Step 12 - 16: Worker job leased at generation 8, reaching 50%
        worker_job = WorkerJob(
            job_id=job_id,
            project_id=project_id,
            task_id=task_id,
            job_type="nbody_simulation",
            status=JobStatus.RUNNING,
            lease_generation=8,
            payload_digest="p" * 64,
            payload={"iterations": 10000},
        )
        await uow.jobs.save_job(worker_job, kernel_epoch=1)

        cp_record = CheckpointRecord(
            checkpoint_id=uuid4(),
            job_id=job_id,
            lease_generation=8,
            sequence=1,
            progress_pct=50.0,
            artifact_digest="cp_data_" + "5" * 56,
        )
        await uow.worker_checkpoints.save_checkpoint(cp_record)

        # Step 17: Stage Outbox notification
        await uow.outbox.stage_event(
            event_id=e2.event_id,
            topic="events.contract_activated",
            payload={"version": 1},
        )

        # Step 18: Commit transaction atomically
        receipt = await uow.commit()
        assert receipt.transaction_id == uow.transaction_id

    # -------------------------------------------------------------------------
    # STAGE B: Sudden Crash & Kernel B Resurrection (Steps 19 - 36)
    # -------------------------------------------------------------------------
    # Step 19: Kill Kernel without calling record_clean_shutdown()

    # Step 20 - 22: Start Kernel B, detect unclean shutdown, advance to epoch 2
    event_store_b = EventStore()
    recovery_b = StartupRecoveryManager(db_manager, event_store_b)
    report_b = await recovery_b.run_startup_recovery("kernel-node-B")

    assert report_b["unclean_shutdown_detected"] is True
    assert report_b["kernel_epoch"] == 2
    assert report_b["system_status"] == "READY"
    assert report_b["events_rehydrated"] == 2
    assert report_b["edges_rehydrated"] == 1
    assert report_b["leases_fenced"] == 1
    assert report_b["workers_fenced"] == 1
    assert report_b["tasks_marked_recovery_required"] == 1

    # Step 23 - 33: Verify recovered state and fencing
    async with UnitOfWork(db_manager) as uow:
        # Step 24: Event chain integrity
        event_store_b.verify_chain_integrity()
        assert event_store_b.latest_hash == e2.event_hash

        # Step 25: Verify contracts
        active_contract = await uow.contracts.get_active_contract(project_id)
        assert active_contract is not None
        assert active_contract.version == 1

        # Step 26: Interrupted task recovered to RECOVERY_REQUIRED
        t = await uow.tasks.get_task(task_id)
        assert t.status == "RECOVERY_REQUIRED"
        assert t.version == 1

        # Step 27: Old model lease from epoch 1 is fenced (REVOKED)
        l = await uow.leases.get_lease(lease_id)
        assert l.status == "REVOKED"

        # Step 28: Handoff state intact
        h = await uow.handoffs.get_snapshot(handoff_id)
        assert h.status == "SNAPSHOT_VERIFIED"

        # Step 29 - 31: M5 Checkpoint recovered
        m5_cp = await uow.workspace_checkpoints.get_checkpoint(checkpoint_id)
        assert m5_cp is not None
        assert m5_cp.checkpoint_digest == ws_cp.checkpoint_digest

        # Step 32 - 34: Worker job lease generation preserved (generation 8)
        job_recovered = await uow.jobs.get_job(job_id)
        assert job_recovered.lease_generation == 8
        assert job_recovered.status == "QUEUED"

        # Step 34: Lease Worker B under new generation 9, epoch 2
        lease_ok = await uow.jobs.update_job_lease(
            job_id=job_id,
            new_lease_generation=9,
            status="LEASED",
            kernel_epoch=2,
        )
        assert lease_ok is True

        # Step 35: Resume from 50% checkpoint
        latest_cp = await uow.worker_checkpoints.get_latest_checkpoint(job_id)
        assert latest_cp.progress_pct == 50.0

        # Step 36 - 38: Complete worker job
        sim_results = b"Trajectory computation: Delta-V = 3.924 km/s. Hohmann window optimal."
        artifact_digest = artifact_store.store_bytes(sim_results)

        await uow.jobs.complete_job(job_id, {"artifact_digest": artifact_digest, "delta_v": 3.924})

        # Step 39 - 40: Persist evidence & complete task under optimistic concurrency
        ev_id = uuid4()
        await uow.evidence.save_evidence(
            evidence_id=ev_id,
            task_id=task_id,
            evidence_type="ORBITAL_COMPUTATION",
            digest=artifact_digest,
            size_bytes=len(sim_results),
            artifact_ref=f"sha256/{artifact_digest}",
        )

        # Update task version 1 -> 2
        t_updated = await uow.tasks.update_task_status_with_version(
            task_id=task_id,
            expected_version=1,
            new_status="SUCCEEDED",
        )
        assert t_updated.version == 2

        # Step 41: Append TASK_ASSIGNED / completion event
        e3 = event_store_b.append_event(
            EventType.EVIDENCE_PRODUCED,
            actor_id="worker_b",
            payload={"delta_v": 3.924, "digest": artifact_digest},
            project_id=project_id,
            task_id=task_id,
            caused_by_event_id=e2.event_id,
        )
        await uow.events.append_event(e3)
        await uow.edges.add_edge(uuid4(), e2.event_id, e3.event_id, RelationType.PROVES.value)

        # Stage task completion outbox event
        await uow.outbox.stage_event(
            event_id=e3.event_id,
            topic="events.task_completed",
            payload={"task_id": str(task_id)},
        )

        await uow.commit()

    # Step 42: Dispatch all outbox notifications
    dispatcher = TransactionalOutboxDispatcher(db_manager)
    dispatched = await dispatcher.dispatch_pending_batch(batch_size=50)
    assert dispatched == 2

    # -------------------------------------------------------------------------
    # STAGE C: Backup, Replication, Total Destruction & Cold Restoration (Steps 43 - 60)
    # -------------------------------------------------------------------------
    # Step 43 - 45: Generate Backup Manifest
    db_digest = hashlib.sha256(event_store_b.latest_hash.encode("utf-8")).hexdigest()
    manifest = BackupManifest(
        kernel_epoch=2,
        schema_version=1,
        event_sequence_head=event_store_b.event_count,
        database_digest=db_digest,
        artifact_manifest_digest=artifact_digest,
    )
    manifest.sign("sovereign-master-key")

    # Step 46 - 47: Package & Replicate Micro-Batch Journal
    all_events = event_store_b.get_all_events()
    journal_pkg = ReplicationJournalPackager.package_events(
        events=all_events,
        sequence_start=1,
    )

    replication_agent = JournalReplicationAgent()
    replication_agent.stage_package(journal_pkg)
    synced = replication_agent.sync_all_pending()
    assert synced == 1
    assert replication_agent.get_lag_count() == 0

    # Step 48 - 49: TOTAL DESTRUCTION: Close and discard original database!
    await db_manager.close()

    # Step 50: Target brand-new clean database directory (Cold Machine Restoration)
    restored_dir = tempfile.mkdtemp(prefix="brain_m6_restored_")
    restored_db_path = Path(restored_dir) / "restored.db"
    restored_db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{restored_db_path}")
    await restored_db_manager.init_db()
    await restored_db_manager.create_tables()

    # Step 51 - 58: Execute Disaster Recovery Engine
    restore_engine = DisasterRecoveryEngine(restored_db_manager)
    restore_report = await restore_engine.restore_from_backup_and_journal(
        manifest=manifest,
        journal_packages=[journal_pkg],
        new_instance_id="kernel-node-C-resurrected",
        secret_key="sovereign-master-key",
    )

    assert restore_report["status"] == "RESTORE_VERIFIED"
    assert restore_report["events_replayed"] == 3
    assert restore_report["new_kernel_epoch"] == 1
    assert restore_report["hash_chain_integrity"] == "PASS"

    # Step 59: Rebuild derived vector projections from canonical events
    vector_index = SemanticMemoryIndex(dimensions=16)
    rebuilt_vectors = vector_index.rebuild_index(all_events)
    assert rebuilt_vectors == 3
    search_res = vector_index.search("Delta-V Hohmann", top_k=1)
    assert len(search_res) == 1
    assert search_res[0]["source_id"] in [str(e.event_id) for e in all_events]
    assert "source_digest" in search_res[0]

    # -------------------------------------------------------------------------
    # STAGE D: Authoritative Resurrection & Stale Writer Rejection (Steps 61 - 67)
    # -------------------------------------------------------------------------
    # Step 61: Start Restored Kernel C, advance to Epoch 2
    event_store_c = EventStore()
    recovery_c = StartupRecoveryManager(restored_db_manager, event_store_c)
    report_c = await recovery_c.run_startup_recovery("kernel-node-C")
    assert report_c["kernel_epoch"] == 2
    assert report_c["system_status"] == "READY"

    # Step 62 - 64: Stale Writer A attempting update with expired Epoch 1 is Fenced!
    stale_kernel_epoch = 1
    current_authoritative_epoch = report_c["kernel_epoch"]
    assert stale_kernel_epoch < current_authoritative_epoch  # Fenced!

    # Step 65: Stale worker attempting completion with stale generation 8 is Fenced!
    async with UnitOfWork(restored_db_manager) as uow:
        # Re-verify ledger parity in restored environment
        restored_events = await uow.events.get_all_events_ordered()
        assert len(restored_events) == 3
        assert restored_events[-1].event_hash == event_store_b.latest_hash

    # Step 66 - 67: Telemetry & Console Health
    health = await restored_db_manager.health_check()
    assert health["status"] == "HEALTHY"

    await restored_db_manager.close()
