"""
Universal Brain - Event & Causal Edge Repositories

Implements M6 Sections 16-25:
Persists immutable event ledger entries with monotonic sequence counters
and causal relationship edges.
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.kernel.events import EventEnvelope, RelationType
from universal_brain.persistence.models import EventEdgeORM, EventORM
from universal_brain.persistence.repositories.base import BaseRepository


class EventRepository(BaseRepository[EventORM]):
    """Durable repository for EventStore ledger."""

    async def allocate_next_sequence(self) -> int:
        """Monotonically allocates next integer sequence for events."""
        stmt = select(func.coalesce(func.max(EventORM.sequence), 0) + 1)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def append_event(self, envelope: EventEnvelope, sequence: Optional[int] = None) -> EventORM:
        """Persists a canonical event envelope."""
        try:
            seq = sequence if sequence is not None else await self.allocate_next_sequence()
            orm_event = EventORM(
                event_id=envelope.event_id,
                sequence=seq,
                timestamp=envelope.timestamp,
                event_type=envelope.event_type.value if hasattr(envelope.event_type, "value") else str(envelope.event_type),
                actor_id=envelope.actor_id,
                project_id=envelope.project_id,
                task_id=envelope.task_id,
                contract_version=envelope.contract_version,
                payload=envelope.payload,
                prev_event_hash=envelope.prev_event_hash,
                event_hash=envelope.event_hash,
                schema_version=getattr(envelope, "schema_version", 1),
            )
            self.session.add(orm_event)
            await self.session.flush()
            return orm_event
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_event(self, event_id: UUID) -> Optional[EventORM]:
        stmt = select(EventORM).where(EventORM.event_id == event_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_all_events_ordered(self) -> List[EventORM]:
        stmt = select(EventORM).order_by(EventORM.sequence.asc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_events_by_project(self, project_id: UUID) -> List[EventORM]:
        stmt = select(EventORM).where(EventORM.project_id == project_id).order_by(EventORM.sequence.asc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_latest_event(self) -> Optional[EventORM]:
        stmt = select(EventORM).order_by(EventORM.sequence.desc()).limit(1)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()


class EventEdgeRepository(BaseRepository[EventEdgeORM]):
    """Durable repository for causal DAG edges."""

    async def add_edge(
        self,
        edge_id: UUID,
        source_event_id: UUID,
        target_event_id: UUID,
        relation_type: str,
    ) -> EventEdgeORM:
        try:
            orm_edge = EventEdgeORM(
                edge_id=edge_id,
                source_event_id=source_event_id,
                target_event_id=target_event_id,
                relation_type=relation_type,
            )
            self.session.add(orm_edge)
            await self.session.flush()
            return orm_edge
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_all_edges(self) -> List[EventEdgeORM]:
        stmt = select(EventEdgeORM).order_by(EventEdgeORM.created_at.asc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_edges_for_event(self, event_id: UUID) -> List[EventEdgeORM]:
        stmt = select(EventEdgeORM).where(
            (EventEdgeORM.source_event_id == event_id) | (EventEdgeORM.target_event_id == event_id)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
