"""Deterministic failure classification and safe DAG recovery insertion.

Traceability: REQ-ENG-002, REQ-ENG-012, ALN-001, ALN-004, ALN-005, ALN-010.
This replanner does not invent new product requirements; it only adds reversible
engineering recovery work tied to the failed node's existing requirement refs.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from universal_brain.executive.schemas import TaskDAG, TaskNode, TaskNodeStatus
from universal_brain.kernel.events import ActionClass

from .planning import TaskDAGMutator
from .schemas import EngineeringNodeRun


class FailureKind(str, Enum):
    MISSING_DEPENDENCY = "missing_dependency"
    COMPILE_ERROR = "compile_error"
    TEST_FAILURE = "test_failure"
    MERGE_CONFLICT = "merge_conflict"
    MISSING_SYMBOL = "missing_symbol"
    TOOL_FAILURE = "tool_failure"
    UNKNOWN = "unknown"


class FailureClassification(BaseModel):
    kind: FailureKind
    summary: str
    signals: list[str] = Field(default_factory=list)


class DeterministicFailureClassifier:
    PATTERNS = [
        (FailureKind.MISSING_DEPENDENCY, re.compile(r"(module not found|no module named|cannot find module|failed to resolve|package .* not found)", re.I)),
        (FailureKind.MERGE_CONFLICT, re.compile(r"(merge conflict|conflict \(content\)|automatic merge failed)", re.I)),
        (FailureKind.MISSING_SYMBOL, re.compile(r"(name .* is not defined|cannot find symbol|undefined reference|unresolved import)", re.I)),
        (FailureKind.TEST_FAILURE, re.compile(r"(\bfailed\b|assertionerror|test failures?|tests? failed)", re.I)),
        (FailureKind.COMPILE_ERROR, re.compile(r"(syntaxerror|compile error|compilation failed|ts\d{4}:|error\[e\d+\])", re.I)),
    ]

    def classify(self, run: EngineeringNodeRun) -> FailureClassification:
        corpus = "\n".join(
            [run.replan_reason or ""]
            + [obs.error or "" for obs in run.observations]
            + [obs.output[-4000:] for obs in run.observations]
            + [check.reason for check in run.verification_checks]
        )
        for kind, pattern in self.PATTERNS:
            match = pattern.search(corpus)
            if match:
                return FailureClassification(kind=kind, summary=match.group(0), signals=[match.group(0)])
        if any(not obs.success for obs in run.observations):
            return FailureClassification(kind=FailureKind.TOOL_FAILURE, summary="authority-gated tool execution failed")
        return FailureClassification(kind=FailureKind.UNKNOWN, summary="no deterministic recovery class matched")


class AdaptiveEngineeringReplanner:
    """Insert bounded recovery tasks for known failure classes and preserve provenance."""

    def __init__(
        self,
        classifier: DeterministicFailureClassifier | None = None,
        *,
        dependency_diagnoser=None,
        workspace_resolver=None,
    ):
        self.classifier = classifier or DeterministicFailureClassifier()
        self.mutator = TaskDAGMutator()
        self.dependency_diagnoser = dependency_diagnoser
        self.workspace_resolver = workspace_resolver
        self._counter = 0

    def replan(self, dag: TaskDAG, failed_node_id: str, run: EngineeringNodeRun) -> str | None:
        failed = dag.nodes.get(failed_node_id)
        if failed is None or failed.status != TaskNodeStatus.REPLAN_REQUIRED:
            return None
        classification = self.classifier.classify(run)
        spec = self._recovery_spec(classification)
        if spec is None:
            return None
        self._counter += 1
        node_id = f"recovery_{self._counter:03d}_{classification.kind.value}_{failed_node_id}"[:120]
        description = f"{spec[1]} Original failure: {classification.summary}"
        if (
            classification.kind == FailureKind.MISSING_DEPENDENCY
            and self.dependency_diagnoser is not None
            and self.workspace_resolver is not None
        ):
            try:
                root = self.workspace_resolver(failed)
                corpus = "\n".join(
                    [run.replan_reason or ""]
                    + [obs.error or "" for obs in run.observations]
                    + [obs.output[-4000:] for obs in run.observations]
                    + [check.reason for check in run.verification_checks]
                )
                plan = self.dependency_diagnoser.diagnose(root, corpus)
                description += (
                    f" Detected ecosystem={plan.ecosystem.value}, package_manager={plan.package_manager}, "
                    f"manifests={plan.manifest_paths}, lockfiles={plan.lockfile_paths}, "
                    f"suggested_commands={plan.suggested_commands}. Inspect manifests before execution."
                )
            except Exception:
                pass
        recovery = TaskNode(
            node_id=node_id,
            dag_id=dag.dag_id,
            goal=spec[0],
            description=description,
            requirement_refs=list(failed.requirement_refs),
            action_class=spec[2],
            tool_scope=list(spec[3]),
            required_capabilities=list(spec[4]),
            acceptance_criteria=[spec[5]],
            expected_evidence=["recovery_execution_log", "verification_log"],
            status=TaskNodeStatus.PLANNED,
        )
        self.mutator.insert_before(dag, failed_node_id, recovery)
        failed.status = TaskNodeStatus.PLANNED
        return recovery.node_id

    @staticmethod
    def _recovery_spec(classification: FailureClassification):
        if classification.kind == FailureKind.MISSING_DEPENDENCY:
            return (
                "Resolve missing project dependency using the existing package/build ecosystem",
                "Inspect existing manifests and lockfiles; do not switch frameworks or package managers without operator-approved architecture change.",
                ActionClass.A1,
                ["read_file", "patch_file", "run_command"],
                ["coding", "tool"],
                "Dependency is declared consistently and the original failing check progresses past dependency resolution",
            )
        if classification.kind in {FailureKind.COMPILE_ERROR, FailureKind.MISSING_SYMBOL}:
            return (
                "Repair deterministic compile/symbol failure",
                "Use compiler diagnostics and code-graph references to make the smallest requirement-preserving repair.",
                ActionClass.A1,
                ["read_file", "patch_file", "run_command"],
                ["coding", "verification"],
                "Compiler/type checker passes the previously failing location",
            )
        if classification.kind == FailureKind.TEST_FAILURE:
            return (
                "Diagnose and repair failing regression tests",
                "Preserve the active requirement and fix implementation defects rather than weakening tests unless the contract explicitly requires a test change.",
                ActionClass.A1,
                ["read_file", "patch_file", "run_command"],
                ["coding", "verification"],
                "Previously failing regression checks pass without reducing required coverage",
            )
        if classification.kind == FailureKind.MERGE_CONFLICT:
            return (
                "Resolve isolated Git integration conflict",
                "Reconcile conflicting branches while preserving requirement traceability and rerun impacted verification.",
                ActionClass.A1,
                ["read_file", "patch_file", "run_command"],
                ["coding", "architecture"],
                "Git conflict markers are absent and impacted verification passes",
            )
        return None
