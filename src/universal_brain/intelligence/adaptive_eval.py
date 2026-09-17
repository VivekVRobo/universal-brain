from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, Field

from .capabilities import CapabilityEvidenceSource
from .evaluations import ModelEvaluationRecord
from .schemas import ModelCapability, ModelRequest, NormalizedModelResult, TaskProfile


class EvaluationVerdict(BaseModel):
    quality_score: float = Field(ge=0, le=1)
    success: bool = True
    evidence_ref: str | None = None
    capability_scores: dict[ModelCapability, float] = Field(default_factory=dict)
    notes: str | None = None


class DeterministicEvaluationAdapter(Protocol):
    def evaluate(
        self,
        *,
        case: "EvaluationCase",
        result: NormalizedModelResult,
    ) -> EvaluationVerdict: ...


class EvaluationCase(BaseModel):
    case_id: str
    task_kind: str
    task_profile: TaskProfile
    request: ModelRequest
    expected_route_id: str | None = None
    expected_model_key: str | None = None
    metadata: dict = Field(default_factory=dict)


class EvaluationRun(BaseModel):
    case_id: str
    model_key: str
    route_id: str
    verdict: EvaluationVerdict
    result_id: str
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AdaptiveEvaluationHarness:
    """Run deterministic local evaluations and feed empirical routing evidence.

    The evaluator is code/operator supplied; the tested model is never allowed to
    grade itself. Result content is not persisted by the ledger, only the score and
    evidence reference.
    """

    def __init__(self, *, fabric, performance_ledger, capability_registry=None) -> None:
        self.fabric = fabric
        self.performance_ledger = performance_ledger
        self.capability_registry = capability_registry

    async def _verdict(self, evaluator, case, result) -> EvaluationVerdict:
        verdict = evaluator.evaluate(case=case, result=result)
        if inspect.isawaitable(verdict):
            verdict = await verdict
        return (
            verdict
            if isinstance(verdict, EvaluationVerdict)
            else EvaluationVerdict.model_validate(verdict)
        )

    async def run_case(self, case: EvaluationCase, evaluator: DeterministicEvaluationAdapter):
        task = case.task_profile.model_copy(update={"task_kind": case.task_kind})
        decision = self.fabric.router.select(task)
        if case.expected_route_id or case.expected_model_key:
            candidates = [decision.selected_score, *decision.alternatives]
            candidate = next(
                (
                    item
                    for item in candidates
                    if (case.expected_route_id is None or item.route_id == case.expected_route_id)
                    and (case.expected_model_key is None or item.model_key == case.expected_model_key)
                ),
                None,
            )
            if candidate is None:
                raise ValueError(
                    f"Evaluation case {case.case_id!r} requested an ineligible model/route"
                )
            decision = self.fabric._decision_for_candidate(decision, candidate)
        result = await self.fabric.invoke_decision(decision, case.request, task)
        verdict = await self._verdict(evaluator, case, result)
        self.performance_ledger.record(
            ModelEvaluationRecord(
                model_key=result.model_key,
                route_id=result.route_id,
                task_kind=case.task_kind,
                quality_score=verdict.quality_score,
                success=verdict.success,
                cost_usd=result.usage.cost_usd,
                evidence_ref=verdict.evidence_ref,
            )
        )
        if self.capability_registry is not None:
            for capability, score in verdict.capability_scores.items():
                self.capability_registry.record_score(
                    model_key=result.model_key,
                    route_id=result.route_id,
                    capability=capability,
                    score=score,
                    source=CapabilityEvidenceSource.EVALUATION,
                    evidence_ref=verdict.evidence_ref,
                    notes=f"evaluation_case={case.case_id}",
                )
        return EvaluationRun(
            case_id=case.case_id,
            model_key=result.model_key,
            route_id=result.route_id,
            verdict=verdict,
            result_id=str(result.result_id),
        )

    async def run_suite(
        self,
        cases: list[EvaluationCase],
        evaluator: DeterministicEvaluationAdapter,
    ) -> list[EvaluationRun]:
        runs = []
        for case in cases:
            runs.append(await self.run_case(case, evaluator))
        return runs
