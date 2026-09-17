"""SQL must be a projection of canonical journal state, never a competing authority."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from universal_brain.api.read_models import latest_mission
from universal_brain.autonomy.schemas import Mission, MissionStatus
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.recovery.startup import StartupRecoveryManager
from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.tools.workers.queue import EphemeralJobQueue
from universal_brain.tools.workers.schemas import CheckpointRecord, JobStatus, WorkerJob


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



@pytest.mark.asyncio
async def test_sql_only_mission_and_worker_state_migrate_without_event_rows(tmp_path: Path):
    db = await _db(tmp_path, "aggregate-only.db")
    try:
        project_id = uuid4()
        mission = Mission(
            project_id=project_id,
            title="Legacy SQL mission",
            goal="Survive canonical migration",
            contract_id=uuid4(),
            contract_version=3,
            status=MissionStatus.ACTIVE,
        )
        job = WorkerJob(
            project_id=project_id,
            task_id=uuid4(),
            job_type="simulation_run",
            status=JobStatus.RUNNING,
            lease_generation=7,
            kernel_epoch=1,
            payload={"steps": 100},
        )
        job = job.model_copy(update={"payload_digest": job.compute_payload_digest()})
        checkpoint = CheckpointRecord(
            job_id=job.job_id,
            lease_generation=7,
            sequence=4,
            progress_pct=55.0,
            created_at=datetime.now(timezone.utc),
        )

        async with UnitOfWork(db) as uow:
            await uow.projects.create_project(project_id, "Legacy project")
            await uow.missions.create_mission(mission)
            await uow.jobs.save_job(job, kernel_epoch=1)
            await uow.worker_checkpoints.save_checkpoint(checkpoint)
            await uow.commit()

        journal_path = tmp_path / "canonical" / "events.jsonl"
        canonical = EventStore.durable(journal_path)
        assert canonical.event_count == 0

        recovery = StartupRecoveryManager(db, canonical)
        report = await recovery.run_startup_recovery("aggregate-migration-node")

        assert report["canonical_source"] == "journal"
        assert report["legacy_sql_migrated"] is True
        assert report["legacy_runtime_migrated"]["missions"] == 1
        assert report["legacy_runtime_migrated"]["worker_jobs"] == 1

        restored_mission = latest_mission(canonical, mission.mission_id)
        assert restored_mission is not None
        assert restored_mission.status == MissionStatus.ACTIVE
        assert restored_mission.mission_version == mission.mission_version

        queue = EphemeralJobQueue(event_store=canonical, kernel_epoch=report["kernel_epoch"])
        restored_job = queue.get_job(job.job_id)
        assert restored_job is not None
        # Legacy RUNNING work has no trustworthy process/lease identity after
        # restart, so migration safely requeues it while preserving fencing state.
        assert restored_job.status == JobStatus.QUEUED
        assert restored_job.lease_generation == 7
        assert restored_job.last_checkpoint_seq == 4
        assert len(restored_job.checkpoints) == 1
        assert restored_job.checkpoints[0].progress_pct == 55.0

        async with UnitOfWork(db) as uow:
            projected = await uow.jobs.get_job(job.job_id)
            assert projected is not None
            assert projected.status == "QUEUED"
            projected_checkpoints = await uow.worker_checkpoints.get_checkpoints_for_job(job.job_id)
            assert len(projected_checkpoints) == 1
            assert projected_checkpoints[0].sequence == 4

        restarted = EventStore.durable(journal_path)
        assert latest_mission(restarted, mission.mission_id) is not None
        replayed_queue = EphemeralJobQueue(event_store=restarted, kernel_epoch=report["kernel_epoch"])
        assert replayed_queue.get_job(job.job_id).status == JobStatus.QUEUED
    finally:
        await db.close()
