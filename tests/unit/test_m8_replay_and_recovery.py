"""
Universal Brain - Unit Tests for M8 World Replay & Recovery
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
from universal_brain.world.entities import WorldEntityManager
from universal_brain.world.recovery import WorldRecoveryManager
from universal_brain.world.replay import WorldReplayEngine
from universal_brain.world.schemas import (
    AssertionStateClass,
    FreshnessStatus,
    Observation,
    ObservationType,
)
from universal_brain.world.snapshots import WorldSnapshotManager


@pytest.mark.asyncio
async def test_world_snapshot_and_deterministic_replay(tmp_path: Any) -> None:
    db_path = tmp_path / "m8_replay_1.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    event_store = EventStore()
    now = datetime.now(timezone.utc)
    sess_id = uuid4()

    # Step 1: Record 3 canonical observations
    obs1 = Observation(
        source_id="camera_1",
        source_session_id=sess_id,
        source_observation_id="cam_01",
        source_sequence=1,
        observation_type=ObservationType.LOCATION,
        subject_ref="robot_01",
        property_key="pose",
        value={"x": 1.0, "y": 2.0, "z": 0.0},
        coordinate_frame="odom",
        observed_at=now,
    )
    obs2 = Observation(
        source_id="bms_1",
        source_session_id=sess_id,
        source_observation_id="bms_01",
        source_sequence=2,
        observation_type=ObservationType.MEASUREMENT,
        subject_ref="robot_01",
        property_key="battery_level",
        value=92.5,
        observed_at=now + timedelta(seconds=1),
    )

    async with UnitOfWork(db_manager) as uow:
        assert uow.observations is not None
        await uow.observations.save_observation(obs1)
        await uow.observations.save_observation(obs2)
        await uow.commit()

    # Step 2: Capture Snapshot
    async with UnitOfWork(db_manager) as uow:
        snap_mgr = WorldSnapshotManager(uow, event_store)
        snapshot = await snap_mgr.capture_snapshot(scope="GLOBAL", observation_head=2)
        assert len(snapshot.snapshot_digest) == 64
        await uow.commit()

    # Step 3: Execute replay into fresh clean db
    replay_db_path = tmp_path / "m8_replay_target.db"
    replay_db_mgr = DatabaseManager(database_url=f"sqlite+aiosqlite:///{replay_db_path}")
    await replay_db_mgr.init_db()
    await replay_db_mgr.create_tables()

    async with UnitOfWork(replay_db_mgr) as uow:
        replay_engine = WorldReplayEngine(uow, event_store)
        replay_res = await replay_engine.replay_from_observations(
            observations=[obs1, obs2],
            mode="HISTORICAL_EXACT",
        )
        assert replay_res["status"] == "VERIFIED_EXACT"
        assert len(replay_res["rebuilt_digest"]) == 64
        assert "robot_01" in replay_res["entities"]
        await uow.commit()

    # Verify entities and assertions in replayed database
    async with UnitOfWork(replay_db_mgr) as uow:
        e_mgr = WorldEntityManager(uow)
        replayed_robot = await e_mgr.get_entity("robot_01")
        assert replayed_robot is not None

        a_mgr = WorldAssertionManager(uow)
        battery = await a_mgr.get_active_assertion("robot_01", "battery_level")
        assert battery is not None
        assert battery.value == 92.5

    await db_manager.close()
    await replay_db_mgr.close()


@pytest.mark.asyncio
async def test_world_recovery_pipeline(tmp_path: Any) -> None:
    db_path = tmp_path / "m8_recov_1.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    t_pre_crash = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
    t_post_boot = t_pre_crash + timedelta(seconds=300)

    async with UnitOfWork(db_manager) as uow:
        e_mgr = WorldEntityManager(uow)
        await e_mgr.create_entity("service_worker", "SERVICE", "Worker Daemon")

        a_mgr = WorldAssertionManager(uow)
        await a_mgr.assert_property(
            entity_id="service_worker",
            property_key="status",
            value="HEALTHY",
            valid_from=t_pre_crash,
            freshness_status=FreshnessStatus.FRESH,
        )

        assert uow.world_processor_leases is not None
        await uow.world_processor_leases.acquire_or_renew_lease(
            partition_key="DEFAULT",
            processor_id="processor_old",
            generation=1,
            epoch=1,  # Old epoch!
            duration_sec=60,
        )
        await uow.commit()

    # Post-crash recovery runs under Kernel Epoch 2
    recovery_mgr = WorldRecoveryManager()
    async with UnitOfWork(db_manager) as uow:
        summary = await recovery_mgr.recover_world_state(
            uow=uow,
            current_epoch=2,
            as_of_time=t_post_boot,
        )
        assert summary["kernel_epoch"] == 2
        assert summary["readiness"] == "READY"
        assert summary["freshness_recalculated_count"] == 1
        await uow.commit()

    # Verify old lease was fenced
    async with UnitOfWork(db_manager) as uow:
        assert uow.world_processor_leases is not None
        lease = await uow.world_processor_leases.get_lease("DEFAULT")
        assert lease is not None
        assert lease.status == "FENCED"

    await db_manager.close()
