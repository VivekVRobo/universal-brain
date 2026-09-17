"""Universal Brain - Persistence Repositories Package."""

from .base import BaseRepository
from .capabilities import CapabilityRepository
from .checkpoints import WorkspaceCheckpointRepository
from .contracts import ContractRepository
from .events import EventEdgeRepository, EventRepository
from .evidence import EvidenceRepository
from .executive import HandoffRepository, ModelLeaseRepository
from .lifecycle import LifecycleRepository
from .missions import (
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
from .outbox import OutboxRepository
from .projects import ProjectRepository
from .tasks import TaskRepository
from .workers import WorkerCheckpointRepository, WorkerJobRepository

from .world import (
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

__all__ = [
    "BaseRepository",
    "ProjectRepository",
    "EventRepository",
    "EventEdgeRepository",
    "ContractRepository",
    "TaskRepository",
    "EvidenceRepository",
    "CapabilityRepository",
    "ModelLeaseRepository",
    "HandoffRepository",
    "WorkerJobRepository",
    "WorkerCheckpointRepository",
    "WorkspaceCheckpointRepository",
    "OutboxRepository",
    "LifecycleRepository",
    "MissionRepository",
    "MissionPlanRepository",
    "MissionSchedulerLeaseRepository",
    "AgentCellRepository",
    "AgentLeaseRepository",
    "CommitmentRepository",
    "BlackboardRepository",
    "WakeupRepository",
    "MissionCheckpointRepository",
    "EscalationRepository",
    "LoopFingerprintRepository",
    "ObservationRepository",
    "ObservationSourceRepository",
    "WorldEntityRepository",
    "WorldAssertionRepository",
    "WorldRelationRepository",
    "WorldContradictionRepository",
    "WorldWatchRepository",
    "WorldSnapshotRepository",
    "WorldProcessorLeaseRepository",
]
