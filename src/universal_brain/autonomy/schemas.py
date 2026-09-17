"""
Universal Brain - Autonomy & Mission Control Schemas

Implements M7 Sections 7, 8, 13, 21, 22, 25, 36, 38, 51, 66, 71, 77, 86, 97:
Canonical Pydantic models for missions, plans, agent cells, leases,
commitments, blackboard records, wakeups, checkpoints, and escalations.
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
# Enums
# -----------------------------------------------------------------------------


class MissionStatus(str, Enum):
    """Lifecycle states of a Mission (M7 Section 8)."""

    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    VALIDATING = "VALIDATING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AutonomyLevel(str, Enum):
    """Autonomy bounds defining operational freedom under constitutional rules (M7 Section 97)."""

    L0_SUGGEST = "L0_SUGGEST"              # Suggest only, no autonomous action
    L1_AUTONOMOUS_A0 = "L1_AUTONOMOUS_A0"  # Autonomous observe only (A0)
    L2_AUTONOMOUS_A1 = "L2_AUTONOMOUS_A1"  # Autonomous reversible actions (A1)
    L3_PROPOSE_A2 = "L3_PROPOSE_A2"        # Propose consequential actions (A2 requires approval)


class AgentRole(str, Enum):
    """Specialized functional responsibilities for temporary agent cells (M7 Section 22)."""

    ARCHITECT = "ARCHITECT"
    RESEARCHER = "RESEARCHER"
    PLANNER = "PLANNER"
    BUILDER = "BUILDER"
    VERIFIER = "VERIFIER"
    TESTER = "TESTER"
    REVIEWER = "REVIEWER"
    OBSERVER = "OBSERVER"
    COORDINATOR = "COORDINATOR"


class AgentLeaseStatus(str, Enum):
    """Lifecycle states of an AgentLease (M7 Section 26)."""

    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    FAILED = "FAILED"
    HANDED_OFF = "HANDED_OFF"


class CommitmentStatus(str, Enum):
    """States of an explicit Agent Commitment (M7 Section 39)."""

    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class BlackboardEntryType(str, Enum):
    """Categories of structured claims on the Mission Blackboard (M7 Section 50)."""

    FACT = "FACT"
    HYPOTHESIS = "HYPOTHESIS"
    DECISION = "DECISION"
    QUESTION = "QUESTION"
    ARTIFACT = "ARTIFACT"
    DEPENDENCY = "DEPENDENCY"
    RISK = "RISK"


class BlackboardStatus(str, Enum):
    """Lifecycle states of a blackboard claim (M7 Section 52)."""

    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    CONFLICTED = "CONFLICTED"


class WakeupType(str, Enum):
    """Triggers for waking up long-horizon missions (M7 Section 65)."""

    TIME = "TIME"
    EVENT = "EVENT"
    WORKER = "WORKER"
    OPERATOR = "OPERATOR"
    RESOURCE = "RESOURCE"
    DEPENDENCY = "DEPENDENCY"
    EXTERNAL_SIGNAL = "EXTERNAL_SIGNAL"


class WakeupStatus(str, Enum):
    """Lifecycle states of a durable wakeup timer (M7 Section 68)."""

    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    FIRED = "FIRED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class EscalationStatus(str, Enum):
    """Lifecycle states of an operator escalation (M7 Section 78)."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class DependencyStatus(str, Enum):
    """States of a mission dependency (M7 Section 60)."""

    UNRESOLVED = "UNRESOLVED"
    WAITING = "WAITING"
    SATISFIED = "SATISFIED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MissionHealth(str, Enum):
    """Derived operational health of a mission (M7 Section 109)."""

    HEALTHY = "HEALTHY"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class MissionBudgetState(str, Enum):
    """Spending tiers for mission budgets (M7 Section 92)."""

    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    CONSERVE = "CONSERVE"
    CRITICAL = "CRITICAL"
    EXHAUSTED = "EXHAUSTED"


# -----------------------------------------------------------------------------
# Canonical Models
# -----------------------------------------------------------------------------


class Mission(BaseModel):
    """Canonical, durable mission representing long-horizon objectives (M7 Section 7)."""

    mission_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    title: str
    goal: str
    description: str = ""

    contract_id: UUID
    contract_version: int = 1

    priority: int = Field(50, ge=0, le=100)
    risk_class: str = "STANDARD"
    maximum_action_class: ActionClass = ActionClass.A1
    maximum_autonomy_level: AutonomyLevel = AutonomyLevel.L2_AUTONOMOUS_A1

    status: MissionStatus = MissionStatus.DRAFT

    created_by: str = "operator"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    deadline: Optional[datetime] = None
    time_horizon: Optional[str] = None
    budget_ceiling: float = 100.0
    budget_spent: float = 0.0

    completion_criteria: List[Dict[str, Any]] = Field(default_factory=list)
    failure_criteria: List[Dict[str, Any]] = Field(default_factory=list)

    current_plan_id: Optional[UUID] = None
    current_plan_version: int = 0

    mission_version: int = 1
    kernel_epoch_created: int = 1


class MissionPlan(BaseModel):
    """Canonical plan version for a mission (M7 Section 13)."""

    plan_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    plan_version: int = 1

    task_dag_id: Optional[UUID] = None
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    risks: List[Dict[str, Any]] = Field(default_factory=list)
    external_dependencies: List[Dict[str, Any]] = Field(default_factory=list)

    resource_estimates: Dict[str, Any] = Field(default_factory=dict)
    budget_estimate: float = 0.0
    milestones: List[Dict[str, Any]] = Field(default_factory=list)
    replan_triggers: List[str] = Field(default_factory=list)

    created_by: str = "planner"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    plan_digest: str = ""

    def calculate_digest(self) -> str:
        """Calculates deterministic SHA-256 digest over canonical plan state."""
        payload = {
            "mission_id": str(self.mission_id),
            "plan_version": self.plan_version,
            "task_dag_id": str(self.task_dag_id) if self.task_dag_id else None,
            "budget_estimate": float(self.budget_estimate),
            "milestones": self.milestones,
            "replan_triggers": sorted(self.replan_triggers),
        }
        json_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()


class AgentCell(BaseModel):
    """Ephemeral cognitive cell assigned to execute scoped tasks (M7 Section 21)."""

    agent_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    role: AgentRole
    status: str = "IDLE"  # IDLE | ACTIVE | FENCED | TERMINATED

    assigned_task_ids: List[UUID] = Field(default_factory=list)
    agent_version: int = 1

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    current_lease_id: Optional[UUID] = None


class AgentLease(BaseModel):
    """Bounded execution authority for an Agent Cell (M7 Section 25)."""

    lease_id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    mission_id: UUID
    task_scope: List[UUID] = Field(default_factory=list)

    lease_generation: int = 1
    kernel_epoch: int = 1

    granted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime

    capability_ceiling: ActionClass = ActionClass.A1
    tool_scope: List[str] = Field(default_factory=list)

    max_turns: int = 20
    turns_used: int = 0

    max_spend: float = 10.0
    spend_used: float = 0.0

    status: AgentLeaseStatus = AgentLeaseStatus.ACTIVE


class MissionSchedulerLease(BaseModel):
    """Fenced single-writer lease for authoritative mission scheduling (M7 Section 19)."""

    lease_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    scheduler_instance_id: str
    kernel_epoch: int = 1
    lease_generation: int = 1
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    heartbeat: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResourceLease(BaseModel):
    """Lease for scarce or exclusive hardware/environment resources (M7 Section 36)."""

    resource_lease_id: UUID = Field(default_factory=uuid4)
    resource_id: str
    resource_type: str  # WORKSPACE | GPU | WORKER_SLOT | HARDWARE
    mission_id: UUID
    task_id: Optional[UUID] = None
    lease_generation: int = 1
    kernel_epoch: int = 1
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    status: str = "ACTIVE"


class Commitment(BaseModel):
    """Explicit accountability commitment from an Agent Cell (M7 Section 38)."""

    commitment_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    task_id: UUID
    agent_id: UUID

    statement: str
    expected_evidence: str

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    status: CommitmentStatus = CommitmentStatus.OPEN


class BlackboardEntry(BaseModel):
    """Structured shared canonical assertion on the Mission Blackboard (M7 Section 51)."""

    entry_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    entry_type: BlackboardEntryType
    statement: str

    source_agent_id: UUID
    source_event_id: Optional[UUID] = None
    evidence_refs: List[str] = Field(default_factory=list)

    status: BlackboardStatus = BlackboardStatus.PROPOSED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entry_version: int = 1


class ConflictRecord(BaseModel):
    """Formally registered contradiction between blackboard claims (M7 Section 55)."""

    conflict_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    entry_ids: List[UUID]
    severity: str = "HIGH"  # LOW | MEDIUM | HIGH
    affected_tasks: List[UUID] = Field(default_factory=list)
    resolution_status: str = "UNRESOLVED"  # UNRESOLVED | IN_VERIFICATION | RESOLVED
    resolution_details: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WakeupRecord(BaseModel):
    """Persistent, crash-resilient timer or external trigger wakeup (M7 Section 66)."""

    wakeup_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    task_id: Optional[UUID] = None
    trigger_type: WakeupType
    trigger_condition: Dict[str, Any] = Field(default_factory=dict)
    due_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    fired_at: Optional[datetime] = None
    status: WakeupStatus = WakeupStatus.PENDING
    idempotency_key: str = ""


class Observation(BaseModel):
    """External world observation with explicit freshness boundary (M7 Section 71)."""

    observation_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    source: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: Optional[datetime] = None
    facts: List[Dict[str, Any]] = Field(default_factory=list)
    uncertainties: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    payload_digest: str = ""


class EscalationRecord(BaseModel):
    """Structured operator escalation envelope (M7 Section 77)."""

    escalation_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    severity: str = "HIGH"  # LOW | MEDIUM | CRITICAL
    reason: str
    required_operator_action: str
    evidence_refs: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    status: EscalationStatus = EscalationStatus.OPEN


class MissionCheckpoint(BaseModel):
    """Canonical logical recovery summary of long-horizon mission state (M7 Section 86)."""

    checkpoint_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    mission_version: int
    plan_id: Optional[UUID] = None
    plan_version: int = 1

    completed_criteria: List[str] = Field(default_factory=list)
    task_state_digest: str = ""
    progress_digest: str = ""
    blackboard_digest: str = ""
    commitment_digest: str = ""
    dependency_digest: str = ""

    budget_state: MissionBudgetState = MissionBudgetState.NORMAL
    open_escalations: int = 0
    open_wakeups: int = 0

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    checkpoint_digest: str = ""

    def calculate_digest(self) -> str:
        """Calculates deterministic SHA-256 digest over canonical checkpoint state."""
        payload = {
            "mission_id": str(self.mission_id),
            "mission_version": self.mission_version,
            "plan_version": self.plan_version,
            "completed_criteria": sorted(self.completed_criteria),
            "task_state_digest": self.task_state_digest,
            "progress_digest": self.progress_digest,
            "blackboard_digest": self.blackboard_digest,
            "commitment_digest": self.commitment_digest,
        }
        json_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()
