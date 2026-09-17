"""
Universal Brain - Unit Tests for M8 Coordinate Frames & Spatial Transforms
"""

import pytest
from datetime import datetime, timedelta, timezone

from universal_brain.world.errors import (
    FrameTransformError,
    FrameTransformStaleError,
)
from universal_brain.world.frames import CoordinateFrameRegistry


def test_coordinate_frame_transform_chain_and_provenance() -> None:
    tf_tree = CoordinateFrameRegistry()
    now = datetime.now(timezone.utc)

    # Publish transforms:
    # base_link -> camera_link: (0.5, 0.0, 0.2)
    tf_tree.update_transform(
        parent_frame="base_link",
        child_frame="camera_link",
        translation=(0.5, 0.0, 0.2),
        timestamp=now,
        ttl_sec=30.0,
    )
    # map -> base_link: (2.0, 3.0, 0.0)
    tf_tree.update_transform(
        parent_frame="map",
        child_frame="base_link",
        translation=(2.0, 3.0, 0.0),
        timestamp=now,
        ttl_sec=30.0,
    )

    # Object detected at camera_link: (0.1, 0.2, 0.5)
    camera_pose = {"x": 0.1, "y": 0.2, "z": 0.5}

    # Transform camera_link -> map
    res = tf_tree.transform_pose(
        pose=camera_pose,
        source_frame="camera_link",
        target_frame="map",
        as_of_time=now,
    )

    # camera_link -> base_link (-0.5, -0.0, -0.2) -> map (+2.0, +3.0, +0.0)
    # Total translation from camera to map:
    # x: 0.1 + 0.5 + 2.0 = 2.6
    # y: 0.2 + 0.0 + 3.0 = 3.2
    # z: 0.5 + 0.2 + 0.0 = 0.7
    assert res.target_frame == "map"
    assert res.transformed_pose["x"] == 2.6
    assert res.transformed_pose["y"] == 3.2
    assert res.transformed_pose["z"] == 0.7
    assert len(res.transform_digest) == 64
    assert res.transform_chain == ["camera_link", "base_link", "map"]


def test_coordinate_frame_stale_transform_raises() -> None:
    tf_tree = CoordinateFrameRegistry()
    t_old = datetime.now(timezone.utc) - timedelta(seconds=60)

    tf_tree.update_transform(
        parent_frame="map",
        child_frame="odom",
        translation=(1.0, 0.0, 0.0),
        timestamp=t_old,
        ttl_sec=5.0,  # 5s TTL
    )

    now = datetime.now(timezone.utc)
    with pytest.raises(FrameTransformStaleError) as exc_info:
        tf_tree.transform_pose(
            pose={"x": 0.0, "y": 0.0, "z": 0.0},
            source_frame="odom",
            target_frame="map",
            as_of_time=now,
        )
    assert "stale" in str(exc_info.value).lower()


def test_coordinate_frame_disconnected_frames_raise() -> None:
    tf_tree = CoordinateFrameRegistry()
    now = datetime.now(timezone.utc)

    tf_tree.update_transform(
        parent_frame="map",
        child_frame="odom",
        translation=(1.0, 0.0, 0.0),
        timestamp=now,
    )

    # tool0 is disconnected from map/odom
    tf_tree.register_frame("isolated_frame")

    with pytest.raises(FrameTransformError) as exc_info:
        tf_tree.transform_pose(
            pose={"x": 0.0, "y": 0.0, "z": 0.0},
            source_frame="isolated_frame",
            target_frame="map",
            as_of_time=now,
        )
    assert "Cannot find transform path" in str(exc_info.value)
