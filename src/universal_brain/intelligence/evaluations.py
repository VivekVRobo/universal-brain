from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ModelEvaluationRecord(BaseModel):
    model_key: str
    route_id: str
    task_kind: str = "general"
    quality_score: float = Field(ge=0, le=1)
    success: bool = True
    latency_ms: Optional[float] = Field(default=None, ge=0)
    cost_usd: Optional[float] = Field(default=None, ge=0)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_ref: Optional[str] = None


class PerformanceSnapshot(BaseModel):
    model_key: str
    task_kind: str
    sample_count: int
    empirical_score: float = Field(ge=0, le=1)
    drift_ratio: float = Field(ge=0)
    drift_alert: bool


class PerformanceLedger:
    """Operator/evaluator-supplied quality observations with optional durability.

    Transport success is intentionally not treated as model quality. Records should
    come from deterministic tests, benchmark harnesses, or explicit human review.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        inactivity_period_days: float = 30.0,
        inactivity_decay_factor: float = 0.90,
        drift_alert_ratio: float = 0.70,
        persistence_path: str | Path | None = None,
        max_records: int = 10_000,
    ):
        self.period = inactivity_period_days
        self.decay = inactivity_decay_factor
        self.alert = drift_alert_ratio
        self.path = Path(persistence_path).expanduser() if persistence_path else None
        self.max_records = max_records
        self._records: list[ModelEvaluationRecord] = []
        self._baselines: dict[tuple[str, str], float] = {}
        if self.path and self.path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported performance ledger schema")
        self._records = [
            ModelEvaluationRecord.model_validate(item) for item in raw.get("records", [])
        ][-self.max_records :]
        self._baselines = {}
        for record in self._records:
            key = (record.model_key, record.task_kind)
            score = record.quality_score if record.success else 0.0
            self._baselines[key] = max(self._baselines.get(key, 0.0), score)

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

    def record(self, record: ModelEvaluationRecord) -> None:
        self._records.append(record)
        if len(self._records) > self.max_records:
            del self._records[: len(self._records) - self.max_records]
        key = (record.model_key, record.task_kind)
        score = record.quality_score if record.success else 0.0
        self._baselines[key] = max(self._baselines.get(key, 0.0), score)
        self._persist()

    def recent(self, limit: int = 100) -> list[ModelEvaluationRecord]:
        return list(reversed(self._records[-max(limit, 0) :])) if limit > 0 else []

    def snapshot(
        self,
        model_key: str,
        task_kind: str = "general",
        now: datetime | None = None,
    ) -> PerformanceSnapshot:
        now = now or datetime.now(timezone.utc)
        records = [
            record
            for record in self._records
            if record.model_key == model_key and record.task_kind == task_kind
        ]
        baseline = self._baselines.get((model_key, task_kind), 0.0)
        if not records:
            return PerformanceSnapshot(
                model_key=model_key,
                task_kind=task_kind,
                sample_count=0,
                empirical_score=0.75,
                drift_ratio=1.0,
                drift_alert=False,
            )

        weighted: list[tuple[float, float, bool]] = []
        for record in records:
            age_days = max((now - record.observed_at).total_seconds() / 86_400, 0.0)
            weight = self.decay ** (age_days / self.period)
            weighted.append(
                (record.quality_score if record.success else 0.0, weight, record.success)
            )

        total_weight = sum(weight for _, weight, _ in weighted)
        quality = sum(value * weight for value, weight, _ in weighted) / total_weight
        success_rate = sum((1 if ok else 0) * weight for _, weight, ok in weighted) / total_weight
        empirical = max(0.0, min(1.0, quality * 0.8 + success_rate * 0.2))
        ratio = empirical / baseline if baseline else 1.0
        return PerformanceSnapshot(
            model_key=model_key,
            task_kind=task_kind,
            sample_count=len(records),
            empirical_score=round(empirical, 6),
            drift_ratio=round(ratio, 6),
            drift_alert=len(records) >= 2 and ratio < self.alert,
        )
