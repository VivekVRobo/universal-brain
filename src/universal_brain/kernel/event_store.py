"""
Universal Brain - Event Store & Causal Graph Engine

Implements ALN-016 (tamper-evident hash chain) and ALN-021 (Total Awareness).
Provides in-memory and database-backed event storage, causal DAG linking,
backward causal lineage tracing, and outbox micro-batching.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from universal_brain.kernel.errors import HashChainTamperError
from universal_brain.kernel.events import (
    EventEdge,
    EventEnvelope,
    EventType,
    RelationType,
)


class EventStore:
    """
    Core transactional event store and causal graph manager.
    Maintains cryptographic hash-chain continuity and directed causal edges.
    """

    def __init__(self) -> None:
        self._events: List[EventEnvelope] = []
        self._events_by_id: Dict[UUID, EventEnvelope] = {}
        self._edges: List[EventEdge] = []
        self._outbox: List[EventEnvelope] = []
        self._latest_hash: str = ""

    @property
    def latest_hash(self) -> str:
        """Returns the SHA-256 hash of the most recent event in the chain."""
        return self._latest_hash

    @property
    def event_count(self) -> int:
        """Returns the total number of events recorded."""
        return len(self._events)

    def append_event(
        self,
        event_type: EventType,
        actor_id: str,
        payload: Optional[Dict[str, Any]] = None,
        project_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        contract_version: Optional[int] = None,
        caused_by_event_id: Optional[UUID] = None,
        timestamp: Optional[datetime] = None,
    ) -> EventEnvelope:
        """
        Atomically append an event to the ledger, compute its SHA-256 hash
        linked to the predecessor, and optionally create a CAUSED_BY causal edge.
        """
        # Create event with current chain head as prev_event_hash
        event = EventEnvelope.create(
            event_type=event_type,
            actor_id=actor_id,
            payload=payload or {},
            project_id=project_id,
            task_id=task_id,
            contract_version=contract_version,
            prev_event_hash=self._latest_hash,
            timestamp=timestamp,
        )

        # Store event
        self._events.append(event)
        self._events_by_id[event.event_id] = event
        self._outbox.append(event)
        self._latest_hash = event.event_hash

        # Link causal edge if cause specified
        if caused_by_event_id:
            if caused_by_event_id not in self._events_by_id:
                raise ValueError(f"Caused-by event {caused_by_event_id} does not exist in store.")
            self.add_edge(
                source_event_id=caused_by_event_id,
                target_event_id=event.event_id,
                relation_type=RelationType.CAUSED_BY,
            )

        return event

    def add_edge(
        self,
        source_event_id: UUID,
        target_event_id: UUID,
        relation_type: RelationType,
    ) -> EventEdge:
        """Record a directed relationship between two events (e.g., PROVES, INVALIDATES)."""
        if source_event_id not in self._events_by_id:
            raise ValueError(f"Source event {source_event_id} not found in store.")
        if target_event_id not in self._events_by_id:
            raise ValueError(f"Target event {target_event_id} not found in store.")

        edge = EventEdge(
            source_event_id=source_event_id,
            target_event_id=target_event_id,
            relation_type=relation_type,
        )
        self._edges.append(edge)
        return edge

    def get_event(self, event_id: UUID) -> Optional[EventEnvelope]:
        """Fetch a specific event by UUID."""
        return self._events_by_id.get(event_id)

    def get_all_events(self) -> List[EventEnvelope]:
        """Return all recorded events in chronological order."""
        return list(self._events)

    def verify_chain_integrity(self) -> bool:
        """
        Traverse the full event ledger and assert cryptographic hash-chain validity (ALN-016).
        Raises HashChainTamperError if any hash mismatch or broken chain is discovered.
        """
        expected_prev_hash = ""
        for idx, event in enumerate(self._events):
            if event.prev_event_hash != expected_prev_hash:
                raise HashChainTamperError(
                    f"Hash chain broken at index {idx} (Event ID: {event.event_id}): "
                    f"expected prev_hash '{expected_prev_hash}', found '{event.prev_event_hash}'."
                )

            recomputed_hash = event.compute_hash(expected_prev_hash)
            if event.event_hash != recomputed_hash:
                raise HashChainTamperError(
                    f"Tampered event payload at index {idx} (Event ID: {event.event_id}): "
                    f"stored hash '{event.event_hash}', recomputed '{recomputed_hash}'."
                )

            expected_prev_hash = event.event_hash

        return True

    def trace_causal_lineage(self, event_id: UUID, max_depth: int = 25) -> List[EventEnvelope]:
        """
        Perform a backward causal walk along CAUSED_BY edges.
        Answers the question: 'Why did this event happen?'
        Returns the path in reverse causal order (originating cause first).
        """
        lineage: List[EventEnvelope] = []
        current_id: Optional[UUID] = event_id
        depth = 0

        while current_id and depth < max_depth:
            event = self._events_by_id.get(current_id)
            if not event:
                break
            lineage.append(event)
            depth += 1

            # Find incoming CAUSED_BY edge where target == current_id
            parent_edge = next(
                (e for e in self._edges if e.target_event_id == current_id and e.relation_type == RelationType.CAUSED_BY),
                None,
            )
            current_id = parent_edge.source_event_id if parent_edge else None

        # Return root cause first (e.g. USER_INPUT -> INTENT_PARSED -> CONTRACT -> TASK -> TOOL)
        lineage.reverse()
        return lineage

    def drain_outbox(self, max_batch_size: int = 100) -> List[EventEnvelope]:
        """
        Drain events from the replication outbox buffer for micro-batch chunk creation.
        Satisfies the 60s micro-batch upload requirement in MEMORY_ARCHITECTURE.md.
        """
        batch = self._outbox[:max_batch_size]
        self._outbox = self._outbox[max_batch_size:]
        return batch

    def export_outbox_jsonl(self, max_batch_size: int = 100) -> str:
        """Formats the drained outbox batch into newline-delimited JSON (JSONL)."""
        events = self.drain_outbox(max_batch_size)
        lines = [e.to_canonical_json() for e in events]
        return "\n".join(lines)
