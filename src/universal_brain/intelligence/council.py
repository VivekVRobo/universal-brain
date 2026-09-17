from __future__ import annotations

import asyncio
import hashlib
import json
import re
from enum import Enum
from typing import Optional, Set

from pydantic import BaseModel, Field

from universal_brain.kernel.errors import CapabilityDeniedError

from .schemas import (
    FabricRoutingDecision,
    ModelMessage,
    ModelRequest,
    NormalizedModelResult,
    TaskProfile,
)


class CouncilRole(BaseModel):
    role: str
    task_profile: TaskProfile
    require_independent_model_from: Optional[str] = None
    require_independent_route_from: Optional[str] = None
    require_independent_models_from: Set[str] = Field(default_factory=set)
    require_independent_routes_from: Set[str] = Field(default_factory=set)


class CouncilAssignment(BaseModel):
    assignments: dict[str, FabricRoutingDecision] = Field(default_factory=dict)


class ClaimStance(str, Enum):
    SUPPORT = "support"
    OPPOSE = "oppose"
    UNCERTAIN = "uncertain"


class CouncilClaim(BaseModel):
    claim_id: str
    role: str
    topic: str
    text: str
    stance: ClaimStance = ClaimStance.SUPPORT


class CouncilDisagreementEdge(BaseModel):
    topic: str
    left_role: str
    right_role: str
    left_stance: ClaimStance
    right_stance: ClaimStance
    reason: str = "explicit_stance_conflict"


class CouncilDisagreementGraph(BaseModel):
    claims: list[CouncilClaim] = Field(default_factory=list)
    disagreements: list[CouncilDisagreementEdge] = Field(default_factory=list)
    exact_agreement_clusters: dict[str, list[str]] = Field(default_factory=dict)
    consensus_is_evidence: bool = False


class CouncilAdjudication(BaseModel):
    topic: str
    left_role: str
    right_role: str
    result: NormalizedModelResult
    advisory_only: bool = True
    consensus_is_evidence: bool = False


class CouncilSynthesisResult(BaseModel):
    member_results: dict[str, NormalizedModelResult]
    disagreement_graph: CouncilDisagreementGraph
    adjudications: list[CouncilAdjudication] = Field(default_factory=list)
    synthesis_result: NormalizedModelResult


class ModelCouncilPlanner:
    def __init__(self, router):
        self.router = router

    def assign(self, roles):
        output = {}
        for role in roles:
            decision = self.router.select(role.task_profile)
            forbidden_models = set(role.require_independent_models_from)
            forbidden_routes = set(role.require_independent_routes_from)
            if role.require_independent_model_from:
                forbidden_models.add(role.require_independent_model_from)
            if role.require_independent_route_from:
                forbidden_routes.add(role.require_independent_route_from)

            if decision.model_key in forbidden_models or decision.route_id in forbidden_routes:
                alternatives = [
                    candidate
                    for candidate in decision.alternatives
                    if candidate.model_key not in forbidden_models
                    and candidate.route_id not in forbidden_routes
                ]
                if not alternatives:
                    raise CapabilityDeniedError(f"No independent route for {role.role}")
                selected = alternatives[0]
                decision = FabricRoutingDecision(
                    model_key=selected.model_key,
                    route_id=selected.route_id,
                    selected_score=selected,
                    alternatives=[
                        candidate
                        for candidate in decision.alternatives
                        if candidate.route_id != selected.route_id
                    ],
                    rejected=decision.rejected,
                )
            output[role.role] = decision
        return CouncilAssignment(assignments=output)


class CouncilDisagreementAnalyzer:
    LINE_PATTERN = re.compile(
        r"^(CLAIM|SUPPORT|OPPOSE|DISAGREE|UNCERTAIN)(?:\[([^\]]+)\])?\s*:\s*(.+)$",
        re.IGNORECASE,
    )

    @staticmethod
    def _normalize_topic(value: str) -> str:
        compact = " ".join(value.lower().split())
        compact = re.sub(r"[^a-z0-9 _.-]", "", compact)
        return compact[:120] or "unspecified"

    @staticmethod
    def _stance(value: object) -> ClaimStance:
        text = str(value or "support").strip().lower()
        if text in {"oppose", "opposed", "disagree", "against", "false"}:
            return ClaimStance.OPPOSE
        if text in {"uncertain", "unknown", "mixed", "unsure"}:
            return ClaimStance.UNCERTAIN
        return ClaimStance.SUPPORT

    def _claim(self, role: str, topic: str, text: str, stance: ClaimStance) -> CouncilClaim:
        material = f"{role}\n{topic}\n{stance.value}\n{text}".encode("utf-8")
        return CouncilClaim(
            claim_id=hashlib.sha256(material).hexdigest()[:16],
            role=role,
            topic=self._normalize_topic(topic),
            text=" ".join(text.split()),
            stance=stance,
        )

    def extract_claims(self, role: str, result: NormalizedModelResult) -> list[CouncilClaim]:
        structured = result.structured_output or {}
        raw_claims = structured.get("claims") if isinstance(structured, dict) else None
        claims: list[CouncilClaim] = []
        if isinstance(raw_claims, list):
            for item in raw_claims:
                if isinstance(item, str):
                    claims.append(
                        self._claim(role, item, item, ClaimStance.SUPPORT)
                    )
                elif isinstance(item, dict):
                    text = str(item.get("claim") or item.get("text") or "").strip()
                    if not text:
                        continue
                    topic = str(item.get("topic") or text)
                    claims.append(
                        self._claim(role, topic, text, self._stance(item.get("stance")))
                    )
        if claims:
            return claims

        for line in result.output_text.splitlines():
            match = self.LINE_PATTERN.match(line.strip())
            if not match:
                continue
            marker, topic, text = match.groups()
            stance = self._stance(marker)
            if marker.lower() == "disagree":
                stance = ClaimStance.OPPOSE
            claims.append(self._claim(role, topic or text, text, stance))
        return claims

    def analyze(self, results: dict[str, NormalizedModelResult]) -> CouncilDisagreementGraph:
        claims = [
            claim
            for role, result in results.items()
            for claim in self.extract_claims(role, result)
        ]
        by_topic: dict[str, list[CouncilClaim]] = {}
        by_text: dict[str, set[str]] = {}
        for claim in claims:
            by_topic.setdefault(claim.topic, []).append(claim)
            normalized_text = self._normalize_topic(claim.text)
            by_text.setdefault(normalized_text, set()).add(claim.role)

        disagreements: list[CouncilDisagreementEdge] = []
        seen_edges: set[tuple[str, str, str]] = set()
        for topic, topic_claims in by_topic.items():
            for index, left in enumerate(topic_claims):
                for right in topic_claims[index + 1 :]:
                    if left.role == right.role:
                        continue
                    stances = {left.stance, right.stance}
                    if ClaimStance.SUPPORT not in stances or ClaimStance.OPPOSE not in stances:
                        continue
                    key = (topic, *sorted([left.role, right.role]))
                    if key in seen_edges:
                        continue
                    seen_edges.add(key)
                    disagreements.append(
                        CouncilDisagreementEdge(
                            topic=topic,
                            left_role=left.role,
                            right_role=right.role,
                            left_stance=left.stance,
                            right_stance=right.stance,
                        )
                    )

        exact_agreements = {
            text: sorted(roles)
            for text, roles in by_text.items()
            if len(roles) >= 2 and text != "unspecified"
        }
        return CouncilDisagreementGraph(
            claims=claims,
            disagreements=disagreements,
            exact_agreement_clusters=exact_agreements,
            consensus_is_evidence=False,
        )


class ModelCouncilExecutor:
    def __init__(self, planner, fabric, analyzer=None):
        self.planner = planner
        self.fabric = fabric
        self.analyzer = analyzer or CouncilDisagreementAnalyzer()

    async def execute(self, roles, requests, parallel=True):
        assignment = self.planner.assign(roles)

        async def run(role):
            request = requests[role.role]
            metadata = dict(request.metadata)
            metadata.setdefault("cognitive_role", role.role)
            metadata.setdefault("task_kind", role.task_profile.task_kind)
            request = request.model_copy(update={"metadata": metadata})
            result = await self.fabric.invoke_decision(
                assignment.assignments[role.role], request, role.task_profile
            )
            result.raw_metadata["council_role"] = role.role
            result.raw_metadata["council_consensus_is_evidence"] = False
            return role.role, result

        if parallel:
            items = await asyncio.gather(*(run(role) for role in roles))
        else:
            items = [await run(role) for role in roles]
        return dict(items)

    @staticmethod
    def synthesis_request(results, disagreement_graph=None, adjudications=None):
        payload = {
            "member_outputs": {
                role: {
                    "output_text": result.output_text,
                    "structured_output": result.structured_output,
                    "model_key": result.model_key,
                    "route_id": result.route_id,
                }
                for role, result in results.items()
            },
            "disagreement_graph": (
                disagreement_graph.model_dump(mode="json")
                if disagreement_graph is not None
                else None
            ),
            "advisory_adjudications": [
                {
                    "topic": item.topic,
                    "left_role": item.left_role,
                    "right_role": item.right_role,
                    "output_text": item.result.output_text,
                    "structured_output": item.result.structured_output,
                    "model_key": item.result.model_key,
                    "route_id": item.result.route_id,
                    "advisory_only": True,
                }
                for item in (adjudications or [])
            ],
        }
        return ModelRequest(
            messages=[
                ModelMessage(
                    role="system",
                    content=(
                        "Synthesize independent proposals. Model agreement is not verification evidence. "
                        "Preserve explicit disagreements, uncertainty, and evidence gaps. Do not silently "
                        "collapse conflicting claims."
                    ),
                ),
                ModelMessage(role="user", content=json.dumps(payload, sort_keys=True)),
            ],
            metadata={
                "cognitive_role": "synthesizer",
                "task_kind": "council_synthesis",
                "council_consensus_is_evidence": False,
            },
        )

    @staticmethod
    def _claims_for_edge(graph, edge):
        return [
            claim
            for claim in graph.claims
            if claim.topic == edge.topic
            and claim.role in {edge.left_role, edge.right_role}
        ]

    @classmethod
    def adjudication_request(cls, graph, edge):
        claims = cls._claims_for_edge(graph, edge)
        payload = {
            "topic": edge.topic,
            "claims": [claim.model_dump(mode="json") for claim in claims],
        }
        return ModelRequest(
            messages=[
                ModelMessage(
                    role="system",
                    content=(
                        "Act as an independent disagreement resolver. Compare the conflicting "
                        "claims, identify what evidence would resolve them, and state whether the "
                        "available material is sufficient. Your judgment is advisory and is NOT "
                        "verification evidence. Preserve uncertainty when evidence is missing."
                    ),
                ),
                ModelMessage(role="user", content=json.dumps(payload, sort_keys=True)),
            ],
            metadata={
                "cognitive_role": "disagreement_resolver",
                "task_kind": "council_disagreement_resolution",
                "council_consensus_is_evidence": False,
            },
        )

    async def adjudicate_disagreements(
        self,
        *,
        member_results,
        disagreement_graph,
        resolution_role: CouncilRole,
        parallel: bool = True,
    ) -> list[CouncilAdjudication]:
        async def resolve(edge):
            involved = [member_results[edge.left_role], member_results[edge.right_role]]
            role = resolution_role.model_copy(
                update={
                    "require_independent_models_from": set(
                        resolution_role.require_independent_models_from
                    )
                    | {item.model_key for item in involved},
                    "require_independent_routes_from": set(
                        resolution_role.require_independent_routes_from
                    )
                    | {item.route_id for item in involved},
                }
            )
            decision = self.planner.assign([role]).assignments[role.role]
            request = self.adjudication_request(disagreement_graph, edge)
            result = await self.fabric.invoke_decision(decision, request, role.task_profile)
            result.raw_metadata.update(
                {
                    "council_role": role.role,
                    "council_adjudication_topic": edge.topic,
                    "council_consensus_is_evidence": False,
                    "advisory_only": True,
                }
            )
            return CouncilAdjudication(
                topic=edge.topic,
                left_role=edge.left_role,
                right_role=edge.right_role,
                result=result,
            )

        edges = disagreement_graph.disagreements
        if not edges:
            return []
        if parallel:
            return list(await asyncio.gather(*(resolve(edge) for edge in edges)))
        return [await resolve(edge) for edge in edges]

    async def execute_and_synthesize(
        self,
        *,
        roles,
        requests,
        synthesis_role: CouncilRole,
        resolution_role: CouncilRole | None = None,
        parallel: bool = True,
    ) -> CouncilSynthesisResult:
        member_results = await self.execute(roles, requests, parallel=parallel)
        graph = self.analyzer.analyze(member_results)
        adjudications = (
            await self.adjudicate_disagreements(
                member_results=member_results,
                disagreement_graph=graph,
                resolution_role=resolution_role,
                parallel=parallel,
            )
            if resolution_role is not None and graph.disagreements
            else []
        )
        used_models = {result.model_key for result in member_results.values()}
        used_routes = {result.route_id for result in member_results.values()}
        synthesis_role = synthesis_role.model_copy(
            update={
                "require_independent_models_from": set(synthesis_role.require_independent_models_from)
                | used_models,
                "require_independent_routes_from": set(synthesis_role.require_independent_routes_from)
                | used_routes,
            }
        )
        decision = self.planner.assign([synthesis_role]).assignments[synthesis_role.role]
        request = self.synthesis_request(member_results, graph, adjudications)
        synthesis = await self.fabric.invoke_decision(decision, request, synthesis_role.task_profile)
        synthesis.raw_metadata.update(
            {
                "council_role": synthesis_role.role,
                "council_consensus_is_evidence": False,
                "council_disagreement_count": len(graph.disagreements),
                "council_member_count": len(member_results),
                "council_adjudication_count": len(adjudications),
            }
        )
        return CouncilSynthesisResult(
            member_results=member_results,
            disagreement_graph=graph,
            adjudications=adjudications,
            synthesis_result=synthesis,
        )
