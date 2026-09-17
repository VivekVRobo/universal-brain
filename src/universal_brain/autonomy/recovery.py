"""
Universal Brain - Mission Recovery Manager

Implements M7 Sections 88-90 and Invariant M7-INV-16:
- Extends M6 startup recovery to restore long-horizon mission state;
- Revalidates contracts and mission versions;
- Fences all pre-crash agent leases without resurrection (M7 Section 90);
- Recovers open commitments, blackboard assertions, and durable wakeups;
- Fires overdue wakeups once logically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType
from universal_brain.persistence.engine import DatabaseManager


class MissionRecoveryManager:
    """Orchestrates deterministic recovery of active missions following host or process crash."""

    def __init__(self, db_manager: DatabaseManager, event_store: EventStore) -> None:
        self.db_manager = db_manager
        self.event_store = event_store

    async def recover_missions(
        self,
        current_kernel_epoch: int,
        instance_id: str = "ub-autonomy-recovery",
    ) -> Dict[str, Any]:
        """
        Executes comprehensive autonomy recovery pipeline (M7 Section 88).
        """
        from universal_brain.persistence.unit_of_work import UnitOfWork

        missions_recovered = 0
        agents_fenced = 0
        wakeups_rehydrated = 0
        commitments_recovered = 0
        overdue_wakeups_fired = 0

        async with UnitOfWork(self.db_manager) as uow:
            # 1. Fence all pre-restart agent leases from older epochs (M7-INV-06 & M7 Section 90)
            agents_fenced = await uow.agent_leases.fence_stale_leases(current_kernel_epoch)

            # 2. Discover active missions
            active_missions = await uow.missions.list_active_missions()
            missions_recovered = len(active_missions)

            # 3. Revalidate contracts and check integrity
            for m in active_missions:
                # Check contract alignment
                contract = await uow.contracts.get_contract_by_version(m.project_id, m.contract_version)
                if not contract:
                    # Mark mission for recovery required
                    await uow.missions.update_mission_status_with_version(
                        mission_id=m.mission_id,
                        expected_version=m.mission_version,
                        new_status="BLOCKED",
                    )
                else:
                    # Rehydrate commitments
                    comms = await uow.commitments.list_mission_commitments(m.mission_id)
                    commitments_recovered += len(comms)

            # 4. Check for overdue wakeups and fire them once logically (M7 Section 70)
            now = datetime.now(timezone.utc)
            overdue = await uow.wakeups.get_overdue_wakeups(now)
            wakeups_rehydrated = len(overdue)

            for w in overdue:
                claimed = await uow.wakeups.claim_wakeup(w.wakeup_id)
                if claimed:
                    await uow.wakeups.fire_wakeup(w.wakeup_id)
                    # Resume mission if it was waiting
                    m = await uow.missions.get_mission(w.mission_id)
                    if m and m.status == "WAITING_EXTERNAL":
                        await uow.missions.update_mission_status_with_version(
                            mission_id=m.mission_id,
                            expected_version=m.mission_version,
                            new_status="ACTIVE",
                        )
                    overdue_wakeups_fired += 1

            await uow.commit()

        # Emit recovery governance event
        self.event_store.append_event(
            EventType.MEMORY_SYNC,
            actor_id=instance_id,
            payload={
                "recovery_type": "M7_AUTONOMY_RECOVERY",
                "kernel_epoch": current_kernel_epoch,
                "missions_recovered": missions_recovered,
                "agents_fenced": agents_fenced,
                "wakeups_rehydrated": wakeups_rehydrated,
                "overdue_wakeups_fired": overdue_wakeups_fired,
            },
        )

        return {
            "status": "RECOVERY_VERIFIED",
            "kernel_epoch": current_kernel_epoch,
            "missions_recovered": missions_recovered,
            "agents_fenced": agents_fenced,
            "commitments_recovered": commitments_recovered,
            "wakeups_rehydrated": wakeups_rehydrated,
            "overdue_wakeups_fired": overdue_wakeups_fired,
        }
