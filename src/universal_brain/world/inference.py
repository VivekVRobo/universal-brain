"""
Universal Brain - World Inference Engine & Model-Derived Boundaries
Implements Sections 73-75 of Milestone M8 Specification (M8-INV-01, M8-INV-07).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

from universal_brain.world.schemas import (
    AssertionStateClass,
    WorldPropertyAssertion,
)


class InferenceRule(BaseModel):
    """Declarative inference rule schema (Section 74)."""

    rule_id: str
    rule_version: int = 1
    input_properties: List[str]
    output_property: str
    confidence_factor: float = 0.8
    description: str = ""


class InferenceEngine:
    """
    Evaluates rule-based inferences and marks model-generated assumptions as INFERRED.
    Strictly prohibits unverified inference from masquerading as verified fact (M8-INV-07).
    """

    def __init__(self) -> None:
        self._rules: Dict[str, InferenceRule] = {}
        self._evaluators: Dict[str, Callable[[Dict[str, Any]], Optional[Any]]] = {}

    def register_rule(
        self,
        rule: InferenceRule,
        evaluator: Callable[[Dict[str, Any]], Optional[Any]],
    ) -> None:
        self._rules[rule.rule_id] = rule
        self._evaluators[rule.rule_id] = evaluator

    def evaluate_inferences(
        self,
        entity_id: str,
        current_properties: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Executes registered inference rules against current properties.
        Outputs candidate INFERRED property values.
        """
        inferred_results = []
        for rule_id, rule in self._rules.items():
            # Check if all required inputs are present
            if all(prop in current_properties for prop in rule.input_properties):
                evaluator = self._evaluators[rule_id]
                val = evaluator(current_properties)
                if val is not None:
                    inferred_results.append({
                        "entity_id": entity_id,
                        "property_key": rule.output_property,
                        "value": val,
                        "state_class": AssertionStateClass.INFERRED,
                        "confidence": rule.confidence_factor,
                        "inference_rule_version": rule.rule_version,
                    })
        return inferred_results
