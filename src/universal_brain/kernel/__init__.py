"""Kernel module for Universal Brain."""
from .events import EventEnvelope, EventEdge, EventType, ActionClass, RelationType
from .capability import (
    CapabilityToken,
    CapabilityService,
    RollbackGrant,
    compute_canonical_request_digest,
    is_resource_authorized,
)
from .event_store import EventStore
from .errors import (
    UniversalBrainError,
    InvariantViolationError,
    RequirementProvenanceError,
    AmbiguityBlockedError,
    DescendantInvalidationError,
    ConstraintWeakenedError,
    ActionScopeViolationError,
    CapabilityDeniedError,
    EvidenceMissingError,
    HealthGateError,
    HashChainTamperError,
    ActuatorProhibitedError,
    BudgetExhaustedError,
    RollbackPreflightError,
)

__all__ = [
    "EventEnvelope",
    "EventEdge",
    "EventType",
    "ActionClass",
    "RelationType",
    "CapabilityToken",
    "CapabilityService",
    "RollbackGrant",
    "compute_canonical_request_digest",
    "is_resource_authorized",
    "EventStore",
    "UniversalBrainError",
    "InvariantViolationError",
    "RequirementProvenanceError",
    "AmbiguityBlockedError",
    "DescendantInvalidationError",
    "ConstraintWeakenedError",
    "ActionScopeViolationError",
    "CapabilityDeniedError",
    "EvidenceMissingError",
    "HealthGateError",
    "HashChainTamperError",
    "ActuatorProhibitedError",
    "BudgetExhaustedError",
    "RollbackPreflightError",
]
