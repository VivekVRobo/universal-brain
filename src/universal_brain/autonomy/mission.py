"""
Universal Brain - Mission State Machine & Controller

Implements M7 Sections 8-12:
- Strict lifecycle transition validation;
- Server-side guard enforcement;
- Optimistic versioning validation (STALE_MISSION_STATE);
- Idempotent command processing;
- Mission != Plan separation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from universal_brain.alignment.contract import AlignmentContract
from universal_brain.autonomy.errors import MissionStateError, MissionVersionConflictError
from universal_brain.autonomy.schemas import Mission, MissionStatus


class MissionStateMachine:
    """Enforces deterministic lifecycle transitions and guards (M7 Sections 8 & 9)."""

    VALID_TRANSITIONS: Dict[MissionStatus, Set[MissionStatus]] = {
        MissionStatus.DRAFT: {MissionStatus.PROPOSED, MissionStatus.CANCELLED},
        MissionStatus.PROPOSED: {MissionStatus.VALIDATING, MissionStatus.CANCELLED},
        MissionStatus.VALIDATING: {MissionStatus.READY, MissionStatus.DRAFT, MissionStatus.CANCELLED},
        MissionStatus.READY: {MissionStatus.ACTIVE, MissionStatus.PAUSED, MissionStatus.CANCELLED},
        MissionStatus.ACTIVE: {
            MissionStatus.PAUSED,
            MissionStatus.WAITING_EXTERNAL,
            MissionStatus.BLOCKED,
            MissionStatus.ESCALATED,
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        },
        MissionStatus.PAUSED: {MissionStatus.ACTIVE, MissionStatus.CANCELLED},
        MissionStatus.WAITING_EXTERNAL: {
            MissionStatus.ACTIVE,
            MissionStatus.BLOCKED,
            MissionStatus.ESCALATED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        },
        MissionStatus.BLOCKED: {
            MissionStatus.ACTIVE,
            MissionStatus.ESCALATED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        },
        MissionStatus.ESCALATED: {
            MissionStatus.ACTIVE,
            MissionStatus.BLOCKED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        },
        MissionStatus.COMPLETED: set(),  # Terminal state
        MissionStatus.FAILED: set(),     # Terminal state
        MissionStatus.CANCELLED: set(),  # Terminal state
    }

    @classmethod
    def validate_transition(
        cls,
        current_status: MissionStatus,
        target_status: MissionStatus,
        mission: Optional[Mission] = None,
        contract: Optional[AlignmentContract] = None,
        verified_criteria: Optional[List[str]] = None,
    ) -> None:
        """Validates that a status transition is permitted and satisfies constitutional guards."""
        allowed = cls.VALID_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            raise MissionStateError(
                f"Illegal mission transition from {current_status.value} to {target_status.value}."
            )

        # Guard: READY -> ACTIVE requires an active contract
        if target_status == MissionStatus.ACTIVE and current_status == MissionStatus.READY:
            if contract and contract.status.value != "active":
                raise MissionStateError("Cannot activate mission: bound contract is not active.")

        # Guard: ACTIVE -> COMPLETED requires all mandatory criteria verified
        if target_status == MissionStatus.COMPLETED and mission:
            required = [c.get("criterion_id") for c in mission.completion_criteria if c.get("mandatory", True)]
            verified = set(verified_criteria or [])
            missing = [cid for cid in required if cid not in verified]
            if missing:
                raise MissionStateError(
                    f"Cannot complete mission: missing mandatory criteria verification: {missing}"
                )


class MissionController:
    """Orchestrates mission mutations, idempotency, and version advancement."""

    def __init__(self) -> None:
        self._processed_commands: Dict[str, Any] = {}

    def transition(
        self,
        mission: Mission,
        target_status: MissionStatus,
        expected_version: int,
        idempotency_key: Optional[str] = None,
        contract: Optional[AlignmentContract] = None,
        verified_criteria: Optional[List[str]] = None,
    ) -> Mission:
        """Transitions mission status with version check and idempotency deduplication."""
        if idempotency_key and idempotency_key in self._processed_commands:
            return self._processed_commands[idempotency_key]

        if mission.mission_version != expected_version:
            raise MissionVersionConflictError(
                f"Optimistic concurrency failure: mission version is {mission.mission_version}, expected {expected_version}",
                mission_id=str(mission.mission_id),
            )

        MissionStateMachine.validate_transition(
            current_status=mission.status,
            target_status=target_status,
            mission=mission,
            contract=contract,
            verified_criteria=verified_criteria,
        )

        mission.status = target_status
        mission.mission_version += 1
        mission.updated_at = datetime.now(timezone.utc)

        if idempotency_key:
            self._processed_commands[idempotency_key] = mission

        return mission
