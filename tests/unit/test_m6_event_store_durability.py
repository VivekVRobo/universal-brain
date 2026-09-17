"""
Universal Brain - EventStore Durability & Hash-Chain Verification Tests

Implements M6 Sections 16-25, 88, 121-122:
Tests event append, database persistence, session boundary reload parity,
and tamper detection triggering immediate integrity failure.
"""

import tempfile
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import update

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventEnvelope, EventType, RelationType
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.errors import IntegrityFailureError
from universal_brain.persistence.models import EventORM
from universal_brain.persistence.recovery.startup import StartupRecoveryManager
from universal_brain.persistence.unit_of_work import UnitOfWork


@pytest.fixture
async def event_db():
    temp_dir = tempfile.mkdtemp(prefix="brain_m6_events_")
    db_path = Path(temp_dir) / "events.db"
    manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await manager.init_db()
    await manager.create_tables()
    yield manager
    await manager.close()


@pytest.mark.asyncio
async def test_event_persistence_and_reload_parity(event_db):
    """Verify events survive session/runtime boundary with identical cryptographic hashes."""
    p_id = uuid4()
    t_id = uuid4()
    original_store = EventStore()

    # Append 3 sequential events forming an unbroken hash chain
    e1 = original_store.append_event(EventType.USER_INPUT, "operator", {"query": "init"}, project_id=p_id)
    e2 = original_store.append_event(EventType.CONTRACT_CREATED, "agent", {"version": 1}, project_id=p_id, caused_by_event_id=e1.event_id)
    e3 = original_store.append_event(EventType.TASK_ASSIGNED, "planner", {"task": "motor"}, project_id=p_id, task_id=t_id, caused_by_event_id=e2.event_id)

    # Persist in DB transaction
    async with UnitOfWork(event_db) as uow:
        for ev in original_store.get_all_events():
            await uow.events.append_event(ev)
        for edge in original_store._edges:
            await uow.edges.add_edge(edge.edge_id, edge.source_event_id, edge.target_event_id, edge.relation_type.value)
        await uow.commit()

    # Create new empty EventStore and rehydrate from DB
    rehydrated_store = EventStore()
    recovery = StartupRecoveryManager(event_db, rehydrated_store)
    report = await recovery.run_startup_recovery("node-test-01")

    assert report["system_status"] == "READY"
    assert report["events_rehydrated"] == 3
    assert report["edges_rehydrated"] == 2
    assert rehydrated_store.latest_hash == original_store.latest_hash

    # Verify each event hash matches exactly
    reloaded_events = rehydrated_store.get_all_events()
    for orig, reloaded in zip(original_store.get_all_events(), reloaded_events):
        assert orig.event_id == reloaded.event_id
        assert orig.event_hash == reloaded.event_hash
        assert orig.prev_event_hash == reloaded.prev_event_hash
        assert orig.payload == reloaded.payload


@pytest.mark.asyncio
async def test_tampered_event_row_fails_integrity_closed(event_db):
    """Verify Invariant M6-INV-18: Tampering with a persisted event row halts recovery."""
    store = EventStore()
    e1 = store.append_event(EventType.USER_INPUT, "operator", {"amount": 100})
    e2 = store.append_event(EventType.TOOL_CALLED, "gateway", {"tool": "actuate"}, caused_by_event_id=e1.event_id)

    async with UnitOfWork(event_db) as uow:
        for ev in store.get_all_events():
            await uow.events.append_event(ev)
        await uow.commit()

    # Tamper with event 1 directly in database (simulating disk or unauthorized tampering)
    async with UnitOfWork(event_db) as uow:
        stmt = (
            update(EventORM)
            .where(EventORM.event_id == e1.event_id)
            .values(payload={"amount": 999999})  # Malicious modification!
        )
        await uow._session.execute(stmt)
        await uow.commit()

    # Recovery must detect broken cryptographic hash-chain and fail closed
    new_store = EventStore()
    recovery = StartupRecoveryManager(event_db, new_store)

    with pytest.raises(IntegrityFailureError, match="CRITICAL: Event hash-chain corrupted"):
        await recovery.run_startup_recovery("node-test-tamper")

    assert recovery.system_status == "INTEGRITY_FAILURE"
