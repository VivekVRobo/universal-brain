from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .schemas import ModelUsage, TransportKind


class RouteInvocationRecord(BaseModel):
    invocation_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    model_key: str
    route_id: str
    transport: TransportKind
    task_kind: str = "general"
    status: str
    started_at: datetime
    ended_at: datetime
    latency_ms: float = Field(ge=0)
    usage: ModelUsage = Field(default_factory=ModelUsage)
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    streamed: bool = False


class RouteTelemetrySnapshot(BaseModel):
    route_id: str
    sample_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = Field(default=0.0, ge=0, le=1)
    average_latency_ms: float = Field(default=0.0, ge=0)
    p95_latency_ms: float = Field(default=0.0, ge=0)
    total_input_tokens: int = Field(default=0, ge=0)
    total_output_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0)
    last_status: Optional[str] = None
    last_error_type: Optional[str] = None
    last_observed_at: Optional[datetime] = None


class RouteTelemetryRegistry:
    """Durable route-level operational telemetry.

    Prompt/response bodies are deliberately excluded. The registry stores only
    routing identifiers, status, latency, usage, and sanitized error metadata.
    """

    SCHEMA_VERSION = 1

    def __init__(self, persistence_path: str | Path | None = None, max_records: int = 5_000):
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        self.path = Path(persistence_path).expanduser() if persistence_path else None
        self.max_records = max_records
        self._records: list[RouteInvocationRecord] = []
        if self.path and self.path.exists():
            self._load()

    @staticmethod
    def _safe_error(message: str | None) -> str | None:
        if not message:
            return None
        compact = " ".join(str(message).split())
        return compact[:400]

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported route telemetry schema")
        records = [RouteInvocationRecord.model_validate(item) for item in raw.get("records", [])]
        self._records = records[-self.max_records :]

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

    def record(self, record: RouteInvocationRecord) -> RouteInvocationRecord:
        cleaned = record.model_copy(
            update={"error_message": self._safe_error(record.error_message)}
        )
        self._records.append(cleaned)
        if len(self._records) > self.max_records:
            del self._records[: len(self._records) - self.max_records]
        self._persist()
        return cleaned

    def recent(self, limit: int = 50, route_id: str | None = None) -> list[RouteInvocationRecord]:
        if limit <= 0:
            return []
        records = self._records
        if route_id is not None:
            records = [record for record in records if record.route_id == route_id]
        return list(reversed(records[-limit:]))

    def snapshot(self, route_id: str) -> RouteTelemetrySnapshot:
        records = [record for record in self._records if record.route_id == route_id]
        if not records:
            return RouteTelemetrySnapshot(route_id=route_id)
        successes = [record for record in records if record.status == "success"]
        latencies = sorted(record.latency_ms for record in records)
        p95_index = max(0, min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1)))))
        last = records[-1]
        return RouteTelemetrySnapshot(
            route_id=route_id,
            sample_count=len(records),
            success_count=len(successes),
            failure_count=len(records) - len(successes),
            success_rate=round(len(successes) / len(records), 6),
            average_latency_ms=round(sum(latencies) / len(latencies), 3),
            p95_latency_ms=round(latencies[p95_index], 3),
            total_input_tokens=sum(record.usage.input_tokens for record in records),
            total_output_tokens=sum(record.usage.output_tokens for record in records),
            total_cost_usd=round(sum(record.usage.cost_usd for record in records), 8),
            last_status=last.status,
            last_error_type=last.error_type,
            last_observed_at=last.ended_at,
        )

    def all_snapshots(self, route_ids: list[str] | None = None) -> list[RouteTelemetrySnapshot]:
        if route_ids is None:
            route_ids = sorted({record.route_id for record in self._records})
        return [self.snapshot(route_id) for route_id in route_ids]

    @staticmethod
    def make_record(
        *,
        request_id: UUID,
        model_key: str,
        route_id: str,
        transport: TransportKind,
        task_kind: str,
        status: str,
        started_at: datetime,
        latency_ms: float,
        usage: ModelUsage | None = None,
        error: Exception | None = None,
        streamed: bool = False,
    ) -> RouteInvocationRecord:
        return RouteInvocationRecord(
            request_id=request_id,
            model_key=model_key,
            route_id=route_id,
            transport=transport,
            task_kind=task_kind,
            status=status,
            started_at=started_at,
            ended_at=datetime.now(timezone.utc),
            latency_ms=max(0.0, latency_ms),
            usage=usage or ModelUsage(),
            error_type=type(error).__name__ if error else None,
            error_message=str(error) if error else None,
            streamed=streamed,
        )
