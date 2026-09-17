"""
Universal Brain - Error Taxonomy

Defines the structured exception hierarchy for the system.
All invariant-related exceptions explicitly reference their governing
Constitutional Article and Alignment Invariant (ALN-001 to ALN-021).
"""

from typing import Optional


class UniversalBrainError(Exception):
    """Base exception for all Universal Brain errors."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvariantViolationError(UniversalBrainError):
    """Raised when an action or state violates a Constitutional Alignment Invariant."""

    def __init__(
        self,
        invariant_id: str,
        message: str,
        details: Optional[dict] = None,
    ) -> None:
        full_message = f"[{invariant_id}] Invariant Violation: {message}"
        super().__init__(full_message, details)
        self.invariant_id = invariant_id


class RequirementProvenanceError(InvariantViolationError):
    """ALN-001: Task or requirement lacks valid provenance tracing to user input."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("ALN-001", message, details)


class AmbiguityBlockedError(InvariantViolationError):
    """ALN-004 / ALN-004a: High-impact ambiguity blocks execution branch."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("ALN-004", message, details)


class DescendantInvalidationError(InvariantViolationError):
    """ALN-005: Operator correction must invalidate affected descendant tasks."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("ALN-005", message, details)


class ConstraintWeakenedError(InvariantViolationError):
    """ALN-006: Explicit constraint cannot be silently weakened."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("ALN-006", message, details)


class ActionScopeViolationError(InvariantViolationError):
    """ALN-007: Action violates bounded scope or lacks rollback instructions."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("ALN-007", message, details)


class CapabilityDeniedError(InvariantViolationError):
    """ALN-008 / ALN-009: Missing, expired, or self-expanded capability token."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("ALN-008", message, details)


class EvidenceMissingError(InvariantViolationError):
    """ALN-010 / ALN-020: Completion or verification claimed without deterministic evidence."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("ALN-010", message, details)


class HealthGateError(InvariantViolationError):
    """ALN-014: Unhealthy system state disables state-changing actions."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("ALN-014", message, details)


class HashChainTamperError(InvariantViolationError):
    """ALN-016: Cryptographic event hash chain broken or tampered."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("ALN-016", message, details)


class ActuatorProhibitedError(InvariantViolationError):
    """ALN-018: Direct physical actuator control is strictly denied in Version 1."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("ALN-018", message, details)


class BudgetExhaustedError(UniversalBrainError):
    """Raised when monthly or project spending ceilings are reached (Cost Control Policy)."""
    pass


class RollbackPreflightError(UniversalBrainError):
    """Raised when an A1 action fails reversibility preflight validation (ADR-0008)."""
    pass
