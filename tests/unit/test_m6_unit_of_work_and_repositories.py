"""
Universal Brain - Milestone M6 Unit of Work & Repositories Tests

Implements M6 Sections 7-15, 120, and Invariant M6-INV-01, M6-INV-02, M6-INV-05:
Tests atomic unit-of-work commit, rollback on error, repository persistence,
and optimistic concurrency conflict prevention.
"""

import tempfile
from pathlib import Path
from uuid import uuid4
import pytest

from universal_brain.executive.schemas import TaskNode, TaskNodeStatus
from universal_brain.kernel.events import ActionClass
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.errors import (
    OptimisticConcurrencyError,
    PersistenceError,
)
from universal_brain.persistence.unit_of_work import TransactionState, UnitOfWork


@pytest.fixture
async def db_fixture():
    temp_dir = tempfile.mkdtemp(prefix="brain_m6_uow_")
    db_path = Path(temp_dir) / "test_brain.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    manager = DatabaseManager(database_url=url)
    await manager.init_db()
    await manager.create_tables()
    yield manager
    await manager.close()


@pytest.mark.asyncio
async def test_unit_of_work_commit_and_state_lifecycle(db_fixture):
    """Verify clean state transitions: NEW -> OPEN -> PREPARING -> COMMITTED."""
    uow = UnitOfWork(db_fixture)
    assert uow.state == TransactionState.NEW

    p_id = uuid4()
    async with uow:
        assert uow.state == TransactionState.OPEN
        assert uow.projects is not None
        await uow.projects.create_project(p_id, "Sovereign Project Alpha")
        receipt = await uow.commit()
        assert uow.state == TransactionState.COMMITTED
        assert receipt.transaction_id == uow.transaction_id

    # Verify persisted in separate session
    async with UnitOfWork(db_fixture) as uow2:
        proj = await uow2.projects.get_project(p_id)
        assert proj is not None
        assert proj.title == "Sovereign Project Alpha"
        assert proj.version == 1


@pytest.mark.asyncio
async def test_unit_of_work_rollback_on_exception(db_fixture):
    """Verify that unhandled exception rolls back transaction to ROLLED_BACK / FAILED."""
    p_id = uuid4()

    with pytest.raises(RuntimeError, match="Simulated mid-transaction crash"):
        async with UnitOfWork(db_fixture) as uow:
            await uow.projects.create_project(p_id, "Doomed Project")
            raise RuntimeError("Simulated mid-transaction crash")

    # Assert nothing was persisted
    async with UnitOfWork(db_fixture) as uow:
        proj = await uow.projects.get_project(p_id)
        assert proj is None


@pytest.mark.asyncio
async def test_optimistic_concurrency_conflict_prevention(db_fixture):
    """Verify Invariant M6-INV-05: stale version update raises OptimisticConcurrencyError."""
    project_id = uuid4()
    task_id = uuid4()
    dag_id = uuid4()

    # 1. Create task with initial version = 1
    node = TaskNode(
        node_id="TASK-01",
        dag_id=dag_id,
        goal="Tuned motor PID",
        requirement_refs=["REQ-01"],
        action_class=ActionClass.A1,
        status=TaskNodeStatus.READY,
        version=1,
    )

    async with UnitOfWork(db_fixture) as uow:
        await uow.projects.create_project(project_id, "PID Project")
        await uow.tasks.save_task(node, project_id=project_id, task_id=task_id)
        await uow.commit()

    # 2. Writer A reads version 1
    # 3. Writer B reads version 1
    # 4. Writer A successfully updates version 1 -> version 2
    async with UnitOfWork(db_fixture) as uow_a:
        t_a = await uow_a.tasks.get_task(task_id)
        assert t_a.version == 1
        await uow_a.tasks.update_task_status_with_version(
            task_id=task_id,
            expected_version=1,
            new_status="EXECUTING",
        )
        await uow_a.commit()

    # 5. Writer B attempts to update expecting version 1 -> Must fail closed!
    async with UnitOfWork(db_fixture) as uow_b:
        with pytest.raises(OptimisticConcurrencyError, match="concurrency conflict"):
            await uow_b.tasks.update_task_status_with_version(
                task_id=task_id,
                expected_version=1,  # Stale version!
                new_status="FAILED",
            )
