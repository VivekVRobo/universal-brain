"""
Universal Brain - World Snapshots & Consistency Boundaries
Implements Sections 87-88 of Milestone M8 Specification (M8-INV-11).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional
from uuid import UUID, uuid4

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType

if TYPE_CHECKING:
    from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.schemas import WorldSnapshot


class WorldSnapshotManager:
    """
    Captures logical point-in-time consistency boundaries across world entities,
    assertions, and relations, producing deterministic SHA-256 snapshot digests.
    """

    def __init__(self, uow: UnitOfWork, event_store: Optional[EventStore] = None) -> None:
        self.uow = uow
        self.event_store = event_store

    async def capture_snapshot(
        self,
        scope: str = "GLOBAL",
        observation_head: int = 0,
        processor_cursor: int = 0,
        ontology_version: int = 1,
        fusion_policy_version: int = 1,
    ) -> WorldSnapshot:
        assert self.uow.world_entities is not None
        assert self.uow.world_assertions is not None
        assert self.uow.world_relations is not None
        assert self.uow.world_snapshots is not None

        entities = await self.uow.world_entities.list_entities()
        entity_versions = {e.entity_id: e.entity_version for e in entities}

        active_assertions = await self.uow.world_assertions.list_all_active_assertions()
        assertion_versions = {str(a.assertion_id): a.assertion_version for a in active_assertions}

        relation_versions: Dict[str, int] = {}
        for e in entities:
            rels = await self.uow.world_relations.list_relations_for_entity(e.entity_id)
            for r in rels:
                relation_versions[str(r.relation_id)] = r.relation_version

        snapshot = WorldSnapshot(
            snapshot_id=uuid4(),
            scope=scope,
            observation_head=observation_head,
            processor_cursor=processor_cursor,
            entity_versions=entity_versions,
            assertion_versions=assertion_versions,
            relation_versions=relation_versions,
            ontology_version=ontology_version,
            fusion_policy_version=fusion_policy_version,
            created_at=datetime.now(timezone.utc),
        )
        snapshot.snapshot_digest = snapshot.calculate_digest()

        await self.uow.world_snapshots.save_snapshot(snapshot)

        if self.event_store:
            self.event_store.append_event(
                event_type=EventType.WORLD_SNAPSHOT_CREATED,
                actor_id="world_model",
                payload={
                    "snapshot_id": str(snapshot.snapshot_id),
                    "snapshot_digest": snapshot.snapshot_digest,
                    "observation_head": observation_head,
                },
            )

        return snapshot

    async def get_snapshot(self, snapshot_id: UUID) -> Optional[WorldSnapshot]:
        assert self.uow.world_snapshots is not None
        return await self.uow.world_snapshots.get_snapshot(snapshot_id)

    async def get_latest_snapshot(self) -> Optional[WorldSnapshot]:
        assert self.uow.world_snapshots is not None
        return await self.uow.world_snapshots.get_latest_snapshot()
