"""
Universal Brain - Bitemporal World Property Assertions
Implements Sections 33-38 of Milestone M8 Specification (M8-INV-01, M8-INV-02).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.schemas import (
    AssertionStateClass,
    AssertionStatus,
    FreshnessStatus,
    PrivacyClass,
    WorldPropertyAssertion,
)


class WorldAssertionManager:
    """
    Manages bitemporal property assertions across external valid time
    and internal transaction time, enforcing strict epistemic state classes.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def assert_property(
        self,
        entity_id: str,
        property_key: str,
        value: Any,
        unit: Optional[str] = None,
        coordinate_frame: Optional[str] = None,
        state_class: AssertionStateClass = AssertionStateClass.OBSERVED,
        valid_from: Optional[datetime] = None,
        valid_until: Optional[datetime] = None,
        confidence: float = 1.0,
        uncertainty: Optional[Dict[str, Any]] = None,
        supporting_observations: Optional[List[UUID]] = None,
        contradicting_observations: Optional[List[UUID]] = None,
        freshness_status: FreshnessStatus = FreshnessStatus.FRESH,
        fusion_policy_version: Optional[int] = None,
        inference_rule_version: Optional[int] = None,
        ontology_version: int = 1,
        privacy_class: PrivacyClass = PrivacyClass.INTERNAL,
    ) -> WorldPropertyAssertion:
        assert self.uow.world_assertions is not None
        now = datetime.now(timezone.utc)
        v_from = valid_from or now

        # Supersede existing active assertion for this property if applicable
        existing = await self.uow.world_assertions.get_active_assertion(entity_id, property_key)
        if existing and existing.status == AssertionStatus.ACTIVE:
            await self.uow.world_assertions.update_assertion_with_version(
                assertion_id=existing.assertion_id,
                expected_version=existing.assertion_version,
                new_status=AssertionStatus.SUPERSEDED.value,
            )

        assertion = WorldPropertyAssertion(
            assertion_id=uuid4(),
            entity_id=entity_id,
            property_key=property_key,
            value=value,
            unit=unit,
            coordinate_frame=coordinate_frame,
            state_class=state_class,
            valid_from=v_from,
            valid_until=valid_until,
            transaction_from=now,
            transaction_until=None,
            confidence=confidence,
            uncertainty=uncertainty,
            supporting_observations=supporting_observations or [],
            contradicting_observations=contradicting_observations or [],
            freshness_status=freshness_status,
            fusion_policy_version=fusion_policy_version,
            inference_rule_version=inference_rule_version,
            ontology_version=ontology_version,
            privacy_class=privacy_class,
            status=AssertionStatus.ACTIVE,
            assertion_version=1,
        )

        await self.uow.world_assertions.create_assertion(assertion)
        return assertion

    async def get_active_assertion(
        self, entity_id: str, property_key: str
    ) -> Optional[WorldPropertyAssertion]:
        assert self.uow.world_assertions is not None
        return await self.uow.world_assertions.get_active_assertion(entity_id, property_key)

    async def list_assertions_for_entity(
        self, entity_id: str
    ) -> List[WorldPropertyAssertion]:
        assert self.uow.world_assertions is not None
        return await self.uow.world_assertions.list_assertions_for_entity(entity_id)

    async def query_at_valid_time(
        self, entity_id: str, property_key: str, event_time: datetime
    ) -> Optional[WorldPropertyAssertion]:
        """Bitemporal query: What applied in external reality at time T?"""
        assert self.uow.world_assertions is not None
        assertions = await self.uow.world_assertions.list_assertions_for_entity(entity_id)
        for a in assertions:
            if a.property_key == property_key:
                if a.valid_from <= event_time:
                    if a.valid_until is None or a.valid_until >= event_time:
                        return a
        return None

    async def query_at_transaction_time(
        self, entity_id: str, property_key: str, knowledge_time: datetime
    ) -> Optional[WorldPropertyAssertion]:
        """Bitemporal query: What did the Brain believe as of knowledge time T?"""
        assert self.uow.world_assertions is not None
        assertions = await self.uow.world_assertions.list_assertions_for_entity(entity_id)
        for a in assertions:
            if a.property_key == property_key:
                if a.transaction_from <= knowledge_time:
                    if a.transaction_until is None or a.transaction_until >= knowledge_time:
                        return a
        return None
