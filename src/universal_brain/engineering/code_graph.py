"""Codebase-wide symbol graph foundation for Universal Brain V5/V5.1.

Traceability: REQ-ENG-005, REQ-ENG-015, REQ-STA-001, ALN-012. This index is
derived state; source files remain canonical. Python uses the stdlib AST for
deterministic symbol/call/import extraction. Other supported languages receive
conservative lexical symbols. V5.1 adds incremental refresh and transitive impact.
"""

from __future__ import annotations

import ast
import hashlib
import re
from enum import Enum
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field


class SymbolKind(str, Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    IMPORT = "import"
    CONSTANT = "constant"


class SymbolRecord(BaseModel):
    symbol_id: str
    name: str
    qualified_name: str
    kind: SymbolKind
    file_path: str
    line: int = 1
    end_line: int | None = None
    digest: str = ""


class ReferenceEdge(BaseModel):
    source_symbol_id: str
    target_name: str
    relation: str
    file_path: str
    line: int = 1


class CodeGraphDelta(BaseModel):
    changed_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    unchanged_files: list[str] = Field(default_factory=list)
    symbols_added: int = 0
    symbols_removed: int = 0
    references_added: int = 0
    references_removed: int = 0


class CodeGraphIndex(BaseModel):
    repository_root: str
    file_digests: dict[str, str] = Field(default_factory=dict)
    symbols: dict[str, SymbolRecord] = Field(default_factory=dict)
    references: list[ReferenceEdge] = Field(default_factory=list)

    def find_symbol(self, name: str) -> list[SymbolRecord]:
        needle = name.strip().lower()
        return [
            symbol
            for symbol in self.symbols.values()
            if symbol.name.lower() == needle or symbol.qualified_name.lower().endswith(f".{needle}")
        ]

    def references_to(self, name: str) -> list[ReferenceEdge]:
        needle = name.strip().lower()
        return [edge for edge in self.references if edge.target_name.lower() == needle]

    def files_impacted_by(self, changed_files: Iterable[str], *, max_depth: int = 6) -> list[str]:
        """Return source/test files transitively dependent on changed definitions.

        This is intentionally conservative. It propagates by symbol names and import
        references; it does not claim semantic equivalence to a full language server.
        """
        changed = {Path(path).as_posix() for path in changed_files}
        impacted = set(changed)
        frontier = set(changed)
        depth = 0
        while frontier and depth < max_depth:
            depth += 1
            names = {
                symbol.name
                for symbol in self.symbols.values()
                if Path(symbol.file_path).as_posix() in frontier
            }
            if not names:
                break
            new_files = {
                Path(edge.file_path).as_posix()
                for edge in self.references
                if edge.target_name in names and Path(edge.file_path).as_posix() not in impacted
            }
            impacted.update(new_files)
            frontier = new_files
        return sorted(impacted)

    def affected_tests(self, changed_files: Iterable[str]) -> list[str]:
        changed = {str(Path(path).as_posix()) for path in changed_files}
        impacted = set(self.files_impacted_by(changed))
        defined_names = {
            symbol.name
            for symbol in self.symbols.values()
            if Path(symbol.file_path).as_posix() in changed
        }
        tests: set[str] = {path for path in impacted if self._is_test_file(path)}
        for edge in self.references:
            path = Path(edge.file_path).as_posix()
            if self._is_test_file(path) and edge.target_name in defined_names:
                tests.add(path)
        changed_stems = {Path(path).stem.replace("test_", "") for path in changed}
        for symbol in self.symbols.values():
            path = Path(symbol.file_path).as_posix()
            if self._is_test_file(path) and any(stem and stem in Path(path).stem for stem in changed_stems):
                tests.add(path)
        return sorted(tests)

    @staticmethod
    def _is_test_file(path: str) -> bool:
        p = Path(path)
        return (
            "tests" in p.parts
            or p.name.startswith("test_")
            or p.name.endswith((".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx"))
        )


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str, module_name: str):
        self.rel_path = rel_path
        self.module_name = module_name
        self.scope: list[str] = []
        self.symbols: list[SymbolRecord] = []
        self.references: list[ReferenceEdge] = []
        self._active_symbol_id = f"module:{rel_path}"

    def _qualified(self, name: str) -> str:
        return ".".join([self.module_name, *self.scope, name]) if self.module_name else ".".join([*self.scope, name])

    def _add_symbol(self, node, name: str, kind: SymbolKind) -> str:
        qualified = self._qualified(name)
        symbol_id = hashlib.sha256(f"{self.rel_path}:{qualified}:{kind.value}".encode()).hexdigest()[:24]
        self.symbols.append(
            SymbolRecord(
                symbol_id=symbol_id,
                name=name,
                qualified_name=qualified,
                kind=kind,
                file_path=self.rel_path,
                line=getattr(node, "lineno", 1),
                end_line=getattr(node, "end_lineno", None),
            )
        )
        return symbol_id

    def visit_ClassDef(self, node: ast.ClassDef):
        symbol_id = self._add_symbol(node, node.name, SymbolKind.CLASS)
        previous = self._active_symbol_id
        self._active_symbol_id = symbol_id
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()
        self._active_symbol_id = previous

    def visit_FunctionDef(self, node: ast.FunctionDef):
        kind = SymbolKind.METHOD if self.scope else SymbolKind.FUNCTION
        symbol_id = self._add_symbol(node, node.name, kind)
        previous = self._active_symbol_id
        self._active_symbol_id = symbol_id
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()
        self._active_symbol_id = previous

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call):
        target = self._call_name(node.func)
        if target:
            self.references.append(
                ReferenceEdge(
                    source_symbol_id=self._active_symbol_id,
                    target_name=target,
                    relation="calls",
                    file_path=self.rel_path,
                    line=getattr(node, "lineno", 1),
                )
            )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.references.append(
                ReferenceEdge(
                    source_symbol_id=self._active_symbol_id,
                    target_name=alias.asname or alias.name.split(".")[-1],
                    relation=f"imports:{alias.name}",
                    file_path=self.rel_path,
                    line=getattr(node, "lineno", 1),
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module or ""
        for alias in node.names:
            target = f"{module}.{alias.name}".strip(".")
            self.references.append(
                ReferenceEdge(
                    source_symbol_id=self._active_symbol_id,
                    target_name=alias.name,
                    relation=f"imports:{target}",
                    file_path=self.rel_path,
                    line=getattr(node, "lineno", 1),
                )
            )

    @staticmethod
    def _call_name(node) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None


class CodeGraphIndexer:
    EXCLUDED = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".brain"}
    TEXT_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".cpp", ".cc", ".c", ".h", ".hpp"}

    def build(self, repository_root: Path) -> CodeGraphIndex:
        root = repository_root.resolve()
        index = CodeGraphIndex(repository_root=str(root))
        for path in self._iter_source_files(root):
            self._replace_file(index, root, path)
        return index

    def refresh(self, index: CodeGraphIndex) -> CodeGraphDelta:
        """Incrementally refresh changed/deleted source files in an existing index."""
        root = Path(index.repository_root).resolve()
        current: dict[str, tuple[Path, str]] = {}
        for path in self._iter_source_files(root):
            rel = path.relative_to(root).as_posix()
            digest = self._digest_file(path)
            if digest is not None:
                current[rel] = (path, digest)

        previous_files = set(index.file_digests)
        current_files = set(current)
        deleted = sorted(previous_files - current_files)
        changed = sorted(
            rel for rel, (_path, digest) in current.items() if index.file_digests.get(rel) != digest
        )
        unchanged = sorted(current_files - set(changed))

        before_symbols = len(index.symbols)
        before_refs = len(index.references)
        for rel in deleted:
            self._remove_file(index, rel)
        for rel in changed:
            self._replace_file(index, root, current[rel][0], known_digest=current[rel][1])

        after_symbols = len(index.symbols)
        after_refs = len(index.references)
        return CodeGraphDelta(
            changed_files=changed,
            deleted_files=deleted,
            unchanged_files=unchanged,
            symbols_added=max(0, after_symbols - before_symbols),
            symbols_removed=max(0, before_symbols - after_symbols),
            references_added=max(0, after_refs - before_refs),
            references_removed=max(0, before_refs - after_refs),
        )

    def _iter_source_files(self, root: Path):
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in self.TEXT_EXTENSIONS:
                continue
            rel = path.relative_to(root)
            if any(part in self.EXCLUDED for part in rel.parts):
                continue
            yield path

    @staticmethod
    def _digest_file(path: Path) -> str | None:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    def _replace_file(
        self,
        index: CodeGraphIndex,
        root: Path,
        path: Path,
        *,
        known_digest: str | None = None,
    ) -> None:
        rel = path.relative_to(root).as_posix()
        self._remove_file(index, rel)
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return
        index.file_digests[rel] = known_digest or hashlib.sha256(raw).hexdigest()
        if path.suffix.lower() == ".py":
            self._index_python(index, rel, text)
        else:
            self._index_lexical(index, rel, text)

    @staticmethod
    def _remove_file(index: CodeGraphIndex, rel: str) -> None:
        index.file_digests.pop(rel, None)
        for symbol_id in [sid for sid, symbol in index.symbols.items() if symbol.file_path == rel]:
            index.symbols.pop(symbol_id, None)
        index.references = [edge for edge in index.references if edge.file_path != rel]

    @staticmethod
    def _index_python(index: CodeGraphIndex, rel: str, text: str) -> None:
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError:
            return
        module_name = Path(rel).with_suffix("").as_posix().replace("/", ".")
        visitor = _PythonVisitor(rel, module_name)
        visitor.visit(tree)
        for symbol in visitor.symbols:
            symbol.digest = index.file_digests[rel]
            index.symbols[symbol.symbol_id] = symbol
        index.references.extend(visitor.references)

    @staticmethod
    def _index_lexical(index: CodeGraphIndex, rel: str, text: str) -> None:
        patterns = [
            (SymbolKind.CLASS, re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)),
            (SymbolKind.FUNCTION, re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)),
            (SymbolKind.FUNCTION, re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)),
        ]
        for kind, pattern in patterns:
            for match in pattern.finditer(text):
                name = match.group(1)
                line = text.count("\n", 0, match.start()) + 1
                symbol_id = hashlib.sha256(f"{rel}:{name}:{kind.value}:{line}".encode()).hexdigest()[:24]
                index.symbols[symbol_id] = SymbolRecord(
                    symbol_id=symbol_id,
                    name=name,
                    qualified_name=f"{rel}:{name}",
                    kind=kind,
                    file_path=rel,
                    line=line,
                    digest=index.file_digests[rel],
                )
