from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .schemas import ModelCapability


class CapabilityEvidenceSource(str, Enum):
    """Origin of an observed capability score.

    Model self-reports are intentionally absent: capability evidence must come from
    configuration, deterministic probes, benchmark/evaluation harnesses, or an
    explicit operator assertion with provenance.
    """

    OPERATOR = "operator"
    BENCHMARK = "benchmark"
    DETERMINISTIC_PROBE = "deterministic_probe"
    EVALUATION = "evaluation"


class CapabilityEvidence(BaseModel):
    model_key: str
    capability: ModelCapability
    score: float = Field(ge=0, le=1)
    source: CapabilityEvidenceSource
    route_id: Optional[str] = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_ref: Optional[str] = None
    notes: Optional[str] = None


class CapabilitySnapshot(BaseModel):
    model_key: str
    capability: ModelCapability
    route_id: Optional[str] = None
    declared_score: float = Field(ge=0, le=1)
    effective_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    sample_count: int = Field(ge=0)
    newest_observation_at: Optional[datetime] = None
    stale: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class CapabilityDiscoveryRegistry:
    """Local, evidence-backed capability discovery overlay.

    Static catalog scores remain a conservative prior. Fresh locally observed
    benchmark/probe evidence may move the effective score up or down, but it never
    changes permissions or action classes. Route-specific observations apply only to
    that access route; global observations apply to every route for the model.
    """

    SCHEMA_VERSION = 1
    SOURCE_WEIGHT = {
        CapabilityEvidenceSource.OPERATOR: 1.00,
        CapabilityEvidenceSource.BENCHMARK: 0.95,
        CapabilityEvidenceSource.DETERMINISTIC_PROBE: 0.90,
        CapabilityEvidenceSource.EVALUATION: 0.85,
    }

    def __init__(
        self,
        *,
        persistence_path: str | Path | None = None,
        freshness_days: float = 45.0,
        decay_factor: float = 0.85,
        declared_prior_weight: float = 1.5,
        max_records: int = 20_000,
    ) -> None:
        self.path = Path(persistence_path).expanduser() if persistence_path else None
        self.freshness_days = max(float(freshness_days), 1.0)
        self.decay_factor = min(max(float(decay_factor), 0.01), 1.0)
        self.declared_prior_weight = max(float(declared_prior_weight), 0.0)
        self.max_records = max(int(max_records), 1)
        self._records: list[CapabilityEvidence] = []
        if self.path and self.path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported capability discovery schema")
        self._records = [
            CapabilityEvidence.model_validate(item) for item in raw.get("records", [])
        ][-self.max_records :]

    def _persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "records": [record.model_dump(mode="json") for record in self._records],
        }
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def record(self, evidence: CapabilityEvidence) -> None:
        self._records.append(evidence)
        if len(self._records) > self.max_records:
            del self._records[: len(self._records) - self.max_records]
        self._persist()

    def record_score(
        self,
        *,
        model_key: str,
        capability: ModelCapability,
        score: float,
        source: CapabilityEvidenceSource,
        route_id: str | None = None,
        evidence_ref: str | None = None,
        notes: str | None = None,
    ) -> CapabilityEvidence:
        evidence = CapabilityEvidence(
            model_key=model_key,
            capability=capability,
            score=score,
            source=source,
            route_id=route_id,
            evidence_ref=evidence_ref,
            notes=notes,
        )
        self.record(evidence)
        return evidence

    def recent(self, limit: int = 100) -> list[CapabilityEvidence]:
        if limit <= 0:
            return []
        return list(reversed(self._records[-limit:]))

    def records_for_model(self, model_key: str) -> list[CapabilityEvidence]:
        return [record for record in self._records if record.model_key == model_key]

    def snapshot(
        self,
        *,
        model_key: str,
        capability: ModelCapability,
        declared_score: float,
        route_id: str | None = None,
        now: datetime | None = None,
    ) -> CapabilitySnapshot:
        now = now or datetime.now(timezone.utc)
        records = [
            record
            for record in self._records
            if record.model_key == model_key
            and record.capability == capability
            and (record.route_id is None or record.route_id == route_id)
        ]
        if not records:
            return CapabilitySnapshot(
                model_key=model_key,
                capability=capability,
                route_id=route_id,
                declared_score=declared_score,
                effective_score=declared_score,
                confidence=0.25,
                sample_count=0,
            )

        weighted_sum = declared_score * self.declared_prior_weight
        total_weight = self.declared_prior_weight
        newest = max(record.observed_at for record in records)
        refs: list[str] = []
        evidence_weight_total = 0.0
        for record in records:
            age_days = max((now - record.observed_at).total_seconds() / 86_400.0, 0.0)
            freshness = self.decay_factor ** (age_days / self.freshness_days)
            route_specific = 1.08 if record.route_id is not None else 1.0
            weight = self.SOURCE_WEIGHT[record.source] * freshness * route_specific
            weighted_sum += record.score * weight
            total_weight += weight
            evidence_weight_total += weight
            if record.evidence_ref and record.evidence_ref not in refs:
                refs.append(record.evidence_ref)

        effective = weighted_sum / max(total_weight, 1e-9)
        confidence = min(1.0, 0.25 + evidence_weight_total / 3.0)
        stale = (now - newest).total_seconds() / 86_400.0 > self.freshness_days * 2
        return CapabilitySnapshot(
            model_key=model_key,
            capability=capability,
            route_id=route_id,
            declared_score=round(float(declared_score), 6),
            effective_score=round(max(0.0, min(1.0, effective)), 6),
            confidence=round(confidence, 6),
            sample_count=len(records),
            newest_observation_at=newest,
            stale=stale,
            evidence_refs=refs,
        )
