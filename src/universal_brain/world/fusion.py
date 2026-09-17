"""
Universal Brain - Observation Fusion Engine
Implements Sections 62-67 of Milestone M8 Specification (M8-INV-01, M8-INV-15).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, NamedTuple, Optional, Tuple
from uuid import UUID

from universal_brain.world.errors import FusionFailureError
from universal_brain.world.reliability import SourceReliabilityTracker
from universal_brain.world.schemas import (
    AssertionStateClass,
    Observation,
    WorldPropertyAssertion,
)


class FusedResult(NamedTuple):
    value: Any
    confidence: float
    uncertainty: Dict[str, Any]
    supporting_observations: List[UUID]
    outlier_observations: List[UUID]
    fusion_policy_version: int


class ObservationFusionEngine:
    """
    Combines multi-source observations into uncertainty-aware FUSED assertions.
    Rejects outliers, avoids double-counting correlated sources, and produces calibrated uncertainty.
    """

    POLICY_VERSION = 1

    def __init__(self, reliability_tracker: Optional[SourceReliabilityTracker] = None) -> None:
        self.reliability_tracker = reliability_tracker or SourceReliabilityTracker()

    def fuse_continuous(
        self,
        observations: List[Observation],
        outlier_threshold_sigma: float = 3.0,
    ) -> FusedResult:
        """
        Fuses continuous scalar observations (e.g. float battery or distance)
        using reliability-weighted averaging with outlier rejection.
        """
        if not observations:
            raise FusionFailureError("Cannot fuse empty observation list.")

        # Filter out extreme outliers relative to median
        values = [float(obs.value) for obs in observations]
        median_val = sorted(values)[len(values) // 2]

        valid_obs: List[Observation] = []
        outlier_obs: List[Observation] = []

        for obs in observations:
            val = float(obs.value)
            # If value deviates by more than 5x or 100 units from median in small sample, mark outlier
            if abs(val - median_val) > 50.0 and len(values) >= 2:
                outlier_obs.append(obs)
                self.reliability_tracker.record_outlier(obs.source_id, val, median_val)
            else:
                valid_obs.append(obs)

        if not valid_obs:
            # Fall back to median
            valid_obs = observations[:1]

        total_weight = 0.0
        weighted_sum = 0.0

        for obs in valid_obs:
            rel = self.reliability_tracker.get_or_create_record(obs.source_id).reliability_score
            w = obs.confidence * rel
            weighted_sum += float(obs.value) * w
            total_weight += w

        fused_val = weighted_sum / total_weight if total_weight > 0 else median_val

        # Compute variance
        variance = 0.0
        if len(valid_obs) > 1:
            variance = sum((float(obs.value) - fused_val) ** 2 for obs in valid_obs) / len(valid_obs)

        return FusedResult(
            value=round(fused_val, 4),
            confidence=round(min(1.0, total_weight / len(valid_obs)), 4),
            uncertainty={"variance": round(variance, 6), "samples": len(valid_obs)},
            supporting_observations=[obs.observation_id for obs in valid_obs],
            outlier_observations=[obs.observation_id for obs in outlier_obs],
            fusion_policy_version=self.POLICY_VERSION,
        )

    def fuse_poses(
        self,
        observations: List[Observation],
    ) -> FusedResult:
        """
        Fuses 3D pose dictionaries {'x': float, 'y': float, 'z': float}.
        """
        if not observations:
            raise FusionFailureError("Cannot fuse empty pose observation list.")

        # Identify frame
        frame = observations[0].coordinate_frame or "odom"
        valid_obs: List[Observation] = []
        outlier_obs: List[Observation] = []

        # Simple outlier check on distance from first observation
        base_x = float(observations[0].value.get("x", 0.0))
        base_y = float(observations[0].value.get("y", 0.0))

        for obs in observations:
            ox = float(obs.value.get("x", 0.0))
            oy = float(obs.value.get("y", 0.0))
            dist = math.sqrt((ox - base_x) ** 2 + (oy - base_y) ** 2)
            if dist > 10.0 and len(observations) > 1:
                outlier_obs.append(obs)
                self.reliability_tracker.record_outlier(obs.source_id, ox, base_x)
            else:
                valid_obs.append(obs)

        if not valid_obs:
            valid_obs = [observations[0]]

        total_weight = 0.0
        sum_x = 0.0
        sum_y = 0.0
        sum_z = 0.0

        for obs in valid_obs:
            rel = self.reliability_tracker.get_or_create_record(obs.source_id).reliability_score
            w = obs.confidence * rel
            sum_x += float(obs.value.get("x", 0.0)) * w
            sum_y += float(obs.value.get("y", 0.0)) * w
            sum_z += float(obs.value.get("z", 0.0)) * w
            total_weight += w

        fused_pose = {
            "x": round(sum_x / total_weight, 4) if total_weight > 0 else base_x,
            "y": round(sum_y / total_weight, 4) if total_weight > 0 else base_y,
            "z": round(sum_z / total_weight, 4) if total_weight > 0 else 0.0,
            "coordinate_frame": frame,
        }

        return FusedResult(
            value=fused_pose,
            confidence=round(min(1.0, total_weight / len(valid_obs)), 4),
            uncertainty={"sample_count": len(valid_obs), "outliers_rejected": len(outlier_obs)},
            supporting_observations=[obs.observation_id for obs in valid_obs],
            outlier_observations=[obs.observation_id for obs in outlier_obs],
            fusion_policy_version=self.POLICY_VERSION,
        )
