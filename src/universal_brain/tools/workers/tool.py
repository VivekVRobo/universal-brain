"""
Universal Brain - Cloud Batch Dispatch Tool

Implements M5 Section 40, 48:
BaseTool subclass for enqueueing and dispatching heavy batch jobs to the worker fabric.
"""

from __future__ import annotations

from typing import Any, Dict
from uuid import UUID, uuid4

from universal_brain.kernel.events import ActionClass
from universal_brain.tools.base import BaseTool, ReversibilityClass, ToolResult
from universal_brain.tools.workers.queue import EphemeralJobQueue
from universal_brain.tools.workers.schemas import JobStatus


class CloudBatchDispatchTool(BaseTool):
    """Submits heavy compute workloads to remote ephemeral worker fabric."""

    name: str = "cloud_batch_dispatch"
    action_class: ActionClass = ActionClass.A1
    description: str = "Dispatches heavy batch jobs (simulations, model training) to ephemeral GPU workers."
    reversibility_class: ReversibilityClass = ReversibilityClass.REVERSIBLE_WITH_LIMITATIONS

    def __init__(self, job_queue: EphemeralJobQueue) -> None:
        self.job_queue = job_queue

    def preflight_check(self, args: Dict[str, Any], target_resource: str = "*") -> bool:
        job_type = args.get("job_type")
        payload = args.get("payload")
        return bool(job_type and isinstance(payload, dict))

    def execute(self, args: Dict[str, Any], target_resource: str = "*") -> ToolResult:
        project_id = UUID(args.get("project_id", str(uuid4())))
        task_id = UUID(args.get("task_id", str(uuid4())))
        job_type = args["job_type"]
        payload = args.get("payload", {})
        idempotency_key = args.get("idempotency_key")

        job = self.job_queue.enqueue_job(
            project_id=project_id,
            task_id=task_id,
            job_type=job_type,
            payload=payload,
            idempotency_key=idempotency_key,
        )

        return ToolResult(
            success=True,
            output=f"Enqueued batch job '{job.job_id}' (type={job_type}). Status={job.status.value}",
            evidence={
                "job_id": str(job.job_id),
                "job_type": job.job_type,
                "payload_digest": job.payload_digest,
                "status": job.status.value,
            },
            rollback_data={"job_id": str(job.job_id)},
            reversibility_class=self.reversibility_class,
            post_digest=job.payload_digest,
        )

    def rollback(self, rollback_data: Dict[str, Any]) -> bool:
        job_id = rollback_data.get("job_id")
        if not job_id:
            return False
        try:
            return self.job_queue.cancel_job(UUID(str(job_id)))
        except (ValueError, TypeError):
            return False

    def verify_rollback(self, rollback_data: Dict[str, Any]) -> bool:
        job_id = rollback_data.get("job_id")
        if not job_id:
            return False
        try:
            job = self.job_queue.get_job(UUID(str(job_id)))
        except (ValueError, TypeError):
            return False
        if job is None or job.status != JobStatus.CANCELLED:
            return False
        return job.current_lease is None or job.current_lease.is_fenced
