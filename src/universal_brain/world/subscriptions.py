"""
Universal Brain - World Mission Subscriptions
Implements Sections 84-86 of Milestone M8 Specification.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set
from uuid import UUID


class WorldSubscriptionRegistry:
    """
    Maintains index of mission subscriptions to world entities, properties,
    and event types, enabling targeted wakeups without global notification spam.
    """

    def __init__(self) -> None:
        # entity_id -> Set of mission_ids
        self._entity_subscriptions: Dict[str, Set[UUID]] = {}
        # (entity_id, property_key) -> Set of mission_ids
        self._property_subscriptions: Dict[str, Set[UUID]] = {}

    def subscribe(
        self,
        mission_id: UUID,
        entity_id: str,
        property_key: Optional[str] = None,
    ) -> None:
        """Registers a mission's interest in world changes."""
        if property_key:
            key = f"{entity_id}:{property_key}"
            self._property_subscriptions.setdefault(key, set()).add(mission_id)
        else:
            self._entity_subscriptions.setdefault(entity_id, set()).add(mission_id)

    def unsubscribe(self, mission_id: UUID, entity_id: str) -> None:
        if entity_id in self._entity_subscriptions:
            self._entity_subscriptions[entity_id].discard(mission_id)

    def get_subscribers(
        self,
        entity_id: str,
        property_key: Optional[str] = None,
    ) -> List[UUID]:
        """
        Returns list of mission IDs subscribed to this entity or property.
        """
        subscribers: Set[UUID] = set()

        if entity_id in self._entity_subscriptions:
            subscribers.update(self._entity_subscriptions[entity_id])

        if property_key:
            prop_key = f"{entity_id}:{property_key}"
            if prop_key in self._property_subscriptions:
                subscribers.update(self._property_subscriptions[prop_key])

        return list(subscribers)
