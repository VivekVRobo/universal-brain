"""
Universal Brain - Anti-Loop Engine & Fingerprint Persistence

Implements M7 Sections 47-49 and Invariant M7-INV-10:
- Computes deterministic fingerprints across repeated operations;
- Tracks occurrences in-memory and binds to database persistence across reboots;
- Prevents infinite loops through progressive multi-stage escalation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, Optional, Tuple
from uuid import UUID

from universal_brain.autonomy.errors import AutonomyLoopError


class AntiLoopEngine:
    """Detects and bounds repetitive failed cognitive/execution cycles."""

    def __init__(self, max_identical_operations: int = 3) -> None:
        self.max_identical = max_identical_operations
        # In-memory map: (mission_id, fingerprint_hash) -> count
        self._counts: Dict[Tuple[UUID, str], int] = {}

    @staticmethod
    def compute_fingerprint(
        mission_id: UUID,
        task_id: UUID,
        operation_type: str,
        target: str,
        input_digest: str,
        failure_class: str,
    ) -> str:
        """Computes deterministic SHA-256 fingerprint for an operation attempt."""
        payload = {
            "mission_id": str(mission_id),
            "task_id": str(task_id),
            "operation_type": operation_type,
            "target": target,
            "input_digest": input_digest,
            "failure_class": failure_class,
        }
        json_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()

    def record_attempt(
        self,
        mission_id: UUID,
        task_id: UUID,
        operation_type: str,
        target: str,
        input_digest: str,
        failure_class: str,
    ) -> int:
        """
        Records an operation attempt and trips AutonomyLoopError when threshold is breached.
        Enforces M7-INV-10.
        """
        fp = self.compute_fingerprint(
            mission_id=mission_id,
            task_id=task_id,
            operation_type=operation_type,
            target=target,
            input_digest=input_digest,
            failure_class=failure_class,
        )
        key = (mission_id, fp)
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count

        if count >= self.max_identical:
            raise AutonomyLoopError(
                f"AUTONOMY_LOOP_DETECTED for mission {mission_id}: operation '{operation_type}' on '{target}' repeated {count} times (fingerprint: {fp[:12]}...).",
                mission_id=str(mission_id),
            )
        return count

    def load_persisted_count(self, mission_id: UUID, fingerprint_hash: str, count: int) -> None:
        """Rehydrates counts from database after restart (M7 Section 48)."""
        self._counts[(mission_id, fingerprint_hash)] = count

    def reset_for_task(self, mission_id: UUID) -> None:
        """Clears fingerprints for a mission upon successful strategy swap or replan."""
        keys_to_remove = [k for k in self._counts if k[0] == mission_id]
        for k in keys_to_remove:
            self._counts.pop(k, None)
