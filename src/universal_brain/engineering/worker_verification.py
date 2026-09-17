"""Independent worker completion gate.

Traceability: REQ-ENG-011, REQ-VER-001, ALN-010, ALN-011. A remote worker's
completion claim is never itself sufficient evidence.
"""

from __future__ import annotations

from typing import Protocol, Any

from pydantic import BaseModel, Field


class WorkerCompletionDecision(BaseModel):
    accepted: bool
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str = ""


class WorkerCompletionVerifier(Protocol):
    async def verify(self, job, completion_evidence: dict[str, Any]) -> WorkerCompletionDecision: ...


class VerifiedWorkerCompletionGate:
    """Verify a completion claim before delegating to EphemeralJobQueue.complete_job."""

    def __init__(self, queue, verifier: WorkerCompletionVerifier):
        self.queue = queue
        self.verifier = verifier

    async def complete_job(
        self,
        job_id,
        worker_id: str,
        lease_generation: int,
        completion_evidence: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        lease_token: str | None = None,
    ):
        job = self.queue.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id!s} not found")
        decision = await self.verifier.verify(job, completion_evidence)
        if not decision.accepted:
            from universal_brain.tools.workers.schemas import JobStatus

            job.status = JobStatus.REJECTED_RESULT
            job.completion_evidence = {
                **completion_evidence,
                "verification_rejected": True,
                "verification_reason": decision.reason,
                "verification_evidence_refs": decision.evidence_refs,
            }
            return job
        evidence = {
            **completion_evidence,
            "verification_evidence_refs": decision.evidence_refs,
            "verification_reason": decision.reason,
        }
        return self.queue.complete_job(
            job_id,
            worker_id,
            lease_generation,
            evidence,
            idempotency_key=idempotency_key,
            lease_token=lease_token,
        )
