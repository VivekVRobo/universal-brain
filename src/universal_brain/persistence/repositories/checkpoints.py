"""
Universal Brain - Workspace Checkpoint Repository

Implements M6 Sections 44-46:
Durable persistence for M5 reversible execution checkpoints and digest proofs.
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.persistence.models import WorkspaceCheckpointORM
from universal_brain.persistence.repositories.base import BaseRepository
from universal_brain.tools.sandbox.schemas import WorkspaceCheckpoint


class WorkspaceCheckpointRepository(BaseRepository[WorkspaceCheckpointORM]):
    """Manages filesystem transaction checkpoints."""

    async def save_checkpoint(self, cp: WorkspaceCheckpoint) -> WorkspaceCheckpointORM:
        try:
            orm_cp = WorkspaceCheckpointORM(
                checkpoint_id=cp.checkpoint_id,
                workspace_id=cp.workspace_id,
                task_id=cp.task_id,
                operation_type=cp.operation_type.value if hasattr(cp.operation_type, "value") else str(cp.operation_type),
                checkpoint_digest=cp.checkpoint_digest,
                reversibility_class=cp.reversibility_class.value if hasattr(cp.reversibility_class, "value") else str(cp.reversibility_class),
                status="READY",
                targets=cp.targets,
                pre_hashes=cp.pre_hashes,
                expected_post_hashes=cp.expected_post_hashes,
                created_at=cp.created_at,
            )
            self.session.add(orm_cp)
            await self.session.flush()
            return orm_cp
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_checkpoint(self, checkpoint_id: UUID) -> Optional[WorkspaceCheckpointORM]:
        stmt = select(WorkspaceCheckpointORM).where(WorkspaceCheckpointORM.checkpoint_id == checkpoint_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_checkpoints_for_workspace(self, workspace_id: UUID) -> List[WorkspaceCheckpointORM]:
        stmt = select(WorkspaceCheckpointORM).where(WorkspaceCheckpointORM.workspace_id == workspace_id).order_by(WorkspaceCheckpointORM.created_at.asc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
