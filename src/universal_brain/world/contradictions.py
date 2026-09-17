"""
Universal Brain - World Contradiction Engine & Verification Promotion
Implements Sections 68-72 of Milestone M8 Specification (M8-INV-05).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID, uuid4

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType

if TYPE_CHECKING:
    from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.schemas import (
    AssertionStateClass,
    AssertionStatus,
    ContradictionSeverity,
    ResolutionStatus,
    WorldContradiction,
    WorldPropertyAssertion,
)


class WorldContradictionEngine:
    """
    Detects contradictory property assertions with overlapping temporal validity,
    preserves competing evidence in history (M8-INV-05), and manages formal verification resolution.
    """

    def __init__(self, uow: UnitOfWork, event_store: Optional[EventStore] = None) -> None:
        self.uow = uow
        self.event_store = event_store

    async def check_contradiction(
        self,
        assertion_a: WorldPropertyAssertion,
        assertion_b: WorldPropertyAssertion,
    ) -> Optional[WorldContradiction]:
        """
        Evaluates whether two assertions mutually contradict within an overlapping time interval.
        """
        if assertion_a.entity_id != assertion_b.entity_id or assertion_a.property_key != assertion_b.property_key:
            return None

        if assertion_a.value == assertion_b.value:
            return None

        # Check temporal overlap
        overlap = not (
            (assertion_a.valid_until and assertion_a.valid_until < assertion_b.valid_from)
            or (assertion_b.valid_until and assertion_b.valid_until < assertion_a.valid_from)
        )

        if not overlap:
            return None

        contradiction = WorldContradiction(
            contradiction_id=uuid4(),
            entity_id=assertion_a.entity_id,
            property_key=assertion_a.property_key,
            assertion_ids=[assertion_a.assertion_id, assertion_b.assertion_id],
            temporal_overlap=True,
            severity=ContradictionSeverity.HIGH,
            detected_at=datetime.now(timezone.utc),
            resolution_status=ResolutionStatus.OPEN,
            resolution_evidence=None,
            winning_assertion_id=None,
        )

        assert self.uow.world_contradictions is not None
        await self.uow.world_contradictions.create_contradiction(contradiction)

        # Mark both assertions as CONTRADICTED
        assert self.uow.world_assertions is not None
        a_curr = await self.uow.world_assertions.get_assertion(assertion_a.assertion_id)
        if a_curr:
            await self.uow.world_assertions.update_assertion_with_version(
                assertion_id=a_curr.assertion_id,
                expected_version=a_curr.assertion_version,
                new_status=AssertionStatus.CONTRADICTED.value,
            )
        b_curr = await self.uow.world_assertions.get_assertion(assertion_b.assertion_id)
        if b_curr:
            await self.uow.world_assertions.update_assertion_with_version(
                assertion_id=b_curr.assertion_id,
                expected_version=b_curr.assertion_version,
                new_status=AssertionStatus.CONTRADICTED.value,
            )

        if self.event_store:
            self.event_store.append_event(
                event_type=EventType.WORLD_CONTRADICTION_DETECTED,
                actor_id="world_model",
                payload={
                    "contradiction_id": str(contradiction.contradiction_id),
                    "entity_id": contradiction.entity_id,
                    "property_key": contradiction.property_key,
                    "assertion_ids": [str(x) for x in contradiction.assertion_ids],
                },
            )

        return contradiction

    async def resolve_contradiction(
        self,
        contradiction_id: UUID,
        winning_assertion_id: UUID,
        verification_evidence: str,
    ) -> WorldContradiction:
        """
        Promotes the winning assertion to VERIFIED while marking the losing assertion REJECTED.
        Preserves the complete audit lineage of both claims.
        """
        assert self.uow.world_contradictions is not None
        assert self.uow.world_assertions is not None

        c = await self.uow.world_contradictions.get_contradiction(contradiction_id)
        if not c:
            raise ValueError(f"Contradiction {contradiction_id} not found.")

        # Update contradiction record
        await self.uow.world_contradictions.resolve_contradiction(
            contradiction_id=contradiction_id,
            winning_assertion_id=winning_assertion_id,
            resolution_evidence=verification_evidence,
        )

        # Update winning assertion
        winning_orm = await self.uow.world_assertions.get_assertion(winning_assertion_id)
        if winning_orm:
            await self.uow.world_assertions.update_assertion_with_version(
                assertion_id=winning_assertion_id,
                expected_version=winning_orm.assertion_version,
                new_status=AssertionStatus.ACTIVE.value,
            )

        # Update losing assertions to REJECTED
        for a_id in c.assertion_ids:
            if a_id != winning_assertion_id:
                losing_orm = await self.uow.world_assertions.get_assertion(a_id)
                if losing_orm:
                    await self.uow.world_assertions.update_assertion_with_version(
                        assertion_id=a_id,
                        expected_version=losing_orm.assertion_version,
                        new_status=AssertionStatus.REJECTED.value,
                    )

        if self.event_store:
            self.event_store.append_event(
                event_type=EventType.WORLD_CONTRADICTION_RESOLVED,
                actor_id="world_model",
                payload={
                    "contradiction_id": str(contradiction_id),
                    "winning_assertion_id": str(winning_assertion_id),
                    "verification_evidence": verification_evidence,
                },
            )

        updated_c = await self.uow.world_contradictions.get_contradiction(contradiction_id)
        assert updated_c is not None
        return updated_c
