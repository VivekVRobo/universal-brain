from __future__ import annotations

from pathlib import Path

import pytest

from universal_brain.engineering import (
    EvidenceStatus,
    ValidationError,
    V53DisposableGitLab,
    V53EvidenceBundler,
    V53OllamaValidator,
    V53RealEnvironmentValidator,
    V53ScenarioResult,
    V53ValidationCheckpointStore,
)


class FakeOllamaClient:
    def __init__(self, models: list[str], outputs: dict[str, str] | None = None):
        self.models = models
        self.outputs = outputs or {model: "OK" for model in models}

    async def list_models(self) -> list[str]:
        return list(self.models)

    async def generate(self, model: str, prompt: str):
        return self.outputs.get(model, ""), {"eval_count": 1}


def test_v53_checkpoint_is_atomic_self_verifying_and_detects_workspace_drift(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("a", encoding="utf-8")
    store = V53ValidationCheckpointStore(tmp_path / "state" / "v53.json", workspace)
    started = store.begin()
    assert started.verify_digest()
    result = V53ScenarioResult(
        scenario_id="probe",
        status=EvidenceStatus.PASS,
        summary="ok",
    )
    updated = store.append(result)
    assert updated.verify_digest()
    assert updated.completed_scenarios == ["probe"]

    (workspace / "a.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValidationError, match="workspace drift"):
        store.load()


def test_v53_evidence_manifest_detects_artifact_tampering(tmp_path: Path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    artifact = evidence / "probe.json"
    artifact.write_text('{"ok": true}', encoding="utf-8")
    bundler = V53EvidenceBundler(evidence)
    path = bundler.write()
    ok, errors = bundler.verify(path)
    assert ok and not errors

    artifact.write_text('{"ok": false}', encoding="utf-8")
    ok, errors = bundler.verify(path)
    assert not ok
    assert any("sha256 mismatch" in error for error in errors)


@pytest.mark.asyncio
async def test_v53_ollama_validator_requires_and_hashes_all_operator_selected_models():
    validator = V53OllamaValidator(FakeOllamaClient(["qwen:a", "qwen:b", "qwen:c"]))
    result = await validator.validate(["qwen:a", "qwen:b", "qwen:c"])
    assert result.status == EvidenceStatus.PASS
    assert len(result.details["samples"]) == 3
    assert all("response_sha256" in item for item in result.details["samples"])
    assert all("response" not in item for item in result.details["samples"])

    missing = await validator.validate(["qwen:a", "missing:model"])
    assert missing.status == EvidenceStatus.FAIL
    assert missing.details["missing_models"] == ["missing:model"]


@pytest.mark.asyncio
async def test_v53_disposable_git_lab_exercises_worktrees_conflict_and_clean_abort(tmp_path: Path):
    result = await V53DisposableGitLab(tmp_path / "git-lab").run()
    if result.status == EvidenceStatus.SKIP:
        pytest.skip(result.summary)
    assert result.status == EvidenceStatus.PASS
    assert "shared.txt" in result.details["conflict_files"]
    assert result.details["base_clean_after_abort"] is True


@pytest.mark.asyncio
async def test_v53_real_environment_validator_preserves_skip_semantics_and_seals_manifest(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sample.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    evidence = workspace / ".brain" / "evidence" / "v53"
    validator = V53RealEnvironmentValidator(workspace, evidence)
    report = await validator.run(
        ollama_validator=V53OllamaValidator(FakeOllamaClient(["m1", "m2", "m3"])),
        ollama_models=["m1", "m2", "m3"],
        include_git_lab=False,
    )
    assert report.verify_digest()
    by_id = {item.scenario_id: item for item in report.results}
    assert by_id["ollama_models"].status == EvidenceStatus.PASS
    if report.platform != "Windows":
        assert by_id["v52_wsl2"].status == EvidenceStatus.SKIP
        assert by_id["v52_hyperv"].status == EvidenceStatus.SKIP
        assert report.overall_status == "partial"
    ok, errors = V53EvidenceBundler(evidence).verify()
    assert ok, errors

@pytest.mark.asyncio
async def test_v53_authority_gated_service_workload_runs_and_stops(tmp_path: Path):
    from universal_brain.engineering import V53AuthorityServiceScenario

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = await V53AuthorityServiceScenario(workspace, workspace / ".brain" / "evidence" / "v53").run()
    assert result.status == EvidenceStatus.PASS, result.details
    assert result.details["event_chain_valid"] is True


@pytest.mark.asyncio
async def test_v53_parallel_ollama_pressure_is_bounded_and_hash_only():
    from universal_brain.engineering import V53OllamaPressureScenario

    client = FakeOllamaClient(["m1", "m2", "m3"])
    result = await V53OllamaPressureScenario(client, ["m1", "m2", "m3"]).run()
    assert result.status == EvidenceStatus.PASS
    assert len(result.details["samples"]) == 3
    assert all("response_sha256" in item for item in result.details["samples"])


@pytest.mark.asyncio
async def test_v53_restart_probe_crosses_real_process_boundary(tmp_path: Path):
    from universal_brain.engineering import V53RestartRecoveryLab

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = await V53RestartRecoveryLab(workspace, workspace / ".brain" / "evidence" / "v53").run()
    assert result.status == EvidenceStatus.PASS, result.details
    assert result.details["writer_exit_code"] == 23
    assert result.details["reader_exit_code"] == 0
    assert result.details["session_match"] is True


@pytest.mark.asyncio
async def test_v53_wsl_execution_is_explicit_skip_off_windows(tmp_path: Path):
    import platform
    from universal_brain.engineering import V53WSLIsolationExecutionScenario

    if platform.system() == "Windows":
        pytest.skip("non-Windows skip semantics test")
    result = await V53WSLIsolationExecutionScenario(tmp_path, "Ubuntu", "/workspace").run()
    assert result.status == EvidenceStatus.SKIP
