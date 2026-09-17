"""
Universal Brain - Autonomy & Mission Control Failure Taxonomy

Implements M7 Section 120 and Section 115:
Normalizes all autonomous mission execution, scheduling, fencing,
deadlock, and recovery errors.
"""

from __future__ import annotations

from typing import Optional


class MissionError(Exception):
    """Base exception for all autonomy and mission control errors."""

    def __init__(self, message: str, mission_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.mission_id = mission_id


class MissionStateError(MissionError):
    """Raised when an illegal mission lifecycle state transition is attempted."""
    pass


class MissionVersionConflictError(MissionError):
    """Raised when optimistic concurrency fails on mutable mission state."""
    pass


class MissionContractChangedError(MissionError):
    """Raised when an active contract changes materially, requiring revalidation."""
    pass


class AgentLeaseExpiredError(MissionError):
    """Raised when an agent attempts an operation after its lease has expired."""
    pass


class AgentFencedError(MissionError):
    """Raised when an agent is fenced by newer lease generation or kernel epoch."""
    pass


class SchedulerFencedError(MissionError):
    """Raised when a scheduler instance is fenced by a newer kernel epoch."""
    pass


class NoProgressError(MissionError):
    """Raised when repeated activity occurs without canonical state or evidence progress."""
    pass


class AutonomyLoopError(MissionError):
    """Raised when the anti-loop engine detects repeated operation fingerprints."""
    pass


class DependencyDeadlockError(MissionError):
    """Raised when circular task or dependency graphs prevent progression."""
    pass


class ResourceDeadlockError(MissionError):
    """Raised when exclusive resource contention creates a circular wait."""
    pass


class MissionBudgetExceededError(MissionError):
    """Raised when mission expenditure hits or exceeds the hard spending ceiling."""
    pass


class MissionDeadlineExceededError(MissionError):
    """Raised when mission deadline has elapsed or is mathematically infeasible."""
    pass


class WakeupConflictError(MissionError):
    """Raised when duplicate or stale wakeups are claimed concurrently."""
    pass


class MissionRecoveryRequiredError(MissionError):
    """Raised when crash recovery cannot deterministically resolve mission ownership."""
    pass
