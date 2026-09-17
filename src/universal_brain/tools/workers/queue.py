"""
Universal Brain - Ephemeral Worker Job Queue Engine

Implements M5 Sections 43, 49-60 and Invariants M5-INV-08, M5-INV-09, M5-INV-10, M5-INV-11:
Pull-based job queue with monotonic lease_generation fencing tokens,
checkpoint resumption on worker disconnect, and idempotent completion.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from universal_brain.kernel.errors import CapabilityDeniedError, UniversalBrainError
from universal_brain.tools.workers.auth import WorkerAuthService
from universal_brain.tools.workers.schemas import (
    CheckpointRecord,
    JobStatus,
    WorkerJob,
    WorkerLease,
    WorkerRegistration,
)


class FencedLeaseError(UniversalBrainError):
    """Raised when a stale/zombie worker attempts to update a job with an older lease generation."""
    pass


class CheckpointSequenceError(UniversalBrainError):
    """Raised when a worker checkpoint regresses or breaks monotonicity."""
    pass


class EphemeralJobQueue:
    """Authoritative pull-based queue coordinating untrusted remote workers."""

    def __init__(self, auth_service: Optional[WorkerAuthService] = None) -> None:
        self._workers: Dict[str, WorkerRegistration] = {}
        self._jobs: Dict[UUID, WorkerJob] = {}
        self._completed_idempotency_keys: Dict[str, UUID] = {}
        self.auth_service = auth_service or WorkerAuthService()

    def get_job(self, job_id: UUID) -> Optional[WorkerJob]:
        """Return authoritative job state for verification/supervision (REQ-ENG-011)."""
        return self._jobs.get(job_id)

    def register_worker(
        self,
        worker_id: str,
        worker_type: str,
        capabilities: Optional[Dict[str, Any]] = None,
        session_id: Optional[UUID] = None,
    ) -> WorkerRegistration:
        """Registers a remote ephemeral worker instance."""
        reg = WorkerRegistration(
            worker_id=worker_id,
            worker_session_id=session_id or uuid4(),
            worker_type=worker_type,
            capabilities=capabilities or {},
        )
        self._workers[worker_id] = reg
        return reg

    def enqueue_job(
        self,
        project_id: UUID,
        task_id: UUID,
        job_type: str,
        payload: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> WorkerJob:
        """Enqueues a new work batch into the queue."""
        if idempotency_key and idempotency_key in self._completed_idempotency_keys:
            existing_id = self._completed_idempotency_keys[idempotency_key]
            return self._jobs[existing_id]

        job = WorkerJob(
            project_id=project_id,
            task_id=task_id,
            job_type=job_type,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        job.payload_digest = job.compute_payload_digest()
        self._jobs[job.job_id] = job
        return job

    def poll_and_lease(
        self,
        worker_id: str,
        session_id: UUID,
        lease_duration_seconds: int = 600,
    ) -> Optional[Tuple[WorkerJob, WorkerLease]]:
        """
        Worker polls for next available job.
        Atomically increments lease_generation (fencing token) and grants lease.
        """
        worker = self._workers.get(worker_id)
        if not worker:
            raise CapabilityDeniedError(f"Worker '{worker_id}' is not registered.")

        worker.last_heartbeat = datetime.now(timezone.utc)

        # Find first QUEUED job
        target_job: Optional[WorkerJob] = None
        for job in self._jobs.values():
            if job.status == JobStatus.QUEUED:
                target_job = job
                break

        if not target_job:
            return None

        # Increment Fencing Token (M5 Section 50)
        target_job.lease_generation += 1
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=lease_duration_seconds)

        lease = WorkerLease(
            job_id=target_job.job_id,
            worker_id=worker_id,
            worker_session_id=session_id,
            lease_generation=target_job.lease_generation,
            leased_at=now,
            expires_at=expires_at,
            last_heartbeat=now,
        )
        # Mint Job Lease Token bound to worker, session, job, and generation
        lease.lease_token = self.auth_service.generate_job_lease_token(
            worker_id=worker_id,
            session_id=str(session_id),
            job_id=str(target_job.job_id),
            lease_generation=target_job.lease_generation,
            kernel_epoch=1,
            body_digest="*",
            ttl_seconds=lease_duration_seconds,
        )

        target_job.current_lease = lease
        target_job.status = JobStatus.LEASED
        return target_job, lease

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
        """
        Records intermediate progress checkpoint from active worker.
        Enforces fencing token, lease token validation, and sequence monotonicity.
        """
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found.")

        # Lease Token Cryptographic Verification (Gate S1)
        if lease_token:
            self.auth_service.verify_job_lease_token(
                token=lease_token,
                expected_worker_id=worker_id,
                expected_job_id=str(job_id),
                expected_lease_generation=lease_generation,
                expected_session_id=str(job.current_lease.worker_session_id) if job.current_lease else None,
            )

        # Fencing Token Gate (M5-INV-09)
        if lease_generation != job.lease_generation or not job.current_lease or job.current_lease.is_fenced:
            raise FencedLeaseError(
                f"FENCED_LEASE: Stale worker '{worker_id}' with generation {lease_generation} "
                f"rejected. Active generation is {job.lease_generation}."
            )

        if job.current_lease.worker_id != worker_id:
            raise CapabilityDeniedError(f"Worker '{worker_id}' does not own active lease for job '{job_id}'.")

        # Monotonic Sequence Check (M5 Section 55)
        if sequence <= job.last_checkpoint_seq:
            raise CheckpointSequenceError(
                f"Checkpoint sequence regression: received {sequence} <= last {job.last_checkpoint_seq}."
            )

        now = datetime.now(timezone.utc)
        job.current_lease.last_heartbeat = now
        job.status = JobStatus.RUNNING

        checkpoint = CheckpointRecord(
            job_id=job_id,
            lease_generation=lease_generation,
            sequence=sequence,
            progress_pct=progress_pct,
            state_artifact_ref=state_artifact_ref,
            artifact_digest=artifact_digest,
            created_at=now,
        )

        job.checkpoints.append(checkpoint)
        job.last_checkpoint_seq = sequence
        return checkpoint

    def reap_stale_leases(self, current_time: Optional[datetime] = None) -> List[UUID]:
        """
        Detects expired worker leases, fences the old lease, and re-queues
        the job preserving the latest verified checkpoint (M5 Section 59).
        """
        now = current_time or datetime.now(timezone.utc)
        reaped = []

        for job in self._jobs.values():
            if job.status in [JobStatus.LEASED, JobStatus.RUNNING, JobStatus.CHECKPOINTING]:
                if job.current_lease and job.current_lease.is_expired(now):
                    # Fence the old lease
                    job.current_lease.is_fenced = True
                    # Re-queue job from last verified checkpoint
                    job.status = JobStatus.QUEUED
                    reaped.append(job.job_id)

        return reaped

    def cancel_job(self, job_id: UUID) -> bool:
        """Cancel a non-terminal job and fence any active lease."""
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.status in {
            JobStatus.COMPLETED,
            JobStatus.CANCELLED,
            JobStatus.REJECTED_RESULT,
        }:
            return False
        if job.current_lease is not None:
            job.current_lease.is_fenced = True
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(timezone.utc)
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
        """
        Submits job completion claim and verifies lease validity.
        (M5 Section 57, 58).
        """
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found.")

        # Lease Token Cryptographic Verification (Gate S1)
        if lease_token:
            self.auth_service.verify_job_lease_token(
                token=lease_token,
                expected_worker_id=worker_id,
                expected_job_id=str(job_id),
                expected_lease_generation=lease_generation,
                expected_session_id=str(job.current_lease.worker_session_id) if job.current_lease else None,
            )

        # Check Idempotency
        if job.status == JobStatus.COMPLETED:
            if idempotency_key and job.idempotency_key == idempotency_key:
                return job

        # Fencing Token Gate
        if lease_generation != job.lease_generation or not job.current_lease or job.current_lease.is_fenced:
            raise FencedLeaseError(
                f"Cannot complete job with fenced/stale lease generation {lease_generation}. "
                f"Active is {job.lease_generation}."
            )

        if job.current_lease.worker_id != worker_id:
            raise CapabilityDeniedError(f"Worker '{worker_id}' is not the current lease holder.")

        job.status = JobStatus.VERIFYING
        job.completion_evidence = completion_evidence
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)

        if idempotency_key:
            self._completed_idempotency_keys[idempotency_key] = job.job_id

        return job
