"""
Universal Brain - Intent Parser & Contract Proposal Layer

Implements Sections 37–39 of the God-Level Specification:
- Structured comprehension separating intent understanding from execution;
- Deterministic ambiguity classification (ALN-004a);
- Assumption tracking ledger;
- Contract proposals validated by AlignmentEngine before task scheduling.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from universal_brain.alignment.contract import (
    AcceptanceCriterion,
    ActionClass,
    AlignmentContract,
    Ambiguity,
    OriginalInput,
    PermissionsCeiling,
    Requirement,
    RequirementKind,
    RequirementPriority,
)
from universal_brain.alignment.engine import AlignmentEngine, AmbiguityClassifier
from universal_brain.executive.schemas import ContractProposal, IntentRecord
from universal_brain.kernel.errors import AmbiguityBlockedError


class IntentParser:
    """Parses raw operator prompts into structured, governed IntentRecords and Contract proposals."""

    def __init__(self, alignment_engine: Optional[AlignmentEngine] = None) -> None:
        self.alignment_engine = alignment_engine or AlignmentEngine()
        self.ambiguity_classifier = AmbiguityClassifier()

    def parse_intent(
        self,
        raw_prompt: str,
        project_id: Optional[UUID] = None,
        operator_id: str = "operator",
        source_event_id: Optional[UUID] = None,
    ) -> IntentRecord:
        """Extracts goals, functional requirements, constraints, and ambiguities."""
        # 1. Primary Goal
        lines = [l.strip() for l in raw_prompt.split("\n") if l.strip()]
        primary_goal = lines[0] if lines else "Autonomous Task"

        # 2. Extract Functional Requirements
        requirements = []
        if len(lines) > 1:
            for l in lines[1:]:
                if l.startswith(("-", "*", "•", "1.", "2.", "3.")):
                    cleaned = re.sub(r"^[-*•\d\.]+\s*", "", l)
                    requirements.append(cleaned)
        if not requirements:
            requirements.append(f"Implement and verify: {primary_goal}")

        # 3. Detect Ambiguities & Impact
        detected_ambiguities: List[Dict[str, Any]] = []
        ambiguity_matches = [
            "maybe", "perhaps", "should be fast", "scalable", "user friendly",
            "secure", "as soon as possible", "etc", "and so on",
        ]
        for term in ambiguity_matches:
            if re.search(r"\b" + re.escape(term) + r"\b", raw_prompt, re.IGNORECASE):
                impact = self.ambiguity_classifier.classify(raw_prompt)
                detected_ambiguities.append({
                    "term": term,
                    "impact": impact.value,
                    "description": f"Vague or underspecified term '{term}' detected.",
                })

        # 4. Check for A2 Consequential Indicators
        explicit_constraints = []
        candidate_constraints = []
        if any(w in raw_prompt.lower() for w in ["actuator", "motor", "can bus", "hardware", "deploy", "physical"]):
            explicit_constraints.append("Direct physical actuator activation requires A2 operator approval (ALN-018).")

        return IntentRecord(
            source_event_id=source_event_id,
            operator_id=operator_id,
            project_id=project_id,
            primary_goal=primary_goal,
            functional_requirements=requirements,
            non_goals=["Unbounded internet crawling", "Bypassing preflight rollback verification"],
            explicit_constraints=explicit_constraints,
            candidate_constraints=candidate_constraints,
            ambiguities=detected_ambiguities,
            assumptions=[{"statement": "Targeting standard Linux/ROS 2 workspace", "impact": "low"}],
            requested_outcomes=["Clean build", "Passing unit tests", "Deterministic evidence artifact"],
        )

    def propose_contract(
        self,
        intent: IntentRecord,
        action_ceiling: ActionClass = ActionClass.A1,
    ) -> AlignmentContract:
        """
        Builds and validates an AlignmentContract draft from the IntentRecord.
        Blocks activation if high-impact ambiguities remain unresolved (ALN-004a).
        """
        # 1. Original Input provenance (ALN-001)
        original_input = OriginalInput(exact_content_ref=intent.primary_goal)

        # 2. Build Requirements
        req_models: List[Requirement] = []
        for idx, req_str in enumerate(intent.functional_requirements, start=1):
            req_models.append(
                Requirement(
                    requirement_id=f"REQ-{idx:03d}",
                    statement=req_str,
                    source_input_ids=[original_input.input_id],
                    kind=RequirementKind.FUNCTIONAL,
                    priority=RequirementPriority.MUST,
                    verification_method="colcon test / deterministic test suite",
                )
            )

        # 3. Acceptance Criteria (ALN-010)
        acceptance_criteria = [
            AcceptanceCriterion(
                criterion_id="AC-001",
                statement="Compiles cleanly and passes all automated unit tests",
                evidence_type="build_log",
                verifier="deterministic",
            )
        ]

        # 4. Permissions Ceiling
        ceiling = action_ceiling
        if intent.explicit_constraints and any("A2" in c for c in intent.explicit_constraints):
            ceiling = ActionClass.A2

        permissions = PermissionsCeiling(
            action_ceiling=ceiling,
            allowed_capabilities=["read", "write", "patch", "test"],
        )

        # 5. Create Draft
        draft = AlignmentContract.create_draft(
            objective=intent.primary_goal,
            requirements=req_models,
            permissions=permissions,
            acceptance_criteria=acceptance_criteria,
            original_inputs=[original_input],
        )

        # 6. Check High-Impact Ambiguity Gate (ALN-004a)
        for amb in intent.ambiguities:
            if str(amb["impact"]).upper() == "HIGH":
                raise AmbiguityBlockedError(
                    f"High-impact ambiguity '{amb['term']}' blocks contract activation. "
                    f"Operator clarification required."
                )

        # Activate contract
        active_contract = draft.activate()
        return active_contract
