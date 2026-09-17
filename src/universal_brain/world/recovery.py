"""
Universal Brain - World Model Post-Crash Recovery Manager
Implements Sections 110-112 of Milestone M8 Specification (M8-INV-14, M8-INV-19).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.freshness import FreshnessEngine


class WorldRecoveryManager:
    """
    Coordinates World Model recovery following an unclean shutdown or host restart.
    Recalculates freshness across all active assertions before declaring projection ready (M8-INV-14),
    and fences stale world processors from older kernel epochs (M8-INV-19).
    """

    def __init__(self, freshness_engine: Optional[FreshnessEngine] = None) -> None:
        self.freshness_engine = freshness_engine or FreshnessEngine()

    async def recover_world_state(
        self,
        uow: UnitOfWork,
        current_epoch: int,
        as_of_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Executes startup recovery pipeline for the World Model.
        """
        now = as_of_time or datetime.now(timezone.utc)
        assert uow.world_assertions is not None
        assert uow.world_entities is not None
        assert uow.world_processor_leases is not None

        # 1. Freshness recalculation barrier (M8-INV-14)
        updated_freshness_count = await self.freshness_engine.reconcile_freshness_after_restart(
            uow=uow,
            as_of_time=now,
        )

        # 2. Acquire or fence world processor lease for new epoch
        lease = await uow.world_processor_leases.get_lease("DEFAULT")
        if lease and lease.kernel_epoch < current_epoch:
            # Lease belongs to old epoch, fence it
            lease.status = "FENCED"

        # 3. Collect recovered statistics
        entities = await uow.world_entities.list_entities()
        active_assertions = await uow.world_assertions.list_all_active_assertions()

        return {
            "kernel_epoch": current_epoch,
            "freshness_recalculated_count": updated_freshness_count,
            "recovered_entities_count": len(entities),
            "active_assertions_count": len(active_assertions),
            "readiness": "READY",
        }
