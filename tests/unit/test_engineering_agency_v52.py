from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from universal_brain.engineering import (
    DependencyEcosystem,
    DependencyRemediationCoordinator,
    DependencyRepairPlan,
    DurableLeaseError,
    DurableWorkerLeaseStore,
    EnduranceCycleResult,
    EngineeringEnduranceHarness,
    EngineeringWorkspace,
    IsolationCapabilities,
    IsolationError,
    IsolationQuota,
    LspRenamePlanner,
    LspSemanticProvider,
    MergeVerificationDecision,
    MultiRepositoryGraphBuilder,
    NetworkMode,
    SerializedMergeCoordinator,
    SourcePosition,
    WSL2IsolationProvider,
)
from universal_brain.engineering.schemas import EngineeringToolObservation
from universal_brain.executive.schemas import TaskNode
from universal_brain.tools.runner.service_tool import ManagedServiceProcessTool


class FakeLspBackend:
    async def request(self, method, params):
        if method == "textDocument/documentSymbol":
            return [
                {
                    "name": "TrajectoryPlanner",
                    "kind": 5,
                    "range": {"start": {"line": 0, "character": 0}, "end": {"line": 4, "character": 1}},
                    "selectionRange": {"start": {"line": 0, "character": 6}, "end": {"line": 0, "character": 23}},
                }
            ]
        if method == "textDocument/diagnostic":
            return {
                "items": [
                    {
                        "range": {"start": {"line": 2, "character": 4}, "end": {"line": 2, "character": 8}},
                        "message": "undefined name",
                        "severity": 1,
                        "source": "fake-lsp",
                    }
                ]
            }
        if method == "textDocument/rename":
            return {
                "changes": {
                    params["textDocument"]["uri"]: [
                        {
                            "range": {"start": {"line": 0, "character": 6}, "end": {"line": 0, "character": 23}},
                            "newText": params["newName"],
                        }
                    ]
                }
            }
        return []


@pytest.mark.asyncio
async def test_lsp_semantic_provider_and_symbol_safe_rename_are_workspace_confined(tmp_path: Path):
    source = tmp_path / "planner.py"
    source.write_text("class TrajectoryPlanner:\n    pass\n", encoding="utf-8")
    uri = source.resolve().as_uri()
    backend = FakeLspBackend()
    provider = LspSemanticProvider(backend, provider_id="pyright")
    symbols = await provider.document_symbols(uri)
    diagnostics = await provider.diagnostics(uri)
    assert symbols[0].name == "TrajectoryPlanner"
    assert diagnostics[0].message == "undefined name"

    planner = LspRenamePlanner(backend, [tmp_path])
    plan = await planner.plan(
        uri=uri,
        position=SourcePosition(line=0, character=8),
        symbol_name="TrajectoryPlanner",
        new_name="SafePlanner",
    )
    assert plan.edits[0].new_text == "SafePlanner"

    other = (tmp_path.parent / "outside.py").resolve().as_uri()

    class EscapingBackend(FakeLspBackend):
        async def request(self, method, params):
            if method == "textDocument/rename":
                return {
                    "changes": {
                        other: [
                            {
                                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
                                "newText": "x",
                            }
                        ]
                    }
                }
            return await super().request(method, params)

    with pytest.raises(ValueError, match="escapes authorized workspace"):
        await LspRenamePlanner(EscapingBackend(), [tmp_path]).plan(
            uri=uri,
            position=SourcePosition(line=0, character=8),
            symbol_name="TrajectoryPlanner",
            new_name="X",
        )


def test_wsl2_isolation_plan_enforces_resource_and_network_controls(tmp_path: Path):
    provider = WSL2IsolationProvider(
        distro="Ubuntu-24.04",
        capabilities=IsolationCapabilities(
            memory_limit=True,
            cpu_limit=True,
            pid_limit=True,
            deny_network=True,
            wall_timeout=True,
        ),
    )
    quota = IsolationQuota(memory_mb=2048, cpu_percent=150, pids_max=96, network_mode=NetworkMode.DENY)
    plan = provider.build_plan(
        workspace_root=tmp_path,
        linux_workspace="/mnt/c/project",
        executable="pytest",
        arguments=["-q"],
        quota=quota,
        host_cwd=tmp_path,
    )
    joined = " ".join(plan.host_arguments)
    assert "MemoryMax=2048M" in joined
    assert "CPUQuota=150%" in joined
    assert "TasksMax=96" in joined
    assert "--net" in joined
    assert set(plan.enforced_controls) >= {"memory", "cpu", "pids", "network-deny", "wall-timeout"}

    unsupported = WSL2IsolationProvider(
        distro="Ubuntu",
        capabilities=IsolationCapabilities(memory_limit=True, cpu_limit=True, pid_limit=True, deny_network=False),
    )
    with pytest.raises(IsolationError, match="network deny"):
        unsupported.build_plan(
            workspace_root=tmp_path,
            linux_workspace="/workspace",
            executable="pytest",
            arguments=[],
            quota=quota,
            host_cwd=tmp_path,
        )


def test_durable_worker_lease_fencing_survives_reacquisition(tmp_path: Path):
    store = DurableWorkerLeaseStore(tmp_path / "leases.json")
    workspace_id = uuid4()
    first = store.acquire(task_id="task-1", worker_id="worker-a", workspace_id=workspace_id, ttl_seconds=30)
    assert store.validate_fence(task_id="task-1", worker_id="worker-a", generation=first.generation)
    with pytest.raises(DurableLeaseError):
        store.acquire(task_id="task-1", worker_id="worker-b", workspace_id=workspace_id, ttl_seconds=30)
    store.release(task_id="task-1", worker_id="worker-a", generation=first.generation)
    second = store.acquire(task_id="task-1", worker_id="worker-b", workspace_id=workspace_id, ttl_seconds=30)
    assert second.generation == first.generation + 1
    assert not store.validate_fence(task_id="task-1", worker_id="worker-a", generation=first.generation)
    assert store.validate_fence(task_id="task-1", worker_id="worker-b", generation=second.generation)


def test_multi_repository_graph_detects_local_manifest_dependencies(tmp_path: Path):
    core = tmp_path / "core"
    app = tmp_path / "app"
    core.mkdir(); app.mkdir()
    (core / "package.json").write_text(json.dumps({"name": "@brain/core"}), encoding="utf-8")
    (app / "package.json").write_text(
        json.dumps({"name": "@brain/app", "dependencies": {"@brain/core": "file:../core"}}),
        encoding="utf-8",
    )
    graph = MultiRepositoryGraphBuilder().build([core, app])
    core_id = next(key for key, repo in graph.repositories.items() if "@brain/core" in repo.package_names)
    app_id = next(key for key, repo in graph.repositories.items() if "@brain/app" in repo.package_names)
    assert graph.dependencies_of(app_id) == [core_id]
    assert graph.downstream(core_id) == [app_id]


class FakeMergeGit:
    def __init__(self, conflicts=None, merge_success=True):
        self.conflicts = list(conflicts or [])
        self.merge_success = merge_success
        self.aborted = False
        self.committed = False
        self.refs = {"HEAD": "base123", "brain/req-1": "src456"}

    async def status_porcelain(self, cwd=None): return ""
    async def rev_parse(self, ref="HEAD", cwd=None): return self.refs[ref]
    async def merge_no_commit(self, branch):
        return EngineeringToolObservation(tool_name="git", success=self.merge_success, output="merge")
    async def conflicted_files(self): return self.conflicts
    async def abort_merge(self): self.aborted = True
    async def commit_merge(self, message=None):
        self.committed = True
        return "merged789"


class FakeIntegrationVerifier:
    def __init__(self, accepted=True): self.accepted = accepted
    async def verify_integration(self, *, branch, source_commit, node):
        return MergeVerificationDecision(
            accepted=self.accepted,
            evidence_refs=["verify://merged-tree"] if self.accepted else [],
            reason="pass" if self.accepted else "tests failed",
        )


@pytest.mark.asyncio
async def test_merge_coordinator_verifies_actual_merged_tree_and_aborts_conflicts():
    node = TaskNode(node_id="verify", dag_id=uuid4(), goal="verify", requirement_refs=["REQ-1"])
    git = FakeMergeGit()
    result = await SerializedMergeCoordinator(git, FakeIntegrationVerifier(True)).integrate_verified_branch(
        branch="brain/req-1",
        verified_source_commit="src456",
        node=node,
    )
    assert result.accepted
    assert result.integrated_commit == "merged789"
    assert git.committed

    conflict_git = FakeMergeGit(conflicts=["src/a.py"])
    rejected = await SerializedMergeCoordinator(conflict_git, FakeIntegrationVerifier(True)).integrate_verified_branch(
        branch="brain/req-1",
        verified_source_commit="src456",
        node=node,
    )
    assert not rejected.accepted
    assert rejected.conflict_files == ["src/a.py"]
    assert conflict_git.aborted


class FakeRemediationGit:
    def __init__(self): self.reset_to = None
    async def status_porcelain(self, cwd=None): return ""
    async def rev_parse(self, ref="HEAD", cwd=None): return "baseline"
    async def reset_hard(self, ref, *, cwd): self.reset_to = ref


class FakeDependencyExecutor:
    def __init__(self, success=True): self.success = success; self.commands = []
    async def run_dependency_command(self, command, *, cwd, operation):
        self.commands.append(command)
        return EngineeringToolObservation(
            tool_name="run_command",
            success=self.success,
            evidence={"command_id": "dep-1"},
            error=None if self.success else "install failed",
        )


class FakeDependencyVerifier:
    def __init__(self, accepted): self.accepted = accepted
    async def verify_dependency_state(self, *, cwd):
        return self.accepted, (["verify://deps"] if self.accepted else []), ("ok" if self.accepted else "tests fail")


@pytest.mark.asyncio
async def test_dependency_remediation_rolls_back_when_post_verification_fails(tmp_path: Path):
    git = FakeRemediationGit()
    coordinator = DependencyRemediationCoordinator(
        git=git,
        executor=FakeDependencyExecutor(True),
        verifier=FakeDependencyVerifier(False),
    )
    plan = DependencyRepairPlan(
        ecosystem=DependencyEcosystem.PYTHON,
        package_manager="pip",
        diagnostic="missing module",
        suggested_commands=[["python", "-m", "pip", "install", "-e", "."]],
        requires_manifest_review=True,
    )
    result = await coordinator.remediate(plan, worktree=tmp_path, manifest_review_approved=True)
    assert not result.accepted
    assert result.rolled_back
    assert git.reset_to == "baseline"


class EnduranceProbe:
    async def run_cycle(self, cycle):
        await asyncio.sleep(0)
        return EnduranceCycleResult(cycle=cycle, passed=True, duration_ms=1.0, evidence_refs=[f"cycle://{cycle}"])


@pytest.mark.asyncio
async def test_endurance_harness_persists_progress_and_completes_bounded_run(tmp_path: Path):
    path = tmp_path / "endurance.json"
    report = await EngineeringEnduranceHarness(EnduranceProbe(), progress_path=path).run(
        duration_seconds=10,
        max_cycles=3,
    )
    assert report.passed
    assert len(report.cycles) == 3
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["cycles"]) == 3


def test_managed_service_tool_owns_process_identity_and_can_stop_it(tmp_path: Path):
    tool = ManagedServiceProcessTool(tmp_path)
    start = tool.execute(
        {
            "operation": "start",
            "service_id": "svc-test",
            "executable": "python",
            "arguments": ["-c", "import time; print('ready', flush=True); time.sleep(30)"],
            "cwd": str(tmp_path),
        }
    )
    assert start.success
    try:
        status = tool.execute({"operation": "status", "service_id": "svc-test"})
        assert status.success and status.output["state"] == "running"
    finally:
        stopped = tool.execute({"operation": "stop", "service_id": "svc-test"})
        assert stopped.success


def test_incremental_diagnostics_reject_stale_versions_and_invalidate_on_digest():
    from universal_brain.engineering import (
        DiagnosticSeverity,
        IncrementalDiagnosticRegistry,
        SemanticDiagnostic,
        SourceRange,
    )

    registry = IncrementalDiagnosticRegistry()
    diagnostic = SemanticDiagnostic(
        uri="file:///tmp/a.py",
        range=SourceRange(
            start=SourcePosition(line=0, character=0),
            end=SourcePosition(line=0, character=1),
        ),
        message="boom",
        severity=DiagnosticSeverity.ERROR,
    )
    registry.update(
        uri=diagnostic.uri,
        diagnostics=[diagnostic],
        document_version=3,
        content_digest="aaa",
    )
    assert registry.error_count() == 1
    with pytest.raises(ValueError, match="stale"):
        registry.update(uri=diagnostic.uri, diagnostics=[], document_version=2, content_digest="aaa")
    assert registry.invalidate_if_digest_changed(uri=diagnostic.uri, current_digest="bbb")
    assert registry.error_count() == 0


def test_engineering_observability_snapshot_exposes_worktrees_leases_and_multirepo(tmp_path: Path):
    from universal_brain.engineering import CodeGraphIndexer, build_engineering_observability_snapshot

    (tmp_path / "a.py").write_text("def x():\n    return 1\n", encoding="utf-8")
    graph = CodeGraphIndexer().build(tmp_path)
    lease_store = DurableWorkerLeaseStore(tmp_path / ".brain" / "leases.json")
    lease_store.acquire(task_id="t1", worker_id="w1", workspace_id=uuid4(), ttl_seconds=30)

    class Worktrees:
        def export_bindings(self):
            return {
                "REQ-1": {
                    "requirement_ref": "REQ-1",
                    "branch": "brain/req-REQ-1",
                    "path": str(tmp_path / "wt"),
                    "node_ids": ["a", "b"],
                    "verified_commit": None,
                    "integrated_commit": None,
                }
            }

    stack = SimpleNamespace(
        code_graph=graph,
        worktrees=Worktrees(),
        distributed_leases=lease_store,
        multi_repo_graph=MultiRepositoryGraphBuilder().build([tmp_path]),
        service_supervisor=None,
        isolation_provider=None,
        semantic_backends=("lsp",),
    )
    snapshot = build_engineering_observability_snapshot(stack)
    assert snapshot.symbol_count >= 1
    assert snapshot.active_worktrees[0].requirement_ref == "REQ-1"
    assert snapshot.durable_worker_leases[0].task_id == "t1"
    assert snapshot.semantic_backends == ["lsp"]
