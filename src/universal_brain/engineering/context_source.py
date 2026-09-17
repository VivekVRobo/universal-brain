"""Code-graph-aware context source.

Traceability: REQ-ENG-005, REQ-STA-002, ALN-012, ALN-013.
Derived graph metadata ranks source snippets; it never grants authority.
"""

from __future__ import annotations

import re
from pathlib import Path

from universal_brain.intelligence.context import BaseContextSource, ContextChunk
from universal_brain.intelligence.schemas import SensitivityLevel

from .code_graph import CodeGraphIndex


class CodeGraphContextSource(BaseContextSource):
    def __init__(
        self,
        index: CodeGraphIndex,
        *,
        sensitivity: SensitivityLevel = SensitivityLevel.INTERNAL,
        context_lines: int = 24,
        semantic_snapshot=None,
    ) -> None:
        self.index = index
        self.root = Path(index.repository_root)
        self.sensitivity = sensitivity
        self.context_lines = max(4, context_lines)
        self.semantic_snapshot = semantic_snapshot

    def retrieve(self, query: str, max_chunks: int = 12) -> list[ContextChunk]:
        if max_chunks <= 0:
            return []
        terms = {term.lower() for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query)}
        scored = []
        for symbol in self.index.symbols.values():
            name = symbol.name.lower()
            qualified = symbol.qualified_name.lower()
            score = 0.0
            if name in terms:
                score += 1.0
            score += 0.12 * sum(1 for term in terms if term in qualified)
            ref_hits = sum(1 for ref in self.index.references if ref.target_name.lower() == name)
            score += min(0.25, ref_hits * 0.025)
            if self.semantic_snapshot is not None:
                semantic_hits = sum(
                    1
                    for fact in self.semantic_snapshot.symbols
                    if fact.name.lower() == name
                )
                score += min(0.35, semantic_hits * 0.12)
            if score > 0:
                scored.append((score, symbol))
        scored.sort(key=lambda item: (item[0], item[1].qualified_name), reverse=True)

        chunks: list[ContextChunk] = []
        seen: set[tuple[str, int]] = set()
        for score, symbol in scored:
            if len(chunks) >= max_chunks:
                break
            path = self.root / symbol.file_path
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            start = max(0, symbol.line - 1 - self.context_lines // 3)
            end_line = symbol.end_line or symbol.line
            end = min(len(lines), end_line + self.context_lines)
            key = (symbol.file_path, start)
            if key in seen:
                continue
            seen.add(key)
            content = "\n".join(lines[start:end])
            refs = [
                {
                    "relation": ref.relation,
                    "target_name": ref.target_name,
                    "line": ref.line,
                }
                for ref in self.index.references
                if ref.file_path == symbol.file_path and ref.source_symbol_id == symbol.symbol_id
            ][:24]
            semantic_diagnostics = []
            if self.semantic_snapshot is not None:
                uri = path.resolve().as_uri()
                semantic_diagnostics = [
                    {
                        "severity": int(item.severity),
                        "message": item.message,
                        "line": item.range.start.line,
                        "source": item.source,
                    }
                    for item in self.semantic_snapshot.diagnostics
                    if item.uri == uri
                    and start <= item.range.start.line <= end
                ][:24]
            chunks.append(
                ContextChunk(
                    source_id=f"codegraph:{symbol.symbol_id}",
                    content=content,
                    relevance_score=min(2.0, score),
                    token_estimate=max(1, len(content) // 4),
                    sensitivity=self.sensitivity,
                    metadata={
                        "retrieval_kind": "code_graph_symbol",
                        "path": symbol.file_path,
                        "symbol": symbol.qualified_name,
                        "symbol_kind": symbol.kind.value,
                        "line": symbol.line,
                        "file_digest": self.index.file_digests.get(symbol.file_path),
                        "outgoing_references": refs,
                        "semantic_diagnostics": semantic_diagnostics,
                    },
                )
            )
        return chunks
