"""
Universal Brain - Unit Tests for M8 Fusion & Contradiction Resolution
"""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from universal_brain.kernel.event_store import EventStore
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.assertions import WorldAssertionManager
from universal_brain.world.contradictions import WorldContradictionEngine
from universal_brain.world.entities import WorldEntityManager
from universal_brain.world.fusion import ObservationFusionEngine
from universal_brain.world.reliability import SourceReliabilityTracker
from universal_brain.world.schemas import (
    AssertionStateClass,
    AssertionStatus,
    Observation,
    ObservationType,
    ResolutionStatus,
)


def test_observation_fusion_continuous_and_outliers() -> None:
    tracker = SourceReliabilityTracker()
    fusion_engine = ObservationFusionEngine(reliability_tracker=tracker)
    now = datetime.now(timezone.utc)
    sess_id = uuid4()

    obs1 = Observation(
        source_id="therm_1",
        source_session_id=sess_id,
        source_observation_id="t1",
        observation_type=ObservationType.MEASUREMENT,
        subject_ref="motor_1",
        property_key="temperature",
        value=50.0,
        unit="C",
        observed_at=now,
    )
    obs2 = Observation(
        source_id="therm_2",
        source_session_id=sess_id,
        source_observation_id="t2",
        observation_type=ObservationType.MEASUREMENT,
        subject_ref="motor_1",
        property_key="temperature",
        value=52.0,
        unit="C",
        observed_at=now,
    )
    # Extreme outlier (sensor fault)
    obs_outlier = Observation(
        source_id="therm_bad",
        source_session_id=sess_id,
        source_observation_id="t3",
        observation_type=ObservationType.MEASUREMENT,
        subject_ref="motor_1",
        property_key="temperature",
        value=350.0,  # 300 degrees higher!
        unit="C",
        observed_at=now,
    )

    fused = fusion_engine.fuse_continuous([obs1, obs2, obs_outlier])
    # Fused value should be around 51.0, and outlier rejected
    assert 50.0 <= fused.value <= 52.0
    assert obs_outlier.observation_id in fused.outlier_observations
    assert obs1.observation_id in fused.supporting_observations
    assert obs2.observation_id in fused.supporting_observations
    assert fused.fusion_policy_version == 1


@pytest.mark.asyncio
async def test_contradiction_detection_and_verification_resolution(tmp_path: Any) -> None:
    db_path = tmp_path / "m8_contra_1.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    event_store = EventStore()
    now = datetime.now(timezone.utc)

    async with UnitOfWork(db_manager) as uow:
        e_mgr = WorldEntityManager(uow)
        await e_mgr.create_entity("valve_01", "DEVICE", "Main Water Valve")

        a_mgr = WorldAssertionManager(uow)
        # Assertion A: Camera says OPEN
        a_cam = await a_mgr.assert_property(
            entity_id="valve_01",
            property_key="status",
            value="OPEN",
            confidence=0.9,
            valid_from=now,
        )
        # Assertion B: Pressure sensor says CLOSED at the exact same time
        a_press = await a_mgr.assert_property(
            entity_id="valve_01",
            property_key="status",
            value="CLOSED",
            confidence=0.95,
            valid_from=now,
        )

        c_engine = WorldContradictionEngine(uow, event_store)
        contra = await c_engine.check_contradiction(a_cam, a_press)
        assert contra is not None
        assert contra.temporal_overlap is True
        assert contra.resolution_status == ResolutionStatus.OPEN
        await uow.commit()

    # Verify both assertions are marked CONTRADICTED
    async with UnitOfWork(db_manager) as uow:
        a_mgr = WorldAssertionManager(uow)
        cam_check = await a_mgr.uow.world_assertions.get_assertion(a_cam.assertion_id)
        assert cam_check is not None
        assert cam_check.status == AssertionStatus.CONTRADICTED

    # Resolve contradiction via independent verification evidence (e.g. operator manual inspection)
    async with UnitOfWork(db_manager) as uow:
        c_engine = WorldContradictionEngine(uow, event_store)
        resolved_c = await c_engine.resolve_contradiction(
            contradiction_id=contra.contradiction_id,
            winning_assertion_id=a_press.assertion_id,
            verification_evidence="Operator physical inspection confirmed valve is mechanically CLOSED.",
        )
        assert resolved_c.resolution_status == ResolutionStatus.RESOLVED
        assert resolved_c.winning_assertion_id == a_press.assertion_id
        await uow.commit()

    # Winning assertion is now ACTIVE, losing assertion is REJECTED
    async with UnitOfWork(db_manager) as uow:
        a_mgr = WorldAssertionManager(uow)
        winner = await a_mgr.uow.world_assertions.get_assertion(a_press.assertion_id)
        loser = await a_mgr.uow.world_assertions.get_assertion(a_cam.assertion_id)
        assert winner is not None
        assert winner.status == AssertionStatus.ACTIVE
        assert loser is not None
        assert loser.status == AssertionStatus.REJECTED

    await db_manager.close()
