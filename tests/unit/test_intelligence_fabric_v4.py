from __future__ import annotations

from uuid import uuid4

import pytest

from universal_brain.autonomy.blackboard import MissionBlackboard
from universal_brain.autonomy.schemas import BlackboardEntryType
from universal_brain.executive.budget import BudgetGatekeeper
from universal_brain.executive.schemas import TaskDAG, TaskNode, TaskNodeStatus
from universal_brain.intelligence import (
    AccessRoute,
    AdaptiveCognitiveMissionRuntime,
    AuthMode,
    CapabilityDiscoveryRegistry,
    CapabilityEvidenceSource,
    CapabilityProfile,
    CompositeContextSource,
    ContextCompiler,
    CouncilRole,
    EventStoreContextSource,
    MissionBlackboardContextSource,
    MissionVerificationDecision,
    ModelCapability,
    ModelCatalog,
    ModelDescriptor,
    ModelMessage,
    ModelRequest,
    RetentionPolicy,
    SemanticMemoryContextSource,
    SensitivityLevel,
    SessionRecoveryStatus,
    TaskProfile,
    TransportKind,
    build_intelligence_stack,
)
from universal_brain.intelligence.schemas import NormalizedModelResult
from universal_brain.intelligence.transports.browser import BrowserModelDriver
from universal_brain.intelligence.transports.mock import MockTransport
from universal_brain.intelligence.transports.windows_uia_driver import WindowsUIAChatDriver
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventType
from universal_brain.persistence.vector.index import SemanticMemoryIndex


def model(key: str, score: float) -> ModelDescriptor:
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
                ModelCapability.ARCHITECTURE: score,
                ModelCapability.CODING: score,
                ModelCapability.VERIFICATION: score,
            }
        ),
    )


def three_model_catalog() -> ModelCatalog:
    catalog = ModelCatalog()
    for key, score in (("model/a", 0.92), ("model/b", 0.86), ("model/c", 0.80)):
        catalog.register_model(model(key, score))
        catalog.register_route(
            AccessRoute(
                route_id=f"{key[-1]}-api",
                model_key=key,
                transport=TransportKind.API,
                retention_policy=RetentionPolicy.ZERO_DATA_RETENTION,
                max_sensitivity=SensitivityLevel.CONFIDENTIAL,
                cost_per_million_input=1,
                cost_per_million_output=2,
            )
        )
    return catalog


def test_capability_discovery_changes_effective_routing_without_permission_change(tmp_path):
    catalog = ModelCatalog()
    catalog.register_model(model("model/observed", 0.60))
    catalog.register_model(model("model/static", 0.82))
    for key in ("model/observed", "model/static"):
        catalog.register_route(
            AccessRoute(
                route_id=f"{key.split('/')[-1]}-api",
                model_key=key,
                transport=TransportKind.API,
                retention_policy=RetentionPolicy.ZERO_DATA_RETENTION,
                max_sensitivity=SensitivityLevel.INTERNAL,
            )
        )
    registry = CapabilityDiscoveryRegistry(persistence_path=tmp_path / "caps.json")
    for index in range(4):
        registry.record_score(
            model_key="model/observed",
            capability=ModelCapability.REASONING,
            score=0.98,
            source=CapabilityEvidenceSource.BENCHMARK,
            evidence_ref=f"benchmark://reasoning/{index}",
        )
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        capability_registry=registry,
        transports=[MockTransport()],
    )
    task = TaskProfile(
        required_capabilities={ModelCapability.REASONING},
        minimum_capability_scores={ModelCapability.REASONING: 0.75},
    )
    decision = stack.router.select(task)
    assert decision.model_key == "model/observed"
    assert "capability_discovery=" in " ".join(decision.selected_score.rationale)
    assert task.action_class == ActionClass.A0
    reloaded = CapabilityDiscoveryRegistry(persistence_path=tmp_path / "caps.json")
    assert reloaded.snapshot(
        model_key="model/observed",
        capability=ModelCapability.REASONING,
        declared_score=0.60,
    ).sample_count == 4


def test_context_memory_retrieval_preserves_provenance_and_blackboard_status():
    project_id = uuid4()
    mission_id = uuid4()
    actor = uuid4()
    store = EventStore()
    event = store.append_event(
        EventType.USER_INPUT,
        actor_id="operator",
        project_id=project_id,
        payload={"objective": "Use a local-first intelligence fabric"},
    )
    semantic = SemanticMemoryIndex()
    semantic.index_event(event)
    blackboard = MissionBlackboard()
    entry = blackboard.post_entry(
        mission_id=mission_id,
        entry_type=BlackboardEntryType.FACT,
        statement="The routing layer must remain provider-neutral",
        source_agent_id=actor,
    )
    blackboard.verify_entry(entry.entry_id, ["test://provider-neutral"])

    source = CompositeContextSource(
        [
            SemanticMemoryContextSource(semantic),
            EventStoreContextSource(store, project_id=project_id),
            MissionBlackboardContextSource(blackboard, mission_id),
        ]
    )
    chunks = source.retrieve("provider neutral local intelligence routing", max_chunks=10)
    assert any(chunk.metadata.get("retrieval_kind") == "derived_semantic_memory" for chunk in chunks)
    assert any(chunk.metadata.get("retrieval_kind") == "canonical_event" for chunk in chunks)
    verified = [
        chunk
        for chunk in chunks
        if chunk.metadata.get("retrieval_kind") == "mission_blackboard"
    ]
    assert verified and verified[0].metadata["status"] == "VERIFIED"
    assert verified[0].metadata["evidence_refs"] == ["test://provider-neutral"]

    route = AccessRoute(
        route_id="local",
        model_key="model/local",
        transport=TransportKind.LOCAL,
        retention_policy=RetentionPolicy.LOCAL_ONLY,
        max_sensitivity=SensitivityLevel.SECRET,
    )
    compiled = ContextCompiler().compile_task(
        request=ModelRequest(
            messages=[ModelMessage(role="user", content="provider neutral local intelligence routing")]
        ),
        task=TaskProfile(required_context_tokens=1_000),
        route=route,
        model_context_window=32_000,
        sources=[source],
    )
    assert compiled.metadata["context_manifest"]
    assert any(
        item["metadata"].get("retrieval_kind") == "canonical_event"
        for item in compiled.metadata["context_manifest"]
    )


class RecoverableBrowserDriver(BrowserModelDriver):
    def __init__(self):
        self.authenticated = True

    async def is_authenticated(self, route):
        return self.authenticated

    async def submit(self, model, route, request):
        return NormalizedModelResult(
            request_id=request.request_id,
            model_key=model.model_key,
            route_id=route.route_id,
            output_text="ok",
            conversation_ref="https://example.test/thread/live",
        )

    async def recover_session(self, route, conversation_ref=None):
        return "https://example.test/thread/recovered"


@pytest.mark.asyncio
async def test_session_recovery_reactivates_noncanonical_conversation_binding():
    catalog = ModelCatalog()
    catalog.register_model(model("model/browser", 0.9))
    route = AccessRoute(
        route_id="browser-route",
        model_key="model/browser",
        transport=TransportKind.BROWSER,
        auth_mode=AuthMode.USER_SESSION,
        retention_policy=RetentionPolicy.PROVIDER_DEFAULT,
        max_sensitivity=SensitivityLevel.INTERNAL,
    )
    catalog.register_route(route)
    driver = RecoverableBrowserDriver()
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        browser_drivers={route.route_id: driver},
    )
    project_id = uuid4()
    binding = stack.conversations.upsert(
        project_id=project_id,
        role="architect",
        model_key=route.model_key,
        route_id=route.route_id,
        conversation_ref="https://example.test/thread/old",
    )
    driver.authenticated = False
    await stack.supervisor.probe_route(route)
    assert stack.conversations.get(binding.binding_id).active is False

    driver.authenticated = True
    recovery = await stack.supervisor.recover_route(route)
    restored = stack.conversations.get(binding.binding_id)
    assert recovery.status == SessionRecoveryStatus.RECOVERED
    assert restored.active is True
    assert restored.conversation_ref.endswith("/recovered")
    assert restored.recovery_count == 1


def test_factory_registers_real_windows_uia_driver_without_importing_pywinauto():
    catalog = ModelCatalog()
    catalog.register_model(model("model/desktop", 0.85))
    route = AccessRoute(
        route_id="desktop-route",
        model_key="model/desktop",
        transport=TransportKind.DESKTOP_APP,
        auth_mode=AuthMode.USER_SESSION,
        retention_policy=RetentionPolicy.LOCAL_ONLY,
        max_sensitivity=SensitivityLevel.CONFIDENTIAL,
        config={"driver": "windows_uia_chat", "title_re": ".*Chat.*"},
    )
    catalog.register_route(route)
    stack = build_intelligence_stack(catalog, budget=BudgetGatekeeper())
    assert isinstance(stack.desktop_transport.drivers[route.route_id], WindowsUIAChatDriver)


@pytest.mark.asyncio
async def test_council_adjudicates_explicit_disagreement_before_synthesis():
    catalog = three_model_catalog()
    mock = MockTransport()
    mock.outputs["a-api"] = "SUPPORT[database]: Use PostgreSQL"
    mock.outputs["b-api"] = "OPPOSE[database]: Do not use PostgreSQL"
    mock.outputs["c-api"] = "UNCERTAIN[database]: Need workload evidence before deciding"
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        transports=[mock],
    )
    base = TaskProfile(required_capabilities={ModelCapability.REASONING})
    first = stack.router.select(base)
    roles = [
        CouncilRole(role="architect", task_profile=base),
        CouncilRole(
            role="critic",
            task_profile=base,
            require_independent_model_from=first.model_key,
            require_independent_route_from=first.route_id,
        ),
    ]
    requests = {
        role.role: ModelRequest(messages=[ModelMessage(role="user", content="database choice")])
        for role in roles
    }
    bundle = await stack.council_executor.execute_and_synthesize(
        roles=roles,
        requests=requests,
        synthesis_role=CouncilRole(role="synthesizer", task_profile=base),
        resolution_role=CouncilRole(role="resolver", task_profile=base),
    )
    assert len(bundle.disagreement_graph.disagreements) == 1
    assert len(bundle.adjudications) == 1
    assert bundle.adjudications[0].advisory_only is True
    assert bundle.synthesis_result.raw_metadata["council_adjudication_count"] == 1
    assert bundle.synthesis_result.raw_metadata["council_consensus_is_evidence"] is False


class AcceptingVerifier:
    async def verify(self, node, result):
        return MissionVerificationDecision(
            accepted=True,
            evidence_refs=[f"test://verified/{node.node_id}"],
            reason="deterministic test adapter accepted result",
        )


@pytest.mark.asyncio
async def test_end_to_end_cognitive_task_dag_advances_only_through_verifier():
    catalog = three_model_catalog()
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        transports=[MockTransport()],
    )
    runtime = AdaptiveCognitiveMissionRuntime(
        fabric=stack.fabric,
        escalator=stack.escalator,
        council_executor=stack.council_executor,
        verifier=AcceptingVerifier(),
        council_for_complex=False,
    )
    dag_id = uuid4()
    first = TaskNode(
        node_id="design",
        dag_id=dag_id,
        goal="Analyze requirements",
        requirement_refs=["REQ-IF-001"],
        acceptance_criteria=["analysis produced"],
        status=TaskNodeStatus.READY,
    )
    second = TaskNode(
        node_id="review",
        dag_id=dag_id,
        goal="Review the analysis",
        requirement_refs=["REQ-IF-001"],
        dependencies=["design"],
        acceptance_criteria=["review produced"],
        status=TaskNodeStatus.PLANNED,
    )
    dag = TaskDAG(
        dag_id=dag_id,
        project_id=uuid4(),
        contract_id=uuid4(),
        contract_version=1,
        nodes={"design": first, "review": second},
    )
    result = await runtime.run_dag(dag)
    assert result.complete is True
    assert [run.node_id for run in result.runs] == ["design", "review"]
    assert all(run.verification and run.verification.accepted for run in result.runs)
    assert all(run.metadata["external_actions_executed"] is False for run in result.runs)
    assert all(node.status == TaskNodeStatus.SUCCEEDED for node in dag.nodes.values())

class FixedEvaluator:
    def evaluate(self, *, case, result):
        from universal_brain.intelligence import EvaluationVerdict

        return EvaluationVerdict(
            quality_score=0.94,
            success=True,
            evidence_ref=f"test://eval/{case.case_id}",
            capability_scores={ModelCapability.REASONING: 0.96},
        )


@pytest.mark.asyncio
async def test_adaptive_evaluation_harness_feeds_quality_and_capability_evidence():
    from universal_brain.intelligence import EvaluationCase

    catalog = three_model_catalog()
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        transports=[MockTransport()],
    )
    case = EvaluationCase(
        case_id="reasoning-001",
        task_kind="reasoning_eval",
        task_profile=TaskProfile(required_capabilities={ModelCapability.REASONING}),
        request=ModelRequest(messages=[ModelMessage(role="user", content="evaluate reasoning")]),
        expected_model_key="model/a",
    )
    run = await stack.evaluation_harness.run_case(case, FixedEvaluator())
    perf = stack.performance.snapshot("model/a", "reasoning_eval")
    cap = stack.capabilities.snapshot(
        model_key="model/a",
        route_id=run.route_id,
        capability=ModelCapability.REASONING,
        declared_score=0.92,
    )
    assert perf.sample_count == 1
    assert perf.empirical_score > 0.9
    assert cap.sample_count == 1
    assert cap.evidence_refs == ["test://eval/reasoning-001"]


def test_evaluation_driven_routing_prefers_locally_better_model_for_task_kind():
    from universal_brain.intelligence import ModelEvaluationRecord

    catalog = three_model_catalog()
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        transports=[MockTransport()],
    )
    for _ in range(3):
        stack.performance.record(
            ModelEvaluationRecord(
                model_key="model/a",
                route_id="a-api",
                task_kind="specialized_review",
                quality_score=0.20,
                success=True,
                evidence_ref="test://eval/a",
            )
        )
        stack.performance.record(
            ModelEvaluationRecord(
                model_key="model/b",
                route_id="b-api",
                task_kind="specialized_review",
                quality_score=0.99,
                success=True,
                evidence_ref="test://eval/b",
            )
        )
    decision = stack.router.select(
        TaskProfile(
            task_kind="specialized_review",
            required_capabilities={ModelCapability.REASONING},
        )
    )
    assert decision.model_key == "model/b"
    assert decision.selected_score.empirical_score > 0.95


@pytest.mark.asyncio
async def test_a2_cognitive_node_requires_independent_multi_model_council_and_stops_before_action():
    catalog = three_model_catalog()
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=100),
        transports=[MockTransport()],
    )
    runtime = AdaptiveCognitiveMissionRuntime(
        fabric=stack.fabric,
        escalator=stack.escalator,
        council_executor=stack.council_executor,
        verifier=None,
    )
    dag_id = uuid4()
    node = TaskNode(
        node_id="a2-review",
        dag_id=dag_id,
        goal="Review consequential architecture migration",
        description="Analyze architecture risks and propose a reversible plan only",
        requirement_refs=["REQ-IF-002"],
        action_class=ActionClass.A2,
        tool_scope=["deploy"],
        acceptance_criteria=["risks and proposal documented"],
        status=TaskNodeStatus.READY,
    )
    run = await runtime.execute_node(node, project_id=uuid4())
    assert run.mode.value == "council"
    assert run.council is not None
    member_models = {result.model_key for result in run.council.member_results.values()}
    assert len(member_models) == 2
    assert run.council.synthesis_result.model_key not in member_models
    assert run.status_after == TaskNodeStatus.VERIFYING
    assert run.metadata["external_actions_executed"] is False
    assert run.metadata["consensus_is_evidence"] is False


def test_playwright_driver_enforces_explicit_attachment_roots(tmp_path):
    from universal_brain.intelligence.transports.playwright_driver import PlaywrightChatUIDriver
    from universal_brain.intelligence.transports.base import TransportOutageError

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    inside = allowed / "context.txt"
    inside.write_text("context", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    route = AccessRoute(
        route_id="browser-upload",
        model_key="model/a",
        transport=TransportKind.BROWSER,
        auth_mode=AuthMode.USER_SESSION,
        retention_policy=RetentionPolicy.PROVIDER_DEFAULT,
        max_sensitivity=SensitivityLevel.INTERNAL,
        config={"allowed_upload_roots": [str(allowed)]},
    )
    driver = PlaywrightChatUIDriver()
    ok = ModelRequest(
        messages=[ModelMessage(role="user", content="read attachment")],
        metadata={"attachment_paths": [str(inside)]},
    )
    assert driver._validate_attachments(route, ok) == [str(inside.resolve())]
    bad = ok.model_copy(update={"metadata": {"attachment_paths": [str(outside)]}})
    with pytest.raises(TransportOutageError):
        driver._validate_attachments(route, bad)
