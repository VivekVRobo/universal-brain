"""
Universal Brain - World Model & Perception Repositories
Implements Section 116 of Milestone M8 Specification (Dual SQLite WAL & PostgreSQL).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.persistence.models import (
    EntityAliasORM,
    EntityResolutionHistoryORM,
    ObservationORM,
    ObservationSourceORM,
    SourceSessionORM,
    WorldContradictionORM,
    WorldEntityORM,
    WorldEventORM,
    WorldProcessorLeaseORM,
    WorldPropertyAssertionORM,
    WorldRelationORM,
    WorldSnapshotORM,
    WorldSubscriptionORM,
    WorldWatchORM,
)
from universal_brain.world.errors import (
    ObservationReplayError,
    SourceFencedError,
    WorldVersionConflictError,
)
from universal_brain.world.schemas import (
    AssertionStateClass,
    AssertionStatus,
    EntityAlias,
    FreshnessStatus,
    Observation,
    ObservationSource,
    ObservationType,
    PrivacyClass,
    SourceHealth,
    SourceSession,
    SourceTrustClass,
    WatchStatus,
    WorldContradiction,
    WorldEntity,
    WorldEvent,
    WorldPropertyAssertion,
    WorldRelation,
    WorldSnapshot,
    WorldWatch,
)


class WorldRepositoryBase:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session


class ObservationRepository(WorldRepositoryBase):
    """Transactional repository for canonical, immutable observations."""

    async def save_observation(self, obs: Observation) -> None:
        orm = ObservationORM(
            observation_id=obs.observation_id,
            source_id=obs.source_id,
            source_session_id=obs.source_session_id,
            source_observation_id=obs.source_observation_id,
            source_sequence=obs.source_sequence,
            observation_type=obs.observation_type.value,
            subject_ref=obs.subject_ref,
            property_key=obs.property_key,
            value=obs.value,
            unit=obs.unit,
            coordinate_frame=obs.coordinate_frame,
            observed_at=obs.observed_at,
            received_at=obs.received_at,
            valid_from=obs.valid_from,
            valid_until=obs.valid_until,
            confidence=obs.confidence,
            uncertainty=obs.uncertainty,
            quality_flags=obs.quality_flags,
            privacy_class=obs.privacy_class.value,
            environment_mode=obs.environment_mode.value,
            raw_payload_ref=obs.raw_payload_ref,
            raw_payload_digest=obs.raw_payload_digest,
            schema_version=obs.schema_version,
            ontology_version=obs.ontology_version,
            created_at=obs.created_at,
            observation_digest=obs.observation_digest,
        )
        self.session.add(orm)
        await self.session.flush()

    async def get_observation(self, observation_id: UUID) -> Optional[Observation]:
        res = await self.session.execute(
            select(ObservationORM).where(ObservationORM.observation_id == observation_id)
        )
        orm = res.scalar_one_or_none()
        if not orm:
            return None
        return self._to_domain(orm)

    async def get_by_source_and_obs_id(self, source_id: str, source_obs_id: str) -> Optional[Observation]:
        res = await self.session.execute(
            select(ObservationORM).where(
                and_(
                    ObservationORM.source_id == source_id,
                    ObservationORM.source_observation_id == source_obs_id,
                )
            )
        )
        orm = res.scalar_one_or_none()
        if not orm:
            return None
        return self._to_domain(orm)

    async def list_observations(self, limit: int = 100) -> List[Observation]:
        res = await self.session.execute(
            select(ObservationORM).order_by(ObservationORM.observed_at.asc()).limit(limit)
        )
        return [self._to_domain(orm) for orm in res.scalars().all()]

    async def list_observations_for_subject(self, subject_ref: str) -> List[Observation]:
        res = await self.session.execute(
            select(ObservationORM)
            .where(ObservationORM.subject_ref == subject_ref)
            .order_by(ObservationORM.observed_at.asc())
        )
        return [self._to_domain(orm) for orm in res.scalars().all()]

    async def count_observations(self) -> int:
        res = await self.session.execute(select(ObservationORM))
        return len(res.scalars().all())

    def _to_domain(self, orm: ObservationORM) -> Observation:
        return Observation(
            observation_id=orm.observation_id,
            source_id=orm.source_id,
            source_session_id=orm.source_session_id,
            source_observation_id=orm.source_observation_id,
            source_sequence=orm.source_sequence,
            observation_type=ObservationType(orm.observation_type),
            subject_ref=orm.subject_ref,
            property_key=orm.property_key,
            value=orm.value,
            unit=orm.unit,
            coordinate_frame=orm.coordinate_frame,
            observed_at=orm.observed_at,
            received_at=orm.received_at,
            valid_from=orm.valid_from,
            valid_until=orm.valid_until,
            confidence=orm.confidence,
            uncertainty=orm.uncertainty,
            quality_flags=orm.quality_flags,
            privacy_class=PrivacyClass(orm.privacy_class),
            raw_payload_ref=orm.raw_payload_ref,
            raw_payload_digest=orm.raw_payload_digest,
            schema_version=orm.schema_version,
            ontology_version=orm.ontology_version,
            created_at=orm.created_at,
            observation_digest=orm.observation_digest,
        )


class ObservationSourceRepository(WorldRepositoryBase):
    """Source registry & epoch-fenced source sessions."""

    async def register_source(self, src: ObservationSource) -> None:
        orm = ObservationSourceORM(
            source_id=src.source_id,
            source_type=src.source_type.value,
            canonical_name=src.canonical_name,
            adapter_type=src.adapter_type,
            trust_class=src.trust_class.value,
            allowed_types=[t.value for t in src.allowed_types],
            allowed_entity_scopes=src.allowed_entity_scopes,
            freshness_policy=src.freshness_policy,
            authentication_token=src.authentication_token,
            registered_at=src.registered_at,
            revoked_at=src.revoked_at,
            health=src.health.value,
            source_version=src.source_version,
        )
        self.session.add(orm)
        await self.session.flush()

    async def get_source(self, source_id: str) -> Optional[ObservationSource]:
        res = await self.session.execute(
            select(ObservationSourceORM).where(ObservationSourceORM.source_id == source_id)
        )
        orm = res.scalar_one_or_none()
        if not orm:
            return None
        return ObservationSource(
            source_id=orm.source_id,
            source_type=orm.source_type,
            canonical_name=orm.canonical_name,
            adapter_type=orm.adapter_type,
            trust_class=SourceTrustClass(orm.trust_class),
            allowed_types=[ObservationType(t) for t in orm.allowed_types],
            allowed_entity_scopes=orm.allowed_entity_scopes,
            freshness_policy=orm.freshness_policy,
            authentication_token=orm.authentication_token,
            registered_at=orm.registered_at,
            revoked_at=orm.revoked_at,
            health=SourceHealth(orm.health),
            source_version=orm.source_version,
        )

    async def update_source_health(self, source_id: str, health: str) -> None:
        await self.session.execute(
            update(ObservationSourceORM)
            .where(ObservationSourceORM.source_id == source_id)
            .values(health=health)
        )
        await self.session.flush()

    async def create_session(self, sess: SourceSession) -> None:
        orm = SourceSessionORM(
            source_session_id=sess.source_session_id,
            source_id=sess.source_id,
            kernel_epoch=sess.kernel_epoch,
            started_at=sess.started_at,
            expires_at=sess.expires_at,
            protocol_version=sess.protocol_version,
            credential_binding=sess.credential_binding,
            status=sess.status,
        )
        self.session.add(orm)
        await self.session.flush()

    async def get_session(self, session_id: UUID) -> Optional[SourceSession]:
        res = await self.session.execute(
            select(SourceSessionORM).where(SourceSessionORM.source_session_id == session_id)
        )
        orm = res.scalar_one_or_none()
        if not orm:
            return None
        return SourceSession(
            source_session_id=orm.source_session_id,
            source_id=orm.source_id,
            kernel_epoch=orm.kernel_epoch,
            started_at=orm.started_at,
            expires_at=orm.expires_at,
            protocol_version=orm.protocol_version,
            credential_binding=orm.credential_binding,
            status=orm.status,
        )


class WorldEntityRepository(WorldRepositoryBase):
    """Durable entities, aliases, and resolution history."""

    async def create_entity(self, entity: WorldEntity) -> None:
        orm = WorldEntityORM(
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            canonical_name=entity.canonical_name,
            identity_attributes=entity.identity_attributes,
            privacy_class=entity.privacy_class.value,
            created_at=entity.created_at,
            retired_at=entity.retired_at,
            status=entity.status,
            entity_version=entity.entity_version,
            ontology_version=entity.ontology_version,
            merged_into=entity.merged_into,
        )
        self.session.add(orm)
        await self.session.flush()

    async def get_entity(self, entity_id: str) -> Optional[WorldEntity]:
        res = await self.session.execute(
            select(WorldEntityORM).where(WorldEntityORM.entity_id == entity_id)
        )
        orm = res.scalar_one_or_none()
        if not orm:
            return None
        return WorldEntity(
            entity_id=orm.entity_id,
            entity_type=orm.entity_type,
            canonical_name=orm.canonical_name,
            identity_attributes=orm.identity_attributes,
            privacy_class=PrivacyClass(orm.privacy_class),
            created_at=orm.created_at,
            retired_at=orm.retired_at,
            status=orm.status,
            entity_version=orm.entity_version,
            ontology_version=orm.ontology_version,
            merged_into=orm.merged_into,
        )

    async def update_entity_with_version(
        self,
        entity_id: str,
        expected_version: int,
        new_status: str = "ACTIVE",
        merged_into: Optional[str] = None,
    ) -> None:
        await self.session.flush()
        res = await self.session.execute(
            update(WorldEntityORM)
            .where(
                and_(
                    WorldEntityORM.entity_id == entity_id,
                    WorldEntityORM.entity_version == expected_version,
                )
            )
            .values(
                status=new_status,
                merged_into=merged_into,
                entity_version=expected_version + 1,
            )
        )
        if res.rowcount == 0:
            existing = await self.get_entity(entity_id)
            curr = existing.entity_version if existing else "NON_EXISTENT"
            raise WorldVersionConflictError(
                f"Optimistic concurrency failure updating entity {entity_id}: expected {expected_version}, was {curr}",
                {"entity_id": entity_id, "expected_version": expected_version, "current_version": curr},
            )
        await self.session.flush()

    async def list_entities(self) -> List[WorldEntity]:
        res = await self.session.execute(select(WorldEntityORM).order_by(WorldEntityORM.created_at.asc()))
        return [
            WorldEntity(
                entity_id=orm.entity_id,
                entity_type=orm.entity_type,
                canonical_name=orm.canonical_name,
                identity_attributes=orm.identity_attributes,
                privacy_class=PrivacyClass(orm.privacy_class),
                created_at=orm.created_at,
                retired_at=orm.retired_at,
                status=orm.status,
                entity_version=orm.entity_version,
                ontology_version=orm.ontology_version,
                merged_into=orm.merged_into,
            )
            for orm in res.scalars().all()
        ]

    async def add_alias(self, alias: EntityAlias) -> None:
        orm = EntityAliasORM(
            alias_id=alias.alias_id,
            alias=alias.alias,
            entity_id=alias.entity_id,
            source_id=alias.source_id,
            confidence=alias.confidence,
            created_at=alias.created_at,
        )
        self.session.add(orm)
        await self.session.flush()

    async def get_entity_by_alias(self, alias: str) -> Optional[WorldEntity]:
        res = await self.session.execute(
            select(EntityAliasORM).where(EntityAliasORM.alias == alias)
        )
        alias_orm = res.scalar_one_or_none()
        if not alias_orm:
            return None
        return await self.get_entity(alias_orm.entity_id)

    async def record_resolution_history(
        self, event_type: str, source_id: str, target_id: Optional[str], evidence_refs: List[str]
    ) -> None:
        from uuid import uuid4
        orm = EntityResolutionHistoryORM(
            history_id=uuid4(),
            event_type=event_type,
            source_entity_id=source_id,
            target_entity_id=target_id,
            evidence_refs=evidence_refs,
            occurred_at=datetime.now(timezone.utc),
        )
        self.session.add(orm)
        await self.session.flush()


class WorldAssertionRepository(WorldRepositoryBase):
    """Bitemporal world property assertions."""

    async def create_assertion(self, a: WorldPropertyAssertion) -> None:
        orm = WorldPropertyAssertionORM(
            assertion_id=a.assertion_id,
            entity_id=a.entity_id,
            property_key=a.property_key,
            value=a.value,
            unit=a.unit,
            coordinate_frame=a.coordinate_frame,
            state_class=a.state_class.value,
            valid_from=a.valid_from,
            valid_until=a.valid_until,
            transaction_from=a.transaction_from,
            transaction_until=a.transaction_until,
            confidence=a.confidence,
            uncertainty=a.uncertainty,
            supporting_observations=[str(x) for x in a.supporting_observations],
            contradicting_observations=[str(x) for x in a.contradicting_observations],
            freshness_status=a.freshness_status.value,
            fusion_policy_version=a.fusion_policy_version,
            inference_rule_version=a.inference_rule_version,
            ontology_version=a.ontology_version,
            privacy_class=a.privacy_class.value,
            status=a.status.value,
            assertion_version=a.assertion_version,
        )
        self.session.add(orm)
        await self.session.flush()

    async def get_assertion(self, assertion_id: UUID) -> Optional[WorldPropertyAssertion]:
        res = await self.session.execute(
            select(WorldPropertyAssertionORM).where(WorldPropertyAssertionORM.assertion_id == assertion_id)
        )
        orm = res.scalar_one_or_none()
        if not orm:
            return None
        return self._to_domain(orm)

    async def get_active_assertion(self, entity_id: str, property_key: str) -> Optional[WorldPropertyAssertion]:
        res = await self.session.execute(
            select(WorldPropertyAssertionORM).where(
                and_(
                    WorldPropertyAssertionORM.entity_id == entity_id,
                    WorldPropertyAssertionORM.property_key == property_key,
                    WorldPropertyAssertionORM.status == "ACTIVE",
                )
            ).order_by(WorldPropertyAssertionORM.valid_from.desc())
        )
        orm = res.scalars().first()
        if not orm:
            return None
        return self._to_domain(orm)

    async def update_assertion_with_version(
        self,
        assertion_id: UUID,
        expected_version: int,
        new_status: str,
        new_confidence: Optional[float] = None,
        new_freshness: Optional[str] = None,
    ) -> None:
        await self.session.flush()
        values: Dict[str, Any] = {
            "status": new_status,
            "assertion_version": expected_version + 1,
        }
        if new_confidence is not None:
            values["confidence"] = new_confidence
        if new_freshness is not None:
            values["freshness_status"] = new_freshness

        res = await self.session.execute(
            update(WorldPropertyAssertionORM)
            .where(
                and_(
                    WorldPropertyAssertionORM.assertion_id == assertion_id,
                    WorldPropertyAssertionORM.assertion_version == expected_version,
                )
            )
            .values(**values)
        )
        if res.rowcount == 0:
            existing = await self.get_assertion(assertion_id)
            curr = existing.assertion_version if existing else "NON_EXISTENT"
            raise WorldVersionConflictError(
                f"Optimistic concurrency failure updating assertion {assertion_id}: expected {expected_version}, was {curr}",
                {"assertion_id": str(assertion_id), "expected_version": expected_version, "current_version": curr},
            )
        await self.session.flush()

    async def list_assertions_for_entity(self, entity_id: str) -> List[WorldPropertyAssertion]:
        res = await self.session.execute(
            select(WorldPropertyAssertionORM)
            .where(WorldPropertyAssertionORM.entity_id == entity_id)
            .order_by(WorldPropertyAssertionORM.valid_from.desc())
        )
        return [self._to_domain(orm) for orm in res.scalars().all()]

    async def list_all_active_assertions(self) -> List[WorldPropertyAssertion]:
        res = await self.session.execute(
            select(WorldPropertyAssertionORM).where(WorldPropertyAssertionORM.status == "ACTIVE")
        )
        return [self._to_domain(orm) for orm in res.scalars().all()]

    def _to_domain(self, orm: WorldPropertyAssertionORM) -> WorldPropertyAssertion:
        return WorldPropertyAssertion(
            assertion_id=orm.assertion_id,
            entity_id=orm.entity_id,
            property_key=orm.property_key,
            value=orm.value,
            unit=orm.unit,
            coordinate_frame=orm.coordinate_frame,
            state_class=AssertionStateClass(orm.state_class),
            valid_from=orm.valid_from,
            valid_until=orm.valid_until,
            transaction_from=orm.transaction_from,
            transaction_until=orm.transaction_until,
            confidence=orm.confidence,
            uncertainty=orm.uncertainty,
            supporting_observations=[UUID(x) for x in orm.supporting_observations],
            contradicting_observations=[UUID(x) for x in orm.contradicting_observations],
            freshness_status=FreshnessStatus(orm.freshness_status),
            fusion_policy_version=orm.fusion_policy_version,
            inference_rule_version=orm.inference_rule_version,
            ontology_version=orm.ontology_version,
            privacy_class=PrivacyClass(orm.privacy_class),
            status=AssertionStatus(orm.status),
            assertion_version=orm.assertion_version,
        )


class WorldRelationRepository(WorldRepositoryBase):
    """Directed temporal relationships."""

    async def create_relation(self, r: WorldRelation) -> None:
        orm = WorldRelationORM(
            relation_id=r.relation_id,
            source_entity=r.source_entity,
            relation_type=r.relation_type,
            target_entity=r.target_entity,
            valid_from=r.valid_from,
            valid_until=r.valid_until,
            transaction_from=r.transaction_from,
            transaction_until=r.transaction_until,
            state_class=r.state_class.value,
            confidence=r.confidence,
            uncertainty=r.uncertainty,
            evidence_refs=r.evidence_refs,
            relation_version=r.relation_version,
            ontology_version=r.ontology_version,
            status=r.status,
        )
        self.session.add(orm)
        await self.session.flush()

    async def get_relation(self, relation_id: UUID) -> Optional[WorldRelation]:
        res = await self.session.execute(
            select(WorldRelationORM).where(WorldRelationORM.relation_id == relation_id)
        )
        orm = res.scalar_one_or_none()
        if not orm:
            return None
        return WorldRelation(
            relation_id=orm.relation_id,
            source_entity=orm.source_entity,
            relation_type=orm.relation_type,
            target_entity=orm.target_entity,
            valid_from=orm.valid_from,
            valid_until=orm.valid_until,
            transaction_from=orm.transaction_from,
            transaction_until=orm.transaction_until,
            state_class=AssertionStateClass(orm.state_class),
            confidence=orm.confidence,
            uncertainty=orm.uncertainty,
            evidence_refs=orm.evidence_refs,
            relation_version=orm.relation_version,
            ontology_version=orm.ontology_version,
            status=orm.status,
        )

    async def list_relations_for_entity(self, entity_id: str) -> List[WorldRelation]:
        res = await self.session.execute(
            select(WorldRelationORM).where(
                and_(
                    WorldRelationORM.source_entity == entity_id,
                    WorldRelationORM.status == "ACTIVE",
                )
            )
        )
        return [
            WorldRelation(
                relation_id=orm.relation_id,
                source_entity=orm.source_entity,
                relation_type=orm.relation_type,
                target_entity=orm.target_entity,
                valid_from=orm.valid_from,
                valid_until=orm.valid_until,
                transaction_from=orm.transaction_from,
                transaction_until=orm.transaction_until,
                state_class=AssertionStateClass(orm.state_class),
                confidence=orm.confidence,
                uncertainty=orm.uncertainty,
                evidence_refs=orm.evidence_refs,
                relation_version=orm.relation_version,
                ontology_version=orm.ontology_version,
                status=orm.status,
            )
            for orm in res.scalars().all()
        ]

    async def end_relation(self, relation_id: UUID, valid_until: datetime) -> None:
        await self.session.execute(
            update(WorldRelationORM)
            .where(WorldRelationORM.relation_id == relation_id)
            .values(valid_until=valid_until, status="SUPERSEDED")
        )
        await self.session.flush()


class WorldContradictionRepository(WorldRepositoryBase):
    """Contradiction tracking & resolution."""

    async def create_contradiction(self, c: WorldContradiction) -> None:
        orm = WorldContradictionORM(
            contradiction_id=c.contradiction_id,
            entity_id=c.entity_id,
            property_key=c.property_key,
            assertion_ids=[str(x) for x in c.assertion_ids],
            temporal_overlap=c.temporal_overlap,
            severity=c.severity.value,
            detected_at=c.detected_at,
            resolution_status=c.resolution_status.value,
            resolution_evidence=c.resolution_evidence,
            winning_assertion_id=c.winning_assertion_id,
        )
        self.session.add(orm)
        await self.session.flush()

    async def get_contradiction(self, contradiction_id: UUID) -> Optional[WorldContradiction]:
        res = await self.session.execute(
            select(WorldContradictionORM).where(WorldContradictionORM.contradiction_id == contradiction_id)
        )
        orm = res.scalar_one_or_none()
        if not orm:
            return None
        return self._to_domain(orm)

    async def list_open_contradictions(self) -> List[WorldContradiction]:
        res = await self.session.execute(
            select(WorldContradictionORM).where(WorldContradictionORM.resolution_status == "OPEN")
        )
        return [self._to_domain(orm) for orm in res.scalars().all()]

    async def resolve_contradiction(
        self, contradiction_id: UUID, winning_assertion_id: UUID, resolution_evidence: str
    ) -> None:
        await self.session.execute(
            update(WorldContradictionORM)
            .where(WorldContradictionORM.contradiction_id == contradiction_id)
            .values(
                resolution_status="RESOLVED",
                winning_assertion_id=winning_assertion_id,
                resolution_evidence=resolution_evidence,
            )
        )
        await self.session.flush()

    def _to_domain(self, orm: WorldContradictionORM) -> WorldContradiction:
        from universal_brain.world.schemas import ContradictionSeverity, ResolutionStatus
        return WorldContradiction(
            contradiction_id=orm.contradiction_id,
            entity_id=orm.entity_id,
            property_key=orm.property_key,
            assertion_ids=[UUID(x) for x in orm.assertion_ids],
            temporal_overlap=orm.temporal_overlap,
            severity=ContradictionSeverity(orm.severity),
            detected_at=orm.detected_at,
            resolution_status=ResolutionStatus(orm.resolution_status),
            resolution_evidence=orm.resolution_evidence,
            winning_assertion_id=orm.winning_assertion_id,
        )


class WorldWatchRepository(WorldRepositoryBase):
    """World watch persistence and condition status."""

    async def create_watch(self, w: WorldWatch) -> None:
        orm = WorldWatchORM(
            watch_id=w.watch_id,
            mission_id=w.mission_id,
            task_id=w.task_id,
            entity_id=w.entity_id,
            property_key=w.property_key,
            expected_value=w.expected_value,
            operator=w.operator,
            required_freshness=w.required_freshness.value,
            required_state_class=w.required_state_class.value if w.required_state_class else None,
            debounce_sec=w.debounce_sec,
            created_at=w.created_at,
            expires_at=w.expires_at,
            status=w.status.value,
            idempotency_key=w.idempotency_key,
            watch_version=w.watch_version,
        )
        self.session.add(orm)

    async def get_watch(self, watch_id: UUID) -> Optional[WorldWatch]:
        res = await self.session.execute(
            select(WorldWatchORM).where(WorldWatchORM.watch_id == watch_id)
        )
        orm = res.scalar_one_or_none()
        if not orm:
            return None
        return self._to_domain(orm)

    async def list_active_watches(self) -> List[WorldWatch]:
        res = await self.session.execute(
            select(WorldWatchORM).where(WorldWatchORM.status == "ACTIVE")
        )
        return [self._to_domain(orm) for orm in res.scalars().all()]

    async def update_watch_status(self, watch_id: UUID, status: str) -> None:
        await self.session.execute(
            update(WorldWatchORM).where(WorldWatchORM.watch_id == watch_id).values(status=status)
        )

    def _to_domain(self, orm: WorldWatchORM) -> WorldWatch:
        return WorldWatch(
            watch_id=orm.watch_id,
            mission_id=orm.mission_id,
            task_id=orm.task_id,
            entity_id=orm.entity_id,
            property_key=orm.property_key,
            expected_value=orm.expected_value,
            operator=orm.operator,
            required_freshness=FreshnessStatus(orm.required_freshness),
            required_state_class=AssertionStateClass(orm.required_state_class) if orm.required_state_class else None,
            debounce_sec=orm.debounce_sec,
            created_at=orm.created_at,
            expires_at=orm.expires_at,
            status=WatchStatus(orm.status),
            idempotency_key=orm.idempotency_key,
            watch_version=orm.watch_version,
        )


class WorldSnapshotRepository(WorldRepositoryBase):
    """World snapshot envelopes."""

    async def save_snapshot(self, snap: WorldSnapshot) -> None:
        orm = WorldSnapshotORM(
            snapshot_id=snap.snapshot_id,
            scope=snap.scope,
            observation_head=snap.observation_head,
            processor_cursor=snap.processor_cursor,
            entity_versions=snap.entity_versions,
            assertion_versions=snap.assertion_versions,
            relation_versions=snap.relation_versions,
            ontology_version=snap.ontology_version,
            fusion_policy_version=snap.fusion_policy_version,
            created_at=snap.created_at,
            snapshot_digest=snap.snapshot_digest,
        )
        self.session.add(orm)

    async def get_snapshot(self, snapshot_id: UUID) -> Optional[WorldSnapshot]:
        res = await self.session.execute(
            select(WorldSnapshotORM).where(WorldSnapshotORM.snapshot_id == snapshot_id)
        )
        orm = res.scalar_one_or_none()
        if not orm:
            return None
        return WorldSnapshot(
            snapshot_id=orm.snapshot_id,
            scope=orm.scope,
            observation_head=orm.observation_head,
            processor_cursor=orm.processor_cursor,
            entity_versions=orm.entity_versions,
            assertion_versions=orm.assertion_versions,
            relation_versions=orm.relation_versions,
            ontology_version=orm.ontology_version,
            fusion_policy_version=orm.fusion_policy_version,
            created_at=orm.created_at,
            snapshot_digest=orm.snapshot_digest,
        )

    async def get_latest_snapshot(self) -> Optional[WorldSnapshot]:
        res = await self.session.execute(
            select(WorldSnapshotORM).order_by(WorldSnapshotORM.created_at.desc()).limit(1)
        )
        orm = res.scalar_one_or_none()
        if not orm:
            return None
        return WorldSnapshot(
            snapshot_id=orm.snapshot_id,
            scope=orm.scope,
            observation_head=orm.observation_head,
            processor_cursor=orm.processor_cursor,
            entity_versions=orm.entity_versions,
            assertion_versions=orm.assertion_versions,
            relation_versions=orm.relation_versions,
            ontology_version=orm.ontology_version,
            fusion_policy_version=orm.fusion_policy_version,
            created_at=orm.created_at,
            snapshot_digest=orm.snapshot_digest,
        )


class WorldProcessorLeaseRepository(WorldRepositoryBase):
    """Epoch-fenced authoritative processor lease."""

    async def acquire_or_renew_lease(
        self,
        partition_key: str,
        processor_id: str,
        generation: int,
        epoch: int,
        duration_sec: int = 30,
    ) -> bool:
        from datetime import timedelta
        from uuid import uuid4
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=duration_sec)

        res = await self.session.execute(
            select(WorldProcessorLeaseORM).where(WorldProcessorLeaseORM.partition_key == partition_key)
        )
        existing = res.scalar_one_or_none()
        if not existing:
            lease = WorldProcessorLeaseORM(
                lease_id=uuid4(),
                partition_key=partition_key,
                processor_id=processor_id,
                lease_generation=generation,
                kernel_epoch=epoch,
                acquired_at=now,
                heartbeat_at=now,
                expires_at=expires,
                status="ACTIVE",
            )
            self.session.add(lease)
            await self.session.flush()
            return True

        # Check fencing
        if existing.kernel_epoch > epoch:
            return False
        if existing.kernel_epoch == epoch and existing.lease_generation > generation:
            return False

        existing.processor_id = processor_id
        existing.lease_generation = generation
        existing.kernel_epoch = epoch
        existing.heartbeat_at = now
        existing.expires_at = expires
        existing.status = "ACTIVE"
        await self.session.flush()
        return True

    async def get_lease(self, partition_key: str = "DEFAULT") -> Optional[WorldProcessorLeaseORM]:
        res = await self.session.execute(
            select(WorldProcessorLeaseORM).where(WorldProcessorLeaseORM.partition_key == partition_key)
        )
        return res.scalar_one_or_none()
