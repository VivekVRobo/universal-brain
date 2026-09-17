"""
Universal Brain - Failure Ledger & Anti-Loop Protection

Implements Sections 47 & 48 of the God-Level Specification:
- First-class failure tracking accumulator;
- Anti-loop protection preventing repeated identical failures;
- Feeds failure intelligence into future EAPs and handoff snapshots.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from universal_brain.kernel.errors import InvariantViolationError


class AntiLoopBreakerError(InvariantViolationError):
    """Raised when the Executive detects an autonomous infinite retry loop."""

    def __init__(self, message: str) -> None:
        super().__init__("ALN-014", message)


class FailureRecord(BaseModel):
    """Canonical failure event entry."""

    failure_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    node_id: str
    provider_id: str
    model_id: str
    tool_name: Optional[str] = None
    target_resource: Optional[str] = None
    category: str  # PREFLIGHT_FAILED | TIMEOUT | BUILD_ERROR | REVERSAL_FAILED
    message: str
    attempt: int = 1
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FailureLedger:
    """Accumulates failures and enforces anti-loop deterministic limits."""

    def __init__(self, max_identical_failures: int = 3) -> None:
        self.max_identical_failures = max_identical_failures
        self._failures: List[FailureRecord] = []

    def record_failure(
        self,
        task_id: UUID,
        node_id: str,
        provider_id: str,
        model_id: str,
        category: str,
        message: str,
        tool_name: Optional[str] = None,
        target_resource: Optional[str] = None,
    ) -> FailureRecord:
        """Records failure and evaluates anti-loop safety threshold."""
        # Count identical prior attempts
        identical_count = sum(
            1 for f in self._failures
            if f.node_id == node_id
            and f.tool_name == tool_name
            and f.target_resource == target_resource
            and f.category == category
        )

        record = FailureRecord(
            task_id=task_id,
            node_id=node_id,
            provider_id=provider_id,
            model_id=model_id,
            tool_name=tool_name,
            target_resource=target_resource,
            category=category,
            message=message,
            attempt=identical_count + 1,
        )
        self._failures.append(record)

        # Enforce Anti-Loop Threshold
        if record.attempt >= self.max_identical_failures:
            raise AntiLoopBreakerError(
                f"[ANTI-LOOP BREAKER] Operation '{tool_name or category}' on target '{target_resource or node_id}' "
                f"failed {record.attempt} times consecutively. Execution halted to prevent resource waste."
            )

        return record

    def list_failures(self, task_id: Optional[UUID] = None) -> List[Dict[str, Any]]:
        """Returns failures formatted for EAP injection."""
        records = self._failures
        if task_id:
            records = [r for r in records if r.task_id == task_id]
        return [
            {
                "failure_id": str(r.failure_id),
                "node_id": r.node_id,
                "provider": r.provider_id,
                "category": r.category,
                "message": r.message,
                "attempt": r.attempt,
            }
            for r in records[-5:]  # Top 5 most recent
        ]
