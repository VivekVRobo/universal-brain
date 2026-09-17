"""
Universal Brain - Evidence Metadata Repository

Implements M6 Sections 47-52:
Persists cryptographic evidence records and supports artifact reachability queries
for reference-counted and reachability garbage collection.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.persistence.models import EvidenceORM
from universal_brain.persistence.repositories.base import BaseRepository


class EvidenceRepository(BaseRepository[EvidenceORM]):
    """Manages evidence metadata records."""

    async def save_evidence(
        self,
        evidence_id: UUID,
        task_id: UUID,
        evidence_type: str,
        digest: str,
        size_bytes: int,
        artifact_ref: Optional[str] = None,
        event_id: Optional[UUID] = None,
        verification_status: str = "VERIFIED",
        payload: Optional[Dict[str, Any]] = None,
    ) -> EvidenceORM:
        try:
            orm_ev = EvidenceORM(
                evidence_id=evidence_id,
                task_id=task_id,
                event_id=event_id,
                evidence_type=evidence_type,
                digest=digest,
                size_bytes=size_bytes,
                artifact_ref=artifact_ref,
                verification_status=verification_status,
                payload=payload or {},
            )
            self.session.add(orm_ev)
            await self.session.flush()
            return orm_ev
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_evidence(self, evidence_id: UUID) -> Optional[EvidenceORM]:
        stmt = select(EvidenceORM).where(EvidenceORM.evidence_id == evidence_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_evidence_for_task(self, task_id: UUID) -> List[EvidenceORM]:
        stmt = select(EvidenceORM).where(EvidenceORM.task_id == task_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_all_referenced_digests(self) -> Set[str]:
        """Returns set of all active evidence digests for reachability verification."""
        stmt = select(EvidenceORM.digest)
        res = await self.session.execute(stmt)
        return set(res.scalars().all())
