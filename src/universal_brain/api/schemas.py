"""
Universal Brain - API Request & Response Schemas

Pydantic v2 schemas defining CQRS Read Models and Command payloads
for the Operator Console and API Gateway.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from universal_brain.executive.budget import BudgetTier
from universal_brain.kernel.events import ActionClass, EventType, RelationType


# -----------------------------------------------------------------------------
# 1. CQRS Read Models (Query Side)
# -----------------------------------------------------------------------------


class RuntimeHealthResponse(BaseModel):
    """Aggregate runtime node health and capacity status."""

    node_id: str
    status: str  # HEALTHY | DEGRADED | CRITICAL
    disk_utilization_pct: float
    is_disk_warning: bool
    is_disk_critical: bool
    budget_spend_usd: float
    monthly_budget_usd: float
    budget_tier: BudgetTier
    active_model_lease: Optional[str] = None
    lease_expires_in_seconds: Optional[int] = None
    active_actions_count: int
    contract_version: Optional[int] = None
    system_mode: str  # LIVE | LOCAL | DEMO


class ProjectSummaryResponse(BaseModel):
    """Active project overview."""

    project_id: UUID
    title: str
    status: str
    current_contract_version: Optional[int] = None
    created_at: datetime
    active_tasks_count: Optional[int] = None
    pending_actions_count: int


class EventItemResponse(BaseModel):
    """Single event item in event list query."""

    event_id: UUID
    timestamp: datetime
    event_type: EventType
    actor_id: str
    project_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    contract_version: Optional[int] = None
    payload: Dict[str, Any]
    prev_event_hash: str
    event_hash: str


class EventListResponse(BaseModel):
    """Paginated event response."""

    events: List[EventItemResponse]
    total_count: int
    page: int
    page_size: int


class CausalGraphNode(BaseModel):
    """Node in the Total Awareness Causal DAG."""

    id: str
    label: str
    event_type: EventType
    actor_id: str
    timestamp: datetime
    event_hash: str
    payload_summary: str
    has_evidence: bool = False


class CausalGraphEdge(BaseModel):
    """Edge in the Total Awareness Causal DAG."""

    source: str
    target: str
    relation_type: RelationType


class CausalGraphResponse(BaseModel):
    """Graph response for visual DAG explorer."""

    nodes: List[CausalGraphNode]
    edges: List[CausalGraphEdge]
    root_cause_event_ids: List[str]


class ContractDiffItem(BaseModel):
    """Semantic diff entry between two contract versions."""

    diff_type: str  # ADDED | REMOVED | MODIFIED
    category: str   # REQUIREMENT | CONSTRAINT | CAPABILITY | AMBIGUITY
    item_id: str
    summary: str


class ContractDetailResponse(BaseModel):
    """Detailed contract view."""

    contract_id: UUID
    version: int
    status: str
    objective: str
    requirements_count: int
    constraints_count: int
    permissions_ceiling: ActionClass
    created_at: datetime
    semantic_diffs: List[ContractDiffItem] = Field(default_factory=list)


class InvariantItem(BaseModel):
    """Status evaluation of an individual alignment invariant."""

    invariant_id: str
    name: str
    description: str
    status: str  # PASS | WARN | FAIL | UNKNOWN
    proofs_count: int
    last_evaluated_at: datetime


class InvariantLedgerResponse(BaseModel):
    """Matrix of all ALN-001 through ALN-021 invariants."""

    invariants: List[InvariantItem]
    pass_count: int
    warn_count: int
    fail_count: int
    unknown_count: int = 0


class ActionProposalResponse(BaseModel):
    """Consequential A2 action proposal record."""

    action_id: UUID
    proposal_version: int
    project_id: UUID
    task_id: UUID
    action_type: str
    target_resource: str
    requested_effect: str
    action_class: ActionClass
    status: str
    preflight_reversibility: str  # VERIFIED_REVERSIBLE | PARTIALLY_REVERSIBLE | IRREVERSIBLE | UNKNOWN
    diff_preview: str
    rollback_procedure: str
    evidence_items_count: int
    payload_hash: str
    authorization_digest: str
    created_at: datetime
    expires_at: datetime
    seconds_remaining: int


class IntelligenceModelStatusResponse(BaseModel):
    """Model identity summary exposed to the Operator Console."""

    model_key: str
    display_name: str
    vendor: str
    family: str
    enabled: bool
    context_window: int
    route_count: int
    empirical_score: float
    evaluation_samples: int
    drift_alert: bool
    capability_evidence_samples: int = 0
    effective_capabilities: Dict[str, float] = Field(default_factory=dict)


class IntelligenceRouteStatusResponse(BaseModel):
    """Access-route health, quota, privacy and operational telemetry."""

    route_id: str
    model_key: str
    transport: str
    enabled: bool
    health: str
    retention_policy: str
    max_sensitivity: str
    cost_per_million_input: float
    cost_per_million_output: float
    quota: Dict[str, Any]
    telemetry: Dict[str, Any]
    active_conversations: int
    recovery_candidates: int = 0


class IntelligenceStatusResponse(BaseModel):
    """Non-authoritative Intelligence Fabric observability snapshot."""

    configured: bool
    model_count: int = 0
    route_count: int = 0
    healthy_routes: int = 0
    degraded_routes: int = 0
    unavailable_routes: int = 0
    active_conversations: int = 0
    models: List[IntelligenceModelStatusResponse] = Field(default_factory=list)
    routes: List[IntelligenceRouteStatusResponse] = Field(default_factory=list)
    recent_invocations: List[Dict[str, Any]] = Field(default_factory=list)
    note: Optional[str] = None


class EngineeringWorktreeStatusResponse(BaseModel):
    requirement_ref: str
    branch: str
    path: str
    node_count: int
    verified_commit: Optional[str] = None
    integrated_commit: Optional[str] = None


class EngineeringLeaseStatusResponse(BaseModel):
    task_id: str
    worker_id: str
    workspace_id: str
    generation: int
    expires_at: str


class EngineeringServiceStatusResponse(BaseModel):
    name: str
    service_id: str
    state: str
    pid: Optional[int] = None
    cwd: str


class EngineeringStatusResponse(BaseModel):
    configured: bool = False
    repository_root: str = ""
    symbol_count: int = 0
    reference_count: int = 0
    indexed_files: int = 0
    active_worktrees: List[EngineeringWorktreeStatusResponse] = Field(default_factory=list)
    durable_worker_leases: List[EngineeringLeaseStatusResponse] = Field(default_factory=list)
    repository_count: int = 0
    cross_repo_dependency_edges: int = 0
    services: List[EngineeringServiceStatusResponse] = Field(default_factory=list)
    semantic_backends: List[str] = Field(default_factory=list)
    isolation_provider: Optional[str] = None
    note: Optional[str] = None


# -----------------------------------------------------------------------------
# 2. CQRS Command Models (Command Side)
# -----------------------------------------------------------------------------


class SubmitCommandRequest(BaseModel):
    """Operator prompt submission."""

    project_id: Optional[UUID] = None
    prompt: str = Field(..., min_length=1)


class ActionApproveRequest(BaseModel):
    """Operator approval of a pending consequential action."""

    operator_id: str = Field(..., min_length=1)
    action_id: UUID
    proposal_version: int
    authorization_digest: str
    nonce: str
    approved_at: Optional[datetime] = None


class ActionRejectRequest(BaseModel):
    """Operator rejection of an unexecuted proposal."""

    operator_id: str = Field(..., min_length=1)
    action_id: UUID
    proposal_version: int
    reason: str = Field(..., min_length=1)


class ActionCancelRequest(BaseModel):
    """Cancellation of an action before execution."""

    operator_id: str = Field(..., min_length=1)
    action_id: UUID
    reason: str


class ActionRollbackRequest(BaseModel):
    """Explicit request to reverse an already executed/failed action."""

    operator_id: str = Field(..., min_length=1)
    action_id: UUID
    reason: str = Field(..., min_length=1)


# -----------------------------------------------------------------------------
# 3. Realtime WebSocket Envelope
# -----------------------------------------------------------------------------


class WebSocketEnvelope(BaseModel):
    """Durable sequence message envelope on /ws/stream."""

    stream_id: str
    sequence: int
    event_id: UUID
    occurred_at: datetime
    entity_version: int
    channel: str  # runtime | tasks | events | actions | telemetry | governance
    event_type: str
    payload: Dict[str, Any]
