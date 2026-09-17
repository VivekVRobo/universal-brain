"""
Universal Brain - Ephemeral Worker Fabric Schemas

Implements M5 Sections 45, 48, 49, 50, 54, 55:
Defines untrusted remote worker models, lease fencing tokens (lease_generation),
monotonic checkpoint records, and verifiable job lifecycles.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class WorkerStatus(str, Enum):
    """Lifecycle status of a remote worker."""

    IDLE = "IDLE"
    BUSY = "BUSY"
    DISCONNECTED = "DISCONNECTED"
    BANNED = "BANNED"


class JobStatus(str, Enum):
    """Authoritative lifecycle status of a remote worker job (M5 Section 49)."""

    QUEUED = "QUEUED"
    LEASED = "LEASED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RUNNING = "RUNNING"
    CHECKPOINTING = "CHECKPOINTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    CANCELLED = "CANCELLED"
    REJECTED_RESULT = "REJECTED_RESULT"


class WorkerRegistration(BaseModel):
    """Advertised worker registration packet (M5 Section 45, 47)."""

    worker_id: str
    worker_session_id: UUID = Field(default_factory=uuid4)
    worker_type: str = Field(..., description="colab_t4 | kaggle_p100 | local_gpu")
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    protocol_version: str = "1.0"
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkerLease(BaseModel):
    """Authoritative lease with fencing token (M5 Section 50, 51)."""

    lease_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    worker_id: str
    worker_session_id: UUID
    lease_generation: int = Field(..., description="Monotonic fencing token")
    leased_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_fenced: bool = False
    lease_token: Optional[str] = None

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        now = current_time or datetime.now(timezone.utc)
        return now > self.expires_at


class CheckpointRecord(BaseModel):
    """Intermediate worker progress checkpoint (M5 Section 53, 54, 55)."""

    checkpoint_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    lease_generation: int
    sequence: int = Field(..., description="Monotonically increasing sequence number")
    progress_pct: float = Field(..., ge=0.0, le=100.0)
    state_artifact_ref: Optional[str] = None
    artifact_digest: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkerJob(BaseModel):
    """Authoritative execution job dispatched to worker fabric (M5 Section 48)."""

    job_id: UUID = Field(default_factory=uuid4)
    job_version: int = 1
    project_id: UUID
    task_id: UUID
    job_type: str = Field(..., description="simulation_run | model_train | dataset_transform")
    payload: Dict[str, Any] = Field(default_factory=dict)
    payload_digest: str = ""
    status: JobStatus = JobStatus.QUEUED

    current_lease: Optional[WorkerLease] = None
    lease_generation: int = 0  # Fencing token counter
    kernel_epoch: int = 1
    checkpoints: List[CheckpointRecord] = Field(default_factory=list)
    last_checkpoint_seq: int = 0

    completion_evidence: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    def compute_payload_digest(self) -> str:
        data_bytes = json.dumps(self.payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(data_bytes).hexdigest()
