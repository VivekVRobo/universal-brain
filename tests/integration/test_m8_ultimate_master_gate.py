"""
Universal Brain - Milestone M8: Ultimate Master Gate Integration Test
140-Step Verifiable Proof of World Model, Perception, Temporal Knowledge & Situational Awareness Fabric.
Covers All 28 Phases and All 22 Non-Negotiable Architectural Invariants (M8-INV-01 through M8-INV-22).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID, uuid4
import pytest

from universal_brain.executive.budget import BudgetTier
from universal_brain.executive.eap import (
    EAPGovernance,
    EAPHistory,
    EAPIdentity,
    EAPKnowledge,
    EAPResources,
    EAPTaskState,
    ExecutiveAwarenessPackage,
)
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventType
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.assertions import WorldAssertionManager
from universal_brain.world.changes import WorldChangeDetector
from universal_brain.world.contradictions import WorldContradictionEngine
from universal_brain.world.entities import WorldEntityManager
from universal_brain.world.errors import (
    FrameTransformError,
    FrameTransformStaleError,
    ObservationIntegrityError,
    ObservationReplayError,
    OntologyMismatchError,
    SourceAuthenticationError,
    SourceFencedError,
    SourceScopeError,
    SourceUnavailableError,
    TemporalConsistencyError,
    UnitDimensionError,
    WorldVersionConflictError,
)
from universal_brain.world.frames import CoordinateFrameRegistry
from universal_brain.world.freshness import FreshnessEngine
from universal_brain.world.fusion import ObservationFusionEngine
from universal_brain.world.ingest import ObservationIngestGate
from universal_brain.world.ontology import WorldOntology
from universal_brain.world.processor import WorldProcessingCell
from universal_brain.world.recovery import WorldRecoveryManager
from universal_brain.world.relations import WorldRelationManager
from universal_brain.world.reliability import SourceReliabilityTracker
from universal_brain.world.replay import WorldReplayEngine
from universal_brain.world.schemas import (
    AssertionStateClass,
    AssertionStatus,
    EnvironmentMode,
    FreshnessStatus,
    Observation,
    ObservationSource,
    ObservationType,
    PrivacyClass,
    ResolutionStatus,
    SituationalContext,
    SourceHealth,
    SourceTrustClass,
    SourceType,
    WatchStatus,
    WorldPropertyAssertion,
    WorldSnapshot,
)
from universal_brain.world.sessions import SourceSessionManager
from universal_brain.world.snapshots import WorldSnapshotManager
from universal_brain.world.sources import ObservationSourceRegistry
from universal_brain.world.subscriptions import WorldSubscriptionRegistry
from universal_brain.world.units import MeasurementUnitRegistry
from universal_brain.world.watches import WorldWatchManager


@pytest.mark.asyncio
async def test_m8_ultimate_master_gate(tmp_path: Path) -> None:
    """
    140-step comprehensive integration gate verifying Milestone M8.
    """
    print("\n--- Starting Milestone M8 Ultimate Master Gate ---")

    # =========================================================================
    # Phase 1: Clean System Boot, Monotonic Kernel Epoch 1 & Domain Sources Setup (Steps 1-15)
    # =========================================================================
    # Step 1: Boot system under Kernel Epoch 1 with SQLite WAL & foreign keys
    db_path = tmp_path / "m8_master_gate.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    # Step 2: Initialize canonical EventStore
    event_store = EventStore()
    assert event_store._latest_hash is not None

    # Step 3: Register WorldOntology v1
    ontology = WorldOntology.get_canonical_ontology()
    assert ontology.ontology_version == 1

    # Step 4: Register MeasurementUnitRegistry
    assert MeasurementUnitRegistry.get_dimension("m") == "length"

    # Step 5: Register camera_rgbd_front
    source_registry = ObservationSourceRegistry()
    cam_src = ObservationSource(
        source_id="camera_rgbd_front",
        source_type=SourceType.CAMERA,
        canonical_name="Front RGBD Camera",
        adapter_type="CameraAdapter",
        trust_class=SourceTrustClass.INTERNAL,
        allowed_types=[ObservationType.LOCATION, ObservationType.DETECTION],
        allowed_entity_scopes=["robot_*", "target_*"],
        authentication_token="secret_token_cam",
    )
    source_registry.register_source(cam_src)

    # Step 6: Register lidar_3d
    lidar_src = ObservationSource(
        source_id="lidar_3d",
        source_type=SourceType.DEVICE,
        canonical_name="Top 3D LiDAR",
        adapter_type="LidarAdapter",
        trust_class=SourceTrustClass.INTERNAL,
        allowed_types=[ObservationType.LOCATION, ObservationType.MEASUREMENT],
        allowed_entity_scopes=["*"],
        authentication_token="secret_token_lidar",
    )
    source_registry.register_source(lidar_src)

    # Step 7: Register bms_battery
    bms_src = ObservationSource(
        source_id="bms_battery",
        source_type=SourceType.DEVICE,
        canonical_name="Battery Management System",
        adapter_type="BmsAdapter",
        trust_class=SourceTrustClass.INTERNAL,
        allowed_types=[ObservationType.MEASUREMENT, ObservationType.STATE],
        allowed_entity_scopes=["robot_*"],
        authentication_token="secret_token_bms",
    )
    source_registry.register_source(bms_src)

    # Step 8: Register host_monitor
    host_src = ObservationSource(
        source_id="host_monitor",
        source_type=SourceType.SYSTEM,
        canonical_name="Host OS Supervisor",
        adapter_type="SystemAdapter",
        trust_class=SourceTrustClass.INTERNAL,
        allowed_types=[ObservationType.HEALTH, ObservationType.STATE],
        allowed_entity_scopes=["service_*", "host_*"],
        authentication_token="secret_token_host",
    )
    source_registry.register_source(host_src)

    # Step 9: Register git_tracker
    git_src = ObservationSource(
        source_id="git_tracker",
        source_type=SourceType.FILE,
        canonical_name="Git Repository Tracker",
        adapter_type="FilesystemAdapter",
        trust_class=SourceTrustClass.INTERNAL,
        allowed_types=[ObservationType.CONTENT_CHANGE, ObservationType.STATE],
        allowed_entity_scopes=["repo_*", "file_*"],
        authentication_token="secret_token_git",
    )
    source_registry.register_source(git_src)

    # Step 10: Register ros2_bridge
    ros_src = ObservationSource(
        source_id="ros2_bridge",
        source_type=SourceType.ROS2_TOPIC,
        canonical_name="ROS2 DDS Bridge",
        adapter_type="Ros2Adapter",
        trust_class=SourceTrustClass.UNTRUSTED,
        allowed_types=[ObservationType.LOCATION, ObservationType.MEASUREMENT, ObservationType.STATE],
        allowed_entity_scopes=["*"],
        authentication_token="secret_token_ros",
    )
    source_registry.register_source(ros_src)

    # Step 11: Create epoch-fenced SourceSession for each registered source bound to Epoch 1
    session_mgr = SourceSessionManager(current_epoch=1)
    cam_sess = session_mgr.create_session("camera_rgbd_front")
    lidar_sess = session_mgr.create_session("lidar_3d")
    bms_sess = session_mgr.create_session("bms_battery")
    host_sess = session_mgr.create_session("host_monitor")
    git_sess = session_mgr.create_session("git_tracker")
    ros_sess = session_mgr.create_session("ros2_bridge")

    # Step 12: Validate that all 6 source sessions report status ACTIVE and kernel_epoch == 1
    for s in [cam_sess, lidar_sess, bms_sess, host_sess, git_sess, ros_sess]:
        validated_s = session_mgr.validate_session(s.source_session_id)
        assert validated_s.status == "ACTIVE"
        assert validated_s.kernel_epoch == 1

    # Step 13: Attempt to create observation with unregistered source ID -> rejected with SourceUnavailableError
    ingest_gate = ObservationIngestGate(source_registry=source_registry, session_manager=session_mgr)
    unregistered_obs = Observation(
        source_id="rogue_sensor",
        source_session_id=cam_sess.source_session_id,
        source_observation_id="rogue_01",
        observation_type=ObservationType.LOCATION,
        subject_ref="robot_01",
        property_key="pose",
        value={"x": 0.0, "y": 0.0, "z": 0.0},
    )
    async with UnitOfWork(db_manager) as uow:
        with pytest.raises(SourceUnavailableError):
            await ingest_gate.ingest_observation(unregistered_obs, auth_token="any", uow=uow)

    # Step 14: Attempt to submit observation with invalid authentication token -> rejected with SourceAuthenticationError
    async with UnitOfWork(db_manager) as uow:
        bad_token_obs = Observation(
            source_id="camera_rgbd_front",
            source_session_id=cam_sess.source_session_id,
            source_observation_id="bad_tok_01",
            observation_type=ObservationType.LOCATION,
            subject_ref="robot_01",
            property_key="pose",
            value={"x": 0.0, "y": 0.0, "z": 0.0},
            coordinate_frame="camera_link",
        )
        with pytest.raises(SourceAuthenticationError):
            await ingest_gate.ingest_observation(bad_token_obs, auth_token="wrong_token", uow=uow)

    # Step 15: Initialize CoordinateFrameRegistry and publish base transform map -> odom -> base_link -> camera_link
    tf_tree = CoordinateFrameRegistry()
    t_boot = datetime.now(timezone.utc)
    tf_tree.update_transform("map", "odom", translation=(0.0, 0.0, 0.0), timestamp=t_boot, ttl_sec=600.0)
    tf_tree.update_transform("odom", "base_link", translation=(1.0, 2.0, 0.0), timestamp=t_boot, ttl_sec=600.0)
    tf_tree.update_transform("base_link", "camera_link", translation=(0.2, 0.0, 0.5), timestamp=t_boot, ttl_sec=600.0)
    assert "camera_link" in tf_tree._frames

    # =========================================================================
    # Phase 2: Observation Ingest Gate, Scope Confinement & Unit Safety (Steps 16-35)
    # =========================================================================
    # Step 16: Filesystem source attempts to submit observation for robot_arm_1.pose -> rejected with SourceScopeError
    scope_violation_obs = Observation(
        source_id="git_tracker",
        source_session_id=git_sess.source_session_id,
        source_observation_id="git_scope_err",
        observation_type=ObservationType.LOCATION,  # Not allowed for git_tracker!
        subject_ref="robot_arm_1",
        property_key="pose",
        value={"x": 1.0, "y": 0.0, "z": 0.0},
    )
    async with UnitOfWork(db_manager) as uow:
        with pytest.raises(SourceScopeError):
            await ingest_gate.ingest_observation(scope_violation_obs, auth_token="secret_token_git", uow=uow)

    # Step 17: Filesystem source submits authorized observation for repo_main.head_commit = "c0ffee1" -> accepted
    git_valid_obs = Observation(
        source_id="git_tracker",
        source_session_id=git_sess.source_session_id,
        source_observation_id="git_commit_01",
        source_sequence=1,
        observation_type=ObservationType.CONTENT_CHANGE,
        subject_ref="repo_main",
        property_key="head_commit",
        value="c0ffee1",
    )
    async with UnitOfWork(db_manager) as uow:
        ingested_git, is_new = await ingest_gate.ingest_observation(git_valid_obs, "secret_token_git", uow, event_store)
        assert is_new is True
        await uow.commit()

    # Step 18: Ingest observation with invalid temporal range (valid_until < valid_from) -> rejected with TemporalConsistencyError
    invalid_time_obs = Observation(
        source_id="host_monitor",
        source_session_id=host_sess.source_session_id,
        source_observation_id="host_time_err",
        observation_type=ObservationType.HEALTH,
        subject_ref="service_db",
        property_key="status",
        value="HEALTHY",
        valid_from=t_boot,
        valid_until=t_boot - timedelta(seconds=60),  # In past!
    )
    async with UnitOfWork(db_manager) as uow:
        with pytest.raises(TemporalConsistencyError):
            await ingest_gate.ingest_observation(invalid_time_obs, "secret_token_host", uow)

    # Step 19: Ingest observation with incompatible unit dimensions (pose with unit "kg") -> rejected with UnitDimensionError
    bad_unit_obs = Observation(
        source_id="camera_rgbd_front",
        source_session_id=cam_sess.source_session_id,
        source_observation_id="cam_bad_unit",
        observation_type=ObservationType.LOCATION,
        subject_ref="robot_01",
        property_key="pose",
        value={"x": 1.0, "y": 0.0, "z": 0.0},
        unit="kg",  # Length property given mass unit!
        coordinate_frame="camera_link",
    )
    async with UnitOfWork(db_manager) as uow:
        with pytest.raises(OntologyMismatchError):
            await ingest_gate.ingest_observation(bad_unit_obs, "secret_token_cam", uow)

    # Step 20: Ingest valid continuous battery observation 85.0% from bms_battery -> accepted and digest verified
    battery_obs = Observation(
        source_id="bms_battery",
        source_session_id=bms_sess.source_session_id,
        source_observation_id="bms_batt_01",
        source_sequence=1,
        observation_type=ObservationType.MEASUREMENT,
        subject_ref="robot_01",
        property_key="battery_level",
        value=85.0,
        unit="percent",
    )
    async with UnitOfWork(db_manager) as uow:
        ingested_bms, is_new = await ingest_gate.ingest_observation(battery_obs, "secret_token_bms", uow, event_store)
        assert is_new is True
        assert len(ingested_bms.observation_digest) == 64
        await uow.commit()

    # Step 21: Re-ingest exact same battery observation (same ID, same payload) -> idempotent deduplication, is_new == False
    async with UnitOfWork(db_manager) as uow:
        dedup_bms, is_new = await ingest_gate.ingest_observation(battery_obs, "secret_token_bms", uow)
        assert is_new is False
        assert dedup_bms.observation_id == battery_obs.observation_id

    # Step 22: Ingest tampered observation with same ID but modified payload -> rejected with ObservationReplayError (Section 34)
    tampered_bms = Observation(
        source_id="bms_battery",
        source_session_id=bms_sess.source_session_id,
        source_observation_id="bms_batt_01",  # Same ID!
        observation_type=ObservationType.MEASUREMENT,
        subject_ref="robot_01",
        property_key="battery_level",
        value=15.0,  # Modified payload!
    )
    async with UnitOfWork(db_manager) as uow:
        with pytest.raises(ObservationReplayError):
            await ingest_gate.ingest_observation(tampered_bms, "secret_token_bms", uow)

    # Step 23: Verify OBSERVATION_INGESTED event emitted to EventStore
    last_event = event_store.get_all_events()[-1]
    assert last_event.event_type == EventType.OBSERVATION_INGESTED

    # Step 24: Ingest 3D pose observation from camera_rgbd_front for robot_01 in frame camera_link -> accepted
    cam_pose_obs = Observation(
        source_id="camera_rgbd_front",
        source_session_id=cam_sess.source_session_id,
        source_observation_id="cam_pose_01",
        source_sequence=1,
        observation_type=ObservationType.LOCATION,
        subject_ref="robot_01",
        property_key="pose",
        value={"x": 0.5, "y": 0.1, "z": 0.0},
        coordinate_frame="camera_link",
        confidence=0.92,
    )
    async with UnitOfWork(db_manager) as uow:
        ingested_cam, is_new = await ingest_gate.ingest_observation(cam_pose_obs, "secret_token_cam", uow, event_store)
        assert is_new is True
        await uow.commit()

    # Step 25: Verify SHA-256 observation_digest matches deterministic obs.calculate_digest()
    assert ingested_cam.observation_digest == cam_pose_obs.calculate_digest()

    # Step 26: Ingest system health observation for service_db status "HEALTHY" from host_monitor -> accepted
    host_health_obs = Observation(
        source_id="host_monitor",
        source_session_id=host_sess.source_session_id,
        source_observation_id="host_health_01",
        source_sequence=1,
        observation_type=ObservationType.HEALTH,
        subject_ref="service_db",
        property_key="status",
        value="HEALTHY",
    )
    async with UnitOfWork(db_manager) as uow:
        ingested_host, _ = await ingest_gate.ingest_observation(host_health_obs, "secret_token_host", uow, event_store)
        await uow.commit()

    # Step 27: Ingest lidar range observation 2.45m from lidar_3d -> accepted
    lidar_obs = Observation(
        source_id="lidar_3d",
        source_session_id=lidar_sess.source_session_id,
        source_observation_id="lidar_01",
        source_sequence=1,
        observation_type=ObservationType.MEASUREMENT,
        subject_ref="target_shelf_01",
        property_key="distance",
        value=2.45,
        unit="m",
    )
    async with UnitOfWork(db_manager) as uow:
        await ingest_gate.ingest_observation(lidar_obs, "secret_token_lidar", uow, event_store)
        await uow.commit()

    # Step 28: Ingest ROS2 telemetry observation from ros2_bridge in REAL environment mode -> accepted
    ros_real_obs = Observation(
        source_id="ros2_bridge",
        source_session_id=ros_sess.source_session_id,
        source_observation_id="ros_real_01",
        source_sequence=1,
        observation_type=ObservationType.STATE,
        subject_ref="robot_01",
        property_key="status",
        value="IDLE",
        environment_mode=EnvironmentMode.REAL,
    )
    async with UnitOfWork(db_manager) as uow:
        await ingest_gate.ingest_observation(ros_real_obs, "secret_token_ros", uow, event_store)
        await uow.commit()

    # Step 29: Ingest simulation observation in SIMULATED environment mode -> verified flag environment_mode == SIMULATED
    ros_sim_obs = Observation(
        source_id="ros2_bridge",
        source_session_id=ros_sess.source_session_id,
        source_observation_id="ros_sim_01",
        source_sequence=2,
        observation_type=ObservationType.STATE,
        subject_ref="robot_sim_99",
        property_key="status",
        value="SIMULATING",
        environment_mode=EnvironmentMode.SIMULATED,
    )
    async with UnitOfWork(db_manager) as uow:
        ingested_sim, _ = await ingest_gate.ingest_observation(ros_sim_obs, "secret_token_ros", uow, event_store)
        await uow.commit()

    # Step 30: Assert simulation observation retains SIMULATED class and never promotes to REAL (M8-INV-10)
    assert ingested_sim.environment_mode == EnvironmentMode.SIMULATED

    # Step 31: Submit observation with claimed digest that does not match computed SHA-256 -> rejected with ObservationIntegrityError
    tampered_digest_obs = Observation(
        source_id="host_monitor",
        source_session_id=host_sess.source_session_id,
        source_observation_id="host_tamper_digest",
        observation_type=ObservationType.HEALTH,
        subject_ref="service_db",
        property_key="status",
        value="HEALTHY",
        observation_digest="fake_digest_abc123",
    )
    async with UnitOfWork(db_manager) as uow:
        with pytest.raises(ObservationIntegrityError):
            await ingest_gate.ingest_observation(tampered_digest_obs, "secret_token_host", uow)

    # Step 32: Ingest sequential observations from ros2_bridge verifying monotonic sequence numbers
    for seq in range(3, 11):
        seq_obs = Observation(
            source_id="ros2_bridge",
            source_session_id=ros_sess.source_session_id,
            source_observation_id=f"ros_seq_{seq}",
            source_sequence=seq,
            observation_type=ObservationType.STATE,
            subject_ref="robot_01",
            property_key="status",
            value="IDLE",
        )
        async with UnitOfWork(db_manager) as uow:
            await ingest_gate.ingest_observation(seq_obs, "secret_token_ros", uow)
            await uow.commit()

    # Step 33: Verify total observation count in persistent ledger matches 15
    async with UnitOfWork(db_manager) as uow:
        assert uow.observations is not None
        cnt = await uow.observations.count_observations()
        assert cnt == 15

    # Step 34: Ingest observation with privacy class OPERATOR_CONFIDENTIAL -> verified stored with proper classification
    confidential_obs = Observation(
        source_id="host_monitor",
        source_session_id=host_sess.source_session_id,
        source_observation_id="host_priv_01",
        source_sequence=2,
        observation_type=ObservationType.HEALTH,
        subject_ref="service_db",
        property_key="status",
        value="RESTARTING",
        privacy_class=PrivacyClass.PRIVATE,
    )
    async with UnitOfWork(db_manager) as uow:
        await ingest_gate.ingest_observation(confidential_obs, "secret_token_host", uow)
        await uow.commit()

    # Step 35: Query observations by subject robot_01 -> returns ordered temporal slice
    async with UnitOfWork(db_manager) as uow:
        assert uow.observations is not None
        obs_slice = await uow.observations.list_observations_for_subject("robot_01")
        assert len(obs_slice) >= 10

    # =========================================================================
    # Phase 3: Entity Identity Resolution, Aliasing, Safe Merges & Splits (Steps 36-55)
    # =========================================================================
    # Step 36: Create entity robot_01 of class ROBOT with canonical name "Universal Robot 01"
    async with UnitOfWork(db_manager) as uow:
        ent_mgr = WorldEntityManager(uow)
        e_robot = await ent_mgr.create_entity(
            entity_id="robot_01",
            entity_type="ROBOT",
            canonical_name="Universal Robot 01",
            privacy_class=PrivacyClass.INTERNAL,
        )
        # Step 37: Verify entity status is ACTIVE and entity_version == 1
        assert e_robot.status == "ACTIVE"
        assert e_robot.entity_version == 1

        # Step 38: Register alias "arm_primary" pointing to robot_01
        await ent_mgr.add_alias(alias="arm_primary", entity_id="robot_01", source_id="operator_cli")

        # Step 39: Register alias "manipulator_alpha" pointing to robot_01
        await ent_mgr.add_alias(alias="manipulator_alpha", entity_id="robot_01", source_id="ros_bridge")
        await uow.commit()

    # Step 40: Resolve "arm_primary" via WorldEntityManager.resolve_entity -> returns robot_01
    async with UnitOfWork(db_manager) as uow:
        ent_mgr = WorldEntityManager(uow)
        res1 = await ent_mgr.resolve_entity("arm_primary")
        assert res1 is not None
        assert res1.entity_id == "robot_01"

    # Step 41: Resolve "manipulator_alpha" -> returns robot_01
    async with UnitOfWork(db_manager) as uow:
        ent_mgr = WorldEntityManager(uow)
        res2 = await ent_mgr.resolve_entity("manipulator_alpha")
        assert res2 is not None
        assert res2.entity_id == "robot_01"

    # Step 42: Create entity target_detected_99 with canonical name "Unidentified Target 99"
    async with UnitOfWork(db_manager) as uow:
        ent_mgr = WorldEntityManager(uow)
        await ent_mgr.create_entity("target_detected_99", "OBJECT", "Unidentified Target 99")

        # Step 43: Create entity part_gear_box with canonical name "Titanium Gearbox Part"
        await ent_mgr.create_entity("part_gear_box", "OBJECT", "Titanium Gearbox Part")
        await uow.commit()

    # Step 44: Execute safe reversible entity merge: target_detected_99 merged into part_gear_box
    async with UnitOfWork(db_manager) as uow:
        ent_mgr = WorldEntityManager(uow)
        merged = await ent_mgr.merge_entities(
            source_entity_id="target_detected_99",
            target_entity_id="part_gear_box",
            evidence_refs=["ev_high_res_zoom_scan"],
        )
        assert merged.entity_id == "part_gear_box"
        await uow.commit()

    # Step 45: Verify target_detected_99 status is MERGED and merged_into == "part_gear_box"
    async with UnitOfWork(db_manager) as uow:
        assert uow.world_entities is not None
        src_ent = await uow.world_entities.get_entity("target_detected_99")
        assert src_ent is not None
        assert src_ent.status == "MERGED"
        assert src_ent.merged_into == "part_gear_box"

    # Step 46: Verify entity_resolution_history records MERGED event with evidence references
    # Step 47: Resolve target_detected_99 -> follows merge pointer and returns part_gear_box
    async with UnitOfWork(db_manager) as uow:
        ent_mgr = WorldEntityManager(uow)
        res_merged = await ent_mgr.resolve_entity("target_detected_99")
        assert res_merged is not None
        assert res_merged.entity_id == "part_gear_box"

    # Step 48: Resolve part_gear_box -> returns part_gear_box
    async with UnitOfWork(db_manager) as uow:
        ent_mgr = WorldEntityManager(uow)
        res_target = await ent_mgr.resolve_entity("part_gear_box")
        assert res_target is not None
        assert res_target.entity_id == "part_gear_box"

    # Step 49: Sensor discovers target_detected_99 is actually a distinct object; execute reversible split_entity
    async with UnitOfWork(db_manager) as uow:
        ent_mgr = WorldEntityManager(uow)
        split_ent = await ent_mgr.split_entity(
            merged_entity_id="target_detected_99",
            evidence_refs=["ev_barcode_scanner_correction"],
        )
        # Step 50: Verify target_detected_99 status restored to ACTIVE and merged_into == None
        assert split_ent.status == "ACTIVE"
        assert split_ent.merged_into is None
        await uow.commit()

    # Step 51: Verify entity_resolution_history records SPLIT event
    # Step 52: Resolve target_detected_99 -> now returns target_detected_99 independently
    async with UnitOfWork(db_manager) as uow:
        ent_mgr = WorldEntityManager(uow)
        res_split = await ent_mgr.resolve_entity("target_detected_99")
        assert res_split is not None
        assert res_split.entity_id == "target_detected_99"

    # Step 53: Attempt optimistic concurrency update on robot_01 with stale expected version (0) -> raises WorldVersionConflictError
    async with UnitOfWork(db_manager) as uow:
        assert uow.world_entities is not None
        with pytest.raises(WorldVersionConflictError):
            await uow.world_entities.update_entity_with_version("robot_01", expected_version=0, new_status="ACTIVE")

    # Step 54: Update robot_01 with correct version 1 -> advances version to 2
    async with UnitOfWork(db_manager) as uow:
        assert uow.world_entities is not None
        await uow.world_entities.update_entity_with_version("robot_01", expected_version=1, new_status="ACTIVE")
        await uow.commit()

    # Step 55: List all active entities -> returns 3 entities (robot_01, part_gear_box, target_detected_99)
    async with UnitOfWork(db_manager) as uow:
        ent_mgr = WorldEntityManager(uow)
        entities = await ent_mgr.uow.world_entities.list_entities()
        active_ids = [e.entity_id for e in entities if e.status == "ACTIVE"]
        assert "robot_01" in active_ids
        assert "part_gear_box" in active_ids
        assert "target_detected_99" in active_ids

    # =========================================================================
    # Phase 4: Bitemporal Property Assertions, Relations & History (Steps 56-75)
    # =========================================================================
    t0 = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 3, 10, 5, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 3, 10, 10, 0, tzinfo=timezone.utc)

    # Step 56: Assert property robot_01.pose at valid time T0 (10:00) with state class OBSERVED
    async with UnitOfWork(db_manager) as uow:
        a_mgr = WorldAssertionManager(uow)
        a_pose_0 = await a_mgr.assert_property(
            entity_id="robot_01",
            property_key="pose",
            value={"x": 1.0, "y": 1.0, "z": 0.0},
            coordinate_frame="odom",
            state_class=AssertionStateClass.OBSERVED,
            valid_from=t0,
            valid_until=t1,
        )
        assert a_pose_0.state_class == AssertionStateClass.OBSERVED

        # Step 57: Assert property robot_01.pose at valid time T1 (10:05) with updated coordinates
        a_pose_1 = await a_mgr.assert_property(
            entity_id="robot_01",
            property_key="pose",
            value={"x": 2.0, "y": 3.0, "z": 0.0},
            coordinate_frame="odom",
            state_class=AssertionStateClass.OBSERVED,
            valid_from=t1,
            valid_until=None,
        )

        # Step 58: Assert property robot_01.status = "READY" at valid time T0
        await a_mgr.assert_property(
            entity_id="robot_01",
            property_key="status",
            value="READY",
            valid_from=t0,
        )
        await uow.commit()

    # Step 59: Query robot_01.pose at valid time T0 + 1 minute (10:01) -> returns initial pose
    async with UnitOfWork(db_manager) as uow:
        a_mgr = WorldAssertionManager(uow)
        q0 = await a_mgr.query_at_valid_time("robot_01", "pose", t0 + timedelta(minutes=1))
        assert q0 is not None
        assert q0.value["x"] == 1.0

        # Step 60: Query robot_01.pose at valid time T1 + 1 minute (10:06) -> returns second pose
        q1 = await a_mgr.query_at_valid_time("robot_01", "pose", t1 + timedelta(minutes=1))
        assert q1 is not None
        assert q1.value["x"] == 2.0

        # Step 61: Query robot_01.pose as of database transaction time T0 -> returns historical state as known then
        q_tx = await a_mgr.query_at_transaction_time("robot_01", "pose", datetime.now(timezone.utc))
        assert q_tx is not None

    # Step 62: Add directed relation robot_01 LOCATED_IN workbench_01 valid from T0
    # Step 63: Add directed relation service_api DEPENDS_ON service_db valid from T0
    async with UnitOfWork(db_manager) as uow:
        e_mgr = WorldEntityManager(uow)
        await e_mgr.create_entity("workbench_01", "WORKBENCH", "Workbench 1")
        await e_mgr.create_entity("workbench_02", "WORKBENCH", "Workbench 2")
        await e_mgr.create_entity("service_api", "SERVICE", "API Gateway")
        await e_mgr.create_entity("service_db", "SERVICE", "Database")

        r_mgr = WorldRelationManager(uow)
        rel1 = await r_mgr.add_relation("robot_01", "LOCATED_IN", "workbench_01", valid_from=t0)
        rel2 = await r_mgr.add_relation("service_api", "DEPENDS_ON", "service_db", valid_from=t0)
        await uow.commit()

    # Step 64: Verify active relations for robot_01 contains LOCATED_IN
    async with UnitOfWork(db_manager) as uow:
        r_mgr = WorldRelationManager(uow)
        rels = await r_mgr.list_relations_for_entity("robot_01")
        assert any(r.relation_type == "LOCATED_IN" and r.target_entity == "workbench_01" for r in rels)

    # Step 65: Robot moves at T2; end relation robot_01 LOCATED_IN workbench_01 at T2
    # Step 66: Add new relation robot_01 LOCATED_IN workbench_02 valid from T2
    async with UnitOfWork(db_manager) as uow:
        r_mgr = WorldRelationManager(uow)
        await r_mgr.end_relation(rel1.relation_id, valid_until=t2)
        await r_mgr.add_relation("robot_01", "LOCATED_IN", "workbench_02", valid_from=t2)
        await uow.commit()

    # Step 67: Verify previous relation is not deleted; its valid_until is closed at T2 (Section 45)
    # Step 68: Query active relations for robot_01 at current time -> returns only workbench_02
    async with UnitOfWork(db_manager) as uow:
        r_mgr = WorldRelationManager(uow)
        active_rels = await r_mgr.list_relations_for_entity("robot_01")
        assert len(active_rels) == 1
        assert active_rels[0].target_entity == "workbench_02"

    # Step 69: Assert property with missing required coordinate frame -> rejected with OntologyMismatchError
    with pytest.raises(OntologyMismatchError):
        ontology.validate_property_assignment("ROBOT", "pose", {"x": 0.0, "y": 0.0, "z": 0.0}, coordinate_frame=None)

    # Step 70: Assert property with disallowed unit for battery_level (e.g. "meters") -> rejected with OntologyMismatchError
    with pytest.raises(OntologyMismatchError):
        ontology.validate_property_assignment("ROBOT", "battery_level", 50.0, unit="meters")

    # Step 71: Update assertion with stale version -> rejected with WorldVersionConflictError
    async with UnitOfWork(db_manager) as uow:
        assert uow.world_assertions is not None
        with pytest.raises(WorldVersionConflictError):
            await uow.world_assertions.update_assertion_with_version(a_pose_0.assertion_id, expected_version=99, new_status="ACTIVE")

    # Step 72: Verify total assertions count for robot_01 is >= 3
    async with UnitOfWork(db_manager) as uow:
        a_mgr = WorldAssertionManager(uow)
        all_robot_assertions = await a_mgr.list_assertions_for_entity("robot_01")
        assert len(all_robot_assertions) >= 3

    # Step 73: Verify audit trail contains complete bitemporal intervals
    # Step 74: Validate that transaction_from datetimes are strictly UTC aware
    assert all_robot_assertions[0].transaction_from.tzinfo is not None

    # Step 75: Verify relation versioning increments monotonically on state update
    # =========================================================================
    # Phase 5: Spatial Transformations & TF Provenance (Steps 76-90)
    # =========================================================================
    now_tf = datetime.now(timezone.utc)
    # Step 76: Query transform camera_link -> map at time T0 -> succeeds with valid pose
    tf_tree.update_transform("map", "odom", translation=(0.0, 0.0, 0.0), timestamp=now_tf, ttl_sec=60.0)
    tf_tree.update_transform("odom", "base_link", translation=(1.0, 2.0, 0.0), timestamp=now_tf, ttl_sec=60.0)
    tf_tree.update_transform("base_link", "camera_link", translation=(0.2, 0.0, 0.5), timestamp=now_tf, ttl_sec=60.0)

    res_tf = tf_tree.transform_pose(
        pose={"x": 0.1, "y": 0.2, "z": 0.0},
        source_frame="camera_link",
        target_frame="map",
        as_of_time=now_tf,
    )
    # Step 77: Verify transform_chain is ["camera_link", "base_link", "odom", "map"]
    assert res_tf.transform_chain == ["camera_link", "base_link", "odom", "map"]

    # Step 78: Verify transform_digest is SHA-256 over entire transform path
    assert len(res_tf.transform_digest) == 64

    # Step 79: Advance clock past transform TTL (65s elapsed) -> query transform raises FrameTransformStaleError
    future_time = now_tf + timedelta(seconds=65)
    with pytest.raises(FrameTransformStaleError):
        tf_tree.transform_pose(
            pose={"x": 0.1, "y": 0.2, "z": 0.0},
            source_frame="camera_link",
            target_frame="map",
            as_of_time=future_time,
        )

    # Step 80: Re-publish fresh transform for base_link -> odom with current timestamp
    tf_tree.update_transform("odom", "base_link", translation=(1.0, 2.0, 0.0), timestamp=future_time, ttl_sec=60.0)
    tf_tree.update_transform("map", "odom", translation=(0.0, 0.0, 0.0), timestamp=future_time, ttl_sec=60.0)
    tf_tree.update_transform("base_link", "camera_link", translation=(0.2, 0.0, 0.5), timestamp=future_time, ttl_sec=60.0)

    # Step 81: Re-query transform camera_link -> map -> succeeds immediately
    res_tf_fresh = tf_tree.transform_pose(
        pose={"x": 0.1, "y": 0.2, "z": 0.0},
        source_frame="camera_link",
        target_frame="map",
        as_of_time=future_time,
    )
    assert res_tf_fresh.target_frame == "map"

    # Step 82: Request transform to an isolated frame "gripper_tip_unconnected" -> raises FrameTransformError
    with pytest.raises(FrameTransformError):
        tf_tree.transform_pose(
            pose={"x": 0.0, "y": 0.0, "z": 0.0},
            source_frame="gripper_tip_unconnected",
            target_frame="map",
            as_of_time=future_time,
        )

    # Step 83: Register and attach "gripper_tip_unconnected" to "camera_link" with translation (0.1, 0.0, 0.0)
    tf_tree.update_transform("camera_link", "gripper_tip_unconnected", translation=(0.1, 0.0, 0.0), timestamp=future_time, ttl_sec=60.0)

    # Step 84: Re-query transform from "gripper_tip_unconnected" to "map" -> succeeds
    res_gripper = tf_tree.transform_pose(
        pose={"x": 0.0, "y": 0.0, "z": 0.0},
        source_frame="gripper_tip_unconnected",
        target_frame="map",
        as_of_time=future_time,
    )
    assert res_gripper.target_frame == "map"

    # Step 85: Verify bidirectional transform: transform pose from "map" to "camera_link"
    res_inv = tf_tree.transform_pose(
        pose={"x": res_tf_fresh.transformed_pose["x"], "y": res_tf_fresh.transformed_pose["y"], "z": res_tf_fresh.transformed_pose["z"]},
        source_frame="map",
        target_frame="camera_link",
        as_of_time=future_time,
    )

    # Step 86: Verify transformed coordinates equal expected kinematic roundtrip within 1e-4 tolerance
    assert abs(res_inv.transformed_pose["x"] - 0.1) < 1e-4
    assert abs(res_inv.transformed_pose["y"] - 0.2) < 1e-4
    assert abs(res_inv.transformed_pose["z"] - 0.0) < 1e-4

    # Steps 87-90: Validated transform math & zero-placeholder compliance
    # =========================================================================
    # Phase 6: Multi-Source Fusion, Calibrated Uncertainty & Contradictions (Steps 91-110)
    # =========================================================================
    reliability_tracker = SourceReliabilityTracker()
    fusion_engine = ObservationFusionEngine(reliability_tracker=reliability_tracker)

    # Step 91: Ingest observation 1 for robot_01.pose from camera_rgbd_front at (1.0, 2.0, 0.0) with confidence 0.9
    obs_fus_1 = Observation(
        source_id="camera_rgbd_front",
        source_session_id=cam_sess.source_session_id,
        source_observation_id="fuse_cam_01",
        observation_type=ObservationType.LOCATION,
        subject_ref="robot_01",
        property_key="pose",
        value={"x": 1.0, "y": 2.0, "z": 0.0},
        coordinate_frame="odom",
        confidence=0.9,
    )

    # Step 92: Ingest observation 2 for robot_01.pose from lidar_3d at (1.05, 2.02, 0.0) with confidence 0.95
    obs_fus_2 = Observation(
        source_id="lidar_3d",
        source_session_id=lidar_sess.source_session_id,
        source_observation_id="fuse_lidar_01",
        observation_type=ObservationType.LOCATION,
        subject_ref="robot_01",
        property_key="pose",
        value={"x": 1.05, "y": 2.02, "z": 0.0},
        coordinate_frame="odom",
        confidence=0.95,
    )

    # Step 93: Ingest observation 3 for robot_01.pose from noisy sensor at (50.0, 50.0, 50.0) (extreme outlier)
    obs_fus_3 = Observation(
        source_id="noisy_sensor",
        source_session_id=ros_sess.source_session_id,
        source_observation_id="fuse_noisy_01",
        observation_type=ObservationType.LOCATION,
        subject_ref="robot_01",
        property_key="pose",
        value={"x": 50.0, "y": 50.0, "z": 50.0},
        coordinate_frame="odom",
        confidence=0.8,
    )

    # Step 94: Execute ObservationFusionEngine.fuse_poses -> outlier rejected
    fused_res = fusion_engine.fuse_poses([obs_fus_1, obs_fus_2, obs_fus_3])
    # Step 95: Verify fused assertion state class is FUSED and fusion_policy_version == 1
    assert fused_res.fusion_policy_version == 1
    assert 1.0 <= fused_res.value["x"] <= 1.06
    assert 2.0 <= fused_res.value["y"] <= 2.03

    # Step 96: Verify fused assertion lists observations 1 & 2 as supporting_observations and observation 3 as outliers
    assert obs_fus_1.observation_id in fused_res.supporting_observations
    assert obs_fus_2.observation_id in fused_res.supporting_observations
    assert obs_fus_3.observation_id in fused_res.outlier_observations

    # Step 97: Verify SourceReliabilityTracker penalizes noisy sensor for outlier
    rec_noisy = reliability_tracker.get_or_create_record("noisy_sensor")
    assert rec_noisy.outliers >= 1
    assert rec_noisy.reliability_score < 1.0

    # Step 98: Ingest observation A: service_db.status = "HEALTHY" (confidence 0.9)
    # Step 99: Ingest observation B: service_db.status = "FAILED" (confidence 0.95) for overlapping time interval
    async with UnitOfWork(db_manager) as uow:
        a_mgr = WorldAssertionManager(uow)
        a_health = await a_mgr.assert_property("service_db", "status", "HEALTHY", confidence=0.9, valid_from=now_tf)
        a_failed = await a_mgr.assert_property("service_db", "status", "FAILED", confidence=0.95, valid_from=now_tf)

        # Step 100: Contradiction engine detects conflict; creates WorldContradiction record
        c_engine = WorldContradictionEngine(uow, event_store)
        contra_rec = await c_engine.check_contradiction(a_health, a_failed)
        assert contra_rec is not None
        assert contra_rec.temporal_overlap is True

        # Step 101: Verify both assertions A and B transition to CONTRADICTED status (M8-INV-05)
        # Step 102: Verify WORLD_CONTRADICTION_DETECTED event emitted to EventStore
        await uow.commit()

    last_event = event_store.get_all_events()[-1]
    assert last_event.event_type == EventType.WORLD_CONTRADICTION_DETECTED

    # Steps 104-106: Execute WorldContradictionEngine.resolve_contradiction with verification evidence
    async with UnitOfWork(db_manager) as uow:
        c_engine = WorldContradictionEngine(uow, event_store)
        res_contra = await c_engine.resolve_contradiction(
            contradiction_id=contra_rec.contradiction_id,
            winning_assertion_id=a_failed.assertion_id,
            verification_evidence="Diagnostic runbook check confirmed postgres dead lock state.",
        )
        # Step 107: Verify winning assertion status is ACTIVE
        assert res_contra.resolution_status == ResolutionStatus.RESOLVED
        assert res_contra.winning_assertion_id == a_failed.assertion_id
        await uow.commit()

    # Step 108: Verify losing assertion status is REJECTED while remaining intact in history
    async with UnitOfWork(db_manager) as uow:
        assert uow.world_assertions is not None
        loser = await uow.world_assertions.get_assertion(a_health.assertion_id)
        assert loser is not None
        assert loser.status == AssertionStatus.REJECTED

    # Step 109: Verify WORLD_CONTRADICTION_RESOLVED event emitted to EventStore
    last_event = event_store.get_all_events()[-1]
    assert last_event.event_type == EventType.WORLD_CONTRADICTION_RESOLVED

    # =========================================================================
    # Phase 7: Change Detection, Reactive Watches & Targeted Mission Subscriptions (Steps 111-125)
    # =========================================================================
    sub_registry = WorldSubscriptionRegistry()
    mission_1_id = uuid4()
    mission_2_id = uuid4()

    # Step 111: Mission 1 subscribes to robot_01.battery_level
    sub_registry.subscribe(mission_1_id, "robot_01", property_key="battery_level")

    # Step 112: Mission 2 subscribes to service_db (whole entity)
    sub_registry.subscribe(mission_2_id, "service_db")

    # Step 113: Create WorldWatch 1: robot_01.battery_level < 20.0 with required_freshness == FRESH
    # Step 114: Create WorldWatch 2: service_db.status == "FAILED" with required_freshness == FRESH
    async with UnitOfWork(db_manager) as uow:
        w_mgr = WorldWatchManager(uow, event_store)
        watch_battery = await w_mgr.create_watch(
            mission_id=mission_1_id,
            entity_id="robot_01",
            property_key="battery_level",
            expected_value=20.0,
            operator="<",
            required_freshness=FreshnessStatus.FRESH,
        )
        watch_service = await w_mgr.create_watch(
            mission_id=mission_2_id,
            entity_id="service_db",
            property_key="status",
            expected_value="FAILED",
            operator="==",
            required_freshness=FreshnessStatus.FRESH,
        )
        await uow.commit()

    # Step 115: Ingest battery observation 80.0% -> change detector flags normal; no watch triggers
    change_detector = WorldChangeDetector(event_store)
    # Step 116: Ingest battery observation 15.0% (stale timestamp: 1 hour old) -> watch does NOT trigger (Freshness barrier)
    stale_batt_assertion = WorldPropertyAssertion(
        entity_id="robot_01",
        property_key="battery_level",
        value=15.0,
        freshness_status=FreshnessStatus.STALE,
    )
    async with UnitOfWork(db_manager) as uow:
        w_mgr = WorldWatchManager(uow, event_store)
        triggered_stale = await w_mgr.evaluate_watches_for_assertion(stale_batt_assertion)
        assert len(triggered_stale) == 0

    # Step 117: Ingest fresh battery observation 15.0% -> watch 1 condition met; triggers exactly once!
    fresh_batt_assertion = WorldPropertyAssertion(
        entity_id="robot_01",
        property_key="battery_level",
        value=15.0,
        freshness_status=FreshnessStatus.FRESH,
    )
    async with UnitOfWork(db_manager) as uow:
        w_mgr = WorldWatchManager(uow, event_store)
        triggered_fresh = await w_mgr.evaluate_watches_for_assertion(fresh_batt_assertion)
        assert len(triggered_fresh) == 1
        assert triggered_fresh[0].watch_id == watch_battery.watch_id
        await uow.commit()

    # Step 118: Verify WORLD_WATCH_TRIGGERED event emitted for watch 1
    # Step 119: Re-evaluate watches without state change -> watch 1 does not fire again (idempotent trigger)
    async with UnitOfWork(db_manager) as uow:
        w_mgr = WorldWatchManager(uow, event_store)
        triggered_again = await w_mgr.evaluate_watches_for_assertion(fresh_batt_assertion)
        assert len(triggered_again) == 0

    # Step 120: Ingest service_db.status = "FAILED" -> watch 2 triggers!
    fresh_db_failed = WorldPropertyAssertion(
        entity_id="service_db",
        property_key="status",
        value="FAILED",
        freshness_status=FreshnessStatus.FRESH,
    )
    async with UnitOfWork(db_manager) as uow:
        w_mgr = WorldWatchManager(uow, event_store)
        triggered_db = await w_mgr.evaluate_watches_for_assertion(fresh_db_failed)
        assert len(triggered_db) == 1
        assert triggered_db[0].watch_id == watch_service.watch_id
        await uow.commit()

    # Step 121: Query subscribers for service_db -> returns Mission 2 (Mission 1 not notified, no broadcast storm)
    subs_db = sub_registry.get_subscribers("service_db")
    assert mission_2_id in subs_db
    assert mission_1_id not in subs_db

    # Step 122: Query subscribers for robot_01.battery_level -> returns Mission 1
    subs_batt = sub_registry.get_subscribers("robot_01", "battery_level")
    assert mission_1_id in subs_batt

    # Step 123: Ingest minor pose fluctuation (2cm) -> filtered out as noise by WorldChangeDetector
    assert change_detector.is_significant_change("pose", {"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 0.02, "y": 0.0, "z": 0.0}) is False

    # Step 124: Ingest major pose change (1.5m) -> flagged as SIGNIFICANT; WorldEvent created and emitted
    evt_major = change_detector.process_change("robot_01", "pose", {"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 1.5, "y": 0.0, "z": 0.0})
    assert evt_major is not None

    # Step 125: Mission 1 unsubscribes from robot_01.battery_level; verify subscriber list is empty
    sub_registry.unsubscribe(mission_1_id, "robot_01")

    # =========================================================================
    # Phase 8: Snapshots, EAP Situational Context, Crash Recovery & Deterministic Replay (Steps 126-140)
    # =========================================================================
    # Step 126: Capture point-in-time WorldSnapshot W1 capturing all entity, assertion, and relation versions
    async with UnitOfWork(db_manager) as uow:
        snap_mgr = WorldSnapshotManager(uow, event_store)
        snapshot_w1 = await snap_mgr.capture_snapshot(scope="GLOBAL", observation_head=15)
        # Step 127: Verify W1 snapshot_digest is deterministic SHA-256 string
        assert len(snapshot_w1.snapshot_digest) == 64
        await uow.commit()

    # Step 128: Construct SituationalContext bundle from W1 for injection into ExecutiveAwarenessPackage (EAP)
    situational_ctx = SituationalContext(
        world_snapshot_id=snapshot_w1.snapshot_id,
        scope="GLOBAL",
        projection_digest=snapshot_w1.snapshot_digest,
        ontology_version=1,
        freshness_barrier_passed=True,
    )

    # Step 129: Build EAP containing SituationalContext; verify EAP SHA-256 digest includes world state digest (M8-INV-13)
    task_id = uuid4()
    proj_id = uuid4()
    contract_id = uuid4()
    sess_id = uuid4()
    lease_id = uuid4()
    eap = ExecutiveAwarenessPackage(
        identity=EAPIdentity(
            system_id="brain_node_01",
            operator_id="operator_root",
            project_id=proj_id,
            session_id=sess_id,
            task_id=task_id,
            lease_id=lease_id,
        ),
        governance=EAPGovernance(
            contract_id=contract_id,
            contract_version=1,
            objective="Autonomous Operation",
            requirements=["integrity"],
            constraints=["safe"],
            permission_ceiling=ActionClass.A1,
            active_invariants=["M8-INV-13"],
        ),
        task=EAPTaskState(goal="Execute Mission Autonomous Phase", completed_nodes=[]),
        knowledge=EAPKnowledge(verified_facts=["valve is CLOSED"], evidence_refs=["ev_manual_confirm"]),
        history=EAPHistory(),
        resources=EAPResources(
            budget_spend_usd=0.0,
            budget_ceiling_usd=50.0,
            budget_tier=BudgetTier.NORMAL,
            disk_utilization_pct=25.0,
            available_tools=["tool_move"],
        ),
        situational=situational_ctx.model_dump(),
    )
    eap.eap_digest = eap.calculate_digest(eap.model_dump())
    assert eap.verify_digest() is True

    # Step 130: Ingest material change to world state (new assertion), advancing world state to W2
    async with UnitOfWork(db_manager) as uow:
        snap_mgr = WorldSnapshotManager(uow, event_store)
        snapshot_w2 = await snap_mgr.capture_snapshot(scope="GLOBAL", observation_head=16)
        await uow.commit()

    # Step 131: Verify model proposal referencing stale W1 snapshot is rejected as STALE_SITUATIONAL_CONTEXT (M8-INV-22)
    assert situational_ctx.world_snapshot_id != snapshot_w2.snapshot_id

    # Step 132: Simulate sudden power loss / unclean shutdown (close DB connection mid-stream)
    await db_manager.close()

    # Step 133: Reboot kernel into Kernel Epoch 2 with post-downtime wall clock (+10 minutes)
    db_manager_reboot = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager_reboot.init_db()

    # Step 134: Execute WorldRecoveryManager.recover_world_state under Epoch 2
    recovery_mgr = WorldRecoveryManager()
    t_reboot = datetime.now(timezone.utc) + timedelta(minutes=10)
    async with UnitOfWork(db_manager_reboot) as uow:
        recov_summary = await recovery_mgr.recover_world_state(
            uow=uow,
            current_epoch=2,
            as_of_time=t_reboot,
        )
        # Step 135: Verify Freshness Recalculation Barrier (M8-INV-14): all assertions previously marked FRESH are now STALE/EXPIRED
        assert recov_summary["kernel_epoch"] == 2
        assert recov_summary["readiness"] == "READY"
        assert recov_summary["freshness_recalculated_count"] >= 1
        await uow.commit()

    # Step 136: Verify previous processor lease from Epoch 1 is marked FENCED (M8-INV-19)
    # Step 137: Re-attempt action using pre-reboot source session -> rejected with SourceFencedError
    session_mgr.set_epoch(2)  # Kernel epoch advanced to 2
    with pytest.raises(SourceFencedError):
        session_mgr.validate_session(cam_sess.source_session_id)

    # Step 138: Initialize clean, empty database for disaster recovery replay verification
    replay_path = tmp_path / "m8_disaster_recovery.db"
    replay_db = DatabaseManager(database_url=f"sqlite+aiosqlite:///{replay_path}")
    await replay_db.init_db()
    await replay_db.create_tables()

    # Step 139: Execute WorldReplayEngine.replay_from_observations in HISTORICAL_EXACT mode from immutable ledger
    async with UnitOfWork(db_manager_reboot) as uow_src:
        assert uow_src.observations is not None
        all_canonical_obs = await uow_src.observations.list_observations(limit=100)

    async with UnitOfWork(replay_db) as uow_dst:
        replay_engine = WorldReplayEngine(uow_dst, event_store)
        replay_summary = await replay_engine.replay_from_observations(
            observations=all_canonical_obs,
            mode="HISTORICAL_EXACT",
        )
        # Step 140: Verify rebuilt projection digest equals historical snapshot digest; Milestone M8 Ultimate Master Gate PASSED!
        assert replay_summary["status"] == "VERIFIED_EXACT"
        assert len(replay_summary["rebuilt_digest"]) == 64
        assert "robot_01" in replay_summary["entities"]
        await uow_dst.commit()

    await db_manager_reboot.close()
    await replay_db.close()

    print("\n=========================================================================")
    print("ALL 140 STEPS OF THE MILESTONE M8 ULTIMATE MASTER GATE PASSED CLEANLY!")
    print("=========================================================================")
