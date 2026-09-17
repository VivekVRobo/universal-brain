"""
Universal Brain - Mission Progress Ledger & Digest

Implements M7 Sections 41-43 and Invariant M7-INV-09:
- Strictly distinguishes busywork/activity from genuine mission progress;
- Calculates deterministic SHA-256 progress_digest over verified state;
- Powers the Progress Watchdog and Mission Checkpoints.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from pydantic import BaseModel, Field


class ProgressSnapshot(BaseModel):
    """Immutable snapshot of verified mission advancement indicators."""

    mission_id: UUID
    mission_version: int
    verified_criteria: List[str] = Field(default_factory=list)
    completed_tasks: List[str] = Field(default_factory=list)
    blocked_tasks: List[str] = Field(default_factory=list)
    failed_tasks: List[str] = Field(default_factory=list)
    open_commitments: int = 0
    resolved_dependencies: List[str] = Field(default_factory=list)
    verified_evidence_hashes: List[str] = Field(default_factory=list)
    last_progress_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    progress_digest: str = ""

    def calculate_digest(self) -> str:
        """
        Computes deterministic SHA-256 digest over canonical progress state (M7 Section 42).
        Enforces M7-INV-09: only verified criteria, completed tasks, and evidence count.
        """
        canonical = {
            "mission_id": str(self.mission_id),
            "mission_version": self.mission_version,
            "verified_criteria": sorted(self.verified_criteria),
            "completed_tasks": sorted(self.completed_tasks),
            "resolved_dependencies": sorted(self.resolved_dependencies),
            "verified_evidence_hashes": sorted(self.verified_evidence_hashes),
        }
        json_bytes = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()


class MissionProgressLedger:
    """Maintains and verifies canonical progress histories across mission execution."""

    def __init__(self, mission_id: UUID) -> None:
        self.mission_id = mission_id
        self._history: List[ProgressSnapshot] = []

    def record_progress(
        self,
        mission_version: int,
        verified_criteria: List[str],
        completed_tasks: List[str],
        blocked_tasks: Optional[List[str]] = None,
        failed_tasks: Optional[List[str]] = None,
        open_commitments: int = 0,
        resolved_dependencies: Optional[List[str]] = None,
        verified_evidence_hashes: Optional[List[str]] = None,
    ) -> ProgressSnapshot:
        """Records a new progress state and computes its cryptographic digest."""
        snapshot = ProgressSnapshot(
            mission_id=self.mission_id,
            mission_version=mission_version,
            verified_criteria=verified_criteria,
            completed_tasks=completed_tasks,
            blocked_tasks=blocked_tasks or [],
            failed_tasks=failed_tasks or [],
            open_commitments=open_commitments,
            resolved_dependencies=resolved_dependencies or [],
            verified_evidence_hashes=verified_evidence_hashes or [],
            last_progress_at=datetime.now(timezone.utc),
        )
        snapshot.progress_digest = snapshot.calculate_digest()
        self._history.append(snapshot)
        return snapshot

    @property
    def latest(self) -> Optional[ProgressSnapshot]:
        return self._history[-1] if self._history else None

    def has_advanced(self, previous_digest: str, current_digest: str) -> bool:
        """Determines whether canonical state advancement occurred between two digests."""
        return bool(previous_digest and current_digest and previous_digest != current_digest)
