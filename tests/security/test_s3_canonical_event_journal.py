"""Canonical EventStore journal durability regressions."""

from pathlib import Path

import pytest

from universal_brain.kernel.canonical_journal import (
    CanonicalEventJournal,
    CanonicalJournalError,
)
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType, RelationType


def test_durable_eventstore_rehydrates_exact_event_and_edge_parity(tmp_path: Path):
    journal_path = tmp_path / "canonical-events.jsonl"
    store = EventStore.durable(journal_path)

    e1 = store.append_event(
        EventType.USER_INPUT,
        "operator",
        {"query": "build parser"},
    )
    e2 = store.append_event(
        EventType.INTENT_PARSED,
        "intent_parser",
        {"primary_goal": "build parser"},
        caused_by_event_id=e1.event_id,
    )
    store.add_edge(e2.event_id, e1.event_id, RelationType.PROVES)

    assert store.event_count == 2
    assert len(store.get_all_edges()) == 2
    expected_hash = store.latest_hash

    restarted = EventStore.durable(journal_path)
    assert restarted.event_count == 2
    assert restarted.latest_hash == expected_hash
    assert restarted.verify_chain_integrity() is True

    events = restarted.get_all_events()
    assert [event.event_id for event in events] == [e1.event_id, e2.event_id]
    assert [event.event_hash for event in events] == [e1.event_hash, e2.event_hash]

    edges = restarted.get_all_edges()
    assert {(edge.source_event_id, edge.target_event_id, edge.relation_type) for edge in edges} == {
        (e1.event_id, e2.event_id, RelationType.CAUSED_BY),
        (e2.event_id, e1.event_id, RelationType.PROVES),
    }


def test_journal_failure_never_mutates_in_memory_projection(tmp_path: Path, monkeypatch):
    journal = CanonicalEventJournal(tmp_path / "canonical-events.jsonl")
    store = EventStore(journal)

    def fail_append(*_args, **_kwargs):
        raise CanonicalJournalError("simulated fsync failure")

    monkeypatch.setattr(journal, "append_event", fail_append)

    with pytest.raises(CanonicalJournalError, match="simulated fsync failure"):
        store.append_event(EventType.USER_INPUT, "operator", {"query": "must not appear"})

    assert store.event_count == 0
    assert store.latest_hash == ""
    assert store.get_all_edges() == []


def test_corrupt_journal_fails_closed_on_rehydrate(tmp_path: Path):
    journal_path = tmp_path / "canonical-events.jsonl"
    store = EventStore.durable(journal_path)
    store.append_event(EventType.USER_INPUT, "operator", {"query": "safe"})

    with journal_path.open("ab") as handle:
        handle.write(b"{this-is-not-json}\n")

    with pytest.raises(CanonicalJournalError, match="malformed"):
        EventStore.durable(journal_path)
