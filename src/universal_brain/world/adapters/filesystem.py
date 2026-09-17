"""
Universal Brain - Filesystem & Repository Perception Adapter
Implements Sections 103-104 of Milestone M8 Specification.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from universal_brain.world.adapters.base import PerceptionAdapter
from universal_brain.world.schemas import (
    Observation,
    ObservationType,
    PrivacyClass,
    SourceHealth,
)


class FilesystemAdapter(PerceptionAdapter):
    """
    Perception adapter monitoring file changes, branch heads, and repository revisions.
    """

    def start(self) -> None:
        self.health_status = SourceHealth.HEALTHY

    def stop(self) -> None:
        self.health_status = SourceHealth.STALE

    def observe(self, raw_signal: Any) -> Optional[Observation]:
        """
        raw_signal format:
        {
            'subject_ref': 'repo_main' or 'file_path',
            'property_key': 'head_commit' or 'file_digest',
            'value': 'abc1234',
            'source_obs_id': optional str,
        }
        """
        if not isinstance(raw_signal, dict):
            return None

        now = datetime.now(timezone.utc)
        seq = self.next_sequence()
        obs_id_str = raw_signal.get("source_obs_id") or f"fs-{seq}-{int(now.timestamp())}"

        raw_bytes = json.dumps(raw_signal, sort_keys=True).encode("utf-8")
        raw_digest = hashlib.sha256(raw_bytes).hexdigest()

        obs = Observation(
            source_id=self.source_id,
            source_session_id=self.source_session_id,
            source_observation_id=obs_id_str,
            source_sequence=seq,
            observation_type=ObservationType.CONTENT_CHANGE,
            subject_ref=raw_signal.get("subject_ref", "repo_main"),
            property_key=raw_signal.get("property_key", "head_commit"),
            value=raw_signal.get("value"),
            unit=None,
            coordinate_frame=None,
            observed_at=now,
            received_at=now,
            valid_from=now,
            valid_until=None,
            confidence=1.0,
            privacy_class=self.privacy_class,
            raw_payload_digest=raw_digest,
            schema_version=1,
            ontology_version=1,
        )
        obs.observation_digest = obs.calculate_digest()
        return obs
