from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from .context import ContextCompiler
from .profiling import DeterministicTaskProfiler, TaskAnalysis
from .schemas import (
    CandidateScore,
    FabricRoutingDecision,
    ModelRequest,
    ModelStreamEvent,
    StreamEventType,
    TaskProfile,
)
from .transports.base import StreamInterruptedError, TransportError


class IntelligenceFabricExhausted(TransportError):
    def __init__(self, failures):
        self.failures = failures
        super().__init__(
            "All eligible routes failed: "
            + "; ".join(f"{route}: {error}" for route, error in failures)
        )


class IntelligenceFabric:
    def __init__(
        self,
        router,
        runtime,
        conversation_registry=None,
        *,
        context_compiler: ContextCompiler | None = None,
        context_sources=(),
        profiler: DeterministicTaskProfiler | None = None,
    ):
        self.router = router
        self.runtime = runtime
        from .sessions import ConversationRegistry

        self.conversations = conversation_registry or ConversationRegistry()
        self.context_compiler = context_compiler or ContextCompiler()
        self.context_sources = list(context_sources)
        self.profiler = profiler or DeterministicTaskProfiler()

    @staticmethod
    def _decision_for_candidate(base, candidate: CandidateScore):
        return FabricRoutingDecision(
            model_key=candidate.model_key,
            route_id=candidate.route_id,
            selected_score=candidate,
            alternatives=[
                item
                for item in [base.selected_score, *base.alternatives]
                if item.route_id != candidate.route_id
            ],
            rejected=base.rejected,
        )

    def _scope(self, request: ModelRequest):
        project_id = request.metadata.get("project_id")
        role = request.metadata.get("cognitive_role") or request.metadata.get("role")
        if not project_id or not role:
            return None, None
        try:
            project_id = (
                project_id if isinstance(project_id, UUID) else UUID(str(project_id))
            )
        except (ValueError, TypeError):
            return None, None
        return project_id, str(role)

    @staticmethod
    def _annotate_request(request: ModelRequest, task: TaskProfile) -> ModelRequest:
        metadata = dict(request.metadata)
        metadata.setdefault("task_kind", task.task_kind)
        metadata.setdefault("action_class", task.action_class.value)
        metadata.setdefault("sensitivity", task.sensitivity.value)
        metadata.setdefault("task_complexity", task.complexity.value)
        metadata.setdefault(
            "required_capabilities",
            sorted(capability.value for capability in task.required_capabilities),
        )
        return request.model_copy(update={"metadata": metadata})

    def _with_continuity(self, request: ModelRequest, decision):
        project_id, role = self._scope(request)
        if (
            not project_id
            or not role
            or request.metadata.get("conversation_ref")
        ):
            return request
        binding = self.conversations.find(
            project_id, role, decision.model_key, decision.route_id
        )
        if not binding:
            return request
        metadata = dict(request.metadata)
        metadata["conversation_ref"] = binding.conversation_ref
        metadata["conversation_context_version"] = binding.context_version
        return request.model_copy(update={"metadata": metadata})

    def _with_context(
        self,
        request: ModelRequest,
        decision: FabricRoutingDecision,
        task: TaskProfile | None,
    ) -> ModelRequest:
        if task is None or not self.context_sources:
            return request
        if request.metadata.get("disable_context_retrieval"):
            return request
        model = self.runtime.catalog.require_model(decision.model_key)
        route = self.runtime.catalog.require_route(decision.route_id)
        return self.context_compiler.compile_task(
            request=request,
            task=task,
            route=route,
            model_context_window=model.context_window,
            sources=self.context_sources,
            max_chunks_per_source=int(
                request.metadata.get("max_context_chunks_per_source", 12) or 12
            ),
        )

    def _record(self, request: ModelRequest, result):
        if not result.conversation_ref:
            return
        project_id, role = self._scope(request)
        if project_id and role:
            self.conversations.upsert(
                project_id=project_id,
                role=role,
                model_key=result.model_key,
                route_id=result.route_id,
                conversation_ref=result.conversation_ref,
                last_task_id=request.task_id,
            )

    async def invoke_decision(
        self,
        decision: FabricRoutingDecision,
        request: ModelRequest,
        task: TaskProfile | None = None,
    ):
        prepared = self._annotate_request(request, task) if task else request
        prepared = self._with_continuity(prepared, decision)
        prepared = self._with_context(prepared, decision, task)
        result = await self.runtime.invoke(decision, prepared)
        self._record(prepared, result)
        return result

    async def invoke(self, task: TaskProfile, request: ModelRequest):
        request = self._annotate_request(request, task)
        initial = self.router.select(task)
        failures = []
        for candidate in [initial.selected_score, *initial.alternatives]:
            try:
                result = await self.invoke_decision(
                    self._decision_for_candidate(initial, candidate), request, task
                )
                result.raw_metadata["routing_decision_id"] = str(initial.decision_id)
                result.raw_metadata["failed_routes_before_success"] = [
                    {"route_id": route_id, "error": error}
                    for route_id, error in failures
                ]
                return result
            except TransportError as exc:
                failures.append((candidate.route_id, str(exc)))
        raise IntelligenceFabricExhausted(failures)

    async def invoke_auto(
        self,
        request: ModelRequest,
        base_task: TaskProfile | None = None,
    ):
        analysis = self.profiler.profile(request, base=base_task)
        result = await self.invoke(analysis.profile, request)
        result.raw_metadata["task_profile_analysis"] = analysis.model_dump(mode="json")
        return result

    def analyze_task(
        self,
        request: ModelRequest,
        base_task: TaskProfile | None = None,
    ) -> TaskAnalysis:
        return self.profiler.profile(request, base=base_task)

    async def stream(
        self,
        task: TaskProfile,
        request: ModelRequest,
    ) -> AsyncIterator[ModelStreamEvent]:
        """Stream across routes with failover only before substantive output.

        Once any text/tool-call/usage payload has escaped a route, automatic route
        switching is prohibited because it could duplicate or contradict already
        emitted content. The caller receives StreamInterruptedError instead.
        """
        request = self._annotate_request(request, task)
        initial = self.router.select(task)
        failures: list[tuple[str, str]] = []
        for candidate in [initial.selected_score, *initial.alternatives]:
            decision = self._decision_for_candidate(initial, candidate)
            prepared = self._with_continuity(request, decision)
            prepared = self._with_context(prepared, decision, task)
            substantive_output = False
            final_result = None
            try:
                async for event in self.runtime.stream(decision, prepared):
                    if event.event_type in {
                        StreamEventType.TEXT_DELTA,
                        StreamEventType.TOOL_CALL,
                        StreamEventType.USAGE,
                    }:
                        substantive_output = True
                    if event.final_result is not None:
                        final_result = event.final_result
                        final_result.raw_metadata["routing_decision_id"] = str(
                            initial.decision_id
                        )
                        final_result.raw_metadata["failed_routes_before_success"] = [
                            {"route_id": route_id, "error": error}
                            for route_id, error in failures
                        ]
                    yield event
                if final_result is not None:
                    self._record(prepared, final_result)
                return
            except TransportError as exc:
                if substantive_output:
                    raise StreamInterruptedError(
                        f"Stream from {candidate.route_id} failed after output began: {exc}"
                    ) from exc
                failures.append((candidate.route_id, str(exc)))
                continue
        raise IntelligenceFabricExhausted(failures)
