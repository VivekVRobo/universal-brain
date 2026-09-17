"""
Universal Brain - World Entity Identity & Resolution Manager
Implements Sections 27-32 of Milestone M8 Specification (M8-INV-21).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.errors import EntityResolutionConflictError, WorldVersionConflictError
from universal_brain.world.schemas import EntityAlias, PrivacyClass, WorldEntity


class WorldEntityManager:
    """
    Manages durable world entities, alias resolution, reversible merges,
    and entity splits. Preserves complete resolution lineage.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_entity(
        self,
        entity_id: str,
        entity_type: str,
        canonical_name: str,
        identity_attributes: Optional[Dict[str, Any]] = None,
        privacy_class: PrivacyClass = PrivacyClass.INTERNAL,
        ontology_version: int = 1,
    ) -> WorldEntity:
        assert self.uow.world_entities is not None
        existing = await self.uow.world_entities.get_entity(entity_id)
        if existing:
            return existing

        entity = WorldEntity(
            entity_id=entity_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            identity_attributes=identity_attributes or {},
            privacy_class=privacy_class,
            created_at=datetime.now(timezone.utc),
            status="ACTIVE",
            entity_version=1,
            ontology_version=ontology_version,
            merged_into=None,
        )
        await self.uow.world_entities.create_entity(entity)
        return entity

    async def get_entity(self, entity_id: str) -> Optional[WorldEntity]:
        assert self.uow.world_entities is not None
        return await self.uow.world_entities.get_entity(entity_id)

    async def add_alias(
        self,
        alias: str,
        entity_id: str,
        source_id: str,
        confidence: float = 1.0,
    ) -> EntityAlias:
        assert self.uow.world_entities is not None
        alias_record = EntityAlias(
            alias_id=uuid4(),
            alias=alias,
            entity_id=entity_id,
            source_id=source_id,
            confidence=confidence,
            created_at=datetime.now(timezone.utc),
        )
        await self.uow.world_entities.add_alias(alias_record)
        return alias_record

    async def resolve_entity(self, identifier: str) -> Optional[WorldEntity]:
        """
        Resolves an entity either directly by entity_id or via registered aliases.
        Follows merged_into pointer if entity was merged.
        """
        assert self.uow.world_entities is not None
        entity = await self.uow.world_entities.get_entity(identifier)
        if not entity:
            entity = await self.uow.world_entities.get_entity_by_alias(identifier)

        if entity and entity.merged_into:
            # Recursively resolve target of merge
            target = await self.uow.world_entities.get_entity(entity.merged_into)
            if target:
                return target

        return entity

    async def merge_entities(
        self,
        source_entity_id: str,
        target_entity_id: str,
        evidence_refs: List[str],
    ) -> WorldEntity:
        """
        Safely merges source_entity into target_entity, preserving lineage (Section 31).
        Does not delete historical records.
        """
        assert self.uow.world_entities is not None
        source = await self.uow.world_entities.get_entity(source_entity_id)
        target = await self.uow.world_entities.get_entity(target_entity_id)

        if not source or not target:
            raise EntityResolutionConflictError(
                f"Cannot merge entities: source '{source_entity_id}' or target '{target_entity_id}' does not exist.",
                {"source_id": source_entity_id, "target_id": target_entity_id},
            )

        if source.entity_id == target.entity_id:
            return target

        # Update source entity with pointer and status
        await self.uow.world_entities.update_entity_with_version(
            entity_id=source.entity_id,
            expected_version=source.entity_version,
            new_status="MERGED",
            merged_into=target.entity_id,
        )

        # Record resolution lineage history
        await self.uow.world_entities.record_resolution_history(
            event_type="MERGED",
            source_id=source.entity_id,
            target_id=target.entity_id,
            evidence_refs=evidence_refs,
        )

        return target

    async def split_entity(
        self,
        merged_entity_id: str,
        evidence_refs: List[str],
    ) -> WorldEntity:
        """
        Reverses a prior entity merge (Section 32), restoring independent identity.
        """
        assert self.uow.world_entities is not None
        entity = await self.uow.world_entities.get_entity(merged_entity_id)
        if not entity:
            raise EntityResolutionConflictError(
                f"Cannot split entity: '{merged_entity_id}' does not exist.",
                {"entity_id": merged_entity_id},
            )

        target_id = entity.merged_into
        await self.uow.world_entities.update_entity_with_version(
            entity_id=entity.entity_id,
            expected_version=entity.entity_version,
            new_status="ACTIVE",
            merged_into=None,
        )

        await self.uow.world_entities.record_resolution_history(
            event_type="SPLIT",
            source_id=entity.entity_id,
            target_id=target_id,
            evidence_refs=evidence_refs,
        )

        updated = await self.uow.world_entities.get_entity(merged_entity_id)
        assert updated is not None
        return updated
