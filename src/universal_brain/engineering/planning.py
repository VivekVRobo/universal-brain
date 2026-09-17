"""Hierarchical and mutable engineering planning.

Traceability: REQ-ENG-001, REQ-ENG-002, REQ-ALN-003, ALN-001, ALN-005,
ALN-010, ALN-021.
"""

from __future__ import annotations

from collections import deque
from typing import Iterable
from uuid import UUID, uuid4

from universal_brain.alignment.contract import AlignmentContract
from universal_brain.executive.schemas import TaskDAG, TaskNode, TaskNodeStatus
from universal_brain.kernel.errors import InvariantViolationError
from universal_brain.kernel.events import ActionClass


class PlanMutationError(ValueError):
    pass


class HierarchicalEngineeringPlanner:
    """Build a requirement-oriented DAG instead of a fixed three-node plan.

    Each requirement receives an independent analysis -> implementation -> verification
    chain. After shared architecture is established, requirement chains can run in
    parallel. A final integration gate joins all verified branches.
    """

    def plan_contract(self, contract: AlignmentContract, project_id: UUID | None = None) -> TaskDAG:
        if not contract.requirements:
            raise InvariantViolationError("ALN-001", "Cannot plan a contract without requirements")
        if not contract.acceptance_criteria:
            raise InvariantViolationError("ALN-010", "Cannot plan without acceptance criteria")

        dag_id = uuid4()
        p_id = project_id or uuid4()
        all_refs = [req.requirement_id for req in contract.requirements]
        nodes: dict[str, TaskNode] = {}

        architecture = TaskNode(
            node_id="eng_000_architecture",
            dag_id=dag_id,
            goal=f"Establish project architecture for {contract.objective}",
            description="Map requirements to components, interfaces, risks, and verification strategy.",
            requirement_refs=all_refs,
            action_class=ActionClass.A0,
            tool_scope=["read_file", "search_code"],
            required_capabilities=["reasoning", "architecture", "coding"],
            acceptance_criteria=["Architecture maps every active requirement to an implementation boundary"],
            expected_evidence=["architecture_manifest"],
            status=TaskNodeStatus.READY,
        )
        nodes[architecture.node_id] = architecture

        verification_nodes: list[str] = []
        for index, req in enumerate(contract.requirements, start=1):
            prefix = f"eng_{index:03d}_{self._slug(req.requirement_id)}"
            analysis_id = f"{prefix}_analyze"
            implementation_id = f"{prefix}_implement"
            verification_id = f"{prefix}_verify"

            nodes[analysis_id] = TaskNode(
                node_id=analysis_id,
                dag_id=dag_id,
                goal=f"Analyze implementation impact for {req.requirement_id}",
                description=req.statement,
                requirement_refs=[req.requirement_id],
                dependencies=[architecture.node_id],
                action_class=ActionClass.A0,
                tool_scope=["read_file", "search_code", "index_symbols"],
                required_capabilities=["reasoning", "coding"],
                acceptance_criteria=[f"Implementation scope for {req.requirement_id} is explicit and testable"],
                expected_evidence=["impact_analysis"],
            )
            nodes[implementation_id] = TaskNode(
                node_id=implementation_id,
                dag_id=dag_id,
                goal=f"Implement {req.requirement_id}",
                description=req.statement,
                requirement_refs=[req.requirement_id],
                dependencies=[analysis_id],
                action_class=ActionClass.A1,
                tool_scope=["read_file", "patch_file", "write_file", "run_command"],
                required_capabilities=["coding", "tool"],
                acceptance_criteria=[req.statement],
                expected_evidence=["source_diff", "tool_evidence"],
            )
            nodes[verification_id] = TaskNode(
                node_id=verification_id,
                dag_id=dag_id,
                goal=f"Verify {req.requirement_id}",
                description=req.verification_method,
                requirement_refs=[req.requirement_id],
                dependencies=[implementation_id],
                action_class=ActionClass.A0,
                tool_scope=["run_command", "read_file"],
                required_capabilities=["verification"],
                acceptance_criteria=[req.verification_method],
                expected_evidence=["exit_code_zero", "verification_log"],
            )
            verification_nodes.append(verification_id)

        integration = TaskNode(
            node_id="eng_900_integration",
            dag_id=dag_id,
            goal="Integrate all requirement branches and run project-level verification",
            description="Verify cross-component behavior and contract-level acceptance criteria.",
            requirement_refs=all_refs,
            dependencies=verification_nodes,
            action_class=ActionClass.A0,
            tool_scope=["run_command", "read_file"],
            required_capabilities=["verification", "architecture"],
            acceptance_criteria=[criterion.statement for criterion in contract.acceptance_criteria],
            expected_evidence=["integration_test_log", "acceptance_criteria_matrix"],
        )
        nodes[integration.node_id] = integration

        dag = TaskDAG(
            dag_id=dag_id,
            project_id=p_id,
            contract_id=contract.contract_id,
            contract_version=contract.version,
            nodes=nodes,
        )
        if not dag.validate_acyclic():
            raise InvariantViolationError("ALN-021", "Engineering planner produced a cyclic DAG")
        return dag

    @staticmethod
    def _slug(value: str) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
        return cleaned[:40] or "requirement"


class TaskDAGMutator:
    """Safely mutate a TaskDAG after discoveries/failures (REQ-ENG-002, ALN-005)."""

    TERMINAL = {TaskNodeStatus.SUCCEEDED, TaskNodeStatus.FAILED}

    def add_node(self, dag: TaskDAG, node: TaskNode) -> None:
        if node.dag_id != dag.dag_id:
            raise PlanMutationError("New node belongs to a different DAG")
        if node.node_id in dag.nodes:
            raise PlanMutationError(f"Duplicate node id: {node.node_id}")
        missing = [dep for dep in node.dependencies if dep not in dag.nodes]
        if missing:
            raise PlanMutationError(f"Unknown dependencies: {missing}")
        dag.nodes[node.node_id] = node
        if not dag.validate_acyclic():
            del dag.nodes[node.node_id]
            raise PlanMutationError("Mutation would introduce a dependency cycle")
        dag.version += 1

    def insert_before(self, dag: TaskDAG, target_id: str, node: TaskNode) -> None:
        target = self._require_node(dag, target_id)
        old_dependencies = list(target.dependencies)
        node = node.model_copy(update={"dependencies": old_dependencies})
        self.add_node(dag, node)
        target.dependencies = [node.node_id]
        target.status = TaskNodeStatus.PLANNED
        target.version += 1
        dag.version += 1
        if not dag.validate_acyclic():
            raise PlanMutationError("insert_before produced a cycle")

    def insert_after(self, dag: TaskDAG, target_id: str, node: TaskNode) -> None:
        target = self._require_node(dag, target_id)
        node = node.model_copy(update={"dependencies": [target_id]})
        dependents = [n for n in dag.nodes.values() if target_id in n.dependencies]
        self.add_node(dag, node)
        for dependent in dependents:
            dependent.dependencies = [node.node_id if dep == target_id else dep for dep in dependent.dependencies]
            dependent.status = TaskNodeStatus.PLANNED
            dependent.version += 1
        dag.version += 1
        if not dag.validate_acyclic():
            raise PlanMutationError("insert_after produced a cycle")

    def invalidate_descendants(self, dag: TaskDAG, root_ids: Iterable[str], *, reason: str = "replan") -> list[str]:
        reverse: dict[str, list[str]] = {node_id: [] for node_id in dag.nodes}
        for node in dag.nodes.values():
            for dep in node.dependencies:
                if dep in reverse:
                    reverse[dep].append(node.node_id)
        queue = deque(root_ids)
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            for child in reverse.get(current, []):
                if child in seen:
                    continue
                seen.add(child)
                queue.append(child)
        for node_id in seen:
            node = dag.nodes[node_id]
            if node.status != TaskNodeStatus.FAILED:
                node.status = TaskNodeStatus.PLANNED
                node.version += 1
        if seen:
            dag.version += 1
        return sorted(seen)

    @staticmethod
    def ready_nodes(dag: TaskDAG) -> list[TaskNode]:
        ready: list[TaskNode] = []
        for node in dag.nodes.values():
            if node.status == TaskNodeStatus.READY:
                ready.append(node)
                continue
            if node.status != TaskNodeStatus.PLANNED:
                continue
            if node.dependencies and all(
                dep in dag.nodes and dag.nodes[dep].status == TaskNodeStatus.SUCCEEDED
                for dep in node.dependencies
            ):
                node.status = TaskNodeStatus.READY
                ready.append(node)
        return ready

    @staticmethod
    def _require_node(dag: TaskDAG, node_id: str) -> TaskNode:
        try:
            return dag.nodes[node_id]
        except KeyError as exc:
            raise PlanMutationError(f"Unknown target node: {node_id}") from exc
