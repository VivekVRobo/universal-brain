"""Multi-repository dependency graph for Universal Brain V5.2.

Traceability: REQ-ENG-027, REQ-ENG-015, ALN-012. The graph is derived from
repository manifests and local path references. It is advisory context, not authority.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class RepositoryDescriptor(BaseModel):
    repo_id: str
    root: Path
    package_names: set[str] = Field(default_factory=set)
    ecosystems: set[str] = Field(default_factory=set)


class RepositoryDependencyEdge(BaseModel):
    source_repo_id: str
    target_repo_id: str
    ecosystem: str
    dependency_name: str
    manifest_path: str
    relation: str = "depends_on"


class MultiRepositoryGraph(BaseModel):
    repositories: dict[str, RepositoryDescriptor] = Field(default_factory=dict)
    edges: list[RepositoryDependencyEdge] = Field(default_factory=list)

    def downstream(self, repo_id: str, *, max_depth: int = 8) -> list[str]:
        """Repositories that transitively depend on ``repo_id``."""
        impacted = {repo_id}
        frontier = {repo_id}
        for _ in range(max_depth):
            next_frontier = {
                edge.source_repo_id
                for edge in self.edges
                if edge.target_repo_id in frontier and edge.source_repo_id not in impacted
            }
            if not next_frontier:
                break
            impacted.update(next_frontier)
            frontier = next_frontier
        impacted.discard(repo_id)
        return sorted(impacted)

    def dependencies_of(self, repo_id: str) -> list[str]:
        return sorted({edge.target_repo_id for edge in self.edges if edge.source_repo_id == repo_id})


class MultiRepositoryGraphBuilder:
    def build(self, roots: list[Path]) -> MultiRepositoryGraph:
        descriptors: dict[str, RepositoryDescriptor] = {}
        by_name: dict[str, str] = {}
        normalized_roots = [root.resolve() for root in roots]
        for index, root in enumerate(normalized_roots):
            repo_id = self._repo_id(root, index)
            descriptor = self._describe(repo_id, root)
            descriptors[repo_id] = descriptor
            for name in descriptor.package_names:
                by_name[name] = repo_id

        by_root = {desc.root.resolve(): repo_id for repo_id, desc in descriptors.items()}
        edges: list[RepositoryDependencyEdge] = []
        for repo_id, descriptor in descriptors.items():
            edges.extend(self._manifest_edges(descriptor, by_name, by_root))

        unique: dict[tuple[str, str, str, str, str], RepositoryDependencyEdge] = {}
        for edge in edges:
            key = (
                edge.source_repo_id,
                edge.target_repo_id,
                edge.ecosystem,
                edge.dependency_name,
                edge.manifest_path,
            )
            if edge.source_repo_id != edge.target_repo_id:
                unique[key] = edge
        return MultiRepositoryGraph(repositories=descriptors, edges=list(unique.values()))

    @staticmethod
    def _repo_id(root: Path, index: int) -> str:
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-") or f"repo-{index}"
        return f"{base}-{index}" if index else base

    def _describe(self, repo_id: str, root: Path) -> RepositoryDescriptor:
        names: set[str] = {root.name}
        ecosystems: set[str] = set()
        package_json = root / "package.json"
        if package_json.exists():
            ecosystems.add("npm")
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
                if data.get("name"):
                    names.add(str(data["name"]))
            except (OSError, json.JSONDecodeError):
                pass
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            ecosystems.add("python")
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                project_name = data.get("project", {}).get("name")
                poetry_name = data.get("tool", {}).get("poetry", {}).get("name")
                if project_name:
                    names.add(str(project_name))
                if poetry_name:
                    names.add(str(poetry_name))
            except (OSError, tomllib.TOMLDecodeError):
                pass
        cargo = root / "Cargo.toml"
        if cargo.exists():
            ecosystems.add("cargo")
            try:
                data = tomllib.loads(cargo.read_text(encoding="utf-8"))
                if data.get("package", {}).get("name"):
                    names.add(str(data["package"]["name"]))
            except (OSError, tomllib.TOMLDecodeError):
                pass
        package_xml = root / "package.xml"
        if package_xml.exists():
            ecosystems.add("ros2")
            try:
                text = package_xml.read_text(encoding="utf-8", errors="replace")
                match = re.search(r"<name>\s*([^<]+?)\s*</name>", text)
                if match:
                    names.add(match.group(1).strip())
            except OSError:
                pass
        if (root / "CMakeLists.txt").exists():
            ecosystems.add("cmake")
        return RepositoryDescriptor(repo_id=repo_id, root=root, package_names=names, ecosystems=ecosystems)

    def _manifest_edges(
        self,
        source: RepositoryDescriptor,
        by_name: dict[str, str],
        by_root: dict[Path, str],
    ) -> list[RepositoryDependencyEdge]:
        edges: list[RepositoryDependencyEdge] = []
        root = source.root

        package_json = root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                for name, value in (data.get(section) or {}).items():
                    target = by_name.get(str(name))
                    if isinstance(value, str) and value.startswith("file:"):
                        target = self._target_from_path(root, value[5:], by_root) or target
                    if target:
                        edges.append(self._edge(source, target, "npm", str(name), package_json))

        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                data = {}
            poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
            for name, value in poetry.items():
                target = by_name.get(str(name))
                if isinstance(value, dict) and value.get("path"):
                    target = self._target_from_path(root, str(value["path"]), by_root) or target
                if target:
                    edges.append(self._edge(source, target, "python", str(name), pyproject))

        cargo = root / "Cargo.toml"
        if cargo.exists():
            try:
                data = tomllib.loads(cargo.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                data = {}
            for section in ("dependencies", "dev-dependencies", "build-dependencies"):
                for name, value in (data.get(section) or {}).items():
                    target = by_name.get(str(name))
                    if isinstance(value, dict) and value.get("path"):
                        target = self._target_from_path(root, str(value["path"]), by_root) or target
                    if target:
                        edges.append(self._edge(source, target, "cargo", str(name), cargo))

        package_xml = root / "package.xml"
        if package_xml.exists():
            try:
                text = package_xml.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for name in re.findall(
                r"<(?:depend|exec_depend|build_depend|buildtool_depend|test_depend)>\s*([^<]+?)\s*</",
                text,
            ):
                target = by_name.get(name.strip())
                if target:
                    edges.append(self._edge(source, target, "ros2", name.strip(), package_xml))

        cmake = root / "CMakeLists.txt"
        if cmake.exists():
            try:
                text = cmake.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for rel in re.findall(r"add_subdirectory\s*\(\s*([^\s\)]+)", text, flags=re.I):
                target = self._target_from_path(root, rel.strip('"\''), by_root)
                if target:
                    edges.append(self._edge(source, target, "cmake", rel, cmake))
        return edges

    @staticmethod
    def _target_from_path(source_root: Path, relative: str, by_root: dict[Path, str]) -> str | None:
        try:
            candidate = (source_root / relative).resolve()
        except OSError:
            return None
        return by_root.get(candidate)

    @staticmethod
    def _edge(
        source: RepositoryDescriptor,
        target_repo_id: str,
        ecosystem: str,
        dependency_name: str,
        manifest: Path,
    ) -> RepositoryDependencyEdge:
        return RepositoryDependencyEdge(
            source_repo_id=source.repo_id,
            target_repo_id=target_repo_id,
            ecosystem=ecosystem,
            dependency_name=dependency_name,
            manifest_path=manifest.relative_to(source.root).as_posix(),
        )
