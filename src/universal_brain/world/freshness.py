"""
Universal Brain - Freshness Engine & Temporal Expiry
Implements Sections 41-44 of Milestone M8 Specification (M8-INV-04, M8-INV-14).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.schemas import FreshnessStatus, WorldPropertyAssertion


class FreshnessEngine:
    """
    Evaluates temporal freshness and expiry of property assertions.
    Enforces that stale information is never represented as current truth (M8-INV-04),
    and re-evaluates all active assertions immediately post-recovery (M8-INV-14).
    """

    DEFAULT_POLICY = {
        "expected_frequency_sec": 5.0,
        "stale_after_sec": 15.0,
        "expire_after_sec": 60.0,
    }

    def __init__(self, default_policy: Optional[Dict[str, float]] = None) -> None:
        self.default_policy = default_policy or self.DEFAULT_POLICY

    def calculate_freshness(
        self,
        observed_at: datetime,
        as_of_time: Optional[datetime] = None,
        policy: Optional[Dict[str, float]] = None,
    ) -> FreshnessStatus:
        """
        Determines freshness status based on elapsed time from observation.
        """
        now = as_of_time or datetime.now(timezone.utc)
        pol = policy or self.default_policy

        age = (now - observed_at).total_seconds()
        if age < 0:
            return FreshnessStatus.FRESH

        expected_freq = pol.get("expected_frequency_sec", 5.0)
        stale_after = pol.get("stale_after_sec", 15.0)
        expire_after = pol.get("expire_after_sec", 60.0)

        if age <= expected_freq:
            return FreshnessStatus.FRESH
        elif age <= stale_after:
            return FreshnessStatus.AGING
        elif age <= expire_after:
            return FreshnessStatus.STALE
        else:
            return FreshnessStatus.EXPIRED

    async def reconcile_freshness_after_restart(
        self,
        uow: UnitOfWork,
        as_of_time: Optional[datetime] = None,
    ) -> int:
        """
        Post-recovery barrier (M8-INV-14):
        Iterates over all active assertions in the database and recalculates their
        freshness status relative to the current post-downtime wall-clock.
        """
        assert uow.world_assertions is not None
        now = as_of_time or datetime.now(timezone.utc)
        active_assertions = await uow.world_assertions.list_all_active_assertions()

        updated_count = 0
        for a in active_assertions:
            new_status = self.calculate_freshness(a.valid_from, as_of_time=now)
            if new_status != a.freshness_status:
                await uow.world_assertions.update_assertion_with_version(
                    assertion_id=a.assertion_id,
                    expected_version=a.assertion_version,
                    new_status=a.status.value,
                    new_freshness=new_status.value,
                )
                updated_count += 1

        return updated_count
