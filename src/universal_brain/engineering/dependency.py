"""Manifest-aware dependency failure diagnosis.

Traceability: REQ-ENG-019, REQ-ENG-012, ALN-007. This module proposes
conservative repair plans. It never installs packages itself.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class DependencyEcosystem(str, Enum):
    PYTHON = "python"
    NPM = "npm"
    CARGO = "cargo"
    ROS2 = "ros2"
    CMAKE = "cmake"
    UNKNOWN = "unknown"


class DependencyRepairPlan(BaseModel):
    ecosystem: DependencyEcosystem
    package_manager: str
    manifest_paths: list[str] = Field(default_factory=list)
    lockfile_paths: list[str] = Field(default_factory=list)
    missing_name: str | None = None
    diagnostic: str
    suggested_commands: list[list[str]] = Field(default_factory=list)
    requires_manifest_review: bool = True


class DependencyFailureDiagnoser:
    PYTHON_PATTERNS = [
        re.compile(r"No module named ['\"]?([A-Za-z0-9_.-]+)", re.I),
        re.compile(r"ModuleNotFoundError:.*?['\"]([A-Za-z0-9_.-]+)['\"]", re.I),
    ]
    NPM_PATTERNS = [
        re.compile(r"Cannot find module ['\"]([^'\"]+)", re.I),
        re.compile(r"Module not found:.*?['\"]?(@?[A-Za-z0-9_./-]+)", re.I),
    ]
    CARGO_PATTERNS = [
        re.compile(r"can't find crate for [`']([A-Za-z0-9_-]+)", re.I),
        re.compile(r"use of unresolved (?:module|crate) [`']([A-Za-z0-9_-]+)", re.I),
    ]

    def diagnose(self, root: Path, output: str) -> DependencyRepairPlan:
        root = root.resolve()
        ecosystem, manager, manifests, locks = self._detect_ecosystem(root)
        missing = self._extract_missing(ecosystem, output)
        commands: list[list[str]] = []

        if ecosystem == DependencyEcosystem.PYTHON:
            if (root / "uv.lock").exists():
                manager = "uv"
                commands = [["uv", "sync", "--frozen"]]
            elif (root / "poetry.lock").exists():
                manager = "poetry"
                commands = [["poetry", "install", "--sync"]]
            elif (root / "requirements.txt").exists():
                manager = "pip"
                commands = [["python", "-m", "pip", "install", "-r", "requirements.txt"]]
            else:
                commands = [["python", "-m", "pip", "install", "-e", "."]]
        elif ecosystem == DependencyEcosystem.NPM:
            if (root / "pnpm-lock.yaml").exists():
                manager = "pnpm"
                commands = [["pnpm", "install", "--frozen-lockfile"]]
            elif (root / "yarn.lock").exists():
                manager = "yarn"
                commands = [["yarn", "install", "--immutable"]]
            else:
                manager = "npm"
                commands = [["npm", "ci"] if (root / "package-lock.json").exists() else ["npm", "install"]]
        elif ecosystem == DependencyEcosystem.CARGO:
            commands = [["cargo", "fetch", "--locked"] if (root / "Cargo.lock").exists() else ["cargo", "fetch"]]
        elif ecosystem == DependencyEcosystem.ROS2:
            commands = [["rosdep", "install", "--from-paths", "src", "--ignore-src", "-r", "-y"]]
        elif ecosystem == DependencyEcosystem.CMAKE:
            commands = [["cmake", "--build", "build"]]

        return DependencyRepairPlan(
            ecosystem=ecosystem,
            package_manager=manager,
            manifest_paths=manifests,
            lockfile_paths=locks,
            missing_name=missing,
            diagnostic=(output[-2000:] if output else "dependency failure without diagnostic output"),
            suggested_commands=commands,
            requires_manifest_review=True,
        )

    @staticmethod
    def _detect_ecosystem(root: Path):
        if (root / "package.json").exists():
            locks = [name for name in ("pnpm-lock.yaml", "yarn.lock", "package-lock.json") if (root / name).exists()]
            return DependencyEcosystem.NPM, "npm", ["package.json"], locks
        if (root / "Cargo.toml").exists():
            locks = ["Cargo.lock"] if (root / "Cargo.lock").exists() else []
            return DependencyEcosystem.CARGO, "cargo", ["Cargo.toml"], locks
        if any(root.rglob("package.xml")) and (root / "src").exists():
            manifests = [p.relative_to(root).as_posix() for p in sorted(root.rglob("package.xml"))[:50]]
            return DependencyEcosystem.ROS2, "rosdep", manifests, []
        if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
            manifests = [name for name in ("pyproject.toml", "requirements.txt") if (root / name).exists()]
            locks = [name for name in ("uv.lock", "poetry.lock", "Pipfile.lock") if (root / name).exists()]
            return DependencyEcosystem.PYTHON, "python", manifests, locks
        if (root / "CMakeLists.txt").exists():
            return DependencyEcosystem.CMAKE, "cmake", ["CMakeLists.txt"], []
        return DependencyEcosystem.UNKNOWN, "unknown", [], []

    def _extract_missing(self, ecosystem: DependencyEcosystem, output: str) -> str | None:
        patterns = {
            DependencyEcosystem.PYTHON: self.PYTHON_PATTERNS,
            DependencyEcosystem.NPM: self.NPM_PATTERNS,
            DependencyEcosystem.CARGO: self.CARGO_PATTERNS,
        }.get(ecosystem, [])
        for pattern in patterns:
            match = pattern.search(output or "")
            if match:
                return match.group(1)
        return None
