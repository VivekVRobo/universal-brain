"""
Universal Brain - Canonical World Model, Perception & Situational Awareness Schemas
Implements Milestone M8 Specification (Sections 7-10, 12-13, 17, 27-35, 45, 69, 79, 80, 87, 97).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ObservationType(str, Enum):
    STATE = "STATE"
    MEASUREMENT = "MEASUREMENT"
    EVENT = "EVENT"
    DETECTION = "DETECTION"
    LOCATION = "LOCATION"
    HEALTH = "HEALTH"
    CONTENT_CHANGE = "CONTENT_CHANGE"
    RESOURCE_CHANGE = "RESOURCE_CHANGE"
    EXTERNAL_SIGNAL = "EXTERNAL_SIGNAL"


class SourceType(str, Enum):
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"
    API = "API"
    FILE = "FILE"
    DATABASE = "DATABASE"
    ROS2_TOPIC = "ROS2_TOPIC"
    CAMERA = "CAMERA"
    MICROPHONE = "MICROPHONE"
    DEVICE = "DEVICE"
    HUMAN = "HUMAN"
    MODEL_DERIVED = "MODEL_DERIVED"
    REMOTE_WORKER = "REMOTE_WORKER"


class SourceTrustClass(str, Enum):
    UNTRUSTED = "UNTRUSTED"
    INTERNAL = "INTERNAL"
    VERIFIED_HARDWARE = "VERIFIED_HARDWARE"
    SOVEREIGN = "SOVEREIGN"


class SourceHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    FAILED = "FAILED"
    REVOKED = "REVOKED"


class EntityResolutionStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    CANDIDATE_MATCH = "CANDIDATE_MATCH"
    MATCHED = "MATCHED"
    REJECTED = "REJECTED"


class AssertionStateClass(str, Enum):
    """Prime Epistemic Invariant (M8-INV-01)."""
    OBSERVED = "OBSERVED"
    FUSED = "FUSED"
    INFERRED = "INFERRED"
    VERIFIED = "VERIFIED"


class AssertionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CONTRADICTED = "CONTRADICTED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class FreshnessStatus(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class WatchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PrivacyClass(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    PRIVATE = "PRIVATE"
    SECRET = "SECRET"
    LOCAL_ONLY = "LOCAL_ONLY"


class EnvironmentMode(str, Enum):
    SIMULATED = "SIMULATED"
    REAL = "REAL"
    REPLAYED = "REPLAYED"
    DEMO = "DEMO"


class ContradictionSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ResolutionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


class Observation(BaseModel):
    """
    Canonical Observation (Sections 8-10).
    Immutable historical record of what an external or internal source claimed.
    """

    observation_id: UUID = Field(default_factory=uuid4)
    source_id: str
    source_session_id: UUID
    source_observation_id: str
    source_sequence: int = 1

    observation_type: ObservationType = ObservationType.STATE

    subject_ref: str
    property_key: str

    value: Any
    unit: Optional[str] = None
    coordinate_frame: Optional[str] = None

    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: Optional[datetime] = None

    confidence: float = 1.0
    uncertainty: Optional[Dict[str, Any]] = None

    quality_flags: List[str] = Field(default_factory=list)
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL
    environment_mode: EnvironmentMode = EnvironmentMode.REAL

    raw_payload_ref: Optional[str] = None
    raw_payload_digest: str = ""

    schema_version: int = 1
    ontology_version: int = 1

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    observation_digest: str = ""

    def calculate_digest(self) -> str:
        """
        Deterministic SHA-256 digest over normalized observation fields (Section 10).
        """
        norm_val = self.value
        if isinstance(norm_val, float):
            norm_val = round(norm_val, 9)
        elif isinstance(norm_val, dict):
            norm_val = json.loads(json.dumps(norm_val, sort_keys=True, default=str))

        canonical_dict = {
            "source_id": self.source_id,
            "source_session_id": str(self.source_session_id),
            "source_observation_id": self.source_observation_id,
            "source_sequence": self.source_sequence,
            "observation_type": self.observation_type.value,
            "subject_ref": self.subject_ref,
            "property_key": self.property_key,
            "value": norm_val,
            "unit": self.unit or "",
            "coordinate_frame": self.coordinate_frame or "",
            "observed_at": self.observed_at.isoformat(),
            "valid_from": self.valid_from.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else "",
            "confidence": round(self.confidence, 4),
            "quality_flags": sorted(self.quality_flags),
            "privacy_class": self.privacy_class.value,
            "environment_mode": self.environment_mode.value,
            "raw_payload_digest": self.raw_payload_digest,
            "schema_version": self.schema_version,
            "ontology_version": self.ontology_version,
        }
        encoded = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class ObservationSource(BaseModel):
    """Observation Source Registry Record (Section 12)."""

    source_id: str
    source_type: SourceType
    canonical_name: str
    adapter_type: str
    trust_class: SourceTrustClass = SourceTrustClass.INTERNAL
    allowed_types: List[ObservationType] = Field(default_factory=list)
    allowed_entity_scopes: List[str] = Field(default_factory=list)
    freshness_policy: Dict[str, Any] = Field(default_factory=dict)
    authentication_token: str = ""
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    revoked_at: Optional[datetime] = None
    health: SourceHealth = SourceHealth.HEALTHY
    source_version: int = 1


class SourceSession(BaseModel):
    """Source Runtime Session with Epoch Binding (Section 13)."""

    source_session_id: UUID = Field(default_factory=uuid4)
    source_id: str
    kernel_epoch: int
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    protocol_version: str = "1.0"
    credential_binding: str = ""
    status: str = "ACTIVE"


class SourceReliability(BaseModel):
    """Source Reliability and Drift Metrics (Sections 17-19)."""

    source_id: str
    samples: int = 0
    confirmed: int = 0
    contradicted: int = 0
    invalid: int = 0
    outliers: int = 0
    timestamp_faults: int = 0
    replay_attempts: int = 0
    scope_violations: int = 0
    reliability_score: float = 1.0
    reliability_policy_version: int = 1
    drift_detected: bool = False
    last_calibrated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorldEntity(BaseModel):
    """Durable Tracked World Entity (Sections 27-31)."""

    entity_id: str
    entity_type: str
    canonical_name: str
    identity_attributes: Dict[str, Any] = Field(default_factory=dict)
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    retired_at: Optional[datetime] = None
    status: str = "ACTIVE"
    entity_version: int = 1
    ontology_version: int = 1
    merged_into: Optional[str] = None


class EntityAlias(BaseModel):
    """Entity Alias Linkage (Section 28)."""

    alias_id: UUID = Field(default_factory=uuid4)
    alias: str
    entity_id: str
    source_id: str
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorldPropertyAssertion(BaseModel):
    """
    Bitemporal World Property Assertion (Sections 33-36).
    Distinguishes valid_time from transaction_time.
    """

    assertion_id: UUID = Field(default_factory=uuid4)
    entity_id: str
    property_key: str

    value: Any
    unit: Optional[str] = None
    coordinate_frame: Optional[str] = None

    state_class: AssertionStateClass = AssertionStateClass.OBSERVED
    valid_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: Optional[datetime] = None
    transaction_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    transaction_until: Optional[datetime] = None

    confidence: float = 1.0
    uncertainty: Optional[Dict[str, Any]] = None

    supporting_observations: List[UUID] = Field(default_factory=list)
    contradicting_observations: List[UUID] = Field(default_factory=list)

    freshness_status: FreshnessStatus = FreshnessStatus.FRESH
    fusion_policy_version: Optional[int] = None
    inference_rule_version: Optional[int] = None

    ontology_version: int = 1
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL
    status: AssertionStatus = AssertionStatus.ACTIVE
    assertion_version: int = 1


class WorldRelation(BaseModel):
    """Temporal Relationship Edge (Section 45)."""

    relation_id: UUID = Field(default_factory=uuid4)
    source_entity: str
    relation_type: str
    target_entity: str

    valid_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: Optional[datetime] = None
    transaction_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    transaction_until: Optional[datetime] = None

    state_class: AssertionStateClass = AssertionStateClass.OBSERVED
    confidence: float = 1.0
    uncertainty: Optional[Dict[str, Any]] = None

    evidence_refs: List[str] = Field(default_factory=list)
    relation_version: int = 1
    ontology_version: int = 1
    status: str = "ACTIVE"


class WorldContradiction(BaseModel):
    """Formally Tracked Contradiction Envelope (Sections 68-70)."""

    contradiction_id: UUID = Field(default_factory=uuid4)
    entity_id: str
    property_key: str
    assertion_ids: List[UUID] = Field(default_factory=list)
    temporal_overlap: bool = True
    severity: ContradictionSeverity = ContradictionSeverity.HIGH
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolution_status: ResolutionStatus = ResolutionStatus.OPEN
    resolution_evidence: Optional[str] = None
    winning_assertion_id: Optional[UUID] = None


class WorldEvent(BaseModel):
    """Normalized Environmental Change Event (Section 79)."""

    world_event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    entity_id: str
    property_key: str
    previous_value: Any = None
    new_value: Any = None
    significance: str = "NORMAL"
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_refs: List[str] = Field(default_factory=list)


class WorldWatch(BaseModel):
    """Persistent Reactive Condition (Sections 80-83)."""

    watch_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    task_id: Optional[UUID] = None
    entity_id: str
    property_key: str
    expected_value: Any
    operator: str = "=="
    required_freshness: FreshnessStatus = FreshnessStatus.FRESH
    required_state_class: Optional[AssertionStateClass] = None
    debounce_sec: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    status: WatchStatus = WatchStatus.ACTIVE
    idempotency_key: str = ""
    watch_version: int = 1


class WorldSnapshot(BaseModel):
    """Logical Consistency Boundary with Deterministic SHA-256 Digest (Sections 87-88)."""

    snapshot_id: UUID = Field(default_factory=uuid4)
    scope: str = "GLOBAL"
    observation_head: int = 0
    processor_cursor: int = 0
    entity_versions: Dict[str, int] = Field(default_factory=dict)
    assertion_versions: Dict[str, int] = Field(default_factory=dict)
    relation_versions: Dict[str, int] = Field(default_factory=dict)
    ontology_version: int = 1
    fusion_policy_version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    snapshot_digest: str = ""

    def calculate_digest(self) -> str:
        canonical_dict = {
            "scope": self.scope,
            "observation_head": self.observation_head,
            "processor_cursor": self.processor_cursor,
            "entity_versions": dict(sorted(self.entity_versions.items())),
            "assertion_versions": dict(sorted(self.assertion_versions.items())),
            "relation_versions": dict(sorted(self.relation_versions.items())),
            "ontology_version": self.ontology_version,
            "fusion_policy_version": self.fusion_policy_version,
        }
        encoded = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class SituationalContext(BaseModel):
    """
    Situational Context Payload injected into Executive Awareness Package (Section 97).
    """

    world_snapshot_id: UUID
    projection_digest: str
    relevant_entities: List[Dict[str, Any]] = Field(default_factory=list)
    verified_facts: List[Dict[str, Any]] = Field(default_factory=list)
    fused_beliefs: List[Dict[str, Any]] = Field(default_factory=list)
    inferences: List[Dict[str, Any]] = Field(default_factory=list)
    contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    stale_state: List[Dict[str, Any]] = Field(default_factory=list)
    unknown_state: List[Dict[str, Any]] = Field(default_factory=list)
    recent_changes: List[Dict[str, Any]] = Field(default_factory=list)
    active_watches: List[Dict[str, Any]] = Field(default_factory=list)
