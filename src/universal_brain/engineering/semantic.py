"""Semantic code intelligence for Universal Brain V5.2.

Traceability: REQ-ENG-021, REQ-ENG-022, REQ-ENG-023, ALN-007, ALN-012,
ALN-020. Tree-sitter and LSP are *derived sensing layers*. They never grant
filesystem authority and never directly apply refactors.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, Field


class SemanticBackendUnavailable(RuntimeError):
    pass


class DiagnosticSeverity(int, Enum):
    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


class SourcePosition(BaseModel):
    line: int = Field(ge=0)
    character: int = Field(ge=0)


class SourceRange(BaseModel):
    start: SourcePosition
    end: SourcePosition


class SemanticLocation(BaseModel):
    uri: str
    range: SourceRange


class SemanticDiagnostic(BaseModel):
    uri: str
    range: SourceRange
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    code: str | int | None = None
    source: str | None = None


class SemanticSymbolFact(BaseModel):
    name: str
    kind: str
    uri: str
    range: SourceRange
    selection_range: SourceRange | None = None
    detail: str | None = None
    provider: str


class SemanticReferenceFact(BaseModel):
    symbol_name: str
    location: SemanticLocation
    provider: str


class SemanticGraphSnapshot(BaseModel):
    symbols: list[SemanticSymbolFact] = Field(default_factory=list)
    references: list[SemanticReferenceFact] = Field(default_factory=list)
    diagnostics: list[SemanticDiagnostic] = Field(default_factory=list)
    provider_notes: list[str] = Field(default_factory=list)


class LspRequestBackend(Protocol):
    """Authority-neutral JSON-RPC request transport for an already-authorized LSP.

    The backend owns process lifecycle/isolation. This layer only speaks standard
    Language Server Protocol request payloads.
    """

    async def request(self, method: str, params: dict[str, Any]) -> Any: ...


class LspSemanticProvider:
    """Standard-LSP semantic sensing adapter.

    It consumes documentSymbol/reference/diagnostic/rename responses without
    assuming a particular language server. This makes pyright, clangd, rust-analyzer,
    tsserver-compatible bridges, etc. replaceable transports rather than architecture.
    """

    def __init__(self, backend: LspRequestBackend, *, provider_id: str = "lsp") -> None:
        self.backend = backend
        self.provider_id = provider_id

    async def document_symbols(self, uri: str) -> list[SemanticSymbolFact]:
        raw = await self.backend.request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
        return self._flatten_symbols(uri, raw or [])

    async def references(
        self,
        uri: str,
        position: SourcePosition,
        *,
        symbol_name: str,
        include_declaration: bool = True,
    ) -> list[SemanticReferenceFact]:
        raw = await self.backend.request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": position.model_dump(),
                "context": {"includeDeclaration": include_declaration},
            },
        )
        facts: list[SemanticReferenceFact] = []
        for item in raw or []:
            if not isinstance(item, dict) or "uri" not in item or "range" not in item:
                continue
            facts.append(
                SemanticReferenceFact(
                    symbol_name=symbol_name,
                    location=SemanticLocation(uri=str(item["uri"]), range=SourceRange.model_validate(item["range"])),
                    provider=self.provider_id,
                )
            )
        return facts

    async def diagnostics(self, uri: str) -> list[SemanticDiagnostic]:
        """Use LSP 3.17 pull diagnostics when the server supports it.

        Push-diagnostic backends may expose their latest cached report through the
        same request backend. An unsupported method should be handled by the backend
        and surfaced as unavailable rather than silently fabricating diagnostics.
        """
        raw = await self.backend.request("textDocument/diagnostic", {"textDocument": {"uri": uri}})
        items = raw.get("items", []) if isinstance(raw, dict) else []
        diagnostics: list[SemanticDiagnostic] = []
        for item in items:
            if not isinstance(item, dict) or "range" not in item:
                continue
            severity_value = int(item.get("severity") or DiagnosticSeverity.ERROR)
            try:
                severity = DiagnosticSeverity(severity_value)
            except ValueError:
                severity = DiagnosticSeverity.ERROR
            diagnostics.append(
                SemanticDiagnostic(
                    uri=uri,
                    range=SourceRange.model_validate(item["range"]),
                    message=str(item.get("message", "")),
                    severity=severity,
                    code=item.get("code"),
                    source=item.get("source"),
                )
            )
        return diagnostics

    async def workspace_symbols(self, query: str) -> list[SemanticSymbolFact]:
        raw = await self.backend.request("workspace/symbol", {"query": query})
        facts: list[SemanticSymbolFact] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            location = item.get("location") or {}
            if not isinstance(location, dict) or "uri" not in location or "range" not in location:
                continue
            facts.append(
                SemanticSymbolFact(
                    name=str(item.get("name", "")),
                    kind=str(item.get("kind", "unknown")),
                    uri=str(location["uri"]),
                    range=SourceRange.model_validate(location["range"]),
                    provider=self.provider_id,
                    detail=item.get("containerName"),
                )
            )
        return facts

    def _flatten_symbols(self, uri: str, items: list[dict[str, Any]]) -> list[SemanticSymbolFact]:
        facts: list[SemanticSymbolFact] = []

        def visit(item: dict[str, Any]) -> None:
            raw_range = item.get("range") or item.get("location", {}).get("range")
            raw_uri = item.get("location", {}).get("uri") or uri
            if raw_range:
                facts.append(
                    SemanticSymbolFact(
                        name=str(item.get("name", "")),
                        kind=str(item.get("kind", "unknown")),
                        uri=str(raw_uri),
                        range=SourceRange.model_validate(raw_range),
                        selection_range=(
                            SourceRange.model_validate(item["selectionRange"])
                            if item.get("selectionRange")
                            else None
                        ),
                        detail=item.get("detail") or item.get("containerName"),
                        provider=self.provider_id,
                    )
                )
            for child in item.get("children", []) or []:
                if isinstance(child, dict):
                    visit(child)

        for item in items:
            if isinstance(item, dict):
                visit(item)
        return facts


class TreeSitterSemanticProvider:
    """Optional real Tree-sitter parser backed by ``tree-sitter-language-pack``.

    The dependency is optional so minimal/kernel deployments remain lightweight.
    When installed, this provider parses supported source files using real syntax
    trees and emits named declaration facts. It intentionally does not pretend to
    provide cross-file type resolution; LSP remains authoritative for that layer.
    """

    LANGUAGE_BY_SUFFIX = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".c": "c",
        ".h": "c",
        ".cc": "cpp",
        ".cpp": "cpp",
        ".hpp": "cpp",
    }
    DECLARATION_TYPES = {
        "class_definition",
        "function_definition",
        "function_declaration",
        "method_definition",
        "method_declaration",
        "class_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "struct_item",
        "enum_item",
        "function_item",
        "impl_item",
        "struct_specifier",
        "enum_specifier",
    }

    def __init__(self, *, provider_id: str = "tree-sitter") -> None:
        self.provider_id = provider_id

    def parse_file(self, path: Path) -> list[SemanticSymbolFact]:
        language = self.LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if language is None:
            return []
        try:
            from tree_sitter_language_pack import get_parser  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency optional in CI
            raise SemanticBackendUnavailable(
                "Tree-sitter semantic provider requires optional dependency "
                "tree-sitter-language-pack"
            ) from exc

        parser = get_parser(language)
        data = path.read_bytes()
        tree = parser.parse(data)
        uri = path.resolve().as_uri()
        facts: list[SemanticSymbolFact] = []

        def text(node) -> str:
            return data[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

        def visit(node) -> None:
            if node.type in self.DECLARATION_TYPES:
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    facts.append(
                        SemanticSymbolFact(
                            name=text(name_node),
                            kind=node.type,
                            uri=uri,
                            range=SourceRange(
                                start=SourcePosition(line=node.start_point.row, character=node.start_point.column),
                                end=SourcePosition(line=node.end_point.row, character=node.end_point.column),
                            ),
                            selection_range=SourceRange(
                                start=SourcePosition(
                                    line=name_node.start_point.row,
                                    character=name_node.start_point.column,
                                ),
                                end=SourcePosition(
                                    line=name_node.end_point.row,
                                    character=name_node.end_point.column,
                                ),
                            ),
                            provider=self.provider_id,
                        )
                    )
            for child in node.children:
                if child.is_named:
                    visit(child)

        visit(tree.root_node)
        return facts


class RefactorTextEdit(BaseModel):
    uri: str
    range: SourceRange
    new_text: str


class SymbolRenamePlan(BaseModel):
    symbol_name: str
    new_name: str
    edits: list[RefactorTextEdit] = Field(default_factory=list)
    provider: str = "lsp"


class LspRenamePlanner:
    """Generate a symbol-safe rename plan from LSP ``textDocument/rename``.

    The planner validates that every edit targets an explicitly allowed workspace.
    It does **not** write files. Application still belongs behind ToolGateway.
    """

    def __init__(self, backend: LspRequestBackend, allowed_roots: list[Path]) -> None:
        self.backend = backend
        self.allowed_roots = [root.resolve() for root in allowed_roots]

    async def plan(
        self,
        *,
        uri: str,
        position: SourcePosition,
        symbol_name: str,
        new_name: str,
    ) -> SymbolRenamePlan:
        if not new_name.strip() or any(ch.isspace() for ch in new_name):
            raise ValueError("new_name must be a non-empty identifier-like token")
        raw = await self.backend.request(
            "textDocument/rename",
            {
                "textDocument": {"uri": uri},
                "position": position.model_dump(),
                "newName": new_name,
            },
        )
        if not isinstance(raw, dict):
            raise ValueError("LSP rename returned no WorkspaceEdit")
        if raw.get("documentChanges"):
            raise ValueError(
                "LSP rename requested documentChanges/file operations; fail closed until explicit file-operation support"
            )
        edits: list[RefactorTextEdit] = []
        for edit_uri, raw_edits in (raw.get("changes") or {}).items():
            path = self._uri_to_path(str(edit_uri))
            self._assert_allowed(path)
            for item in raw_edits or []:
                if not isinstance(item, dict) or "range" not in item:
                    continue
                edits.append(
                    RefactorTextEdit(
                        uri=str(edit_uri),
                        range=SourceRange.model_validate(item["range"]),
                        new_text=str(item.get("newText", "")),
                    )
                )
        if not edits:
            raise ValueError("LSP rename produced no text edits")
        return SymbolRenamePlan(symbol_name=symbol_name, new_name=new_name, edits=edits)

    @staticmethod
    def _uri_to_path(uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise ValueError(f"Refactor edit uses unsupported URI scheme: {parsed.scheme!r}")
        path_text = unquote(parsed.path)
        if parsed.netloc:
            path_text = f"//{parsed.netloc}{path_text}"
        # Windows file:///C:/... URI normalization when running on Windows.
        if len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":":
            path_text = path_text[1:]
        return Path(path_text).resolve()

    def _assert_allowed(self, path: Path) -> None:
        for root in self.allowed_roots:
            if path == root or root in path.parents:
                return
        raise ValueError(f"LSP refactor edit escapes authorized workspace roots: {path}")


class DiagnosticDocumentState(BaseModel):
    uri: str
    document_version: int | None = None
    content_digest: str | None = None
    diagnostics: list[SemanticDiagnostic] = Field(default_factory=list)


class IncrementalDiagnosticRegistry:
    """Version/digest-aware LSP diagnostic cache.

    Newer document versions replace older diagnostics. A content digest mismatch can
    explicitly invalidate cached findings after autonomous edits, preventing stale
    diagnostics from being treated as current verification evidence.
    """

    def __init__(self) -> None:
        self._documents: dict[str, DiagnosticDocumentState] = {}

    def update(
        self,
        *,
        uri: str,
        diagnostics: list[SemanticDiagnostic],
        document_version: int | None = None,
        content_digest: str | None = None,
    ) -> DiagnosticDocumentState:
        previous = self._documents.get(uri)
        if (
            previous is not None
            and previous.document_version is not None
            and document_version is not None
            and document_version < previous.document_version
        ):
            raise ValueError("stale LSP diagnostic version rejected")
        state = DiagnosticDocumentState(
            uri=uri,
            document_version=document_version,
            content_digest=content_digest,
            diagnostics=list(diagnostics),
        )
        self._documents[uri] = state
        return state

    def invalidate_if_digest_changed(self, *, uri: str, current_digest: str) -> bool:
        state = self._documents.get(uri)
        if state is None or state.content_digest is None or state.content_digest == current_digest:
            return False
        self._documents.pop(uri, None)
        return True

    def diagnostics_for(self, uri: str) -> list[SemanticDiagnostic]:
        state = self._documents.get(uri)
        return list(state.diagnostics) if state else []

    def all_diagnostics(self) -> list[SemanticDiagnostic]:
        return [item for state in self._documents.values() for item in state.diagnostics]

    def error_count(self) -> int:
        return sum(1 for item in self.all_diagnostics() if item.severity == DiagnosticSeverity.ERROR)
