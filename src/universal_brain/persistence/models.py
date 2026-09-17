"""
Universal Brain - Unified Persistence Models

Implements M6 Sections 12, 16, 25, 26, 29, 31, 33, 37, 41, 44, 53, 76, 80:
SQLAlchemy 2.0 ORM models covering all canonical state aggregates with
backend portability (supporting both PostgreSQL 16+ and SQLite WAL).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID as PyUUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator


# -----------------------------------------------------------------------------
# Portable JSON & UUID Types
# -----------------------------------------------------------------------------


class PortableUUID(TypeDecorator):
    """Stores UUIDs as native PostgreSQL UUID or 36-character String in SQLite."""
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value: Any, dialect: Any) -> Optional[PyUUID]:
        if value is None:
            return None
        if isinstance(value, PyUUID):
            return value
        return PyUUID(value)


class PortableDateTime(TypeDecorator):
    """Stores timezone-aware datetimes and guarantees UTC tzinfo on retrieval across SQLite & Postgres."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        return value

    def process_result_value(self, value: Any, dialect: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        return value


class Base(DeclarativeBase):
    """Base declarative class for all persistence models."""
    pass


# -----------------------------------------------------------------------------
# 1. Projects & Lifecycle
# -----------------------------------------------------------------------------


class ProjectORM(Base):
    __tablename__ = "projects"

    project_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    current_contract_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class KernelLifecycleORM(Base):
    """Tracks active kernel instance leases, epochs, and unclean shutdowns (M6 Section 76)."""
    __tablename__ = "kernel_lifecycle"

    instance_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kernel_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="STARTED")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    shutdown_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# -----------------------------------------------------------------------------
# 2. Event Ledger & Causal Graph (ALN-016, ALN-021)
# -----------------------------------------------------------------------------


class EventORM(Base):
    __tablename__ = "events"

    event_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    project_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True, index=True)
    task_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True, index=True)
    contract_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    prev_event_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("sequence", name="uq_events_sequence"),
        Index("ix_events_event_hash", "event_hash"),
        Index("ix_events_prev_hash", "prev_event_hash"),
    )


class EventEdgeORM(Base):
    __tablename__ = "event_edges"

    edge_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    source_event_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    target_event_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("source_event_id", "target_event_id", name="uq_event_edges_pair"),
    )


# -----------------------------------------------------------------------------
# 3. Alignment Contracts (Immutable Versioning)
# -----------------------------------------------------------------------------


class AlignmentContractORM(Base):
    __tablename__ = "alignment_contracts"

    contract_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    project_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="DRAFT")
    contract_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    contract_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_contracts_project_version"),
    )


class ActiveContractPointerORM(Base):
    """Authoritative active contract pointer for a project (M6 Section 27)."""
    __tablename__ = "active_contract_pointers"

    project_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    active_contract_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False)
    active_version: Mapped[int] = mapped_column(Integer, nullable=False)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


# -----------------------------------------------------------------------------
# 4. Tasks & Dependencies (Optimistic Concurrency)
# -----------------------------------------------------------------------------


class TaskORM(Base):
    __tablename__ = "tasks"

    task_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    project_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    dag_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action_class: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PLANNED", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    task_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("dag_id", "node_id", name="uq_tasks_dag_node"),
    )


class TaskDependencyORM(Base):
    __tablename__ = "task_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dag_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    task_node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    depends_on_node_id: Mapped[str] = mapped_column(String(128), nullable=False)


# -----------------------------------------------------------------------------
# 5. Evidence & Capabilities
# -----------------------------------------------------------------------------


class EvidenceORM(Base):
    __tablename__ = "evidence"

    evidence_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    task_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    event_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True, index=True)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    digest: Mapped[str] = mapped_column(CHAR(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    artifact_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(50), nullable=False, default="UNVERIFIED")
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class CapabilityGrantORM(Base):
    __tablename__ = "capability_grants"

    token_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    project_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    task_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    action_class: Mapped[str] = mapped_column(String(10), nullable=False)
    target_resource: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_operations: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    signature: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="ACTIVE")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# -----------------------------------------------------------------------------
# 6. Executive State (Model Leases & Handoffs)
# -----------------------------------------------------------------------------


class ModelLeaseORM(Base):
    __tablename__ = "model_leases"

    lease_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    project_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    task_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="ACTIVE")
    kernel_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class HandoffSnapshotORM(Base):
    __tablename__ = "handoff_snapshots"

    snapshot_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    project_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    task_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    task_version: Mapped[int] = mapped_column(Integer, nullable=False)
    outgoing_model: Mapped[str] = mapped_column(String(128), nullable=False)
    incoming_model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="SNAPSHOT_VERIFIED")
    state_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


# -----------------------------------------------------------------------------
# 7. M5 Workers & Checkpoints
# -----------------------------------------------------------------------------


class WorkerJobORM(Base):
    __tablename__ = "worker_jobs"

    job_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    project_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    task_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="QUEUED", index=True)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kernel_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    completion_evidence: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkerCheckpointORM(Base):
    __tablename__ = "worker_checkpoints"

    checkpoint_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    job_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    progress_pct: Mapped[float] = mapped_column(Float, nullable=False)
    state_artifact_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    artifact_digest: Mapped[Optional[str]] = mapped_column(CHAR(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_worker_checkpoint_seq"),
    )


class WorkspaceCheckpointORM(Base):
    __tablename__ = "workspace_checkpoints"

    checkpoint_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    workspace_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    task_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    checkpoint_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    reversibility_class: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="READY")
    targets: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    pre_hashes: Mapped[Dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    expected_post_hashes: Mapped[Dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


# -----------------------------------------------------------------------------
# 8. Transactional Outbox (At-Least-Once Delivery)
# -----------------------------------------------------------------------------


class OutboxRecordORM(Base):
    __tablename__ = "outbox"

    outbox_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    event_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# -----------------------------------------------------------------------------
# 9. Derived Semantic Embeddings (Rebuildable)
# -----------------------------------------------------------------------------


class SemanticEmbeddingORM(Base):
    __tablename__ = "semantic_embeddings"

    embedding_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_vector: Mapped[List[float]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


# -----------------------------------------------------------------------------
# 10. M7 Autonomy Fabric & Long-Horizon Missions (M7 Section 115)
# -----------------------------------------------------------------------------


class MissionORM(Base):
    """Canonical durable mission model (M7 Section 7)."""
    __tablename__ = "missions"

    mission_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    project_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    contract_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50, index=True)
    risk_class: Mapped[str] = mapped_column(String(64), nullable=False, default="STANDARD")
    maximum_action_class: Mapped[str] = mapped_column(String(16), nullable=False, default="A1")
    maximum_autonomy_level: Mapped[str] = mapped_column(String(32), nullable=False, default="L2_AUTONOMOUS_A1")

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT", index=True)

    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="operator")
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    deadline: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    time_horizon: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    budget_ceiling: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    budget_spent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    completion_criteria: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    failure_criteria: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    current_plan_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True)
    current_plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    mission_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    kernel_epoch_created: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class MissionPlanORM(Base):
    """Immutable mission plan versions (M7 Section 13)."""
    __tablename__ = "mission_plans"

    plan_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    mission_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    task_dag_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True)

    assumptions: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    risks: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    external_dependencies: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    resource_estimates: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    budget_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    milestones: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    replan_triggers: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)

    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="planner")
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    plan_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    __table_args__ = (UniqueConstraint("mission_id", "plan_version", name="uq_mission_plan_version"),)


class MissionSchedulerLeaseORM(Base):
    """Epoch-fenced authoritative mission scheduler lease (M7 Section 19)."""
    __tablename__ = "mission_scheduler_leases"

    lease_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    mission_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    scheduler_instance_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kernel_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    acquired_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False)
    heartbeat: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class AgentCellORM(Base):
    """Temporary cognitive worker cell (M7 Section 21)."""
    __tablename__ = "agent_cells"

    agent_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    mission_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="IDLE")
    assigned_task_ids: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    agent_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    current_lease_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True)


class AgentLeaseORM(Base):
    """Bounded, fenced lease for an Agent Cell (M7 Section 25)."""
    __tablename__ = "agent_leases"

    lease_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    agent_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("agent_cells.agent_id", ondelete="CASCADE"), nullable=False, index=True
    )
    mission_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_scope: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    kernel_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    granted_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False)

    capability_ceiling: Mapped[str] = mapped_column(String(16), nullable=False, default="A1")
    tool_scope: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)

    max_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    turns_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_spend: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    spend_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)


class ResourceLeaseORM(Base):
    """Scarce environment/hardware resource lease (M7 Section 36)."""
    __tablename__ = "resource_leases"

    resource_lease_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    mission_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    kernel_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    acquired_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)


class MissionCommitmentORM(Base):
    """Explicit accountability commitment from an Agent Cell (M7 Section 38)."""
    __tablename__ = "mission_commitments"

    commitment_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    mission_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    agent_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("agent_cells.agent_id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    expected_evidence: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN", index=True)


class BlackboardEntryORM(Base):
    """Structured shared canonical assertion on Mission Blackboard (M7 Section 51)."""
    __tablename__ = "blackboard_entries"

    entry_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    mission_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    source_agent_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False)
    source_event_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True)
    evidence_refs: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PROPOSED", index=True)
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    entry_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WakeupRecordORM(Base):
    """Persistent, crash-resilient timer or external trigger wakeup (M7 Section 66)."""
    __tablename__ = "wakeup_records"

    wakeup_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    mission_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_condition: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    due_at: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    fired_at: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")


class MissionCheckpointORM(Base):
    """Canonical logical recovery summary of mission state (M7 Section 86)."""
    __tablename__ = "mission_checkpoints"

    checkpoint_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    mission_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False, index=True
    )
    mission_version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    completed_criteria: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    task_state_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False, default="")
    progress_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False, default="")
    blackboard_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False, default="")
    commitment_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False, default="")
    dependency_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False, default="")

    budget_state: Mapped[str] = mapped_column(String(32), nullable=False, default="NORMAL")
    open_escalations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_wakeups: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    checkpoint_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class EscalationORM(Base):
    """Structured operator escalation envelope (M7 Section 77)."""
    __tablename__ = "escalations"

    escalation_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    mission_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False, index=True
    )
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="HIGH")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    required_operator_action: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN", index=True)


class LoopFingerprintORM(Base):
    """Persisted operation loop fingerprint tracking (M7 Section 48)."""
    __tablename__ = "loop_fingerprints"

    fingerprint_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    mission_id: Mapped[PyUUID] = mapped_column(
        PortableUUID, ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    fingerprint_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


# =============================================================================
# Milestone M8: World Model, Perception & Situational Awareness ORM Models
# =============================================================================


class ObservationSourceORM(Base):
    """Registered observation source (M8 Section 12)."""
    __tablename__ = "observation_sources"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(64), nullable=False)
    trust_class: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    allowed_types: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    allowed_entity_scopes: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    freshness_policy: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    authentication_token: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    registered_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    health: Mapped[str] = mapped_column(String(32), nullable=False, default="HEALTHY")
    source_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SourceSessionORM(Base):
    """Epoch-fenced source runtime session (M8 Section 13)."""
    __tablename__ = "source_sessions"

    source_session_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("observation_sources.source_id", ondelete="CASCADE"), nullable=False, index=True
    )
    kernel_epoch: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    credential_binding: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)


class ObservationORM(Base):
    """Canonical immutable observation record (M8 Section 8)."""
    __tablename__ = "world_observations"

    observation_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_session_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    source_observation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    observation_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    subject_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    property_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    coordinate_frame: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False)
    valid_until: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    uncertainty: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    quality_flags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    privacy_class: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    environment_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="REAL")
    raw_payload_ref: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    raw_payload_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False, default="")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ontology_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    observation_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False, default="")


class WorldEntityORM(Base):
    """Durable tracked world entity (M8 Section 27)."""
    __tablename__ = "world_entities"

    entity_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(String(128), nullable=False)
    identity_attributes: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    privacy_class: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    retired_at: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    entity_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ontology_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    merged_into: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class EntityAliasORM(Base):
    """Entity alias linkage (M8 Section 28)."""
    __tablename__ = "world_entity_aliases"

    alias_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    alias: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("world_entities.entity_id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class EntityResolutionHistoryORM(Base):
    """Lineage of merges and splits (M8 Sections 31-32)."""
    __tablename__ = "entity_resolution_history"

    history_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)  # MERGED, SPLIT
    source_entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_entity_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    evidence_refs: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    occurred_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class WorldPropertyAssertionORM(Base):
    """Bitemporal world property assertion (M8 Section 33)."""
    __tablename__ = "world_property_assertions"

    assertion_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("world_entities.entity_id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    coordinate_frame: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    state_class: Mapped[str] = mapped_column(String(32), nullable=False, default="OBSERVED", index=True)
    valid_from: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False, index=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    transaction_from: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    transaction_until: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    uncertainty: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    supporting_observations: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    contradicting_observations: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    freshness_status: Mapped[str] = mapped_column(String(32), nullable=False, default="FRESH", index=True)
    fusion_policy_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    inference_rule_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ontology_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    privacy_class: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    assertion_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WorldRelationORM(Base):
    """Directed temporal entity relationship (M8 Section 45)."""
    __tablename__ = "world_relations"

    relation_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    source_entity: Mapped[str] = mapped_column(
        String(64), ForeignKey("world_entities.entity_id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_entity: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    valid_from: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False, index=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    transaction_from: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    transaction_until: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    state_class: Mapped[str] = mapped_column(String(32), nullable=False, default="OBSERVED")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    uncertainty: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    evidence_refs: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    relation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ontology_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)


class WorldContradictionORM(Base):
    """Tracked contradiction envelope (M8 Section 69)."""
    __tablename__ = "world_contradictions"

    contradiction_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("world_entities.entity_id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    assertion_ids: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    temporal_overlap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="HIGH")
    detected_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN", index=True)
    resolution_evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    winning_assertion_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True)


class WorldEventORM(Base):
    """Normalized environmental change event (M8 Section 79)."""
    __tablename__ = "world_events"

    world_event_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    property_key: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    significance: Mapped[str] = mapped_column(String(32), nullable=False, default="NORMAL")
    observed_at: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    evidence_refs: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)


class WorldSnapshotORM(Base):
    """Point-in-time consistency snapshot envelope (M8 Section 87)."""
    __tablename__ = "world_snapshots"

    snapshot_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="GLOBAL")
    observation_head: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processor_cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entity_versions: Mapped[Dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    assertion_versions: Mapped[Dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    relation_versions: Mapped[Dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    ontology_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fusion_policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    snapshot_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False, default="")


class WorldWatchORM(Base):
    """Persistent reactive condition record (M8 Section 80)."""
    __tablename__ = "world_watches"

    watch_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    mission_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    task_id: Mapped[Optional[PyUUID]] = mapped_column(PortableUUID, nullable=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    property_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expected_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    operator: Mapped[str] = mapped_column(String(16), nullable=False, default="==")
    required_freshness: Mapped[str] = mapped_column(String(32), nullable=False, default="FRESH")
    required_state_class: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    debounce_sec: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(PortableDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    watch_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WorldSubscriptionORM(Base):
    """Targeted mission-to-world subscription (M8 Section 84)."""
    __tablename__ = "world_subscriptions"

    subscription_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    mission_id: Mapped[PyUUID] = mapped_column(PortableUUID, nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    property_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class WorldProcessorLeaseORM(Base):
    """Authoritative world processor generation lease (M8 Section 56)."""
    __tablename__ = "world_processor_leases"

    lease_id: Mapped[PyUUID] = mapped_column(PortableUUID, primary_key=True)
    partition_key: Mapped[str] = mapped_column(String(64), nullable=False, default="DEFAULT", unique=True, index=True)
    processor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    kernel_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        PortableDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(PortableDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
