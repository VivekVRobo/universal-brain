"""
Universal Brain - Declarative Task Planner

Implements Sections 40–44 of the God-Level Specification:
- Converts active AlignmentContract into a declarative TaskDAG;
- Enforces requirement traceability (ALN-001: Every task cites a requirement);
- Acyclic dependency validation;
- Strict rule: The planner produces declarative plans; it NEVER executes tools directly.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from uuid import UUID, uuid4

from universal_brain.alignment.contract import AlignmentContract
from universal_brain.executive.schemas import TaskDAG, TaskNode, TaskNodeStatus
from universal_brain.kernel.errors import InvariantViolationError
from universal_brain.kernel.events import ActionClass


class TaskPlanner:
    """Generates declarative, requirement-grounded Task DAGs from Alignment Contracts."""

    def plan_contract(
        self,
        contract: AlignmentContract,
        project_id: Optional[UUID] = None,
    ) -> TaskDAG:
        """
        Deconstructs contract requirements into an acyclic task graph.
        Ensures ALN-001 and ALN-010 compliance.
        """
        p_id = project_id or uuid4()
        dag_id = uuid4()
        nodes: Dict[str, TaskNode] = {}

        # 1. Step 1: Design / Interface Node (A0 - Read-only analysis)
        req_ids = [r.requirement_id for r in contract.requirements]
        if not req_ids:
            raise InvariantViolationError("ALN-001", "Cannot plan contract without requirements.")

        node_1 = TaskNode(
            node_id="task_01_design",
            dag_id=dag_id,
            goal="Analyze requirements and design component interfaces",
            description=f"Design architecture satisfying: {', '.join(req_ids)}",
            requirement_refs=req_ids,
            dependencies=[],
            action_class=ActionClass.A0,
            tool_scope=["read_file", "search_web"],
            required_capabilities=["read"],
            acceptance_criteria=["Design document or interface specification drafted"],
            status=TaskNodeStatus.READY,
        )
        nodes[node_1.node_id] = node_1

        # 2. Step 2: Implementation Node (A1 - Reversible file modification)
        node_2 = TaskNode(
            node_id="task_02_implementation",
            dag_id=dag_id,
            goal=f"Implement source code for: {contract.objective}",
            description="Write source files respecting explicit constraints",
            requirement_refs=req_ids,
            dependencies=["task_01_design"],
            action_class=ActionClass.A1,
            tool_scope=["patch_file", "write_file"],
            required_capabilities=["write", "patch"],
            acceptance_criteria=["Source files generated and verified under dry-run reversibility"],
            status=TaskNodeStatus.PLANNED,
        )
        nodes[node_2.node_id] = node_2

        # 3. Step 3: Verification & Test Execution (A0/A1)
        ac_statements = [ac.statement for ac in contract.acceptance_criteria]
        node_3 = TaskNode(
            node_id="task_03_verification",
            dag_id=dag_id,
            goal="Execute build and automated test suite",
            description="Generate deterministic verification evidence log",
            requirement_refs=req_ids,
            dependencies=["task_02_implementation"],
            action_class=ActionClass.A0,
            tool_scope=["colcon_build", "run_tests"],
            required_capabilities=["exec:test"],
            acceptance_criteria=ac_statements or ["All tests pass with 0 errors"],
            expected_evidence=["test_execution_log", "exit_code_zero"],
            status=TaskNodeStatus.PLANNED,
        )
        nodes[node_3.node_id] = node_3

        # 4. Optional Step 4: Consequential Hardware Bringup (A2)
        if contract.permissions.action_ceiling == ActionClass.A2:
            node_4 = TaskNode(
                node_id="task_04_hardware_bringup",
                dag_id=dag_id,
                goal="Deploy verified controller to physical hardware testbed",
                description="Requires explicit human operator authorization ceremony",
                requirement_refs=req_ids,
                dependencies=["task_03_verification"],
                action_class=ActionClass.A2,
                tool_scope=["can_transceiver_enable", "power_relay_on"],
                required_capabilities=["can:write", "relay:power"],
                acceptance_criteria=["Operator cryptographic sign-off received", "Pre-state verified"],
                reversibility_requirement=True,
                status=TaskNodeStatus.PLANNED,
            )
            nodes[node_4.node_id] = node_4

        dag = TaskDAG(
            dag_id=dag_id,
            project_id=p_id,
            contract_id=contract.contract_id,
            contract_version=contract.version,
            nodes=nodes,
        )

        # Validate DAG
        if not dag.validate_acyclic():
            raise InvariantViolationError("ALN-021", "Generated task plan contains dependency cycles.")

        return dag

    def plan_engineering_contract(
        self,
        contract: AlignmentContract,
        project_id: Optional[UUID] = None,
    ) -> TaskDAG:
        """V5 engineering planner entry point (REQ-ENG-001).

        Kept separate from plan_contract for backward compatibility with earlier
        milestone gates. New engineering missions should prefer this method.
        """
        from universal_brain.engineering.planning import HierarchicalEngineeringPlanner

        return HierarchicalEngineeringPlanner().plan_contract(contract, project_id=project_id)
