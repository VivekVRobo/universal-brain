"""
Universal Brain - Capability Token Service

Implements ALN-008 (target-specific A2 approval), ALN-009 (anti-privilege-escalation),
and Gate S1 request-bound capability tokens and verified rollback grants.
Issues and cryptographically validates time-bounded capability tokens required
by the Tool Gateway for all state-changing actions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from universal_brain.config import settings
from universal_brain.kernel.errors import CapabilityDeniedError
from universal_brain.kernel.events import ActionClass


_ACTION_CLASS_ORDER = {
    ActionClass.A0: 0,
    ActionClass.A1: 1,
    ActionClass.A2: 2,
    ActionClass.A3: 3,
}


def is_resource_authorized(pattern: str, target: str) -> bool:
    """
    Checks if a target resource conforms to an authorized pattern.
    Enforces segment-aware boundaries:
    - '*' matches anything.
    - Exact matches match.
    - 'safe/*' matches 'safe/foo.txt', but strictly rejects 'safeevil'.
    - 'safe/' prefix matches anything under 'safe/'.
    - Never treats 'safe*' as matching 'safeevil'.
    """
    if pattern == "*" or pattern == target:
        return True

    clean_target = target.replace("\\", "/").rstrip("/")
    clean_pattern = pattern.replace("\\", "/").rstrip("/")

    if clean_pattern == clean_target:
        return True

    if clean_pattern.endswith("/*"):
        base_dir = clean_pattern[:-2]
        return clean_target == base_dir or clean_target.startswith(base_dir + "/")

    if clean_pattern.endswith("*"):
        base = clean_pattern[:-1]
        if base.endswith(("/", "_", "-", ".")):
            return clean_target.startswith(base)
        return False

    try:
        p_target = Path(target).resolve()
        p_pattern = Path(pattern).resolve()
        if p_target == p_pattern or p_target.is_relative_to(p_pattern):
            return True
    except Exception:
        pass

    return False


def compute_canonical_request_digest(
    tool_name: str,
    args: Dict[str, Any],
    action_class: ActionClass,
    contract_id: UUID,
    contract_version: int,
    task_id: UUID,
    idempotency_key: Optional[str] = None,
) -> str:
    """Computes deterministic SHA-256 over the authority-relevant tool request."""
    canonical_payload = {
        "action_class": action_class.value,
        "args": args,
        "contract_id": str(contract_id),
        "contract_version": contract_version,
        "idempotency_key": idempotency_key or "",
        "task_id": str(task_id),
        "tool_name": tool_name,
    }
    raw = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class CapabilityToken(BaseModel):
    """Cryptographically signed, scoped capability authorization token."""

    model_config = {"frozen": True, "extra": "forbid"}

    token_id: UUID = Field(default_factory=uuid4, description="Unique capability token ID")
    project_id: UUID = Field(..., description="Project bounding this token")
    task_id: UUID = Field(..., description="Specific task authorized to use this token")
    contract_id: UUID = Field(..., description="Exact Alignment Contract authorized by this token")
    contract_version: int = Field(..., description="Contract version in effect when issued")
    action_class: ActionClass = Field(..., description="Maximum action class authorized (A0-A2)")
    target_resource: str = Field(..., description="Exact resource/path pattern authorized")
    allowed_operations: List[str] = Field(..., description="Allowed operations (e.g. ['read', 'write', 'commit'])")
    request_digest: Optional[str] = Field(None, description="SHA-256 digest of canonical tool request")
    idempotency_key: Optional[str] = Field(None, description="Bound idempotency key")
    issued_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC issue timestamp",
    )
    expires_at: datetime = Field(..., description="UTC expiration timestamp")
    signature: str = Field(..., description="HMAC-SHA256 signature validating token authenticity")

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        now = current_time or datetime.now(timezone.utc)
        return now > self.expires_at


class RollbackGrant(BaseModel):
    """Cryptographically signed grant authorizing compensation rollback."""

    model_config = {"frozen": True, "extra": "forbid"}

    grant_id: UUID = Field(default_factory=uuid4, description="Unique rollback grant ID")
    project_id: UUID = Field(..., description="Project bounding this grant")
    task_id: UUID = Field(..., description="Specific task bounding this grant")
    action_id: UUID = Field(..., description="Original action authorized to roll back")
    tool_name: str = Field(..., description="Target tool to roll back")
    target_resource: str = Field(..., description="Resource authorized for rollback")
    pre_state_hash: Optional[str] = Field(None, description="Expected pre-mutation hash to restore")
    issued_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC issue timestamp",
    )
    expires_at: datetime = Field(..., description="UTC expiration timestamp")
    signature: str = Field(..., description="HMAC-SHA256 signature validating grant authenticity")

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        now = current_time or datetime.now(timezone.utc)
        return now > self.expires_at


class CapabilityService:
    """Issues and verifies capability tokens and rollback grants using HMAC-SHA256."""

    def __init__(self, secret_key: Optional[str] = None) -> None:
        self._secret = (secret_key or settings.hmac_secret_key).encode("utf-8")

    def _compute_signature(
        self,
        token_id: UUID,
        project_id: UUID,
        task_id: UUID,
        contract_id: UUID,
        contract_version: int,
        action_class: ActionClass,
        target_resource: str,
        allowed_operations: List[str],
        issued_at: datetime,
        expires_at: datetime,
        request_digest: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        """Generates deterministic HMAC-SHA256 digest over token parameters."""
        canonical_data = {
            "action_class": action_class.value,
            "allowed_operations": sorted(allowed_operations),
            "contract_id": str(contract_id),
            "contract_version": contract_version,
            "expires_at": expires_at.isoformat(timespec="microseconds") + "Z",
            "idempotency_key": idempotency_key or "",
            "issued_at": issued_at.isoformat(timespec="microseconds") + "Z",
            "project_id": str(project_id),
            "request_digest": request_digest or "",
            "target_resource": target_resource,
            "task_id": str(task_id),
            "token_id": str(token_id),
        }
        json_bytes = json.dumps(canonical_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self._secret, json_bytes, hashlib.sha256).hexdigest()

    def _compute_rollback_signature(
        self,
        grant_id: UUID,
        project_id: UUID,
        task_id: UUID,
        action_id: UUID,
        tool_name: str,
        target_resource: str,
        pre_state_hash: Optional[str],
        issued_at: datetime,
        expires_at: datetime,
    ) -> str:
        canonical_data = {
            "action_id": str(action_id),
            "expires_at": expires_at.isoformat(timespec="microseconds") + "Z",
            "grant_id": str(grant_id),
            "issued_at": issued_at.isoformat(timespec="microseconds") + "Z",
            "pre_state_hash": pre_state_hash or "",
            "project_id": str(project_id),
            "target_resource": target_resource,
            "task_id": str(task_id),
            "tool_name": tool_name,
        }
        json_bytes = json.dumps(canonical_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self._secret, json_bytes, hashlib.sha256).hexdigest()

    def issue_token(
        self,
        project_id: UUID,
        task_id: UUID,
        contract_id: UUID,
        contract_version: int,
        action_class: ActionClass,
        target_resource: str,
        allowed_operations: List[str],
        ttl_seconds: Optional[int] = None,
        issued_by_operator: bool = False,
        request_digest: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> CapabilityToken:
        """
        Issue a new capability token.
        Enforces ALN-008: A2 actions require fresh explicit operator authorization.
        Enforces ALN-018: A3 prohibited actions can never be issued.
        """
        if action_class == ActionClass.A3:
            raise CapabilityDeniedError("A3 actions are strictly prohibited and cannot be issued a capability token.")

        if action_class == ActionClass.A2 and not issued_by_operator:
            raise CapabilityDeniedError(
                "A2 consequential actions require fresh operator authorization before token issuance (ALN-008)."
            )

        now = datetime.now(timezone.utc)
        ttl = ttl_seconds or settings.capability_token_ttl_seconds
        expires_at = datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc)
        token_id = uuid4()

        sig = self._compute_signature(
            token_id=token_id,
            project_id=project_id,
            task_id=task_id,
            contract_id=contract_id,
            contract_version=contract_version,
            action_class=action_class,
            target_resource=target_resource,
            allowed_operations=allowed_operations,
            issued_at=now,
            expires_at=expires_at,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
        )

        return CapabilityToken(
            token_id=token_id,
            project_id=project_id,
            task_id=task_id,
            contract_id=contract_id,
            contract_version=contract_version,
            action_class=action_class,
            target_resource=target_resource,
            allowed_operations=allowed_operations,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
            issued_at=now,
            expires_at=expires_at,
            signature=sig,
        )

    def issue_rollback_grant(
        self,
        project_id: UUID,
        task_id: UUID,
        action_id: UUID,
        tool_name: str,
        target_resource: str,
        pre_state_hash: Optional[str] = None,
        ttl_seconds: int = 86400,
    ) -> RollbackGrant:
        """Issues an explicit RollbackGrant bound to the action and target state."""
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc)
        grant_id = uuid4()

        sig = self._compute_rollback_signature(
            grant_id=grant_id,
            project_id=project_id,
            task_id=task_id,
            action_id=action_id,
            tool_name=tool_name,
            target_resource=target_resource,
            pre_state_hash=pre_state_hash,
            issued_at=now,
            expires_at=expires_at,
        )

        return RollbackGrant(
            grant_id=grant_id,
            project_id=project_id,
            task_id=task_id,
            action_id=action_id,
            tool_name=tool_name,
            target_resource=target_resource,
            pre_state_hash=pre_state_hash,
            issued_at=now,
            expires_at=expires_at,
            signature=sig,
        )

    def verify_token(
        self,
        token: CapabilityToken,
        target_resource: str,
        required_operation: str,
        current_contract_id: UUID,
        current_contract_version: int,
        current_time: Optional[datetime] = None,
        expected_request_digest: Optional[str] = None,
        required_action_class: Optional[ActionClass] = None,
        expected_project_id: Optional[UUID] = None,
        expected_task_id: Optional[UUID] = None,
    ) -> bool:
        """Validate signature plus all supplied authority dimensions.

        ``contract_id`` and ``contract_version`` are mandatory because a token
        issued for one contract must never become valid merely because another
        contract happens to share the same version number.
        """
        expected_sig = self._compute_signature(
            token_id=token.token_id,
            project_id=token.project_id,
            task_id=token.task_id,
            contract_id=token.contract_id,
            contract_version=token.contract_version,
            action_class=token.action_class,
            target_resource=token.target_resource,
            allowed_operations=token.allowed_operations,
            issued_at=token.issued_at,
            expires_at=token.expires_at,
            request_digest=token.request_digest,
            idempotency_key=token.idempotency_key,
        )

        if not hmac.compare_digest(token.signature, expected_sig):
            raise CapabilityDeniedError("Capability token signature is invalid or has been tampered with.")

        if token.is_expired(current_time):
            raise CapabilityDeniedError(f"Capability token expired at {token.expires_at.isoformat()}.")

        if token.contract_id != current_contract_id:
            raise CapabilityDeniedError(
                f"Capability token contract ({token.contract_id}) does not match active contract ({current_contract_id})."
            )

        if token.contract_version != current_contract_version:
            raise CapabilityDeniedError(
                f"Capability token contract version ({token.contract_version}) is stale; current is {current_contract_version}."
            )

        if expected_project_id is not None and token.project_id != expected_project_id:
            raise CapabilityDeniedError(
                f"Capability token project ({token.project_id}) does not match execution project ({expected_project_id})."
            )

        if expected_task_id is not None and token.task_id != expected_task_id:
            raise CapabilityDeniedError(
                f"Capability token task ({token.task_id}) does not match execution task ({expected_task_id})."
            )

        if required_action_class is not None:
            if _ACTION_CLASS_ORDER[required_action_class] > _ACTION_CLASS_ORDER[token.action_class]:
                raise CapabilityDeniedError(
                    f"Capability token action ceiling ({token.action_class.value}) does not authorize "
                    f"required action class ({required_action_class.value})."
                )

        if token.request_digest:
            if not expected_request_digest:
                raise CapabilityDeniedError(
                    "Capability token requires a verified request digest, but none was computed."
                )
            if not hmac.compare_digest(token.request_digest, expected_request_digest):
                raise CapabilityDeniedError(
                    "Capability token request digest mismatch: invocation arguments do not match authorized token."
                )

        if not is_resource_authorized(token.target_resource, target_resource):
            raise CapabilityDeniedError(
                f"Target resource '{target_resource}' is outside authorized scope '{token.target_resource}'."
            )

        if required_operation not in token.allowed_operations and "*" not in token.allowed_operations:
            raise CapabilityDeniedError(
                f"Operation '{required_operation}' is not in authorized operations: {token.allowed_operations}."
            )

        return True

    def verify_rollback_grant(
        self,
        grant: RollbackGrant,
        tool_name: str,
        target_resource: str,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """Validates a RollbackGrant signature, expiry, tool, and target scope."""
        expected_sig = self._compute_rollback_signature(
            grant_id=grant.grant_id,
            project_id=grant.project_id,
            task_id=grant.task_id,
            action_id=grant.action_id,
            tool_name=grant.tool_name,
            target_resource=grant.target_resource,
            pre_state_hash=grant.pre_state_hash,
            issued_at=grant.issued_at,
            expires_at=grant.expires_at,
        )

        if not hmac.compare_digest(grant.signature, expected_sig):
            raise CapabilityDeniedError("Rollback grant signature is invalid or tampered with.")

        if grant.is_expired(current_time):
            raise CapabilityDeniedError(f"Rollback grant expired at {grant.expires_at.isoformat()}.")

        if grant.tool_name != tool_name and grant.tool_name != "*":
            raise CapabilityDeniedError(
                f"Rollback grant is for tool '{grant.tool_name}', cannot roll back '{tool_name}'."
            )

        if not is_resource_authorized(grant.target_resource, target_resource):
            raise CapabilityDeniedError(
                f"Target resource '{target_resource}' is outside rollback grant scope '{grant.target_resource}'."
            )

        return True
