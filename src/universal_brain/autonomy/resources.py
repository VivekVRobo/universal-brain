"""
Universal Brain - Resource Lease System & Deadlock Prevention

Implements M7 Sections 35-37 and Section 62:
- Coordinates exclusive access to scarce physical/logical resources;
- Fences stale resource holders upon reassignment;
- Prevents resource contention and race conditions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID

from universal_brain.autonomy.errors import ResourceDeadlockError
from universal_brain.autonomy.schemas import ResourceLease


class ResourceLeaseController:
    """Manages exclusive leases over scarce resources with epoch and generation fencing."""

    def __init__(self) -> None:
        self._leases: Dict[str, ResourceLease] = {}

    def acquire_resource(
        self,
        resource_id: str,
        resource_type: str,
        mission_id: UUID,
        task_id: Optional[UUID] = None,
        kernel_epoch: int = 1,
        duration_seconds: int = 300,
    ) -> ResourceLease:
        """Acquires or reassigns an exclusive resource lease."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=duration_seconds)

        existing = self._leases.get(resource_id)
        if existing and existing.status == "ACTIVE" and now <= existing.expires_at:
            if existing.mission_id == mission_id and existing.task_id == task_id:
                # Renewal
                existing.expires_at = expires_at
                return existing
            # Active lease held by another task/mission
            raise ResourceDeadlockError(
                f"Resource '{resource_id}' ({resource_type}) is exclusively held by mission {existing.mission_id} until {existing.expires_at.isoformat()}."
            )

        new_generation = (existing.lease_generation + 1) if existing else 1
        lease = ResourceLease(
            resource_id=resource_id,
            resource_type=resource_type,
            mission_id=mission_id,
            task_id=task_id,
            lease_generation=new_generation,
            kernel_epoch=kernel_epoch,
            acquired_at=now,
            expires_at=expires_at,
            status="ACTIVE",
        )
        self._leases[resource_id] = lease
        return lease

    def release_resource(self, resource_id: str, mission_id: UUID) -> None:
        """Releases a resource lease."""
        lease = self._leases.get(resource_id)
        if lease and lease.mission_id == mission_id:
            lease.status = "RELEASED"

    def get_lease(self, resource_id: str) -> Optional[ResourceLease]:
        return self._leases.get(resource_id)

    def validate_resource_authority(
        self,
        resource_id: str,
        expected_generation: int,
        current_kernel_epoch: int,
    ) -> bool:
        """Validates that a resource operation holds current unfenced authority."""
        lease = self._leases.get(resource_id)
        if not lease or lease.status != "ACTIVE":
            return False
        now = datetime.now(timezone.utc)
        if now > lease.expires_at:
            lease.status = "EXPIRED"
            return False
        if lease.kernel_epoch < current_kernel_epoch:
            lease.status = "REVOKED"
            return False
        if lease.lease_generation != expected_generation:
            return False
        return True
