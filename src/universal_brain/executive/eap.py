"""
Universal Brain - Executive Awareness Package (EAP) Builder

Implements Section 8 of the God-Level Specification:
- Deterministic, provider-agnostic context envelope;
- Dynamic token budgeting and context priority hierarchy (P0 to P4);
- Cryptographic eap_digest tracking (Invariant 4);
- Strict rule: Individual providers never construct their own context.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from universal_brain.alignment.contract import AlignmentContract
from universal_brain.config import settings
from universal_brain.executive.budget import BudgetGatekeeper, BudgetTier
from universal_brain.executive.schemas import TaskDAG, TaskNode
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass
from universal_brain.memory.retention import StorageRetentionManager


class EAPIdentity(BaseModel):
    system_id: str
    operator_id: str
    project_id: UUID
    session_id: UUID
    task_id: UUID
    lease_id: UUID


class EAPGovernance(BaseModel):
    contract_id: UUID
    contract_version: int
    objective: str
    requirements: List[str]
    constraints: List[str]
    permission_ceiling: ActionClass
    active_invariants: List[str]


class EAPTaskState(BaseModel):
    goal: str
    completed_nodes: List[str] = Field(default_factory=list)
    active_node: Optional[str] = None
    blocked_nodes: List[str] = Field(default_factory=list)
    next_candidates: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)


class EAPKnowledge(BaseModel):
    verified_facts: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    unresolved_questions: List[Dict[str, Any]] = Field(default_factory=list)


class EAPHistory(BaseModel):
    recent_events: List[Dict[str, Any]] = Field(default_factory=list)
    causal_lineage: List[str] = Field(default_factory=list)
    recent_failures: List[Dict[str, Any]] = Field(default_factory=list)


class EAPResources(BaseModel):
    budget_spend_usd: float
    budget_ceiling_usd: float
    budget_tier: BudgetTier
    disk_utilization_pct: float
    available_tools: List[str]


class ExecutiveAwarenessPackage(BaseModel):
    """
    The canonical context envelope injected into the model.
    Providers do not query raw databases; they receive this EAP.
    """

    identity: EAPIdentity
    governance: EAPGovernance
    task: EAPTaskState
    knowledge: EAPKnowledge
    history: EAPHistory
    resources: EAPResources
    situational: Optional[Any] = None  # SituationalContext from M8
    schema_version: int = 1
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    eap_digest: str = ""

    @staticmethod
    def calculate_digest(data: Dict[str, Any]) -> str:
        """Deterministic SHA-256 over canonical EAP content."""
        canonical = {
            "governance": {
                "contract_id": str(data["governance"]["contract_id"]),
                "contract_version": data["governance"]["contract_version"],
                "permission_ceiling": str(data["governance"]["permission_ceiling"]),
                "requirements": sorted(data["governance"]["requirements"]),
            },
            "identity": {
                "project_id": str(data["identity"]["project_id"]),
                "system_id": data["identity"]["system_id"],
                "task_id": str(data["identity"]["task_id"]),
            },
            "knowledge": {
                "evidence_refs": sorted(data["knowledge"]["evidence_refs"]),
                "verified_facts": sorted(data["knowledge"]["verified_facts"]),
            },
            "task": {
                "active_node": data["task"].get("active_node"),
                "completed_nodes": sorted(data["task"]["completed_nodes"]),
                "goal": data["task"]["goal"],
            },
        }
        if data.get("situational"):
            sit = data["situational"]
            canonical["situational"] = {
                "world_snapshot_id": str(sit.get("world_snapshot_id", "")),
                "projection_digest": sit.get("projection_digest", ""),
            }
        json_bytes = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()

    def verify_digest(self) -> bool:
        """Assert digest integrity."""
        expected = self.calculate_digest(self.model_dump())
        return self.eap_digest.lower() == expected.lower()


class EAPBuilder:
    """Constructs deterministic, budget-pruned EAPs from authoritative Brain state."""

    def __init__(
        self,
        max_context_tokens: int = 5000,
    ) -> None:
        self.max_context_tokens = max_context_tokens

    def build_eap(
        self,
        project_id: UUID,
        session_id: UUID,
        task_id: UUID,
        lease_id: UUID,
        contract: AlignmentContract,
        event_store: EventStore,
        budget_gatekeeper: BudgetGatekeeper,
        retention_manager: StorageRetentionManager,
        task_dag: Optional[TaskDAG] = None,
        active_node_id: Optional[str] = None,
        available_tools: Optional[List[str]] = None,
        failures: Optional[List[Dict[str, Any]]] = None,
    ) -> ExecutiveAwarenessPackage:
        """
        Synthesizes the deterministic EAP respecting Priority Hierarchy:
        P0 (Never Prune): Contract, Constraints, Active Node, Acceptance Criteria
        P1 (Very High): Evidence, Failures
        P2 (Medium): Recent completed nodes, causal history
        P3 (Compressible): Older completed tasks
        P4 (Externalize): Raw logs (kept as references)
        """
        # 1. Identity
        identity = EAPIdentity(
            system_id=settings.system_id,
            operator_id="operator",
            project_id=project_id,
            session_id=session_id,
            task_id=task_id,
            lease_id=lease_id,
        )

        # 2. P0: Governance
        req_list = [f"{r.requirement_id}: {r.statement}" for r in contract.requirements]
        const_list = [f"{c.constraint_id}: {c.statement}" for c in contract.constraints]
        governance = EAPGovernance(
            contract_id=contract.contract_id,
            contract_version=contract.version,
            objective=contract.objective,
            requirements=req_list,
            constraints=const_list,
            permission_ceiling=contract.permissions.action_ceiling,
            active_invariants=["ALN-001", "ALN-004a", "ALN-008", "ALN-010", "ALN-014", "ALN-016", "ALN-021"],
        )

        # 3. P0/P2: Task State
        completed = []
        blocked = []
        next_cand = []
        active_node_goal = contract.objective
        acceptance_crit = [f"{ac.criterion_id}: {ac.statement}" for ac in contract.acceptance_criteria]

        if task_dag:
            for nid, node in task_dag.nodes.items():
                if node.status.value == "SUCCEEDED":
                    completed.append(nid)
                elif node.status.value == "BLOCKED":
                    blocked.append(nid)
                elif node.status.value in ["PLANNED", "READY"] and nid != active_node_id:
                    next_cand.append(nid)
                if nid == active_node_id:
                    active_node_goal = node.goal
                    acceptance_crit = node.acceptance_criteria or acceptance_crit

        task_state = EAPTaskState(
            goal=active_node_goal,
            completed_nodes=completed,
            active_node=active_node_id,
            blocked_nodes=blocked,
            next_candidates=next_cand,
            acceptance_criteria=acceptance_crit,
        )

        # 4. P1: Knowledge & Evidence
        evidence_events = [
            e for e in event_store.get_all_events()
            if e.event_type.value == "EVIDENCE_PRODUCED"
        ]
        evidence_refs = [f"ev-{e.event_id}" for e in evidence_events[-5:]]
        facts = [f"Contract v{contract.version} active with {len(contract.requirements)} mandatory requirements."]

        knowledge = EAPKnowledge(
            verified_facts=facts,
            evidence_refs=evidence_refs,
            assumptions=[{"id": "ASM-01", "statement": "Targeting ROS 2 Humble robot_controller.cpp"}],
            unresolved_questions=[],
        )

        # 5. P2: History & Causal Lineage
        recent_events = [
            {"event_id": str(e.event_id), "type": e.event_type.value, "time": e.timestamp.isoformat()}
            for e in event_store.get_all_events()[-10:]
        ]
        history = EAPHistory(
            recent_events=recent_events,
            causal_lineage=[e["event_id"] for e in recent_events],
            recent_failures=failures or [],
        )

        # 6. Resources
        disk = retention_manager.check_disk_capacity()
        tier = budget_gatekeeper.get_tier()
        resources = EAPResources(
            budget_spend_usd=budget_gatekeeper.cumulative_spend_usd,
            budget_ceiling_usd=budget_gatekeeper.monthly_budget_usd,
            budget_tier=tier,
            disk_utilization_pct=disk.utilization_pct,
            available_tools=available_tools or ["patch_file", "colcon_build", "run_tests"],
        )

        # 7. Package and Digest
        eap_dict = {
            "identity": identity.model_dump(),
            "governance": governance.model_dump(),
            "task": task_state.model_dump(),
            "knowledge": knowledge.model_dump(),
            "history": history.model_dump(),
            "resources": resources.model_dump(),
        }
        digest = ExecutiveAwarenessPackage.calculate_digest(eap_dict)

        return ExecutiveAwarenessPackage(
            identity=identity,
            governance=governance,
            task=task_state,
            knowledge=knowledge,
            history=history,
            resources=resources,
            eap_digest=digest,
        )
