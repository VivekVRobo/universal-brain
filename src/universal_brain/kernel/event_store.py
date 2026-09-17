"""
Universal Brain - Event Store & Causal Graph Engine

The EventStore is an in-memory projection of the canonical append-only event
ledger. When a CanonicalEventJournal is configured, every event/edge is fsync'd
before the in-memory projection is mutated.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from universal_brain.kernel.canonical_journal import CanonicalEventJournal
from universal_brain.kernel.errors import HashChainTamperError
from universal_brain.kernel.events import (
    EventEdge,
    EventEnvelope,
    EventType,
    RelationType,
)


class EventStore:
    """Tamper-evident canonical event projection with optional durable journal."""

    def __init__(
        self,
        journal: CanonicalEventJournal | None = None,
        *,
        rehydrate: bool = True,
    ) -> None:
        self._events: List[EventEnvelope] = []
        self._events_by_id: Dict[UUID, EventEnvelope] = {}
        self._edges: List[EventEdge] = []
        self._outbox: List[EventEnvelope] = []
        self._latest_hash: str = ""
        self._journal = journal

        if self._journal is not None and rehydrate:
            self.rehydrate_from_journal()

    @classmethod
    def durable(cls, journal_path: Path, *, rehydrate: bool = True) -> "EventStore":
        """Create an EventStore backed by the canonical fsync journal."""
        return cls(CanonicalEventJournal(journal_path), rehydrate=rehydrate)

    @property
    def journal(self) -> CanonicalEventJournal | None:
        return self._journal

    @property
    def is_durable(self) -> bool:
        return self._journal is not None

    @property
    def latest_hash(self) -> str:
        return self._latest_hash

    @property
    def event_count(self) -> int:
        return len(self._events)

    def _reset_projection(self) -> None:
        self._events.clear()
        self._events_by_id.clear()
        self._edges.clear()
        self._outbox.clear()
        self._latest_hash = ""

    def _project_event(
        self,
        event: EventEnvelope,
        causal_edge: EventEdge | None = None,
        *,
        enqueue_outbox: bool = True,
    ) -> None:
        if event.event_id in self._events_by_id:
            raise ValueError(f"Duplicate event id {event.event_id} in canonical projection.")
        if event.prev_event_hash != self._latest_hash:
            raise HashChainTamperError(
                f"Canonical event {event.event_id} does not extend current chain head."
            )

        self._events.append(event)
        self._events_by_id[event.event_id] = event
        self._latest_hash = event.event_hash
        if enqueue_outbox:
            self._outbox.append(event)

        if causal_edge is not None:
            self._project_edge(causal_edge)

    def _project_edge(self, edge: EventEdge) -> None:
        if edge.source_event_id not in self._events_by_id:
            raise ValueError(f"Source event {edge.source_event_id} not found in store.")
        if edge.target_event_id not in self._events_by_id:
            raise ValueError(f"Target event {edge.target_event_id} not found in store.")
        if any(existing.edge_id == edge.edge_id for existing in self._edges):
            raise ValueError(f"Duplicate edge id {edge.edge_id} in canonical projection.")
        self._edges.append(edge)

    def rehydrate_from_journal(self) -> int:
        """Rebuild the entire in-memory projection deterministically from the journal."""
        if self._journal is None:
            raise RuntimeError("EventStore has no canonical journal configured.")

        records = self._journal.load_records()
        self._reset_projection()

        for index, record in enumerate(records, start=1):
            kind = record["kind"]
            if kind == "event":
                event = EventEnvelope.model_validate(record["event"])
                raw_edge = record.get("causal_edge")
                edge = EventEdge.model_validate(raw_edge) if raw_edge else None
                self._project_event(event, causal_edge=edge, enqueue_outbox=False)
            elif kind == "edge":
                self._project_edge(EventEdge.model_validate(record["edge"]))
            else:
                raise ValueError(f"Unsupported canonical journal record {index}: {kind}")

        self.verify_chain_integrity()
        return self.event_count

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
        """Append one canonical event, durable-before-visible when journaled."""
        if caused_by_event_id and caused_by_event_id not in self._events_by_id:
            raise ValueError(f"Caused-by event {caused_by_event_id} does not exist in store.")

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

        causal_edge = None
        if caused_by_event_id:
            causal_edge = EventEdge(
                source_event_id=caused_by_event_id,
                target_event_id=event.event_id,
                relation_type=RelationType.CAUSED_BY,
            )

        # Durability is the commit point. RAM is only updated after fsync succeeds.
        if self._journal is not None:
            self._journal.append_event(event, causal_edge)

        self._project_event(event, causal_edge=causal_edge)
        return event

    def add_edge(
        self,
        source_event_id: UUID,
        target_event_id: UUID,
        relation_type: RelationType,
    ) -> EventEdge:
        """Record a causal relationship, durable-before-visible when journaled."""
        if source_event_id not in self._events_by_id:
            raise ValueError(f"Source event {source_event_id} not found in store.")
        if target_event_id not in self._events_by_id:
            raise ValueError(f"Target event {target_event_id} not found in store.")

        edge = EventEdge(
            source_event_id=source_event_id,
            target_event_id=target_event_id,
            relation_type=relation_type,
        )
        if self._journal is not None:
            self._journal.append_edge(edge)
        self._project_edge(edge)
        return edge

    def get_event(self, event_id: UUID) -> Optional[EventEnvelope]:
        return self._events_by_id.get(event_id)

    def get_all_events(self) -> List[EventEnvelope]:
        return list(self._events)

    def get_all_edges(self) -> List[EventEdge]:
        return list(self._edges)

    def verify_chain_integrity(self) -> bool:
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
        lineage: List[EventEnvelope] = []
        current_id: Optional[UUID] = event_id
        depth = 0

        while current_id and depth < max_depth:
            event = self._events_by_id.get(current_id)
            if not event:
                break
            lineage.append(event)
            depth += 1
            parent_edge = next(
                (
                    edge
                    for edge in self._edges
                    if edge.target_event_id == current_id
                    and edge.relation_type == RelationType.CAUSED_BY
                ),
                None,
            )
            current_id = parent_edge.source_event_id if parent_edge else None

        lineage.reverse()
        return lineage

    def drain_outbox(self, max_batch_size: int = 100) -> List[EventEnvelope]:
        batch = self._outbox[:max_batch_size]
        self._outbox = self._outbox[max_batch_size:]
        return batch

    def export_outbox_jsonl(self, max_batch_size: int = 100) -> str:
        events = self.drain_outbox(max_batch_size)
        return "\n".join(event.to_canonical_json() for event in events)
