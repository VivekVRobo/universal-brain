"""
Universal Brain - World Change Detection & Event Generation
Implements Sections 76-79 of Milestone M8 Specification.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType
from universal_brain.world.schemas import WorldEvent


class WorldChangeDetector:
    """
    Analyzes property transitions, applies noise rejection thresholds, hysteresis,
    and debounce logic, emitting normalized WorldEvents and WORLD_STATE_CHANGED governance events.
    """

    def __init__(
        self,
        event_store: Optional[EventStore] = None,
        numeric_delta_threshold: float = 0.05,
        pose_distance_threshold: float = 0.05,  # 5cm
    ) -> None:
        self.event_store = event_store
        self.numeric_delta_threshold = numeric_delta_threshold
        self.pose_distance_threshold = pose_distance_threshold
        self._last_event_times: Dict[str, datetime] = {}

    def is_significant_change(
        self,
        property_key: str,
        prev_val: Any,
        new_val: Any,
    ) -> bool:
        if prev_val is None:
            return True

        if isinstance(new_val, (str, bool)):
            return prev_val != new_val

        if isinstance(new_val, (int, float)) and isinstance(prev_val, (int, float)):
            return abs(float(new_val) - float(prev_val)) >= self.numeric_delta_threshold

        if isinstance(new_val, dict) and isinstance(prev_val, dict):
            # Check if 3D pose
            if "x" in new_val and "y" in new_val:
                px, py = float(prev_val.get("x", 0.0)), float(prev_val.get("y", 0.0))
                nx, ny = float(new_val.get("x", 0.0)), float(new_val.get("y", 0.0))
                pz, nz = float(prev_val.get("z", 0.0)), float(new_val.get("z", 0.0))
                dist = math.sqrt((nx - px) ** 2 + (ny - py) ** 2 + (nz - pz) ** 2)
                return dist >= self.pose_distance_threshold
            return prev_val != new_val

        return prev_val != new_val

    def process_change(
        self,
        entity_id: str,
        property_key: str,
        prev_val: Any,
        new_val: Any,
        observed_at: Optional[datetime] = None,
        evidence_refs: Optional[List[str]] = None,
    ) -> Optional[WorldEvent]:
        """
        Evaluates whether a value transition is significant, and if so,
        creates and logs a WorldEvent.
        """
        if not self.is_significant_change(property_key, prev_val, new_val):
            return None

        now = datetime.now(timezone.utc)
        obs_time = observed_at or now

        # Debounce key: entity:property
        debounce_key = f"{entity_id}:{property_key}"
        last_time = self._last_event_times.get(debounce_key)
        if last_time and (now - last_time).total_seconds() < 0.1:  # 100ms debounce
            return None

        self._last_event_times[debounce_key] = now

        event = WorldEvent(
            world_event_id=uuid4(),
            event_type="PROPERTY_CHANGED",
            entity_id=entity_id,
            property_key=property_key,
            previous_value=prev_val,
            new_value=new_val,
            significance="SIGNIFICANT",
            observed_at=obs_time,
            detected_at=now,
            evidence_refs=evidence_refs or [],
        )

        if self.event_store:
            self.event_store.append_event(
                event_type=EventType.WORLD_STATE_CHANGED,
                actor_id="world_model",
                payload={
                    "world_event_id": str(event.world_event_id),
                    "entity_id": entity_id,
                    "property_key": property_key,
                    "previous_value": prev_val,
                    "new_value": new_val,
                },
            )

        return event
