#!/usr/bin/env python3
"""Run a bounded, resumable V5.2 real-repository endurance command loop.

The operator supplies an argv JSON array; no shell expansion is used. Each cycle
writes stdout/stderr evidence and the EngineeringEnduranceHarness atomically updates
the run record. A >=2 hour passing record can later satisfy the V5.2 evidence gate.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from universal_brain.engineering import EnduranceCycleResult, EngineeringEnduranceHarness


class CommandCycleRunner:
    def __init__(self, workspace: Path, command: list[str], evidence_dir: Path, timeout_seconds: int) -> None:
        self.workspace = workspace.resolve()
        self.command = list(command)
        self.evidence_dir = evidence_dir.resolve()
        self.timeout_seconds = timeout_seconds
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    async def run_cycle(self, cycle: int) -> EnduranceCycleResult:
        start = time.monotonic()
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                self.command,
                cwd=str(self.workspace),
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
            stdout = result.stdout or b""
            stderr = result.stderr or b""
            exit_code = result.returncode
            reason = f"exit_code={exit_code}"
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            exit_code = -1
            reason = f"timeout>{self.timeout_seconds}s"
        duration_ms = (time.monotonic() - start) * 1000.0
        stdout_path = self.evidence_dir / f"cycle-{cycle:06d}.stdout.log"
        stderr_path = self.evidence_dir / f"cycle-{cycle:06d}.stderr.log"
        meta_path = self.evidence_dir / f"cycle-{cycle:06d}.json"
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        meta = {
            "cycle": cycle,
            "command": self.command,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            "reason": reason,
        }
        meta_path.write_text(json.dumps(meta, sort_keys=True, indent=2), encoding="utf-8")
        return EnduranceCycleResult(
            cycle=cycle,
            passed=exit_code == 0,
            duration_ms=duration_ms,
            evidence_refs=[str(meta_path), str(stdout_path), str(stderr_path)],
            reason=reason,
        )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, default=Path.cwd())
    p.add_argument("--duration-hours", type=float, required=True)
    p.add_argument("--command-json", required=True, help='JSON argv array, e.g. ["python","-m","pytest","-q"]')
    p.add_argument("--record", type=Path, default=None)
    p.add_argument("--evidence-dir", type=Path, default=None)
    p.add_argument("--cycle-timeout-seconds", type=int, default=1800)
    p.add_argument("--cycle-delay-seconds", type=float, default=5.0)
    p.add_argument("--max-consecutive-failures", type=int, default=3)
    p.add_argument("--max-cycles", type=int, default=None)
    return p


async def main() -> int:
    args = build_parser().parse_args()
    if args.duration_hours <= 0:
        raise SystemExit("--duration-hours must be > 0")
    command = json.loads(args.command_json)
    if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
        raise SystemExit("--command-json must be a non-empty JSON array of strings")
    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace does not exist: {workspace}")
    record = (args.record or workspace / ".brain" / "evidence" / "v52-endurance.json").resolve()
    evidence_dir = (args.evidence_dir or record.parent / "v52-endurance-cycles").resolve()
    runner = CommandCycleRunner(workspace, command, evidence_dir, args.cycle_timeout_seconds)
    harness = EngineeringEnduranceHarness(
        runner,
        progress_path=record,
        max_consecutive_failures=args.max_consecutive_failures,
        cycle_delay_seconds=args.cycle_delay_seconds,
    )
    report = await harness.run(
        duration_seconds=args.duration_hours * 3600,
        max_cycles=args.max_cycles,
    )
    print(f"Endurance result: {'PASS' if report.passed else 'FAIL'}")
    print(f"Cycles: {len(report.cycles)}")
    print(f"Record: {record}")
    if args.duration_hours < 2:
        print("NOTE: This is a smoke/endurance run but does not satisfy the >=2 hour V5.2 evidence gate.")
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
