"""Long-running engineering endurance harness for Universal Brain V5.2.

Traceability: REQ-ENG-030, ALN-014, ALN-020. The harness is deliberately
provider-neutral. Production deployments can bind a real-repository cycle runner
and run for hours; unit tests use short deterministic intervals.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


class EnduranceCycleResult(BaseModel):
    cycle: int
    passed: bool
    duration_ms: float = Field(ge=0)
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str = ""


class EnduranceRunReport(BaseModel):
    started_at: datetime
    finished_at: datetime
    requested_duration_seconds: float
    cycles: list[EnduranceCycleResult] = Field(default_factory=list)
    passed: bool
    consecutive_failures_max: int = 0
    checkpoint_path: str | None = None


class EnduranceCycleRunner(Protocol):
    async def run_cycle(self, cycle: int) -> EnduranceCycleResult: ...


class EngineeringEnduranceHarness:
    def __init__(
        self,
        runner: EnduranceCycleRunner,
        *,
        progress_path: Path,
        max_consecutive_failures: int = 3,
        cycle_delay_seconds: float = 0.0,
    ) -> None:
        self.runner = runner
        self.progress_path = progress_path.resolve()
        self.max_consecutive_failures = max(1, max_consecutive_failures)
        self.cycle_delay_seconds = max(0.0, cycle_delay_seconds)

    async def run(
        self,
        *,
        duration_seconds: float,
        max_cycles: int | None = None,
    ) -> EnduranceRunReport:
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be > 0")
        started = datetime.now(timezone.utc)
        start_mono = time.monotonic()
        cycles: list[EnduranceCycleResult] = []
        consecutive = 0
        consecutive_max = 0
        cycle = 0
        while time.monotonic() - start_mono < duration_seconds:
            if max_cycles is not None and cycle >= max_cycles:
                break
            cycle += 1
            result = await self.runner.run_cycle(cycle)
            cycles.append(result)
            consecutive = 0 if result.passed else consecutive + 1
            consecutive_max = max(consecutive_max, consecutive)
            self._persist_progress(started, cycles, duration_seconds, consecutive_max)
            if consecutive >= self.max_consecutive_failures:
                break
            if self.cycle_delay_seconds:
                await asyncio.sleep(self.cycle_delay_seconds)

        finished = datetime.now(timezone.utc)
        passed = bool(cycles) and all(item.passed for item in cycles) and consecutive < self.max_consecutive_failures
        report = EnduranceRunReport(
            started_at=started,
            finished_at=finished,
            requested_duration_seconds=duration_seconds,
            cycles=cycles,
            passed=passed,
            consecutive_failures_max=consecutive_max,
            checkpoint_path=str(self.progress_path),
        )
        self._persist_report(report)
        return report

    def _persist_progress(
        self,
        started: datetime,
        cycles: list[EnduranceCycleResult],
        requested_duration_seconds: float,
        consecutive_max: int,
    ) -> None:
        payload = {
            "started_at": started.isoformat(),
            "requested_duration_seconds": requested_duration_seconds,
            "cycles": [item.model_dump(mode="json") for item in cycles],
            "consecutive_failures_max": consecutive_max,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._atomic_json(payload)

    def _persist_report(self, report: EnduranceRunReport) -> None:
        self._atomic_json(report.model_dump(mode="json"))

    def _atomic_json(self, payload: dict) -> None:
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.progress_path.with_name(f".{self.progress_path.name}.{os.getpid()}.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.progress_path)
