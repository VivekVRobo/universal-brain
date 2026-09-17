"""Durable engineering mission checkpoints and workspace-drift recovery.

Traceability: REQ-ENG-014, REQ-STA-003, ALN-005, ALN-016, ALN-020.
Checkpoints are derived execution state. They never expand authority and are
self-verifying before a mission is resumed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from universal_brain.executive.schemas import TaskDAG, TaskNodeStatus

from .schemas import EngineeringNodeRun


class EngineeringCheckpointError(RuntimeError):
    pass


class WorkspaceFingerprint(BaseModel):
    digest: str
    file_count: int
    total_bytes: int


class EngineeringMissionCheckpoint(BaseModel):
    schema_version: int = 1
    dag: TaskDAG
    workspace_fingerprint: WorkspaceFingerprint
    runs: list[EngineeringNodeRun] = Field(default_factory=list)
    requirement_worktrees: dict[str, dict[str, Any]] = Field(default_factory=dict)
    worktree_fingerprints: dict[str, WorkspaceFingerprint] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    payload_sha256: str = ""

    def canonical_payload(self) -> bytes:
        payload = self.model_dump(mode="json", exclude={"payload_sha256"})
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def with_checksum(self) -> "EngineeringMissionCheckpoint":
        digest = hashlib.sha256(self.canonical_payload()).hexdigest()
        return self.model_copy(update={"payload_sha256": digest})

    def verify_checksum(self) -> None:
        expected = hashlib.sha256(self.canonical_payload()).hexdigest()
        if not self.payload_sha256 or self.payload_sha256 != expected:
            raise EngineeringCheckpointError(
                f"Engineering checkpoint checksum mismatch: expected {expected}, got {self.payload_sha256 or '<missing>'}"
            )


class WorkspaceFingerprinter:
    """Create a deterministic repository-content fingerprint.

    Generated/cache trees are excluded because they are not canonical project
    state. File content is streamed so large source artifacts do not need to be
    loaded into memory at once.
    """

    DEFAULT_EXCLUDED_DIRS = {
        ".git",
        ".brain",
        "node_modules",
        "dist",
        "build",
        "target",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
    }

    def __init__(self, excluded_dirs: set[str] | None = None) -> None:
        self.excluded_dirs = set(excluded_dirs or self.DEFAULT_EXCLUDED_DIRS)

    def fingerprint(self, root: Path) -> WorkspaceFingerprint:
        root = root.resolve()
        if not root.exists() or not root.is_dir():
            raise EngineeringCheckpointError(f"Workspace root does not exist: {root}")

        aggregate = hashlib.sha256()
        file_count = 0
        total_bytes = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if any(part in self.excluded_dirs for part in rel.parts):
                continue
            try:
                stat = path.stat()
                file_hash = hashlib.sha256()
                with path.open("rb") as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        file_hash.update(chunk)
            except OSError as exc:
                raise EngineeringCheckpointError(f"Could not fingerprint {path}: {exc}") from exc

            rel_text = rel.as_posix()
            digest = file_hash.hexdigest()
            aggregate.update(rel_text.encode("utf-8"))
            aggregate.update(b"\0")
            aggregate.update(str(stat.st_size).encode("ascii"))
            aggregate.update(b"\0")
            aggregate.update(digest.encode("ascii"))
            aggregate.update(b"\n")
            file_count += 1
            total_bytes += stat.st_size

        return WorkspaceFingerprint(
            digest=aggregate.hexdigest(),
            file_count=file_count,
            total_bytes=total_bytes,
        )


class EngineeringCheckpointStore:
    """Atomic local checkpoint store with SHA-256 self-verification."""

    TRANSIENT_STATUSES = {
        TaskNodeStatus.LEASE_ASSIGNED,
        TaskNodeStatus.COGNITIVE_WORK,
        TaskNodeStatus.TOOL_PROPOSED,
        TaskNodeStatus.PREFLIGHT,
        TaskNodeStatus.EXECUTING,
        TaskNodeStatus.VERIFYING,
    }

    def __init__(self, path: Path, *, fingerprinter: WorkspaceFingerprinter | None = None) -> None:
        self.path = path.resolve()
        self.fingerprinter = fingerprinter or WorkspaceFingerprinter()

    def save(
        self,
        *,
        dag: TaskDAG,
        workspace_root: Path,
        runs: list[EngineeringNodeRun] | None = None,
        requirement_worktrees: dict[str, dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EngineeringMissionCheckpoint:
        bindings = dict(requirement_worktrees or {})
        worktree_fingerprints = {}
        for requirement, raw in bindings.items():
            path_value = raw.get("path") if isinstance(raw, dict) else None
            if path_value:
                path = Path(path_value)
                if path.exists() and path.is_dir():
                    worktree_fingerprints[requirement] = self.fingerprinter.fingerprint(path)

        checkpoint = EngineeringMissionCheckpoint(
            dag=dag.model_copy(deep=True),
            workspace_fingerprint=self.fingerprinter.fingerprint(workspace_root),
            runs=list(runs or []),
            requirement_worktrees=bindings,
            worktree_fingerprints=worktree_fingerprints,
            metadata=dict(metadata or {}),
        ).with_checksum()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        payload = checkpoint.model_dump_json(indent=2)
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)
        return checkpoint

    def load(self) -> EngineeringMissionCheckpoint:
        try:
            checkpoint = EngineeringMissionCheckpoint.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise EngineeringCheckpointError(f"Could not load engineering checkpoint: {exc}") from exc
        checkpoint.verify_checksum()
        return checkpoint

    def recover(self, *, workspace_root: Path) -> tuple[TaskDAG, list[str], EngineeringMissionCheckpoint]:
        checkpoint = self.load()
        current = self.fingerprinter.fingerprint(workspace_root)
        if current.digest != checkpoint.workspace_fingerprint.digest:
            raise EngineeringCheckpointError(
                "Workspace drift detected since checkpoint; fail closed and re-index/replan before resume"
            )
        for requirement, expected in checkpoint.worktree_fingerprints.items():
            raw = checkpoint.requirement_worktrees.get(requirement, {})
            path_value = raw.get("path") if isinstance(raw, dict) else None
            if not path_value or not Path(path_value).exists():
                raise EngineeringCheckpointError(
                    f"Recovered requirement worktree is missing: {requirement}"
                )
            actual = self.fingerprinter.fingerprint(Path(path_value))
            if actual.digest != expected.digest:
                raise EngineeringCheckpointError(
                    f"Requirement worktree drift detected for {requirement}; fail closed"
                )

        dag = checkpoint.dag.model_copy(deep=True)
        reset_nodes: list[str] = []
        for node in dag.nodes.values():
            if node.status in self.TRANSIENT_STATUSES:
                node.status = TaskNodeStatus.REPLAN_REQUIRED
                node.version += 1
                reset_nodes.append(node.node_id)
        return dag, reset_nodes, checkpoint
