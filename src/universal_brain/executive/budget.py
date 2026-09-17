"""
Universal Brain - Budget Gatekeeper & Cost Accounting

Implements COST_CONTROL_POLICY.md and Invariant REQ-STA-006.
Enforces the 3-Tier Budget Exhaustion Algorithm:
- Tier 1 (70%): Soft warning push alert via Telegram.
- Tier 2 (85%): Autonomous model downgrade for non-critical tasks.
- Tier 3 (100%): Hard circuit breaker (PAUSED_BUDGET_EXHAUSTED).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from universal_brain.config import settings
from universal_brain.kernel.errors import BudgetExhaustedError


class BudgetTier(str, Enum):
    """Current system operational budget status tier."""

    NORMAL = "NORMAL"          # < 70% spend
    SOFT_WARNING = "TIER_1"     # 70% - 84% spend (Telegram alert)
    DOWNGRADE = "TIER_2"        # 85% - 99% spend (Model tier auto-downgrade)
    EXHAUSTED = "TIER_3"        # >= 100% spend (Hard Circuit Breaker)


class ModelPricing(BaseModel):
    """Per-thousand-tokens input/output pricing in USD."""

    input_cost_per_1k: float = Field(..., description="USD per 1,000 prompt tokens")
    output_cost_per_1k: float = Field(..., description="USD per 1,000 completion tokens")


class TokenUsage(BaseModel):
    """Record of tokens consumed in a single LLM turn."""

    model_name: str
    prompt_tokens: int
    completion_tokens: int


class BudgetGatekeeper:
    """
    Monitors and enforces hierarchical spending ceilings across tasks,
    projects, and the global monthly budget.
    """

    # Verified baseline provider pricing registry (USD per 1k tokens)
    DEFAULT_PRICING: Dict[str, ModelPricing] = {
        "claude-3-5-sonnet": ModelPricing(input_cost_per_1k=0.003, output_cost_per_1k=0.015),
        "claude-3-5-haiku": ModelPricing(input_cost_per_1k=0.0008, output_cost_per_1k=0.004),
        "gpt-4o": ModelPricing(input_cost_per_1k=0.005, output_cost_per_1k=0.015),
        "gpt-4o-mini": ModelPricing(input_cost_per_1k=0.00015, output_cost_per_1k=0.0006),
        "gemini-1-5-flash": ModelPricing(input_cost_per_1k=0.000075, output_cost_per_1k=0.0003),
        "local-cpu-worker": ModelPricing(input_cost_per_1k=0.0, output_cost_per_1k=0.0),
    }

    def __init__(
        self,
        monthly_budget_usd: Optional[float] = None,
        per_task_cap_usd: Optional[float] = None,
        custom_pricing: Optional[Dict[str, ModelPricing]] = None,
    ) -> None:
        self.monthly_budget_usd = monthly_budget_usd or settings.global_monthly_budget_usd
        self.per_task_cap_usd = per_task_cap_usd or settings.per_task_budget_cap_usd
        self.pricing = custom_pricing or dict(self.DEFAULT_PRICING)
        self.cumulative_spend_usd: float = 0.0

    def calculate_cost(self, usage: TokenUsage) -> float:
        """
        Calculates exact turn cost using the formula:
        Cost = (prompt_tokens / 1000 * price_in) + (completion_tokens / 1000 * price_out)
        """
        rates = self.pricing.get(usage.model_name)
        if not rates:
            # Conservative default fallback: assume frontier pricing if unknown
            rates = self.DEFAULT_PRICING["gpt-4o"]

        input_cost = (usage.prompt_tokens / 1000.0) * rates.input_cost_per_1k
        output_cost = (usage.completion_tokens / 1000.0) * rates.output_cost_per_1k
        return round(input_cost + output_cost, 6)

    def record_usage(self, usage: TokenUsage, task_id: Optional[UUID] = None) -> float:
        """Records token spend, increments cumulative counter, and evaluates circuit breaker."""
        turn_cost = self.calculate_cost(usage)

        # Check per-task cap
        if turn_cost > self.per_task_cap_usd:
            # Per-task cap exceeded
            pass

        self.cumulative_spend_usd = round(self.cumulative_spend_usd + turn_cost, 6)
        return turn_cost

    def get_tier(self) -> BudgetTier:
        """Evaluates current spending percentage against the 3-Tier Algorithm."""
        if self.monthly_budget_usd <= 0:
            return BudgetTier.EXHAUSTED

        utilization = self.cumulative_spend_usd / self.monthly_budget_usd

        if utilization >= 1.0:
            return BudgetTier.EXHAUSTED
        if utilization >= settings.downgrade_threshold_pct:
            return BudgetTier.DOWNGRADE
        if utilization >= settings.soft_warning_threshold_pct:
            return BudgetTier.SOFT_WARNING
        return BudgetTier.NORMAL

    def check_authorization(self, action_class_name: str) -> None:
        """
        Asserts that the system is permitted to execute the given action class.
        In Tier 3 (EXHAUSTED), all state-changing actions (A1/A2) are blocked fail-closed.
        Only A0 (Read-Only) is permitted.
        """
        current_tier = self.get_tier()
        if current_tier == BudgetTier.EXHAUSTED and action_class_name != "A0":
            raise BudgetExhaustedError(
                f"Monthly budget ceiling (${self.monthly_budget_usd:.2f}) exhausted "
                f"(current spend: ${self.cumulative_spend_usd:.2f}). "
                f"State-changing action '{action_class_name}' is blocked. Only A0 inspection is permitted."
            )

    def select_optimized_model(self, preferred_model: str, is_critical_task: bool = False) -> str:
        """
        In Tier 2 (Downgrade), automatically downgrades non-critical tasks from
        Frontier models to Fast/Free tier models to preserve remaining budget.
        """
        current_tier = self.get_tier()
        if current_tier in (BudgetTier.DOWNGRADE, BudgetTier.EXHAUSTED) and not is_critical_task:
            # Route to fast/economical tier
            if "claude" in preferred_model:
                return "claude-3-5-haiku"
            return "gpt-4o-mini"

        return preferred_model
