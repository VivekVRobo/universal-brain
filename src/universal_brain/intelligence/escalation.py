from __future__ import annotations

from enum import Enum
from typing import Optional, Set

from pydantic import BaseModel, Field, model_validator

from .fabric import IntelligenceFabricExhausted
from .schemas import TaskProfile, TransportKind
from .transports.base import TransportError


class ResultAssessment(BaseModel):
    accepted: bool
    score: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class DeterministicResultAssessor:
    def assess(self, task, request, result) -> ResultAssessment:
        reasons: list[str] = []
        if not (result.output_text.strip() or result.structured_output or result.tool_calls):
            reasons.append("empty_result")
        min_chars = int(request.metadata.get("min_output_chars", 0) or 0)
        if min_chars and len(result.output_text.strip()) < min_chars:
            reasons.append(f"output_shorter_than_{min_chars}")
        if (task.require_structured_output or request.response_schema) and result.structured_output is None:
            reasons.append("structured_output_required")
        required_keys = request.metadata.get("required_structured_keys") or []
        if required_keys and isinstance(result.structured_output, dict):
            missing = [key for key in required_keys if key not in result.structured_output]
            if missing:
                reasons.append("missing_structured_keys:" + ",".join(sorted(map(str, missing))))
        score = 1.0 if not reasons else max(0.0, 1.0 - len(reasons) / 3)
        return ResultAssessment(accepted=not reasons, score=score, reasons=reasons)


class EscalationOutcome(str, Enum):
    ACCEPTED = "accepted"
    QUALITY_REJECTED = "quality_rejected"
    TRANSPORT_FAILED = "transport_failed"
    NO_ROUTE = "no_route"


class EscalationStage(BaseModel):
    stage_id: str
    max_candidates: int = Field(default=4, ge=1)
    allowed_transports: Optional[Set[TransportKind]] = None
    max_input_cost_per_million: Optional[float] = Field(default=None, ge=0)
    max_output_cost_per_million: Optional[float] = Field(default=None, ge=0)
    minimum_total_score: float = Field(default=0.0, ge=0, le=1)
    distinct_models_within_stage: bool = False


class EscalationTransition(BaseModel):
    from_stage: str
    outcomes: Set[EscalationOutcome]
    to_stage: str


class EscalationPolicyGraph(BaseModel):
    entry_stage: str
    stages: dict[str, EscalationStage]
    transitions: list[EscalationTransition] = Field(default_factory=list)
    max_stage_hops: int = Field(default=8, ge=1)

    @model_validator(mode="after")
    def validate_graph(self):
        if self.entry_stage not in self.stages:
            raise ValueError("entry_stage missing from stages")
        for key, stage in self.stages.items():
            if stage.stage_id != key:
                raise ValueError(f"stage key {key!r} does not match stage_id {stage.stage_id!r}")
        for transition in self.transitions:
            if transition.from_stage not in self.stages or transition.to_stage not in self.stages:
                raise ValueError("transition references unknown stage")
        return self

    @classmethod
    def all_eligible(cls, max_candidates: int = 4) -> "EscalationPolicyGraph":
        stage = EscalationStage(stage_id="eligible", max_candidates=max_candidates)
        return cls(entry_stage=stage.stage_id, stages={stage.stage_id: stage})

    @classmethod
    def economy_then_frontier(
        cls,
        *,
        economy_input_ceiling: float = 2.0,
        economy_output_ceiling: float = 5.0,
        candidates_per_stage: int = 2,
    ) -> "EscalationPolicyGraph":
        economy = EscalationStage(
            stage_id="economy",
            max_candidates=candidates_per_stage,
            max_input_cost_per_million=economy_input_ceiling,
            max_output_cost_per_million=economy_output_ceiling,
        )
        frontier = EscalationStage(
            stage_id="frontier",
            max_candidates=max(2, candidates_per_stage),
        )
        return cls(
            entry_stage="economy",
            stages={"economy": economy, "frontier": frontier},
            transitions=[
                EscalationTransition(
                    from_stage="economy",
                    outcomes={
                        EscalationOutcome.QUALITY_REJECTED,
                        EscalationOutcome.TRANSPORT_FAILED,
                        EscalationOutcome.NO_ROUTE,
                    },
                    to_stage="frontier",
                )
            ],
        )

    def next_stage(self, current: str, outcome: EscalationOutcome) -> str | None:
        for transition in self.transitions:
            if transition.from_stage == current and outcome in transition.outcomes:
                return transition.to_stage
        return None


class IntelligenceEscalator:
    def __init__(self, fabric, assessor=None, policy: EscalationPolicyGraph | None = None):
        self.fabric = fabric
        self.assessor = assessor or DeterministicResultAssessor()
        self.policy = policy

    @staticmethod
    def _stage_task(task: TaskProfile, stage: EscalationStage) -> TaskProfile:
        allowed = task.allowed_transports
        if stage.allowed_transports is not None:
            allowed = (
                set(stage.allowed_transports)
                if allowed is None
                else set(allowed) & set(stage.allowed_transports)
            )
        max_input = task.max_input_cost_per_million
        if stage.max_input_cost_per_million is not None:
            max_input = (
                stage.max_input_cost_per_million
                if max_input is None
                else min(max_input, stage.max_input_cost_per_million)
            )
        max_output = task.max_output_cost_per_million
        if stage.max_output_cost_per_million is not None:
            max_output = (
                stage.max_output_cost_per_million
                if max_output is None
                else min(max_output, stage.max_output_cost_per_million)
            )
        return task.model_copy(
            update={
                "allowed_transports": allowed,
                "max_input_cost_per_million": max_input,
                "max_output_cost_per_million": max_output,
            }
        )

    async def _legacy_invoke(self, task, request, max_attempts, never_repeat_model):
        decision = self.fabric.router.select(task)
        attempts: list[dict] = []
        seen_models: set[str] = set()
        for candidate in [decision.selected_score, *decision.alternatives]:
            if len(attempts) >= max_attempts:
                break
            if never_repeat_model and candidate.model_key in seen_models:
                continue
            seen_models.add(candidate.model_key)
            try:
                result = await self.fabric.invoke_decision(
                    self.fabric._decision_for_candidate(decision, candidate), request, task
                )
            except TransportError as exc:
                attempts.append(
                    {
                        "route_id": candidate.route_id,
                        "model_key": candidate.model_key,
                        "status": EscalationOutcome.TRANSPORT_FAILED.value,
                        "error": str(exc),
                    }
                )
                continue
            assessment = self.assessor.assess(task, request, result)
            attempts.append(
                {
                    "route_id": candidate.route_id,
                    "model_key": candidate.model_key,
                    "status": (
                        EscalationOutcome.ACCEPTED.value
                        if assessment.accepted
                        else EscalationOutcome.QUALITY_REJECTED.value
                    ),
                    "assessment": assessment.model_dump(),
                }
            )
            if assessment.accepted:
                result.raw_metadata["intelligence_escalation"] = attempts
                return result
        raise IntelligenceFabricExhausted(
            [
                (attempt["route_id"], attempt.get("error") or str(attempt.get("assessment")))
                for attempt in attempts
            ]
        )

    async def invoke(
        self,
        task,
        request,
        max_attempts: int = 4,
        never_repeat_model: bool = False,
        policy: EscalationPolicyGraph | None = None,
    ):
        graph = policy or self.policy
        if graph is None:
            return await self._legacy_invoke(task, request, max_attempts, never_repeat_model)

        attempts: list[dict] = []
        seen_routes: set[str] = set()
        seen_models: set[str] = set()
        stage_id = graph.entry_stage
        stage_hops = 0
        while stage_id is not None and stage_hops < graph.max_stage_hops:
            if len(attempts) >= max_attempts:
                break
            stage_hops += 1
            stage = graph.stages[stage_id]
            stage_task = self._stage_task(task, stage)
            try:
                decision = self.fabric.router.select(stage_task)
            except Exception as exc:
                attempts.append(
                    {
                        "stage": stage_id,
                        "status": EscalationOutcome.NO_ROUTE.value,
                        "error": str(exc),
                    }
                )
                stage_id = graph.next_stage(stage_id, EscalationOutcome.NO_ROUTE)
                continue

            candidates = [decision.selected_score, *decision.alternatives]
            candidates = [
                candidate
                for candidate in candidates
                if candidate.route_id not in seen_routes
                and candidate.total_score >= stage.minimum_total_score
            ]
            stage_outcome = EscalationOutcome.NO_ROUTE
            stage_models: set[str] = set()
            for candidate in candidates[: stage.max_candidates]:
                if len(attempts) >= max_attempts:
                    break
                if never_repeat_model and candidate.model_key in seen_models:
                    continue
                if stage.distinct_models_within_stage and candidate.model_key in stage_models:
                    continue
                seen_routes.add(candidate.route_id)
                seen_models.add(candidate.model_key)
                stage_models.add(candidate.model_key)
                try:
                    result = await self.fabric.invoke_decision(
                        self.fabric._decision_for_candidate(decision, candidate), request, stage_task
                    )
                except TransportError as exc:
                    stage_outcome = EscalationOutcome.TRANSPORT_FAILED
                    attempts.append(
                        {
                            "stage": stage_id,
                            "route_id": candidate.route_id,
                            "model_key": candidate.model_key,
                            "status": stage_outcome.value,
                            "error": str(exc),
                        }
                    )
                    continue

                assessment = self.assessor.assess(stage_task, request, result)
                stage_outcome = (
                    EscalationOutcome.ACCEPTED
                    if assessment.accepted
                    else EscalationOutcome.QUALITY_REJECTED
                )
                attempts.append(
                    {
                        "stage": stage_id,
                        "route_id": candidate.route_id,
                        "model_key": candidate.model_key,
                        "status": stage_outcome.value,
                        "assessment": assessment.model_dump(),
                    }
                )
                if assessment.accepted:
                    result.raw_metadata["intelligence_escalation"] = attempts
                    result.raw_metadata["escalation_policy_entry"] = graph.entry_stage
                    return result

            stage_id = graph.next_stage(stage_id, stage_outcome)

        raise IntelligenceFabricExhausted(
            [
                (
                    attempt.get("route_id") or f"stage:{attempt.get('stage', 'unknown')}",
                    attempt.get("error") or str(attempt.get("assessment")),
                )
                for attempt in attempts
            ]
        )
