"""
Universal Brain - Policy-Based Model Router

Implements Sections 26–29 of the God-Level Specification:
- Hard eligibility checks before ranking;
- Budget-aware auto-downgrade integration with BudgetGatekeeper;
- Multi-dimensional policy scoring (Capability, Cost, Context, Health);
- Operational routing explanations (Invariant: Observable intelligence decisions).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from universal_brain.executive.budget import BudgetGatekeeper, BudgetTier
from universal_brain.executive.providers.base import BaseModelProvider
from universal_brain.executive.providers.registry import ModelProviderRegistry
from universal_brain.kernel.errors import CapabilityDeniedError


class RoutingDecision:
    """Explains why a specific model was selected and why others were rejected."""

    def __init__(
        self,
        selected_provider: BaseModelProvider,
        rationale: str,
        rejected_candidates: List[Tuple[str, str]],
    ) -> None:
        self.selected_provider = selected_provider
        self.rationale = rationale
        self.rejected_candidates = rejected_candidates  # List of (provider_id, reason)


class ModelRouter:
    """Selects eligible model providers based on capabilities, budget, and health."""

    def __init__(
        self,
        registry: ModelProviderRegistry,
        budget_gatekeeper: BudgetGatekeeper,
    ) -> None:
        self.registry = registry
        self.budget_gatekeeper = budget_gatekeeper

    def select_model(
        self,
        required_context_tokens: int = 4000,
        task_complexity: str = "standard",  # standard | complex_planning | quick_exec
        allow_local_only: bool = False,
    ) -> RoutingDecision:
        """
        Evaluates registered providers against hard eligibility gates
        and budget-tier constraints.
        """
        all_providers = list(self.registry._providers.values())
        if not all_providers:
            raise CapabilityDeniedError("No model providers registered in Universal Brain.")

        tier = self.budget_gatekeeper.get_tier()
        eligible: List[BaseModelProvider] = []
        rejected: List[Tuple[str, str]] = []

        for p in all_providers:
            p_id = p.metadata.provider_id

            # 1. Circuit Breaker Check
            if not self.registry._circuit_breakers[p_id].is_available:
                rejected.append((p_id, f"Circuit breaker is {p.metadata.health_status}."))
                continue

            # 2. Context Window Check
            if p.metadata.context_window < required_context_tokens:
                rejected.append((p_id, f"Context window ({p.metadata.context_window}) too small for {required_context_tokens}."))
                continue

            # 3. Budget Tier Check
            if tier == BudgetTier.EXHAUSTED and p.metadata.cost_per_million_input > 0:
                rejected.append((p_id, "Budget exhausted (Tier 3). Paid API models prohibited."))
                continue

            if tier == BudgetTier.DOWNGRADE and p.metadata.cost_per_million_input > 5.00:
                rejected.append((p_id, "Budget conserve mode (Tier 2). High-cost frontier models prohibited."))
                continue

            if allow_local_only and "local" not in p.metadata.provider_id.lower():
                rejected.append((p_id, "Policy requires local execution only."))
                continue

            eligible.append(p)

        if not eligible:
            raise CapabilityDeniedError(
                f"No eligible models available. Tier: {tier.value}. Rejected: {rejected}"
            )

        # 4. Multi-dimensional ranking
        # Score higher for capability fit, lower for cost in caution tiers
        def score_provider(provider: BaseModelProvider) -> float:
            score = 100.0
            # Frontier reasoning preference for complex planning
            if task_complexity == "complex_planning" and "claude" in provider.metadata.model_family.lower():
                score += 30.0
            # Prefer lower cost when under budget caution
            if tier in [BudgetTier.SOFT_WARNING, BudgetTier.DOWNGRADE]:
                score -= provider.metadata.cost_per_million_input * 2.0
            return score

        eligible.sort(key=score_provider, reverse=True)
        winner = eligible[0]

        rationale = (
            f"Selected '{winner.metadata.model_id}' under {tier.value}. "
            f"Context: {winner.metadata.context_window} tokens. "
            f"Cost: ${winner.metadata.cost_per_million_input:.2f}/M in. "
            f"Health: {winner.metadata.health_status}."
        )

        return RoutingDecision(
            selected_provider=winner,
            rationale=rationale,
            rejected_candidates=rejected,
        )
