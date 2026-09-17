"""Project-level Definition-of-Done auditing.

Traceability: REQ-ENG-010, REQ-VER-001..004, ALN-010, ALN-020.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from universal_brain.alignment.contract import AlignmentContract
from universal_brain.executive.schemas import TaskDAG, TaskNodeStatus

from .schemas import EngineeringNodeRun


class ProjectCompletionReport(BaseModel):
    accepted: bool
    missing_requirements: list[str] = Field(default_factory=list)
    incomplete_nodes: list[str] = Field(default_factory=list)
    nodes_without_verification: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ProjectCompletionAuditor:
    """Fail-closed project completion gate; no model confidence is consulted."""

    def audit(self, contract: AlignmentContract, dag: TaskDAG, runs: list[EngineeringNodeRun]) -> ProjectCompletionReport:
        active_requirements = {item.requirement_id for item in contract.requirements}
        covered = {ref for node in dag.nodes.values() for ref in node.requirement_refs}
        missing = sorted(active_requirements - covered)
        incomplete = sorted(
            node.node_id for node in dag.nodes.values() if node.status != TaskNodeStatus.SUCCEEDED
        )
        run_by_node = {run.node_id: run for run in runs}
        no_verification: list[str] = []
        evidence_refs: list[str] = []
        for node in dag.nodes.values():
            run = run_by_node.get(node.node_id)
            if node.status == TaskNodeStatus.SUCCEEDED:
                if run is None or not run.verification_checks:
                    no_verification.append(node.node_id)
                elif not all(check.passed for check in run.verification_checks):
                    no_verification.append(node.node_id)
                else:
                    evidence_refs.extend(
                        check.evidence_ref for check in run.verification_checks if check.evidence_ref
                    )
        reasons: list[str] = []
        if missing:
            reasons.append("active requirements are not represented in the TaskDAG")
        if incomplete:
            reasons.append("not every TaskDAG node is SUCCEEDED")
        if no_verification:
            reasons.append("one or more succeeded nodes lack passing executable verification evidence")
        if not contract.acceptance_criteria:
            reasons.append("contract has no acceptance criteria")
        accepted = not (missing or incomplete or no_verification or not contract.acceptance_criteria)
        return ProjectCompletionReport(
            accepted=accepted,
            missing_requirements=missing,
            incomplete_nodes=incomplete,
            nodes_without_verification=sorted(no_verification),
            evidence_refs=sorted(set(evidence_refs)),
            reasons=reasons,
        )
