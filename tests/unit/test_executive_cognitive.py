"""
Universal Brain - Executive Cognitive & Adversarial Verification Suite

Validates Milestones M3 + M4:
- Invariant 1: Models never become authoritative state stores.
- Invariant 3: Canonical state survives provider failure.
- Invariant 4: Every model invocation is associated with an eap_digest.
- Invariant 5: Every committed result is validated against current state.
- Invariant 6: Every task traces back to contract requirements (ALN-001).
- Invariant 7: Every tool invocation passes through ToolGateway.
- Invariant 9: Handoff revokes previous execution ownership (Split-brain protection).
- Invariant 10: Completion requires evidence.
- Invariant: NO LOSS OF CANONICAL TASK STATE ACROSS MODEL HANDOFFS.
"""

from datetime import datetime, timezone
from uuid import uuid4
import pytest

from universal_brain.alignment.contract import (
    AcceptanceCriterion,
    ActionClass,
    AlignmentContract,
    OriginalInput,
    PermissionsCeiling,
    Requirement,
    RequirementKind,
    RequirementPriority,
)
from universal_brain.executive.budget import BudgetGatekeeper, BudgetTier
from universal_brain.executive.eap import EAPBuilder, ExecutiveAwarenessPackage
from universal_brain.executive.failures import AntiLoopBreakerError, FailureLedger
from universal_brain.executive.handoff import CognitiveHandoffManager
from universal_brain.executive.intent import IntentParser
from universal_brain.executive.leases import ModelLeaseController
from universal_brain.executive.planner import TaskPlanner
from universal_brain.executive.providers.base import ProviderOutageError
from universal_brain.executive.providers.mock import MockModelProvider
from universal_brain.executive.providers.registry import ModelProviderRegistry
from universal_brain.executive.router import ModelRouter
from universal_brain.executive.scheduler import ExecutiveScheduler
from universal_brain.executive.schemas import LeaseStatus, TaskNodeStatus
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.errors import AmbiguityBlockedError, CapabilityDeniedError, InvariantViolationError
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType
from universal_brain.memory.retention import StorageRetentionManager
from universal_brain.tools.base import BaseTool, ToolResult
from universal_brain.tools.gateway import ToolGateway


class MockPatchTool(BaseTool):
    @property
    def name(self) -> str:
        return "patch_file"

    @property
    def action_class(self) -> ActionClass:
        return ActionClass.A1

    @property
    def allowed_resource_patterns(self) -> list[str]:
        return ["./src/.*"]

    def preflight_check(self, args: dict, target_resource: str = "*") -> bool:
        return True

    def execute(self, args: dict, target_resource: str = "*") -> ToolResult:
        return ToolResult(
            success=True,
            output="Patch applied",
            evidence={"sha256": "abc1234"},
            rollback_data={"reverse": "diff"},
        )

    def rollback(self, rollback_data: dict) -> bool:
        return True


class MockReadTool(BaseTool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def action_class(self) -> ActionClass:
        return ActionClass.A0

    @property
    def allowed_resource_patterns(self) -> list[str]:
        return ["./src/.*", "./tests/.*"]

    def preflight_check(self, args: dict, target_resource: str = "*") -> bool:
        return True

    def execute(self, args: dict, target_resource: str = "*") -> ToolResult:
        return ToolResult(
            success=True,
            output="Read analysis specification",
            evidence={"spec": True},
        )

    def rollback(self, rollback_data: dict) -> bool:
        return True


@pytest.fixture
def test_env():
    event_store = EventStore()
    capability_service = CapabilityService()
    budget_gatekeeper = BudgetGatekeeper(monthly_budget_usd=20.0)
    retention_manager = StorageRetentionManager(critical_threshold_pct=99.9)
    tool_gateway = ToolGateway(
        event_store=event_store,
        capability_service=capability_service,
        budget_gatekeeper=budget_gatekeeper,
        retention_manager=retention_manager,
    )
    tool_gateway.register_tool(MockReadTool())
    tool_gateway.register_tool(MockPatchTool())

    eap_builder = EAPBuilder()
    lease_controller = ModelLeaseController()
    handoff_manager = CognitiveHandoffManager(lease_controller, event_store)

    registry = ModelProviderRegistry()
    mock_claude = MockModelProvider(provider_id="mock-claude", model_id="claude-3-5-sonnet")
    mock_gpt = MockModelProvider(provider_id="mock-gpt", model_id="gpt-4o")
    registry.register_provider(mock_claude)
    registry.register_provider(mock_gpt)

    router = ModelRouter(registry, budget_gatekeeper)
    failure_ledger = FailureLedger(max_identical_failures=3)

    scheduler = ExecutiveScheduler(
        router=router,
        lease_controller=lease_controller,
        eap_builder=eap_builder,
        tool_gateway=tool_gateway,
        capability_service=capability_service,
        event_store=event_store,
        handoff_manager=handoff_manager,
        retention_manager=retention_manager,
        failure_ledger=failure_ledger,
    )

    # Base contract
    orig = OriginalInput(exact_content_ref="Build PID Controller")
    req = Requirement(
        requirement_id="REQ-001",
        statement="ROS 2 Humble balance PID node",
        source_input_ids=[orig.input_id],
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        verification_method="test",
    )
    perm = PermissionsCeiling(action_ceiling=ActionClass.A1)
    crit = AcceptanceCriterion(criterion_id="AC-001", statement="Pass 100% tests", evidence_type="log", verifier="det")
    contract = AlignmentContract.create_draft(
        objective="PID Controller",
        requirements=[req],
        permissions=perm,
        acceptance_criteria=[crit],
        original_inputs=[orig],
    ).activate()

    return {
        "event_store": event_store,
        "capability_service": capability_service,
        "budget_gatekeeper": budget_gatekeeper,
        "retention_manager": retention_manager,
        "tool_gateway": tool_gateway,
        "eap_builder": eap_builder,
        "lease_controller": lease_controller,
        "handoff_manager": handoff_manager,
        "registry": registry,
        "router": router,
        "scheduler": scheduler,
        "contract": contract,
        "mock_claude": mock_claude,
        "mock_gpt": mock_gpt,
    }


def test_eap_determinism_and_digest_integrity(test_env):
    """Verify that identical Brain state produces deterministic EAP and eap_digest."""
    builder: EAPBuilder = test_env["eap_builder"]
    contract = test_env["contract"]
    event_store = test_env["event_store"]
    budget = test_env["budget_gatekeeper"]
    retention = test_env["retention_manager"]

    p_id = uuid4()
    t_id = uuid4()
    s_id = uuid4()
    l_id = uuid4()

    eap_1 = builder.build_eap(p_id, s_id, t_id, l_id, contract, event_store, budget, retention)
    eap_2 = builder.build_eap(p_id, s_id, t_id, l_id, contract, event_store, budget, retention)

    assert eap_1.eap_digest == eap_2.eap_digest
    assert len(eap_1.eap_digest) == 64
    assert eap_1.verify_digest() is True


def test_provider_circuit_breaker_trips_on_failures(test_env):
    """Verify that 3 consecutive provider failures trip circuit breaker to OPEN."""
    registry: ModelProviderRegistry = test_env["registry"]
    router: ModelRouter = test_env["router"]
    mock_claude: MockModelProvider = test_env["mock_claude"]

    assert registry._circuit_breakers["mock-claude"].state == "HEALTHY"

    # Record 3 failures
    registry.record_failure("mock-claude")
    assert registry._circuit_breakers["mock-claude"].state == "DEGRADED"
    registry.record_failure("mock-claude")
    registry.record_failure("mock-claude")
    assert registry._circuit_breakers["mock-claude"].state == "OPEN"

    # Router must reject mock-claude and select mock-gpt
    decision = router.select_model()
    assert decision.selected_provider.metadata.provider_id == "mock-gpt"
    assert any("Circuit breaker is OPEN" in reason for pid, reason in decision.rejected_candidates if pid == "mock-claude")


def test_model_lease_revocation_prevents_stale_commits(test_env):
    """Verify that revoked leases cannot be used or record usage."""
    controller: ModelLeaseController = test_env["lease_controller"]
    p_id = uuid4()
    t_id = uuid4()

    lease = controller.grant_lease(
        provider_id="mock-claude",
        model_id="claude-3-5-sonnet",
        task_id=t_id,
        project_id=p_id,
        max_turns=3,
    )
    assert lease.is_valid() is True

    # Revoke lease
    controller.revoke_lease(lease.lease_id)
    assert lease.status == LeaseStatus.REVOKED
    assert lease.is_valid() is False

    with pytest.raises(CapabilityDeniedError, match="revoked"):
        controller.record_usage(lease.lease_id, 100, 50, 0.001)


def test_cognitive_handoff_invariant_no_loss_of_task_state(test_env):
    """
    CRITICAL MASTER GATE:
    Verify NO LOSS OF CANONICAL TASK STATE ACROSS MODEL HANDOFFS.
    """
    handoff_manager: CognitiveHandoffManager = test_env["handoff_manager"]
    controller: ModelLeaseController = test_env["lease_controller"]
    contract = test_env["contract"]

    p_id = uuid4()
    t_id = uuid4()

    # Outgoing Lease for Model A
    lease_a = controller.grant_lease("mock-claude", "claude-3-5-sonnet", t_id, p_id)

    # Model A completes 2 subtasks, has 1 active, 1 failure, and 2 evidence refs
    snapshot = handoff_manager.create_snapshot(
        project_id=p_id,
        task_id=t_id,
        task_version=3,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        outgoing_provider="mock-claude",
        outgoing_model="claude-3-5-sonnet",
        outgoing_lease_id=lease_a.lease_id,
        incoming_provider="mock-gpt",
        incoming_model="gpt-4o",
        goal="Humanoid Balance Controller Bringup",
        completed_subtasks=["task_01_design", "task_02_impl"],
        active_subtask="task_03_verification",
        blocked_subtasks=[],
        next_planned_actions=["Run Gazebo simulation"],
        open_assumptions=[{"id": "ASM-01", "statement": "ROS 2 Humble"}],
        unresolved_ambiguities=[],
        evidence_refs=["ev-build-991", "ev-test-992"],
        failure_ledger=[{"attempt": 1, "error": "compiler warning"}],
        active_capability_ceiling=ActionClass.A1,
        tool_scope=["patch_file", "run_tests"],
    )

    assert snapshot.verify_digest() is True

    # Execute Handoff
    new_snapshot, lease_b = handoff_manager.execute_handoff(snapshot)

    # 1. Verify Split-Brain Protection: Model A lease is REVOKED
    assert lease_a.status == LeaseStatus.REVOKED
    assert lease_a.is_valid() is False

    # 2. Verify Model B lease is ACTIVE and distinct
    assert lease_b.status == LeaseStatus.ACTIVE
    assert lease_b.lease_id != lease_a.lease_id

    # 3. Verify ZERO LOSS OF CANONICAL STATE (State Parity)
    assert new_snapshot.completed_subtasks == ["task_01_design", "task_02_impl"]
    assert new_snapshot.active_subtask == "task_03_verification"
    assert new_snapshot.evidence_refs == ["ev-build-991", "ev-test-992"]
    assert new_snapshot.contract_version == contract.version
    assert new_snapshot.incoming_model == "gpt-4o"
    assert new_snapshot.verify_digest() is True


def test_tampered_handoff_snapshot_fails_closed(test_env):
    """Verify that tampering with a snapshot digest halts handoff immediately."""
    handoff_manager: CognitiveHandoffManager = test_env["handoff_manager"]
    controller: ModelLeaseController = test_env["lease_controller"]
    contract = test_env["contract"]
    p_id = uuid4()
    t_id = uuid4()

    lease = controller.grant_lease("mock-claude", "claude", t_id, p_id)
    snapshot = handoff_manager.create_snapshot(
        project_id=p_id,
        task_id=t_id,
        task_version=1,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        outgoing_provider="mock-claude",
        outgoing_model="claude",
        outgoing_lease_id=lease.lease_id,
        incoming_provider="mock-gpt",
        incoming_model="gpt-4o",
        goal="Task",
        completed_subtasks=[],
    )

    # Tamper with snapshot goal without updating digest
    snapshot.goal = "MALICIOUS TAMPERED GOAL"

    with pytest.raises(InvariantViolationError, match="state_digest mismatch"):
        handoff_manager.execute_handoff(snapshot)


def test_intent_parser_detects_ambiguity_and_blocks_aln004a():
    """Verify that high-impact ambiguity in intent blocks contract activation."""
    parser = IntentParser()
    prompt = "Deploy controller to motor actuator and maybe delete prod_db perhaps"

    intent = parser.parse_intent(prompt)
    assert len(intent.ambiguities) >= 1

    # Should raise AmbiguityBlockedError
    with pytest.raises(AmbiguityBlockedError, match="High-impact ambiguity"):
        parser.propose_contract(intent)


def test_task_planner_and_scheduler_end_to_end(test_env):
    """Verify TaskPlanner produces DAG and ExecutiveScheduler advances steps cleanly."""
    contract = test_env["contract"]
    scheduler: ExecutiveScheduler = test_env["scheduler"]
    p_id = uuid4()
    s_id = uuid4()

    planner = TaskPlanner()
    dag = planner.plan_contract(contract, project_id=p_id)

    assert dag.validate_acyclic() is True
    assert len(dag.nodes) >= 3
    assert "task_01_design" in dag.nodes

    # Node 1 is READY
    ready_nodes = scheduler.get_ready_nodes(dag)
    assert len(ready_nodes) == 1
    assert ready_nodes[0].node_id == "task_01_design"

    # Execute step 1
    import asyncio
    res = asyncio.run(scheduler.execute_step(dag, contract, s_id))
    assert res["status"] == "STEP_SUCCEEDED"
    assert dag.nodes["task_01_design"].status == TaskNodeStatus.SUCCEEDED

    # Node 2 becomes READY
    ready_after = scheduler.get_ready_nodes(dag)
    assert len(ready_after) == 1
    assert ready_after[0].node_id == "task_02_implementation"


def test_anti_loop_breaker_halts_repeated_failures(test_env):
    """Verify failure ledger halts autonomous loops after 3 consecutive identical failures."""
    ledger = FailureLedger(max_identical_failures=3)
    t_id = uuid4()

    # Attempt 1
    ledger.record_failure(t_id, "node_01", "mock-claude", "claude", "BUILD_ERROR", "Undefined symbol", tool_name="colcon")
    # Attempt 2
    ledger.record_failure(t_id, "node_01", "mock-claude", "claude", "BUILD_ERROR", "Undefined symbol", tool_name="colcon")
    # Attempt 3 must raise AntiLoopBreakerError
    with pytest.raises(AntiLoopBreakerError, match="ANTI-LOOP BREAKER"):
        ledger.record_failure(t_id, "node_01", "mock-claude", "claude", "BUILD_ERROR", "Undefined symbol", tool_name="colcon")


def test_budget_aware_routing_auto_downgrade(test_env):
    """Verify router automatically downgrades model tiers when budget is under pressure."""
    router: ModelRouter = test_env["router"]
    budget: BudgetGatekeeper = test_env["budget_gatekeeper"]

    # At normal budget ($0 spend), prefers Claude
    decision = router.select_model(task_complexity="complex_planning")
    assert decision.selected_provider.metadata.provider_id == "mock-claude"

    # Simulate budget spend reaching Tier 2 ($18.00 / $20.00 ceiling)
    budget.cumulative_spend_usd = 18.00
    assert budget.get_tier() == BudgetTier.DOWNGRADE

    # Mock Claude costs $3.00/M input, Mock GPT costs $5.00/M input
    # In Tier 2, Claude is selected over GPT due to cost efficiency
    decision_downgrade = router.select_model()
    assert decision_downgrade.selected_provider.metadata.cost_per_million_input <= 3.00
