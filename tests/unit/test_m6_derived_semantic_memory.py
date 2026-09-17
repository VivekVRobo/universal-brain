"""
Universal Brain - Derived Semantic Memory & Vector Index Tests

Implements M6 Sections 50-54, 84-88, and Invariant M6-INV-09:
Verifies that vector search remains a non-authoritative derived projection,
preserves complete retrieval provenance, and can be destroyed and reconstructed via rebuild_index().
"""

from uuid import uuid4
import pytest

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType
from universal_brain.persistence.vector.index import SemanticMemoryIndex


def test_semantic_memory_provenance_and_search():
    """Verify vector search returns candidate context with complete provenance attached (Section 53)."""
    index = SemanticMemoryIndex(dimensions=16)
    store = EventStore()

    e1 = store.append_event(EventType.USER_INPUT, "operator", {"task": "deploy cluster"})
    e2 = store.append_event(EventType.TOOL_CALLED, "gateway", {"tool": "k8s_apply"})
    e3 = store.append_event(EventType.SYSTEM_FAILURE, "monitor", {"error": "OOMKilled"})

    index.index_event(e1)
    index.index_event(e2)
    index.index_event(e3)

    # Search for cluster failure
    results = index.search("OOMKilled memory failure", top_k=2)
    assert len(results) == 2
    top = results[0]
    assert "source_type" in top
    assert "source_id" in top
    assert "source_version" in top
    assert "source_digest" in top
    assert top["source_id"] == str(e3.event_id)


def test_vector_index_destruction_and_rebuild():
    """Verify vector memory is rebuildable from canonical events (M6 Section 88, Invariant M6-INV-09)."""
    index = SemanticMemoryIndex(dimensions=16)
    store = EventStore()

    events = [
        store.append_event(EventType.USER_INPUT, "operator", {"seq": i})
        for i in range(5)
    ]

    for ev in events:
        index.index_event(ev)
    assert len(index.records) == 5

    # DESTROY vector index completely
    index.records.clear()
    assert len(index.records) == 0

    # REBUILD from canonical event ledger
    rebuilt_count = index.rebuild_index(store.get_all_events())
    assert rebuilt_count == 5
    assert len(index.records) == 5
    for ev in events:
        assert ev.event_id in index.records
