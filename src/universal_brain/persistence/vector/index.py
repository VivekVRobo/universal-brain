"""
Universal Brain - Derived Semantic Memory & Vector Projection

Implements M6 Sections 50-54, 84-88, and Invariant M6-INV-09:
Non-authoritative, derived vector search index that preserves retrieval provenance
and can be 100% reconstructed from canonical events via rebuild_index().
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from universal_brain.kernel.events import EventEnvelope


class EmbeddingRecord(BaseModel):
    """Derived vector representation maintaining explicit provenance (Section 53)."""

    embedding_id: UUID = Field(default_factory=uuid4)
    source_type: str
    source_id: UUID
    source_version: int = 1
    source_digest: str
    content_preview: str
    vector: List[float]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SemanticMemoryIndex:
    """Non-authoritative, derived vector projection over canonical events."""

    def __init__(self, dimensions: int = 16) -> None:
        self.dimensions = dimensions
        self.records: Dict[UUID, EmbeddingRecord] = {}

    def _generate_vector(self, text: str) -> List[float]:
        """Generates deterministic pseudo-embedding vector for testing/local offline indexing."""
        vec = []
        for i in range(self.dimensions):
            h = hashlib.sha256(f"{text}:{i}".encode("utf-8")).hexdigest()
            # Normalize to [-1.0, 1.0]
            val = (int(h[:8], 16) / 0xFFFFFFFF) * 2.0 - 1.0
            vec.append(val)
        # Normalize vector length to 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [round(x / norm, 4) for x in vec]

    def index_event(self, envelope: EventEnvelope) -> EmbeddingRecord:
        """Indexes a canonical event with explicit provenance (Section 53)."""
        content = f"{envelope.event_type.value}: {envelope.payload}"
        digest = envelope.event_hash
        vector = self._generate_vector(content)

        record = EmbeddingRecord(
            source_type="event",
            source_id=envelope.event_id,
            source_version=envelope.contract_version or 1,
            source_digest=digest,
            content_preview=content[:200],
            vector=vector,
        )
        self.records[envelope.event_id] = record
        return record

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieves candidate context with full provenance attached.
        (M6 Section 53: Semantic retrieval is not truth; returns candidate context).
        """
        query_vec = self._generate_vector(query)
        scored: List[tuple[float, EmbeddingRecord]] = []

        for rec in self.records.values():
            # Cosine similarity
            score = sum(q * r for q, r in zip(query_vec, rec.vector))
            scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, rec in scored[:top_k]:
            results.append({
                "score": round(score, 4),
                "source_type": rec.source_type,
                "source_id": str(rec.source_id),
                "source_version": rec.source_version,
                "source_digest": rec.source_digest,
                "preview": rec.content_preview,
            })

        return results

    def rebuild_index(self, events: List[EventEnvelope]) -> int:
        """
        Destroys and completely reconstructs vector store from scratch
        using canonical events (M6 Section 88).
        """
        self.records.clear()
        for ev in events:
            self.index_event(ev)
        return len(self.records)
