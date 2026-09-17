"""
Universal Brain - ROS2 Perception Adapter & High-Rate Stream Compactor
Implements Sections 106-109 of Milestone M8 Specification (M8-INV-10, M8-INV-12).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from universal_brain.world.adapters.base import PerceptionAdapter
from universal_brain.world.schemas import (
    EnvironmentMode,
    Observation,
    ObservationType,
    PrivacyClass,
    SourceHealth,
)


class ROS2Adapter(PerceptionAdapter):
    """
    Perception adapter for ROS2 robotics topics (/odom, /joint_states, /scan, /battery_state).
    Preserves frame_id, manages high-rate compaction, and preserves simulation/real environment mode.
    """

    def __init__(
        self,
        source_id: str,
        source_session_id: UUID,
        privacy_class: PrivacyClass = PrivacyClass.INTERNAL,
        environment_mode: EnvironmentMode = EnvironmentMode.REAL,
        compaction_ratio: int = 1,  # 1 = emit every sample; >1 = downsample high rate
    ) -> None:
        super().__init__(source_id, source_session_id, privacy_class)
        self.environment_mode = environment_mode
        self.compaction_ratio = compaction_ratio
        self._raw_sample_accumulator: List[Dict[str, Any]] = []

    def start(self) -> None:
        self.health_status = SourceHealth.HEALTHY

    def stop(self) -> None:
        self.health_status = SourceHealth.STALE

    def observe(self, raw_signal: Any) -> Optional[Observation]:
        """
        raw_signal format:
        {
            'topic': '/odom',
            'subject_ref': 'robot_arm_1',
            'property_key': 'pose',
            'value': {'x': 1.2, 'y': 0.5, 'z': 0.0},
            'frame_id': 'odom',
            'unit': 'm',
            'source_obs_id': optional str,
        }
        """
        if not isinstance(raw_signal, dict):
            return None

        self._raw_sample_accumulator.append(raw_signal)

        # High-rate stream compaction (Section 61)
        if len(self._raw_sample_accumulator) < self.compaction_ratio:
            return None

        samples_batch = list(self._raw_sample_accumulator)
        self._raw_sample_accumulator.clear()

        # Representative sample is the latest
        latest = samples_batch[-1]
        now = datetime.now(timezone.utc)
        seq = self.next_sequence()
        obs_id_str = latest.get("source_obs_id") or f"ros2-{seq}-{int(now.timestamp())}"

        # Hash entire batch payload to preserve raw stream provenance
        raw_bytes = json.dumps(samples_batch, sort_keys=True, default=str).encode("utf-8")
        batch_digest = hashlib.sha256(raw_bytes).hexdigest()

        obs = Observation(
            source_id=self.source_id,
            source_session_id=self.source_session_id,
            source_observation_id=obs_id_str,
            source_sequence=seq,
            observation_type=ObservationType.LOCATION if latest.get("property_key") == "pose" else ObservationType.MEASUREMENT,
            subject_ref=latest.get("subject_ref", "robot"),
            property_key=latest.get("property_key", "pose"),
            value=latest.get("value"),
            unit=latest.get("unit", "m"),
            coordinate_frame=latest.get("frame_id", "odom"),
            observed_at=now,
            received_at=now,
            valid_from=now,
            valid_until=None,
            confidence=1.0,
            privacy_class=self.privacy_class,
            environment_mode=self.environment_mode,
            raw_payload_digest=batch_digest,
            quality_flags=["COMPACTED"] if len(samples_batch) > 1 else [],
            schema_version=1,
            ontology_version=1,
        )
        obs.observation_digest = obs.calculate_digest()
        return obs
