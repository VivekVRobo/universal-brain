"""
Universal Brain - Canonical Observation Ingest Gate
Implements Sections 33-35, 52-53 of Milestone M8 Specification (M8-INV-02, M8-INV-03).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple
from uuid import UUID

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType

if TYPE_CHECKING:
    from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.errors import (
    ObservationIntegrityError,
    ObservationReplayError,
    ObservationValidationError,
    TemporalConsistencyError,
)
from universal_brain.world.ontology import WorldOntology
from universal_brain.world.schemas import Observation
from universal_brain.world.sessions import SourceSessionManager
from universal_brain.world.sources import ObservationSourceRegistry
from universal_brain.world.units import MeasurementUnitRegistry


class ObservationIngestGate:
    """
    Authoritative boundary for all external and internal observations.
    Enforces authentication, scope confinement, schema validation, unit safety,
    replay protection, and atomic persistence.
    """

    def __init__(
        self,
        source_registry: ObservationSourceRegistry,
        session_manager: SourceSessionManager,
        ontology: Optional[WorldOntology] = None,
    ) -> None:
        self.source_registry = source_registry
        self.session_manager = session_manager
        self.ontology = ontology or WorldOntology.get_canonical_ontology()

    async def ingest_observation(
        self,
        obs: Observation,
        auth_token: str,
        uow: UnitOfWork,
        event_store: Optional[EventStore] = None,
    ) -> Tuple[Observation, bool]:
        """
        Validates, deduplicates, and persists an observation atomically.
        Returns (observation, is_new).
        """
        # 1. Authenticate source
        self.source_registry.authenticate_source(obs.source_id, auth_token)

        # 2. Validate session and epoch
        self.session_manager.validate_session(obs.source_session_id)

        # 3. Validate source scope
        self.source_registry.validate_scope(
            source_id=obs.source_id,
            obs_type=obs.observation_type,
            subject_ref=obs.subject_ref,
            property_key=obs.property_key,
        )

        # 4. Validate temporal consistency
        if obs.valid_until and obs.valid_until < obs.valid_from:
            raise TemporalConsistencyError(
                f"Invalid temporal interval: valid_until ({obs.valid_until.isoformat()}) cannot be before valid_from ({obs.valid_from.isoformat()}).",
                {"valid_from": obs.valid_from.isoformat(), "valid_until": obs.valid_until.isoformat()},
            )

        # 5. Validate ontology rules & units
        if obs.unit:
            MeasurementUnitRegistry.get_dimension(obs.unit)
        self.ontology.validate_property_assignment(
            entity_class="",
            property_key=obs.property_key,
            value=obs.value,
            unit=obs.unit,
            coordinate_frame=obs.coordinate_frame,
        )

        # 6. Verify or calculate digest
        computed_digest = obs.calculate_digest()
        if obs.observation_digest and obs.observation_digest != computed_digest:
            raise ObservationIntegrityError(
                f"Observation digest mismatch: claimed {obs.observation_digest}, computed {computed_digest}.",
                {"claimed": obs.observation_digest, "computed": computed_digest},
            )
        obs.observation_digest = computed_digest

        # 7. Check replay & deduplication
        assert uow.observations is not None
        existing = await uow.observations.get_by_source_and_obs_id(
            source_id=obs.source_id,
            source_obs_id=obs.source_observation_id,
        )
        if existing:
            if existing.observation_digest == obs.observation_digest:
                # Safe idempotent deduplication
                return existing, False
            else:
                # Replay attack with same ID but different payload
                raise ObservationReplayError(
                    f"Observation ID '{obs.source_observation_id}' for source '{obs.source_id}' already exists with different payload digest.",
                    {
                        "source_id": obs.source_id,
                        "source_observation_id": obs.source_observation_id,
                        "existing_digest": existing.observation_digest,
                        "new_digest": obs.observation_digest,
                    },
                )

        # 8. Persist observation to immutable ledger
        await uow.observations.save_observation(obs)

        # 9. Optionally append to canonical EventStore
        if event_store:
            event_store.append_event(
                event_type=EventType.OBSERVATION_INGESTED,
                actor_id="world_ingest",
                payload={
                    "observation_id": str(obs.observation_id),
                    "source_id": obs.source_id,
                    "subject_ref": obs.subject_ref,
                    "property_key": obs.property_key,
                    "observation_digest": obs.observation_digest,
                },
            )

        return obs, True
