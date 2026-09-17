"""
Universal Brain - Unit Tests for M8 Change Detection, Watches & Subscriptions
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from universal_brain.kernel.event_store import EventStore
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.changes import WorldChangeDetector
from universal_brain.world.schemas import (
    AssertionStateClass,
    FreshnessStatus,
    WatchStatus,
    WorldPropertyAssertion,
)
from universal_brain.world.subscriptions import WorldSubscriptionRegistry
from universal_brain.world.watches import WorldWatchManager


def test_world_change_detector_significance_and_debounce() -> None:
    event_store = EventStore()
    detector = WorldChangeDetector(
        event_store=event_store,
        numeric_delta_threshold=0.5,
        pose_distance_threshold=0.1,  # 10cm
    )

    # 1. Negligible noise change (< 0.5) -> Not significant
    assert detector.is_significant_change("temperature", 50.0, 50.2) is False

    # 2. Significant change (>= 0.5) -> Significant
    assert detector.is_significant_change("temperature", 50.0, 51.0) is True

    # 3. Pose change: 5cm delta -> Not significant (< 10cm threshold)
    p1 = {"x": 0.0, "y": 0.0, "z": 0.0}
    p2 = {"x": 0.05, "y": 0.0, "z": 0.0}
    assert detector.is_significant_change("pose", p1, p2) is False

    # 4. Pose change: 20cm delta -> Significant
    p3 = {"x": 0.20, "y": 0.0, "z": 0.0}
    assert detector.is_significant_change("pose", p1, p3) is True

    # 5. Process change emits event
    evt = detector.process_change("motor_1", "temperature", 50.0, 51.5)
    assert evt is not None
    assert evt.property_key == "temperature"
    assert evt.new_value == 51.5


@pytest.mark.asyncio
async def test_world_watch_freshness_barrier_and_exactly_once(tmp_path: Any) -> None:
    db_path = tmp_path / "m8_watch_1.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    event_store = EventStore()
    mission_id = uuid4()

    async with UnitOfWork(db_manager) as uow:
        w_mgr = WorldWatchManager(uow, event_store)
        watch = await w_mgr.create_watch(
            mission_id=mission_id,
            entity_id="service_api",
            property_key="status",
            expected_value="FAILED",
            operator="==",
            required_freshness=FreshnessStatus.FRESH,
        )
        assert watch.status == WatchStatus.ACTIVE
        await uow.commit()

    # 1. Assertion matches value "FAILED" but is STALE -> Watch does NOT trigger (Freshness barrier)
    stale_assertion = WorldPropertyAssertion(
        entity_id="service_api",
        property_key="status",
        value="FAILED",
        freshness_status=FreshnessStatus.STALE,
    )
    async with UnitOfWork(db_manager) as uow:
        w_mgr = WorldWatchManager(uow, event_store)
        triggered = await w_mgr.evaluate_watches_for_assertion(stale_assertion)
        assert len(triggered) == 0

    # 2. Assertion is FRESH and matches value -> Watch TRIGGERS
    fresh_assertion = WorldPropertyAssertion(
        entity_id="service_api",
        property_key="status",
        value="FAILED",
        freshness_status=FreshnessStatus.FRESH,
    )
    async with UnitOfWork(db_manager) as uow:
        w_mgr = WorldWatchManager(uow, event_store)
        triggered = await w_mgr.evaluate_watches_for_assertion(fresh_assertion)
        assert len(triggered) == 1
        assert triggered[0].watch_id == watch.watch_id
        await uow.commit()

    # 3. Duplicate evaluation -> Exactly-once trigger (M8-INV-08): does not re-trigger
    async with UnitOfWork(db_manager) as uow:
        w_mgr = WorldWatchManager(uow, event_store)
        triggered_dup = await w_mgr.evaluate_watches_for_assertion(fresh_assertion)
        assert len(triggered_dup) == 0

    await db_manager.close()


def test_world_subscription_registry() -> None:
    registry = WorldSubscriptionRegistry()
    m1 = uuid4()
    m2 = uuid4()

    registry.subscribe(mission_id=m1, entity_id="robot_01")
    registry.subscribe(mission_id=m2, entity_id="robot_01", property_key="battery_level")

    # Subs for robot_01 without property -> m1
    subs_entity = registry.get_subscribers(entity_id="robot_01")
    assert m1 in subs_entity
    assert m2 not in subs_entity

    # Subs for robot_01:battery_level -> both m1 (subscribed to whole entity) and m2
    subs_prop = registry.get_subscribers(entity_id="robot_01", property_key="battery_level")
    assert m1 in subs_prop
    assert m2 in subs_prop
