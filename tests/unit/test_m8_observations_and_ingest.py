"""
Universal Brain - Unit Tests for M8 Observations & Ingest Gate
"""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.errors import (
    ObservationIntegrityError,
    ObservationReplayError,
    SourceAuthenticationError,
    SourceFencedError,
    SourceScopeError,
    TemporalConsistencyError,
)
from universal_brain.world.ingest import ObservationIngestGate
from universal_brain.world.schemas import (
    Observation,
    ObservationSource,
    ObservationType,
    SourceTrustClass,
    SourceType,
)
from universal_brain.world.sessions import SourceSessionManager
from universal_brain.world.sources import ObservationSourceRegistry


@pytest.mark.asyncio
async def test_observation_valid_ingest_and_digest(tmp_path: Any) -> None:
    db_path = tmp_path / "m8_obs_1.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    registry = ObservationSourceRegistry()
    src = ObservationSource(
        source_id="camera_front",
        source_type=SourceType.CAMERA,
        canonical_name="Front RGBD Camera",
        adapter_type="CameraAdapter",
        trust_class=SourceTrustClass.INTERNAL,
        allowed_types=[ObservationType.LOCATION, ObservationType.DETECTION],
        allowed_entity_scopes=["robot_*", "target_*"],
        authentication_token="secret_token_123",
    )
    registry.register_source(src)

    sessions = SourceSessionManager(current_epoch=1)
    sess = sessions.create_session("camera_front", duration_sec=3600)

    gate = ObservationIngestGate(source_registry=registry, session_manager=sessions)

    obs = Observation(
        source_id="camera_front",
        source_session_id=sess.source_session_id,
        source_observation_id="cam_obs_001",
        source_sequence=1,
        observation_type=ObservationType.LOCATION,
        subject_ref="robot_arm_1",
        property_key="pose",
        value={"x": 1.5, "y": 0.2, "z": 0.0},
        coordinate_frame="odom",
    )

    async with UnitOfWork(db_manager) as uow:
        persisted_obs, is_new = await gate.ingest_observation(
            obs=obs,
            auth_token="secret_token_123",
            uow=uow,
        )
        assert is_new is True
        assert len(persisted_obs.observation_digest) == 64
        await uow.commit()

    # Re-ingest same observation -> safe idempotent deduplication
    async with UnitOfWork(db_manager) as uow:
        dedup_obs, is_new = await gate.ingest_observation(
            obs=obs,
            auth_token="secret_token_123",
            uow=uow,
        )
        assert is_new is False
        assert dedup_obs.observation_id == obs.observation_id

    await db_manager.close()


@pytest.mark.asyncio
async def test_observation_replay_with_different_payload_fails(tmp_path: Any) -> None:
    db_path = tmp_path / "m8_obs_2.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    registry = ObservationSourceRegistry()
    src = ObservationSource(
        source_id="sensor_a",
        source_type=SourceType.DEVICE,
        canonical_name="Sensor A",
        adapter_type="DeviceAdapter",
        allowed_types=[ObservationType.STATE],
        allowed_entity_scopes=["*"],
        authentication_token="tok_a",
    )
    registry.register_source(src)

    sessions = SourceSessionManager(current_epoch=1)
    sess = sessions.create_session("sensor_a")
    gate = ObservationIngestGate(source_registry=registry, session_manager=sessions)

    obs1 = Observation(
        source_id="sensor_a",
        source_session_id=sess.source_session_id,
        source_observation_id="obs_dup_10",
        observation_type=ObservationType.STATE,
        subject_ref="valve_1",
        property_key="status",
        value="OPEN",
    )

    async with UnitOfWork(db_manager) as uow:
        await gate.ingest_observation(obs=obs1, auth_token="tok_a", uow=uow)
        await uow.commit()

    # Create obs2 with same ID but different payload
    obs2 = Observation(
        source_id="sensor_a",
        source_session_id=sess.source_session_id,
        source_observation_id="obs_dup_10",
        observation_type=ObservationType.STATE,
        subject_ref="valve_1",
        property_key="status",
        value="CLOSED",  # Modified payload!
    )

    async with UnitOfWork(db_manager) as uow:
        with pytest.raises(ObservationReplayError):
            await gate.ingest_observation(obs=obs2, auth_token="tok_a", uow=uow)

    await db_manager.close()


@pytest.mark.asyncio
async def test_observation_security_scope_and_fencing(tmp_path: Any) -> None:
    db_path = tmp_path / "m8_obs_3.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    registry = ObservationSourceRegistry()
    src = ObservationSource(
        source_id="fs_adapter",
        source_type=SourceType.FILE,
        canonical_name="FS",
        adapter_type="Filesystem",
        allowed_types=[ObservationType.CONTENT_CHANGE],
        allowed_entity_scopes=["repo_*"],
        authentication_token="valid_token",
    )
    registry.register_source(src)

    sessions = SourceSessionManager(current_epoch=1)
    sess = sessions.create_session("fs_adapter")
    gate = ObservationIngestGate(source_registry=registry, session_manager=sessions)

    # 1. Test bad auth token
    obs = Observation(
        source_id="fs_adapter",
        source_session_id=sess.source_session_id,
        source_observation_id="fs_01",
        observation_type=ObservationType.CONTENT_CHANGE,
        subject_ref="repo_main",
        property_key="head_commit",
        value="commit1",
    )
    async with UnitOfWork(db_manager) as uow:
        with pytest.raises(SourceAuthenticationError):
            await gate.ingest_observation(obs=obs, auth_token="wrong_token", uow=uow)

    # 2. Test scope violation (entity scope)
    obs_bad_scope = Observation(
        source_id="fs_adapter",
        source_session_id=sess.source_session_id,
        source_observation_id="fs_02",
        observation_type=ObservationType.CONTENT_CHANGE,
        subject_ref="robot_arm_1",  # Not allowed for fs_adapter!
        property_key="head_commit",
        value="commit1",
    )
    async with UnitOfWork(db_manager) as uow:
        with pytest.raises(SourceScopeError):
            await gate.ingest_observation(obs=obs_bad_scope, auth_token="valid_token", uow=uow)

    # 3. Test epoch fencing
    sessions.set_epoch(2)  # Epoch advances to 2, old session was created in epoch 1
    async with UnitOfWork(db_manager) as uow:
        with pytest.raises(SourceFencedError):
            await gate.ingest_observation(obs=obs, auth_token="valid_token", uow=uow)

    await db_manager.close()
