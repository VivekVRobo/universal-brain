"""Repository ecosystem discovery for engineering missions.

Traceability: REQ-ENG-013, REQ-STA-001, ALN-012. Discovery is read-only and does
not install dependencies or mutate manifests.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from .schemas import EngineeringWorkspace


class EngineeringWorkspaceInspector:
    def discover(self, repository_root: Path, *, project_id: UUID) -> EngineeringWorkspace:
        root = repository_root.resolve()
        languages: list[str] = []
        build_systems: list[str] = []
        test_commands: list[list[str]] = []

        if (root / "pyproject.toml").exists() or any(root.glob("requirements*.txt")):
            languages.append("python")
            build_systems.append("python-packaging")
            if (root / "tests").exists():
                test_commands.append(["pytest", "-q"])
        if (root / "package.json").exists():
            languages.append("javascript-typescript")
            package = self._read_json(root / "package.json")
            scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
            build_systems.append("npm")
            if "test" in scripts:
                test_commands.append(["npm", "test", "--", "--runInBand"])
            if (root / "tsconfig.json").exists():
                test_commands.append(["npm", "exec", "tsc", "--", "--noEmit"])
        if (root / "Cargo.toml").exists():
            languages.append("rust")
            build_systems.append("cargo")
            test_commands.append(["cargo", "test", "--all-targets"])
        if (root / "CMakeLists.txt").exists():
            build_systems.append("cmake")
        if (root / "src").exists() and any(root.rglob("package.xml")):
            languages.append("ros2")
            build_systems.append("colcon")
            test_commands.append(["colcon", "test", "--event-handlers", "console_direct+"])

        git_root = root if (root / ".git").exists() else None
        return EngineeringWorkspace(
            project_id=project_id,
            repository_root=root,
            git_root=git_root,
            worktree_root=root / ".brain" / "worktrees",
            language_ecosystems=sorted(set(languages)),
            build_systems=sorted(set(build_systems)),
            test_commands=test_commands,
            metadata={"discovered": True},
        )

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
