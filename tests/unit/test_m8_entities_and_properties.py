"""
Universal Brain - Unit Tests for M8 Entities, Identity & Bitemporal Assertions
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
from universal_brain.world.schemas import (
    AssertionStateClass,
    AssertionStatus,
    PrivacyClass,
)


@pytest.mark.asyncio
async def test_entity_creation_alias_and_resolution(tmp_path: Any) -> None:
    db_path = tmp_path / "m8_ent_1.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    async with UnitOfWork(db_manager) as uow:
        mgr = WorldEntityManager(uow)
        entity = await mgr.create_entity(
            entity_id="robot_01",
            entity_type="ROBOT",
            canonical_name="UR5e Manipulator",
            privacy_class=PrivacyClass.INTERNAL,
        )
        assert entity.entity_id == "robot_01"
        assert entity.entity_version == 1

        # Add alias
        await mgr.add_alias(
            alias="assembly_arm_left",
            entity_id="robot_01",
            source_id="operator_console",
        )
        await uow.commit()

    async with UnitOfWork(db_manager) as uow:
        mgr = WorldEntityManager(uow)
        # Resolve by ID
        res1 = await mgr.resolve_entity("robot_01")
        assert res1 is not None
        assert res1.canonical_name == "UR5e Manipulator"

        # Resolve by alias
        res2 = await mgr.resolve_entity("assembly_arm_left")
        assert res2 is not None
        assert res2.entity_id == "robot_01"

    await db_manager.close()


@pytest.mark.asyncio
async def test_entity_safe_merge_and_split(tmp_path: Any) -> None:
    db_path = tmp_path / "m8_ent_2.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    async with UnitOfWork(db_manager) as uow:
        mgr = WorldEntityManager(uow)
        await mgr.create_entity(entity_id="target_unknown_1", entity_type="OBJECT", canonical_name="Unknown Object")
        await mgr.create_entity(entity_id="target_cube_red", entity_type="OBJECT", canonical_name="Red Cube")
        await uow.commit()

    # Merge unknown into red cube
    async with UnitOfWork(db_manager) as uow:
        mgr = WorldEntityManager(uow)
        merged_target = await mgr.merge_entities(
            source_entity_id="target_unknown_1",
            target_entity_id="target_cube_red",
            evidence_refs=["ev_camera_close_view"],
        )
        assert merged_target.entity_id == "target_cube_red"
        await uow.commit()

    # Resolving unknown entity now resolves to red cube
    async with UnitOfWork(db_manager) as uow:
        mgr = WorldEntityManager(uow)
        res = await mgr.resolve_entity("target_unknown_1")
        assert res is not None
        assert res.entity_id == "target_cube_red"

    # Split entity (reversing merge)
    async with UnitOfWork(db_manager) as uow:
        mgr = WorldEntityManager(uow)
        split_entity = await mgr.split_entity(
            merged_entity_id="target_unknown_1",
            evidence_refs=["ev_color_sensor_correction"],
        )
        assert split_entity.status == "ACTIVE"
        assert split_entity.merged_into is None
        await uow.commit()

    # Resolving unknown entity now resolves back to itself
    async with UnitOfWork(db_manager) as uow:
        mgr = WorldEntityManager(uow)
        res = await mgr.resolve_entity("target_unknown_1")
        assert res is not None
        assert res.entity_id == "target_unknown_1"

    await db_manager.close()


@pytest.mark.asyncio
async def test_bitemporal_property_assertions(tmp_path: Any) -> None:
    db_path = tmp_path / "m8_ent_3.db"
    db_manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{db_path}")
    await db_manager.init_db()
    await db_manager.create_tables()

    t0 = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 3, 10, 5, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 3, 10, 10, 0, tzinfo=timezone.utc)

    async with UnitOfWork(db_manager) as uow:
        e_mgr = WorldEntityManager(uow)
        await e_mgr.create_entity("service_db", "SERVICE", "PostgreSQL Primary")

        a_mgr = WorldAssertionManager(uow)
        # At T0, status was HEALTHY
        await a_mgr.assert_property(
            entity_id="service_db",
            property_key="status",
            value="HEALTHY",
            state_class=AssertionStateClass.OBSERVED,
            valid_from=t0,
            valid_until=t1,
        )
        # At T1, status became DEGRADED
        await a_mgr.assert_property(
            entity_id="service_db",
            property_key="status",
            value="DEGRADED",
            state_class=AssertionStateClass.OBSERVED,
            valid_from=t1,
            valid_until=None,
        )
        await uow.commit()

    async with UnitOfWork(db_manager) as uow:
        a_mgr = WorldAssertionManager(uow)
        # Query at valid time T0 (10:02) -> HEALTHY
        query_t0 = datetime(2026, 9, 3, 10, 2, 0, tzinfo=timezone.utc)
        a0 = await a_mgr.query_at_valid_time("service_db", "status", query_t0)
        assert a0 is not None
        assert a0.value == "HEALTHY"

        # Query at valid time T1 (10:07) -> DEGRADED
        query_t1 = datetime(2026, 9, 3, 10, 7, 0, tzinfo=timezone.utc)
        a1 = await a_mgr.query_at_valid_time("service_db", "status", query_t1)
        assert a1 is not None
        assert a1.value == "DEGRADED"

    await db_manager.close()
