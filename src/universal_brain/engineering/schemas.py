from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from universal_brain.executive.schemas import TaskNodeStatus


class EngineeringWorkspace(BaseModel):
    """Canonical engineering workspace descriptor (REQ-ENG-006, ALN-012).

    The descriptor is model-neutral. It does not grant filesystem authority; all
    state-changing operations still require ToolGateway authorization.
    """

    workspace_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    repository_root: Path
    git_root: Path | None = None
    base_ref: str = "HEAD"
    worktree_root: Path | None = None
    language_ecosystems: list[str] = Field(default_factory=list)
    build_systems: list[str] = Field(default_factory=list)
    test_commands: list[list[str]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("repository_root")
    @classmethod
    def repository_root_must_be_absolute(cls, value: Path) -> Path:
        resolved = value.resolve()
        if not resolved.is_absolute():
            raise ValueError("repository_root must resolve to an absolute path")
        return resolved

    def normalized_worktree_root(self) -> Path:
        return (self.worktree_root or self.repository_root / ".brain" / "worktrees").resolve()


class EngineeringToolObservation(BaseModel):
    """Normalized observation returned from an authority-gated tool execution."""

    tool_name: str
    call_id: str | None = None
    success: bool
    output: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VerificationCommand(BaseModel):
    check_id: str
    executable: str
    arguments: list[str] = Field(default_factory=list)
    cwd: Path
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    required: bool = True


class VerificationCheckResult(BaseModel):
    check_id: str
    passed: bool
    evidence_ref: str | None = None
    exit_code: int | None = None
    stdout_digest: str | None = None
    stderr_digest: str | None = None
    reason: str = ""


class EngineeringNodeRun(BaseModel):
    node_id: str
    status_before: TaskNodeStatus
    status_after: TaskNodeStatus
    iterations: int = 0
    observations: list[EngineeringToolObservation] = Field(default_factory=list)
    verification_checks: list[VerificationCheckResult] = Field(default_factory=list)
    model_result_id: UUID | None = None
    replan_reason: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EngineeringDAGRun(BaseModel):
    dag_id: UUID
    runs: list[EngineeringNodeRun] = Field(default_factory=list)
    cycles: int = 0
    complete: bool = False
    blocked_nodes: list[str] = Field(default_factory=list)
