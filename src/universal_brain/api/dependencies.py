"""
Universal Brain - API Dependency Injection Container

Ensures that the API acts strictly as an adapter layer binding to existing
singleton instances of EventStore, CapabilityService, BudgetGatekeeper, etc.
Satisfies the Runtime Singleton Invariant: Never spawn an alternate authoritative Brain.
"""

from typing import Optional, Any

from universal_brain.alignment.engine import AlignmentEngine
from universal_brain.api.actions import ActionManager
from universal_brain.api.websocket import WebSocketGateway
from universal_brain.executive.budget import BudgetGatekeeper
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.event_store import EventStore
from universal_brain.memory.retention import StorageRetentionManager
from universal_brain.persistence.artifacts.store import ContentAddressedArtifactStore
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.recovery.startup import StartupRecoveryManager
from universal_brain.tools.gateway import ToolGateway
from universal_brain.tools.workers.auth import WorkerAuthService
from universal_brain.tools.workers.queue import EphemeralJobQueue


class RuntimeContainer:
    """Dependency container for authoritative runtime singletons."""

    def __init__(
        self,
        event_store: Optional[EventStore] = None,
        capability_service: Optional[CapabilityService] = None,
        budget_gatekeeper: Optional[BudgetGatekeeper] = None,
        retention_manager: Optional[StorageRetentionManager] = None,
        alignment_engine: Optional[AlignmentEngine] = None,
        action_manager: Optional[ActionManager] = None,
        ws_gateway: Optional[WebSocketGateway] = None,
        tool_gateway: Optional[ToolGateway] = None,
        job_queue: Optional[EphemeralJobQueue] = None,
        worker_auth: Optional[WorkerAuthService] = None,
        db_manager: Optional[DatabaseManager] = None,
        artifact_store: Optional[ContentAddressedArtifactStore] = None,
        intelligence_stack: Optional[Any] = None,
        engineering_stack: Optional[Any] = None,
    ) -> None:
        self.event_store = event_store or EventStore()
        self.capability_service = capability_service or CapabilityService()
        self.budget_gatekeeper = budget_gatekeeper or BudgetGatekeeper()
        self.retention_manager = retention_manager or StorageRetentionManager(critical_threshold_pct=99.9)
        self.alignment_engine = alignment_engine or AlignmentEngine()
        self.action_manager = action_manager or ActionManager(self.capability_service)
        self.ws_gateway = ws_gateway or WebSocketGateway()
        self.tool_gateway = tool_gateway or ToolGateway(
            event_store=self.event_store,
            capability_service=self.capability_service,
            budget_gatekeeper=self.budget_gatekeeper,
            retention_manager=self.retention_manager,
        )
        self.job_queue = job_queue or EphemeralJobQueue()
        self.worker_auth = worker_auth or WorkerAuthService()

        # Traceability: REQ-STA-001 (local-first canonical state) and ALN-014
        # (critical persistence/audit failures must fail closed for state changes).
        # Persistence is intentionally lazy. Importing the control-plane API must
        # not eagerly load a concrete database driver (for example asyncpg) or
        # establish persistence infrastructure before a persistence-backed route
        # is actually used. This keeps CQRS/read-only/security endpoints usable in
        # minimal runtimes and prevents an unavailable optional backend from
        # taking down the entire sovereign control plane at import time.
        self._db_manager = db_manager
        self._artifact_store = artifact_store
        self._recovery_manager = (
            StartupRecoveryManager(db_manager, self.event_store)
            if db_manager is not None
            else None
        )

        self.intelligence_stack = intelligence_stack
        self.engineering_stack = engineering_stack

    @property
    def db_manager(self) -> DatabaseManager:
        """Return the persistence manager, constructing it only on first use.

        The default manager may require a backend-specific driver such as
        ``asyncpg`` or ``aiosqlite``. Deferring construction preserves the
        Runtime Singleton Invariant without making unrelated API imports depend
        on whichever persistence backend is configured for deployment.
        """
        if self._db_manager is None:
            self._db_manager = DatabaseManager()
        return self._db_manager

    @property
    def artifact_store(self) -> ContentAddressedArtifactStore:
        """Return the content-addressed artifact store on first use."""
        if self._artifact_store is None:
            self._artifact_store = ContentAddressedArtifactStore()
        return self._artifact_store

    @property
    def recovery_manager(self) -> StartupRecoveryManager:
        """Return recovery coordination bound to the authoritative DB manager."""
        if self._recovery_manager is None:
            self._recovery_manager = StartupRecoveryManager(self.db_manager, self.event_store)
        return self._recovery_manager

    @property
    def persistence_initialized(self) -> bool:
        """Whether this container has materialized persistence infrastructure."""
        return self._db_manager is not None


# Global default container
_container = RuntimeContainer()


def get_container() -> RuntimeContainer:
    """Fetch active runtime container."""
    return _container


def set_container(container: RuntimeContainer) -> None:
    """Override container (used in integration testing)."""
    global _container
    _container = container
