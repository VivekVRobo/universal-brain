from __future__ import annotations

from universal_brain.executive.budget import BudgetGatekeeper, BudgetTier
from universal_brain.kernel.errors import CapabilityDeniedError

from .catalog import ModelCatalog
from .evaluations import PerformanceLedger
from .health import RouteHealthRegistry
from .quota import RouteQuotaRegistry
from .schemas import (
    CandidateScore,
    FabricRoutingDecision,
    ModelCapability,
    RejectedCandidate,
    RetentionPolicy,
    RouteHealth,
    SensitivityLevel,
    TaskComplexity,
    TransportKind,
)
from .telemetry import RouteTelemetryRegistry


class IntelligenceRouter:
    def __init__(
        self,
        catalog: ModelCatalog,
        budget_gatekeeper: BudgetGatekeeper,
        health_registry=None,
        performance_ledger=None,
        quota_registry=None,
        telemetry_registry=None,
        capability_registry=None,
        route_policies=None,
    ):
        self.catalog = catalog
        self.budget_gatekeeper = budget_gatekeeper
        self.health_registry = health_registry or RouteHealthRegistry()
        self.performance_ledger = performance_ledger or PerformanceLedger()
        self.quota_registry = quota_registry or RouteQuotaRegistry()
        self.telemetry_registry = telemetry_registry or RouteTelemetryRegistry()
        self.capability_registry = capability_registry
        self.route_policies = list(route_policies or [])


    def _capability_snapshot(self, model, route, capability):
        declared = model.capability_profile.get(capability)
        if self.capability_registry is None:
            return declared, None
        snapshot = self.capability_registry.snapshot(
            model_key=model.model_key,
            capability=capability,
            declared_score=declared,
            route_id=route.route_id,
        )
        return snapshot.effective_score, snapshot

    def _eligibility_reason(self, model, route, task, budget_tier):
        if not model.enabled:
            return "Model is disabled."
        if not route.enabled:
            return "Route is disabled."
        health = self.health_registry.get_state(route.route_id)
        if health in {RouteHealth.OPEN, RouteHealth.DISABLED, RouteHealth.AUTH_REQUIRED}:
            return f"Route health is {health.value}."
        quota_reason = self.quota_registry.eligibility_reason(
            route.route_id, task.required_context_tokens, task.estimated_output_tokens
        )
        if quota_reason:
            return quota_reason
        if task.local_only and route.transport != TransportKind.LOCAL:
            return "Task requires local-only execution."
        if task.allowed_transports is not None and route.transport not in task.allowed_transports:
            return "Transport not allowed."
        if not route.allows_sensitivity(task.sensitivity):
            return f"Route permits at most {route.max_sensitivity.value}."
        if task.sensitivity == SensitivityLevel.SECRET and route.transport != TransportKind.LOCAL:
            return "ALN-013: secret context cannot leave local runtime."
        context_limit = route.context_window_override or model.context_window
        if context_limit < task.required_context_tokens:
            return "Context window too small."
        if task.require_structured_output and not route.supports_structured_outputs:
            return "Structured output unsupported."
        if task.require_tools and not route.supports_tools:
            return "Tools unsupported."
        if task.require_vision and not route.supports_vision:
            return "Vision unsupported."
        for capability in task.required_capabilities:
            minimum = task.minimum_capability_scores.get(capability, 0.5)
            actual, _snapshot = self._capability_snapshot(model, route, capability)
            if actual < minimum:
                return f"Capability {capability.value} below minimum."
        if (
            task.max_input_cost_per_million is not None
            and route.cost_per_million_input > task.max_input_cost_per_million
        ):
            return "Input price exceeds ceiling."
        if (
            task.max_output_cost_per_million is not None
            and route.cost_per_million_output > task.max_output_cost_per_million
        ):
            return "Output price exceeds ceiling."
        if budget_tier == BudgetTier.EXHAUSTED and (
            route.cost_per_million_input > 0 or route.cost_per_million_output > 0
        ):
            return "Budget exhausted: paid routes prohibited."
        if budget_tier == BudgetTier.DOWNGRADE and route.cost_per_million_input > 5:
            return "Budget downgrade tier prohibits high-cost route."
        for policy in self.route_policies:
            hook = getattr(policy, "eligibility_reason", None)
            if hook is None:
                continue
            reason = hook(model, route, task)
            if reason:
                return str(reason)
        return None

    def _score(self, model, route, task, budget_tier):
        capability_weights = task.capability_weights or {
            capability: 1.0 for capability in task.required_capabilities
        } or {ModelCapability.REASONING: 1.0}
        capability_observations = {
            capability: self._capability_snapshot(model, route, capability)
            for capability in capability_weights
        }
        capability_score = sum(
            capability_observations[capability][0] * weight
            for capability, weight in capability_weights.items()
        ) / sum(capability_weights.values())

        performance = self.performance_ledger.snapshot(model.model_key, task.task_kind)
        empirical_score = performance.empirical_score

        blended_price = route.cost_per_million_input + 0.25 * route.cost_per_million_output
        cost_score = max(0.0, 1.0 - min(blended_price / 20.0, 1.0))
        privacy_score = {
            RetentionPolicy.LOCAL_ONLY: 1.0,
            RetentionPolicy.ZERO_DATA_RETENTION: 0.95,
            RetentionPolicy.PROVIDER_DEFAULT: 0.55,
            RetentionPolicy.UNKNOWN: 0.30,
        }[route.retention_policy]

        route_health = self.health_registry.get_state(route.route_id)
        health_score = 1.0 if route_health == RouteHealth.HEALTHY else 0.65
        operational = self.telemetry_registry.snapshot(route.route_id)
        if operational.sample_count >= 3:
            health_score *= max(0.40, operational.success_rate)

        if task.preferred_transports:
            try:
                transport_score = max(
                    0.6, 1.0 - task.preferred_transports.index(route.transport) * 0.1
                )
            except ValueError:
                transport_score = 0.5
        else:
            transport_score = {
                TransportKind.LOCAL: 0.95,
                TransportKind.API: 0.90,
                TransportKind.DESKTOP_APP: 0.70,
                TransportKind.BROWSER: 0.65,
            }[route.transport]

        context_limit = route.context_window_override or model.context_window
        if task.required_context_tokens <= 0:
            context_score = 1.0
        else:
            context_ratio = context_limit / max(task.required_context_tokens, 1)
            context_score = min(1.0, 0.5 + min(context_ratio / 4.0, 0.5))

        capability_weight = {
            TaskComplexity.TRIVIAL: 0.30,
            TaskComplexity.STANDARD: 0.34,
            TaskComplexity.COMPLEX: 0.38,
            TaskComplexity.FRONTIER: 0.42,
        }[task.complexity]
        # Keep the score normalized by moving weight away from cost/transport as
        # complexity rises, not by letting the total exceed 1.
        extra = capability_weight - 0.34
        cost_weight = max(0.04, 0.09 - extra * 0.55)
        transport_weight = max(0.03, 0.06 - extra * 0.45)
        static_weight_sum = capability_weight + 0.12 + 0.18 + 0.14 + cost_weight + transport_weight + 0.07
        total = (
            capability_score * capability_weight
            + empirical_score * 0.12
            + privacy_score * 0.18
            + health_score * 0.14
            + cost_score * cost_weight
            + transport_score * transport_weight
            + context_score * 0.07
        ) / static_weight_sum

        rationale = [
            f"complexity={task.complexity.value}",
            f"capability={capability_score:.3f}",
            f"empirical={empirical_score:.3f}({performance.sample_count} samples)",
            f"privacy={privacy_score:.3f}",
            f"health={health_score:.3f}({operational.sample_count} route samples)",
            f"cost={cost_score:.3f}",
        ]
        discovered = [
            (capability, snapshot)
            for capability, (_score, snapshot) in capability_observations.items()
            if snapshot is not None and snapshot.sample_count > 0
        ]
        if discovered:
            rationale.append(
                "capability_discovery="
                + ",".join(
                    f"{capability.value}:{snapshot.effective_score:.3f}/c{snapshot.confidence:.2f}"
                    for capability, snapshot in sorted(discovered, key=lambda item: item[0].value)
                )
            )
        if performance.drift_alert:
            rationale.append("model_quality_drift_alert")

        policy_multiplier = 1.0
        for policy in self.route_policies:
            hook = getattr(policy, "score_multiplier", None)
            if hook is None:
                continue
            multiplier = max(0.0, min(1.0, float(hook(model, route, task))))
            policy_multiplier *= multiplier
            rationale.append(f"route_policy_multiplier={multiplier:.3f}")
        total *= policy_multiplier

        return CandidateScore(
            model_key=model.model_key,
            route_id=route.route_id,
            total_score=round(total, 6),
            capability_score=round(capability_score, 6),
            empirical_score=round(empirical_score, 6),
            cost_score=round(cost_score, 6),
            privacy_score=round(privacy_score, 6),
            health_score=round(health_score, 6),
            transport_score=round(transport_score, 6),
            context_score=round(context_score, 6),
            rationale=rationale,
        )

    def select(self, task):
        budget_tier = self.budget_gatekeeper.get_tier()
        scored = []
        rejected = []
        for route in self.catalog.list_routes(enabled_only=False):
            model = self.catalog.require_model(route.model_key)
            reason = self._eligibility_reason(model, route, task, budget_tier)
            if reason:
                rejected.append(
                    RejectedCandidate(
                        model_key=model.model_key,
                        route_id=route.route_id,
                        reason=reason,
                    )
                )
            else:
                scored.append(self._score(model, route, task, budget_tier))
        if not scored:
            raise CapabilityDeniedError(
                "No eligible Intelligence Fabric route. "
                + "; ".join(f"{item.route_id}: {item.reason}" for item in rejected)
            )
        scored.sort(
            key=lambda item: (item.total_score, item.model_key, item.route_id),
            reverse=True,
        )
        winner = scored[0]
        return FabricRoutingDecision(
            model_key=winner.model_key,
            route_id=winner.route_id,
            selected_score=winner,
            alternatives=scored[1:],
            rejected=rejected,
        )
