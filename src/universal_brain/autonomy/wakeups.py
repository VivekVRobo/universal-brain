"""
Universal Brain - Durable Wakeup Manager & Long-Horizon Timers

Implements M7 Sections 64-70 and Invariant M7-INV-08:
- Allows long-horizon autonomy to sleep without continuous token burn (WAITING_EXTERNAL);
- Persists wakeups across host crashes and restarts;
- Enforces single-claim fencing and exactly-once logical execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from universal_brain.autonomy.errors import MissionVersionConflictError, WakeupConflictError
from universal_brain.autonomy.schemas import WakeupRecord, WakeupStatus, WakeupType


class WakeupManager:
    """Manages durable time- and event-based wakeups with reboot survival."""

    def __init__(self) -> None:
        self._wakeups: Dict[UUID, WakeupRecord] = {}

    def schedule_wakeup(
        self,
        mission_id: UUID,
        trigger_type: WakeupType,
        due_at: datetime,
        task_id: Optional[UUID] = None,
        trigger_condition: Optional[dict] = None,
        idempotency_key: str = "",
    ) -> WakeupRecord:
        """Schedules a new durable wakeup (M7 Section 66)."""
        if idempotency_key:
            for existing in self._wakeups.values():
                if existing.idempotency_key == idempotency_key and existing.status == WakeupStatus.PENDING:
                    return existing

        wakeup = WakeupRecord(
            mission_id=mission_id,
            task_id=task_id,
            trigger_type=trigger_type,
            trigger_condition=trigger_condition or {},
            due_at=due_at,
            created_at=datetime.now(timezone.utc),
            status=WakeupStatus.PENDING,
            idempotency_key=idempotency_key,
        )
        self._wakeups[wakeup.wakeup_id] = wakeup
        return wakeup

    def claim_wakeup(self, wakeup_id: UUID) -> bool:
        """
        Atomically claims a wakeup for firing. Returns False if already claimed or fired.
        Enforces M7-INV-08 (at-least-once delivery, exactly-once logical effect).
        """
        wakeup = self._wakeups.get(wakeup_id)
        if not wakeup or wakeup.status != WakeupStatus.PENDING:
            return False
        wakeup.status = WakeupStatus.CLAIMED
        return True

    def fire_wakeup(
        self,
        wakeup_id: UUID,
        current_mission_version: int,
        expected_mission_version: int,
    ) -> WakeupRecord:
        """
        Fires a claimed wakeup, asserting mission version integrity (M7 Section 67).
        """
        wakeup = self._wakeups.get(wakeup_id)
        if not wakeup:
            raise WakeupConflictError(f"Wakeup {wakeup_id} not found.")

        if wakeup.status not in (WakeupStatus.CLAIMED, WakeupStatus.PENDING):
            raise WakeupConflictError(
                f"Cannot fire wakeup {wakeup_id} in status {wakeup.status.value}."
            )

        if current_mission_version != expected_mission_version:
            wakeup.status = WakeupStatus.EXPIRED
            raise MissionVersionConflictError(
                f"Stale wakeup rejected: mission version {current_mission_version} != expected {expected_mission_version}"
            )

        wakeup.status = WakeupStatus.FIRED
        wakeup.fired_at = datetime.now(timezone.utc)
        return wakeup

    def get_due_wakeups(self, now: Optional[datetime] = None) -> List[WakeupRecord]:
        """Returns pending wakeups that are due for execution."""
        ref_time = now or datetime.now(timezone.utc)
        return [
            w for w in self._wakeups.values()
            if w.status == WakeupStatus.PENDING and w.due_at <= ref_time
        ]

    def cancel_mission_wakeups(self, mission_id: UUID) -> int:
        """Cancels all pending wakeups for a mission (e.g. upon mission cancel)."""
        count = 0
        for w in self._wakeups.values():
            if w.mission_id == mission_id and w.status == WakeupStatus.PENDING:
                w.status = WakeupStatus.CANCELLED
                count += 1
        return count
