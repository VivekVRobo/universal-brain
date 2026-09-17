"""Universal Brain - Milestone M3/M4 Master Gate Verification."""

from uuid import uuid4

import pytest

from universal_brain.alignment.contract import ActionClass
from universal_brain.executive.budget import BudgetGatekeeper
from universal_brain.executive.eap import EAPBuilder
from universal_brain.executive.failures import FailureLedger
from universal_brain.executive.handoff import CognitiveHandoffManager
from universal_brain.executive.intent import IntentParser
from universal_brain.executive.leases import ModelLeaseController
from universal_brain.executive.planner import TaskPlanner
from universal_brain.executive.providers.mock import MockModelProvider
from universal_brain.executive.providers.registry import ModelProviderRegistry
from universal_brain.executive.router import ModelRouter
from universal_brain.executive.scheduler import ExecutiveScheduler
from universal_brain.executive.schemas import LeaseStatus, TaskNodeStatus
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.errors import CapabilityDeniedError
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType
from universal_brain.memory.retention import StorageRetentionManager
from universal_brain.tools.base import BaseTool, ToolResult
from universal_brain.tools.gateway import ToolGateway


class MockBuildTool(BaseTool):
    @property
    def name(self) -> str:
        return "colcon_build"

    @property
    def action_class(self) -> ActionClass:
        return ActionClass.A1

    @property
    def allowed_resource_patterns(self) -> list[str]:
        return ["./src/.*", "./build/.*"]

    def preflight_check(self, args: dict, target_resource: str = "*") -> bool:
        return True

    def execute(self, args: dict, target_resource: str = "*") -> ToolResult:
        return ToolResult(
            success=True,
            output="Finished <<< humanoid_balance_controller [1.42s]",
            evidence={"sha256": "3df84ab1", "exit_code": 0},
            rollback_data={"clean": True},
        )

    def rollback(self, rollback_data: dict) -> bool:
        return True


class MockTestTool(BaseTool):
    @property
    def name(self) -> str:
        return "run_tests"

    @property
    def action_class(self) -> ActionClass:
        return ActionClass.A0

    @property
    def allowed_resource_patterns(self) -> list[str]:
        return ["./tests/.*", "./src/.*"]

    def preflight_check(self, args: dict, target_resource: str = "*") -> bool:
        return True

    def execute(self, args: dict, target_resource: str = "*") -> ToolResult:
        return ToolResult(
            success=True,
            output="14/14 unit tests passed. 0 failures. 0 collisions.",
            evidence={"tests_passed": 14, "exit_code": 0},
        )

    def rollback(self, rollback_data: dict) -> bool:
        return True


def test_ultimate_m3_m4_master_gate():
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
    tool_gateway.register_tool(MockBuildTool())
    tool_gateway.register_tool(MockTestTool())

    eap_builder = EAPBuilder()
    lease_controller = ModelLeaseController()
    handoff_manager = CognitiveHandoffManager(lease_controller, event_store)
    registry = ModelProviderRegistry()
    registry.register_provider(MockModelProvider(provider_id="mock-claude", model_id="claude-3-5-sonnet"))
    registry.register_provider(MockModelProvider(provider_id="mock-gpt", model_id="gpt-4o"))
    router = ModelRouter(registry, budget_gatekeeper)
    failure_ledger = FailureLedger()
    ExecutiveScheduler(
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

    prompt = "Implement humanoid balance PID controller\n1. Must compile with colcon\n2. Must pass unit tests"
    parser = IntentParser()
    contract = parser.propose_contract(parser.parse_intent(prompt))
    assert contract.status.value == "active"
    assert len(contract.requirements) == 2

    project_id = uuid4()
    session_id = uuid4()
    dag = TaskPlanner().plan_contract(contract, project_id=project_id)
    assert dag.validate_acyclic() is True

    decision = router.select_model(task_complexity="complex_planning")
    assert decision.selected_provider.metadata.provider_id == "mock-claude"
    lease_a = lease_controller.grant_lease(
        provider_id="mock-claude",
        model_id="claude-3-5-sonnet",
        task_id=dag.dag_id,
        project_id=project_id,
    )
    dag.nodes["task_01_design"].status = TaskNodeStatus.SUCCEEDED
    event_store.append_event(
        event_type=EventType.EVIDENCE_PRODUCED,
        actor_id="claude-3-5-sonnet",
        project_id=project_id,
        task_id=dag.dag_id,
        payload={"spec": "Interface designed", "sha256": "5ef14c6f"},
    )

    snapshot = handoff_manager.create_snapshot(
        project_id=project_id,
        task_id=dag.dag_id,
        task_version=dag.version,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        outgoing_provider="mock-claude",
        outgoing_model="claude-3-5-sonnet",
        outgoing_lease_id=lease_a.lease_id,
        incoming_provider="mock-gpt",
        incoming_model="gpt-4o",
        goal=dag.nodes["task_02_implementation"].goal,
        completed_subtasks=["task_01_design"],
        active_subtask="task_02_implementation",
        evidence_refs=["ev-design-spec-001"],
        open_assumptions=[{"id": "ASM-01", "statement": "ROS 2 Humble"}],
        active_capability_ceiling=ActionClass.A1,
        tool_scope=["colcon_build"],
    )
    assert snapshot.verify_digest() is True
    new_snapshot, lease_b = handoff_manager.execute_handoff(snapshot)
    assert lease_a.status == LeaseStatus.REVOKED
    with pytest.raises(CapabilityDeniedError, match="revoked"):
        lease_controller.record_usage(lease_a.lease_id, 100, 50, 0.001)
    assert lease_b.status == LeaseStatus.ACTIVE
    assert new_snapshot.completed_subtasks == ["task_01_design"]

    eap = eap_builder.build_eap(
        project_id=project_id,
        session_id=session_id,
        task_id=dag.dag_id,
        lease_id=lease_b.lease_id,
        contract=contract,
        event_store=event_store,
        budget_gatekeeper=budget_gatekeeper,
        retention_manager=retention_manager,
        task_dag=dag,
        active_node_id="task_02_implementation",
        available_tools=["colcon_build"],
    )
    assert eap.verify_digest() is True

    build_token = capability_service.issue_token(
        project_id=project_id,
        task_id=dag.dag_id,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        action_class=ActionClass.A1,
        target_resource="./build/humanoid_balance_controller",
        allowed_operations=["colcon_build"],
    )
    build_result = tool_gateway.execute_tool(
        tool_name="colcon_build",
        args={"pkg": "humanoid_balance_controller"},
        capability_token=build_token,
        contract=contract,
        target_resource="./build/humanoid_balance_controller",
    )
    assert build_result.success is True
    dag.nodes["task_02_implementation"].status = TaskNodeStatus.SUCCEEDED

    test_token = capability_service.issue_token(
        project_id=project_id,
        task_id=dag.dag_id,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        action_class=ActionClass.A0,
        target_resource="./tests/test_balance.cpp",
        allowed_operations=["run_tests"],
    )
    test_result = tool_gateway.execute_tool(
        tool_name="run_tests",
        args={"filter": "*balance*"},
        capability_token=test_token,
        contract=contract,
        target_resource="./tests/test_balance.cpp",
    )
    assert test_result.success is True
    assert test_result.evidence["tests_passed"] == 14
    dag.nodes["task_03_verification"].status = TaskNodeStatus.SUCCEEDED

    event_types = [event.event_type for event in event_store.get_all_events()]
    assert EventType.HANDOFF_OCCURRED in event_types
    assert EventType.TOOL_CALLED in event_types
    assert EventType.EVIDENCE_PRODUCED in event_types
    assert event_store.verify_chain_integrity() is True
