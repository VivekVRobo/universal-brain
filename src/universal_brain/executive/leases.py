"""
Universal Brain - Model Lease Controller

Implements Sections 24 & 25 of the God-Level Specification:
- Bounded, ephemeral execution leases for frontier and local models;
- Turn limits, context token accounting, and cost ceilings;
- Immediate revocation upon lease expiration, exhaustion, or cognitive handoff.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from uuid import UUID

from universal_brain.executive.schemas import LeaseStatus, ModelLease
from universal_brain.kernel.errors import CapabilityDeniedError


class ModelLeaseController:
    """Manages ephemeral model lease lifecycles and resource consumption."""

    def __init__(self, default_duration_minutes: int = 30) -> None:
        self.default_duration = timedelta(minutes=default_duration_minutes)
        self._leases: Dict[UUID, ModelLease] = {}

    def grant_lease(
        self,
        provider_id: str,
        model_id: str,
        task_id: UUID,
        project_id: UUID,
        max_turns: int = 10,
        max_input_tokens: int = 100000,
        spend_ceiling_usd: float = 5.0,
    ) -> ModelLease:
        """Issues a new bounded model lease."""
        now = datetime.now(timezone.utc)
        lease = ModelLease(
            provider_id=provider_id,
            model_id=model_id,
            task_id=task_id,
            project_id=project_id,
            granted_at=now,
            expires_at=now + self.default_duration,
            max_turns=max_turns,
            max_input_tokens=max_input_tokens,
            spend_ceiling_usd=spend_ceiling_usd,
            status=LeaseStatus.ACTIVE,
        )
        self._leases[lease.lease_id] = lease
        return lease

    def get_lease(self, lease_id: UUID) -> Optional[ModelLease]:
        """Fetch lease by ID."""
        return self._leases.get(lease_id)

    def record_usage(
        self,
        lease_id: UUID,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> ModelLease:
        """Records token and cost consumption on an active lease."""
        lease = self.get_lease(lease_id)
        if not lease:
            raise CapabilityDeniedError(f"Lease '{lease_id}' not found.")

        if not lease.is_valid():
            raise CapabilityDeniedError(f"Cannot record usage: lease '{lease_id}' is expired, exhausted, or revoked.")

        lease.turns_used += 1
        lease.input_tokens_used += input_tokens
        lease.output_tokens_used += output_tokens
        lease.spend_used_usd += cost_usd

        # Check exhaustion
        if lease.turns_used >= lease.max_turns:
            lease.status = LeaseStatus.EXHAUSTED
        elif lease.spend_used_usd >= lease.spend_ceiling_usd:
            lease.status = LeaseStatus.EXHAUSTED

        return lease

    def revoke_lease(self, lease_id: UUID, reason: str = "Handoff or termination") -> ModelLease:
        """Immediately revokes an active lease (used during cognitive handoff)."""
        lease = self.get_lease(lease_id)
        if not lease:
            raise CapabilityDeniedError(f"Lease '{lease_id}' not found.")

        lease.status = LeaseStatus.REVOKED
        return lease
