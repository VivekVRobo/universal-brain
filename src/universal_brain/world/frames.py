"""
Universal Brain - Coordinate Frames & Spatial Transform Registry
Implements Sections 47-51 of Milestone M8 Specification (M8-INV-12).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from universal_brain.world.errors import FrameTransformError, FrameTransformStaleError


class TransformRecord(NamedTuple):
    parent_frame: str
    child_frame: str
    translation: Tuple[float, float, float]  # (x, y, z)
    rotation: Tuple[float, float, float, float]  # (qx, qy, qz, qw)
    timestamp: datetime
    ttl_sec: float
    transform_digest: str


class TransformedPoseResult(NamedTuple):
    transformed_pose: Dict[str, Any]
    target_frame: str
    transform_chain: List[str]
    transform_timestamp: datetime
    transform_digest: str


class CoordinateFrameRegistry:
    """
    Maintains coordinate frames and spatial transform tree (e.g. TF tree),
    enforcing coordinate frame provenance and transform freshness.
    """

    def __init__(self) -> None:
        # parent -> {child: TransformRecord}
        self._transforms: Dict[str, Dict[str, TransformRecord]] = {}
        # Registered frame names
        self._frames: set[str] = {"map", "odom", "base_link", "camera_link", "tool0"}

    def register_frame(self, frame_id: str) -> None:
        self._frames.add(frame_id.strip())

    def update_transform(
        self,
        parent_frame: str,
        child_frame: str,
        translation: Tuple[float, float, float],
        rotation: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
        timestamp: Optional[datetime] = None,
        ttl_sec: float = 10.0,
    ) -> TransformRecord:
        """Publishes or updates a spatial transform between parent and child."""
        p = parent_frame.strip()
        c = child_frame.strip()
        self.register_frame(p)
        self.register_frame(c)

        ts = timestamp or datetime.now(timezone.utc)
        payload = {
            "parent": p,
            "child": c,
            "translation": translation,
            "rotation": rotation,
            "timestamp": ts.isoformat(),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        rec = TransformRecord(
            parent_frame=p,
            child_frame=c,
            translation=translation,
            rotation=rotation,
            timestamp=ts,
            ttl_sec=ttl_sec,
            transform_digest=digest,
        )

        # child_frame -> parent_frame carries +translation (point in child expressed in parent)
        c_to_p_rec = TransformRecord(
            parent_frame=c,
            child_frame=p,
            translation=translation,
            rotation=rotation,
            timestamp=ts,
            ttl_sec=ttl_sec,
            transform_digest=digest,
        )
        if c not in self._transforms:
            self._transforms[c] = {}
        self._transforms[c][p] = c_to_p_rec

        # parent_frame -> child_frame carries inverse (-translation)
        inv_translation = (-translation[0], -translation[1], -translation[2])
        p_to_c_rec = TransformRecord(
            parent_frame=p,
            child_frame=c,
            translation=inv_translation,
            rotation=rotation,
            timestamp=ts,
            ttl_sec=ttl_sec,
            transform_digest=digest,
        )
        if p not in self._transforms:
            self._transforms[p] = {}
        self._transforms[p][c] = p_to_c_rec

        return c_to_p_rec

    def transform_pose(
        self,
        pose: Dict[str, Any],
        source_frame: str,
        target_frame: str,
        as_of_time: Optional[datetime] = None,
        max_staleness_sec: Optional[float] = None,
    ) -> TransformedPoseResult:
        """
        Transforms a 3D pose dictionary {'x': ..., 'y': ..., 'z': ...} from
        source_frame to target_frame while checking staleness.
        """
        s = source_frame.strip()
        t = target_frame.strip()

        if s == t:
            return TransformedPoseResult(
                transformed_pose=pose,
                target_frame=t,
                transform_chain=[s],
                transform_timestamp=as_of_time or datetime.now(timezone.utc),
                transform_digest="IDENTITY",
            )

        # BFS for transform path
        queue: List[Tuple[str, List[TransformRecord]]] = [(s, [])]
        visited = {s}
        found_path: Optional[List[TransformRecord]] = None

        while queue:
            curr, path = queue.pop(0)
            if curr == t:
                found_path = path
                break

            for nxt, rec in self._transforms.get(curr, {}).items():
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, path + [rec]))

        if not found_path:
            raise FrameTransformError(
                f"Cannot find transform path between '{source_frame}' and '{target_frame}'.",
                {"source_frame": source_frame, "target_frame": target_frame},
            )

        now = as_of_time or datetime.now(timezone.utc)
        cur_x = float(pose.get("x", 0.0))
        cur_y = float(pose.get("y", 0.0))
        cur_z = float(pose.get("z", 0.0))

        chain_frames = [s]
        combined_digests = []
        oldest_ts = now

        for rec in found_path:
            # Check staleness
            staleness = (now - rec.timestamp).total_seconds()
            limit = max_staleness_sec if max_staleness_sec is not None else rec.ttl_sec
            if staleness > limit:
                raise FrameTransformStaleError(
                    f"Transform from '{rec.parent_frame}' to '{rec.child_frame}' is stale by {staleness:.2f}s (TTL: {limit}s).",
                    {
                        "parent": rec.parent_frame,
                        "child": rec.child_frame,
                        "staleness_sec": staleness,
                        "ttl_sec": limit,
                    },
                )

            cur_x += rec.translation[0]
            cur_y += rec.translation[1]
            cur_z += rec.translation[2]
            chain_frames.append(rec.child_frame)
            combined_digests.append(rec.transform_digest)
            if rec.timestamp < oldest_ts:
                oldest_ts = rec.timestamp

        total_digest = hashlib.sha256(":".join(combined_digests).encode("utf-8")).hexdigest()

        transformed = dict(pose)
        transformed["x"] = round(cur_x, 6)
        transformed["y"] = round(cur_y, 6)
        transformed["z"] = round(cur_z, 6)
        transformed["frame_id"] = t

        return TransformedPoseResult(
            transformed_pose=transformed,
            target_frame=t,
            transform_chain=chain_frames,
            transform_timestamp=oldest_ts,
            transform_digest=total_digest,
        )
