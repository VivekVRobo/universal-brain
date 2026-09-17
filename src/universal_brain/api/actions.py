"""Canonical consequential-action state machine.

ActionManager is a projection of EventStore. Proposal creation and every durable
state transition are appended to the canonical event ledger before the in-memory
projection is mutated.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from universal_brain.config import settings
from universal_brain.kernel.capability import CapabilityService, CapabilityToken
from universal_brain.kernel.errors import ActionScopeViolationError, CapabilityDeniedError
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventType


class ActionStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    PREFLIGHTING = "PREFLIGHTING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    APPROVED = "APPROVED"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"


class ActionProposal(BaseModel):
    """Authoritative consequential action proposal."""

    action_id: UUID = Field(default_factory=uuid4)
    proposal_version: int = Field(1, ge=1)
    project_id: UUID
    task_id: UUID
    contract_id: UUID
    contract_version: int
    action_type: str
    target_resource: str
    action_class: ActionClass
    status: ActionStatus = ActionStatus.PROPOSED
    requested_effect: str
    payload: Dict[str, Any]
    required_capabilities: List[str]
    diff_preview: str
    rollback_plan: str
    preflight_passed: bool = False
    evidence_items_count: int = 0
    operator_identity: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: Optional[datetime] = None
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=6)
    )
    nonce: str = Field(default_factory=lambda: uuid4().hex)

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        now = current_time or datetime.now(timezone.utc)
        return now > self.expires_at

    def compute_payload_hash(self) -> str:
        json_bytes = json.dumps(
            self.payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()

    def compute_authorization_digest(
        self,
        operator_identity: Optional[str] = None,
        approved_at: Optional[datetime] = None,
    ) -> str:
        """Bind approval to the canonical server-side operator identity."""
        app_time = approved_at or datetime.now(timezone.utc)
        preflight_digest = hashlib.sha256(
            f"preflight:{self.preflight_passed}".encode("utf-8")
        ).hexdigest()
        rollback_digest = hashlib.sha256(
            self.rollback_plan.encode("utf-8")
        ).hexdigest()

        canonical_digest_dict = {
            "action_class": self.action_class.value,
            "action_id": str(self.action_id),
            "approved_at": app_time.isoformat(timespec="microseconds") + "Z",
            "canonical_payload_hash": self.compute_payload_hash(),
            "contract_id": str(self.contract_id),
            "contract_version": self.contract_version,
            "created_at": self.created_at.isoformat(timespec="microseconds") + "Z",
            "expires_at": self.expires_at.isoformat(timespec="microseconds") + "Z",
            "nonce": self.nonce,
            "operator_identity": settings.operator_id,
            "preflight_evidence_digest": preflight_digest,
            "proposal_version": self.proposal_version,
            "required_capabilities": sorted(self.required_capabilities),
            "rollback_plan_digest": rollback_digest,
            "system_id": settings.system_id,
            "target_identity": self.target_resource,
        }
        json_bytes = json.dumps(
            canonical_digest_dict, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()


class ActionManager:
    """Replayable projection of canonical consequential-action lifecycle events."""

    def __init__(
        self,
        capability_service: CapabilityService,
        event_store: Optional[EventStore] = None,
    ) -> None:
        self.capability_service = capability_service
        self.event_store = event_store
        self._proposals: Dict[UUID, ActionProposal] = {}
        self._idempotency_cache: Dict[str, Dict[str, Any]] = {}
        if self.event_store is not None:
            self.rehydrate_from_events()

    @staticmethod
    def _operator_identity() -> str:
        return settings.operator_id

    def rehydrate_from_events(self) -> None:
        self._proposals.clear()
        self._idempotency_cache.clear()
        if self.event_store is None:
            return

        for event in self.event_store.get_all_events():
            if event.event_type not in {
                EventType.ACTION_PROPOSED,
                EventType.ACTION_STATE_CHANGED,
            }:
                continue
            raw = event.payload.get("proposal")
            if not isinstance(raw, dict):
                continue
            proposal = ActionProposal.model_validate(raw)
            self._proposals[proposal.action_id] = proposal

            key = event.payload.get("idempotency_key")
            if not isinstance(key, str) or not key:
                continue
            raw_token = event.payload.get("token")
            if isinstance(raw_token, dict):
                self._idempotency_cache[key] = {"token": raw_token}
            else:
                self._idempotency_cache[key] = {
                    "proposal": proposal.model_dump(mode="json")
                }

    def _append_projection_event(
        self,
        event_type: EventType,
        proposal: ActionProposal,
        *,
        transition: str,
        idempotency_key: Optional[str] = None,
        token: Optional[CapabilityToken] = None,
        reason: Optional[str] = None,
    ) -> None:
        if self.event_store is None:
            return

        payload: Dict[str, Any] = {
            "transition": transition,
            "proposal": proposal.model_dump(mode="json"),
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        if token is not None:
            payload["token"] = token.model_dump(mode="json")
        if reason:
            payload["reason"] = reason

        self.event_store.append_event(
            event_type=event_type,
            actor_id=self._operator_identity(),
            payload=payload,
            project_id=proposal.project_id,
            task_id=proposal.task_id,
            contract_version=proposal.contract_version,
        )

    def get_proposal(self, action_id: UUID) -> Optional[ActionProposal]:
        return self._proposals.get(action_id)

    def list_proposals(self, project_id: Optional[UUID] = None) -> List[ActionProposal]:
        proposals = list(self._proposals.values())
        if project_id:
            proposals = [p for p in proposals if p.project_id == project_id]
        return proposals

    def create_proposal(
        self,
        project_id: UUID,
        task_id: UUID,
        contract_id: UUID,
        contract_version: int,
        action_type: str,
        target_resource: str,
        action_class: ActionClass,
        requested_effect: str,
        payload: Dict[str, Any],
        required_capabilities: List[str],
        diff_preview: str,
        rollback_plan: str,
        preflight_passed: bool = True,
        evidence_items_count: int = 1,
    ) -> ActionProposal:
        proposal = ActionProposal(
            project_id=project_id,
            task_id=task_id,
            contract_id=contract_id,
            contract_version=contract_version,
            action_type=action_type,
            target_resource=target_resource,
            action_class=action_class,
            status=(
                ActionStatus.AWAITING_APPROVAL
                if preflight_passed
                else ActionStatus.PREFLIGHTING
            ),
            requested_effect=requested_effect,
            payload=payload,
            required_capabilities=required_capabilities,
            diff_preview=diff_preview,
            rollback_plan=rollback_plan,
            preflight_passed=preflight_passed,
            evidence_items_count=evidence_items_count,
        )
        self._append_projection_event(
            EventType.ACTION_PROPOSED,
            proposal,
            transition="CREATED",
        )
        self._proposals[proposal.action_id] = proposal
        return proposal

    def approve_action(
        self,
        action_id: UUID,
        proposal_version: int,
        operator_id: str,
        authorization_digest: str,
        nonce: str,
        idempotency_key: Optional[str] = None,
        current_time: Optional[datetime] = None,
        approved_at: Optional[datetime] = None,
    ) -> CapabilityToken:
        if idempotency_key and idempotency_key in self._idempotency_cache:
            cached = self._idempotency_cache[idempotency_key]
            return CapabilityToken.model_validate(cached["token"])

        proposal = self.get_proposal(action_id)
        if not proposal:
            raise ValueError(f"Action proposal '{action_id}' does not exist.")

        if proposal.status != ActionStatus.AWAITING_APPROVAL:
            raise ActionScopeViolationError(
                f"Action '{action_id}' is in status '{proposal.status.value}'; "
                "only 'AWAITING_APPROVAL' actions can be approved."
            )

        if proposal.is_expired(current_time):
            expired = proposal.model_copy(update={"status": ActionStatus.EXPIRED})
            self._append_projection_event(
                EventType.ACTION_STATE_CHANGED,
                expired,
                transition="EXPIRED",
            )
            self._proposals[action_id] = expired
            raise CapabilityDeniedError(
                f"Action approval deadline expired at {proposal.expires_at.isoformat()}. "
                "Proposal transitioned to EXPIRED."
            )

        if proposal.proposal_version != proposal_version:
            raise ActionScopeViolationError(
                "APPROVAL_INVALIDATED: PROPOSAL_CHANGED_AFTER_REVIEW. "
                f"Reviewed version was {proposal_version}, current version is {proposal.proposal_version}."
            )

        if proposal.nonce != nonce:
            raise CapabilityDeniedError("Invalid or replayed authorization nonce.")

        canonical_operator = self._operator_identity()
        now = approved_at or current_time or datetime.now(timezone.utc)
        expected_digest = proposal.compute_authorization_digest(approved_at=now)
        if authorization_digest.lower() != expected_digest.lower():
            raise CapabilityDeniedError(
                "Authorization digest mismatch. Target, contract, preflight, or payload has mutated."
            )

        if proposal.action_class == ActionClass.A2:
            raise CapabilityDeniedError(
                "A2_LOCKED_PENDING_CHALLENGE_POLICY: authenticated operator control plane is active, "
                "but consequential execution remains disabled pending the dedicated A2 challenge and rollback gate."
            )

        updated = proposal.model_copy(
            update={
                "status": ActionStatus.AUTHORIZED,
                "approved_at": now,
                "operator_identity": canonical_operator,
            }
        )
        token = self.capability_service.issue_token(
            project_id=updated.project_id,
            task_id=updated.task_id,
            contract_id=updated.contract_id,
            contract_version=updated.contract_version,
            action_class=updated.action_class,
            target_resource=updated.target_resource,
            allowed_operations=updated.required_capabilities,
            issued_by_operator=True,
        )

        self._append_projection_event(
            EventType.ACTION_STATE_CHANGED,
            updated,
            transition="AUTHORIZED",
            idempotency_key=idempotency_key,
            token=token,
        )
        self._proposals[action_id] = updated

        if idempotency_key:
            self._idempotency_cache[idempotency_key] = {
                "token": token.model_dump(mode="json")
            }
        return token

    def reject_action(
        self,
        action_id: UUID,
        proposal_version: int,
        operator_id: str,
        reason: str,
        idempotency_key: Optional[str] = None,
    ) -> ActionProposal:
        if idempotency_key and idempotency_key in self._idempotency_cache:
            return ActionProposal.model_validate(
                self._idempotency_cache[idempotency_key]["proposal"]
            )

        proposal = self.get_proposal(action_id)
        if not proposal:
            raise ValueError(f"Action proposal '{action_id}' does not exist.")

        if proposal.status not in (
            ActionStatus.AWAITING_APPROVAL,
            ActionStatus.PREFLIGHTING,
            ActionStatus.PROPOSED,
        ):
            raise ActionScopeViolationError(
                f"Cannot reject action in state '{proposal.status.value}'. "
                "Action may have already executed."
            )

        if proposal.proposal_version != proposal_version:
            raise ActionScopeViolationError(
                f"Proposal version conflict: reviewed {proposal_version}, "
                f"current {proposal.proposal_version}."
            )

        updated = proposal.model_copy(
            update={
                "status": ActionStatus.REJECTED,
                "operator_identity": self._operator_identity(),
            }
        )
        self._append_projection_event(
            EventType.ACTION_STATE_CHANGED,
            updated,
            transition="REJECTED",
            idempotency_key=idempotency_key,
            reason=reason,
        )
        self._proposals[action_id] = updated

        if idempotency_key:
            self._idempotency_cache[idempotency_key] = {
                "proposal": updated.model_dump(mode="json")
            }
        return updated

    def rollback_action(
        self,
        action_id: UUID,
        operator_id: str,
        reason: str,
        idempotency_key: Optional[str] = None,
    ) -> ActionProposal:
        if idempotency_key and idempotency_key in self._idempotency_cache:
            return ActionProposal.model_validate(
                self._idempotency_cache[idempotency_key]["proposal"]
            )

        proposal = self.get_proposal(action_id)
        if not proposal:
            raise ValueError(f"Action proposal '{action_id}' does not exist.")

        if proposal.status not in (
            ActionStatus.FAILED,
            ActionStatus.PARTIAL,
            ActionStatus.SUCCEEDED,
        ):
            raise ActionScopeViolationError(
                f"Cannot rollback action in status '{proposal.status.value}'. "
                "Rollback requires an executed, failed, or partial state."
            )

        if proposal.action_class == ActionClass.A2:
            raise CapabilityDeniedError(
                "A2_LOCKED_PENDING_CHALLENGE_POLICY: authenticated operator control plane is active, "
                "but A2 rollback remains disabled pending a signed RollbackGrant challenge flow."
            )

        updated = proposal.model_copy(
            update={
                "status": ActionStatus.ROLLED_BACK,
                "operator_identity": self._operator_identity(),
            }
        )
        self._append_projection_event(
            EventType.ACTION_STATE_CHANGED,
            updated,
            transition="ROLLED_BACK",
            idempotency_key=idempotency_key,
            reason=reason,
        )
        self._proposals[action_id] = updated

        if idempotency_key:
            self._idempotency_cache[idempotency_key] = {
                "proposal": updated.model_dump(mode="json")
            }
        return updated
