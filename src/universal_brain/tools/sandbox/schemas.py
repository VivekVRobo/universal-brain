"""
Universal Brain - Workspace Sandbox Schemas

Defines canonical models for execution workspaces, state manifests,
checkpoints, and reversibility proofs per ADR-0008 and M5 Sections 8-13.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from universal_brain.tools.base import ReversibilityClass


class WorkspaceStatus(str, Enum):
    """Lifecycle states of an execution workspace (M5 Section 10)."""

    CREATING = "CREATING"
    READY = "READY"
    STAGING = "STAGING"
    PREFLIGHTED = "PREFLIGHTED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED_SAFE = "FAILED_SAFE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class MutationType(str, Enum):
    """Operation classes for filesystem mutation (M5 Section 4)."""

    TEXT_PATCH = "TEXT_PATCH"
    FILE_WRITE = "FILE_WRITE"
    FILE_DELETE = "FILE_DELETE"
    FILE_RENAME = "FILE_RENAME"
    BINARY_REPLACE = "BINARY_REPLACE"
    MULTI_FILE_TRANSACTION = "MULTI_FILE_TRANSACTION"


class ManifestItem(BaseModel):
    """Metadata and cryptographic hash for a single filesystem object."""

    model_config = {"frozen": True}

    relative_path: str = Field(..., description="Path relative to workspace root")
    object_type: str = Field("file", description="file | directory | symlink")
    size_bytes: int = Field(0, description="Size in bytes")
    sha256: str = Field(..., description="Hex SHA-256 digest of content")
    permissions: int = Field(0o644, description="POSIX permissions or Windows equivalent")
    mtime: float = Field(default_factory=lambda: datetime.now(timezone.utc).timestamp())


class StateManifest(BaseModel):
    """Canonical state manifest across target workspace paths (M5 Section 12)."""

    items: Dict[str, ManifestItem] = Field(default_factory=dict)
    manifest_digest: str = Field("", description="Deterministic SHA-256 across all items")

    def compute_digest(self) -> str:
        """Computes deterministic digest over sorted manifest items."""
        ordered = {k: self.items[k].model_dump() for k in sorted(self.items.keys())}
        json_bytes = json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()


class WorkspaceCheckpoint(BaseModel):
    """A deterministic transaction checkpoint for reversible mutations (M5 Section 11)."""

    checkpoint_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    task_id: UUID
    operation_type: MutationType
    targets: List[str] = Field(..., description="Target relative paths")
    pre_state_manifest: StateManifest
    post_state_manifest: Optional[StateManifest] = None

    forward_delta: Optional[str] = None
    reverse_delta: Optional[str] = None
    tombstone_refs: Dict[str, str] = Field(default_factory=dict)
    blob_refs: Dict[str, str] = Field(default_factory=dict)

    pre_hashes: Dict[str, str] = Field(default_factory=dict)
    expected_post_hashes: Dict[str, str] = Field(default_factory=dict)

    reversibility_class: ReversibilityClass = ReversibilityClass.UNKNOWN
    reversibility_proof: Dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    schema_version: int = 1
    checkpoint_digest: str = ""

    def calculate_digest(self) -> str:
        """Calculates deterministic SHA-256 over canonical checkpoint fields."""
        fields = {
            "checkpoint_id": str(self.checkpoint_id),
            "workspace_id": str(self.workspace_id),
            "task_id": str(self.task_id),
            "operation_type": self.operation_type.value,
            "targets": sorted(self.targets),
            "pre_hashes": {k: self.pre_hashes[k] for k in sorted(self.pre_hashes.keys())},
            "expected_post_hashes": {k: self.expected_post_hashes[k] for k in sorted(self.expected_post_hashes.keys())},
            "reversibility_class": self.reversibility_class.value,
            "created_at": self.created_at.isoformat(),
        }
        json_bytes = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()

    def verify_digest(self) -> bool:
        """Verifies checkpoint data against its cryptographic digest."""
        if not self.checkpoint_digest:
            return False
        return self.checkpoint_digest == self.calculate_digest()


class Workspace(BaseModel):
    """Isolated execution workspace (M5 Section 8)."""

    workspace_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    task_id: UUID
    root_path: Path
    status: WorkspaceStatus = WorkspaceStatus.READY
    active_checkpoints: List[WorkspaceCheckpoint] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
