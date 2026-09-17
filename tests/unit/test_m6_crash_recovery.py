"""
Universal Brain - Crash Recovery & Epoch Fencing Unit Tests

Implements M6 Sections 15, 20, 32, 34, 43, 74-83, and Invariants M6-INV-11, M6-INV-12, M6-INV-13:
Tests unclean shutdown detection, monotonic kernel epoch advancement,
automatic task recovery transition, and epoch-based fencing of stale model/worker leases.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import pytest

from universal_brain.executive.schemas import LeaseStatus, ModelLease, TaskNode, TaskNodeStatus
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.recovery.startup import StartupRecoveryManager
from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.tools.workers.schemas import JobStatus, WorkerJob


@pytest.fixture
async def recovery_db():
    temp_dir = tempfile.mkdtemp(prefix="brain_m6_recovery_")
    db_path = Path(temp_dir) / "recovery.db"
    manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await manager.init_db()
    await manager.create_tables()
    yield manager
    await manager.close()


@pytest.mark.asyncio
async def test_unclean_shutdown_and_epoch_fencing_recovery(recovery_db):
    """
    Simulate running Brain that crashes without clean shutdown.
    New Kernel starts, detects unclean shutdown, increments epoch,
    and fences stale model leases, worker jobs, and recovers interrupted tasks.
    """
    store = EventStore()
    recovery = StartupRecoveryManager(recovery_db, store)

    # 1. Kernel A Boots at Epoch 1
    report1 = await recovery.run_startup_recovery("kernel-node-A")
    assert report1["kernel_epoch"] == 1

    # 2. Kernel A creates a task, a model lease, and a worker job under epoch 1
    project_id = uuid4()
    task_id = uuid4()
    dag_id = uuid4()
    job_id = uuid4()
    lease_id = uuid4()

    async with UnitOfWork(recovery_db) as uow:
        await uow.projects.create_project(project_id, "Critical Mission")

        # Task in RUNNING state
        node = TaskNode(
            node_id="TASK-FLIGHT-01",
            dag_id=dag_id,
            goal="Compute trajectory",
            requirement_refs=["REQ-NAV-01"],
            action_class=ActionClass.A1,
            status=TaskNodeStatus.EXECUTING,
        )
        await uow.tasks.save_task(node, project_id=project_id, task_id=task_id)

        # Model Lease under epoch 1
        lease = ModelLease(
            lease_id=lease_id,
            project_id=project_id,
            task_id=task_id,
            provider_id="anthropic",
            model_id="claude-3-5-sonnet",
            status=LeaseStatus.ACTIVE,
            granted_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await uow.leases.save_lease(lease, kernel_epoch=1)

        # Worker Job leased under epoch 1
        job = WorkerJob(
            job_id=job_id,
            project_id=project_id,
            task_id=task_id,
            job_type="trajectory_sim",
            status=JobStatus.LEASED,
            lease_generation=5,
            payload_digest="d" * 64,
            payload={},
        )
        await uow.jobs.save_job(job, kernel_epoch=1)

        await uow.commit()

    # 3. Simulate CRASH: Kernel A process dies abruptly without record_clean_shutdown()

    # 4. Kernel B boots up
    store_b = EventStore()
    recovery_b = StartupRecoveryManager(recovery_db, store_b)
    report2 = await recovery_b.run_startup_recovery("kernel-node-B")

    # Assertions on Recovery Execution
    assert report2["unclean_shutdown_detected"] is True
    assert report2["kernel_epoch"] == 2
    assert report2["tasks_marked_recovery_required"] == 1
    assert report2["leases_fenced"] == 1
    assert report2["workers_fenced"] == 1
    assert report2["system_status"] == "READY"

    # Verify state in database
    async with UnitOfWork(recovery_db) as uow:
        # Task is now RECOVERY_REQUIRED
        t = await uow.tasks.get_task(task_id)
        assert t.status == "RECOVERY_REQUIRED"

        # Model lease from epoch 1 is REVOKED
        l = await uow.leases.get_lease(lease_id)
        assert l.status == "REVOKED"

        # Worker job is reset to QUEUED for safe re-scheduling
        j = await uow.jobs.get_job(job_id)
        assert j.status == "QUEUED"
        # Crucial: lease_generation did NOT reset to 0 (M6 Section 42, Invariant M6-INV-11)
        assert j.lease_generation == 5
