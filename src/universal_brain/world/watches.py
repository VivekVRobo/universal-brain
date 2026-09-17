"""
Universal Brain - World Watches & Reactive Triggers
Implements Sections 80-83 of Milestone M8 Specification (M8-INV-08).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, List, Optional
from uuid import UUID, uuid4

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType

if TYPE_CHECKING:
    from universal_brain.persistence.unit_of_work import UnitOfWork
from universal_brain.world.schemas import (
    AssertionStateClass,
    FreshnessStatus,
    WatchStatus,
    WorldPropertyAssertion,
    WorldWatch,
)


class WorldWatchManager:
    """
    Manages persistent reactive world conditions.
    Enforces required freshness, verification requirements, and exactly-once logical triggers (M8-INV-08).
    """

    def __init__(self, uow: UnitOfWork, event_store: Optional[EventStore] = None) -> None:
        self.uow = uow
        self.event_store = event_store

    async def create_watch(
        self,
        mission_id: UUID,
        entity_id: str,
        property_key: str,
        expected_value: Any,
        operator: str = "==",
        task_id: Optional[UUID] = None,
        required_freshness: FreshnessStatus = FreshnessStatus.FRESH,
        required_state_class: Optional[AssertionStateClass] = None,
        debounce_sec: float = 0.0,
    ) -> WorldWatch:
        assert self.uow.world_watches is not None
        watch = WorldWatch(
            watch_id=uuid4(),
            mission_id=mission_id,
            task_id=task_id,
            entity_id=entity_id,
            property_key=property_key,
            expected_value=expected_value,
            operator=operator,
            required_freshness=required_freshness,
            required_state_class=required_state_class,
            debounce_sec=debounce_sec,
            created_at=datetime.now(timezone.utc),
            expires_at=None,
            status=WatchStatus.ACTIVE,
            idempotency_key=f"{mission_id}:{entity_id}:{property_key}:{expected_value}",
            watch_version=1,
        )
        await self.uow.world_watches.create_watch(watch)

        if self.event_store:
            self.event_store.append_event(
                event_type=EventType.WORLD_WATCH_CREATED,
                actor_id="world_model",
                payload={
                    "watch_id": str(watch.watch_id),
                    "mission_id": str(mission_id),
                    "entity_id": entity_id,
                    "property_key": property_key,
                },
            )

        return watch

    async def evaluate_watches_for_assertion(
        self,
        assertion: WorldPropertyAssertion,
    ) -> List[WorldWatch]:
        """
        Evaluates active watches against an updated assertion.
        Returns list of watches triggered on this cycle.
        """
        assert self.uow.world_watches is not None
        active_watches = await self.uow.world_watches.list_active_watches()
        triggered = []

        for w in active_watches:
            if w.entity_id != assertion.entity_id or w.property_key != assertion.property_key:
                continue

            # Section 82: Check freshness barrier
            if assertion.freshness_status != w.required_freshness and w.required_freshness == FreshnessStatus.FRESH:
                continue

            # Section 81: Check verification level requirement
            if w.required_state_class and assertion.state_class != w.required_state_class:
                continue

            # Evaluate condition
            matched = False
            if w.operator == "==":
                matched = (assertion.value == w.expected_value)
            elif w.operator == "!=":
                matched = (assertion.value != w.expected_value)
            elif w.operator == "<":
                matched = (float(assertion.value) < float(w.expected_value))
            elif w.operator == ">":
                matched = (float(assertion.value) > float(w.expected_value))
            elif w.operator == "<=":
                matched = (float(assertion.value) <= float(w.expected_value))
            elif w.operator == ">=":
                matched = (float(assertion.value) >= float(w.expected_value))

            if matched:
                # Exactly-once trigger (M8-INV-08)
                await self.uow.world_watches.update_watch_status(w.watch_id, WatchStatus.TRIGGERED.value)
                w.status = WatchStatus.TRIGGERED
                triggered.append(w)

                if self.event_store:
                    self.event_store.append_event(
                        event_type=EventType.WORLD_WATCH_TRIGGERED,
                        actor_id="world_model",
                        payload={
                            "watch_id": str(w.watch_id),
                            "mission_id": str(w.mission_id),
                            "entity_id": w.entity_id,
                            "property_key": w.property_key,
                            "triggered_value": assertion.value,
                        },
                    )

        return triggered
