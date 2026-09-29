"""
Universal Brain - Base Tool Definition

Implements ADR-0002 (Action Authority), ALN-007 (Bounded scope & rollback),
and M5 Safety Invariants (Reversibility Classification).
All tools declare explicit permission classes (A0-A3), reversibility classifications,
preflight validation methods, and rollback mechanics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from universal_brain.kernel.events import ActionClass


class ReversibilityClass(str, Enum):
    """Classification of tool action reversibility (M5 Section 5)."""

    VERIFIED_REVERSIBLE = "VERIFIED_REVERSIBLE"
    REVERSIBLE_WITH_LIMITATIONS = "REVERSIBLE_WITH_LIMITATIONS"
    COMPENSATABLE = "COMPENSATABLE"
    IRREVERSIBLE = "IRREVERSIBLE"
    UNKNOWN = "UNKNOWN"


class ToolResult(BaseModel):
    """Deterministic output produced by a tool execution."""

    success: bool
    output: Any
    evidence: Dict[str, Any] = Field(default_factory=dict)
    rollback_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    reversibility_class: ReversibilityClass = Field(default=ReversibilityClass.UNKNOWN)
    checkpoint_id: Optional[str] = None
    pre_digest: Optional[str] = None
    post_digest: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)


class ReconciliationStatus(str, Enum):
    """Outcome of checking whether an interrupted external effect occurred."""

    CONFIRMED = "CONFIRMED"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


class ReconciliationResult(BaseModel):
    """Tool supplied observation used to resolve an uncertain execution."""

    status: ReconciliationStatus
    result: Optional[ToolResult] = None
    detail: str = ""


class BaseTool(ABC):
    """Abstract base class for all tools registered in the Tool Gateway."""

    name: str
    action_class: ActionClass
    description: str
    reversibility_class: ReversibilityClass = ReversibilityClass.UNKNOWN

    @abstractmethod
    def preflight_check(self, args: Dict[str, Any]) -> bool:
        """
        Validates preconditions and asserts reversibility before any mutation.
        Must return True for execution to proceed (ALN-007, ADR-0008).
        """
        pass

    @abstractmethod
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """Executes the tool action within bounded scope."""
        pass

    @abstractmethod
    def rollback(self, rollback_data: Dict[str, Any]) -> bool:
        """Reverses the effect of an A1 action using recorded rollback data."""
        pass

    def reconcile(self, args: Dict[str, Any], operation_id: str) -> ReconciliationResult:
        """Observe an uncertain prior execution without causing another effect.

        Tools that can prove the external outcome should override this method.
        The default is deliberately UNKNOWN so the gateway fails closed instead
        of replaying a state changing action after an ambiguous crash.
        """
        return ReconciliationResult(
            status=ReconciliationStatus.UNKNOWN,
            detail=f"tool {self.name!r} does not implement execution reconciliation",
        )
