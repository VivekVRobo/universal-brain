"""
Universal Brain - Transactional Outbox Unit Tests

Implements M6 Sections 18-21, 53-57, and Invariant M6-INV-07:
Tests staging outbox records in the same transaction as domain events,
at-least-once delivery, retry backoff, and dead-letter progression.
"""

import tempfile
from pathlib import Path
from uuid import uuid4
import pytest

from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.outbox.dispatcher import TransactionalOutboxDispatcher
from universal_brain.persistence.unit_of_work import UnitOfWork


@pytest.fixture
async def outbox_db():
    temp_dir = tempfile.mkdtemp(prefix="brain_m6_outbox_")
    db_path = Path(temp_dir) / "outbox.db"
    manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await manager.init_db()
    await manager.create_tables()
    yield manager
    await manager.close()


@pytest.mark.asyncio
async def test_atomic_outbox_staging_and_delivery(outbox_db):
    """Verify that domain event + outbox staging commit together, and dispatcher delivers."""
    event_id = uuid4()
    received_payloads = []

    async def mock_subscriber(topic: str, payload: dict):
        received_payloads.append((topic, payload))

    dispatcher = TransactionalOutboxDispatcher(outbox_db)
    dispatcher.register_handler("events.task_state_changed", mock_subscriber)

    # 1. Stage outbox record in UnitOfWork
    async with UnitOfWork(outbox_db) as uow:
        await uow.outbox.stage_event(
            event_id=event_id,
            topic="events.task_state_changed",
            payload={"task_id": str(uuid4()), "new_status": "COMPLETED"},
        )
        assert await uow.outbox.get_pending_count() == 1
        await uow.commit()

    # 2. Dispatch pending batch
    delivered_count = await dispatcher.dispatch_pending_batch(batch_size=10)
    assert delivered_count == 1
    assert len(received_payloads) == 1
    assert received_payloads[0][0] == "events.task_state_changed"
    assert received_payloads[0][1]["new_status"] == "COMPLETED"

    # 3. Assert outbox count is now 0 pending
    async with UnitOfWork(outbox_db) as uow:
        assert await uow.outbox.get_pending_count() == 0


@pytest.mark.asyncio
async def test_outbox_retry_and_dead_letter(outbox_db):
    """Verify failed deliveries increment attempts and eventually land in DEAD_LETTER."""
    event_id = uuid4()

    async def failing_subscriber(topic: str, payload: dict):
        raise ConnectionError("Remote downstream subscriber offline")

    dispatcher = TransactionalOutboxDispatcher(outbox_db)
    dispatcher.register_handler("events.critical", failing_subscriber)

    async with UnitOfWork(outbox_db) as uow:
        rec = await uow.outbox.stage_event(
            event_id=event_id,
            topic="events.critical",
            payload={"action": "reboot"},
        )
        outbox_id = rec.outbox_id
        await uow.commit()

    # Dispatch with max_retries = 2
    # Attempt 1 -> Fails, backoff
    await dispatcher.dispatch_pending_batch(batch_size=10, max_retries=2)

    async with UnitOfWork(outbox_db) as uow:
        from sqlalchemy import select
        from universal_brain.persistence.models import OutboxRecordORM
        stmt = select(OutboxRecordORM).where(OutboxRecordORM.outbox_id == outbox_id)
        res = await uow._session.execute(stmt)
        record = res.scalar_one()
        assert record.attempts == 1
        assert record.status == "PENDING"
        # Force available_at to past to simulate time elapsed
        from datetime import datetime, timezone, timedelta
        record.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await uow.commit()

    # Attempt 2 -> Fails, reaches max_retries=2 -> Transitions to DEAD_LETTER
    await dispatcher.dispatch_pending_batch(batch_size=10, max_retries=2)

    async with UnitOfWork(outbox_db) as uow:
        from sqlalchemy import select
        from universal_brain.persistence.models import OutboxRecordORM
        stmt = select(OutboxRecordORM).where(OutboxRecordORM.outbox_id == outbox_id)
        res = await uow._session.execute(stmt)
        record = res.scalar_one()
        assert record.attempts == 2
        assert record.status == "DEAD_LETTER"
        assert "Remote downstream subscriber offline" in record.last_error
