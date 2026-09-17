"""
Universal Brain - Source Reliability & Sensor Drift Tracker
Implements Sections 17-20 of Milestone M8 Specification (M8-INV-06).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from universal_brain.world.schemas import SourceHealth, SourceReliability


class SourceReliabilityTracker:
    """
    Maintains quantitative, evidence-grounded reliability metrics per observation source,
    detects gradual sensor drift, and manages recovery hysteresis.
    """

    POLICY_VERSION = 1

    def __init__(self, recovery_threshold_consecutive: int = 3) -> None:
        self.recovery_threshold = recovery_threshold_consecutive
        self._records: Dict[str, SourceReliability] = {}
        self._consecutive_successes: Dict[str, int] = {}
        self._recent_errors: Dict[str, List[float]] = {}

    def get_or_create_record(self, source_id: str) -> SourceReliability:
        if source_id not in self._records:
            self._records[source_id] = SourceReliability(
                source_id=source_id,
                samples=0,
                confirmed=0,
                contradicted=0,
                invalid=0,
                outliers=0,
                reliability_score=1.0,
                reliability_policy_version=self.POLICY_VERSION,
                drift_detected=False,
                last_calibrated_at=datetime.now(timezone.utc),
            )
            self._consecutive_successes[source_id] = 0
            self._recent_errors[source_id] = []
        return self._records[source_id]

    def record_success(self, source_id: str, confirmed: bool = True) -> SourceReliability:
        rec = self.get_or_create_record(source_id)
        rec.samples += 1
        if confirmed:
            rec.confirmed += 1
        self._consecutive_successes[source_id] = self._consecutive_successes.get(source_id, 0) + 1
        self._recompute_score(rec)
        return rec

    def record_contradiction(self, source_id: str) -> SourceReliability:
        rec = self.get_or_create_record(source_id)
        rec.samples += 1
        rec.contradicted += 1
        self._consecutive_successes[source_id] = 0
        self._recompute_score(rec)
        return rec

    def record_outlier(self, source_id: str, value: float, reference: float) -> SourceReliability:
        rec = self.get_or_create_record(source_id)
        rec.samples += 1
        rec.outliers += 1
        self._consecutive_successes[source_id] = 0

        # Track error delta for drift
        delta = abs(value - reference)
        errors = self._recent_errors.setdefault(source_id, [])
        errors.append(delta)
        if len(errors) > 10:
            errors.pop(0)

        # If average error is consistently large, mark drift
        if len(errors) >= 3 and (sum(errors) / len(errors)) > 1.5:
            rec.drift_detected = True

        self._recompute_score(rec)
        return rec

    def check_recovery_eligibility(self, source_id: str) -> bool:
        """Returns True if degraded source has achieved enough consecutive good readings."""
        return self._consecutive_successes.get(source_id, 0) >= self.recovery_threshold

    def _recompute_score(self, rec: SourceReliability) -> None:
        if rec.samples == 0:
            rec.reliability_score = 1.0
            return

        # Weighting: confirmed additions vs penalties for contradictions, outliers, and drift
        penalty = (rec.contradicted * 0.15) + (rec.outliers * 0.1) + (0.2 if rec.drift_detected else 0.0)
        base = max(0.0, 1.0 - penalty)
        rec.reliability_score = round(max(0.1, min(1.0, base)), 4)
