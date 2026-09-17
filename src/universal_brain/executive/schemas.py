"""
Universal Brain - Executive Canonical Data Contracts

Defines model-independent, canonical contracts for:
- Intent comprehension (IntentRecord);
- Contract proposals (ContractProposal);
- Declarative task DAGs (TaskNode, TaskDAG);
- Ephemeral model authorization (ModelLease);
- Cognitive continuity (HandoffSnapshot);
- Structured model responses (ExecutiveModelResponse).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from universal_brain.kernel.events import ActionClass


# -----------------------------------------------------------------------------
# 1. Intent & Contract Proposal Contracts
# -----------------------------------------------------------------------------


class IntentRecord(BaseModel):
    """Canonical record of structured operator intent."""

    intent_id: UUID = Field(default_factory=uuid4)
    source_event_id: Optional[UUID] = None
    operator_id: str = "operator"
    project_id: Optional[UUID] = None
    primary_goal: str
    functional_requirements: List[str] = Field(default_factory=list)
    non_goals: List[str] = Field(default_factory=list)
    explicit_constraints: List[str] = Field(default_factory=list)
    candidate_constraints: List[str] = Field(default_factory=list)
    ambiguities: List[Dict[str, Any]] = Field(default_factory=list)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    requested_outcomes: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: int = 1


class ContractProposal(BaseModel):
    """Proposal to instantiate or amend an AlignmentContract."""

    proposal_id: UUID = Field(default_factory=uuid4)
    intent_id: UUID
    objective: str
    requirements: List[Dict[str, Any]] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    action_ceiling: ActionClass = ActionClass.A1
    acceptance_criteria: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "DRAFT"


# -----------------------------------------------------------------------------
# 2. Declarative Task DAG Contracts
# -----------------------------------------------------------------------------


class TaskNodeStatus(str, Enum):
    """Lifecycle status of a single DAG node."""

    PLANNED = "PLANNED"
    READY = "READY"
    LEASE_ASSIGNED = "LEASE_ASSIGNED"
    COGNITIVE_WORK = "COGNITIVE_WORK"
    TOOL_PROPOSED = "TOOL_PROPOSED"
    PREFLIGHT = "PREFLIGHT"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"


class TaskNode(BaseModel):
    """Declarative unit of executable work."""

    node_id: str
    dag_id: UUID
    goal: str
    description: str = ""
    requirement_refs: List[str] = Field(..., min_length=1)  # ALN-001: Must cite at least one requirement
    dependencies: List[str] = Field(default_factory=list)
    action_class: ActionClass = ActionClass.A0
    tool_scope: List[str] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)  # ALN-010: Acceptance criteria required
    expected_evidence: List[str] = Field(default_factory=list)
    reversibility_requirement: bool = True
    status: TaskNodeStatus = TaskNodeStatus.PLANNED
    version: int = Field(1, ge=1)


class TaskDAG(BaseModel):
    """Acyclic directed graph of declarative tasks."""

    dag_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    contract_id: UUID
    contract_version: int
    nodes: Dict[str, TaskNode] = Field(default_factory=dict)
    version: int = Field(1, ge=1)

    def validate_acyclic(self) -> bool:
        """Verifies that the task dependencies form a valid DAG (no cycles)."""
        visited: Dict[str, int] = {}  # 0 = unvisited, 1 = visiting, 2 = visited

        def dfs(node_id: str) -> bool:
            visited[node_id] = 1
            node = self.nodes.get(node_id)
            if node:
                for dep in node.dependencies:
                    if visited.get(dep) == 1:
                        return False  # Cycle detected
                    if visited.get(dep) != 2:
                        if not dfs(dep):
                            return False
            visited[node_id] = 2
            return True

        for nid in self.nodes:
            if visited.get(nid) != 2:
                if not dfs(nid):
                    return False
        return True


# -----------------------------------------------------------------------------
# 3. Model Lease Contracts
# -----------------------------------------------------------------------------


class LeaseStatus(str, Enum):
    """Lifecycle status of an ephemeral model lease."""

    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"
    REVOKED = "REVOKED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class ModelLease(BaseModel):
    """Bounded, ephemeral intelligence execution lease."""

    lease_id: UUID = Field(default_factory=uuid4)
    provider_id: str
    model_id: str
    task_id: UUID
    project_id: UUID
    granted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    max_turns: int = 10
    turns_used: int = 0
    max_input_tokens: int = 100000
    input_tokens_used: int = 0
    max_output_tokens: int = 4000
    output_tokens_used: int = 0
    spend_ceiling_usd: float = 5.0
    spend_used_usd: float = 0.0
    status: LeaseStatus = LeaseStatus.ACTIVE

    def is_valid(self, now: Optional[datetime] = None) -> bool:
        """Check if lease is still active and unexhausted."""
        current_time = now or datetime.now(timezone.utc)
        if self.status != LeaseStatus.ACTIVE:
            return False
        if current_time > self.expires_at:
            return False
        if self.turns_used >= self.max_turns:
            return False
        if self.spend_used_usd >= self.spend_ceiling_usd:
            return False
        return True


# -----------------------------------------------------------------------------
# 4. Cognitive Handoff Contracts
# -----------------------------------------------------------------------------


class HandoffSnapshot(BaseModel):
    """
    Formal, model-independent state transfer snapshot.
    Enforces invariant: NO LOSS OF CANONICAL TASK STATE ACROSS MODEL HANDOFFS.
    """

    handoff_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    task_id: UUID
    task_version: int
    contract_id: UUID
    contract_version: int
    outgoing_provider: str
    outgoing_model: str
    outgoing_lease_id: UUID
    incoming_provider: str
    incoming_model: str
    incoming_lease_id: Optional[UUID] = None
    goal: str
    completed_subtasks: List[str] = Field(default_factory=list)
    active_subtask: Optional[str] = None
    blocked_subtasks: List[str] = Field(default_factory=list)
    next_planned_actions: List[str] = Field(default_factory=list)
    open_assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    unresolved_ambiguities: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    failure_ledger: List[Dict[str, Any]] = Field(default_factory=list)
    active_capability_ceiling: ActionClass
    tool_scope: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: int = 1
    state_digest: str = ""

    @staticmethod
    def calculate_digest(data: Dict[str, Any]) -> str:
        """Computes deterministic SHA-256 over canonical snapshot fields."""
        ceiling = data.get("active_capability_ceiling")
        if hasattr(ceiling, "value"):
            ceiling = ceiling.value
        elif isinstance(ceiling, str):
            # If ActionClass string representation e.g. "ActionClass.A1"
            ceiling = ceiling.split(".")[-1]

        canonical_fields = {
            "active_capability_ceiling": str(ceiling),
            "active_subtask": data.get("active_subtask"),
            "blocked_subtasks": sorted(data.get("blocked_subtasks") or []),
            "completed_subtasks": sorted(data.get("completed_subtasks") or []),
            "contract_id": str(data["contract_id"]),
            "contract_version": int(data["contract_version"]),
            "evidence_refs": sorted(data.get("evidence_refs") or []),
            "goal": str(data["goal"]),
            "next_planned_actions": list(data.get("next_planned_actions") or []),
            "project_id": str(data["project_id"]),
            "task_id": str(data["task_id"]),
            "task_version": int(data["task_version"]),
            "tool_scope": sorted(data.get("tool_scope") or []),
        }
        json_bytes = json.dumps(canonical_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()

    def verify_digest(self) -> bool:
        """Verify that current snapshot matches recorded state_digest."""
        expected = self.calculate_digest(self.model_dump())
        return self.state_digest.lower() == expected.lower()


# -----------------------------------------------------------------------------
# 5. Untrusted Model Response Contract
# -----------------------------------------------------------------------------


class ExecutiveModelResponse(BaseModel):
    """
    Structured model proposal envelope.
    Treated as untrusted input until validated by the Kernel.
    """

    response_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    lease_id: UUID
    observations: List[str] = Field(default_factory=list)
    proposed_decisions: List[Dict[str, Any]] = Field(default_factory=list)
    proposed_task_updates: List[Dict[str, Any]] = Field(default_factory=list)
    requested_tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    new_assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    resolved_ambiguities: List[str] = Field(default_factory=list)
    new_ambiguities: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_requests: List[str] = Field(default_factory=list)
    handoff_recommended: bool = False
    completion_candidate: bool = False
    raw_content: Optional[str] = None
    provider_metadata: Dict[str, Any] = Field(default_factory=dict)
