"""
Universal Brain - Authoritative Action State Machine & Lifecycle

Implements Section 3 of the Operator Console Specification:
- Authoritative action lifecycle state machine;
- 16-field TOCTOU Authorization Digest;
- Optimistic concurrency (proposal_version tracking);
- Strict separation of Reject (no rollback) vs. Rollback (undo executed state);
- Command idempotency tracking.
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
from universal_brain.kernel.events import ActionClass


class ActionStatus(str, Enum):
    """Authoritative lifecycle status for consequential actions."""

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
        """Check if 6-hour dead-man's deadline has elapsed."""
        now = current_time or datetime.now(timezone.utc)
        return now > self.expires_at

    def compute_payload_hash(self) -> str:
        """Compute deterministic SHA-256 over action payload."""
        json_bytes = json.dumps(self.payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()

    def compute_authorization_digest(
        self,
        operator_identity: str,
        approved_at: Optional[datetime] = None,
    ) -> str:
        """
        Computes the 16-field Authorization Digest binding:
        action_id, proposal_version, canonical_payload_hash, target_identity,
        action_class, contract_id, contract_version, required_capabilities,
        preflight_evidence_digest, rollback_plan_digest, operator_identity,
        created_at, approved_at, expires_at, nonce, system_id.
        """
        app_time = approved_at or datetime.now(timezone.utc)
        preflight_digest = hashlib.sha256(f"preflight:{self.preflight_passed}".encode("utf-8")).hexdigest()
        rollback_digest = hashlib.sha256(self.rollback_plan.encode("utf-8")).hexdigest()

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
            "operator_identity": operator_identity,
            "preflight_evidence_digest": preflight_digest,
            "proposal_version": self.proposal_version,
            "required_capabilities": sorted(self.required_capabilities),
            "rollback_plan_digest": rollback_digest,
            "system_id": settings.system_id,
            "target_identity": self.target_resource,
        }
        json_bytes = json.dumps(canonical_digest_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()


class ActionManager:
    """Manages consequential action state transitions, TOCTOU checks, and idempotency."""

    def __init__(self, capability_service: CapabilityService) -> None:
        self.capability_service = capability_service
        self._proposals: Dict[UUID, ActionProposal] = {}
        self._idempotency_cache: Dict[str, Dict[str, Any]] = {}

    def get_proposal(self, action_id: UUID) -> Optional[ActionProposal]:
        """Fetch proposal by ID."""
        return self._proposals.get(action_id)

    def list_proposals(self, project_id: Optional[UUID] = None) -> List[ActionProposal]:
        """List proposals, optionally filtered by project."""
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
        """Instantiate a new action proposal."""
        proposal = ActionProposal(
            project_id=project_id,
            task_id=task_id,
            contract_id=contract_id,
            contract_version=contract_version,
            action_type=action_type,
            target_resource=target_resource,
            action_class=action_class,
            status=ActionStatus.AWAITING_APPROVAL if preflight_passed else ActionStatus.PREFLIGHTING,
            requested_effect=requested_effect,
            payload=payload,
            required_capabilities=required_capabilities,
            diff_preview=diff_preview,
            rollback_plan=rollback_plan,
            preflight_passed=preflight_passed,
            evidence_items_count=evidence_items_count,
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
        """
        Approves an action proposal with strict TOCTOU and optimistic concurrency verification:
        1. Idempotency check.
        2. Action exists and is in AWAITING_APPROVAL status.
        3. Expiry verification (6-hour dead-man's deadline).
        4. Optimistic concurrency check (proposal_version must match).
        5. Nonce and Authorization Digest verification.
        6. State transition: AWAITING_APPROVAL -> APPROVED -> AUTHORIZED.
        7. Issue CapabilityToken via CapabilityService.
        """
        # 1. Idempotency
        if idempotency_key and idempotency_key in self._idempotency_cache:
            cached = self._idempotency_cache[idempotency_key]
            return CapabilityToken.model_validate(cached["token"])

        # 2. Lookup proposal
        proposal = self.get_proposal(action_id)
        if not proposal:
            raise ValueError(f"Action proposal '{action_id}' does not exist.")

        if proposal.status != ActionStatus.AWAITING_APPROVAL:
            raise ActionScopeViolationError(
                f"Action '{action_id}' is in status '{proposal.status.value}'; "
                f"only 'AWAITING_APPROVAL' actions can be approved."
            )

        # 3. Expiry verification
        if proposal.is_expired(current_time):
            proposal.status = ActionStatus.EXPIRED
            raise CapabilityDeniedError(
                f"Action approval deadline expired at {proposal.expires_at.isoformat()}. "
                f"Proposal transitioned to EXPIRED."
            )

        # 4. Optimistic concurrency check
        if proposal.proposal_version != proposal_version:
            raise ActionScopeViolationError(
                f"APPROVAL_INVALIDATED: PROPOSAL_CHANGED_AFTER_REVIEW. "
                f"Reviewed version was {proposal_version}, current version is {proposal.proposal_version}."
            )

        # 5. Nonce check
        if proposal.nonce != nonce:
            raise CapabilityDeniedError("Invalid or replayed authorization nonce.")

        # 6. Recompute and assert Authorization Digest
        now = approved_at or current_time or datetime.now(timezone.utc)
        expected_digest = proposal.compute_authorization_digest(
            operator_identity=operator_id,
            approved_at=now,
        )
        if authorization_digest.lower() != expected_digest.lower():
            raise CapabilityDeniedError(
                "Authorization digest mismatch. Target, contract, preflight, or payload has mutated."
            )

        # Gate S1 A2 Execution Lockdown:
        if proposal.action_class == ActionClass.A2:
            raise CapabilityDeniedError(
                "A2_LOCKED_PENDING_OPERATOR_AUTH: A2 consequential approvals are locked pending verified operator authentication middleware and challenge synchronization."
            )

        # 7. Update status
        proposal.status = ActionStatus.AUTHORIZED
        proposal.approved_at = now
        proposal.operator_identity = operator_id

        # 8. Issue CapabilityToken
        token = self.capability_service.issue_token(
            project_id=proposal.project_id,
            task_id=proposal.task_id,
            contract_version=proposal.contract_version,
            action_class=proposal.action_class,
            target_resource=proposal.target_resource,
            allowed_operations=proposal.required_capabilities,
            issued_by_operator=True,
        )

        if idempotency_key:
            self._idempotency_cache[idempotency_key] = {"token": token.model_dump()}

        return token

    def reject_action(
        self,
        action_id: UUID,
        proposal_version: int,
        operator_id: str,
        reason: str,
        idempotency_key: Optional[str] = None,
    ) -> ActionProposal:
        """
        Rejects an unexecuted proposal.
        Does NOT execute rollback because no state was mutated!
        """
        if idempotency_key and idempotency_key in self._idempotency_cache:
            return ActionProposal.model_validate(self._idempotency_cache[idempotency_key]["proposal"])

        proposal = self.get_proposal(action_id)
        if not proposal:
            raise ValueError(f"Action proposal '{action_id}' does not exist.")

        if proposal.status not in (ActionStatus.AWAITING_APPROVAL, ActionStatus.PREFLIGHTING, ActionStatus.PROPOSED):
            raise ActionScopeViolationError(
                f"Cannot reject action in state '{proposal.status.value}'. Action may have already executed."
            )

        if proposal.proposal_version != proposal_version:
            raise ActionScopeViolationError(
                f"Proposal version conflict: reviewed {proposal_version}, current {proposal.proposal_version}."
            )

        proposal.status = ActionStatus.REJECTED
        proposal.operator_identity = operator_id

        if idempotency_key:
            self._idempotency_cache[idempotency_key] = {"proposal": proposal.model_dump()}

        return proposal

    def rollback_action(
        self,
        action_id: UUID,
        operator_id: str,
        reason: str,
        idempotency_key: Optional[str] = None,
    ) -> ActionProposal:
        """
        Executes rollback on an action that previously changed state or failed mid-execution.
        """
        if idempotency_key and idempotency_key in self._idempotency_cache:
            return ActionProposal.model_validate(self._idempotency_cache[idempotency_key]["proposal"])

        proposal = self.get_proposal(action_id)
        if not proposal:
            raise ValueError(f"Action proposal '{action_id}' does not exist.")

        # Rollback only allowed if action executed, failed, or is in partial state
        if proposal.status not in (ActionStatus.FAILED, ActionStatus.PARTIAL, ActionStatus.SUCCEEDED):
            raise ActionScopeViolationError(
                f"Cannot rollback action in status '{proposal.status.value}'. "
                f"Rollback requires an executed, failed, or partial state."
            )

        if proposal.action_class == ActionClass.A2:
            raise CapabilityDeniedError(
                "A2_LOCKED_PENDING_OPERATOR_AUTH: Rollback execution of A2 actions is locked pending verified operator authentication middleware and signed RollbackGrant."
            )

        proposal.status = ActionStatus.ROLLED_BACK

        if idempotency_key:
            self._idempotency_cache[idempotency_key] = {"proposal": proposal.model_dump()}

        return proposal
