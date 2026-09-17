"""
Universal Brain - Unit Tests for M8 Freshness & Source Reliability
"""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.assertions import WorldAssertionManager
from universal_brain.world.entities import WorldEntityManager
from universal_brain.world.freshness import FreshnessEngine
from universal_brain.world.reliability import SourceReliabilityTracker
from universal_brain.world.schemas import FreshnessStatus


def test_freshness_engine_status_progression() -> None:
    engine = FreshnessEngine(
        default_policy={
            "expected_frequency_sec": 5.0,
            "stale_after_sec": 15.0,
            "expire_after_sec": 60.0,
        }
    )
    t0 = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)

    # Within 5s -> FRESH
    t_fresh = t0 + timedelta(seconds=3)
    assert engine.calculate_freshness(t0, as_of_time=t_fresh) == FreshnessStatus.FRESH

    # 10s -> AGING
    t_aging = t0 + timedelta(seconds=10)
    assert engine.calculate_freshness(t0, as_of_time=t_aging) == FreshnessStatus.AGING

    # 30s -> STALE
    t_stale = t0 + timedelta(seconds=30)
    assert engine.calculate_freshness(t0, as_of_time=t_stale) == FreshnessStatus.STALE

    # 90s -> EXPIRED
    t_expired = t0 + timedelta(seconds=90)
    assert engine.calculate_freshness(t0, as_of_time=t_expired) == FreshnessStatus.EXPIRED


@pytest.mark.asyncio
async def test_freshness_post_restart_reconciliation_barrier(tmp_path: Any) -> None:
    db_path = tmp_path / "m8_fresh_1.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    t_before_crash = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    t_after_reboot = t_before_crash + timedelta(seconds=120)  # 2 minutes down

    async with UnitOfWork(db_manager) as uow:
        e_mgr = WorldEntityManager(uow)
        await e_mgr.create_entity("robot_1", "ROBOT", "Robot 1")
        a_mgr = WorldAssertionManager(uow)
        # Stored before crash as FRESH
        await a_mgr.assert_property(
            entity_id="robot_1",
            property_key="battery_level",
            value=85.0,
            valid_from=t_before_crash,
            freshness_status=FreshnessStatus.FRESH,
        )
        await uow.commit()

    # Post-crash barrier runs
    freshness_engine = FreshnessEngine()
    async with UnitOfWork(db_manager) as uow:
        updated_count = await freshness_engine.reconcile_freshness_after_restart(
            uow=uow,
            as_of_time=t_after_reboot,
        )
        assert updated_count == 1
        await uow.commit()

    # Verify assertion is now EXPIRED/STALE relative to new clock
    async with UnitOfWork(db_manager) as uow:
        a_mgr = WorldAssertionManager(uow)
        a = await a_mgr.get_active_assertion("robot_1", "battery_level")
        assert a is not None
        assert a.freshness_status == FreshnessStatus.EXPIRED

    await db_manager.close()


def test_source_reliability_drift_and_hysteresis() -> None:
    tracker = SourceReliabilityTracker(recovery_threshold_consecutive=3)

    # Initial perfect score
    rec = tracker.get_or_create_record("lidar_top")
    assert rec.reliability_score == 1.0

    # Record 2 successes
    tracker.record_success("lidar_top")
    tracker.record_success("lidar_top")
    assert tracker.get_or_create_record("lidar_top").confirmed == 2

    # Record contradiction -> score drops
    tracker.record_contradiction("lidar_top")
    rec_after_contra = tracker.get_or_create_record("lidar_top")
    assert rec_after_contra.reliability_score < 1.0
    assert tracker.check_recovery_eligibility("lidar_top") is False

    # Inject persistent sensor drift via outliers
    tracker.record_outlier("lidar_top", value=10.0, reference=5.0)
    tracker.record_outlier("lidar_top", value=10.2, reference=5.0)
    tracker.record_outlier("lidar_top", value=10.1, reference=5.0)

    rec_drift = tracker.get_or_create_record("lidar_top")
    assert rec_drift.drift_detected is True

    # Test recovery hysteresis: needs 3 consecutive successes
    tracker.record_success("lidar_top")
    assert tracker.check_recovery_eligibility("lidar_top") is False
    tracker.record_success("lidar_top")
    assert tracker.check_recovery_eligibility("lidar_top") is False
    tracker.record_success("lidar_top")
    assert tracker.check_recovery_eligibility("lidar_top") is True
