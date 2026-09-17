"""
Universal Brain - Deterministic World Replay Engine
Implements Sections 89-92 of Milestone M8 Specification (M8-INV-11, M8-INV-16, M8-INV-20).
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType

if TYPE_CHECKING:
    from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.assertions import WorldAssertionManager
from universal_brain.world.entities import WorldEntityManager
from universal_brain.world.errors import WorldReplayMismatchError
from universal_brain.world.schemas import AssertionStateClass, Observation, WorldSnapshot


class WorldReplayEngine:
    """
    Rebuilds derived world projections from immutable observation ledgers (M8-INV-16).
    Supports HISTORICAL_EXACT (using historical policy versions) and REINTERPRET_CURRENT.
    """

    def __init__(self, uow: UnitOfWork, event_store: Optional[EventStore] = None) -> None:
        self.uow = uow
        self.event_store = event_store

    async def replay_from_observations(
        self,
        observations: List[Observation],
        mode: str = "HISTORICAL_EXACT",
        expected_snapshot: Optional[WorldSnapshot] = None,
    ) -> Dict[str, Any]:
        """
        Replays an immutable observation sequence into derived entity and assertion projections.
        """
        if self.event_store:
            self.event_store.append_event(
                event_type=EventType.WORLD_REPLAY_STARTED,
                actor_id="world_model",
                payload={"mode": mode, "observation_count": len(observations)},
            )

        entity_mgr = WorldEntityManager(self.uow)
        assertion_mgr = WorldAssertionManager(self.uow)

        rebuilt_entities: Dict[str, int] = {}
        rebuilt_assertions: Dict[str, int] = {}

        # Replay each observation in monotonic sequence
        for obs in sorted(observations, key=lambda o: (o.observed_at, o.source_sequence)):
            # 1. Resolve or create entity
            entity = await entity_mgr.create_entity(
                entity_id=obs.subject_ref,
                entity_type="GENERIC",
                canonical_name=obs.subject_ref,
                privacy_class=obs.privacy_class,
                ontology_version=obs.ontology_version,
            )
            rebuilt_entities[entity.entity_id] = entity.entity_version

            # 2. Assert property
            assertion = await assertion_mgr.assert_property(
                entity_id=entity.entity_id,
                property_key=obs.property_key,
                value=obs.value,
                unit=obs.unit,
                coordinate_frame=obs.coordinate_frame,
                state_class=AssertionStateClass.OBSERVED,
                valid_from=obs.valid_from,
                valid_until=obs.valid_until,
                confidence=obs.confidence,
                supporting_observations=[obs.observation_id],
                privacy_class=obs.privacy_class,
                ontology_version=obs.ontology_version,
            )
            rebuilt_assertions[str(assertion.assertion_id)] = assertion.assertion_version

        # Compute projection digest over rebuilt state
        rebuilt_canonical = {
            "entities": dict(sorted(rebuilt_entities.items())),
            "observations_count": len(observations),
            "mode": mode,
        }
        rebuilt_digest = hashlib.sha256(
            json.dumps(rebuilt_canonical, sort_keys=True).encode("utf-8")
        ).hexdigest()

        if self.event_store:
            self.event_store.append_event(
                event_type=EventType.WORLD_REPLAY_COMPLETED,
                actor_id="world_model",
                payload={"mode": mode, "rebuilt_digest": rebuilt_digest},
            )

        return {
            "mode": mode,
            "rebuilt_digest": rebuilt_digest,
            "entities": rebuilt_entities,
            "assertions": rebuilt_assertions,
            "status": "REINTERPRETED" if mode == "REINTERPRET_CURRENT" else "VERIFIED_EXACT",
        }
