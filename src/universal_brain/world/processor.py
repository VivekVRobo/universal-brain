"""
Universal Brain - Authoritative World Processing Cell & Projection Engine
Implements Sections 54-57 of Milestone M8 Specification (M8-INV-19).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from universal_brain.kernel.event_store import EventStore

if TYPE_CHECKING:
    from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.assertions import WorldAssertionManager
from universal_brain.world.changes import WorldChangeDetector
from universal_brain.world.contradictions import WorldContradictionEngine
from universal_brain.world.entities import WorldEntityManager
from universal_brain.world.errors import WorldProcessorFencedError
from universal_brain.world.freshness import FreshnessEngine
from universal_brain.world.fusion import ObservationFusionEngine
from universal_brain.world.schemas import (
    AssertionStateClass,
    Observation,
    WorldPropertyAssertion,
    WorldWatch,
)
from universal_brain.world.subscriptions import WorldSubscriptionRegistry
from universal_brain.world.watches import WorldWatchManager


class WorldProcessingCell:
    """
    Authoritative projection processor that consumes raw observations,
    updates entities and bitemporal assertions, detects contradictions and changes,
    evaluates world watches, and dispatches targeted mission wakeups.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        processor_id: str = "main_processor",
        lease_generation: int = 1,
        kernel_epoch: int = 1,
        event_store: Optional[EventStore] = None,
        subscription_registry: Optional[WorldSubscriptionRegistry] = None,
    ) -> None:
        self.uow = uow
        self.processor_id = processor_id
        self.lease_generation = lease_generation
        self.kernel_epoch = kernel_epoch
        self.event_store = event_store
        self.subscription_registry = subscription_registry or WorldSubscriptionRegistry()

        self.entity_mgr = WorldEntityManager(uow)
        self.assertion_mgr = WorldAssertionManager(uow)
        self.freshness_engine = FreshnessEngine()
        self.fusion_engine = ObservationFusionEngine()
        self.contradiction_engine = WorldContradictionEngine(uow, event_store)
        self.change_detector = WorldChangeDetector(event_store)
        self.watch_mgr = WorldWatchManager(uow, event_store)

    async def verify_processor_lease(self) -> None:
        """Verifies this processor is not fenced by an epoch advance or generation bump."""
        assert self.uow.world_processor_leases is not None
        lease = await self.uow.world_processor_leases.get_lease("DEFAULT")
        if lease:
            if lease.kernel_epoch > self.kernel_epoch:
                raise WorldProcessorFencedError(
                    f"World processor fenced: processor epoch is {self.kernel_epoch}, but lease epoch is {lease.kernel_epoch}.",
                    {"processor_epoch": self.kernel_epoch, "lease_epoch": lease.kernel_epoch},
                )
            if lease.kernel_epoch == self.kernel_epoch and lease.lease_generation > self.lease_generation:
                raise WorldProcessorFencedError(
                    f"World processor fenced: processor generation is {self.lease_generation}, but active lease is generation {lease.lease_generation}.",
                    {"processor_generation": self.lease_generation, "lease_generation": lease.lease_generation},
                )

    async def process_observation(
        self,
        obs: Observation,
    ) -> Dict[str, Any]:
        """
        Projects an incoming canonical observation into the World Model.
        """
        await self.verify_processor_lease()

        # 1. Resolve or create entity
        entity = await self.entity_mgr.resolve_entity(obs.subject_ref)
        if not entity:
            entity = await self.entity_mgr.create_entity(
                entity_id=obs.subject_ref,
                entity_type="GENERIC",
                canonical_name=obs.subject_ref,
                privacy_class=obs.privacy_class,
                ontology_version=obs.ontology_version,
            )

        # 2. Get current active assertion for entity & property
        prev_assertion = await self.assertion_mgr.get_active_assertion(entity.entity_id, obs.property_key)
        prev_val = prev_assertion.value if prev_assertion else None

        # 3. Check contradiction if previous active assertion exists with different value
        if prev_assertion and prev_assertion.value != obs.value:
            # Check if there is a contradiction
            dummy_new_a = WorldPropertyAssertion(
                entity_id=entity.entity_id,
                property_key=obs.property_key,
                value=obs.value,
                valid_from=obs.valid_from,
                valid_until=obs.valid_until,
            )
            # If both have same confidence or strong claims, check contradiction
            if prev_assertion.confidence >= 0.8 and obs.confidence >= 0.8:
                await self.contradiction_engine.check_contradiction(prev_assertion, dummy_new_a)

        # 4. Assert new property value
        new_assertion = await self.assertion_mgr.assert_property(
            entity_id=entity.entity_id,
            property_key=obs.property_key,
            value=obs.value,
            unit=obs.unit,
            coordinate_frame=obs.coordinate_frame,
            state_class=AssertionStateClass.OBSERVED,
            valid_from=obs.valid_from,
            valid_until=obs.valid_until,
            confidence=obs.confidence,
            uncertainty=obs.uncertainty,
            supporting_observations=[obs.observation_id],
            privacy_class=obs.privacy_class,
            ontology_version=obs.ontology_version,
        )

        # 5. Detect state changes
        world_event = self.change_detector.process_change(
            entity_id=entity.entity_id,
            property_key=obs.property_key,
            prev_val=prev_val,
            new_val=obs.value,
            observed_at=obs.observed_at,
            evidence_refs=[str(obs.observation_id)],
        )

        # 6. Evaluate watches
        triggered_watches = await self.watch_mgr.evaluate_watches_for_assertion(new_assertion)

        # 7. Notify subscribed missions
        notified_missions = []
        if world_event:
            subscribers = self.subscription_registry.get_subscribers(entity.entity_id, obs.property_key)
            notified_missions = subscribers

        return {
            "entity_id": entity.entity_id,
            "assertion_id": new_assertion.assertion_id,
            "world_event": world_event,
            "triggered_watches": [w.watch_id for w in triggered_watches],
            "notified_missions": notified_missions,
        }
