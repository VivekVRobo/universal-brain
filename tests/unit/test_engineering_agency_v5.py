from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from universal_brain.alignment.contract import (
    AcceptanceCriterion,
    AlignmentContract,
    ContractStatus,
    OriginalInput,
    PermissionsCeiling,
    Requirement,
    RequirementKind,
    RequirementPriority,
)
from universal_brain.engineering import (
    CodeGraphIndexer,
    EngineeringAgencyRuntime,
    EngineeringToolObservation,
    EngineeringWorkspace,
    ExecutableVerificationAdapter,
    GitTransactionEngine,
    GitTransactionError,
    HierarchicalEngineeringPlanner,
    TaskDAGMutator,
    VerificationCheckResult,
)
from universal_brain.engineering.schemas import VerificationCommand
from universal_brain.executive.schemas import TaskDAG, TaskNode, TaskNodeStatus
from universal_brain.intelligence.mission_runtime import MissionNodeRun, CognitiveExecutionMode, TaskNodeIntelligenceMapper
from universal_brain.intelligence.schemas import (
    ModelCapability,
    ModelRequest,
    NormalizedModelResult,
    NormalizedToolCall,
    TaskProfile,
)
from universal_brain.kernel.events import ActionClass


def contract_with_requirements(count: int = 3) -> AlignmentContract:
    source = OriginalInput(exact_content_ref="operator://v5-plan")
    requirements = [
        Requirement(
            requirement_id=f"REQ-{index:03d}",
            statement=f"Implement capability {index}",
            source_input_ids=[source.input_id],
            kind=RequirementKind.FUNCTIONAL,
            priority=RequirementPriority.MUST,
            verification_method=f"Automated test for capability {index} passes",
        )
        for index in range(1, count + 1)
    ]
    return AlignmentContract(
        status=ContractStatus.ACTIVE,
        original_inputs=[source],
        objective="Build a large production engineering system",
        requirements=requirements,
        permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="AC-001",
                statement="All project checks pass",
                evidence_type="test_output",
                verifier="deterministic",
            )
        ],
    )


def test_hierarchical_planner_scales_by_requirement_and_parallelizes_after_architecture():
    contract = contract_with_requirements(4)
    dag = HierarchicalEngineeringPlanner().plan_contract(contract)
    assert len(dag.nodes) == 3 * 4 + 2
    assert dag.validate_acyclic()
    assert dag.nodes["eng_000_architecture"].status == TaskNodeStatus.READY
    assert all(node.requirement_refs for node in dag.nodes.values())
    assert all(node.acceptance_criteria for node in dag.nodes.values())

    dag.nodes["eng_000_architecture"].status = TaskNodeStatus.SUCCEEDED
    ready = TaskDAGMutator.ready_nodes(dag)
    analyze = [node for node in ready if node.node_id.endswith("_analyze")]
    assert len(analyze) == 4


def test_dag_mutation_inserts_discovered_dependency_and_invalidates_descendants():
    dag = HierarchicalEngineeringPlanner().plan_contract(contract_with_requirements(1))
    dag.nodes["eng_000_architecture"].status = TaskNodeStatus.SUCCEEDED
    analyze = next(node for node in dag.nodes.values() if node.node_id.endswith("_analyze"))
    analyze.status = TaskNodeStatus.SUCCEEDED
    implement = next(node for node in dag.nodes.values() if node.node_id.endswith("_implement"))
    implement.status = TaskNodeStatus.REPLAN_REQUIRED

    new_node = TaskNode(
        node_id="eng_discovered_dependency",
        dag_id=dag.dag_id,
        goal="Add discovered dependency contract",
        description="New dependency found while implementing requirement",
        requirement_refs=implement.requirement_refs,
        action_class=ActionClass.A1,
        tool_scope=["patch_file"],
        required_capabilities=["coding"],
        acceptance_criteria=["Dependency definition exists and is verified"],
    )
    mutator = TaskDAGMutator()
    mutator.insert_before(dag, implement.node_id, new_node)
    assert implement.dependencies == [new_node.node_id]
    assert dag.validate_acyclic()

    implement.status = TaskNodeStatus.SUCCEEDED
    verify = next(node for node in dag.nodes.values() if node.node_id.endswith("_verify"))
    verify.status = TaskNodeStatus.SUCCEEDED
    integration = dag.nodes["eng_900_integration"]
    integration.status = TaskNodeStatus.SUCCEEDED
    invalidated = mutator.invalidate_descendants(dag, [new_node.node_id])
    assert implement.node_id in invalidated
    assert verify.node_id in invalidated
    assert integration.node_id in invalidated
    assert dag.nodes[verify.node_id].status == TaskNodeStatus.PLANNED


def test_code_graph_finds_symbols_calls_and_affected_tests(tmp_path: Path):
    src = tmp_path / "src"
    tests = tmp_path / "tests"
    src.mkdir()
    tests.mkdir()
    (src / "planner.py").write_text(
        "class TrajectoryPlanner:\n"
        "    def plan(self):\n"
        "        return apply_velocity_limit()\n\n"
        "def apply_velocity_limit():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    (tests / "test_planner.py").write_text(
        "from src.planner import TrajectoryPlanner\n\n"
        "def test_plan():\n"
        "    assert TrajectoryPlanner().plan() == 1\n",
        encoding="utf-8",
    )
    index = CodeGraphIndexer().build(tmp_path)
    assert index.find_symbol("TrajectoryPlanner")
    assert index.find_symbol("apply_velocity_limit")
    assert any(edge.target_name == "apply_velocity_limit" for edge in index.references)
    assert "tests/test_planner.py" in index.affected_tests(["src/planner.py"])


class StaticVerificationPolicy:
    def __init__(self, commands):
        self.commands = commands

    def discover(self, workspace_root):
        return list(self.commands)


class FakeVerificationExecutor:
    def __init__(self, passed=True):
        self.passed = passed
        self.calls = []

    async def run(self, command, *, node):
        self.calls.append(command.check_id)
        return VerificationCheckResult(
            check_id=command.check_id,
            passed=self.passed,
            evidence_ref=f"test://{command.check_id}",
            exit_code=0 if self.passed else 1,
            reason="ok" if self.passed else "failed",
        )


@pytest.mark.asyncio
async def test_executable_verifier_fails_closed_without_checks_and_accepts_real_check_contract(tmp_path: Path):
    node = TaskNode(
        node_id="verify",
        dag_id=uuid4(),
        goal="Verify project",
        requirement_refs=["REQ-1"],
        acceptance_criteria=["tests pass"],
    )
    result = NormalizedModelResult(request_id=uuid4(), model_key="local", route_id="ollama")
    empty = ExecutableVerificationAdapter(tmp_path, FakeVerificationExecutor(), policy=StaticVerificationPolicy([]))
    decision = await empty.verify(node, result)
    assert not decision.accepted
    assert "no executable verification" in decision.reason

    command = VerificationCommand(check_id="pytest", executable="pytest", cwd=tmp_path)
    executor = FakeVerificationExecutor(passed=True)
    verifier = ExecutableVerificationAdapter(tmp_path, executor, policy=StaticVerificationPolicy([command]))
    decision = await verifier.verify(node, result)
    assert decision.accepted
    assert decision.evidence_refs == ["test://pytest"]


class FakeToolExecutor:
    async def execute(self, node, call):
        return EngineeringToolObservation(
            tool_name=call.tool_name,
            call_id=call.call_id,
            success=True,
            output="patched file and tests now pass",
            evidence={"digest": "abc"},
        )


class FakeVerifier:
    def __init__(self):
        self.last_results = [VerificationCheckResult(check_id="tests", passed=True, evidence_ref="test://pass")]

    async def verify(self, node, result):
        from universal_brain.intelligence.mission_runtime import MissionVerificationDecision
        return MissionVerificationDecision(accepted=True, evidence_refs=["test://pass"], reason="pass")


class FakeEscalator:
    def __init__(self):
        self.requests = []

    async def invoke(self, profile, request):
        self.requests.append(request)
        return NormalizedModelResult(
            request_id=request.request_id,
            model_key="ollama/qwen",
            route_id="local",
            output_text="repair complete; ready for external verification",
        )


class FakeFabric:
    def analyze_task(self, request, base_task=None):
        return SimpleNamespace(profile=base_task or TaskProfile(required_capabilities={ModelCapability.REASONING}))


class FakeCognitiveRuntime:
    def __init__(self):
        self.mapper = TaskNodeIntelligenceMapper()
        self.fabric = FakeFabric()
        self.escalator = FakeEscalator()

    async def execute_node(self, node, *, project_id):
        result = NormalizedModelResult(
            request_id=uuid4(),
            model_key="ollama/qwen",
            route_id="local",
            output_text="need patch",
            tool_calls=[NormalizedToolCall(tool_name="patch_file", arguments={"target": "src/a.py"}, call_id="c1")],
        )
        before = node.status
        node.status = TaskNodeStatus.TOOL_PROPOSED
        return MissionNodeRun(
            node_id=node.node_id,
            mode=CognitiveExecutionMode.DIRECT,
            result=result,
            status_before=before,
            status_after=node.status,
            tool_proposal_count=1,
        )


@pytest.mark.asyncio
async def test_engineering_loop_executes_tool_observes_reasons_again_and_verifies():
    node = TaskNode(
        node_id="impl",
        dag_id=uuid4(),
        goal="Implement change",
        requirement_refs=["REQ-1"],
        action_class=ActionClass.A1,
        tool_scope=["patch_file"],
        required_capabilities=["coding"],
        acceptance_criteria=["feature works"],
        status=TaskNodeStatus.READY,
    )
    cognitive = FakeCognitiveRuntime()
    runtime = EngineeringAgencyRuntime(
        cognitive_runtime=cognitive,
        tool_executor=FakeToolExecutor(),
        verifier=FakeVerifier(),
        max_tool_iterations=3,
    )
    run = await runtime.execute_node(node, project_id=uuid4())
    assert run.status_after == TaskNodeStatus.SUCCEEDED
    assert run.iterations == 1
    assert run.observations[0].success
    assert "OBSERVATION_ITERATION=1" in cognitive.escalator.requests[0].messages[-1].content


class RecordingGitExecutor:
    def __init__(self):
        self.calls = []

    async def run_git(self, arguments, *, cwd, operation):
        self.calls.append((operation, list(arguments), Path(cwd)))
        output = "deadbeef\n" if operation == "git_rev_parse" else "ok"
        return EngineeringToolObservation(tool_name="run_command", success=True, output=output)


@pytest.mark.asyncio
async def test_git_engine_confines_worktrees_and_builds_reviewable_transactions(tmp_path: Path):
    workspace = EngineeringWorkspace(project_id=uuid4(), repository_root=tmp_path, git_root=tmp_path)
    workspace.normalized_worktree_root().mkdir(parents=True, exist_ok=True)
    executor = RecordingGitExecutor()
    engine = GitTransactionEngine(workspace, executor)
    path = await engine.create_task_worktree("REQ-123")
    assert workspace.normalized_worktree_root() in path.parents
    sha = await engine.commit(path, message="Implement REQ-123")
    assert sha == "deadbeef"
    operations = [item[0] for item in executor.calls]
    assert operations[:4] == ["git_worktree_add", "git_add", "git_commit", "git_rev_parse"]

    with pytest.raises(GitTransactionError):
        await engine.create_task_worktree("x", branch="../unsafe")

from universal_brain.engineering import (
    LocalModelResourceProfile,
    LocalResourceSnapshot,
    OllamaResourceManager,
    ProjectCompletionAuditor,
    VerifiedWorkerCompletionGate,
    WorkerCompletionDecision,
)
from universal_brain.tools.workers.queue import EphemeralJobQueue


def test_ollama_resource_manager_prefers_warm_model_and_blocks_vram_overcommit():
    manager = OllamaResourceManager([
        LocalModelResourceProfile(model_key="ollama/qwen3b", estimated_vram_mb=2200, estimated_ram_mb=3500, max_concurrency=2, expected_tokens_per_second=45),
        LocalModelResourceProfile(model_key="ollama/deepseek8b", estimated_vram_mb=5200, estimated_ram_mb=7000, max_concurrency=1, expected_tokens_per_second=18),
    ])
    snapshot = LocalResourceSnapshot(
        available_vram_mb=4096,
        available_ram_mb=12000,
        loaded_models={"ollama/qwen3b"},
        gpu_utilization_pct=15,
    )
    assert manager.can_admit("ollama/qwen3b", snapshot)[0]
    assert not manager.can_admit("ollama/deepseek8b", snapshot)[0]
    reservation = manager.reserve("ollama/qwen3b", snapshot)
    assert reservation.estimated_vram_mb == 0
    manager.release(reservation.reservation_id)


def test_project_completion_auditor_requires_verification_for_every_succeeded_node():
    contract = contract_with_requirements(1)
    dag = HierarchicalEngineeringPlanner().plan_contract(contract)
    for node in dag.nodes.values():
        node.status = TaskNodeStatus.SUCCEEDED
    runs = [
        SimpleNamespace(
            node_id=node.node_id,
            verification_checks=[VerificationCheckResult(check_id="check", passed=True, evidence_ref=f"test://{node.node_id}")],
        )
        for node in dag.nodes.values()
    ]
    report = ProjectCompletionAuditor().audit(contract, dag, runs)
    assert report.accepted
    runs.pop()
    report = ProjectCompletionAuditor().audit(contract, dag, runs)
    assert not report.accepted
    assert report.nodes_without_verification


class WorkerVerifier:
    def __init__(self, accepted):
        self.accepted = accepted

    async def verify(self, job, completion_evidence):
        return WorkerCompletionDecision(
            accepted=self.accepted,
            evidence_refs=["verify://worker-result"] if self.accepted else [],
            reason="verified" if self.accepted else "artifact test failed",
        )


@pytest.mark.asyncio
async def test_worker_completion_gate_rejects_unverified_claim_before_queue_completion():
    queue = EphemeralJobQueue()
    worker = queue.register_worker("w1", "local_gpu")
    job = queue.enqueue_job(uuid4(), uuid4(), "code", {"task": "x"})
    leased = queue.poll_and_lease("w1", worker.worker_session_id)
    assert leased is not None
    _, lease = leased
    gate = VerifiedWorkerCompletionGate(queue, WorkerVerifier(False))
    rejected = await gate.complete_job(job.job_id, "w1", lease.lease_generation, {"done": True})
    assert rejected.status.value == "REJECTED_RESULT"


@pytest.mark.asyncio
async def test_worker_completion_gate_accepts_independently_verified_claim():
    queue = EphemeralJobQueue()
    worker = queue.register_worker("w1", "local_gpu")
    job = queue.enqueue_job(uuid4(), uuid4(), "code", {"task": "x"})
    leased = queue.poll_and_lease("w1", worker.worker_session_id)
    assert leased is not None
    _, lease = leased
    gate = VerifiedWorkerCompletionGate(queue, WorkerVerifier(True))
    completed = await gate.complete_job(job.job_id, "w1", lease.lease_generation, {"done": True})
    assert completed.status.value == "COMPLETED"
    assert completed.completion_evidence["verification_evidence_refs"] == ["verify://worker-result"]

from universal_brain.engineering import CodeGraphContextSource


def test_code_graph_context_source_retrieves_symbol_scoped_context(tmp_path: Path):
    (tmp_path / "planner.py").write_text(
        "class TrajectoryPlanner:\n"
        "    def plan(self):\n"
        "        return self.apply_limit()\n\n"
        "    def apply_limit(self):\n"
        "        return 42\n",
        encoding="utf-8",
    )
    index = CodeGraphIndexer().build(tmp_path)
    chunks = CodeGraphContextSource(index).retrieve("TrajectoryPlanner apply_limit", max_chunks=4)
    assert chunks
    assert any(chunk.metadata.get("retrieval_kind") == "code_graph_symbol" for chunk in chunks)
    assert any("TrajectoryPlanner" in chunk.content for chunk in chunks)

from universal_brain.engineering import AdaptiveEngineeringReplanner, EngineeringWorkspaceInspector


def test_replanner_inserts_requirement_preserving_dependency_recovery():
    dag = HierarchicalEngineeringPlanner().plan_contract(contract_with_requirements(1))
    implement = next(node for node in dag.nodes.values() if node.node_id.endswith("_implement"))
    implement.status = TaskNodeStatus.REPLAN_REQUIRED
    run = SimpleNamespace(
        node_id=implement.node_id,
        replan_reason="Module not found: pydantic_core",
        observations=[],
        verification_checks=[],
    )
    recovery_id = AdaptiveEngineeringReplanner().replan(dag, implement.node_id, run)
    assert recovery_id is not None
    recovery = dag.nodes[recovery_id]
    assert recovery.requirement_refs == implement.requirement_refs
    assert recovery_id in implement.dependencies
    assert dag.validate_acyclic()


def test_workspace_inspector_detects_existing_ecosystems_without_mutation(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    workspace = EngineeringWorkspaceInspector().discover(tmp_path, project_id=uuid4())
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after
    assert "python" in workspace.language_ecosystems
    assert "javascript-typescript" in workspace.language_ecosystems
    assert ["pytest", "-q"] in workspace.test_commands
    assert any(command[:3] == ["npm", "exec", "tsc"] for command in workspace.test_commands)


def test_parallel_engineering_fails_closed_without_verified_workspace_isolation():
    with pytest.raises(ValueError, match="parallel engineering requires verified isolated workspaces"):
        EngineeringAgencyRuntime(
            cognitive_runtime=FakeCognitiveRuntime(),
            tool_executor=FakeToolExecutor(),
            verifier=FakeVerifier(),
            max_parallel_nodes=2,
        )
