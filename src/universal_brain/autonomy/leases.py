"""
Universal Brain - Agent Lease Controller & Fencing

Implements M7 Sections 25-29 and Invariants M7-INV-04, M7-INV-05, M7-INV-06:
- Grants ephemeral, bounded execution authority to Agent Cells;
- Enforces multi-dimensional fencing key: (mission_id, task_id, lease_id, generation, epoch, version);
- Fences stale agents upon reassignment or kernel reboot;
- Enforces turn and spend quotas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID

from universal_brain.autonomy.errors import (
    AgentFencedError,
    AgentLeaseExpiredError,
    MissionBudgetExceededError,
    MissionVersionConflictError,
)
from universal_brain.autonomy.schemas import AgentLease, AgentLeaseStatus
from universal_brain.kernel.events import ActionClass


class AgentLeaseController:
    """Controls bounded agent execution leases and split-agent fencing."""

    def __init__(self, max_lease_duration_minutes: int = 60) -> None:
        self.max_duration = timedelta(minutes=max_lease_duration_minutes)
        self._leases: Dict[UUID, AgentLease] = {}

    def grant_lease(
        self,
        agent_id: UUID,
        mission_id: UUID,
        task_scope: List[UUID],
        capability_ceiling: ActionClass = ActionClass.A1,
        tool_scope: Optional[List[str]] = None,
        kernel_epoch: int = 1,
        lease_generation: int = 1,
        duration_minutes: int = 30,
        max_turns: int = 20,
        max_spend: float = 10.0,
    ) -> AgentLease:
        """Issues a new bounded agent execution lease (M7 Section 25)."""
        now = datetime.now(timezone.utc)
        expires_at = now + min(timedelta(minutes=duration_minutes), self.max_duration)

        lease = AgentLease(
            agent_id=agent_id,
            mission_id=mission_id,
            task_scope=task_scope,
            lease_generation=lease_generation,
            kernel_epoch=kernel_epoch,
            granted_at=now,
            expires_at=expires_at,
            capability_ceiling=capability_ceiling,
            tool_scope=tool_scope or [],
            max_turns=max_turns,
            turns_used=0,
            max_spend=max_spend,
            spend_used=0.0,
            status=AgentLeaseStatus.ACTIVE,
        )
        self._leases[lease.lease_id] = lease
        return lease

    def get_lease(self, lease_id: UUID) -> Optional[AgentLease]:
        """Retrieves lease by ID."""
        return self._leases.get(lease_id)

    def validate_lease_authority(
        self,
        lease_id: UUID,
        task_id: UUID,
        current_kernel_epoch: int,
        current_lease_generation: int,
        mission_version: int,
        expected_mission_version: int,
    ) -> AgentLease:
        """
        Validates that the requesting agent has current, unfenced authority (M7 Section 27).
        Enforces M7-INV-04, M7-INV-05, M7-INV-06.
        """
        lease = self.get_lease(lease_id)
        if not lease:
            raise AgentFencedError(f"Lease {lease_id} not found.")

        if lease.status != AgentLeaseStatus.ACTIVE:
            raise AgentFencedError(f"Lease {lease_id} is in status {lease.status.value}, not ACTIVE.")

        now = datetime.now(timezone.utc)
        if now > lease.expires_at:
            lease.status = AgentLeaseStatus.EXPIRED
            raise AgentLeaseExpiredError(f"Lease {lease_id} expired at {lease.expires_at.isoformat()}.")

        # 1. Kernel Epoch Fencing (M7-INV-06)
        if lease.kernel_epoch < current_kernel_epoch:
            lease.status = AgentLeaseStatus.REVOKED
            raise AgentFencedError(
                f"Agent lease {lease_id} belongs to older kernel epoch {lease.kernel_epoch} < {current_kernel_epoch}."
            )

        # 2. Split-Agent Lease Generation Fencing (M7-INV-05)
        if lease.lease_generation < current_lease_generation:
            lease.status = AgentLeaseStatus.REVOKED
            raise AgentFencedError(
                f"Agent lease {lease_id} has stale generation {lease.lease_generation} < {current_lease_generation}."
            )

        # 3. Mission Version Fencing (M7-INV-04)
        if mission_version != expected_mission_version:
            raise MissionVersionConflictError(
                f"Mission version conflict: current version {mission_version} != expected {expected_mission_version}"
            )

        # 4. Task Scope Confinement
        if task_id not in lease.task_scope:
            raise AgentFencedError(f"Task {task_id} not in authorized task scope for lease {lease_id}.")

        return lease

    def record_usage(self, lease_id: UUID, turns: int = 1, spend: float = 0.0) -> None:
        """Records turn and financial spend usage against lease ceilings."""
        lease = self.get_lease(lease_id)
        if not lease:
            return

        lease.turns_used += turns
        lease.spend_used += spend

        if lease.turns_used >= lease.max_turns:
            lease.status = AgentLeaseStatus.COMPLETED

        if lease.spend_used > lease.max_spend:
            lease.status = AgentLeaseStatus.FAILED
            raise MissionBudgetExceededError(
                f"Agent lease {lease_id} exceeded spend ceiling ${lease.max_spend:.2f} (used: ${lease.spend_used:.2f})"
            )

    def revoke_lease(self, lease_id: UUID, reason: str = "Explicit revocation") -> None:
        """Revokes an active lease immediately."""
        lease = self.get_lease(lease_id)
        if lease and lease.status == AgentLeaseStatus.ACTIVE:
            lease.status = AgentLeaseStatus.REVOKED

    def fence_epoch(self, current_epoch: int) -> int:
        """Fences all active leases from previous kernel epochs."""
        count = 0
        for lease in self._leases.values():
            if lease.status == AgentLeaseStatus.ACTIVE and lease.kernel_epoch < current_epoch:
                lease.status = AgentLeaseStatus.REVOKED
                count += 1
        return count
