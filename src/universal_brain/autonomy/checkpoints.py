"""
Universal Brain - Mission Checkpoint Manager

Implements M7 Sections 86 & 87:
- Creates canonical logical recovery summaries of long-horizon mission state;
- Computes deterministic SHA-256 checkpoint_digest across criteria, tasks, and blackboard;
- Supports periodic, milestone-triggered, and pre-risk checkpointing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from universal_brain.autonomy.schemas import (
    Mission,
    MissionBudgetState,
    MissionCheckpoint,
)


class MissionCheckpointManager:
    """Creates and verifies logical mission recovery checkpoints."""

    def __init__(self) -> None:
        self._checkpoints: Dict[UUID, List[MissionCheckpoint]] = {}

    def capture_checkpoint(
        self,
        mission: Mission,
        completed_criteria: List[str],
        task_state_digest: str,
        progress_digest: str,
        blackboard_digest: str,
        commitment_digest: str = "",
        dependency_digest: str = "",
        budget_state: MissionBudgetState = MissionBudgetState.NORMAL,
        open_escalations: int = 0,
        open_wakeups: int = 0,
    ) -> MissionCheckpoint:
        """Captures and seals a canonical mission checkpoint (M7 Section 86)."""
        cp = MissionCheckpoint(
            mission_id=mission.mission_id,
            mission_version=mission.mission_version,
            plan_id=mission.current_plan_id,
            plan_version=mission.current_plan_version,
            completed_criteria=completed_criteria,
            task_state_digest=task_state_digest,
            progress_digest=progress_digest,
            blackboard_digest=blackboard_digest,
            commitment_digest=commitment_digest,
            dependency_digest=dependency_digest,
            budget_state=budget_state,
            open_escalations=open_escalations,
            open_wakeups=open_wakeups,
            created_at=datetime.now(timezone.utc),
        )
        cp.checkpoint_digest = cp.calculate_digest()

        if mission.mission_id not in self._checkpoints:
            self._checkpoints[mission.mission_id] = []
        self._checkpoints[mission.mission_id].append(cp)
        return cp

    def get_latest_checkpoint(self, mission_id: UUID) -> Optional[MissionCheckpoint]:
        cps = self._checkpoints.get(mission_id)
        return cps[-1] if cps else None
