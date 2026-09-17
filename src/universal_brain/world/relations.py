"""
Universal Brain - Temporal World Entity Relations
Implements Sections 45-46 of Milestone M8 Specification.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.schemas import AssertionStateClass, WorldRelation


class WorldRelationManager:
    """
    Manages directed temporal relations between world entities,
    preserving relational history across interval closures.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def add_relation(
        self,
        source_entity: str,
        relation_type: str,
        target_entity: str,
        valid_from: Optional[datetime] = None,
        valid_until: Optional[datetime] = None,
        state_class: AssertionStateClass = AssertionStateClass.OBSERVED,
        confidence: float = 1.0,
        uncertainty: Optional[Dict[str, Any]] = None,
        evidence_refs: Optional[List[str]] = None,
        ontology_version: int = 1,
    ) -> WorldRelation:
        assert self.uow.world_relations is not None
        now = datetime.now(timezone.utc)
        relation = WorldRelation(
            relation_id=uuid4(),
            source_entity=source_entity,
            relation_type=relation_type,
            target_entity=target_entity,
            valid_from=valid_from or now,
            valid_until=valid_until,
            transaction_from=now,
            transaction_until=None,
            state_class=state_class,
            confidence=confidence,
            uncertainty=uncertainty,
            evidence_refs=evidence_refs or [],
            relation_version=1,
            ontology_version=ontology_version,
            status="ACTIVE",
        )
        await self.uow.world_relations.create_relation(relation)
        return relation

    async def end_relation(
        self,
        relation_id: UUID,
        valid_until: Optional[datetime] = None,
    ) -> None:
        """Closes the validity interval of an active relation without deleting history."""
        assert self.uow.world_relations is not None
        now = datetime.now(timezone.utc)
        await self.uow.world_relations.end_relation(relation_id, valid_until or now)

    async def list_relations_for_entity(
        self,
        entity_id: str,
    ) -> List[WorldRelation]:
        assert self.uow.world_relations is not None
        return await self.uow.world_relations.list_relations_for_entity(entity_id)
