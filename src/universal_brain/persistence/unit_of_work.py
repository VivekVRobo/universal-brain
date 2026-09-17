"""
Universal Brain - Unit of Work & Transaction Boundary Manager

Implements M6 Sections 8-12 and Invariants M6-INV-01, M6-INV-02:
Coordinates atomic transaction state across aggregates, repositories, and the outbox,
enforcing the canonical transaction lifecycle: NEW -> OPEN -> PREPARING -> COMMITTED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.errors import PersistenceError
from universal_brain.persistence.repositories.capabilities import CapabilityRepository
from universal_brain.persistence.repositories.checkpoints import WorkspaceCheckpointRepository
from universal_brain.persistence.repositories.contracts import ContractRepository
from universal_brain.persistence.repositories.events import (
    EventEdgeRepository,
    EventRepository,
)
from universal_brain.persistence.repositories.evidence import EvidenceRepository
from universal_brain.persistence.repositories.executive import (
    HandoffRepository,
    ModelLeaseRepository,
)
from universal_brain.persistence.repositories.lifecycle import LifecycleRepository
from universal_brain.persistence.repositories.missions import (
    AgentCellRepository,
    AgentLeaseRepository,
    BlackboardRepository,
    CommitmentRepository,
    EscalationRepository,
    LoopFingerprintRepository,
    MissionCheckpointRepository,
    MissionPlanRepository,
    MissionRepository,
    MissionSchedulerLeaseRepository,
    WakeupRepository,
)
from universal_brain.persistence.repositories.outbox import OutboxRepository
from universal_brain.persistence.repositories.projects import ProjectRepository
from universal_brain.persistence.repositories.tasks import TaskRepository
from universal_brain.persistence.repositories.workers import (
    WorkerCheckpointRepository,
    WorkerJobRepository,
)
from universal_brain.persistence.repositories.world import (
    ObservationRepository,
    ObservationSourceRepository,
    WorldAssertionRepository,
    WorldContradictionRepository,
    WorldEntityRepository,
    WorldProcessorLeaseRepository,
    WorldRelationRepository,
    WorldSnapshotRepository,
    WorldWatchRepository,
)


class TransactionState(str, Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    PREPARING = "PREPARING"
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


@dataclass
class TransactionCommitReceipt:
    """Internal receipt produced on successful transaction commit (M6 Section 12)."""
    transaction_id: UUID
    committed_at: datetime
    events_persisted: int = 0
    outbox_staged: int = 0


class UnitOfWork:
    """Atomic transaction coordinator providing bound repository instances."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager
        self.transaction_id: UUID = uuid4()
        self.state: TransactionState = TransactionState.NEW
        self._session: Optional[AsyncSession] = None

        # Repositories (bound on enter)
        self.projects: Optional[ProjectRepository] = None
        self.events: Optional[EventRepository] = None
        self.edges: Optional[EventEdgeRepository] = None
        self.contracts: Optional[ContractRepository] = None
        self.tasks: Optional[TaskRepository] = None
        self.evidence: Optional[EvidenceRepository] = None
        self.capabilities: Optional[CapabilityRepository] = None
        self.leases: Optional[ModelLeaseRepository] = None
        self.handoffs: Optional[HandoffRepository] = None
        self.jobs: Optional[WorkerJobRepository] = None
        self.worker_checkpoints: Optional[WorkerCheckpointRepository] = None
        self.workspace_checkpoints: Optional[WorkspaceCheckpointRepository] = None
        self.outbox: Optional[OutboxRepository] = None
        self.lifecycle: Optional[LifecycleRepository] = None

        # M7 Autonomy Repositories
        self.missions: Optional[MissionRepository] = None
        self.mission_plans: Optional[MissionPlanRepository] = None
        self.scheduler_leases: Optional[MissionSchedulerLeaseRepository] = None
        self.agent_cells: Optional[AgentCellRepository] = None
        self.agent_leases: Optional[AgentLeaseRepository] = None
        self.commitments: Optional[CommitmentRepository] = None
        self.blackboard: Optional[BlackboardRepository] = None
        self.wakeups: Optional[WakeupRepository] = None
        self.mission_checkpoints: Optional[MissionCheckpointRepository] = None
        self.escalations: Optional[EscalationRepository] = None
        self.loop_fingerprints: Optional[LoopFingerprintRepository] = None

        # M8 World Model Repositories
        self.observations: Optional[ObservationRepository] = None
        self.observation_sources: Optional[ObservationSourceRepository] = None
        self.world_entities: Optional[WorldEntityRepository] = None
        self.world_assertions: Optional[WorldAssertionRepository] = None
        self.world_relations: Optional[WorldRelationRepository] = None
        self.world_contradictions: Optional[WorldContradictionRepository] = None
        self.world_watches: Optional[WorldWatchRepository] = None
        self.world_snapshots: Optional[WorldSnapshotRepository] = None
        self.world_processor_leases: Optional[WorldProcessorLeaseRepository] = None

    async def __aenter__(self) -> UnitOfWork:
        if self.state != TransactionState.NEW:
            raise PersistenceError(f"Cannot open UnitOfWork in state {self.state}")

        self._session = self.db_manager.session_factory()
        self.state = TransactionState.OPEN

        # Instantiate repositories bound to this session
        self.projects = ProjectRepository(self._session)
        self.events = EventRepository(self._session)
        self.edges = EventEdgeRepository(self._session)
        self.contracts = ContractRepository(self._session)
        self.tasks = TaskRepository(self._session)
        self.evidence = EvidenceRepository(self._session)
        self.capabilities = CapabilityRepository(self._session)
        self.leases = ModelLeaseRepository(self._session)
        self.handoffs = HandoffRepository(self._session)
        self.jobs = WorkerJobRepository(self._session)
        self.worker_checkpoints = WorkerCheckpointRepository(self._session)
        self.workspace_checkpoints = WorkspaceCheckpointRepository(self._session)
        self.outbox = OutboxRepository(self._session)
        self.lifecycle = LifecycleRepository(self._session)

        # M7 Autonomy Repositories
        self.missions = MissionRepository(self._session)
        self.mission_plans = MissionPlanRepository(self._session)
        self.scheduler_leases = MissionSchedulerLeaseRepository(self._session)
        self.agent_cells = AgentCellRepository(self._session)
        self.agent_leases = AgentLeaseRepository(self._session)
        self.commitments = CommitmentRepository(self._session)
        self.blackboard = BlackboardRepository(self._session)
        self.wakeups = WakeupRepository(self._session)
        self.mission_checkpoints = MissionCheckpointRepository(self._session)
        self.escalations = EscalationRepository(self._session)
        self.loop_fingerprints = LoopFingerprintRepository(self._session)

        # M8 World Model Repositories
        self.observations = ObservationRepository(self._session)
        self.observation_sources = ObservationSourceRepository(self._session)
        self.world_entities = WorldEntityRepository(self._session)
        self.world_assertions = WorldAssertionRepository(self._session)
        self.world_relations = WorldRelationRepository(self._session)
        self.world_contradictions = WorldContradictionRepository(self._session)
        self.world_watches = WorldWatchRepository(self._session)
        self.world_snapshots = WorldSnapshotRepository(self._session)
        self.world_processor_leases = WorldProcessorLeaseRepository(self._session)

        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
                self.state = TransactionState.FAILED
            elif self.state == TransactionState.OPEN:
                # If exited without explicit commit, rollback
                await self.rollback()
        finally:
            if self._session:
                await self._session.close()
                self._session = None

    async def commit(self) -> TransactionCommitReceipt:
        """Flushes and commits all mutations within this atomic transaction boundary."""
        if self.state != TransactionState.OPEN or not self._session:
            raise PersistenceError(f"Cannot commit UnitOfWork in state {self.state}")

        self.state = TransactionState.PREPARING
        try:
            await self._session.commit()
            self.state = TransactionState.COMMITTED
            return TransactionCommitReceipt(
                transaction_id=self.transaction_id,
                committed_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            await self.rollback()
            self.state = TransactionState.FAILED
            raise PersistenceError(f"Commit failed for transaction '{self.transaction_id}': {e}") from e

    async def rollback(self) -> None:
        """Rolls back the active transaction."""
        if self._session:
            try:
                await self._session.rollback()
            except Exception:
                pass
        self.state = TransactionState.ROLLED_BACK
