"""
Universal Brain - Command Runner Schemas

Implements M5 Sections 23, 29, 31, 33, 84:
Defines structured command specifications, resource quotas, termination reasons,
isolation levels, and execution results.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from universal_brain.kernel.events import ActionClass


class IsolationLevel(str, Enum):
    """Runtime containment levels (M5 Section 84)."""

    L0_OBSERVE = "L0_OBSERVE"
    L1_WORKSPACE_CONFINED = "L1_WORKSPACE_CONFINED"
    L2_RESTRICTED_ENV = "L2_RESTRICTED_ENV"
    L3_ISOLATED_CONTAINER = "L3_ISOLATED_CONTAINER"


class TerminationReason(str, Enum):
    """Reason for process termination (M5 Section 31)."""

    COMPLETED = "COMPLETED"
    TIMEOUT = "TIMEOUT"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"
    CANCELLED = "CANCELLED"
    ABORTED_ON_ERROR = "ABORTED_ON_ERROR"


class NetworkPolicy(str, Enum):
    """Subprocess outbound network access policy (M5 Section 33)."""

    NETWORK_DENIED = "NETWORK_DENIED"
    LOCAL_ONLY = "LOCAL_ONLY"
    ALLOWLISTED = "ALLOWLISTED"
    UNRESTRICTED_WITH_AUTHORIZATION = "UNRESTRICTED_WITH_AUTHORIZATION"


class CommandSpec(BaseModel):
    """Structured request for subprocess execution (M5 Section 23)."""

    command_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    workspace_id: UUID
    executable: str = Field(..., description="Binary/executable name without shell expansion")
    arguments: List[str] = Field(default_factory=list, description="Explicit argv arguments")
    cwd: Path = Field(..., description="Working directory confined to workspace")
    timeout_seconds: int = Field(60, description="Wall-clock execution ceiling")
    output_limit_bytes: int = Field(500_000, description="Max total stdout/stderr bytes before truncation")
    environment_overrides: Dict[str, str] = Field(default_factory=dict)
    network_policy: NetworkPolicy = NetworkPolicy.LOCAL_ONLY
    action_class: ActionClass = ActionClass.A1
    expected_exit_codes: List[int] = Field(default_factory=lambda: [0])


class CommandResult(BaseModel):
    """Structured deterministic result of subprocess execution (M5 Section 31)."""

    command_id: UUID
    execution_id: UUID = Field(default_factory=uuid4)
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    exit_code: int
    termination_reason: TerminationReason
    stdout_preview: str
    stderr_preview: str
    stdout_digest: str
    stderr_digest: str
    truncated: bool = False
    isolation_level: IsolationLevel = IsolationLevel.L1_WORKSPACE_CONFINED
    evidence_refs: List[str] = Field(default_factory=list)
