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

from universal_brain.autonomy.schemas import AgentCell, AgentLease, Mission, WakeupRecord
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventEdge, EventEnvelope, EventType, RelationType
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.errors import IntegrityFailureError
from universal_brain.persistence.models import (
    AgentCellORM,
    AgentLeaseORM,
    EventEdgeORM,
    EventORM,
    MissionORM,
    TaskORM,
    WakeupRecordORM,
    WorkerCheckpointORM,
    WorkerJobORM,
)
from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.tools.workers.queue import EphemeralJobQueue
from universal_brain.tools.workers.schemas import CheckpointRecord, JobStatus, WorkerJob


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

    async def _migrate_legacy_sql_runtime_state_to_journal(
        self,
        uow: UnitOfWork,
    ) -> Dict[str, int]:
        """One-time import of SQL-only runtime aggregates into canonical events.

        Older builds persisted missions/worker jobs directly in SQL without full
        event snapshots. On the first journal-backed boot we preserve those
        aggregates by emitting migration snapshots before SQL becomes projection-only.
        Active worker leases cannot be reconstructed safely from legacy SQL, so
        they are migrated as QUEUED with the monotonic lease_generation preserved.
        """
        migrated = {
            "missions": 0,
            "worker_jobs": 0,
            "agent_leases": 0,
            "wakeups": 0,
        }

        existing_missions: set[UUID] = set()
        existing_jobs: set[UUID] = set()
        existing_leases: set[UUID] = set()
        existing_wakeups: set[UUID] = set()

        for event in self.event_store.get_all_events():
            payload = event.payload or {}
            raw_mission = payload.get("mission")
            if isinstance(raw_mission, dict) and raw_mission.get("mission_id"):
                existing_missions.add(UUID(str(raw_mission["mission_id"])))

            raw_job = payload.get("job")
            if isinstance(raw_job, dict) and raw_job.get("job_id"):
                existing_jobs.add(UUID(str(raw_job["job_id"])))

            raw_lease = payload.get("lease")
            if isinstance(raw_lease, dict) and raw_lease.get("lease_id"):
                existing_leases.add(UUID(str(raw_lease["lease_id"])))

            raw_wakeup = payload.get("wakeup")
            if isinstance(raw_wakeup, dict) and raw_wakeup.get("wakeup_id"):
                existing_wakeups.add(UUID(str(raw_wakeup["wakeup_id"])))

        mission_rows = list(
            (await uow._session.execute(select(MissionORM))).scalars().all()
        )
        mission_by_id: Dict[UUID, Mission] = {}
        for row in mission_rows:
            mission = Mission(
                mission_id=row.mission_id,
                project_id=row.project_id,
                title=row.title,
                goal=row.goal,
                description=row.description,
                contract_id=row.contract_id,
                contract_version=row.contract_version,
                priority=row.priority,
                risk_class=row.risk_class,
                maximum_action_class=ActionClass(row.maximum_action_class),
                maximum_autonomy_level=row.maximum_autonomy_level,
                status=row.status,
                created_by=row.created_by,
                created_at=row.created_at,
                updated_at=row.updated_at,
                deadline=row.deadline,
                time_horizon=row.time_horizon,
                budget_ceiling=row.budget_ceiling,
                budget_spent=row.budget_spent,
                completion_criteria=row.completion_criteria or [],
                failure_criteria=row.failure_criteria or [],
                current_plan_id=row.current_plan_id,
                current_plan_version=row.current_plan_version,
                mission_version=row.mission_version,
                kernel_epoch_created=row.kernel_epoch_created,
            )
            mission_by_id[mission.mission_id] = mission
            if mission.mission_id in existing_missions:
                continue

            type_by_status = {
                "ACTIVE": EventType.MISSION_ACTIVATED,
                "PAUSED": EventType.MISSION_PAUSED,
                "CANCELLED": EventType.MISSION_CANCELLED,
                "COMPLETED": EventType.MISSION_COMPLETED,
                "FAILED": EventType.MISSION_FAILED,
            }
            event_type = type_by_status.get(mission.status.value, EventType.MISSION_CREATED)
            self.event_store.append_event(
                event_type=event_type,
                actor_id="legacy_sql_migration",
                payload={
                    "migration_source": "legacy_sql",
                    "mission": mission.model_dump(mode="json"),
                },
                project_id=mission.project_id,
                contract_version=mission.contract_version,
            )
            migrated["missions"] += 1

        checkpoint_rows = list(
            (await uow._session.execute(select(WorkerCheckpointORM))).scalars().all()
        )
        checkpoints_by_job: Dict[UUID, list[CheckpointRecord]] = {}
        for row in checkpoint_rows:
            checkpoint = CheckpointRecord(
                checkpoint_id=row.checkpoint_id,
                job_id=row.job_id,
                lease_generation=row.lease_generation,
                sequence=row.sequence,
                progress_pct=row.progress_pct,
                state_artifact_ref=row.state_artifact_ref,
                artifact_digest=row.artifact_digest,
                created_at=row.created_at,
            )
            checkpoints_by_job.setdefault(row.job_id, []).append(checkpoint)

        worker_rows = list(
            (await uow._session.execute(select(WorkerJobORM))).scalars().all()
        )
        for row in worker_rows:
            if row.job_id in existing_jobs:
                continue
            checkpoints = sorted(
                checkpoints_by_job.get(row.job_id, []),
                key=lambda checkpoint: checkpoint.sequence,
            )
            legacy_status = JobStatus(row.status)
            unsafe_active = legacy_status in {
                JobStatus.LEASED,
                JobStatus.RUNNING,
                JobStatus.CHECKPOINTING,
            }
            migrated_status = JobStatus.QUEUED if unsafe_active else legacy_status

            job = WorkerJob(
                job_id=row.job_id,
                project_id=row.project_id,
                task_id=row.task_id,
                job_type=row.job_type,
                status=migrated_status,
                lease_generation=row.lease_generation,
                kernel_epoch=row.kernel_epoch,
                payload_digest=row.payload_digest,
                idempotency_key=row.idempotency_key,
                payload=row.payload or {},
                checkpoints=checkpoints,
                last_checkpoint_seq=max(
                    (checkpoint.sequence for checkpoint in checkpoints),
                    default=0,
                ),
                completion_evidence=row.completion_evidence or {},
                created_at=row.created_at,
                completed_at=row.completed_at,
            )
            event_type = (
                EventType.WORKER_JOB_COMPLETED
                if job.status == JobStatus.COMPLETED
                else EventType.WORKER_JOB_CANCELLED
                if job.status == JobStatus.CANCELLED
                else EventType.WORKER_JOB_REQUEUED
                if unsafe_active
                else EventType.WORKER_JOB_ENQUEUED
            )
            self.event_store.append_event(
                event_type=event_type,
                actor_id="legacy_sql_migration",
                payload={
                    "migration_source": "legacy_sql",
                    "transition": (
                        "LEGACY_ACTIVE_LEASE_RECOVERED_TO_QUEUE"
                        if unsafe_active
                        else "LEGACY_SQL_IMPORT"
                    ),
                    "job": job.model_dump(mode="json"),
                },
                project_id=job.project_id,
                task_id=job.task_id,
            )
            migrated["worker_jobs"] += 1

        agent_rows = {
            row.agent_id: row
            for row in (
                await uow._session.execute(select(AgentCellORM))
            ).scalars().all()
        }
        lease_rows = list(
            (await uow._session.execute(select(AgentLeaseORM))).scalars().all()
        )
        for row in lease_rows:
            if row.lease_id in existing_leases:
                continue
            agent_row = agent_rows.get(row.agent_id)
            mission = mission_by_id.get(row.mission_id)
            if agent_row is None or mission is None:
                continue

            agent = AgentCell(
                agent_id=agent_row.agent_id,
                mission_id=agent_row.mission_id,
                role=agent_row.role,
                status=agent_row.status,
                assigned_task_ids=[UUID(str(item)) for item in (agent_row.assigned_task_ids or [])],
                agent_version=agent_row.agent_version,
                created_at=agent_row.created_at,
                expires_at=agent_row.expires_at,
                current_lease_id=agent_row.current_lease_id,
            )
            lease = AgentLease(
                lease_id=row.lease_id,
                agent_id=row.agent_id,
                mission_id=row.mission_id,
                task_scope=[UUID(str(item)) for item in (row.task_scope or [])],
                lease_generation=row.lease_generation,
                kernel_epoch=row.kernel_epoch,
                granted_at=row.granted_at,
                expires_at=row.expires_at,
                capability_ceiling=ActionClass(row.capability_ceiling),
                tool_scope=row.tool_scope or [],
                max_turns=row.max_turns,
                turns_used=row.turns_used,
                max_spend=row.max_spend,
                spend_used=row.spend_used,
                status=row.status,
            )
            task_id = lease.task_scope[0] if lease.task_scope else None
            self.event_store.append_event(
                event_type=EventType.AGENT_LEASE_GRANTED,
                actor_id="legacy_sql_migration",
                payload={
                    "migration_source": "legacy_sql",
                    "agent": agent.model_dump(mode="json"),
                    "lease": lease.model_dump(mode="json"),
                },
                project_id=mission.project_id,
                task_id=task_id,
                contract_version=mission.contract_version,
            )
            migrated["agent_leases"] += 1

        wakeup_rows = list(
            (await uow._session.execute(select(WakeupRecordORM))).scalars().all()
        )
        for row in wakeup_rows:
            if row.wakeup_id in existing_wakeups:
                continue
            mission = mission_by_id.get(row.mission_id)
            if mission is None:
                continue
            wakeup = WakeupRecord(
                wakeup_id=row.wakeup_id,
                mission_id=row.mission_id,
                task_id=row.task_id,
                trigger_type=row.trigger_type,
                trigger_condition=row.trigger_condition or {},
                due_at=row.due_at,
                created_at=row.created_at,
                fired_at=row.fired_at,
                status=row.status,
                idempotency_key=row.idempotency_key,
            )
            self.event_store.append_event(
                event_type=(
                    EventType.MISSION_WAKEUP_FIRED
                    if wakeup.status.value == "FIRED"
                    else EventType.MISSION_WAKEUP_SCHEDULED
                ),
                actor_id="legacy_sql_migration",
                payload={
                    "migration_source": "legacy_sql",
                    "mission": mission.model_dump(mode="json"),
                    "wakeup": wakeup.model_dump(mode="json"),
                },
                project_id=mission.project_id,
                task_id=wakeup.task_id,
                contract_version=mission.contract_version,
            )
            migrated["wakeups"] += 1

        return migrated

    async def _reconcile_sql_mission_projection(
        self,
        uow: UnitOfWork,
    ) -> int:
        """Upsert current canonical mission snapshots into the SQL read index."""
        mission_events = {
            EventType.MISSION_CREATED,
            EventType.MISSION_ACTIVATED,
            EventType.MISSION_PAUSED,
            EventType.MISSION_RESUMED,
            EventType.MISSION_CANCELLED,
            EventType.MISSION_COMPLETED,
            EventType.MISSION_FAILED,
            EventType.MISSION_WAKEUP_SCHEDULED,
            EventType.MISSION_WAKEUP_FIRED,
        }
        latest: Dict[UUID, Mission] = {}
        for event in self.event_store.get_all_events():
            if event.event_type not in mission_events:
                continue
            raw = (event.payload or {}).get("mission")
            if not isinstance(raw, dict):
                continue
            try:
                mission = Mission.model_validate(raw)
            except Exception:
                continue
            latest[mission.mission_id] = mission

        for mission in latest.values():
            project = await uow.projects.get_project(mission.project_id)
            if project is None:
                await uow.projects.create_project(
                    mission.project_id,
                    mission.title or f"Project {str(mission.project_id)[:8]}",
                )

            row = await uow.missions.get_mission(mission.mission_id)
            if row is None:
                await uow.missions.create_mission(mission)
                continue

            row.project_id = mission.project_id
            row.title = mission.title
            row.goal = mission.goal
            row.description = mission.description
            row.contract_id = mission.contract_id
            row.contract_version = mission.contract_version
            row.priority = mission.priority
            row.risk_class = mission.risk_class
            row.maximum_action_class = mission.maximum_action_class.value
            row.maximum_autonomy_level = mission.maximum_autonomy_level.value
            row.status = mission.status.value
            row.created_by = mission.created_by
            row.created_at = mission.created_at
            row.updated_at = mission.updated_at
            row.deadline = mission.deadline
            row.time_horizon = mission.time_horizon
            row.budget_ceiling = mission.budget_ceiling
            row.budget_spent = mission.budget_spent
            row.completion_criteria = mission.completion_criteria
            row.failure_criteria = mission.failure_criteria
            row.current_plan_id = mission.current_plan_id
            row.current_plan_version = mission.current_plan_version
            row.mission_version = mission.mission_version
            row.kernel_epoch_created = mission.kernel_epoch_created

        await uow._session.flush()
        return len(latest)

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
        mission_projection_rows = 0
        legacy_runtime_migrated = {
            "missions": 0,
            "worker_jobs": 0,
            "agent_leases": 0,
            "wakeups": 0,
        }

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
                    # validate any SQL event history, atomically initialize the
                    # empty journal, then import SQL-only runtime aggregates.
                    if self.event_store.event_count == 0:
                        self.event_store.load_verified_history(
                            sql_events,
                            sql_edges,
                            initialize_journal=True,
                        )
                        legacy_runtime_migrated = (
                            await self._migrate_legacy_sql_runtime_state_to_journal(uow)
                        )
                        legacy_sql_migrated = bool(
                            sql_events or any(legacy_runtime_migrated.values())
                        )
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
                    mission_projection_rows = (
                        await self._reconcile_sql_mission_projection(uow)
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
            "legacy_runtime_migrated": legacy_runtime_migrated,
            "unclean_shutdown_detected": unclean_shutdown,
            "events_rehydrated": self.event_store.event_count,
            "edges_rehydrated": len(self.event_store.get_all_edges()),
            "sql_projection_events": self.event_store.event_count,
            "sql_projection_edges": len(self.event_store.get_all_edges()),
            "sql_projection_missions": mission_projection_rows,
            "leases_fenced": leases_fenced,
            "workers_fenced": workers_fenced,
            "tasks_marked_recovery_required": tasks_recovered,
        }
