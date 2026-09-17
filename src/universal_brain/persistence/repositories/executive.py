"""
Universal Brain - Executive State Repositories

Implements M6 Sections 33-36:
Durable persistence for ephemeral model leases (fenced on kernel restart)
and model-independent cognitive handoff snapshots.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.executive.schemas import HandoffSnapshot, ModelLease
from universal_brain.persistence.models import HandoffSnapshotORM, ModelLeaseORM
from universal_brain.persistence.repositories.base import BaseRepository


class ModelLeaseRepository(BaseRepository[ModelLeaseORM]):
    """Manages ephemeral model lease persistence and epoch fencing."""

    async def save_lease(self, lease: ModelLease, kernel_epoch: int = 1) -> ModelLeaseORM:
        try:
            orm_lease = ModelLeaseORM(
                lease_id=lease.lease_id,
                project_id=lease.project_id,
                task_id=lease.task_id,
                provider_id=lease.provider_id,
                model_id=lease.model_id,
                status=lease.status.value if hasattr(lease.status, "value") else str(lease.status),
                kernel_epoch=kernel_epoch,
                granted_at=lease.granted_at,
                expires_at=lease.expires_at,
                metadata_payload=lease.model_dump(mode="json"),
            )
            self.session.add(orm_lease)
            await self.session.flush()
            return orm_lease
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_lease(self, lease_id: UUID) -> Optional[ModelLeaseORM]:
        stmt = select(ModelLeaseORM).where(ModelLeaseORM.lease_id == lease_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def revoke_lease(self, lease_id: UUID) -> bool:
        now = datetime.now(timezone.utc)
        stmt = (
            update(ModelLeaseORM)
            .where(ModelLeaseORM.lease_id == lease_id)
            .values(status="REVOKED", revoked_at=now)
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return res.rowcount > 0

    async def fence_stale_leases(self, current_epoch: int) -> int:
        """Fences all active leases issued under an earlier kernel epoch (M6 Section 34)."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(ModelLeaseORM)
            .where(
                ModelLeaseORM.kernel_epoch < current_epoch,
                ModelLeaseORM.status == "ACTIVE",
            )
            .values(status="REVOKED", revoked_at=now)
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return res.rowcount


class HandoffRepository(BaseRepository[HandoffSnapshotORM]):
    """Manages cognitive handoff snapshots."""

    async def save_snapshot(self, snapshot: HandoffSnapshot) -> HandoffSnapshotORM:
        try:
            orm_snapshot = HandoffSnapshotORM(
                snapshot_id=snapshot.handoff_id,
                project_id=snapshot.project_id,
                task_id=snapshot.task_id,
                task_version=snapshot.task_version,
                outgoing_model=snapshot.outgoing_model,
                incoming_model=snapshot.incoming_model,
                status="SNAPSHOT_VERIFIED",
                state_digest=snapshot.state_digest,
                payload=snapshot.model_dump(mode="json"),
            )
            self.session.add(orm_snapshot)
            await self.session.flush()
            return orm_snapshot
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_snapshot(self, snapshot_id: UUID) -> Optional[HandoffSnapshotORM]:
        stmt = select(HandoffSnapshotORM).where(HandoffSnapshotORM.snapshot_id == snapshot_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_status(self, snapshot_id: UUID, new_status: str) -> bool:
        stmt = (
            update(HandoffSnapshotORM)
            .where(HandoffSnapshotORM.snapshot_id == snapshot_id)
            .values(status=new_status)
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return res.rowcount > 0
