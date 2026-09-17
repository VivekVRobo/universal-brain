#!/usr/bin/env python3
"""Run Universal Brain V5.3 real-environment validation.

The command is evidence-oriented. It does not install packages, create WSL
instances/Hyper-V VMs, change network policy, or bypass authentication. Missing
operator-supplied target capabilities remain SKIP rather than becoming PASS.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from universal_brain.engineering import (
    EvidenceStatus,
    HttpOllamaProbeClient,
    V53EvidenceBundler,
    V53OllamaValidator,
    V53RealEnvironmentValidator,
    V53AuthorityServiceScenario,
    V53OllamaPressureScenario,
    V53RestartRecoveryLab,
    V53WSLIsolationExecutionScenario,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, default=Path.cwd())
    p.add_argument("--evidence-root", type=Path, default=None)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--lsp-executable", default=None)
    p.add_argument("--lsp-arg", action="append", default=[])
    p.add_argument("--lsp-file", type=Path, default=None)
    p.add_argument("--lsp-language-id", default=None)
    p.add_argument("--wsl-distro", default=None)
    p.add_argument("--hyperv-vm", default=None)
    p.add_argument("--endurance-record", type=Path, default=None)
    p.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    p.add_argument("--ollama-model", action="append", default=[])
    p.add_argument("--allow-remote-ollama", action="store_true")
    p.add_argument("--skip-git-lab", action="store_true")
    p.add_argument("--enable-service-workload", action="store_true")
    p.add_argument("--enable-restart-probe", action="store_true")
    p.add_argument("--enable-ollama-pressure", action="store_true", help="Opt in to one concurrent prompt per selected Ollama model; may use substantial RAM/VRAM.")
    p.add_argument("--wsl-linux-workspace", default=None, help="Absolute WSL path mapping to --workspace; enables real one-time ToolGateway WSL execution when --wsl-distro is also set.")
    p.add_argument("--verify-existing-manifest", action="store_true")
    return p


async def main() -> int:
    args = parser().parse_args()
    workspace = args.workspace.resolve()
    evidence_root = (args.evidence_root or workspace / ".brain" / "evidence" / "v53").resolve()
    if args.verify_existing_manifest:
        ok, errors = V53EvidenceBundler(evidence_root).verify()
        print(f"V5.3 evidence manifest: {'PASS' if ok else 'FAIL'}")
        for error in errors:
            print(f"- {error}")
        return 0 if ok else 2

    lsp_command = [args.lsp_executable, *args.lsp_arg] if args.lsp_executable else None
    ollama_validator = None
    if args.ollama_model:
        client = HttpOllamaProbeClient(args.ollama_url, allow_remote=args.allow_remote_ollama)
        ollama_validator = V53OllamaValidator(client)

    extra = []
    if args.enable_service_workload:
        extra.append(V53AuthorityServiceScenario(workspace, evidence_root).run)
    if args.enable_restart_probe:
        extra.append(V53RestartRecoveryLab(workspace, evidence_root).run)
    if args.enable_ollama_pressure:
        if ollama_validator is None:
            raise SystemExit("--enable-ollama-pressure requires at least one --ollama-model")
        extra.append(V53OllamaPressureScenario(ollama_validator.client, args.ollama_model).run)
    if args.wsl_distro and args.wsl_linux_workspace:
        extra.append(V53WSLIsolationExecutionScenario(workspace, args.wsl_distro, args.wsl_linux_workspace).run)

    validator = V53RealEnvironmentValidator(workspace, evidence_root)
    report = await validator.run(
        lsp_command=lsp_command,
        lsp_file=args.lsp_file,
        lsp_language_id=args.lsp_language_id,
        wsl_distro=args.wsl_distro,
        hyperv_vm=args.hyperv_vm,
        endurance_record=args.endurance_record,
        ollama_validator=ollama_validator,
        ollama_models=args.ollama_model,
        include_git_lab=not args.skip_git_lab,
        extra_scenarios=extra,
        resume=args.resume,
    )
    print(f"Universal Brain {report.checkpoint} validation: {report.overall_status.upper()}")
    for item in report.results:
        print(f"[{item.status.value.upper():4}] {item.scenario_id}: {item.summary}")
    print(f"Report SHA-256: {report.report_sha256}")
    print(f"Evidence root: {evidence_root}")
    failures = any(item.status == EvidenceStatus.FAIL for item in report.results)
    skips = any(item.status == EvidenceStatus.SKIP for item in report.results)
    return 2 if failures or (args.strict and skips) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
