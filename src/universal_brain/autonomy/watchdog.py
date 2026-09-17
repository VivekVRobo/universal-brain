"""
Universal Brain - Mission Progress Watchdog

Implements M7 Sections 44-46 and Invariant M7-INV-09:
- Monitors genuine state/evidence advancement;
- Flags NO_PROGRESS when activity occurs without advancing the progress digest;
- Drives deterministic replanning and escalation ladders.
"""

from __future__ import annotations

from typing import Dict, Optional
from uuid import UUID

from universal_brain.autonomy.errors import NoProgressError
from universal_brain.autonomy.progress import MissionProgressLedger


class ProgressWatchdog:
    """Detects stagnated execution loops where activity continues without progress."""

    def __init__(self, max_operations_without_progress: int = 5) -> None:
        self.max_ops = max_operations_without_progress
        self._last_digests: Dict[UUID, str] = {}
        self._ops_since_progress: Dict[UUID, int] = {}

    def observe_activity(
        self,
        mission_id: UUID,
        current_progress_digest: str,
    ) -> None:
        """
        Records an operation and verifies progress digest advancement (M7 Section 45).
        Raises NoProgressError if operations exceed threshold without progress advancement.
        """
        last_digest = self._last_digests.get(mission_id)

        if not last_digest:
            self._last_digests[mission_id] = current_progress_digest
            self._ops_since_progress[mission_id] = 0
            return

        if current_progress_digest != last_digest:
            # Genuine advancement detected! Reset counter
            self._last_digests[mission_id] = current_progress_digest
            self._ops_since_progress[mission_id] = 0
        else:
            # Activity occurred without digest advancement
            ops = self._ops_since_progress.get(mission_id, 0) + 1
            self._ops_since_progress[mission_id] = ops

            if ops >= self.max_ops:
                raise NoProgressError(
                    f"NO_PROGRESS detected for mission {mission_id}: {ops} operations executed without progress advancement.",
                    mission_id=str(mission_id),
                )

    def reset(self, mission_id: UUID) -> None:
        """Resets watchdog counters upon replan or operator intervention."""
        self._ops_since_progress[mission_id] = 0
        self._last_digests.pop(mission_id, None)
