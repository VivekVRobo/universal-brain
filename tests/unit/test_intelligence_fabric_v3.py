from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from universal_brain.executive.budget import BudgetGatekeeper
from universal_brain.intelligence import (
    AccessRoute,
    AuthMode,
    CapabilityProfile,
    ClaimStance,
    ContextCompiler,
    CouncilDisagreementAnalyzer,
    CouncilRole,
    DeterministicTaskProfiler,
    EscalationPolicyGraph,
    FileSystemContextSource,
    ModelCapability,
    ModelDescriptor,
    ModelEvaluationRecord,
    ModelMessage,
    ModelRequest,
    ModelStreamEvent,
    ModelUsage,
    PerformanceLedger,
    RetentionPolicy,
    RouteHealth,
    RouteTelemetryRegistry,
    SensitivityLevel,
    StreamEventType,
    StreamInterruptedError,
    TaskComplexity,
    TaskProfile,
    ToolCallNormalizer,
    TransportKind,
    build_intelligence_stack,
)
from universal_brain.intelligence.schemas import NormalizedModelResult
from universal_brain.intelligence.transports.base import BaseModelTransport, TransportOutageError
from universal_brain.intelligence.transports.browser import BrowserModelDriver
from universal_brain.intelligence.transports.mock import MockTransport


def descriptor(key: str, score: float) -> ModelDescriptor:
    return ModelDescriptor(
        model_key=key,
        vendor="test",
        model_id=key,
        display_name=key,
        family="test",
        context_window=256_000,
        capability_profile=CapabilityProfile(
            scores={
                ModelCapability.REASONING: score,
                ModelCapability.CODING: score,
                ModelCapability.ARCHITECTURE: score,
                ModelCapability.VERIFICATION: score,
                ModelCapability.STRUCTURED_OUTPUT: score,
                ModelCapability.TOOL_USE: score,
            }
        ),
    )


def three_model_catalog():
    from universal_brain.intelligence import ModelCatalog

    catalog = ModelCatalog()
    for key, score in [("model/a", 0.98), ("model/b", 0.90), ("model/c", 0.82)]:
        catalog.register_model(descriptor(key, score))
    catalog.register_route(
        AccessRoute(
            route_id="a-api",
            model_key="model/a",
            transport=TransportKind.API,
            retention_policy=RetentionPolicy.ZERO_DATA_RETENTION,
            max_sensitivity=SensitivityLevel.CONFIDENTIAL,
            cost_per_million_input=10,
            cost_per_million_output=40,
        )
    )
    catalog.register_route(
        AccessRoute(
            route_id="b-api",
            model_key="model/b",
            transport=TransportKind.API,
            retention_policy=RetentionPolicy.PROVIDER_DEFAULT,
            max_sensitivity=SensitivityLevel.INTERNAL,
            cost_per_million_input=1,
            cost_per_million_output=2,
        )
    )
    catalog.register_route(
        AccessRoute(
            route_id="c-local",
            model_key="model/c",
            transport=TransportKind.LOCAL,
            retention_policy=RetentionPolicy.LOCAL_ONLY,
            max_sensitivity=SensitivityLevel.SECRET,
            cost_per_million_input=0,
            cost_per_million_output=0,
        )
    )
    return catalog


def test_deterministic_task_profiler_builds_capability_profile():
    profiler = DeterministicTaskProfiler()
    request = ModelRequest(
        messages=[
            ModelMessage(
                role="user",
                content=(
                    "Deeply review this repository architecture, refactor the Python runtime, "
                    "run tests, verify evidence, and return structured JSON."
                ),
            )
        ],
        response_schema={"type": "object"},
        tools=[{"type": "function", "name": "run_tests"}],
    )
    analysis = profiler.profile(request)
    assert analysis.profile.complexity in {TaskComplexity.COMPLEX, TaskComplexity.FRONTIER}
    assert ModelCapability.CODING in analysis.profile.required_capabilities
    assert ModelCapability.ARCHITECTURE in analysis.profile.required_capabilities
    assert ModelCapability.VERIFICATION in analysis.profile.required_capabilities
    assert ModelCapability.STRUCTURED_OUTPUT in analysis.profile.required_capabilities
    assert analysis.profile.require_tools is True


def test_context_compiler_v2_retrieves_repo_without_secret_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "router.py").write_text(
        "class IntelligenceRouter:\n    # architecture routing capability scoring\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("unrelated notes", encoding="utf-8")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-thismustneverappear123456789", encoding="utf-8")
    source = FileSystemContextSource(tmp_path)
    route = AccessRoute(
        route_id="local",
        model_key="model/c",
        transport=TransportKind.LOCAL,
        retention_policy=RetentionPolicy.LOCAL_ONLY,
        max_sensitivity=SensitivityLevel.SECRET,
    )
    compiler = ContextCompiler()
    request = ModelRequest(
        messages=[ModelMessage(role="user", content="review intelligence router architecture")]
    )
    compiled = compiler.compile_task(
        request=request,
        task=TaskProfile(required_context_tokens=1000),
        route=route,
        model_context_window=32_000,
        sources=[source],
    )
    joined = "\n".join(message.content for message in compiled.messages)
    assert "IntelligenceRouter" in joined
    assert "thismustneverappear" not in joined
    assert compiled.metadata["context_compiler_version"] == 2
    assert compiled.metadata["context_manifest"]


def test_performance_ledger_is_durable(tmp_path):
    path = tmp_path / "performance.json"
    ledger = PerformanceLedger(persistence_path=path)
    ledger.record(
        ModelEvaluationRecord(
            model_key="model/a",
            route_id="a-api",
            task_kind="coding",
            quality_score=0.91,
            evidence_ref="test://suite/1",
        )
    )
    loaded = PerformanceLedger(persistence_path=path)
    snapshot = loaded.snapshot("model/a", "coding")
    assert snapshot.sample_count == 1
    assert snapshot.empirical_score > 0.9


@pytest.mark.asyncio
async def test_runtime_telemetry_is_durable(tmp_path):
    telemetry_path = tmp_path / "telemetry.json"
    stack = build_intelligence_stack(
        three_model_catalog(),
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        telemetry_path=telemetry_path,
        transports=[MockTransport()],
    )
    result = await stack.fabric.invoke(
        TaskProfile(required_capabilities={ModelCapability.REASONING}),
        ModelRequest(messages=[ModelMessage(role="user", content="hello")]),
    )
    loaded = RouteTelemetryRegistry(telemetry_path)
    snapshot = loaded.snapshot(result.route_id)
    assert snapshot.sample_count == 1
    assert snapshot.success_count == 1
    assert snapshot.total_input_tokens == 100


def test_tool_call_normalizer_handles_multiple_provider_shapes():
    openai = ToolCallNormalizer.openai_chat(
        [{"id": "x", "function": {"name": "read_file", "arguments": '{"path":"a"}'}}]
    )
    anthropic = ToolCallNormalizer.anthropic(
        [{"type": "tool_use", "id": "y", "name": "run", "input": {"cmd": "pwd"}}]
    )
    gemini = ToolCallNormalizer.gemini(
        [{"content": {"parts": [{"functionCall": {"name": "search", "args": {"q": "x"}}}]}}]
    )
    assert openai[0].arguments == {"path": "a"}
    assert anthropic[0].tool_name == "run"
    assert gemini[0].arguments == {"q": "x"}


@pytest.mark.asyncio
async def test_escalation_policy_graph_moves_from_economy_to_frontier():
    catalog = three_model_catalog()
    mock = MockTransport()
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        transports=[mock],
    )
    # Economy route is selected first but returns a result below deterministic threshold.
    mock.outputs["b-api"] = "x"
    mock.outputs["a-api"] = "frontier answer passes threshold"
    mock.outputs["c-local"] = "x"
    policy = EscalationPolicyGraph.economy_then_frontier(
        economy_input_ceiling=2,
        economy_output_ceiling=5,
        candidates_per_stage=2,
    )
    task = TaskProfile(
        required_capabilities={ModelCapability.REASONING},
        allowed_transports={TransportKind.API},
    )
    result = await stack.escalator.invoke(
        task,
        ModelRequest(
            messages=[ModelMessage(role="user", content="x")],
            metadata={"min_output_chars": 8},
        ),
        policy=policy,
    )
    assert result.route_id == "a-api"
    attempts = result.raw_metadata["intelligence_escalation"]
    assert attempts[0]["stage"] == "economy"
    assert attempts[-1]["stage"] == "frontier"


def test_council_disagreement_graph_preserves_explicit_conflict():
    analyzer = CouncilDisagreementAnalyzer()
    request_id = uuid4()
    results = {
        "architect": NormalizedModelResult(
            request_id=request_id,
            model_key="model/a",
            route_id="a-api",
            structured_output={
                "claims": [{"topic": "database", "claim": "Use PostgreSQL", "stance": "support"}]
            },
        ),
        "critic": NormalizedModelResult(
            request_id=request_id,
            model_key="model/b",
            route_id="b-api",
            structured_output={
                "claims": [{"topic": "database", "claim": "Do not use PostgreSQL", "stance": "oppose"}]
            },
        ),
    }
    graph = analyzer.analyze(results)
    assert len(graph.disagreements) == 1
    assert graph.disagreements[0].left_stance != graph.disagreements[0].right_stance
    assert graph.consensus_is_evidence is False


@pytest.mark.asyncio
async def test_council_synthesis_uses_independent_model_and_keeps_non_evidence_marker():
    catalog = three_model_catalog()
    mock = MockTransport()
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        transports=[mock],
    )
    first = stack.router.select(TaskProfile(required_capabilities={ModelCapability.REASONING}))
    roles = [
        CouncilRole(
            role="architect",
            task_profile=TaskProfile(required_capabilities={ModelCapability.REASONING}),
        ),
        CouncilRole(
            role="critic",
            task_profile=TaskProfile(required_capabilities={ModelCapability.VERIFICATION}),
            require_independent_route_from=first.route_id,
        ),
    ]
    requests = {
        role.role: ModelRequest(messages=[ModelMessage(role="user", content=role.role)])
        for role in roles
    }
    synthesis_role = CouncilRole(
        role="synthesizer",
        task_profile=TaskProfile(required_capabilities={ModelCapability.REASONING}),
    )
    bundle = await stack.council_executor.execute_and_synthesize(
        roles=roles,
        requests=requests,
        synthesis_role=synthesis_role,
    )
    member_models = {result.model_key for result in bundle.member_results.values()}
    assert bundle.synthesis_result.model_key not in member_models
    assert bundle.synthesis_result.raw_metadata["council_consensus_is_evidence"] is False


class ToggleBrowserDriver(BrowserModelDriver):
    def __init__(self, authenticated=True):
        self.authenticated = authenticated

    async def is_authenticated(self, route):
        return self.authenticated

    async def submit(self, model, route, request):
        return NormalizedModelResult(
            request_id=request.request_id,
            model_key=model.model_key,
            route_id=route.route_id,
            output_text="ok",
        )


@pytest.mark.asyncio
async def test_session_supervisor_invalidates_continuity_on_auth_loss():
    from universal_brain.intelligence import ModelCatalog

    catalog = ModelCatalog()
    catalog.register_model(descriptor("model/browser", 0.9))
    route = AccessRoute(
        route_id="browser-route",
        model_key="model/browser",
        transport=TransportKind.BROWSER,
        auth_mode=AuthMode.USER_SESSION,
        retention_policy=RetentionPolicy.PROVIDER_DEFAULT,
        max_sensitivity=SensitivityLevel.INTERNAL,
    )
    catalog.register_route(route)
    driver = ToggleBrowserDriver(authenticated=True)
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        browser_drivers={route.route_id: driver},
    )
    project_id = uuid4()
    stack.conversations.upsert(
        project_id=project_id,
        role="architect",
        model_key=route.model_key,
        route_id=route.route_id,
        conversation_ref="https://example.test/thread/1",
    )
    driver.authenticated = False
    probe = await stack.supervisor.probe_route(route)
    assert probe.health == RouteHealth.AUTH_REQUIRED
    assert stack.conversations.find(project_id, "architect") is None


class PartialFailTransport(BaseModelTransport):
    def __init__(self, fail_route: str):
        self.fail_route = fail_route

    def supports(self, route):
        return True

    async def invoke(self, model, route, request):
        return NormalizedModelResult(
            request_id=request.request_id,
            model_key=model.model_key,
            route_id=route.route_id,
            output_text="fallback",
        )

    async def stream(self, model, route, request):
        yield ModelStreamEvent(
            event_type=StreamEventType.STARTED,
            request_id=request.request_id,
            model_key=model.model_key,
            route_id=route.route_id,
            sequence=0,
        )
        if route.route_id == self.fail_route:
            yield ModelStreamEvent(
                event_type=StreamEventType.TEXT_DELTA,
                request_id=request.request_id,
                model_key=model.model_key,
                route_id=route.route_id,
                sequence=1,
                delta_text="partial",
            )
            raise TransportOutageError("stream broke")
        result = await self.invoke(model, route, request)
        yield ModelStreamEvent(
            event_type=StreamEventType.COMPLETED,
            request_id=request.request_id,
            model_key=model.model_key,
            route_id=route.route_id,
            sequence=1,
            final_result=result,
        )


@pytest.mark.asyncio
async def test_streaming_never_switches_route_after_partial_output():
    catalog = three_model_catalog()
    router_stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        transports=[MockTransport()],
    )
    task = TaskProfile(required_capabilities={ModelCapability.REASONING})
    first_route = router_stack.router.select(task).route_id
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        transports=[PartialFailTransport(first_route)],
    )
    events = []
    with pytest.raises(StreamInterruptedError):
        async for event in stack.fabric.stream(
            task, ModelRequest(messages=[ModelMessage(role="user", content="x")])
        ):
            events.append(event)
    assert any(event.delta_text == "partial" for event in events)


def test_observability_snapshot_exposes_no_prompt_bodies():
    from universal_brain.intelligence import build_observability_snapshot

    stack = build_intelligence_stack(
        three_model_catalog(),
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        transports=[MockTransport()],
    )
    snapshot = build_observability_snapshot(stack)
    payload = snapshot.model_dump(mode="json")
    assert payload["configured"] is True
    assert payload["model_count"] == 3
    assert payload["route_count"] == 3
    assert "messages" not in str(payload).lower()
