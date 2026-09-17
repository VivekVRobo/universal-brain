from __future__ import annotations

from dataclasses import dataclass

from universal_brain.executive.budget import BudgetGatekeeper

from .catalog import ModelCatalog
from .adaptive_eval import AdaptiveEvaluationHarness
from .capabilities import CapabilityDiscoveryRegistry
from .context import ContextCompiler
from .council import ModelCouncilExecutor, ModelCouncilPlanner
from .escalation import EscalationPolicyGraph, IntelligenceEscalator
from .evaluations import PerformanceLedger
from .fabric import IntelligenceFabric
from .health import RouteHealthRegistry
from .mission_runtime import AdaptiveCognitiveMissionRuntime
from .profiling import DeterministicTaskProfiler
from .quota import RouteQuotaPolicy, RouteQuotaRegistry
from .routing import IntelligenceRouter
from .runtime import IntelligenceRuntime
from .schemas import TransportKind
from .sessions import ConversationRegistry
from .supervisor import InteractionSessionSupervisor
from .telemetry import RouteTelemetryRegistry
from .transports import (
    BrowserHumanTransport,
    DesktopAppTransport,
    OpenAICompatibleTransport,
    PlaywrightChatUIDriver,
    WindowsUIAChatDriver,
)


@dataclass(slots=True)
class IntelligenceStack:
    catalog: ModelCatalog
    budget: BudgetGatekeeper
    health: RouteHealthRegistry
    quota: RouteQuotaRegistry
    performance: PerformanceLedger
    capabilities: CapabilityDiscoveryRegistry
    telemetry: RouteTelemetryRegistry
    conversations: ConversationRegistry
    context_compiler: ContextCompiler
    profiler: DeterministicTaskProfiler
    browser_transport: BrowserHumanTransport
    desktop_transport: DesktopAppTransport
    supervisor: InteractionSessionSupervisor
    runtime: IntelligenceRuntime
    router: IntelligenceRouter
    fabric: IntelligenceFabric
    escalator: IntelligenceEscalator
    council_planner: ModelCouncilPlanner
    council_executor: ModelCouncilExecutor
    evaluation_harness: AdaptiveEvaluationHarness
    mission_runtime: AdaptiveCognitiveMissionRuntime


def build_intelligence_stack(
    catalog,
    *,
    budget=None,
    health=None,
    quota=None,
    performance=None,
    performance_path=None,
    capability_registry=None,
    capability_registry_path=None,
    telemetry=None,
    telemetry_path=None,
    conversation_registry=None,
    conversation_registry_path=None,
    context_compiler=None,
    context_sources=(),
    profiler=None,
    browser_drivers=None,
    desktop_drivers=None,
    transports=(),
    escalation_policy: EscalationPolicyGraph | None = None,
    mission_verifier=None,
    route_policies=(),
):
    budget = budget or BudgetGatekeeper()
    health = health or RouteHealthRegistry()
    quota = quota or RouteQuotaRegistry()
    if performance is not None and performance_path is not None:
        raise ValueError("pass performance ledger or performance_path, not both")
    performance = performance or PerformanceLedger(persistence_path=performance_path)
    if capability_registry is not None and capability_registry_path is not None:
        raise ValueError("pass capability registry or capability_registry_path, not both")
    capabilities = capability_registry or CapabilityDiscoveryRegistry(
        persistence_path=capability_registry_path
    )
    if telemetry is not None and telemetry_path is not None:
        raise ValueError("pass telemetry registry or telemetry_path, not both")
    telemetry = telemetry or RouteTelemetryRegistry(persistence_path=telemetry_path)
    if conversation_registry is not None and conversation_registry_path is not None:
        raise ValueError("pass conversation registry or conversation_registry_path, not both")
    conversations = conversation_registry or ConversationRegistry(conversation_registry_path)
    context_compiler = context_compiler or ContextCompiler()
    profiler = profiler or DeterministicTaskProfiler()

    browser_driver_map = dict(browser_drivers or {})
    desktop_driver_map = dict(desktop_drivers or {})
    for route in catalog.list_routes(enabled_only=False):
        if isinstance(route.config.get("quota"), dict):
            quota.configure(
                route.route_id,
                RouteQuotaPolicy.model_validate(route.config["quota"]),
            )
        if (
            route.transport == TransportKind.BROWSER
            and route.config.get("driver") == "playwright_chat_ui"
            and route.route_id not in browser_driver_map
        ):
            browser_driver_map[route.route_id] = PlaywrightChatUIDriver()
        if (
            route.transport == TransportKind.DESKTOP_APP
            and route.config.get("driver") == "windows_uia_chat"
            and route.route_id not in desktop_driver_map
        ):
            desktop_driver_map[route.route_id] = WindowsUIAChatDriver()

    browser = BrowserHumanTransport(browser_driver_map)
    desktop = DesktopAppTransport(desktop_driver_map)
    all_transports = [
        *list(transports),
        OpenAICompatibleTransport(),
        browser,
        desktop,
    ]
    runtime = IntelligenceRuntime(
        catalog,
        all_transports,
        health_registry=health,
        quota_registry=quota,
        telemetry_registry=telemetry,
        execution_policies=route_policies,
    )
    router = IntelligenceRouter(
        catalog, budget, health, performance, quota, telemetry, capabilities, route_policies
    )
    fabric = IntelligenceFabric(
        router,
        runtime,
        conversations,
        context_compiler=context_compiler,
        context_sources=context_sources,
        profiler=profiler,
    )
    escalator = IntelligenceEscalator(fabric, policy=escalation_policy)
    planner = ModelCouncilPlanner(router)
    executor = ModelCouncilExecutor(planner, fabric)
    evaluation_harness = AdaptiveEvaluationHarness(
        fabric=fabric,
        performance_ledger=performance,
        capability_registry=capabilities,
    )
    mission_runtime = AdaptiveCognitiveMissionRuntime(
        fabric=fabric,
        escalator=escalator,
        council_executor=executor,
        verifier=mission_verifier,
    )
    supervisor = InteractionSessionSupervisor(
        browser_transport=browser,
        desktop_transport=desktop,
        conversations=conversations,
        health_registry=health,
    )
    return IntelligenceStack(
        catalog=catalog,
        budget=budget,
        health=health,
        quota=quota,
        performance=performance,
        capabilities=capabilities,
        telemetry=telemetry,
        conversations=conversations,
        context_compiler=context_compiler,
        profiler=profiler,
        browser_transport=browser,
        desktop_transport=desktop,
        supervisor=supervisor,
        runtime=runtime,
        router=router,
        fabric=fabric,
        escalator=escalator,
        council_planner=planner,
        council_executor=executor,
        evaluation_harness=evaluation_harness,
        mission_runtime=mission_runtime,
    )
