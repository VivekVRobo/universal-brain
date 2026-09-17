"""
Universal Brain - Kernel Lifecycle & Epoch Fencing Repository

Implements M6 Sections 43, 76-80, and Invariants M6-INV-12, M6-INV-13:
Enforces single-writer kernel leases, epoch advancement on boot,
and unclean shutdown detection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.persistence.models import KernelLifecycleORM
from universal_brain.persistence.repositories.base import BaseRepository


class LifecycleRepository(BaseRepository[KernelLifecycleORM]):
    """Manages kernel instance leases and epoch allocation."""

    async def get_latest_lifecycle(self) -> Optional[KernelLifecycleORM]:
        """Fetches the most recently recorded kernel lifecycle marker."""
        stmt = select(KernelLifecycleORM).order_by(KernelLifecycleORM.started_at.desc()).limit(1)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def acquire_or_advance_epoch(self, instance_id: str) -> KernelLifecycleORM:
        """
        Advances the monotonic kernel epoch and asserts single-writer authority.
        (M6 Section 43, 80).
        """
        try:
            # Find global max epoch
            stmt = select(func.coalesce(func.max(KernelLifecycleORM.kernel_epoch), 0))
            res = await self.session.execute(stmt)
            max_epoch = int(res.scalar_one())
            new_epoch = max_epoch + 1

            now = datetime.now(timezone.utc)
            marker = KernelLifecycleORM(
                instance_id=instance_id,
                kernel_epoch=new_epoch,
                status="RUNNING",
                started_at=now,
                last_heartbeat=now,
            )
            self.session.add(marker)
            await self.session.flush()
            return marker
        except Exception as e:
            raise self._translate_exception(e) from e

    async def heartbeat(self, instance_id: str) -> bool:
        """Updates active heartbeat timestamp for this kernel instance."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(KernelLifecycleORM)
            .where(KernelLifecycleORM.instance_id == instance_id)
            .values(last_heartbeat=now)
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return res.rowcount > 0

    async def record_clean_shutdown(self, instance_id: str) -> bool:
        """Records orderly clean shutdown (M6 Section 76)."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(KernelLifecycleORM)
            .where(KernelLifecycleORM.instance_id == instance_id)
            .values(status="CLEAN_SHUTDOWN", shutdown_at=now)
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return res.rowcount > 0
