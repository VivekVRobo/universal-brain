"""
Universal Brain - Transactional Outbox Repository

Implements M6 Sections 18-21, 53-57:
Manages at-least-once transactional outbox records staged in the same
database transaction as domain mutations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.persistence.models import OutboxRecordORM
from universal_brain.persistence.repositories.base import BaseRepository


class OutboxRepository(BaseRepository[OutboxRecordORM]):
    """Manages transactional outbox records."""

    async def stage_event(
        self,
        event_id: UUID,
        topic: str,
        payload: Dict[str, Any],
        outbox_id: Optional[UUID] = None,
    ) -> OutboxRecordORM:
        """Stages an outbox record in the active transaction."""
        try:
            oid = outbox_id or uuid4()
            now = datetime.now(timezone.utc)
            record = OutboxRecordORM(
                outbox_id=oid,
                event_id=event_id,
                topic=topic,
                payload=payload,
                status="PENDING",
                attempts=0,
                created_at=now,
                available_at=now,
            )
            self.session.add(record)
            await self.session.flush()
            return record
        except Exception as e:
            raise self._translate_exception(e) from e

    async def claim_pending(self, batch_size: int = 50) -> List[OutboxRecordORM]:
        """Claims up to batch_size pending outbox items and marks them PROCESSING."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(OutboxRecordORM)
            .where(
                OutboxRecordORM.status == "PENDING",
                OutboxRecordORM.available_at <= now,
            )
            .order_by(OutboxRecordORM.created_at.asc())
            .limit(batch_size)
        )
        res = await self.session.execute(stmt)
        records = list(res.scalars().all())

        for rec in records:
            rec.status = "PROCESSING"
        await self.session.flush()
        return records

    async def mark_delivered(self, outbox_id: UUID) -> bool:
        """Marks an outbox record as successfully delivered."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(OutboxRecordORM)
            .where(OutboxRecordORM.outbox_id == outbox_id)
            .values(status="DELIVERED", delivered_at=now)
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return res.rowcount > 0

    async def mark_failed(self, outbox_id: UUID, error: str, max_retries: int = 5) -> bool:
        """Increments attempt count and backs off or transitions to DEAD_LETTER."""
        stmt = select(OutboxRecordORM).where(OutboxRecordORM.outbox_id == outbox_id)
        res = await self.session.execute(stmt)
        rec = res.scalar_one_or_none()
        if not rec:
            return False

        rec.attempts += 1
        rec.last_error = error

        if rec.attempts >= max_retries:
            rec.status = "DEAD_LETTER"
        else:
            rec.status = "PENDING"
            # Exponential backoff: 2^attempts seconds
            backoff_sec = 2 ** rec.attempts
            rec.available_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_sec)

        await self.session.flush()
        return True

    async def get_pending_count(self) -> int:
        """Returns the total number of pending or retryable outbox items."""
        stmt = select(func.count(OutboxRecordORM.outbox_id)).where(OutboxRecordORM.status == "PENDING")
        res = await self.session.execute(stmt)
        return int(res.scalar_one())
