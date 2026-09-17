"""
Universal Brain - API Dependency Injection Container

Ensures that the API acts strictly as an adapter layer binding to existing
singleton instances of EventStore, CapabilityService, BudgetGatekeeper, etc.
Satisfies the Runtime Singleton Invariant: Never spawn an alternate authoritative Brain.
"""

from typing import Optional, Any

from universal_brain.alignment.engine import AlignmentEngine
from universal_brain.config import settings
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
        self.event_store = event_store or EventStore.durable(
            settings.canonical_event_journal_path
        )
        self.capability_service = capability_service or CapabilityService()
        self.budget_gatekeeper = budget_gatekeeper or BudgetGatekeeper()
        self.retention_manager = retention_manager or StorageRetentionManager(critical_threshold_pct=99.9)
        self.alignment_engine = alignment_engine or AlignmentEngine()
        self.action_manager = action_manager or ActionManager(
            self.capability_service,
            event_store=self.event_store,
        )
        self.ws_gateway = ws_gateway or WebSocketGateway()
        self.tool_gateway = tool_gateway or ToolGateway(
            event_store=self.event_store,
            capability_service=self.capability_service,
            budget_gatekeeper=self.budget_gatekeeper,
            retention_manager=self.retention_manager,
        )
        self.job_queue = job_queue or EphemeralJobQueue(event_store=self.event_store)
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
        self._recovery_completed = settings.app_env not in {"production", "staging"}
        self._recovery_report: Optional[dict[str, Any]] = None

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

    def rehydrate_runtime_projections(self) -> None:
        """Replay all runtime projections after canonical history changes."""
        self.action_manager.rehydrate_from_events()
        self.job_queue.rehydrate_from_events()

    def mark_recovery_complete(self, report: dict[str, Any]) -> None:
        self.job_queue.kernel_epoch = int(report.get("kernel_epoch", 1))
        self.rehydrate_runtime_projections()
        self._recovery_completed = report.get("system_status") == "READY"
        self._recovery_report = dict(report)

    @property
    def recovery_completed(self) -> bool:
        return self._recovery_completed

    @property
    def canonical_state_ready(self) -> bool:
        """Whether state-changing runtime work has a durable recovered authority."""
        if not self.event_store.is_durable:
            return False
        if settings.app_env in {"production", "staging"}:
            return self._recovery_completed
        return True

    @property
    def persistence_initialized(self) -> bool:
        """Whether the SQL projection manager has been materialized."""
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
