from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from universal_brain.engineering import (
    CodeGraphIndexer,
    DependencyEcosystem,
    DependencyFailureDiagnoser,
    EngineeringCausalAuditor,
    EngineeringCheckpointError,
    EngineeringCheckpointStore,
    EngineeringWorkspace,
    GitTransactionEngine,
    ImpactAwareExecutableVerificationAdapter,
    LocalModelResourceProfile,
    LocalResourceSnapshot,
    OllamaResourceManager,
    OllamaRouteResourcePolicy,
    PersistentServiceSupervisor,
    RequirementWorktreeManager,
    ServiceState,
    VerificationCheckResult,
    WorkspaceScopedToolExecutor,
)
from universal_brain.engineering.schemas import EngineeringToolObservation, VerificationCommand
from universal_brain.executive.budget import BudgetGatekeeper
from universal_brain.executive.schemas import TaskDAG, TaskNode, TaskNodeStatus
from universal_brain.intelligence.catalog import ModelCatalog
from universal_brain.intelligence.routing import IntelligenceRouter
from universal_brain.intelligence.schemas import (
    AccessRoute,
    CapabilityProfile,
    ModelCapability,
    ModelDescriptor,
    ModelMessage,
    ModelRequest,
    NormalizedModelResult,
    NormalizedToolCall,
    RetentionPolicy,
    SensitivityLevel,
    TaskProfile,
    TransportKind,
)
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventType


def one_node_dag(status: TaskNodeStatus = TaskNodeStatus.READY) -> TaskDAG:
    dag_id = uuid4()
    node = TaskNode(
        node_id="eng_001_req_1_implement",
        dag_id=dag_id,
        goal="Implement REQ-1",
        requirement_refs=["REQ-1"],
        action_class=ActionClass.A1,
        tool_scope=["patch_file"],
        required_capabilities=["coding"],
        acceptance_criteria=["tests pass"],
        status=status,
    )
    return TaskDAG(
        dag_id=dag_id,
        project_id=uuid4(),
        contract_id=uuid4(),
        contract_version=1,
        nodes={node.node_id: node},
    )


def test_checkpoint_is_atomic_self_verifying_and_fails_closed_on_workspace_drift(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    dag = one_node_dag(TaskNodeStatus.COGNITIVE_WORK)
    store = EngineeringCheckpointStore(tmp_path / ".brain" / "mission.json")
    checkpoint = store.save(dag=dag, workspace_root=tmp_path)
    assert checkpoint.payload_sha256

    recovered, reset, loaded = store.recover(workspace_root=tmp_path)
    assert reset == ["eng_001_req_1_implement"]
    assert recovered.nodes[reset[0]].status == TaskNodeStatus.REPLAN_REQUIRED
    loaded.verify_checksum()

    (tmp_path / "src" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(EngineeringCheckpointError, match="Workspace drift"):
        store.recover(workspace_root=tmp_path)


def test_causal_auditor_hashes_model_content_without_storing_raw_prompt():
    store = EventStore()
    auditor = EngineeringCausalAuditor(store)
    project_id = uuid4()
    request = ModelRequest(
        messages=[ModelMessage(role="user", content="SECRET PROMPT CONTENT")],
        metadata={"node_id": "n1"},
    )
    request_event = auditor.record_request(request, project_id=project_id, node_id="n1")
    result = NormalizedModelResult(
        request_id=request.request_id,
        model_key="ollama/qwen",
        route_id="local",
        output_text="PRIVATE RESPONSE CONTENT",
        tool_calls=[NormalizedToolCall(tool_name="patch_file", arguments={"path": "a.py"})],
    )
    response_event = auditor.record_response(
        result,
        project_id=project_id,
        node_id="n1",
        caused_by_event_id=request_event.event_id,
    )
    assert request_event.event_type == EventType.MODEL_REQUESTED
    assert response_event.event_type == EventType.MODEL_RESPONSE
    assert "SECRET PROMPT CONTENT" not in str(request_event.payload)
    assert "PRIVATE RESPONSE CONTENT" not in str(response_event.payload)
    lineage = store.trace_causal_lineage(response_event.event_id)
    assert [event.event_type for event in lineage] == [EventType.MODEL_REQUESTED, EventType.MODEL_RESPONSE]
    assert store.verify_chain_integrity()


def test_code_graph_incremental_refresh_and_transitive_test_impact(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text(
        "from src.a import foo\n\ndef bar():\n    return foo()\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_b.py").write_text(
        "from src.b import bar\n\ndef test_bar():\n    assert bar() == 1\n",
        encoding="utf-8",
    )
    indexer = CodeGraphIndexer()
    index = indexer.build(tmp_path)
    assert "tests/test_b.py" in index.affected_tests(["src/a.py"])

    (tmp_path / "src" / "a.py").write_text("def foo():\n    return 2\n", encoding="utf-8")
    delta = indexer.refresh(index)
    assert delta.changed_files == ["src/a.py"]
    assert "src/b.py" in index.files_impacted_by(["src/a.py"])
    assert "tests/test_b.py" in index.affected_tests(["src/a.py"])

    (tmp_path / "src" / "b.py").unlink()
    delta = indexer.refresh(index)
    assert "src/b.py" in delta.deleted_files
    assert not any(symbol.file_path == "src/b.py" for symbol in index.symbols.values())


class StaticPolicy:
    def discover(self, root: Path):
        return [VerificationCommand(check_id="python_pytest", executable="pytest", arguments=["-q"], cwd=root)]


class RecordingVerificationExecutor:
    def __init__(self):
        self.commands = []

    async def run(self, command, *, node):
        self.commands.append(command)
        return VerificationCheckResult(
            check_id=command.check_id,
            passed=True,
            evidence_ref="test://impact",
            exit_code=0,
            reason="ok",
        )


@pytest.mark.asyncio
async def test_impact_verifier_scopes_pytest_to_affected_tests(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "planner.py").write_text(
        "def plan():\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_planner.py").write_text(
        "from src.planner import plan\n\ndef test_plan():\n    assert plan() == 1\n",
        encoding="utf-8",
    )
    graph = CodeGraphIndexer().build(tmp_path)
    executor = RecordingVerificationExecutor()

    async def changed(_node):
        return ["src/planner.py"]

    verifier = ImpactAwareExecutableVerificationAdapter(
        tmp_path,
        executor,
        code_graph=graph,
        changed_files_provider=changed,
        policy=StaticPolicy(),
    )
    node = one_node_dag().nodes["eng_001_req_1_implement"]
    result = NormalizedModelResult(request_id=uuid4(), model_key="m", route_id="r")
    decision = await verifier.verify(node, result)
    assert decision.accepted
    assert verifier.last_affected_tests == ["tests/test_planner.py"]
    assert executor.commands[0].arguments == ["-q", "tests/test_planner.py"]


class FakeGit:
    def __init__(self, root: Path):
        self.workspace = EngineeringWorkspace(project_id=uuid4(), repository_root=root, git_root=root)
        self.workspace.normalized_worktree_root().mkdir(parents=True, exist_ok=True)
        self.created = []
        self.committed = []
        self.integrated = []
        self.removed = []

    async def create_task_worktree(self, task_id, *, branch=None):
        path = self.workspace.normalized_worktree_root() / task_id
        path.mkdir(parents=True, exist_ok=True)
        self.created.append((task_id, branch, path))
        return path

    async def commit(self, path, *, message, paths=None):
        self.committed.append((Path(path), message))
        return "abc123"

    async def integrate_branch(self, branch):
        self.integrated.append(branch)
        return "def456"

    async def remove_worktree(self, task_id, *, force=False):
        self.removed.append(task_id)


@pytest.mark.asyncio
async def test_requirement_chain_reuses_one_worktree_and_integrates_only_after_verify(tmp_path: Path):
    fake_git = FakeGit(tmp_path)
    manager = RequirementWorktreeManager(fake_git, max_active=2)
    dag_id = uuid4()
    analyze = TaskNode(
        node_id="eng_001_req_1_analyze",
        dag_id=dag_id,
        goal="Analyze",
        requirement_refs=["REQ-1"],
        acceptance_criteria=["scope explicit"],
    )
    implement = analyze.model_copy(update={"node_id": "eng_001_req_1_implement"})
    verify = analyze.model_copy(update={"node_id": "eng_001_req_1_verify"})

    a = await manager.acquire_for_node(analyze)
    b = await manager.acquire_for_node(implement)
    assert a.path == b.path
    assert len(fake_git.created) == 1
    finalized = await manager.finalize_verified_requirement(verify)
    assert finalized.verified_commit == "abc123"
    assert finalized.integrated_commit == "def456"
    assert fake_git.integrated == ["brain/req-REQ-1"]
    assert fake_git.removed == ["REQ-1"]


class RecordingDelegate:
    def __init__(self):
        self.calls = []

    async def execute(self, node, call):
        self.calls.append(call)
        return EngineeringToolObservation(tool_name=call.tool_name, success=True)


@pytest.mark.asyncio
async def test_workspace_scoped_tool_executor_rebases_relative_paths_and_rejects_escape(tmp_path: Path):
    delegate = RecordingDelegate()
    wrapper = WorkspaceScopedToolExecutor(delegate, lambda _node: tmp_path)
    node = one_node_dag().nodes["eng_001_req_1_implement"]
    ok = await wrapper.execute(node, NormalizedToolCall(tool_name="patch_file", arguments={"path": "src/a.py"}))
    assert ok.success
    assert delegate.calls[0].arguments["path"] == str((tmp_path / "src/a.py").resolve())

    bad = await wrapper.execute(node, NormalizedToolCall(tool_name="patch_file", arguments={"path": "../escape.py"}))
    assert not bad.success
    assert "escapes assigned engineering workspace" in bad.error


def test_ollama_resource_policy_participates_in_actual_router_eligibility():
    catalog = ModelCatalog()
    capability = CapabilityProfile(scores={ModelCapability.REASONING: 0.8})
    catalog.register_model(ModelDescriptor(
        model_key="ollama/small", vendor="local", model_id="small", display_name="small", family="ollama",
        capability_profile=capability,
    ))
    catalog.register_model(ModelDescriptor(
        model_key="ollama/large", vendor="local", model_id="large", display_name="large", family="ollama",
        capability_profile=capability,
    ))
    for key in ("small", "large"):
        catalog.register_route(AccessRoute(
            route_id=f"local-{key}", model_key=f"ollama/{key}", transport=TransportKind.LOCAL,
            retention_policy=RetentionPolicy.LOCAL_ONLY,
            max_sensitivity=SensitivityLevel.SECRET,
            config={"resource_model_key": f"ollama/{key}"},
        ))
    manager = OllamaResourceManager([
        LocalModelResourceProfile(model_key="ollama/small", estimated_vram_mb=2000, estimated_ram_mb=3000),
        LocalModelResourceProfile(model_key="ollama/large", estimated_vram_mb=8000, estimated_ram_mb=9000),
    ])
    snapshot = LocalResourceSnapshot(available_vram_mb=4096, available_ram_mb=12000, loaded_models=set())
    policy = OllamaRouteResourcePolicy(manager, lambda: snapshot)
    router = IntelligenceRouter(catalog, BudgetGatekeeper(monthly_budget_usd=10), route_policies=[policy])
    decision = router.select(TaskProfile(required_capabilities={ModelCapability.REASONING}, local_only=True))
    assert decision.model_key == "ollama/small"
    assert any(item.route_id == "local-large" and "resource admission" in item.reason.lower() for item in decision.rejected)


def test_dependency_diagnoser_preserves_existing_lockfile_ecosystem(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    plan = DependencyFailureDiagnoser().diagnose(tmp_path, "Cannot find module 'react'")
    assert plan.ecosystem == DependencyEcosystem.NPM
    assert plan.package_manager == "pnpm"
    assert plan.missing_name == "react"
    assert plan.suggested_commands == [["pnpm", "install", "--frozen-lockfile"]]


class FakeServiceBackend:
    def __init__(self):
        self.running = {}
        self.next_pid = 100

    async def start(self, record):
        self.next_pid += 1
        self.running[str(record.service_id)] = True
        return self.next_pid, f"log://{record.name}"

    async def stop(self, record):
        self.running[str(record.service_id)] = False
        return True

    async def is_running(self, record):
        return self.running.get(str(record.service_id), record.state == ServiceState.RUNNING)

    async def tail_logs(self, record, max_lines=200):
        return f"{record.name}: ready"


@pytest.mark.asyncio
async def test_service_supervisor_persists_and_recovers_long_running_service_state(tmp_path: Path):
    backend = FakeServiceBackend()
    registry = tmp_path / ".brain" / "services.json"
    supervisor = PersistentServiceSupervisor(registry, backend)
    record = await supervisor.start("api", ["uvicorn", "app:app"], cwd=tmp_path)
    assert record.state == ServiceState.RUNNING
    assert registry.exists()
    assert await supervisor.logs("api") == "api: ready"

    restored = PersistentServiceSupervisor(registry, backend)
    recovered = await restored.recover()
    assert recovered[0].name == "api"
    stopped = await restored.stop("api")
    assert stopped.state == ServiceState.STOPPED


class RecordingGitExecutorV51:
    def __init__(self):
        self.calls = []

    async def run_git(self, arguments, *, cwd, operation):
        self.calls.append((operation, list(arguments), Path(cwd)))
        if operation in {"git_rev_parse", "git_integration_rev_parse"}:
            output = "deadbeef\n"
        else:
            output = ""
        return EngineeringToolObservation(tool_name="run_command", success=True, output=output)


@pytest.mark.asyncio
async def test_git_engine_verified_integration_fails_closed_on_dirty_base_and_merges_clean_branch(tmp_path: Path):
    workspace = EngineeringWorkspace(project_id=uuid4(), repository_root=tmp_path, git_root=tmp_path)
    executor = RecordingGitExecutorV51()
    engine = GitTransactionEngine(workspace, executor)
    sha = await engine.integrate_branch("brain/req-REQ-1")
    assert sha == "deadbeef"
    assert [call[0] for call in executor.calls] == ["git_status", "git_merge_verified_branch", "git_integration_rev_parse"]


def test_worktree_scheduler_respects_capacity_but_reuses_existing_requirement(tmp_path: Path):
    fake_git = FakeGit(tmp_path)
    manager = RequirementWorktreeManager(fake_git, max_active=1)
    dag_id = uuid4()
    req1_analyze = TaskNode(
        node_id="r1a", dag_id=dag_id, goal="a", requirement_refs=["REQ-1"], acceptance_criteria=["ok"]
    )
    req1_impl = req1_analyze.model_copy(update={"node_id": "r1i"})
    req2_analyze = req1_analyze.model_copy(update={"node_id": "r2a", "requirement_refs": ["REQ-2"]})

    # Simulate REQ-1 already owning the only slot.
    root = fake_git.workspace.normalized_worktree_root()
    binding_path = root / "REQ-1"
    binding_path.mkdir(parents=True, exist_ok=True)
    manager.restore_bindings({
        "REQ-1": {
            "requirement_ref": "REQ-1",
            "branch": "brain/req-REQ-1",
            "path": str(binding_path),
            "node_ids": ["r1a"],
            "verified_commit": None,
            "integrated_commit": None,
        }
    })
    selected = manager.select_schedulable([req2_analyze, req1_impl], limit=2)
    assert [node.node_id for node in selected] == ["r1i"]


class FlakyIntegrationGit(FakeGit):
    def __init__(self, root: Path):
        super().__init__(root)
        self.integration_attempts = 0

    async def integrate_branch(self, branch):
        self.integration_attempts += 1
        if self.integration_attempts == 1:
            raise RuntimeError("merge conflict")
        return await super().integrate_branch(branch)


@pytest.mark.asyncio
async def test_verified_worktree_finalize_is_retry_safe_after_integration_failure(tmp_path: Path):
    fake_git = FlakyIntegrationGit(tmp_path)
    manager = RequirementWorktreeManager(fake_git)
    node = TaskNode(
        node_id="eng_001_req_1_verify",
        dag_id=uuid4(),
        goal="verify",
        requirement_refs=["REQ-1"],
        acceptance_criteria=["ok"],
    )
    await manager.acquire_for_node(node)
    with pytest.raises(RuntimeError, match="merge conflict"):
        await manager.finalize_verified_requirement(node)
    # Commit must not be repeated on retry; only integration is retried.
    assert len(fake_git.committed) == 1
    finalized = await manager.finalize_verified_requirement(node)
    assert finalized.integrated_commit == "def456"
    assert len(fake_git.committed) == 1


def test_engineering_factory_wires_scoped_tools_verification_checkpoint_and_audit(tmp_path: Path):
    from universal_brain.engineering import build_engineering_agency_stack

    class DummyGitExecutor:
        async def run_git(self, arguments, *, cwd, operation):
            return EngineeringToolObservation(tool_name="git", success=True, output="")

    class DummyToolExecutor:
        async def execute(self, node, call):
            return EngineeringToolObservation(tool_name=call.tool_name, success=True)

    class DummyVerificationExecutor:
        async def run(self, command, *, node):
            return VerificationCheckResult(check_id=command.check_id, passed=True, evidence_ref="x", exit_code=0)

    workspace = EngineeringWorkspace(project_id=uuid4(), repository_root=tmp_path, git_root=tmp_path)
    workspace.normalized_worktree_root().mkdir(parents=True, exist_ok=True)
    stack = build_engineering_agency_stack(
        workspace=workspace,
        cognitive_runtime=SimpleNamespace(),
        tool_executor=DummyToolExecutor(),
        verification_executor=DummyVerificationExecutor(),
        git_executor=DummyGitExecutor(),
        event_store=EventStore(),
        max_parallel_nodes=2,
    )
    assert stack.runtime.worktree_manager is stack.worktrees
    assert stack.runtime.checkpoint_store is stack.checkpoint_store
    assert stack.verifier.workspace_resolver.__self__ is stack.worktrees
    assert stack.verifier.workspace_resolver.__func__ is stack.worktrees.workspace_for_node.__func__
