"""
Universal Brain - World Model, Perception & Situational Awareness Package
Milestone M8.
"""

from .assertions import WorldAssertionManager
from .changes import WorldChangeDetector
from .contradictions import WorldContradictionEngine
from .entities import WorldEntityManager
from .errors import (
    ContradictionError,
    EntityResolutionConflictError,
    FrameTransformError,
    FrameTransformStaleError,
    FusionFailureError,
    ObservationIntegrityError,
    ObservationReplayError,
    ObservationValidationError,
    OntologyMismatchError,
    SequenceGapError,
    SourceAuthenticationError,
    SourceFencedError,
    SourceScopeError,
    SourceUnavailableError,
    TemporalConsistencyError,
    UnitDimensionError,
    WorldModelError,
    WorldProcessorFencedError,
    WorldRecoveryRequiredError,
    WorldReplayMismatchError,
    WorldVersionConflictError,
    WorldWatchEvaluationError,
)
from .frames import CoordinateFrameRegistry, TransformedPoseResult
from .freshness import FreshnessEngine
from .fusion import ObservationFusionEngine
from .inference import InferenceEngine, InferenceRule
from .ingest import ObservationIngestGate
from .ontology import WorldOntology
from .processor import WorldProcessingCell
from .recovery import WorldRecoveryManager
from .relations import WorldRelationManager
from .reliability import SourceReliabilityTracker
from .replay import WorldReplayEngine
from .schemas import (
    AssertionStateClass,
    AssertionStatus,
    EntityAlias,
    EntityResolutionStatus,
    EnvironmentMode,
    FreshnessStatus,
    Observation,
    ObservationSource,
    ObservationType,
    PrivacyClass,
    SituationalContext,
    SourceHealth,
    SourceReliability,
    SourceSession,
    SourceTrustClass,
    SourceType,
    WatchStatus,
    WorldContradiction,
    WorldEntity,
    WorldEvent,
    WorldPropertyAssertion,
    WorldRelation,
    WorldSnapshot,
    WorldWatch,
)
from .sessions import SourceSessionManager
from .snapshots import WorldSnapshotManager
from .sources import ObservationSourceRegistry
from .subscriptions import WorldSubscriptionRegistry
from .units import MeasurementUnitRegistry, UnitConversionResult

__all__ = [
    # Schemas & Enums
    "ObservationType",
    "SourceType",
    "SourceTrustClass",
    "SourceHealth",
    "EntityResolutionStatus",
    "AssertionStateClass",
    "AssertionStatus",
    "FreshnessStatus",
    "WatchStatus",
    "PrivacyClass",
    "EnvironmentMode",
    "Observation",
    "ObservationSource",
    "SourceSession",
    "SourceReliability",
    "WorldEntity",
    "EntityAlias",
    "WorldPropertyAssertion",
    "WorldRelation",
    "WorldContradiction",
    "WorldEvent",
    "WorldWatch",
    "WorldSnapshot",
    "SituationalContext",
    # Core Engines
    "MeasurementUnitRegistry",
    "UnitConversionResult",
    "WorldOntology",
    "ObservationSourceRegistry",
    "SourceSessionManager",
    "ObservationIngestGate",
    "WorldEntityManager",
    "WorldAssertionManager",
    "WorldRelationManager",
    "CoordinateFrameRegistry",
    "TransformedPoseResult",
    "FreshnessEngine",
    "SourceReliabilityTracker",
    "ObservationFusionEngine",
    "WorldContradictionEngine",
    "InferenceEngine",
    "InferenceRule",
    "WorldChangeDetector",
    "WorldWatchManager",
    "WorldSubscriptionRegistry",
    "WorldSnapshotManager",
    "WorldReplayEngine",
    "WorldProcessingCell",
    "WorldRecoveryManager",
    # Errors
    "WorldModelError",
    "ObservationValidationError",
    "ObservationIntegrityError",
    "ObservationReplayError",
    "SourceAuthenticationError",
    "SourceScopeError",
    "SourceFencedError",
    "SourceUnavailableError",
    "OntologyMismatchError",
    "UnitDimensionError",
    "EntityResolutionConflictError",
    "TemporalConsistencyError",
    "SequenceGapError",
    "FrameTransformError",
    "FrameTransformStaleError",
    "FusionFailureError",
    "ContradictionError",
    "WorldVersionConflictError",
    "WorldProcessorFencedError",
    "WorldWatchEvaluationError",
    "WorldReplayMismatchError",
    "WorldRecoveryRequiredError",
]
