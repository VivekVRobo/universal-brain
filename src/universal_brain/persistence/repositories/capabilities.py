"""
Universal Brain - Capability Authorization Repository

Implements M6 Sections 37-40:
Persists capability grant records (excluding signing secrets), tracks revocations,
and prevents expired or revoked tokens from regaining active runtime authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.kernel.capability import CapabilityToken
from universal_brain.persistence.models import CapabilityGrantORM
from universal_brain.persistence.repositories.base import BaseRepository


class CapabilityRepository(BaseRepository[CapabilityGrantORM]):
    """Durable ledger of issued and revoked capability tokens."""

    async def save_grant(self, token: CapabilityToken) -> CapabilityGrantORM:
        """Persists authorization record for an issued capability token."""
        try:
            grant = CapabilityGrantORM(
                token_id=token.token_id,
                project_id=token.project_id,
                task_id=token.task_id,
                contract_version=token.contract_version,
                action_class=token.action_class.value if hasattr(token.action_class, "value") else str(token.action_class),
                target_resource=token.target_resource,
                allowed_operations=token.allowed_operations,
                signature=token.signature,
                status="ACTIVE",
                issued_at=token.issued_at,
                expires_at=token.expires_at,
            )
            self.session.add(grant)
            await self.session.flush()
            return grant
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_grant(self, token_id: UUID) -> Optional[CapabilityGrantORM]:
        stmt = select(CapabilityGrantORM).where(CapabilityGrantORM.token_id == token_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def revoke_grant(self, token_id: UUID) -> bool:
        """Durably revokes a capability grant."""
        try:
            now = datetime.now(timezone.utc)
            stmt = (
                update(CapabilityGrantORM)
                .where(CapabilityGrantORM.token_id == token_id)
                .values(status="REVOKED", revoked_at=now)
            )
            res = await self.session.execute(stmt)
            await self.session.flush()
            return res.rowcount > 0
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_valid_grants(self, project_id: UUID, current_time: Optional[datetime] = None) -> List[CapabilityGrantORM]:
        """Fetches active, unexpired, and unrevoked grants for a project."""
        now = current_time or datetime.now(timezone.utc)
        stmt = select(CapabilityGrantORM).where(
            CapabilityGrantORM.project_id == project_id,
            CapabilityGrantORM.status == "ACTIVE",
            CapabilityGrantORM.expires_at > now,
            CapabilityGrantORM.revoked_at.is_(None),
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
