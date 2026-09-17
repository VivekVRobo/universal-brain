"""Replayable ephemeral-worker job queue.

Workers are ephemeral; job state is not. Every job lifecycle transition is
durable in the canonical EventStore before the in-memory queue projection changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from universal_brain.kernel.errors import CapabilityDeniedError, UniversalBrainError
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType
from universal_brain.tools.workers.auth import WorkerAuthService
from universal_brain.tools.workers.schemas import (
    CheckpointRecord,
    JobStatus,
    WorkerJob,
    WorkerLease,
    WorkerRegistration,
)


class FencedLeaseError(UniversalBrainError):
    pass


class CheckpointSequenceError(UniversalBrainError):
    pass


_WORKER_JOB_EVENTS = {
    EventType.WORKER_JOB_ENQUEUED,
    EventType.WORKER_JOB_LEASED,
    EventType.WORKER_JOB_PROGRESS,
    EventType.WORKER_JOB_COMPLETED,
    EventType.WORKER_JOB_CANCELLED,
    EventType.WORKER_JOB_REQUEUED,
}


class EphemeralJobQueue:
    """Pull-based worker coordination with canonical durable job projections."""

    def __init__(
        self,
        auth_service: Optional[WorkerAuthService] = None,
        event_store: Optional[EventStore] = None,
        kernel_epoch: int = 1,
    ) -> None:
        self._workers: Dict[str, WorkerRegistration] = {}
        self._jobs: Dict[UUID, WorkerJob] = {}
        self._completed_idempotency_keys: Dict[str, UUID] = {}
        self.auth_service = auth_service or WorkerAuthService()
        self.event_store = event_store
        self.kernel_epoch = kernel_epoch
        if self.event_store is not None:
            self.rehydrate_from_events()

    def rehydrate_from_events(self) -> None:
        self._jobs.clear()
        self._completed_idempotency_keys.clear()
        if self.event_store is None:
            return

        for event in self.event_store.get_all_events():
            if event.event_type not in _WORKER_JOB_EVENTS:
                continue
            raw_job = event.payload.get("job")
            if not isinstance(raw_job, dict):
                continue
            job = WorkerJob.model_validate(raw_job)
            self._jobs[job.job_id] = job
            if job.status == JobStatus.COMPLETED and job.idempotency_key:
                self._completed_idempotency_keys[job.idempotency_key] = job.job_id

    def _commit_job(self, event_type: EventType, job: WorkerJob, transition: str) -> WorkerJob:
        if self.event_store is not None:
            self.event_store.append_event(
                event_type=event_type,
                actor_id="worker_queue",
                payload={
                    "transition": transition,
                    "job": job.model_dump(mode="json"),
                },
                project_id=job.project_id,
                task_id=job.task_id,
            )

        existing = self._jobs.get(job.job_id)
        if existing is not None and existing is not job:
            # Preserve public object identity for callers holding a job reference,
            # but mutate it only after the canonical journal commit has succeeded.
            for field_name in WorkerJob.model_fields:
                setattr(existing, field_name, getattr(job, field_name))
            committed = existing
        else:
            committed = job

        self._jobs[job.job_id] = committed
        if committed.status == JobStatus.COMPLETED and committed.idempotency_key:
            self._completed_idempotency_keys[committed.idempotency_key] = committed.job_id
        return committed

    def get_job(self, job_id: UUID) -> Optional[WorkerJob]:
        return self._jobs.get(job_id)

    def register_worker(
        self,
        worker_id: str,
        worker_type: str,
        capabilities: Optional[Dict[str, Any]] = None,
        session_id: Optional[UUID] = None,
    ) -> WorkerRegistration:
        """Worker process registration remains ephemeral by design."""
        registration = WorkerRegistration(
            worker_id=worker_id,
            worker_session_id=session_id or uuid4(),
            worker_type=worker_type,
            capabilities=capabilities or {},
        )
        self._workers[worker_id] = registration
        return registration

    def enqueue_job(
        self,
        project_id: UUID,
        task_id: UUID,
        job_type: str,
        payload: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> WorkerJob:
        if idempotency_key and idempotency_key in self._completed_idempotency_keys:
            return self._jobs[self._completed_idempotency_keys[idempotency_key]]

        job = WorkerJob(
            project_id=project_id,
            task_id=task_id,
            job_type=job_type,
            payload=payload,
            idempotency_key=idempotency_key,
            kernel_epoch=self.kernel_epoch,
        )
        job = job.model_copy(update={"payload_digest": job.compute_payload_digest()})
        return self._commit_job(EventType.WORKER_JOB_ENQUEUED, job, "ENQUEUED")

    def poll_and_lease(
        self,
        worker_id: str,
        session_id: UUID,
        lease_duration_seconds: int = 600,
    ) -> Optional[Tuple[WorkerJob, WorkerLease]]:
        worker = self._workers.get(worker_id)
        if not worker:
            raise CapabilityDeniedError(f"Worker '{worker_id}' is not registered.")
        if worker.worker_session_id != session_id:
            raise CapabilityDeniedError(
                f"Worker session mismatch for '{worker_id}'."
            )

        worker.last_heartbeat = datetime.now(timezone.utc)
        target_job = next(
            (job for job in self._jobs.values() if job.status == JobStatus.QUEUED),
            None,
        )
        if target_job is None:
            return None

        generation = target_job.lease_generation + 1
        now = datetime.now(timezone.utc)
        lease = WorkerLease(
            job_id=target_job.job_id,
            worker_id=worker_id,
            worker_session_id=session_id,
            lease_generation=generation,
            leased_at=now,
            expires_at=now + timedelta(seconds=lease_duration_seconds),
            last_heartbeat=now,
        )
        lease = lease.model_copy(
            update={
                "lease_token": self.auth_service.generate_job_lease_token(
                    worker_id=worker_id,
                    session_id=str(session_id),
                    job_id=str(target_job.job_id),
                    lease_generation=generation,
                    kernel_epoch=1,
                    body_digest="*",
                    ttl_seconds=lease_duration_seconds,
                )
            }
        )

        updated = target_job.model_copy(
            update={
                "lease_generation": generation,
                "kernel_epoch": self.kernel_epoch,
                "current_lease": lease,
                "status": JobStatus.LEASED,
            }
        )
        committed = self._commit_job(EventType.WORKER_JOB_LEASED, updated, "LEASED")
        return committed, committed.current_lease

    def record_progress(
        self,
        job_id: UUID,
        worker_id: str,
        lease_generation: int,
        sequence: int,
        progress_pct: float,
        state_artifact_ref: Optional[str] = None,
        artifact_digest: Optional[str] = None,
        lease_token: Optional[str] = None,
    ) -> CheckpointRecord:
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found.")

        if lease_token:
            self.auth_service.verify_job_lease_token(
                token=lease_token,
                expected_worker_id=worker_id,
                expected_job_id=str(job_id),
                expected_lease_generation=lease_generation,
                expected_session_id=(
                    str(job.current_lease.worker_session_id)
                    if job.current_lease
                    else None
                ),
            )

        if (
            lease_generation != job.lease_generation
            or not job.current_lease
            or job.current_lease.is_fenced
        ):
            raise FencedLeaseError(
                f"FENCED_LEASE: Stale worker '{worker_id}' with generation "
                f"{lease_generation} rejected. Active generation is {job.lease_generation}."
            )
        if job.current_lease.worker_id != worker_id:
            raise CapabilityDeniedError(
                f"Worker '{worker_id}' does not own active lease for job '{job_id}'."
            )
        if sequence <= job.last_checkpoint_seq:
            raise CheckpointSequenceError(
                f"Checkpoint sequence regression: received {sequence} "
                f"<= last {job.last_checkpoint_seq}."
            )

        now = datetime.now(timezone.utc)
        checkpoint = CheckpointRecord(
            job_id=job_id,
            lease_generation=lease_generation,
            sequence=sequence,
            progress_pct=progress_pct,
            state_artifact_ref=state_artifact_ref,
            artifact_digest=artifact_digest,
            created_at=now,
        )
        lease = job.current_lease.model_copy(update={"last_heartbeat": now})
        updated = job.model_copy(
            update={
                "current_lease": lease,
                "status": JobStatus.RUNNING,
                "checkpoints": [*job.checkpoints, checkpoint],
                "last_checkpoint_seq": sequence,
            }
        )
        self._commit_job(EventType.WORKER_JOB_PROGRESS, updated, "PROGRESS")
        return checkpoint

    def fence_stale_epoch(self, current_epoch: int) -> List[UUID]:
        """Fence active jobs leased by an older kernel epoch in canonical state."""
        self.kernel_epoch = current_epoch
        fenced_jobs: List[UUID] = []
        for job in list(self._jobs.values()):
            if job.status not in {
                JobStatus.LEASED,
                JobStatus.RUNNING,
                JobStatus.CHECKPOINTING,
            }:
                continue
            if job.kernel_epoch >= current_epoch:
                continue
            fenced_lease = (
                job.current_lease.model_copy(update={"is_fenced": True})
                if job.current_lease is not None
                else None
            )
            updated = job.model_copy(
                update={
                    "current_lease": fenced_lease,
                    "status": JobStatus.QUEUED,
                }
            )
            self._commit_job(
                EventType.WORKER_JOB_REQUEUED,
                updated,
                "KERNEL_EPOCH_FENCED",
            )
            fenced_jobs.append(job.job_id)
        return fenced_jobs

    def reap_stale_leases(
        self,
        current_time: Optional[datetime] = None,
    ) -> List[UUID]:
        now = current_time or datetime.now(timezone.utc)
        reaped: List[UUID] = []

        for job in list(self._jobs.values()):
            if job.status not in {
                JobStatus.LEASED,
                JobStatus.RUNNING,
                JobStatus.CHECKPOINTING,
            }:
                continue
            if not job.current_lease or not job.current_lease.is_expired(now):
                continue

            fenced = job.current_lease.model_copy(update={"is_fenced": True})
            updated = job.model_copy(
                update={
                    "current_lease": fenced,
                    "status": JobStatus.QUEUED,
                }
            )
            self._commit_job(EventType.WORKER_JOB_REQUEUED, updated, "LEASE_EXPIRED_REQUEUED")
            reaped.append(job.job_id)

        return reaped

    def cancel_job(self, job_id: UUID) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.status in {
            JobStatus.COMPLETED,
            JobStatus.CANCELLED,
            JobStatus.REJECTED_RESULT,
        }:
            return False

        fenced = (
            job.current_lease.model_copy(update={"is_fenced": True})
            if job.current_lease is not None
            else None
        )
        updated = job.model_copy(
            update={
                "current_lease": fenced,
                "status": JobStatus.CANCELLED,
                "completed_at": datetime.now(timezone.utc),
            }
        )
        self._commit_job(EventType.WORKER_JOB_CANCELLED, updated, "CANCELLED")
        return True

    def complete_job(
        self,
        job_id: UUID,
        worker_id: str,
        lease_generation: int,
        completion_evidence: Dict[str, Any],
        idempotency_key: Optional[str] = None,
        lease_token: Optional[str] = None,
    ) -> WorkerJob:
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found.")

        if job.status == JobStatus.COMPLETED:
            if idempotency_key and job.idempotency_key == idempotency_key:
                return job

        if lease_token:
            self.auth_service.verify_job_lease_token(
                token=lease_token,
                expected_worker_id=worker_id,
                expected_job_id=str(job_id),
                expected_lease_generation=lease_generation,
                expected_session_id=(
                    str(job.current_lease.worker_session_id)
                    if job.current_lease
                    else None
                ),
            )

        if (
            lease_generation != job.lease_generation
            or not job.current_lease
            or job.current_lease.is_fenced
        ):
            raise FencedLeaseError(
                f"Cannot complete job with fenced/stale lease generation "
                f"{lease_generation}. Active is {job.lease_generation}."
            )
        if job.current_lease.worker_id != worker_id:
            raise CapabilityDeniedError(
                f"Worker '{worker_id}' is not the current lease holder."
            )

        updated = job.model_copy(
            update={
                "status": JobStatus.COMPLETED,
                "completion_evidence": completion_evidence,
                "completed_at": datetime.now(timezone.utc),
            }
        )
        return self._commit_job(EventType.WORKER_JOB_COMPLETED, updated, "COMPLETED")
