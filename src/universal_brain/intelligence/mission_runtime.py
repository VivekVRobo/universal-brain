from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from universal_brain.executive.schemas import TaskDAG, TaskNode, TaskNodeStatus
from universal_brain.kernel.events import ActionClass

from .council import CouncilRole, CouncilSynthesisResult
from .schemas import (
    ModelCapability,
    ModelMessage,
    ModelRequest,
    NormalizedModelResult,
    TaskComplexity,
    TaskProfile,
)


class CognitiveExecutionMode(str, Enum):
    DIRECT = "direct"
    COUNCIL = "council"


class MissionVerificationDecision(BaseModel):
    accepted: bool
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str = ""


class MissionVerificationAdapter(Protocol):
    async def verify(
        self,
        node: TaskNode,
        result: NormalizedModelResult,
    ) -> MissionVerificationDecision: ...


class MissionNodeRun(BaseModel):
    node_id: str
    mode: CognitiveExecutionMode
    result: NormalizedModelResult
    council: CouncilSynthesisResult | None = None
    status_before: TaskNodeStatus
    status_after: TaskNodeStatus
    verification: MissionVerificationDecision | None = None
    tool_proposal_count: int = 0
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = Field(default_factory=dict)


class MissionCycleResult(BaseModel):
    dag_id: UUID
    runs: list[MissionNodeRun] = Field(default_factory=list)
    blocked_nodes: list[str] = Field(default_factory=list)
    complete: bool = False
    cycles: int = 0


class TaskNodeIntelligenceMapper:
    """Convert canonical TaskNode requirements into an Intelligence Fabric task.

    This mapping affects cognition selection only; it never expands the node's action
    class, tool scope, or permissions.
    """

    CAPABILITY_ALIASES = {
        "read": ModelCapability.REASONING,
        "reason": ModelCapability.REASONING,
        "reasoning": ModelCapability.REASONING,
        "code": ModelCapability.CODING,
        "coding": ModelCapability.CODING,
        "write": ModelCapability.CODING,
        "patch": ModelCapability.CODING,
        "architecture": ModelCapability.ARCHITECTURE,
        "research": ModelCapability.RESEARCH,
        "verify": ModelCapability.VERIFICATION,
        "verification": ModelCapability.VERIFICATION,
        "test": ModelCapability.VERIFICATION,
        "vision": ModelCapability.VISION,
        "tool": ModelCapability.TOOL_USE,
        "computer": ModelCapability.COMPUTER_USE,
    }

    def map(self, node: TaskNode, *, project_id: UUID) -> TaskProfile:
        capabilities: set[ModelCapability] = {ModelCapability.REASONING}
        for raw in node.required_capabilities:
            text = str(raw).strip().lower()
            head = text.split(":", 1)[0]
            capability = self.CAPABILITY_ALIASES.get(text) or self.CAPABILITY_ALIASES.get(head)
            if capability:
                capabilities.add(capability)
        goal_text = f"{node.goal} {node.description}".lower()
        if any(term in goal_text for term in ("implement", "code", "source", "refactor")):
            capabilities.add(ModelCapability.CODING)
        if any(term in goal_text for term in ("architecture", "design", "interface")):
            capabilities.add(ModelCapability.ARCHITECTURE)
        if any(term in goal_text for term in ("verify", "test", "audit", "evidence")):
            capabilities.add(ModelCapability.VERIFICATION)

        return TaskProfile(
            task_kind="mission_task",
            required_capabilities=capabilities,
            action_class=node.action_class,
            require_tools=False,  # Tool calls remain proposals for ToolGateway.
            metadata={
                "project_id": str(project_id),
                "node_id": node.node_id,
                "requirement_refs": list(node.requirement_refs),
                "tool_scope": list(node.tool_scope),
                "acceptance_criteria": list(node.acceptance_criteria),
                "expected_evidence": list(node.expected_evidence),
            },
        )

    def request(self, node: TaskNode, *, project_id: UUID) -> ModelRequest:
        system = (
            "You are a leased cognitive worker inside Universal Brain. Work only on the "
            "declared task. Do not expand permissions. Do not execute external actions. "
            "Any tool call is a proposal for Kernel/ToolGateway review. Do not claim task "
            "completion or verification without inspectable evidence."
        )
        user = (
            f"TASK: {node.goal}\n"
            f"DESCRIPTION: {node.description}\n"
            f"REQUIREMENT_REFS: {node.requirement_refs}\n"
            f"ACTION_CLASS: {node.action_class.value}\n"
            f"TOOL_SCOPE: {node.tool_scope}\n"
            f"ACCEPTANCE_CRITERIA: {node.acceptance_criteria}\n"
            f"EXPECTED_EVIDENCE: {node.expected_evidence}\n"
            "Return the best task-scoped cognitive result and explicitly identify evidence gaps."
        )
        return ModelRequest(
            messages=[ModelMessage(role="system", content=system), ModelMessage(role="user", content=user)],
            metadata={
                "project_id": str(project_id),
                "cognitive_role": "mission_worker",
                "task_kind": "mission_task",
                "action_class": node.action_class.value,
                "node_id": node.node_id,
                "requirement_refs": list(node.requirement_refs),
                "tool_scope": list(node.tool_scope),
                "profile_text": f"{node.goal}\n{node.description}",
            },
        )


class AdaptiveCognitiveMissionRuntime:
    """Bridge canonical TaskDAG nodes into the adaptive Intelligence Fabric.

    The runtime performs cognition and optional verification orchestration. It does
    not execute model-proposed tools itself. A1/A2 proposals remain behind the normal
    Kernel/ToolGateway approval path.
    """

    def __init__(
        self,
        *,
        fabric,
        escalator,
        council_executor,
        mapper: TaskNodeIntelligenceMapper | None = None,
        verifier: MissionVerificationAdapter | None = None,
        council_for_complex: bool = True,
        council_required_for_a2: bool = True,
    ) -> None:
        self.fabric = fabric
        self.escalator = escalator
        self.council_executor = council_executor
        self.mapper = mapper or TaskNodeIntelligenceMapper()
        self.verifier = verifier
        self.council_for_complex = council_for_complex
        self.council_required_for_a2 = council_required_for_a2

    @staticmethod
    def _role_request(base: ModelRequest, role: str) -> ModelRequest:
        messages = [
            ModelMessage(
                role="system",
                content=(
                    f"COUNCIL_ROLE={role}. Provide an independent task-scoped analysis. "
                    "State claims clearly; preserve uncertainty and evidence gaps."
                ),
            ),
            *base.messages,
        ]
        metadata = dict(base.metadata)
        metadata["cognitive_role"] = role
        return base.model_copy(update={"messages": messages, "metadata": metadata})

    async def _run_council(
        self,
        *,
        profile: TaskProfile,
        request: ModelRequest,
    ) -> CouncilSynthesisResult:
        member_profile = profile.model_copy(update={"task_kind": "mission_council_member"})
        first = self.fabric.router.select(member_profile)
        roles = [
            CouncilRole(role="architect", task_profile=member_profile),
            CouncilRole(
                role="critic",
                task_profile=member_profile,
                require_independent_model_from=first.model_key,
                require_independent_route_from=first.route_id,
            ),
        ]
        requests = {role.role: self._role_request(request, role.role) for role in roles}
        synthesis_profile = profile.model_copy(update={"task_kind": "mission_council_synthesis"})
        synthesis_role = CouncilRole(role="synthesizer", task_profile=synthesis_profile)
        resolution_role = CouncilRole(
            role="disagreement_resolver",
            task_profile=profile.model_copy(update={"task_kind": "mission_council_resolution"}),
        )
        return await self.council_executor.execute_and_synthesize(
            roles=roles,
            requests=requests,
            synthesis_role=synthesis_role,
            resolution_role=resolution_role,
        )

    async def execute_node(self, node: TaskNode, *, project_id: UUID) -> MissionNodeRun:
        if not node.requirement_refs:
            raise ValueError("ALN-001: mission cognitive task must cite requirement refs")
        if not node.acceptance_criteria:
            raise ValueError("ALN-010: mission cognitive task requires acceptance criteria")
        status_before = node.status
        node.status = TaskNodeStatus.COGNITIVE_WORK
        base_profile = self.mapper.map(node, project_id=project_id)
        request = self.mapper.request(node, project_id=project_id)
        analysis = self.fabric.analyze_task(request, base_task=base_profile)
        profile = analysis.profile
        use_council = (
            node.action_class == ActionClass.A2
            or (
                self.council_for_complex
                and profile.complexity in {TaskComplexity.COMPLEX, TaskComplexity.FRONTIER}
            )
        )
        council_bundle = None
        fallback_reason = None
        if use_council:
            try:
                council_bundle = await self._run_council(profile=profile, request=request)
                result = council_bundle.synthesis_result
                mode = CognitiveExecutionMode.COUNCIL
            except Exception as exc:
                if node.action_class == ActionClass.A2 and self.council_required_for_a2:
                    node.status = TaskNodeStatus.BLOCKED
                    raise
                fallback_reason = f"{type(exc).__name__}: {exc}"
                result = await self.escalator.invoke(profile, request)
                mode = CognitiveExecutionMode.DIRECT
        else:
            result = await self.escalator.invoke(profile, request)
            mode = CognitiveExecutionMode.DIRECT

        verification = None
        if result.tool_calls:
            node.status = TaskNodeStatus.TOOL_PROPOSED
        else:
            node.status = TaskNodeStatus.VERIFYING
            if self.verifier is not None:
                verification = await self.verifier.verify(node, result)
                node.status = (
                    TaskNodeStatus.SUCCEEDED
                    if verification.accepted
                    else TaskNodeStatus.REPLAN_REQUIRED
                )

        metadata = {
            "task_profile_analysis": analysis.model_dump(mode="json"),
            "requirement_refs": list(node.requirement_refs),
            "consensus_is_evidence": False,
            "external_actions_executed": False,
        }
        if fallback_reason:
            metadata["council_fallback_reason"] = fallback_reason
        return MissionNodeRun(
            node_id=node.node_id,
            mode=mode,
            result=result,
            council=council_bundle,
            status_before=status_before,
            status_after=node.status,
            verification=verification,
            tool_proposal_count=len(result.tool_calls),
            metadata=metadata,
        )

    @staticmethod
    def _refresh_ready_nodes(dag: TaskDAG) -> None:
        for node in dag.nodes.values():
            if node.status != TaskNodeStatus.PLANNED:
                continue
            if all(
                dag.nodes[dependency].status == TaskNodeStatus.SUCCEEDED
                for dependency in node.dependencies
                if dependency in dag.nodes
            ) and all(dependency in dag.nodes for dependency in node.dependencies):
                node.status = TaskNodeStatus.READY

    async def run_dag(
        self,
        dag: TaskDAG,
        *,
        max_cycles: int = 32,
    ) -> MissionCycleResult:
        if not dag.validate_acyclic():
            raise ValueError("ALN-021: task DAG contains a dependency cycle")
        runs: list[MissionNodeRun] = []
        cycles = 0
        while cycles < max_cycles:
            cycles += 1
            self._refresh_ready_nodes(dag)
            ready = [node for node in dag.nodes.values() if node.status == TaskNodeStatus.READY]
            if not ready:
                break
            for node in ready:
                runs.append(await self.execute_node(node, project_id=dag.project_id))
            # Without an approved verifier, nodes stop at VERIFYING/TOOL_PROPOSED;
            # continuing downstream would incorrectly imply acceptance.
            if self.verifier is None:
                break

        complete = bool(dag.nodes) and all(
            node.status == TaskNodeStatus.SUCCEEDED for node in dag.nodes.values()
        )
        blocked = [
            node.node_id
            for node in dag.nodes.values()
            if node.status
            in {
                TaskNodeStatus.BLOCKED,
                TaskNodeStatus.REPLAN_REQUIRED,
                TaskNodeStatus.FAILED,
                TaskNodeStatus.TOOL_PROPOSED,
                TaskNodeStatus.VERIFYING,
            }
        ]
        return MissionCycleResult(
            dag_id=dag.dag_id,
            runs=runs,
            blocked_nodes=blocked,
            complete=complete,
            cycles=cycles,
        )
