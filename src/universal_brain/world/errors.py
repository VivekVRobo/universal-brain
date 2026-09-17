"""
Universal Brain - World Model & Perception Failure Taxonomy
Implements Section 118 of Milestone M8 Specification.
"""

from typing import Optional


class WorldModelError(Exception):
    """Base exception for all World Model, Perception, and Situational Awareness errors."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ObservationValidationError(WorldModelError):
    """Raised when an incoming observation fails schema, unit, or coordinate frame validation."""
    pass


class ObservationIntegrityError(WorldModelError):
    """Raised when an observation's payload digest does not match its claims or is tampered with."""
    pass


class ObservationReplayError(WorldModelError):
    """Raised when a duplicated observation ID arrives with different content or invalid sequence."""
    pass


class SourceAuthenticationError(WorldModelError):
    """Raised when an observation source fails credential verification or authentication."""
    pass


class SourceScopeError(WorldModelError):
    """Raised when a source attempts to report observations outside its authorized entity or property scope."""
    pass


class SourceFencedError(WorldModelError):
    """Raised when an observation is submitted by a source session from a superseded kernel epoch or expired lease."""
    pass


class SourceUnavailableError(WorldModelError):
    """Raised when an observation source is offline, revoked, or unreachable."""
    pass


class OntologyMismatchError(WorldModelError):
    """Raised when an observation or assertion uses an unsupported or incompatible ontology version."""
    pass


class UnitDimensionError(WorldModelError):
    """Raised when an observation value has an incompatible physical dimension or unit conversion fails."""
    pass


class EntityResolutionConflictError(WorldModelError):
    """Raised when multiple distinct entities conflict during identity resolution or merge."""
    pass


class TemporalConsistencyError(WorldModelError):
    """Raised when timestamps violate temporal ordering (e.g. valid_from > valid_until, non-monotonic clock)."""
    pass


class SequenceGapError(WorldModelError):
    """Raised when a monotonic source sequence skips expected observation numbers."""
    pass


class FrameTransformError(WorldModelError):
    """Raised when a required coordinate frame transformation is missing or fails."""
    pass


class FrameTransformStaleError(WorldModelError):
    """Raised when a coordinate transform chain has expired beyond its freshness tolerance."""
    pass


class FusionFailureError(WorldModelError):
    """Raised when multi-source observation fusion cannot reach a deterministic estimate."""
    pass


class ContradictionError(WorldModelError):
    """Raised when mutually incompatible assertions overlap temporally and cannot be reconciled."""
    pass


class WorldVersionConflictError(WorldModelError):
    """Raised when optimistic concurrency checks fail on mutable entity, assertion, or watch versions."""
    pass


class WorldProcessorFencedError(WorldModelError):
    """Raised when an authoritative world projection processor is superseded by a newer generation or epoch."""
    pass


class WorldWatchEvaluationError(WorldModelError):
    """Raised when a world watch condition expression fails evaluation or references invalid properties."""
    pass


class WorldReplayMismatchError(WorldModelError):
    """Raised when deterministic replay yields a projection digest that does not match historical snapshot."""
    pass


class WorldRecoveryRequiredError(WorldModelError):
    """Raised when world state is inconsistent post-crash and requires operator recovery or projection rebuild."""
    pass
