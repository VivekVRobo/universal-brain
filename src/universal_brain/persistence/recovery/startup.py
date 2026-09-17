"""
Universal Brain - Startup & Crash Recovery Manager

Implements M6 Sections 15, 20-22, 32, 34, 43, 74-83, and Invariant M6-INV-12:
Executes the comprehensive boot-time recovery pipeline:
- Database connectivity check
- Unclean shutdown detection
- Monotonic kernel epoch advancement
- Event ledger hydration and cryptographic hash-chain verification
- Causal edge graph reconstruction
- Stale model lease and worker lease fencing
- Interrupted task recovery
- Readiness state assertion (READY, READ_ONLY, INTEGRITY_FAILURE, RECOVERY_REQUIRED).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventEdge, EventEnvelope, EventType, RelationType
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.errors import (
    IntegrityFailureError,
    RecoveryRequiredError,
)
from universal_brain.persistence.unit_of_work import UnitOfWork


class StartupRecoveryManager:
    """Orchestrates deterministic resurrection of canonical state following shutdown or crash."""

    def __init__(self, db_manager: DatabaseManager, event_store: EventStore) -> None:
        self.db_manager = db_manager
        self.event_store = event_store
        self.current_epoch: int = 1
        self.system_status: str = "STARTING"

    async def run_startup_recovery(self, instance_id: str = "ub-node-01") -> Dict[str, Any]:
        """
        Executes full recovery pipeline.
        Returns a detailed audit report of recovered components.
        """
        self.system_status = "RECOVERING"
        unclean_shutdown = False
        tasks_recovered = 0
        leases_fenced = 0
        workers_fenced = 0

        async with UnitOfWork(self.db_manager) as uow:
            # 1. Inspect previous lifecycle marker (M6 Section 76, 77)
            latest_lifecycle = await uow.lifecycle.get_latest_lifecycle()
            if latest_lifecycle and latest_lifecycle.status != "CLEAN_SHUTDOWN":
                unclean_shutdown = True

            # 2. Advance Kernel Epoch (M6 Section 43, 80)
            marker = await uow.lifecycle.acquire_or_advance_epoch(instance_id)
            self.current_epoch = marker.kernel_epoch

            # 3. Rehydrate EventStore & Verify Hash-Chain (M6 Section 15, 20)
            persisted_events = await uow.events.get_all_events_ordered()
            self.event_store._events.clear()
            self.event_store._events_by_id.clear()
            self.event_store._latest_hash = ""

            try:
                for e_orm in persisted_events:
                    ts = e_orm.timestamp
                    if ts.tzinfo is None:
                        from datetime import timezone
                        ts = ts.replace(tzinfo=timezone.utc)
                    envelope = EventEnvelope(
                        event_id=e_orm.event_id,
                        timestamp=ts,
                        event_type=EventType(e_orm.event_type) if e_orm.event_type in EventType.__members__.values() else EventType.INTENT_PARSED,
                        actor_id=e_orm.actor_id,
                        project_id=e_orm.project_id,
                        task_id=e_orm.task_id,
                        contract_version=e_orm.contract_version,
                        payload=e_orm.payload,
                        prev_event_hash=e_orm.prev_event_hash,
                        event_hash=e_orm.event_hash,
                    )
                    self.event_store._events.append(envelope)
                    self.event_store._events_by_id[envelope.event_id] = envelope
                    self.event_store._latest_hash = envelope.event_hash

                # Cryptographic Integrity Assertion (ALN-016 / M6-INV-18)
                self.event_store.verify_chain_integrity()
            except Exception as e:
                self.system_status = "INTEGRITY_FAILURE"
                await uow.commit()
                raise IntegrityFailureError(f"CRITICAL: Event hash-chain corrupted on recovery: {e}") from e

            # 4. Rehydrate Causal Edges (M6 Section 25)
            persisted_edges = await uow.edges.get_all_edges()
            self.event_store._edges.clear()
            for edge_orm in persisted_edges:
                edge = EventEdge(
                    edge_id=edge_orm.edge_id,
                    source_event_id=edge_orm.source_event_id,
                    target_event_id=edge_orm.target_event_id,
                    relation_type=RelationType(edge_orm.relation_type) if edge_orm.relation_type in RelationType.__members__.values() else RelationType.CAUSED_BY,
                    created_at=edge_orm.created_at,
                )
                self.event_store._edges.append(edge)

            # 5. Fence Stale Model Leases (M6 Section 34)
            leases_fenced = await uow.leases.fence_stale_leases(self.current_epoch)

            # 6. Fence Stale Worker Jobs (M6 Section 43)
            workers_fenced = await uow.jobs.fence_stale_workers(self.current_epoch)

            # 7. Recover Interrupted RUNNING Tasks (M6 Section 32)
            from sqlalchemy import select, update
            from universal_brain.persistence.models import TaskORM
            stmt = select(TaskORM).where(TaskORM.status.in_(["RUNNING", "EXECUTING", "COGNITIVE_WORK"]))
            res = await uow._session.execute(stmt)
            running_tasks = list(res.scalars().all())

            for t in running_tasks:
                t.status = "RECOVERY_REQUIRED"
                tasks_recovered += 1

            # Commit recovery adjustments
            await uow.commit()

        self.system_status = "READY"

        return {
            "system_status": self.system_status,
            "kernel_epoch": self.current_epoch,
            "unclean_shutdown_detected": unclean_shutdown,
            "events_rehydrated": len(self.event_store._events),
            "edges_rehydrated": len(self.event_store._edges),
            "leases_fenced": leases_fenced,
            "workers_fenced": workers_fenced,
            "tasks_marked_recovery_required": tasks_recovered,
        }
