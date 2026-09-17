from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelStatusSnapshot(BaseModel):
    model_key: str
    display_name: str
    vendor: str
    family: str
    enabled: bool
    context_window: int
    route_count: int
    empirical_score: float
    evaluation_samples: int
    drift_alert: bool
    capability_evidence_samples: int = 0
    effective_capabilities: dict[str, float] = Field(default_factory=dict)


class RouteStatusSnapshot(BaseModel):
    route_id: str
    model_key: str
    transport: str
    enabled: bool
    health: str
    retention_policy: str
    max_sensitivity: str
    cost_per_million_input: float
    cost_per_million_output: float
    quota: dict[str, Any]
    telemetry: dict[str, Any]
    active_conversations: int
    recovery_candidates: int = 0


class IntelligenceObservabilitySnapshot(BaseModel):
    configured: bool = True
    model_count: int = 0
    route_count: int = 0
    healthy_routes: int = 0
    degraded_routes: int = 0
    unavailable_routes: int = 0
    active_conversations: int = 0
    models: list[ModelStatusSnapshot] = Field(default_factory=list)
    routes: list[RouteStatusSnapshot] = Field(default_factory=list)
    recent_invocations: list[dict[str, Any]] = Field(default_factory=list)
    note: str | None = None


def build_observability_snapshot(stack) -> IntelligenceObservabilitySnapshot:
    """Build a content-free control-plane snapshot from an IntelligenceStack."""
    active_bindings = stack.conversations.list_all(active_only=True)
    conversations_by_route: dict[str, int] = {}
    for binding in active_bindings:
        conversations_by_route[binding.route_id] = (
            conversations_by_route.get(binding.route_id, 0) + 1
        )

    export = stack.catalog.export()
    model_rows: list[ModelStatusSnapshot] = []
    for item in sorted(export["models"], key=lambda row: row["model_key"]):
        descriptor = stack.catalog.require_model(item["model_key"])
        performance = stack.performance.snapshot(descriptor.model_key)
        capability_records = (
            stack.capabilities.records_for_model(descriptor.model_key)
            if getattr(stack, "capabilities", None) is not None
            else []
        )
        effective_capabilities = {}
        if getattr(stack, "capabilities", None) is not None:
            for capability, declared in descriptor.capability_profile.scores.items():
                effective_capabilities[capability.value] = stack.capabilities.snapshot(
                    model_key=descriptor.model_key,
                    capability=capability,
                    declared_score=declared,
                ).effective_score
        model_rows.append(
            ModelStatusSnapshot(
                model_key=descriptor.model_key,
                display_name=descriptor.display_name,
                vendor=descriptor.vendor,
                family=descriptor.family,
                enabled=descriptor.enabled,
                context_window=descriptor.context_window,
                route_count=len(stack.catalog.routes_for_model(descriptor.model_key)),
                empirical_score=performance.empirical_score,
                evaluation_samples=performance.sample_count,
                drift_alert=performance.drift_alert,
                capability_evidence_samples=len(capability_records),
                effective_capabilities=effective_capabilities,
            )
        )

    route_rows: list[RouteStatusSnapshot] = []
    healthy = degraded = unavailable = 0
    for route in sorted(
        stack.catalog.list_routes(enabled_only=False), key=lambda item: item.route_id
    ):
        health = stack.health.get_state(route.route_id) if route.enabled else "disabled"
        health_value = health.value if hasattr(health, "value") else str(health)
        if health_value == "healthy":
            healthy += 1
        elif health_value == "degraded":
            degraded += 1
        else:
            unavailable += 1
        route_rows.append(
            RouteStatusSnapshot(
                route_id=route.route_id,
                model_key=route.model_key,
                transport=route.transport.value,
                enabled=route.enabled,
                health=health_value,
                retention_policy=route.retention_policy.value,
                max_sensitivity=route.max_sensitivity.value,
                cost_per_million_input=route.cost_per_million_input,
                cost_per_million_output=route.cost_per_million_output,
                quota=stack.quota.snapshot(route.route_id).model_dump(mode="json"),
                telemetry=stack.telemetry.snapshot(route.route_id).model_dump(mode="json"),
                active_conversations=conversations_by_route.get(route.route_id, 0),
                recovery_candidates=len(
                    stack.conversations.list_route(route.route_id, active_only=False)
                ),
            )
        )

    return IntelligenceObservabilitySnapshot(
        model_count=len(model_rows),
        route_count=len(route_rows),
        healthy_routes=healthy,
        degraded_routes=degraded,
        unavailable_routes=unavailable,
        active_conversations=len(active_bindings),
        models=model_rows,
        routes=route_rows,
        recent_invocations=[
            record.model_dump(mode="json") for record in stack.telemetry.recent(limit=20)
        ],
    )
