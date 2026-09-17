"""Universal Brain V5.3 real-environment validation and evidence bundling.

Traceability: REQ-ENG-034..REQ-ENG-040, ALN-010, ALN-015, ALN-016,
ALN-020, ALN-021.

This module does not turn target-machine availability into fabricated proof. It
coordinates explicit PASS/FAIL/SKIP checks, persists resumable validation state,
probes configured local Ollama models without storing raw generations, and seals
an evidence bundle that can be verified offline.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, Field

from .checkpointing import WorkspaceFingerprinter
from .evidence import EvidenceStatus, TargetEvidenceItem, V52TargetEvidenceCollector


class ValidationError(RuntimeError):
    pass


class V53ScenarioResult(BaseModel):
    scenario_id: str
    status: EvidenceStatus
    summary: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = Field(default=0, ge=0)
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class V53ValidationCheckpoint(BaseModel):
    schema_version: str = "ub-v53-validation-checkpoint/v1"
    session_id: UUID = Field(default_factory=uuid4)
    checkpoint: str = "V5.3"
    workspace: str
    workspace_fingerprint_sha256: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_scenarios: list[str] = Field(default_factory=list)
    scenario_results: list[V53ScenarioResult] = Field(default_factory=list)
    complete: bool = False
    payload_sha256: str = ""

    def canonical_bytes(self) -> bytes:
        payload = self.model_dump(mode="json")
        payload["payload_sha256"] = ""
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def seal(self) -> "V53ValidationCheckpoint":
        digest = hashlib.sha256(self.canonical_bytes()).hexdigest()
        return self.model_copy(update={"payload_sha256": digest})

    def verify_digest(self) -> bool:
        return bool(self.payload_sha256) and hashlib.sha256(self.canonical_bytes()).hexdigest() == self.payload_sha256


class V53ValidationCheckpointStore:
    """Atomic resumable validation-session state with workspace drift checks."""

    def __init__(self, path: Path, workspace: Path) -> None:
        self.path = path.resolve()
        self.workspace = workspace.resolve()

    def _fingerprint(self) -> str:
        return WorkspaceFingerprinter().fingerprint(self.workspace).digest

    def begin(self) -> V53ValidationCheckpoint:
        checkpoint = V53ValidationCheckpoint(
            workspace=str(self.workspace),
            workspace_fingerprint_sha256=self._fingerprint(),
        ).seal()
        self.save(checkpoint)
        return checkpoint

    def load(self, *, require_no_drift: bool = True) -> V53ValidationCheckpoint:
        if not self.path.exists():
            raise ValidationError(f"validation checkpoint not found: {self.path}")
        checkpoint = V53ValidationCheckpoint.model_validate_json(self.path.read_text(encoding="utf-8"))
        if not checkpoint.verify_digest():
            raise ValidationError("validation checkpoint digest mismatch")
        if Path(checkpoint.workspace).resolve() != self.workspace:
            raise ValidationError("validation checkpoint belongs to a different workspace")
        if require_no_drift and checkpoint.workspace_fingerprint_sha256 != self._fingerprint():
            raise ValidationError("workspace drift detected since validation session started")
        return checkpoint

    def append(self, result: V53ScenarioResult, *, allow_workspace_drift: bool = False) -> V53ValidationCheckpoint:
        current = self.load(require_no_drift=not allow_workspace_drift)
        results = [item for item in current.scenario_results if item.scenario_id != result.scenario_id]
        results.append(result)
        completed = sorted({*current.completed_scenarios, result.scenario_id})
        updated = current.model_copy(
            update={
                "updated_at": datetime.now(timezone.utc),
                "completed_scenarios": completed,
                "scenario_results": results,
            }
        ).seal()
        self.save(updated)
        return updated

    def finish(self, *, allow_workspace_drift: bool = False) -> V53ValidationCheckpoint:
        current = self.load(require_no_drift=not allow_workspace_drift)
        updated = current.model_copy(update={"updated_at": datetime.now(timezone.utc), "complete": True}).seal()
        self.save(updated)
        return updated

    def save(self, checkpoint: V53ValidationCheckpoint) -> Path:
        sealed = checkpoint if checkpoint.verify_digest() else checkpoint.seal()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(sealed.model_dump(mode="json"), handle, sort_keys=True, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)
        return self.path


class V53EvidenceArtifact(BaseModel):
    relative_path: str
    size_bytes: int = Field(ge=0)
    sha256: str


class V53EvidenceManifest(BaseModel):
    schema_version: str = "ub-v53-evidence-manifest/v1"
    checkpoint: str = "V5.3"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_root: str
    artifacts: list[V53EvidenceArtifact] = Field(default_factory=list)
    manifest_sha256: str = ""

    def canonical_bytes(self) -> bytes:
        payload = self.model_dump(mode="json")
        payload["manifest_sha256"] = ""
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def seal(self) -> "V53EvidenceManifest":
        return self.model_copy(update={"manifest_sha256": hashlib.sha256(self.canonical_bytes()).hexdigest()})

    def verify_digest(self) -> bool:
        return bool(self.manifest_sha256) and hashlib.sha256(self.canonical_bytes()).hexdigest() == self.manifest_sha256


class V53EvidenceBundler:
    """Build and verify an offline-checkable evidence manifest."""

    MANIFEST_NAME = "v53-evidence-manifest.json"

    def __init__(self, evidence_root: Path) -> None:
        self.evidence_root = evidence_root.resolve()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def build(self) -> V53EvidenceManifest:
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        artifacts: list[V53EvidenceArtifact] = []
        for path in sorted(self.evidence_root.rglob("*")):
            if not path.is_file() or path.name == self.MANIFEST_NAME:
                continue
            relative = path.relative_to(self.evidence_root).as_posix()
            artifacts.append(
                V53EvidenceArtifact(
                    relative_path=relative,
                    size_bytes=path.stat().st_size,
                    sha256=self._sha256(path),
                )
            )
        return V53EvidenceManifest(evidence_root=str(self.evidence_root), artifacts=artifacts).seal()

    def write(self, manifest: V53EvidenceManifest | None = None) -> Path:
        sealed = manifest or self.build()
        if not sealed.verify_digest():
            sealed = sealed.seal()
        path = self.evidence_root / self.MANIFEST_NAME
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(sealed.model_dump(mode="json"), handle, sort_keys=True, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        return path

    def verify(self, path: Path | None = None) -> tuple[bool, list[str]]:
        manifest_path = (path or self.evidence_root / self.MANIFEST_NAME).resolve()
        manifest = V53EvidenceManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        errors: list[str] = []
        if not manifest.verify_digest():
            errors.append("manifest digest mismatch")
        for artifact in manifest.artifacts:
            candidate = (self.evidence_root / artifact.relative_path).resolve()
            try:
                candidate.relative_to(self.evidence_root)
            except ValueError:
                errors.append(f"artifact escaped evidence root: {artifact.relative_path}")
                continue
            if not candidate.is_file():
                errors.append(f"missing artifact: {artifact.relative_path}")
                continue
            if candidate.stat().st_size != artifact.size_bytes:
                errors.append(f"size mismatch: {artifact.relative_path}")
            if self._sha256(candidate) != artifact.sha256:
                errors.append(f"sha256 mismatch: {artifact.relative_path}")
        return not errors, errors


class OllamaProbeClient(Protocol):
    async def list_models(self) -> list[str]: ...
    async def generate(self, model: str, prompt: str) -> tuple[str, dict[str, Any]]: ...


class HttpOllamaProbeClient:
    """Minimal Ollama probe client. Raw generations are never persisted by V5.3."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434", *, allow_remote: bool = False, timeout_seconds: float = 90) -> None:
        parsed = httpx.URL(base_url)
        host = (parsed.host or "").lower()
        if not allow_remote and host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("remote Ollama probe endpoints require explicit allow_remote=True")
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Ollama endpoint must use http or https")
        self.base_url = str(parsed).rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()
        names = []
        for item in payload.get("models", []) if isinstance(payload, dict) else []:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
        return sorted(set(names))

    async def generate(self, model: str, prompt: str) -> tuple[str, dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            payload = response.json()
        text = str(payload.get("response") or "") if isinstance(payload, dict) else ""
        metadata = {
            key: payload.get(key)
            for key in ("total_duration", "load_duration", "prompt_eval_count", "eval_count", "eval_duration")
            if isinstance(payload, dict) and payload.get(key) is not None
        }
        return text, metadata


class V53OllamaValidator:
    def __init__(self, client: OllamaProbeClient) -> None:
        self.client = client

    async def validate(self, required_models: list[str]) -> V53ScenarioResult:
        start_dt = datetime.now(timezone.utc)
        start = time.monotonic()
        if len(required_models) < 1:
            return V53ScenarioResult(
                scenario_id="ollama_models",
                status=EvidenceStatus.SKIP,
                summary="No operator-selected Ollama models supplied",
                started_at=start_dt,
                finished_at=datetime.now(timezone.utc),
            )
        try:
            available = await self.client.list_models()
            missing = [model for model in required_models if model not in available]
            if missing:
                return V53ScenarioResult(
                    scenario_id="ollama_models",
                    status=EvidenceStatus.FAIL,
                    summary=f"Required Ollama models are unavailable: {', '.join(missing)}",
                    started_at=start_dt,
                    finished_at=datetime.now(timezone.utc),
                    duration_ms=(time.monotonic() - start) * 1000,
                    details={"required_models": required_models, "available_models": available, "missing_models": missing},
                )
            probe_prompt = "Universal Brain V5.3 health probe. Reply briefly with OK."
            samples: list[dict[str, Any]] = []
            failures: list[str] = []
            for model in required_models:
                model_start = time.monotonic()
                text, metadata = await self.client.generate(model, probe_prompt)
                latency_ms = (time.monotonic() - model_start) * 1000
                if not text.strip():
                    failures.append(model)
                samples.append(
                    {
                        "model": model,
                        "latency_ms": round(latency_ms, 3),
                        "response_sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
                        "response_bytes": len(text.encode("utf-8", errors="replace")),
                        "runtime_metadata": metadata,
                    }
                )
            status = EvidenceStatus.FAIL if failures else EvidenceStatus.PASS
            return V53ScenarioResult(
                scenario_id="ollama_models",
                status=status,
                summary=(
                    f"Probed {len(required_models)} configured Ollama model(s)"
                    if not failures
                    else f"Empty/failed generation from: {', '.join(failures)}"
                ),
                started_at=start_dt,
                finished_at=datetime.now(timezone.utc),
                duration_ms=(time.monotonic() - start) * 1000,
                details={
                    "required_models": required_models,
                    "available_models": available,
                    "probe_prompt_sha256": hashlib.sha256(probe_prompt.encode()).hexdigest(),
                    "samples": samples,
                },
            )
        except Exception as exc:
            return V53ScenarioResult(
                scenario_id="ollama_models",
                status=EvidenceStatus.FAIL,
                summary="Ollama target probe failed",
                started_at=start_dt,
                finished_at=datetime.now(timezone.utc),
                duration_ms=(time.monotonic() - start) * 1000,
                details={"error": f"{type(exc).__name__}: {exc}"},
            )


class V53DisposableGitLab:
    """Exercise real Git worktrees and a deliberate merge conflict in a disposable lab.

    The operator repository is not modified. This validates host Git behavior only;
    production merge evidence still comes from real Engineering Agency runs.
    """

    def __init__(self, lab_root: Path) -> None:
        self.lab_root = lab_root.resolve()

    def _run(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=str(cwd), text=True, capture_output=True, shell=False, check=False, timeout=60)

    async def run(self) -> V53ScenarioResult:
        start_dt = datetime.now(timezone.utc)
        start = time.monotonic()
        if shutil.which("git") is None:
            return V53ScenarioResult(
                scenario_id="git_worktree_conflict_lab",
                status=EvidenceStatus.SKIP,
                summary="git executable is unavailable",
                started_at=start_dt,
                finished_at=datetime.now(timezone.utc),
            )
        if self.lab_root.exists():
            shutil.rmtree(self.lab_root)
        repo = self.lab_root / "repo"
        worktrees = self.lab_root / "worktrees"
        repo.mkdir(parents=True, exist_ok=True)
        worktrees.mkdir(parents=True, exist_ok=True)
        commands = [
            (["git", "init", "-b", "main"], repo),
            (["git", "config", "user.email", "ub-v53@example.invalid"], repo),
            (["git", "config", "user.name", "Universal Brain V5.3 Validation"], repo),
        ]
        for args, cwd in commands:
            result = await asyncio.to_thread(self._run, args, cwd)
            if result.returncode != 0:
                return self._failure(start_dt, start, f"command failed: {' '.join(args)}", result)
        (repo / "shared.txt").write_text("base\n", encoding="utf-8")
        for args in (["git", "add", "shared.txt"], ["git", "commit", "-m", "base"]):
            result = await asyncio.to_thread(self._run, args, repo)
            if result.returncode != 0:
                return self._failure(start_dt, start, f"command failed: {' '.join(args)}", result)
        wt_a, wt_b = worktrees / "a", worktrees / "b"
        for branch, path in (("validation/a", wt_a), ("validation/b", wt_b)):
            result = await asyncio.to_thread(self._run, ["git", "worktree", "add", "-b", branch, str(path), "HEAD"], repo)
            if result.returncode != 0:
                return self._failure(start_dt, start, f"worktree creation failed for {branch}", result)
        (wt_a / "shared.txt").write_text("branch-a\n", encoding="utf-8")
        (wt_b / "shared.txt").write_text("branch-b\n", encoding="utf-8")
        for path, message in ((wt_a, "change a"), (wt_b, "change b")):
            for args in (["git", "add", "shared.txt"], ["git", "commit", "-m", message]):
                result = await asyncio.to_thread(self._run, args, path)
                if result.returncode != 0:
                    return self._failure(start_dt, start, f"commit failed in {path.name}", result)
        merge_a = await asyncio.to_thread(self._run, ["git", "merge", "--no-ff", "--no-edit", "validation/a"], repo)
        if merge_a.returncode != 0:
            return self._failure(start_dt, start, "first branch merge unexpectedly failed", merge_a)
        merge_b = await asyncio.to_thread(self._run, ["git", "merge", "--no-ff", "--no-commit", "validation/b"], repo)
        conflicts = await asyncio.to_thread(self._run, ["git", "diff", "--name-only", "--diff-filter=U"], repo)
        conflict_files = [line.strip() for line in conflicts.stdout.splitlines() if line.strip()]
        if merge_b.returncode == 0 or "shared.txt" not in conflict_files:
            return V53ScenarioResult(
                scenario_id="git_worktree_conflict_lab",
                status=EvidenceStatus.FAIL,
                summary="deliberate merge conflict was not detected",
                started_at=start_dt,
                finished_at=datetime.now(timezone.utc),
                duration_ms=(time.monotonic() - start) * 1000,
                details={"merge_exit_code": merge_b.returncode, "conflict_files": conflict_files},
            )
        await asyncio.to_thread(self._run, ["git", "merge", "--abort"], repo)
        head = await asyncio.to_thread(self._run, ["git", "status", "--porcelain"], repo)
        status = EvidenceStatus.PASS if not head.stdout.strip() else EvidenceStatus.FAIL
        if status == EvidenceStatus.PASS:
            shutil.rmtree(self.lab_root, ignore_errors=True)
        return V53ScenarioResult(
            scenario_id="git_worktree_conflict_lab",
            status=status,
            summary="Disposable Git worktrees created; deliberate conflict detected and aborted cleanly",
            started_at=start_dt,
            finished_at=datetime.now(timezone.utc),
            duration_ms=(time.monotonic() - start) * 1000,
            details={"conflict_files": conflict_files, "base_clean_after_abort": not head.stdout.strip()},
        )

    def _failure(self, start_dt: datetime, start: float, summary: str, result: subprocess.CompletedProcess[str]) -> V53ScenarioResult:
        return V53ScenarioResult(
            scenario_id="git_worktree_conflict_lab",
            status=EvidenceStatus.FAIL,
            summary=summary,
            started_at=start_dt,
            finished_at=datetime.now(timezone.utc),
            duration_ms=(time.monotonic() - start) * 1000,
            details={"exit_code": result.returncode, "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]},
        )


ScenarioRunner = Callable[[], Awaitable[V53ScenarioResult]]


class V53ValidationReport(BaseModel):
    schema_version: str = "ub-v53-validation-report/v1"
    checkpoint: str = "V5.3"
    base_checkpoint: str = "V5.2"
    session_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    workspace: str
    platform: str
    platform_release: str
    python_version: str
    results: list[V53ScenarioResult] = Field(default_factory=list)
    overall_status: str = "partial"
    report_sha256: str = ""

    def canonical_bytes(self) -> bytes:
        payload = self.model_dump(mode="json")
        payload["report_sha256"] = ""
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def seal(self) -> "V53ValidationReport":
        return self.model_copy(update={"report_sha256": hashlib.sha256(self.canonical_bytes()).hexdigest()})

    def verify_digest(self) -> bool:
        return bool(self.report_sha256) and hashlib.sha256(self.canonical_bytes()).hexdigest() == self.report_sha256


class V53RealEnvironmentValidator:
    """Compose V5.2 target evidence with V5.3 runtime/endurance scenarios."""

    def __init__(self, workspace: Path, evidence_root: Path) -> None:
        self.workspace = workspace.resolve()
        self.evidence_root = evidence_root.resolve()
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        self.store = V53ValidationCheckpointStore(self.evidence_root / "v53-validation-checkpoint.json", self.workspace)

    async def run(
        self,
        *,
        lsp_command: list[str] | None = None,
        lsp_file: Path | None = None,
        lsp_language_id: str | None = None,
        wsl_distro: str | None = None,
        hyperv_vm: str | None = None,
        endurance_record: Path | None = None,
        ollama_validator: V53OllamaValidator | None = None,
        ollama_models: list[str] | None = None,
        extra_scenarios: list[ScenarioRunner] | None = None,
        include_git_lab: bool = True,
        resume: bool = False,
    ) -> V53ValidationReport:
        checkpoint = self.store.load() if resume and self.store.path.exists() else self.store.begin()
        results: list[V53ScenarioResult] = list(checkpoint.scenario_results)
        completed = {item.scenario_id for item in results}

        base = await V52TargetEvidenceCollector(self.workspace).collect(
            lsp_command=lsp_command,
            lsp_file=lsp_file,
            lsp_language_id=lsp_language_id,
            wsl_distro=wsl_distro,
            hyperv_vm=hyperv_vm,
            endurance_record=endurance_record,
        )
        for item in base.checks:
            scenario_id = f"v52_{item.check_id}"
            if scenario_id in completed:
                continue
            converted = V53ScenarioResult(
                scenario_id=scenario_id,
                status=item.status,
                summary=item.summary,
                details=item.details,
                evidence_refs=item.evidence_refs,
            )
            checkpoint = self.store.append(converted)
            results.append(converted)
            completed.add(scenario_id)

        runners: list[ScenarioRunner] = []
        if ollama_validator is not None:
            runners.append(lambda: ollama_validator.validate(list(ollama_models or [])))
        else:
            async def skipped_ollama() -> V53ScenarioResult:
                return V53ScenarioResult(
                    scenario_id="ollama_models",
                    status=EvidenceStatus.SKIP,
                    summary="Ollama probe not configured",
                )
            runners.append(skipped_ollama)
        if include_git_lab:
            runners.append(V53DisposableGitLab(self.evidence_root / "v53-git-lab").run)
        for runner in extra_scenarios or []:
            runners.append(runner)

        for runner in runners:
            result = await runner()
            if result.scenario_id in completed:
                continue
            checkpoint = self.store.append(result, allow_workspace_drift=result.scenario_id == "git_worktree_conflict_lab")
            results.append(result)
            completed.add(result.scenario_id)

        checkpoint = self.store.finish(allow_workspace_drift=True)
        failures = [item for item in results if item.status == EvidenceStatus.FAIL]
        skips = [item for item in results if item.status == EvidenceStatus.SKIP]
        overall = "failed" if failures else "partial" if skips else "passed"
        report = V53ValidationReport(
            session_id=checkpoint.session_id,
            workspace=str(self.workspace),
            platform=platform.system(),
            platform_release=platform.release(),
            python_version=platform.python_version(),
            results=results,
            overall_status=overall,
        ).seal()
        report_path = self.evidence_root / "v53-validation-report.json"
        temp = report_path.with_name(f".{report_path.name}.{os.getpid()}.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(report.model_dump(mode="json"), handle, sort_keys=True, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, report_path)
        V53EvidenceBundler(self.evidence_root).write()
        return report

class V53AuthorityServiceScenario:
    """Exercise a real long-running process through ToolGateway authority.

    The child is a bounded Python sleeper that writes a readiness line. It runs
    only inside the evidence directory and is always stopped in ``finally``.
    """

    def __init__(self, workspace: Path, evidence_root: Path) -> None:
        self.workspace = workspace.resolve()
        self.evidence_root = evidence_root.resolve()

    async def run(self) -> V53ScenarioResult:
        import sys
        from uuid import uuid4
        from universal_brain.alignment.contract import (
            AcceptanceCriterion,
            AlignmentContract,
            OriginalInput,
            PermissionsCeiling,
            Requirement,
            RequirementKind,
            RequirementPriority,
        )
        from universal_brain.kernel.capability import CapabilityService
        from universal_brain.kernel.event_store import EventStore
        from universal_brain.kernel.events import ActionClass
        from universal_brain.tools.gateway import ToolGateway
        from universal_brain.tools.runner.service_tool import ManagedServiceProcessTool

        start_dt = datetime.now(timezone.utc)
        start = time.monotonic()
        service_root = self.evidence_root / "service-lab"
        service_root.mkdir(parents=True, exist_ok=True)
        event_store = EventStore()
        cap_service = CapabilityService()
        gateway = ToolGateway(event_store=event_store, capability_service=cap_service)
        tool = ManagedServiceProcessTool(self.workspace, log_root=service_root / "logs")
        gateway.register_tool(tool)

        original = OriginalInput(exact_content_ref="V5.3 operator-authorized service validation")
        requirement = Requirement(
            requirement_id="REQ-ENG-036",
            statement="Exercise authority-gated persistent service lifecycle on the target machine",
            source_input_ids=[original.input_id],
            kind=RequirementKind.EVIDENCE,
            priority=RequirementPriority.MUST,
            verification_method="ToolGateway service lifecycle evidence",
        )
        criterion = AcceptanceCriterion(
            criterion_id="AC-V53-SERVICE",
            statement="Service starts, emits readiness, reports running, and stops through ToolGateway",
            evidence_type="tool_gateway_events",
            verifier="deterministic",
        )
        contract = AlignmentContract.create_draft(
            objective="Universal Brain V5.3 service validation",
            requirements=[requirement],
            permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
            acceptance_criteria=[criterion],
            original_inputs=[original],
        ).activate()
        project_id = uuid4()
        service_id = str(uuid4())

        def token():
            return cap_service.issue_token(
                project_id=project_id,
                task_id=uuid4(),
                contract_id=contract.contract_id,
                contract_version=contract.version,
                action_class=ActionClass.A1,
                target_resource=str(self.workspace),
                allowed_operations=["manage_service"],
            )

        started = False
        try:
            start_result = gateway.execute_tool(
                tool_name="manage_service",
                args={
                    "operation": "start",
                    "service_id": service_id,
                    "executable": sys.executable,
                    "arguments": [
                        "-u",
                        "-c",
                        "import time; print('UB_V53_SERVICE_READY', flush=True); time.sleep(60)",
                    ],
                    "cwd": str(self.workspace),
                },
                capability_token=token(),
                contract=contract,
                actor_id="v53_target_validator",
                target_resource=str(self.workspace),
            )
            if not start_result.success:
                raise RuntimeError(start_result.error_message or "service start failed")
            started = True
            status_result = None
            logs_result = None
            for _ in range(20):
                await asyncio.sleep(0.1)
                status_result = gateway.execute_tool(
                    tool_name="manage_service",
                    args={"operation": "status", "service_id": service_id},
                    capability_token=token(),
                    contract=contract,
                    actor_id="v53_target_validator",
                    target_resource=str(self.workspace),
                )
                logs_result = gateway.execute_tool(
                    tool_name="manage_service",
                    args={"operation": "logs", "service_id": service_id, "max_lines": 50},
                    capability_token=token(),
                    contract=contract,
                    actor_id="v53_target_validator",
                    target_resource=str(self.workspace),
                )
                if logs_result.success and "UB_V53_SERVICE_READY" in str(logs_result.output):
                    break
            assert status_result is not None and logs_result is not None
            passed = (
                status_result.success
                and isinstance(status_result.output, dict)
                and status_result.output.get("state") == "running"
                and logs_result.success
                and "UB_V53_SERVICE_READY" in str(logs_result.output)
                and event_store.verify_chain_integrity()
            )
            return V53ScenarioResult(
                scenario_id="authority_service_workload",
                status=EvidenceStatus.PASS if passed else EvidenceStatus.FAIL,
                summary=(
                    "Authority-gated service started, emitted readiness, and produced a valid causal event chain"
                    if passed
                    else "Authority-gated service lifecycle did not satisfy the target gate"
                ),
                started_at=start_dt,
                finished_at=datetime.now(timezone.utc),
                duration_ms=(time.monotonic() - start) * 1000,
                details={
                    "event_count_before_stop": event_store.event_count,
                    "event_chain_valid": event_store.verify_chain_integrity(),
                    "status": status_result.output if status_result.success else status_result.error_message,
                    "log_sha256": hashlib.sha256(str(logs_result.output).encode()).hexdigest(),
                },
                evidence_refs=[
                    str(start_result.evidence.get("tool_call_event_id", "")),
                    str(start_result.evidence.get("evidence_event_id", "")),
                ],
            )
        except Exception as exc:
            return V53ScenarioResult(
                scenario_id="authority_service_workload",
                status=EvidenceStatus.FAIL,
                summary="Authority-gated service target scenario failed",
                started_at=start_dt,
                finished_at=datetime.now(timezone.utc),
                duration_ms=(time.monotonic() - start) * 1000,
                details={"error": f"{type(exc).__name__}: {exc}"},
            )
        finally:
            if started:
                try:
                    gateway.execute_tool(
                        tool_name="manage_service",
                        args={"operation": "stop", "service_id": service_id},
                        capability_token=token(),
                        contract=contract,
                        actor_id="v53_target_validator",
                        target_resource=str(self.workspace),
                    )
                except Exception:
                    pass


class V53OllamaPressureScenario:
    """Optional bounded three-model concurrency probe."""

    def __init__(self, client: OllamaProbeClient, models: list[str]) -> None:
        self.client = client
        self.models = list(models)

    async def run(self) -> V53ScenarioResult:
        start_dt = datetime.now(timezone.utc)
        start = time.monotonic()
        if len(self.models) < 2:
            return V53ScenarioResult(
                scenario_id="ollama_parallel_pressure",
                status=EvidenceStatus.SKIP,
                summary="Parallel Ollama pressure requires at least two operator-selected models",
                started_at=start_dt,
                finished_at=datetime.now(timezone.utc),
            )
        prompt = "Universal Brain V5.3 bounded concurrency probe. Reply with OK."

        async def one(model: str) -> dict[str, Any]:
            model_start = time.monotonic()
            try:
                text, meta = await self.client.generate(model, prompt)
                return {
                    "model": model,
                    "ok": bool(text.strip()),
                    "latency_ms": round((time.monotonic() - model_start) * 1000, 3),
                    "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "response_bytes": len(text.encode()),
                    "runtime_metadata": meta,
                }
            except Exception as exc:
                return {
                    "model": model,
                    "ok": False,
                    "latency_ms": round((time.monotonic() - model_start) * 1000, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                }

        samples = await asyncio.gather(*(one(model) for model in self.models))
        passed = all(item.get("ok") for item in samples)
        return V53ScenarioResult(
            scenario_id="ollama_parallel_pressure",
            status=EvidenceStatus.PASS if passed else EvidenceStatus.FAIL,
            summary=(
                f"{len(samples)} Ollama models completed one bounded concurrent probe"
                if passed
                else "One or more Ollama models failed under bounded concurrent pressure"
            ),
            started_at=start_dt,
            finished_at=datetime.now(timezone.utc),
            duration_ms=(time.monotonic() - start) * 1000,
            details={
                "models": self.models,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "samples": samples,
            },
        )


class V53RestartRecoveryLab:
    """Prove checkpoint survival across two independent Python processes."""

    def __init__(self, workspace: Path, evidence_root: Path) -> None:
        self.workspace = workspace.resolve()
        self.evidence_root = evidence_root.resolve()

    async def run(self) -> V53ScenarioResult:
        start_dt = datetime.now(timezone.utc)
        start = time.monotonic()
        python = shutil.which("python") or shutil.which("python.exe") or os.sys.executable
        helper = self.evidence_root / "v53-restart-helper.py"
        state = self.evidence_root / "v53-restart-probe.json"
        src_root = Path(__file__).resolve().parents[2]
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper_code = "\n".join([
            "from pathlib import Path",
            "import sys",
            f"sys.path.insert(0, {str(src_root)!r})",
            "from universal_brain.engineering.validation import V53ValidationCheckpointStore",
            "workspace=Path(sys.argv[2]).resolve(); state=Path(sys.argv[3]).resolve()",
            "store=V53ValidationCheckpointStore(state, workspace)",
            "if sys.argv[1]=='write':",
            "    cp=store.begin(); print(cp.session_id); raise SystemExit(23)",
            "cp=store.load(); print(cp.session_id); raise SystemExit(0)",
            "",
        ])
        helper.write_text(helper_code, encoding="utf-8")
        try:
            first = await asyncio.to_thread(
                subprocess.run,
                [python, str(helper), "write", str(self.workspace), str(state)],
                capture_output=True,
                text=True,
                shell=False,
                timeout=30,
                check=False,
            )
            second = await asyncio.to_thread(
                subprocess.run,
                [python, str(helper), "read", str(self.workspace), str(state)],
                capture_output=True,
                text=True,
                shell=False,
                timeout=30,
                check=False,
            )
            id1 = first.stdout.strip().splitlines()[-1] if first.stdout.strip() else ""
            id2 = second.stdout.strip().splitlines()[-1] if second.stdout.strip() else ""
            passed = first.returncode == 23 and second.returncode == 0 and bool(id1) and id1 == id2
            return V53ScenarioResult(
                scenario_id="process_restart_recovery",
                status=EvidenceStatus.PASS if passed else EvidenceStatus.FAIL,
                summary=(
                    "A checkpoint created by one Python process was verified and recovered by a second process"
                    if passed
                    else "Cross-process checkpoint recovery probe failed"
                ),
                started_at=start_dt,
                finished_at=datetime.now(timezone.utc),
                duration_ms=(time.monotonic() - start) * 1000,
                details={
                    "writer_exit_code": first.returncode,
                    "reader_exit_code": second.returncode,
                    "session_match": id1 == id2 and bool(id1),
                    "writer_stderr": first.stderr[-1000:],
                    "reader_stderr": second.stderr[-1000:],
                },
                evidence_refs=[str(state)],
            )
        except Exception as exc:
            return V53ScenarioResult(
                scenario_id="process_restart_recovery",
                status=EvidenceStatus.FAIL,
                summary="Cross-process restart recovery probe raised an exception",
                started_at=start_dt,
                finished_at=datetime.now(timezone.utc),
                duration_ms=(time.monotonic() - start) * 1000,
                details={"error": f"{type(exc).__name__}: {exc}"},
            )
        finally:
            helper.unlink(missing_ok=True)


class V53WSLIsolationExecutionScenario:
    """Optional real WSL2 command through ToolGateway's opaque plan boundary."""

    def __init__(self, workspace: Path, distro: str, linux_workspace: str) -> None:
        self.workspace = workspace.resolve()
        self.distro = distro
        self.linux_workspace = linux_workspace

    async def run(self) -> V53ScenarioResult:
        if platform.system() != "Windows":
            return V53ScenarioResult(
                scenario_id="wsl2_toolgateway_execution",
                status=EvidenceStatus.SKIP,
                summary="Real WSL2 ToolGateway execution requires Windows",
            )
        from uuid import uuid4
        from universal_brain.alignment.contract import (
            AcceptanceCriterion, AlignmentContract, OriginalInput, PermissionsCeiling,
            Requirement, RequirementKind, RequirementPriority,
        )
        from universal_brain.kernel.capability import CapabilityService
        from universal_brain.kernel.event_store import EventStore
        from universal_brain.kernel.events import ActionClass
        from universal_brain.tools.gateway import ToolGateway
        from .isolation import IsolationCapabilities, IsolationQuota, NetworkMode, WSL2IsolationProvider
        from .isolation_tool import IsolationPlanExecutionTool

        start_dt = datetime.now(timezone.utc)
        start = time.monotonic()
        original = OriginalInput(exact_content_ref="V5.3 operator-authorized WSL2 isolation validation")
        req = Requirement(
            requirement_id="REQ-ENG-036",
            statement="Execute one bounded WSL2 isolation plan through ToolGateway",
            source_input_ids=[original.input_id],
            kind=RequirementKind.EVIDENCE,
            priority=RequirementPriority.MUST,
            verification_method="ToolGateway isolation evidence",
        )
        contract = AlignmentContract.create_draft(
            objective="V5.3 WSL2 isolation execution evidence",
            requirements=[req],
            permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
            acceptance_criteria=[AcceptanceCriterion(
                criterion_id="AC-V53-WSL",
                statement="Bounded WSL2 command returns the expected marker through one-time plan execution",
                evidence_type="tool_gateway_events",
                verifier="deterministic",
            )],
            original_inputs=[original],
        ).activate()
        caps = IsolationCapabilities(
            memory_limit=True, cpu_limit=True, pid_limit=True,
            deny_network=True, wall_timeout=True,
        )
        provider = WSL2IsolationProvider(distro=self.distro, capabilities=caps)
        quota = IsolationQuota(memory_mb=512, cpu_percent=100, pids_max=32, wall_seconds=30, network_mode=NetworkMode.DENY)
        try:
            plan = provider.build_plan(
                workspace_root=self.workspace,
                linux_workspace=self.linux_workspace,
                executable="/usr/bin/python3",
                arguments=["-c", "print('UB_V53_WSL_OK')"],
                quota=quota,
                host_cwd=self.workspace,
            )
            store = EventStore(); cap_service = CapabilityService(); gateway = ToolGateway(store, cap_service)
            tool = IsolationPlanExecutionTool(self.workspace, allowed_wsl_distros={self.distro})
            gateway.register_tool(tool)
            plan_id = tool.register_plan(plan)
            token = cap_service.issue_token(
                project_id=uuid4(), task_id=uuid4(), contract_id=contract.contract_id,
                contract_version=contract.version, action_class=ActionClass.A1,
                target_resource=str(self.workspace), allowed_operations=["run_isolated_command"],
            )
            result = gateway.execute_tool(
                tool_name="run_isolated_command",
                args={"plan_id": plan_id},
                capability_token=token,
                contract=contract,
                actor_id="v53_target_validator",
                target_resource=str(self.workspace),
            )
            passed = result.success and "UB_V53_WSL_OK" in str(result.output) and store.verify_chain_integrity()
            return V53ScenarioResult(
                scenario_id="wsl2_toolgateway_execution",
                status=EvidenceStatus.PASS if passed else EvidenceStatus.FAIL,
                summary=(
                    "Real WSL2 command executed through one-time ToolGateway isolation plan"
                    if passed else "WSL2 ToolGateway isolation execution failed"
                ),
                started_at=start_dt, finished_at=datetime.now(timezone.utc),
                duration_ms=(time.monotonic()-start)*1000,
                details={
                    "distro": self.distro,
                    "linux_workspace": self.linux_workspace,
                    "event_chain_valid": store.verify_chain_integrity(),
                    "tool_evidence": result.evidence,
                    "error": result.error_message,
                },
                evidence_refs=[str(result.evidence.get("tool_call_event_id", "")), str(result.evidence.get("evidence_event_id", ""))],
            )
        except Exception as exc:
            return V53ScenarioResult(
                scenario_id="wsl2_toolgateway_execution",
                status=EvidenceStatus.FAIL,
                summary="WSL2 ToolGateway isolation scenario raised an exception",
                started_at=start_dt, finished_at=datetime.now(timezone.utc),
                duration_ms=(time.monotonic()-start)*1000,
                details={"error": f"{type(exc).__name__}: {exc}", "distro": self.distro},
            )
