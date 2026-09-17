"""
Universal Brain - Alignment Contract

Defines the canonical Alignment Contract schema, including requirements,
constraints, assumptions, ambiguities, acceptance criteria, and permissions.

Implements ALN-001 (task cites requirement), ALN-004 (high-impact ambiguity
blocks execution), ALN-004a (deterministic taxonomy), and ALN-010 (completion
requires evidence).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from universal_brain.kernel.events import ActionClass


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class ContractStatus(str, Enum):
    """Lifecycle status of an Alignment Contract."""

    DRAFT = "draft"
    CLARIFICATION_REQUIRED = "clarification_required"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CLOSED = "closed"


class AmbiguityImpact(str, Enum):
    """Impact classification for ambiguities (ALN-004a deterministic taxonomy)."""

    LOW = "low"          # Record reversible assumption
    MEDIUM = "medium"    # Prefer clarification
    HIGH = "high"        # Block affected execution branch


class RequirementPriority(str, Enum):
    """Priority level for requirements."""

    MUST = "must"
    SHOULD = "should"
    MAY = "may"


class RequirementKind(str, Enum):
    """Classification of requirement type."""

    FUNCTIONAL = "functional"
    QUALITY = "quality"
    SAFETY = "safety"
    PRIVACY = "privacy"
    PERMISSION = "permission"
    EVIDENCE = "evidence"


# -----------------------------------------------------------------------------
# Pydantic Models
# -----------------------------------------------------------------------------


class OriginalInput(BaseModel):
    """Immutable record of raw user input."""

    model_config = {"frozen": True, "extra": "forbid"}

    input_id: UUID = Field(default_factory=uuid4, description="Unique input identifier")
    exact_content_ref: str = Field(
        ...,
        description="Immutable reference to the exact content (e.g., URI, hash, or verbatim string)",
        min_length=1,
    )
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when input was received",
    )


class Requirement(BaseModel):
    """A single requirement derived from user input(s)."""

    model_config = {"frozen": True, "extra": "forbid"}

    requirement_id: str = Field(
        ..., description="Unique requirement identifier (e.g., 'REQ-001')", min_length=1
    )
    statement: str = Field(..., description="Clear, testable statement", min_length=1)
    source_input_ids: List[UUID] = Field(
        default_factory=list, description="Original inputs that inspired this requirement"
    )
    kind: RequirementKind = Field(..., description="Requirement classification")
    priority: RequirementPriority = Field(..., description="Priority level")
    verification_method: str = Field(
        ..., description="How this requirement will be verified (test, review, measurement)", min_length=1
    )

    @field_validator("source_input_ids")
    @classmethod
    def at_least_one_source(cls, v: List[UUID]) -> List[UUID]:
        """Each requirement must trace to at least one original input (ALN-001)."""
        if not v:
            raise ValueError("Requirement must have at least one source_input_id")
        return v


class Constraint(BaseModel):
    """An explicit constraint that cannot be silently weakened."""

    model_config = {"frozen": True, "extra": "forbid"}

    constraint_id: str = Field(
        ..., description="Unique constraint identifier", min_length=1
    )
    statement: str = Field(..., description="Constraint statement", min_length=1)
    authority: str = Field(
        ...,
        description="Source of authority: explicit_user, constitution, policy, derived",
        min_length=1,
    )


class Assumption(BaseModel):
    """An assumption made during interpretation, with impact classification."""

    model_config = {"frozen": True, "extra": "forbid"}

    assumption_id: str = Field(
        ..., description="Unique assumption identifier", min_length=1
    )
    statement: str = Field(..., description="Assumption statement", min_length=1)
    impact: AmbiguityImpact = Field(..., description="Assessed impact")
    confirmed: bool = Field(
        False, description="Has this assumption been verified by the operator?"
    )
    rollback_path: str = Field(
        ...,
        description="If assumption is wrong, how to revert or compensate",
        min_length=1,
    )


class Ambiguity(BaseModel):
    """An unresolved ambiguity, classified per ALN-004a."""

    model_config = {"frozen": True, "extra": "forbid"}

    ambiguity_id: str = Field(
        ..., description="Unique ambiguity identifier", min_length=1
    )
    question: str = Field(..., description="The ambiguous question", min_length=1)
    impact: AmbiguityImpact = Field(..., description="Impact classification")
    affected_refs: List[str] = Field(
        default_factory=list,
        description="IDs of affected requirements, tasks, or contracts",
    )
    resolution_status: str = Field(
        "open",
        description="open | assumed | answered | blocked",
        pattern=r"^(open|assumed|answered|blocked)$",
    )


class AcceptanceCriterion(BaseModel):
    """A criterion that must be satisfied for completion."""

    model_config = {"frozen": True, "extra": "forbid"}

    criterion_id: str = Field(
        ..., description="Unique acceptance criterion identifier", min_length=1
    )
    statement: str = Field(..., description="Clear, testable statement", min_length=1)
    evidence_type: str = Field(
        ..., description="Type of evidence required (test_output, measurement, review)", min_length=1
    )
    verifier: str = Field(
        ..., description="Who verifies: deterministic, independent_model, operator, mixed", min_length=1
    )


class PermissionsCeiling(BaseModel):
    """Declared permission bounds for the contract."""

    model_config = {"frozen": True, "extra": "forbid"}

    action_ceiling: ActionClass = Field(..., description="Maximum action class allowed")
    allowed_capabilities: List[str] = Field(
        default_factory=list, description="Explicitly allowed capabilities"
    )
    denied_capabilities: List[str] = Field(
        default_factory=list, description="Explicitly denied capabilities"
    )
    expires_at: Optional[datetime] = Field(
        None, description="Optional expiration timestamp for permissions"
    )


class ChangeLogEntry(BaseModel):
    """Record of a contract version change."""

    model_config = {"frozen": True, "extra": "forbid"}

    version: int = Field(..., description="New version number", ge=1)
    reason: str = Field(..., description="Why the change was made", min_length=1)
    authority_event_id: UUID = Field(..., description="Event that authorized the change")
    semantic_diff_ref: Optional[str] = Field(
        None, description="Reference to a diff or explanation"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of change",
    )


class AlignmentContract(BaseModel):
    """
    The canonical Alignment Contract bridging user intent to executable tasks.

    Satisfies ALN-001 through ALN-006, ALN-010, ALN-020.
    """

    model_config = {"extra": "forbid", "validate_default": True}

    contract_id: UUID = Field(default_factory=uuid4, description="Unique contract identifier")
    version: int = Field(1, description="Contract version number", ge=1)
    status: ContractStatus = Field(
        ContractStatus.DRAFT, description="Current lifecycle status"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of creation",
    )

    original_inputs: List[OriginalInput] = Field(
        ..., description="All raw inputs that informed this contract"
    )
    objective: str = Field(..., description="High-level goal statement", min_length=1)
    rationale: List[str] = Field(default_factory=list, description="Justification for objective")
    priority: int = Field(0, description="Relative priority of this contract", ge=0)

    requirements: List[Requirement] = Field(
        ..., description="Functional and non-functional requirements"
    )
    constraints: List[Constraint] = Field(
        default_factory=list, description="Explicit constraints"
    )
    non_goals: List[str] = Field(default_factory=list, description="Things explicitly not in scope")
    assumptions: List[Assumption] = Field(default_factory=list, description="Made assumptions")
    ambiguities: List[Ambiguity] = Field(default_factory=list, description="Open ambiguities")
    permissions: PermissionsCeiling = Field(..., description="Permission bounds")
    acceptance_criteria: List[AcceptanceCriterion] = Field(
        ..., description="Criteria for success"
    )
    commitments: List[str] = Field(default_factory=list, description="Explicit commitments")
    change_log: List[ChangeLogEntry] = Field(
        default_factory=list, description="Version history"
    )

    @model_validator(mode="after")
    def validate_transitions(self) -> "AlignmentContract":
        """
        Enforce transition rules:
        1. If status == "active":
           - No open high-impact ambiguity (ALN-004, ALN-004a)
           - At least one acceptance criterion (ALN-010)
        """
        if self.status == ContractStatus.ACTIVE:
            # Rule 1: No high-impact open ambiguities
            high_open = [
                a for a in self.ambiguities
                if a.impact == AmbiguityImpact.HIGH and a.resolution_status == "open"
            ]
            if high_open:
                ids = ", ".join(a.ambiguity_id for a in high_open)
                raise ValueError(
                    f"Cannot activate contract: open high-impact ambiguity(ies): {ids}"
                )

            # Rule 2: At least one acceptance criterion
            if not self.acceptance_criteria:
                raise ValueError("Active contract must have at least one acceptance criterion")

        return self

    def activate(self) -> "AlignmentContract":
        """
        Transition contract to ACTIVE status with full invariant revalidation.
        Enforces ALN-004 (no open high-impact ambiguity) and ALN-010 (acceptance criteria).
        """
        data = self.model_dump()
        data["status"] = ContractStatus.ACTIVE
        return self.__class__.model_validate(data)

    @classmethod
    def create_draft(
        cls,
        objective: str,
        requirements: List[Requirement],
        permissions: PermissionsCeiling,
        acceptance_criteria: List[AcceptanceCriterion],
        original_inputs: Optional[List[OriginalInput]] = None,
        constraints: Optional[List[Constraint]] = None,
        non_goals: Optional[List[str]] = None,
        assumptions: Optional[List[Assumption]] = None,
        ambiguities: Optional[List[Ambiguity]] = None,
        commitments: Optional[List[str]] = None,
        rationale: Optional[List[str]] = None,
        priority: int = 0,
    ) -> "AlignmentContract":
        """Factory method to create a new draft contract with minimal required fields."""
        return cls(
            version=1,
            status=ContractStatus.DRAFT,
            original_inputs=original_inputs or [],
            objective=objective,
            rationale=rationale or [],
            priority=priority,
            requirements=requirements,
            constraints=constraints or [],
            non_goals=non_goals or [],
            assumptions=assumptions or [],
            ambiguities=ambiguities or [],
            permissions=permissions,
            acceptance_criteria=acceptance_criteria,
            commitments=commitments or [],
            change_log=[],
        )
