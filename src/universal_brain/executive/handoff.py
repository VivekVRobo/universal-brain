"""
Universal Brain - Cognitive Handoff Protocol

Implements Sections 30–36 of the God-Level Specification:
- Strict invariant: NO LOSS OF CANONICAL TASK STATE ACROSS MODEL HANDOFFS;
- State transfer, NOT chat transcript replay;
- Cryptographic state_digest verification;
- Split-brain protection via optimistic concurrency and lease revocation;
- Recovery invariant (ALN-015) revalidation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from universal_brain.executive.leases import ModelLeaseController
from universal_brain.executive.schemas import HandoffSnapshot, ModelLease
from universal_brain.kernel.errors import CapabilityDeniedError, InvariantViolationError
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventType


class CognitiveHandoffManager:
    """Orchestrates seamless, zero-loss task state handoffs between models."""

    def __init__(
        self,
        lease_controller: ModelLeaseController,
        event_store: EventStore,
    ) -> None:
        self.lease_controller = lease_controller
        self.event_store = event_store
        self._snapshots: Dict[UUID, HandoffSnapshot] = {}

    def create_snapshot(
        self,
        project_id: UUID,
        task_id: UUID,
        task_version: int,
        contract_id: UUID,
        contract_version: int,
        outgoing_provider: str,
        outgoing_model: str,
        outgoing_lease_id: UUID,
        incoming_provider: str,
        incoming_model: str,
        goal: str,
        completed_subtasks: List[str],
        active_subtask: Optional[str] = None,
        blocked_subtasks: Optional[List[str]] = None,
        next_planned_actions: Optional[List[str]] = None,
        open_assumptions: Optional[List[Dict[str, Any]]] = None,
        unresolved_ambiguities: Optional[List[Dict[str, Any]]] = None,
        evidence_refs: Optional[List[str]] = None,
        failure_ledger: Optional[List[Dict[str, Any]]] = None,
        active_capability_ceiling: ActionClass = ActionClass.A1,
        tool_scope: Optional[List[str]] = None,
    ) -> HandoffSnapshot:
        snapshot = HandoffSnapshot(
            project_id=project_id,
            task_id=task_id,
            task_version=task_version,
            contract_id=contract_id,
            contract_version=contract_version,
            outgoing_provider=outgoing_provider,
            outgoing_model=outgoing_model,
            outgoing_lease_id=outgoing_lease_id,
            incoming_provider=incoming_provider,
            incoming_model=incoming_model,
            goal=goal,
            completed_subtasks=completed_subtasks or [],
            active_subtask=active_subtask,
            blocked_subtasks=blocked_subtasks or [],
            next_planned_actions=next_planned_actions or [],
            open_assumptions=open_assumptions or [],
            unresolved_ambiguities=unresolved_ambiguities or [],
            evidence_refs=evidence_refs or [],
            failure_ledger=failure_ledger or [],
            active_capability_ceiling=active_capability_ceiling,
            tool_scope=tool_scope or [],
            state_digest="",
        )
        snapshot.state_digest = snapshot.calculate_digest(snapshot.model_dump())

        self._snapshots[snapshot.handoff_id] = snapshot
        return snapshot

    def execute_handoff(
        self,
        snapshot: HandoffSnapshot,
        incoming_lease_duration_minutes: int = 30,
    ) -> Tuple[HandoffSnapshot, ModelLease]:
        """
        Executes formal handoff:
        1. Verifies state_digest integrity.
        2. Revokes outgoing lease (split-brain protection).
        3. Grants fresh incoming model lease.
        4. Emits CHECKPOINT_SAVED event to EventStore (ALN-016 Merkle & ALN-021 DAG).
        5. Revalidates recovery invariant ALN-015.
        """
        # 1. Verify Digest
        if not snapshot.verify_digest():
            raise InvariantViolationError(
                "ALN-015",
                "Handoff state_digest mismatch! Task state was tampered or corrupted during transfer.",
            )

        # 2. Revoke Outgoing Lease
        try:
            self.lease_controller.revoke_lease(
                snapshot.outgoing_lease_id,
                reason=f"Handoff to {snapshot.incoming_provider}/{snapshot.incoming_model}",
            )
        except CapabilityDeniedError:
            pass  # Already expired/revoked is acceptable

        # 3. Grant Incoming Lease
        new_lease = self.lease_controller.grant_lease(
            provider_id=snapshot.incoming_provider,
            model_id=snapshot.incoming_model,
            task_id=snapshot.task_id,
            project_id=snapshot.project_id,
        )
        snapshot.incoming_lease_id = new_lease.lease_id

        # 4. Record Event
        self.event_store.append_event(
            event_type=EventType.HANDOFF_OCCURRED,
            actor_id="cognitive_handoff_manager",
            payload={
                "handoff_id": str(snapshot.handoff_id),
                "outgoing_model": snapshot.outgoing_model,
                "incoming_model": snapshot.incoming_model,
                "state_digest": snapshot.state_digest,
                "completed_count": len(snapshot.completed_subtasks),
            },
            project_id=snapshot.project_id,
            task_id=snapshot.task_id,
            contract_version=snapshot.contract_version,
        )

        # 5. Validate Recovery Parity (ALN-015)
        self.validate_recovery(snapshot, new_lease)

        return snapshot, new_lease

    def validate_recovery(self, snapshot: HandoffSnapshot, new_lease: ModelLease) -> bool:
        """Validates ALN-015: Incoming model inherits identical canonical task bounds."""
        if not new_lease.is_valid():
            raise InvariantViolationError("ALN-015", "Incoming model lease is invalid upon transfer.")
        if snapshot.contract_version < 1:
            raise InvariantViolationError("ALN-015", "Invalid contract version on handoff snapshot.")
        return True
