"""
Universal Brain - Worker Fabric & Checkpoint Repositories

Implements M6 Sections 41-43:
Durable persistence for remote worker jobs, monotonic lease_generation fencing tokens,
and monotonic progress checkpoints surviving host restarts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.persistence.models import WorkerCheckpointORM, WorkerJobORM
from universal_brain.persistence.repositories.base import BaseRepository
from universal_brain.tools.workers.schemas import CheckpointRecord, WorkerJob


class WorkerJobRepository(BaseRepository[WorkerJobORM]):
    """Manages worker job state and lease generations."""

    async def save_job(self, job: WorkerJob, kernel_epoch: int = 1) -> WorkerJobORM:
        try:
            orm_job = WorkerJobORM(
                job_id=job.job_id,
                project_id=job.project_id,
                task_id=job.task_id,
                job_type=job.job_type,
                status=job.status.value if hasattr(job.status, "value") else str(job.status),
                lease_generation=job.lease_generation,
                kernel_epoch=kernel_epoch,
                payload_digest=job.payload_digest,
                idempotency_key=job.idempotency_key,
                payload=job.payload,
                completion_evidence=job.completion_evidence,
                created_at=job.created_at,
                completed_at=job.completed_at,
            )
            self.session.add(orm_job)
            await self.session.flush()
            return orm_job
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_job(self, job_id: UUID) -> Optional[WorkerJobORM]:
        stmt = select(WorkerJobORM).where(WorkerJobORM.job_id == job_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> Optional[WorkerJobORM]:
        stmt = select(WorkerJobORM).where(WorkerJobORM.idempotency_key == key)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_job_lease(
        self,
        job_id: UUID,
        new_lease_generation: int,
        status: str = "LEASED",
        kernel_epoch: int = 1,
    ) -> bool:
        """Updates lease generation and epoch. Enforces monotonic increase."""
        stmt = (
            update(WorkerJobORM)
            .where(
                WorkerJobORM.job_id == job_id,
                WorkerJobORM.lease_generation < new_lease_generation,
            )
            .values(
                lease_generation=new_lease_generation,
                status=status,
                kernel_epoch=kernel_epoch,
            )
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return res.rowcount > 0

    async def complete_job(self, job_id: UUID, evidence: Dict[str, Any]) -> bool:
        now = datetime.now(timezone.utc)
        stmt = (
            update(WorkerJobORM)
            .where(WorkerJobORM.job_id == job_id)
            .values(status="COMPLETED", completion_evidence=evidence, completed_at=now)
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return res.rowcount > 0

    async def fence_stale_workers(self, current_epoch: int) -> int:
        """Fences all jobs leased under an earlier kernel epoch back to QUEUED."""
        stmt = (
            update(WorkerJobORM)
            .where(
                WorkerJobORM.kernel_epoch < current_epoch,
                WorkerJobORM.status.in_(["LEASED", "RUNNING", "CHECKPOINTING"]),
            )
            .values(status="QUEUED")
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return res.rowcount


class WorkerCheckpointRepository(BaseRepository[WorkerCheckpointORM]):
    """Manages intermediate worker progress checkpoints."""

    async def save_checkpoint(self, cp: CheckpointRecord) -> WorkerCheckpointORM:
        try:
            orm_cp = WorkerCheckpointORM(
                checkpoint_id=cp.checkpoint_id,
                job_id=cp.job_id,
                lease_generation=cp.lease_generation,
                sequence=cp.sequence,
                progress_pct=cp.progress_pct,
                state_artifact_ref=cp.state_artifact_ref,
                artifact_digest=cp.artifact_digest,
                created_at=cp.created_at,
            )
            self.session.add(orm_cp)
            await self.session.flush()
            return orm_cp
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_checkpoints_for_job(self, job_id: UUID) -> List[WorkerCheckpointORM]:
        stmt = select(WorkerCheckpointORM).where(WorkerCheckpointORM.job_id == job_id).order_by(WorkerCheckpointORM.sequence.asc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_latest_checkpoint(self, job_id: UUID) -> Optional[WorkerCheckpointORM]:
        stmt = select(WorkerCheckpointORM).where(WorkerCheckpointORM.job_id == job_id).order_by(WorkerCheckpointORM.sequence.desc()).limit(1)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()
