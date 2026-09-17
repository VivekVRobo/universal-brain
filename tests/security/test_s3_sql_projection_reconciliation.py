"""SQL must be a projection of canonical journal state, never a competing authority."""

from pathlib import Path
from uuid import uuid4

import pytest

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.recovery.startup import StartupRecoveryManager
from universal_brain.persistence.unit_of_work import UnitOfWork


async def _db(tmp_path: Path, name: str) -> DatabaseManager:
    manager = DatabaseManager(
        database_url=f"sqlite+aiosqlite:///{tmp_path / name}"
    )
    await manager.init_db()
    await manager.create_tables()
    return manager


@pytest.mark.asyncio
async def test_verified_legacy_sql_history_seeds_empty_journal_once(tmp_path: Path):
    db = await _db(tmp_path, "legacy.db")
    try:
        legacy = EventStore()
        project_id = uuid4()
        first = legacy.append_event(
            EventType.USER_INPUT,
            "operator",
            {"utterance": "legacy command"},
            project_id=project_id,
        )
        second = legacy.append_event(
            EventType.INTENT_PARSED,
            "intent_parser",
            {"primary_goal": "legacy command"},
            project_id=project_id,
            caused_by_event_id=first.event_id,
        )

        async with UnitOfWork(db) as uow:
            for event in legacy.get_all_events():
                await uow.events.append_event(event)
            for edge in legacy.get_all_edges():
                await uow.edges.add_edge(
                    edge.edge_id,
                    edge.source_event_id,
                    edge.target_event_id,
                    edge.relation_type.value,
                )
            await uow.commit()

        journal_path = tmp_path / "canonical" / "events.jsonl"
        durable = EventStore.durable(journal_path)
        recovery = StartupRecoveryManager(db, durable)
        report = await recovery.run_startup_recovery("migration-node")

        assert report["canonical_source"] == "journal"
        assert report["legacy_sql_migrated"] is True
        assert durable.event_count == 2
        assert durable.latest_hash == second.event_hash

        restarted = EventStore.durable(journal_path)
        assert restarted.event_count == 2
        assert restarted.latest_hash == second.event_hash
        assert restarted.verify_chain_integrity() is True
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_journal_rebuilds_divergent_sql_event_projection(tmp_path: Path):
    db = await _db(tmp_path, "projection.db")
    try:
        journal_path = tmp_path / "canonical" / "events.jsonl"
        canonical = EventStore.durable(journal_path)
        project_id = uuid4()
        canonical_event = canonical.append_event(
            EventType.USER_INPUT,
            "operator",
            {"utterance": "canonical truth"},
            project_id=project_id,
        )

        divergent = EventStore()
        sql_only = divergent.append_event(
            EventType.USER_INPUT,
            "rogue-sql-writer",
            {"utterance": "must not become truth"},
            project_id=project_id,
        )
        async with UnitOfWork(db) as uow:
            await uow.events.append_event(sql_only)
            await uow.commit()

        restarted = EventStore.durable(journal_path)
        recovery = StartupRecoveryManager(db, restarted)
        report = await recovery.run_startup_recovery("projection-node")

        assert report["canonical_source"] == "journal"
        assert report["legacy_sql_migrated"] is False
        assert restarted.event_count == 1
        assert restarted.latest_hash == canonical_event.event_hash

        async with UnitOfWork(db) as uow:
            rows = await uow.events.get_all_events_ordered()
            assert len(rows) == 1
            assert rows[0].event_id == canonical_event.event_id
            assert rows[0].event_hash == canonical_event.event_hash
            assert rows[0].actor_id == "operator"
    finally:
        await db.close()
