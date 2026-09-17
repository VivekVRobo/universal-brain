"""
Universal Brain - Alignment Contract Engine

Implements:
- ALN-004a: Deterministic Ambiguity Classification Taxonomy.
- ALN-005: Operator corrections preserve history and invalidate affected descendants.
- ALN-006: Contract-diff gate preventing silent weakening of explicit constraints.
"""

from __future__ import annotations

import re
from typing import List, Optional, Set
from uuid import UUID

from universal_brain.alignment.contract import (
    AlignmentContract,
    Ambiguity,
    AmbiguityImpact,
    ChangeLogEntry,
    Constraint,
    ContractStatus,
)
from universal_brain.kernel.errors import (
    AmbiguityBlockedError,
    ConstraintWeakenedError,
    DescendantInvalidationError,
)


class AmbiguityClassifier:
    """
    Deterministic rule engine implementing ALN-004a.
    Classifies ambiguity impact purely via deterministic pattern matching (No LLM).
    """

    # High impact triggers: external filesystem, permissions, billing, production DB, A2 tokens
    HIGH_PATTERNS = [
        r"\b(rm\s+-rf|chmod|chown|delete|drop\s+table|alter\s+table)\b",
        r"\b(production|prod_db|database|billing|credit_card|payment|spend|api_key)\b",
        r"\b(actuator|motor|servo|gpio|robot_arm|hardware_bus|can_bus)\b",
        r"\b(external_network|open_port|public_ip|ssh|root_access)\b",
        r"\b(outside\s+sandbox|filesystem\s+root)\b",
    ]

    # Medium impact triggers: library choice, architecture pattern, framework
    MEDIUM_PATTERNS = [
        r"\b(library|framework|dependency|algorithm|architecture|protocol|version|distro|ros2)\b",
        r"\b(database_driver|async_engine|cache_strategy|schema_design)\b",
    ]

    # Low impact triggers: purely stylistic, naming, whitespace, comment formatting
    LOW_PATTERNS = [
        r"\b(variable_name|whitespace|formatting|comment|docstring_wording|log_format|lint_rule)\b",
        r"\b(naming\s+convention|variables?|camelcase|snake_case|indentation|styling)\b",
    ]

    @classmethod
    def classify(cls, question: str, target_resource: Optional[str] = None) -> AmbiguityImpact:
        """Deterministically assigns HIGH, MEDIUM, or LOW impact."""
        combined_text = f"{question} {target_resource or ''}".lower()

        # Check High Impact first
        for pattern in cls.HIGH_PATTERNS:
            if re.search(pattern, combined_text):
                return AmbiguityImpact.HIGH

        # Check explicit Low Impact
        for pattern in cls.LOW_PATTERNS:
            if re.search(pattern, combined_text):
                return AmbiguityImpact.LOW

        # Check Medium Impact
        for pattern in cls.MEDIUM_PATTERNS:
            if re.search(pattern, combined_text):
                return AmbiguityImpact.MEDIUM

        # Default strictly to MEDIUM (ALN-004a / ALN-006: unrecognized ambiguity must seek clarification or conservative handling)
        return AmbiguityImpact.MEDIUM


class AlignmentEngine:
    """Manages contract lifecycle transitions, constraint preservation, and amendments."""

    @staticmethod
    def validate_constraint_preservation(
        prior_contract: AlignmentContract,
        new_contract: AlignmentContract,
        is_operator_authorized: bool = False,
    ) -> None:
        """
        Enforces ALN-006: Explicit constraints cannot be silently weakened or removed.
        Any removal or weakening of an existing constraint requires explicit operator approval.
        """
        if is_operator_authorized:
            return  # Operator has authority to amend constraints

        prior_constraints_by_id = {c.constraint_id: c for c in prior_contract.constraints}
        new_constraints_by_id = {c.constraint_id: c for c in new_contract.constraints}

        # Check for dropped constraints
        dropped = set(prior_constraints_by_id.keys()) - set(new_constraints_by_id.keys())
        if dropped:
            raise ConstraintWeakenedError(
                f"Cannot weaken constraints: constraint(s) {dropped} were removed without operator authorization."
            )

        # Check for modified statements
        for c_id, prior_c in prior_constraints_by_id.items():
            new_c = new_constraints_by_id[c_id]
            if prior_c.statement != new_c.statement:
                raise ConstraintWeakenedError(
                    f"Constraint '{c_id}' statement was modified without explicit operator authorization."
                )

    @staticmethod
    def amend_contract(
        current_contract: AlignmentContract,
        reason: str,
        authority_event_id: UUID,
        updated_requirements: Optional[list] = None,
        updated_constraints: Optional[List[Constraint]] = None,
        updated_ambiguities: Optional[List[Ambiguity]] = None,
        semantic_diff_ref: Optional[str] = None,
        is_operator_authorized: bool = True,
    ) -> AlignmentContract:
        """
        Creates a new version of the contract, preserving history and enforcing ALN-005 & ALN-006.
        """
        new_version = current_contract.version + 1

        new_contract_data = current_contract.model_dump()
        new_contract_data["version"] = new_version
        new_contract_data["status"] = ContractStatus.DRAFT  # Amendments start in draft

        if updated_requirements is not None:
            new_contract_data["requirements"] = updated_requirements
        if updated_constraints is not None:
            new_contract_data["constraints"] = updated_constraints
        if updated_ambiguities is not None:
            new_contract_data["ambiguities"] = updated_ambiguities

        # Record ChangeLog entry (ALN-005)
        log_entry = ChangeLogEntry(
            version=new_version,
            reason=reason,
            authority_event_id=authority_event_id,
            semantic_diff_ref=semantic_diff_ref,
        )
        new_contract_data["change_log"].append(log_entry.model_dump())

        new_contract = AlignmentContract.model_validate(new_contract_data)

        # Enforce ALN-006: constraint diff gate
        AlignmentEngine.validate_constraint_preservation(
            prior_contract=current_contract,
            new_contract=new_contract,
            is_operator_authorized=is_operator_authorized,
        )

        return new_contract

    @staticmethod
    def identify_invalidated_descendants(
        prior_contract: AlignmentContract,
        amended_contract: AlignmentContract,
    ) -> Set[str]:
        """
        Enforces ALN-005: Traverses requirement diffs to identify which downstream
        tasks or requirements are invalidated by an amendment.
        """
        prior_reqs = {r.requirement_id: r.statement for r in prior_contract.requirements}
        new_reqs = {r.requirement_id: r.statement for r in amended_contract.requirements}

        invalidated_ids: Set[str] = set()

        # Dropped requirements
        for r_id in prior_reqs:
            if r_id not in new_reqs:
                invalidated_ids.add(r_id)

        # Changed statements
        for r_id, stmt in new_reqs.items():
            if r_id in prior_reqs and prior_reqs[r_id] != stmt:
                invalidated_ids.add(r_id)

        return invalidated_ids
