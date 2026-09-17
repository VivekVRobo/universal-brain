"""
Universal Brain - Project Repository

Implements M6 Section 7 & 12:
Manages project state, versioning, and contract version counters.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.persistence.models import ProjectORM
from universal_brain.persistence.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[ProjectORM]):
    """Manages project persistence."""

    async def create_project(self, project_id: UUID, title: str) -> ProjectORM:
        try:
            proj = ProjectORM(
                project_id=project_id,
                title=title,
                status="ACTIVE",
                current_contract_version=0,
                version=1,
            )
            self.session.add(proj)
            await self.session.flush()
            return proj
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_project(self, project_id: UUID) -> Optional[ProjectORM]:
        stmt = select(ProjectORM).where(ProjectORM.project_id == project_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_contract_version(self, project_id: UUID, new_version: int) -> bool:
        stmt = (
            update(ProjectORM)
            .where(ProjectORM.project_id == project_id)
            .values(current_contract_version=new_version, version=ProjectORM.version + 1)
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return res.rowcount > 0
