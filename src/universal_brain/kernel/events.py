"""
Universal Brain - Kernel Events

Defines the canonical event taxonomy, action classes, and relation types for
the tamper-evident, causal event graph. Implements ALN-016 (hash chain)
and ALN-021 (Total Awareness).

All events are immutable and hash-linked to their predecessor.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class EventType(str, Enum):
    """Canonical governance event types (18 total)."""

    USER_INPUT = "USER_INPUT"
    INTENT_PARSED = "INTENT_PARSED"
    CONTRACT_CREATED = "CONTRACT_CREATED"
    CONTRACT_UPDATED = "CONTRACT_UPDATED"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    MODEL_SELECTED = "MODEL_SELECTED"
    MODEL_REQUESTED = "MODEL_REQUESTED"
    MODEL_RESPONSE = "MODEL_RESPONSE"
    TOOL_CALLED = "TOOL_CALLED"
    EVIDENCE_PRODUCED = "EVIDENCE_PRODUCED"
    VERIFICATION_RUN = "VERIFICATION_RUN"
    HALLUCINATION_CAUGHT = "HALLUCINATION_CAUGHT"
    ROLLBACK_EXECUTED = "ROLLBACK_EXECUTED"
    HANDOFF_OCCURRED = "HANDOFF_OCCURRED"
    OPERATOR_APPROVAL = "OPERATOR_APPROVAL"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"
    CONSTITUTION_CHECK = "CONSTITUTION_CHECK"
    CONSTITUTION_AMEND = "CONSTITUTION_AMEND"
    MEMORY_SYNC = "MEMORY_SYNC"

    # M7 Autonomy & Mission Events (Section 119)
    MISSION_CREATED = "MISSION_CREATED"
    MISSION_ACTIVATED = "MISSION_ACTIVATED"
    MISSION_PAUSED = "MISSION_PAUSED"
    MISSION_RESUMED = "MISSION_RESUMED"
    MISSION_CANCELLED = "MISSION_CANCELLED"
    MISSION_COMPLETED = "MISSION_COMPLETED"
    MISSION_FAILED = "MISSION_FAILED"
    MISSION_PLAN_CREATED = "MISSION_PLAN_CREATED"
    MISSION_REPLANNED = "MISSION_REPLANNED"
    MISSION_REVALIDATION_REQUIRED = "MISSION_REVALIDATION_REQUIRED"
    AGENT_CREATED = "AGENT_CREATED"
    AGENT_LEASE_GRANTED = "AGENT_LEASE_GRANTED"
    AGENT_LEASE_REVOKED = "AGENT_LEASE_REVOKED"
    AGENT_FENCED = "AGENT_FENCED"
    AGENT_HANDOFF_COMPLETED = "AGENT_HANDOFF_COMPLETED"
    COMMITMENT_CREATED = "COMMITMENT_CREATED"
    COMMITMENT_SATISFIED = "COMMITMENT_SATISFIED"
    COMMITMENT_FAILED = "COMMITMENT_FAILED"
    MISSION_WAKEUP_SCHEDULED = "MISSION_WAKEUP_SCHEDULED"
    MISSION_WAKEUP_FIRED = "MISSION_WAKEUP_FIRED"
    MISSION_BLOCKED = "MISSION_BLOCKED"
    MISSION_UNBLOCKED = "MISSION_UNBLOCKED"
    MISSION_ESCALATED = "MISSION_ESCALATED"
    NO_PROGRESS_DETECTED = "NO_PROGRESS_DETECTED"
    AUTONOMY_LOOP_DETECTED = "AUTONOMY_LOOP_DETECTED"
    DEPENDENCY_DEADLOCK = "DEPENDENCY_DEADLOCK"
    RESOURCE_DEADLOCK = "RESOURCE_DEADLOCK"
    BLACKBOARD_CONFLICT_DETECTED = "BLACKBOARD_CONFLICT_DETECTED"
    MISSION_CHECKPOINT_CREATED = "MISSION_CHECKPOINT_CREATED"

    # M8 World Model, Perception & Situational Awareness Events (Section 115)
    OBSERVATION_INGESTED = "OBSERVATION_INGESTED"
    OBSERVATION_REJECTED = "OBSERVATION_REJECTED"
    OBSERVATION_CORRECTED = "OBSERVATION_CORRECTED"
    SOURCE_REGISTERED = "SOURCE_REGISTERED"
    SOURCE_SESSION_STARTED = "SOURCE_SESSION_STARTED"
    SOURCE_SESSION_FENCED = "SOURCE_SESSION_FENCED"
    SOURCE_DEGRADED = "SOURCE_DEGRADED"
    SOURCE_DRIFT_DETECTED = "SOURCE_DRIFT_DETECTED"
    SOURCE_RECOVERED = "SOURCE_RECOVERED"
    WORLD_ENTITY_CREATED = "WORLD_ENTITY_CREATED"
    WORLD_ENTITY_RESOLVED = "WORLD_ENTITY_RESOLVED"
    WORLD_ENTITY_MERGED = "WORLD_ENTITY_MERGED"
    WORLD_ENTITY_SPLIT = "WORLD_ENTITY_SPLIT"
    WORLD_ASSERTION_CREATED = "WORLD_ASSERTION_CREATED"
    WORLD_ASSERTION_SUPERSEDED = "WORLD_ASSERTION_SUPERSEDED"
    WORLD_ASSERTION_EXPIRED = "WORLD_ASSERTION_EXPIRED"
    WORLD_RELATION_CREATED = "WORLD_RELATION_CREATED"
    WORLD_RELATION_ENDED = "WORLD_RELATION_ENDED"
    WORLD_CONTRADICTION_DETECTED = "WORLD_CONTRADICTION_DETECTED"
    WORLD_CONTRADICTION_RESOLVED = "WORLD_CONTRADICTION_RESOLVED"
    WORLD_STATE_CHANGED = "WORLD_STATE_CHANGED"
    WORLD_WATCH_CREATED = "WORLD_WATCH_CREATED"
    WORLD_WATCH_TRIGGERED = "WORLD_WATCH_TRIGGERED"
    WORLD_SNAPSHOT_CREATED = "WORLD_SNAPSHOT_CREATED"
    WORLD_REPLAY_STARTED = "WORLD_REPLAY_STARTED"
    WORLD_REPLAY_COMPLETED = "WORLD_REPLAY_COMPLETED"
    WORLD_PROCESSOR_FENCED = "WORLD_PROCESSOR_FENCED"


class ActionClass(str, Enum):
    """Action permission class (A0 - A3)."""

    A0 = "A0"  # Observe only
    A1 = "A1"  # Reversible digital action
    A2 = "A2"  # Consequential (requires explicit approval)
    A3 = "A3"  # Prohibited autonomous action


class RelationType(str, Enum):
    """Causal relationship between two events."""

    CAUSED_BY = "CAUSED_BY"       # target is caused by source
    PROVES = "PROVES"             # target provides evidence for source
    INVALIDATES = "INVALIDATES"   # target invalidates source (correction)
    SUPERSEDES = "SUPERSEDES"     # target replaces source (new version)


# -----------------------------------------------------------------------------
# Pydantic Models
# -----------------------------------------------------------------------------


class EventEnvelope(BaseModel):
    """
    Immutable, tamper-evident event record.

    Satisfies ALN-016 (hash chain) and ALN-021 (Total Awareness).
    """

    model_config = {
        "frozen": True,           # Immutable after creation
        "extra": "forbid",        # No extra fields
        "validate_default": True,
    }

    event_id: UUID = Field(default_factory=uuid4, description="Unique event identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of event creation",
    )
    event_type: EventType = Field(..., description="Canonical event type")
    actor_id: str = Field(
        ...,
        description="Identifier of the entity that generated this event",
        min_length=1,
        max_length=128,
    )
    project_id: Optional[UUID] = Field(
        None, description="Project context (if any)"
    )
    task_id: Optional[UUID] = Field(
        None, description="Task context (if any)"
    )
    contract_version: Optional[int] = Field(
        None, description="Alignment Contract version in effect at event time"
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured payload specific to the event type",
    )
    prev_event_hash: str = Field(
        ...,
        description="SHA-256 hex digest of the immediately preceding event (empty string for genesis)",
        pattern=r"^[a-fA-F0-9]{0,64}$",
        min_length=0,
        max_length=64,
    )
    event_hash: str = Field(
        ...,
        description="SHA-256 hex digest of this event's canonical JSON representation",
        pattern=r"^[a-fA-F0-9]{64}$",
        min_length=64,
        max_length=64,
    )

    @field_validator("prev_event_hash")
    @classmethod
    def validate_prev_hash(cls, v: str) -> str:
        """Ensure prev_event_hash is either empty or 64 hex characters."""
        if v == "":
            return v
        if len(v) != 64 or not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError("prev_event_hash must be empty or a 64-character hex string")
        return v.lower()

    @model_validator(mode="after")
    def check_hash_integrity(self) -> "EventEnvelope":
        """
        Verify that event_hash matches the computed hash from the current state.
        This ensures tamper evidence is self-consistent (ALN-016).
        """
        computed = self.compute_hash(self.prev_event_hash)
        if self.event_hash.lower() != computed.lower():
            raise ValueError(
                f"event_hash mismatch: provided {self.event_hash}, computed {computed}"
            )
        return self

    @staticmethod
    def calculate_hash(
        event_id: UUID,
        timestamp: datetime,
        event_type: EventType,
        actor_id: str,
        payload: Dict[str, Any],
        prev_event_hash: str,
        project_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        contract_version: Optional[int] = None,
    ) -> str:
        """Deterministic canonical JSON serialization and SHA-256 computation."""
        canonical = {
            "actor_id": actor_id,
            "contract_version": contract_version,
            "event_id": str(event_id),
            "event_type": event_type.value,
            "payload": payload,
            "prev_event_hash": prev_event_hash.lower(),
            "project_id": str(project_id) if project_id else None,
            "task_id": str(task_id) if task_id else None,
            "timestamp": timestamp.isoformat(timespec="microseconds") + "Z",
        }
        json_str = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    def compute_hash(self, prev_hash: str) -> str:
        """Compute SHA-256 digest for this instance."""
        return self.calculate_hash(
            event_id=self.event_id,
            timestamp=self.timestamp,
            event_type=self.event_type,
            actor_id=self.actor_id,
            payload=self.payload,
            prev_event_hash=prev_hash,
            project_id=self.project_id,
            task_id=self.task_id,
            contract_version=self.contract_version,
        )

    def to_canonical_json(self) -> str:
        """Return the canonical JSON serialization used for hashing and replication."""
        canonical = {
            "actor_id": self.actor_id,
            "contract_version": self.contract_version,
            "event_hash": self.event_hash,
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "payload": self.payload,
            "prev_event_hash": self.prev_event_hash,
            "project_id": str(self.project_id) if self.project_id else None,
            "task_id": str(self.task_id) if self.task_id else None,
            "timestamp": self.timestamp.isoformat(timespec="microseconds") + "Z",
        }
        return json.dumps(canonical, sort_keys=True, separators=(",", ":"))

    @classmethod
    def create(
        cls,
        event_type: EventType,
        actor_id: str,
        payload: Optional[Dict[str, Any]] = None,
        project_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        contract_version: Optional[int] = None,
        prev_event_hash: str = "",
        timestamp: Optional[datetime] = None,
    ) -> "EventEnvelope":
        """Factory method to instantiate a new event with automatically computed hash."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        event_id = uuid4()
        clean_payload = payload or {}
        event_hash = cls.calculate_hash(
            event_id=event_id,
            timestamp=timestamp,
            event_type=event_type,
            actor_id=actor_id,
            payload=clean_payload,
            prev_event_hash=prev_event_hash,
            project_id=project_id,
            task_id=task_id,
            contract_version=contract_version,
        )
        return cls(
            event_id=event_id,
            timestamp=timestamp,
            event_type=event_type,
            actor_id=actor_id,
            project_id=project_id,
            task_id=task_id,
            contract_version=contract_version,
            payload=clean_payload,
            prev_event_hash=prev_event_hash,
            event_hash=event_hash,
        )


class EventEdge(BaseModel):
    """
    Represents a directed causal relationship between two events.

    Stored separately from events to allow flexible graph queries.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    edge_id: UUID = Field(default_factory=uuid4, description="Unique edge identifier")
    source_event_id: UUID = Field(..., description="Source event (cause)")
    target_event_id: UUID = Field(..., description="Target event (effect)")
    relation_type: RelationType = Field(..., description="Type of causal relation")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this relation was recorded",
    )

    @model_validator(mode="after")
    def prevent_self_loop(self) -> "EventEdge":
        """Prevent self-referential edges."""
        if self.source_event_id == self.target_event_id:
            raise ValueError("source_event_id and target_event_id cannot be equal")
        return self
