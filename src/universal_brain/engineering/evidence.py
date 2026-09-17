"""Target-machine evidence records for Universal Brain V5.2.

Traceability: REQ-ENG-032, REQ-ENG-033, REQ-TOL-001, ALN-016, ALN-020.

The cross-platform test suite proves implementation logic. This module is for the
separate deployment-evidence layer: real semantic runtimes, Windows isolation,
service lifecycle, distributed leases, and endurance records. Evidence reports
are self-digested and intentionally separate "not tested" from "failed".
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .distributed_leases import DurableWorkerLeaseStore
from .endurance import EnduranceRunReport
from .lsp_runtime import StdioLspBackend
from .semantic import LspSemanticProvider, SemanticBackendUnavailable, TreeSitterSemanticProvider


class EvidenceStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


class TargetEvidenceItem(BaseModel):
    check_id: str
    status: EvidenceStatus
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class TargetMachineEvidenceReport(BaseModel):
    schema_version: str = "ub-engineering-evidence/v1"
    checkpoint: str = "V5.2"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    platform: str
    platform_release: str
    python_version: str
    workspace: str
    checks: list[TargetEvidenceItem] = Field(default_factory=list)
    overall_status: str = "partial"
    report_sha256: str = ""

    def canonical_bytes(self) -> bytes:
        payload = self.model_dump(mode="json")
        payload["report_sha256"] = ""
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def seal(self) -> "TargetMachineEvidenceReport":
        digest = hashlib.sha256(self.canonical_bytes()).hexdigest()
        return self.model_copy(update={"report_sha256": digest})

    def verify_digest(self) -> bool:
        return bool(self.report_sha256) and hashlib.sha256(self.canonical_bytes()).hexdigest() == self.report_sha256


class V52TargetEvidenceCollector:
    """Collect non-fabricated deployment evidence with explicit skips.

    Potentially expensive/mutating checks are opt-in. Basic platform, Tree-sitter,
    LSP, WSL2 and Hyper-V probes are read-only except for launching temporary
    language-server processes.
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        if not self.workspace.exists():
            raise ValueError(f"workspace does not exist: {self.workspace}")

    async def collect(
        self,
        *,
        lsp_command: list[str] | None = None,
        lsp_file: Path | None = None,
        lsp_language_id: str | None = None,
        wsl_distro: str | None = None,
        hyperv_vm: str | None = None,
        endurance_record: Path | None = None,
    ) -> TargetMachineEvidenceReport:
        checks = [self._platform_check(), self._tree_sitter_check()]
        checks.append(
            await self._lsp_check(
                lsp_command=lsp_command,
                lsp_file=lsp_file,
                lsp_language_id=lsp_language_id,
            )
        )
        checks.append(self._wsl_check(wsl_distro))
        checks.append(self._hyperv_check(hyperv_vm))
        checks.append(self._distributed_lease_check())
        checks.append(self._endurance_record_check(endurance_record))
        failures = [item for item in checks if item.status == EvidenceStatus.FAIL]
        skips = [item for item in checks if item.status == EvidenceStatus.SKIP]
        overall = "failed" if failures else "partial" if skips else "passed"
        return TargetMachineEvidenceReport(
            platform=platform.system(),
            platform_release=platform.release(),
            python_version=platform.python_version(),
            workspace=str(self.workspace),
            checks=checks,
            overall_status=overall,
        ).seal()

    def write_report(self, path: Path, report: TargetMachineEvidenceReport) -> Path:
        sealed = report if report.verify_digest() else report.seal()
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(sealed.model_dump(mode="json"), handle, sort_keys=True, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        return path

    def _platform_check(self) -> TargetEvidenceItem:
        return TargetEvidenceItem(
            check_id="platform",
            status=EvidenceStatus.PASS,
            summary=f"{platform.system()} {platform.release()} / Python {platform.python_version()}",
            details={"machine": platform.machine(), "python_executable": sys.executable},
        )

    def _tree_sitter_check(self) -> TargetEvidenceItem:
        with tempfile.TemporaryDirectory(prefix="ub-v52-ts-") as directory:
            sample = Path(directory) / "sample.py"
            sample.write_text("class EvidenceProbe:\n    def run(self):\n        return 1\n", encoding="utf-8")
            try:
                facts = TreeSitterSemanticProvider().parse_file(sample)
            except SemanticBackendUnavailable as exc:
                return TargetEvidenceItem(
                    check_id="tree_sitter",
                    status=EvidenceStatus.SKIP,
                    summary="Tree-sitter optional runtime is not installed",
                    details={"reason": str(exc)},
                )
            except Exception as exc:
                return TargetEvidenceItem(
                    check_id="tree_sitter",
                    status=EvidenceStatus.FAIL,
                    summary="Tree-sitter runtime failed",
                    details={"error": f"{type(exc).__name__}: {exc}"},
                )
            names = sorted({item.name for item in facts})
            return TargetEvidenceItem(
                check_id="tree_sitter",
                status=EvidenceStatus.PASS if "EvidenceProbe" in names else EvidenceStatus.FAIL,
                summary=f"Parsed {len(facts)} semantic declaration facts",
                details={"symbols": names, "provider": "tree-sitter-language-pack"},
            )

    async def _lsp_check(
        self,
        *,
        lsp_command: list[str] | None,
        lsp_file: Path | None,
        lsp_language_id: str | None,
    ) -> TargetEvidenceItem:
        if not lsp_command:
            return TargetEvidenceItem(
                check_id="lsp",
                status=EvidenceStatus.SKIP,
                summary="No operator-authorized language-server command supplied",
            )
        if lsp_file is None or not lsp_language_id:
            return TargetEvidenceItem(
                check_id="lsp",
                status=EvidenceStatus.FAIL,
                summary="LSP command supplied without --lsp-file and --lsp-language-id",
            )
        source = lsp_file.resolve()
        try:
            source.relative_to(self.workspace)
        except ValueError:
            return TargetEvidenceItem(
                check_id="lsp",
                status=EvidenceStatus.FAIL,
                summary="LSP probe file is outside the authorized workspace",
                details={"file": str(source)},
            )
        if not source.exists():
            return TargetEvidenceItem(
                check_id="lsp",
                status=EvidenceStatus.FAIL,
                summary="LSP probe file does not exist",
                details={"file": str(source)},
            )
        backend = StdioLspBackend(lsp_command, workspace_root=self.workspace, request_timeout_seconds=30)
        try:
            await backend.start()
            uri = await backend.open_document(source, language_id=lsp_language_id)
            provider = LspSemanticProvider(backend, provider_id=Path(lsp_command[0]).name)
            symbols = await provider.document_symbols(uri)
            diagnostics = await provider.diagnostics(uri)
            return TargetEvidenceItem(
                check_id="lsp",
                status=EvidenceStatus.PASS,
                summary=f"Real stdio language server responded with {len(symbols)} symbols and {len(diagnostics)} diagnostics",
                details={
                    "command": [Path(lsp_command[0]).name, *lsp_command[1:]],
                    "file": str(source),
                    "symbol_sample": [item.name for item in symbols[:20]],
                    "diagnostic_count": len(diagnostics),
                    "stderr_tail": backend.stderr_tail[-2000:],
                },
            )
        except Exception as exc:
            return TargetEvidenceItem(
                check_id="lsp",
                status=EvidenceStatus.FAIL,
                summary="Real language-server smoke test failed",
                details={"error": f"{type(exc).__name__}: {exc}", "stderr_tail": backend.stderr_tail[-4000:]},
            )
        finally:
            await backend.close(force=False)

    def _wsl_check(self, distro: str | None) -> TargetEvidenceItem:
        if platform.system() != "Windows":
            return TargetEvidenceItem(
                check_id="wsl2",
                status=EvidenceStatus.SKIP,
                summary="WSL2 target evidence requires Windows",
            )
        executable = shutil.which("wsl.exe") or shutil.which("wsl")
        if executable is None:
            return TargetEvidenceItem(
                check_id="wsl2",
                status=EvidenceStatus.FAIL,
                summary="wsl.exe is not available",
            )
        try:
            listed = subprocess.run(
                [executable, "--list", "--quiet"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            distros = [line.strip().replace("\x00", "") for line in listed.stdout.splitlines() if line.strip()]
            if listed.returncode != 0:
                raise RuntimeError(listed.stderr.strip() or f"wsl --list exited {listed.returncode}")
            if not distros:
                return TargetEvidenceItem(
                    check_id="wsl2",
                    status=EvidenceStatus.FAIL,
                    summary="WSL is installed but no distributions are registered",
                )
            if distro and distro not in distros:
                return TargetEvidenceItem(
                    check_id="wsl2",
                    status=EvidenceStatus.FAIL,
                    summary=f"Requested WSL distro is not registered: {distro}",
                    details={"registered_distros": distros},
                )
            target = distro or distros[0]
            probe = subprocess.run(
                [executable, "--distribution", target, "--", "sh", "-lc", "command -v systemd-run; command -v unshare"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            tools = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
            passed = probe.returncode == 0 and len(tools) >= 2
            return TargetEvidenceItem(
                check_id="wsl2",
                status=EvidenceStatus.PASS if passed else EvidenceStatus.FAIL,
                summary=("WSL2 distro exposes systemd-run and unshare" if passed else "WSL2 isolation prerequisites are incomplete"),
                details={"distro": target, "registered_distros": distros, "probe_output": tools, "stderr": probe.stderr[-2000:]},
            )
        except Exception as exc:
            return TargetEvidenceItem(
                check_id="wsl2",
                status=EvidenceStatus.FAIL,
                summary="WSL2 target probe failed",
                details={"error": f"{type(exc).__name__}: {exc}"},
            )

    def _hyperv_check(self, vm_name: str | None) -> TargetEvidenceItem:
        if platform.system() != "Windows":
            return TargetEvidenceItem(
                check_id="hyperv",
                status=EvidenceStatus.SKIP,
                summary="Hyper-V target evidence requires Windows",
            )
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe") or shutil.which("powershell")
        if powershell is None:
            return TargetEvidenceItem(
                check_id="hyperv",
                status=EvidenceStatus.FAIL,
                summary="PowerShell is unavailable for Hyper-V capability probing",
            )
        script = "Get-Command Get-VM -ErrorAction Stop | Out-Null; 'hyperv-cmdlets-ok'"
        if vm_name:
            safe_vm = vm_name.replace("'", "''")
            script += f"; (Get-VM -Name '{safe_vm}' -ErrorAction Stop).Name"
        try:
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            return TargetEvidenceItem(
                check_id="hyperv",
                status=EvidenceStatus.PASS if result.returncode == 0 else EvidenceStatus.FAIL,
                summary=("Hyper-V PowerShell capability is available" if result.returncode == 0 else "Hyper-V capability probe failed"),
                details={"vm_name": vm_name, "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]},
            )
        except Exception as exc:
            return TargetEvidenceItem(
                check_id="hyperv",
                status=EvidenceStatus.FAIL,
                summary="Hyper-V target probe failed",
                details={"error": f"{type(exc).__name__}: {exc}"},
            )

    def _distributed_lease_check(self) -> TargetEvidenceItem:
        try:
            with tempfile.TemporaryDirectory(prefix="ub-v52-leases-") as directory:
                store = DurableWorkerLeaseStore(Path(directory) / "leases.json")
                workspace_id = uuid4()
                generations: list[int] = []
                for idx in range(4):
                    worker = f"evidence-worker-{idx}"
                    lease = store.acquire(
                        task_id="evidence-task",
                        worker_id=worker,
                        workspace_id=workspace_id,
                        ttl_seconds=10,
                    )
                    generations.append(lease.generation)
                    store.release(task_id="evidence-task", worker_id=worker, generation=lease.generation)
                passed = generations == sorted(generations) and len(set(generations)) == 4
                return TargetEvidenceItem(
                    check_id="distributed_leases",
                    status=EvidenceStatus.PASS if passed else EvidenceStatus.FAIL,
                    summary="Generation-fenced durable lease reacquisition succeeded" if passed else "Lease generations were not monotonic",
                    details={"generations": generations},
                )
        except Exception as exc:
            return TargetEvidenceItem(
                check_id="distributed_leases",
                status=EvidenceStatus.FAIL,
                summary="Distributed lease evidence probe failed",
                details={"error": f"{type(exc).__name__}: {exc}"},
            )

    def _endurance_record_check(self, path: Path | None) -> TargetEvidenceItem:
        if path is None:
            return TargetEvidenceItem(
                check_id="multi_hour_endurance",
                status=EvidenceStatus.SKIP,
                summary="No operator-produced endurance record supplied",
            )
        record_path = path.resolve()
        try:
            raw = json.loads(record_path.read_text(encoding="utf-8"))
            report = EnduranceRunReport.model_validate(raw)
            elapsed = (report.finished_at - report.started_at).total_seconds()
            minimum = 2 * 60 * 60
            passed = report.passed and elapsed >= minimum and report.requested_duration_seconds >= minimum
            digest = hashlib.sha256(record_path.read_bytes()).hexdigest()
            return TargetEvidenceItem(
                check_id="multi_hour_endurance",
                status=EvidenceStatus.PASS if passed else EvidenceStatus.FAIL,
                summary=("Multi-hour endurance record satisfies the V5.2 evidence gate" if passed else "Endurance record does not prove a completed >=2 hour passing run"),
                details={
                    "record": str(record_path),
                    "elapsed_seconds": elapsed,
                    "requested_duration_seconds": report.requested_duration_seconds,
                    "cycles": len(report.cycles),
                    "record_sha256": digest,
                },
                evidence_refs=[str(record_path)],
            )
        except Exception as exc:
            return TargetEvidenceItem(
                check_id="multi_hour_endurance",
                status=EvidenceStatus.FAIL,
                summary="Endurance record could not be validated",
                details={"error": f"{type(exc).__name__}: {exc}", "record": str(record_path)},
            )
