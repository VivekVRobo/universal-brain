from __future__ import annotations

import json
import re
from typing import Iterable
from uuid import UUID

from .context import BaseContextSource, ContextChunk
from .schemas import SensitivityLevel

TOKEN_RE = re.compile(r"[A-Za-z0-9_+#.-]{2,}")


def _terms(text: str) -> set[str]:
    return {term.lower() for term in TOKEN_RE.findall(text)}


def _lexical_score(query: str, text: str) -> float:
    query_terms = _terms(query)
    if not query_terms:
        return 0.01
    text_terms = _terms(text)
    overlap = len(query_terms & text_terms)
    return overlap / max(len(query_terms), 1)


class SemanticMemoryContextSource(BaseContextSource):
    """Adapter over the derived SemanticMemoryIndex.

    Semantic retrieval is candidate context, never truth. Every chunk preserves the
    source event/version/digest provenance returned by the derived index.
    """

    def __init__(
        self,
        index,
        *,
        source_id: str = "semantic_memory",
        sensitivity: SensitivityLevel = SensitivityLevel.INTERNAL,
    ) -> None:
        self.index = index
        self.source_id = source_id
        self.sensitivity = sensitivity

    def retrieve(self, query: str, max_chunks: int = 12) -> list[ContextChunk]:
        if max_chunks <= 0:
            return []
        output: list[ContextChunk] = []
        for rank, item in enumerate(self.index.search(query, top_k=max_chunks)):
            preview = str(item.get("preview") or "").strip()
            if not preview:
                continue
            similarity = float(item.get("score", 0.0))
            normalized = max(0.0, min(1.0, (similarity + 1.0) / 2.0))
            output.append(
                ContextChunk(
                    source_id=f"{self.source_id}:{item.get('source_id', rank)}",
                    content=preview,
                    relevance_score=round(normalized, 6),
                    token_estimate=max(1, len(preview) // 4),
                    sensitivity=self.sensitivity,
                    metadata={
                        "retrieval_kind": "derived_semantic_memory",
                        "non_authoritative": True,
                        "source_type": item.get("source_type"),
                        "source_id": item.get("source_id"),
                        "source_version": item.get("source_version"),
                        "source_digest": item.get("source_digest"),
                        "raw_similarity": similarity,
                    },
                )
            )
        return output


class EventStoreContextSource(BaseContextSource):
    """Lexical adapter over canonical EventStore entries with provenance."""

    def __init__(
        self,
        event_store,
        *,
        project_id: UUID | None = None,
        source_id: str = "event_store",
        sensitivity: SensitivityLevel = SensitivityLevel.INTERNAL,
        max_events_scanned: int = 1_000,
    ) -> None:
        self.event_store = event_store
        self.project_id = project_id
        self.source_id = source_id
        self.sensitivity = sensitivity
        self.max_events_scanned = max(1, int(max_events_scanned))

    def retrieve(self, query: str, max_chunks: int = 12) -> list[ContextChunk]:
        if max_chunks <= 0:
            return []
        events = self.event_store.get_all_events()[-self.max_events_scanned :]
        candidates: list[ContextChunk] = []
        for event in events:
            if self.project_id is not None and event.project_id != self.project_id:
                continue
            payload = json.dumps(event.payload, sort_keys=True, default=str)
            text = f"{event.event_type.value}: {payload}"
            score = _lexical_score(query, text)
            if score <= 0 and query.strip():
                continue
            candidates.append(
                ContextChunk(
                    source_id=f"{self.source_id}:{event.event_id}",
                    content=text,
                    relevance_score=round(score, 6),
                    token_estimate=max(1, len(text) // 4),
                    sensitivity=self.sensitivity,
                    metadata={
                        "retrieval_kind": "canonical_event",
                        "event_id": str(event.event_id),
                        "event_hash": event.event_hash,
                        "event_type": event.event_type.value,
                        "project_id": str(event.project_id) if event.project_id else None,
                        "task_id": str(event.task_id) if event.task_id else None,
                        "contract_version": event.contract_version,
                        "timestamp": event.timestamp.isoformat(),
                    },
                )
            )
        candidates.sort(
            key=lambda chunk: (chunk.relevance_score, chunk.metadata.get("timestamp", "")),
            reverse=True,
        )
        return candidates[:max_chunks]


class MissionBlackboardContextSource(BaseContextSource):
    """Mission-scoped retrieval over structured blackboard entries.

    VERIFIED entries are ranked above proposed entries, while conflicted/rejected
    state remains visible in metadata so a model cannot mistake it for settled fact.
    """

    def __init__(
        self,
        blackboard,
        mission_id: UUID,
        *,
        source_id: str = "mission_blackboard",
        sensitivity: SensitivityLevel = SensitivityLevel.INTERNAL,
    ) -> None:
        self.blackboard = blackboard
        self.mission_id = mission_id
        self.source_id = source_id
        self.sensitivity = sensitivity

    def retrieve(self, query: str, max_chunks: int = 12) -> list[ContextChunk]:
        if max_chunks <= 0:
            return []
        candidates: list[ContextChunk] = []
        for entry in self.blackboard.list_entries(self.mission_id):
            score = _lexical_score(query, entry.statement)
            status = getattr(entry.status, "value", str(entry.status))
            if status == "VERIFIED":
                score += 0.35
            elif status == "CONFLICTED":
                score += 0.08
            elif status == "REJECTED":
                score *= 0.25
            if score <= 0 and query.strip():
                continue
            evidence = list(entry.evidence_refs)
            content = (
                f"[{entry.entry_type.value}/{status}] {entry.statement}\n"
                f"Evidence refs: {', '.join(evidence) if evidence else 'none'}"
            )
            candidates.append(
                ContextChunk(
                    source_id=f"{self.source_id}:{entry.entry_id}",
                    content=content,
                    relevance_score=round(max(score, 0.0), 6),
                    token_estimate=max(1, len(content) // 4),
                    sensitivity=self.sensitivity,
                    metadata={
                        "retrieval_kind": "mission_blackboard",
                        "mission_id": str(entry.mission_id),
                        "entry_id": str(entry.entry_id),
                        "entry_type": entry.entry_type.value,
                        "status": status,
                        "evidence_refs": evidence,
                        "source_event_id": str(entry.source_event_id)
                        if entry.source_event_id
                        else None,
                    },
                )
            )
        candidates.sort(
            key=lambda chunk: (chunk.relevance_score, chunk.source_id), reverse=True
        )
        return candidates[:max_chunks]


class CompositeContextSource(BaseContextSource):
    """Deterministically merge multiple context sources into one retrieval surface."""

    def __init__(self, sources: Iterable[BaseContextSource]) -> None:
        self.sources = list(sources)

    def retrieve(self, query: str, max_chunks: int = 12) -> list[ContextChunk]:
        if max_chunks <= 0:
            return []
        per_source = max(1, max_chunks)
        chunks = [
            chunk
            for source in self.sources
            for chunk in source.retrieve(query, max_chunks=per_source)
        ]
        deduped: dict[str, ContextChunk] = {}
        for chunk in chunks:
            existing = deduped.get(chunk.source_id)
            if existing is None or chunk.relevance_score > existing.relevance_score:
                deduped[chunk.source_id] = chunk
        ranked = sorted(
            deduped.values(),
            key=lambda chunk: (chunk.relevance_score, -chunk.token_estimate, chunk.source_id),
            reverse=True,
        )
        return ranked[:max_chunks]
