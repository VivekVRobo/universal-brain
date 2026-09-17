#!/usr/bin/env python3
"""Collect Universal Brain V5.2 target-machine evidence.

This command is intentionally non-destructive. It launches a language server only
when explicitly supplied by the operator, performs read-only Windows capability
probes, validates durable lease fencing, and can verify an existing endurance
record. It does not create VMs, install packages, change WSL settings, or bypass
ToolGateway authority.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from universal_brain.engineering import EvidenceStatus, V52TargetEvidenceCollector


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, default=Path.cwd())
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--lsp-executable", default=None)
    p.add_argument("--lsp-arg", action="append", default=[])
    p.add_argument("--lsp-file", type=Path, default=None)
    p.add_argument("--lsp-language-id", default=None)
    p.add_argument("--wsl-distro", default=None)
    p.add_argument("--hyperv-vm", default=None)
    p.add_argument("--endurance-record", type=Path, default=None)
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on skipped target-machine checks as well as failures.",
    )
    return p


async def main() -> int:
    args = parser().parse_args()
    workspace = args.workspace.resolve()
    output = (args.output or workspace / ".brain" / "evidence" / "v52-target-evidence.json").resolve()
    lsp_command = None
    if args.lsp_executable:
        lsp_command = [args.lsp_executable, *args.lsp_arg]

    collector = V52TargetEvidenceCollector(workspace)
    report = await collector.collect(
        lsp_command=lsp_command,
        lsp_file=args.lsp_file,
        lsp_language_id=args.lsp_language_id,
        wsl_distro=args.wsl_distro,
        hyperv_vm=args.hyperv_vm,
        endurance_record=args.endurance_record,
    )
    collector.write_report(output, report)

    print(f"Universal Brain {report.checkpoint} target evidence: {report.overall_status.upper()}")
    for item in report.checks:
        print(f"[{item.status.value.upper():4}] {item.check_id}: {item.summary}")
    print(f"Report: {output}")
    print(f"SHA-256: {report.report_sha256}")

    failures = any(item.status == EvidenceStatus.FAIL for item in report.checks)
    skips = any(item.status == EvidenceStatus.SKIP for item in report.checks)
    if failures or (args.strict and skips):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
