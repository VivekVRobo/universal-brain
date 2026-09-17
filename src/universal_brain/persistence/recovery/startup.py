"""
Universal Brain - Startup & Crash Recovery Manager

Canonical state rule:
- fsync event journal is authoritative when configured;
- in-memory EventStore is rebuilt from that journal;
- SQL event/edge tables are durable indexed projections and are reconciled from
  canonical journal state, never used to overwrite a non-empty journal.
"""

from __future__ import annotations

from datetime import timezone
from typing import Any, Dict

from sqlalchemy import delete, select

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventEdge, EventEnvelope, EventType, RelationType
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.errors import IntegrityFailureError
from universal_brain.persistence.models import (
    EventEdgeORM,
    EventORM,
    TaskORM,
    WorkerCheckpointORM,
    WorkerJobORM,
)
from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.tools.workers.queue import EphemeralJobQueue


class StartupRecoveryManager:
    """Deterministically resurrect canonical state following shutdown or crash."""

    def __init__(self, db_manager: DatabaseManager, event_store: EventStore) -> None:
        self.db_manager = db_manager
        self.event_store = event_store
        self.current_epoch: int = 1
        self.system_status: str = "STARTING"

    @staticmethod
    def _event_from_orm(e_orm: EventORM) -> EventEnvelope:
        timestamp = e_orm.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return EventEnvelope(
            event_id=e_orm.event_id,
            timestamp=timestamp,
            event_type=EventType(e_orm.event_type),
            actor_id=e_orm.actor_id,
            project_id=e_orm.project_id,
            task_id=e_orm.task_id,
            contract_version=e_orm.contract_version,
            payload=e_orm.payload,
            prev_event_hash=e_orm.prev_event_hash,
            event_hash=e_orm.event_hash,
        )

    @staticmethod
    def _edge_from_orm(edge_orm: EventEdgeORM) -> EventEdge:
        created_at = edge_orm.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return EventEdge(
            edge_id=edge_orm.edge_id,
            source_event_id=edge_orm.source_event_id,
            target_event_id=edge_orm.target_event_id,
            relation_type=RelationType(edge_orm.relation_type),
            created_at=created_at,
        )

    async def _rebuild_sql_event_projection(self, uow: UnitOfWork) -> None:
        """Replace SQL event/edge projection from canonical EventStore state."""
        await uow._session.execute(delete(EventEdgeORM))
        await uow._session.execute(delete(EventORM))
        await uow._session.flush()

        for sequence, event in enumerate(self.event_store.get_all_events(), start=1):
            await uow.events.append_event(event, sequence=sequence)

        for edge in self.event_store.get_all_edges():
            await uow.edges.add_edge(
                edge.edge_id,
                edge.source_event_id,
                edge.target_event_id,
                edge.relation_type.value,
            )

    async def _rebuild_sql_worker_projection(
        self,
        uow: UnitOfWork,
        queue: EphemeralJobQueue,
    ) -> None:
        """Replace SQL worker-job/checkpoint indexes from canonical job snapshots."""
        await uow._session.execute(delete(WorkerCheckpointORM))
        await uow._session.execute(delete(WorkerJobORM))
        await uow._session.flush()

        for job in queue._jobs.values():
            await uow.jobs.save_job(job, kernel_epoch=job.kernel_epoch)
            for checkpoint in job.checkpoints:
                await uow.worker_checkpoints.save_checkpoint(checkpoint)

    async def run_startup_recovery(self, instance_id: str = "ub-node-01") -> Dict[str, Any]:
        self.system_status = "RECOVERING"
        unclean_shutdown = False
        tasks_recovered = 0
        leases_fenced = 0
        workers_fenced = 0
        legacy_sql_migrated = False
        canonical_source = "sql-legacy"

        async with UnitOfWork(self.db_manager) as uow:
            latest_lifecycle = await uow.lifecycle.get_latest_lifecycle()
            if latest_lifecycle and latest_lifecycle.status != "CLEAN_SHUTDOWN":
                unclean_shutdown = True

            marker = await uow.lifecycle.acquire_or_advance_epoch(instance_id)
            self.current_epoch = marker.kernel_epoch

            persisted_events = await uow.events.get_all_events_ordered()
            persisted_edges = await uow.edges.get_all_edges()

            try:
                sql_events = [self._event_from_orm(row) for row in persisted_events]
                sql_edges = [self._edge_from_orm(row) for row in persisted_edges]

                if self.event_store.is_durable:
                    canonical_source = "journal"

                    # First boot after upgrading a legacy SQL-only deployment:
                    # validate the SQL history, atomically seed the empty journal,
                    # then immediately treat the journal as canonical.
                    if self.event_store.event_count == 0 and sql_events:
                        self.event_store.load_verified_history(
                            sql_events,
                            sql_edges,
                            initialize_journal=True,
                        )
                        legacy_sql_migrated = True
                    else:
                        self.event_store.rehydrate_from_journal()

                    self.event_store.verify_chain_integrity()

                    # Worker jobs are canonical projections too. Fence stale
                    # execution epochs by appending canonical requeue events before
                    # rebuilding any SQL indexes.
                    canonical_worker_queue = EphemeralJobQueue(
                        event_store=self.event_store,
                        kernel_epoch=self.current_epoch,
                    )
                    workers_fenced = len(
                        canonical_worker_queue.fence_stale_epoch(self.current_epoch)
                    )

                    # SQL is a projection now. Any SQL-only rows, missing rows, or
                    # stale rows are overwritten from canonical journal truth.
                    await self._rebuild_sql_event_projection(uow)
                    await self._rebuild_sql_worker_projection(
                        uow,
                        canonical_worker_queue,
                    )
                else:
                    # Compatibility mode for tests/legacy components that have not
                    # opted into the canonical journal yet.
                    self.event_store.load_verified_history(sql_events, sql_edges)
                    self.event_store.verify_chain_integrity()

            except Exception as exc:
                self.system_status = "INTEGRITY_FAILURE"
                await uow.rollback()
                raise IntegrityFailureError(
                    f"CRITICAL: Event hash-chain corrupted during canonical recovery: {exc}"
                ) from exc

            leases_fenced = await uow.leases.fence_stale_leases(self.current_epoch)
            if not self.event_store.is_durable:
                # Legacy compatibility only. Durable runtimes fence worker jobs
                # through canonical events above and then rebuild SQL from them.
                workers_fenced = await uow.jobs.fence_stale_workers(self.current_epoch)

            stmt = select(TaskORM).where(
                TaskORM.status.in_(["RUNNING", "EXECUTING", "COGNITIVE_WORK"])
            )
            result = await uow._session.execute(stmt)
            running_tasks = list(result.scalars().all())
            for task in running_tasks:
                task.status = "RECOVERY_REQUIRED"
                tasks_recovered += 1

            await uow.commit()

        self.system_status = "READY"

        return {
            "system_status": self.system_status,
            "kernel_epoch": self.current_epoch,
            "canonical_source": canonical_source,
            "legacy_sql_migrated": legacy_sql_migrated,
            "unclean_shutdown_detected": unclean_shutdown,
            "events_rehydrated": self.event_store.event_count,
            "edges_rehydrated": len(self.event_store.get_all_edges()),
            "sql_projection_events": self.event_store.event_count,
            "sql_projection_edges": len(self.event_store.get_all_edges()),
            "leases_fenced": leases_fenced,
            "workers_fenced": workers_fenced,
            "tasks_marked_recovery_required": tasks_recovered,
        }
