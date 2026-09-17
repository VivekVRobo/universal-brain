"""
Universal Brain - Alignment Contract Repository

Implements M6 Sections 26-28:
Persists immutable contract versions and authoritative active pointers.
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.alignment.contract import AlignmentContract
from universal_brain.persistence.models import (
    ActiveContractPointerORM,
    AlignmentContractORM,
)
from universal_brain.persistence.repositories.base import BaseRepository


class ContractRepository(BaseRepository[AlignmentContractORM]):
    """Manages immutable contract revisions and active contract binding."""

    async def store_contract_version(
        self,
        contract: AlignmentContract,
        project_id: Optional[UUID] = None,
    ) -> AlignmentContractORM:
        """Saves a new immutable version of an AlignmentContract."""
        try:
            pid = project_id or getattr(contract, "project_id", None) or uuid4()
            if hasattr(contract, "calculate_digest"):
                digest = contract.calculate_digest()
            else:
                import hashlib
                digest = hashlib.sha256(contract.model_dump_json().encode("utf-8")).hexdigest()

            orm_contract = AlignmentContractORM(
                contract_id=contract.contract_id,
                project_id=pid,
                version=contract.version,
                status="ACTIVE",
                contract_digest=digest,
                contract_data=contract.model_dump(mode="json"),
            )
            self.session.add(orm_contract)
            await self.session.flush()
            return orm_contract
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_contract_by_version(self, project_id: UUID, version: int) -> Optional[AlignmentContractORM]:
        stmt = select(AlignmentContractORM).where(
            AlignmentContractORM.project_id == project_id,
            AlignmentContractORM.version == version,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_latest_version(self, project_id: UUID) -> Optional[AlignmentContractORM]:
        stmt = select(AlignmentContractORM).where(
            AlignmentContractORM.project_id == project_id
        ).order_by(AlignmentContractORM.version.desc()).limit(1)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def set_active_contract(self, project_id: UUID, contract_id: UUID, version: int) -> ActiveContractPointerORM:
        """Updates the authoritative active contract pointer for a project."""
        try:
            stmt = select(ActiveContractPointerORM).where(ActiveContractPointerORM.project_id == project_id)
            res = await self.session.execute(stmt)
            pointer = res.scalar_one_or_none()

            if pointer:
                pointer.active_contract_id = contract_id
                pointer.active_version = version
            else:
                pointer = ActiveContractPointerORM(
                    project_id=project_id,
                    active_contract_id=contract_id,
                    active_version=version,
                )
                self.session.add(pointer)

            await self.session.flush()
            return pointer
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_active_contract(self, project_id: UUID) -> Optional[AlignmentContractORM]:
        """Fetches the active contract version for a project."""
        stmt = select(ActiveContractPointerORM).where(ActiveContractPointerORM.project_id == project_id)
        res = await self.session.execute(stmt)
        pointer = res.scalar_one_or_none()
        if not pointer:
            return None
        return await self.get_contract_by_version(project_id, pointer.active_version)
