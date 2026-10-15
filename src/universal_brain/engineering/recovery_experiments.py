"""Controlled recovery reliability experiments for Universal Brain.

These experiments are research instrumentation. They distinguish deterministic
component behavior from target machine proof and do not promote skipped or
synthetic conditions into production claims.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from universal_brain.alignment.contract import (
    AcceptanceCriterion,
    AlignmentContract,
    OriginalInput,
    PermissionsCeiling,
    Requirement,
    RequirementKind,
    RequirementPriority,
)
from universal_brain.engineering.checkpointing import (
    EngineeringCheckpointError,
    EngineeringCheckpointStore,
)
from universal_brain.executive.schemas import TaskDAG, TaskNode, TaskNodeStatus
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventType
from universal_brain.tools.base import BaseTool, ReversibilityClass, ToolResult
from universal_brain.tools.gateway import ToolGateway


class ExperimentTrial(BaseModel):
    experiment_id: str
    trial_id: str
    condition: str
    interruption_point: str = ""
    strategy: str = ""
    passed: bool
    metrics: dict[str, float | int | bool] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


def _detect_source_commit() -> str:
    env_sha = os.environ.get("GITHUB_SHA", "").strip()
    if env_sha:
        return env_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            shell=False,
            check=False,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _environment_metadata() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
    }


class ExperimentReport(BaseModel):
    schema_version: str = "ub-recovery-experiments/v1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_commit: str = Field(default_factory=_detect_source_commit)
    environment: dict[str, str] = Field(default_factory=_environment_metadata)
    trials: list[ExperimentTrial] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    payload_sha256: str = ""

    def canonical_bytes(self) -> bytes:
        payload = self.model_dump(mode="json")
        payload["payload_sha256"] = ""
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def seal(self) -> "ExperimentReport":
        digest = hashlib.sha256(self.canonical_bytes()).hexdigest()
        return self.model_copy(update={"payload_sha256": digest})

    def verify_digest(self) -> bool:
        return bool(self.payload_sha256) and (
            hashlib.sha256(self.canonical_bytes()).hexdigest() == self.payload_sha256
        )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _effect_path(root: Path) -> Path:
    return root / "src" / "effects.log"


def _read_effects(root: Path) -> list[str]:
    path = _effect_path(root)
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_effect(root: Path, step: int) -> None:
    path = _effect_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"step_{step:03d}\n")
        handle.flush()
        os.fsync(handle.fileno())


def _effect_metrics(root: Path, total_steps: int) -> tuple[int, int]:
    effects = _read_effects(root)
    counts = Counter(effects)
    duplicates = sum(max(0, count - 1) for count in counts.values())
    missing = sum(1 for step in range(1, total_steps + 1) if counts[f"step_{step:03d}"] == 0)
    return duplicates, missing


def _build_dag(
    total_steps: int,
    completed_steps: int,
    *,
    active_status: TaskNodeStatus = TaskNodeStatus.READY,
) -> TaskDAG:
    dag_id = uuid4()
    project_id = uuid4()
    contract_id = uuid4()
    nodes: dict[str, TaskNode] = {}
    for step in range(1, total_steps + 1):
        node_id = f"step_{step:03d}"
        if step <= completed_steps:
            status = TaskNodeStatus.SUCCEEDED
        elif step == completed_steps + 1:
            status = active_status
        else:
            status = TaskNodeStatus.PLANNED
        nodes[node_id] = TaskNode(
            node_id=node_id,
            dag_id=dag_id,
            goal=f"Apply deterministic research step {step}",
            requirement_refs=["REQ-RECOVERY-EXP"],
            dependencies=[] if step == 1 else [f"step_{step - 1:03d}"],
            action_class=ActionClass.A1,
            tool_scope=["research_step"],
            acceptance_criteria=[f"step {step} appears exactly once"],
            status=status,
        )
    return TaskDAG(
        dag_id=dag_id,
        project_id=project_id,
        contract_id=contract_id,
        contract_version=1,
        nodes=nodes,
    )


def _seed_workspace(root: Path, completed_steps: int) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    for step in range(1, completed_steps + 1):
        _append_effect(root, step)


def _complete_from(root: Path, start_step: int, total_steps: int) -> None:
    for step in range(start_step, total_steps + 1):
        _append_effect(root, step)


def _run_information_set_trial(
    *,
    strategy: str,
    interruption_pct: int,
    crash_window: str,
    total_steps: int,
    trial_index: int,
) -> ExperimentTrial:
    completed = min(total_steps - 1, max(1, round(total_steps * interruption_pct / 100)))
    next_step = completed + 1
    with tempfile.TemporaryDirectory(prefix=f"ub-exp1-{strategy}-") as directory:
        root = Path(directory)
        _seed_workspace(root, completed)
        brain = root / ".brain"
        brain.mkdir(parents=True, exist_ok=True)
        dag = _build_dag(total_steps, completed)

        if strategy == "conversation":
            _atomic_json(
                brain / "conversation.json",
                {
                    "completed_steps": completed,
                    "last_message": f"steps 1 through {completed} completed",
                },
            )
        elif strategy == "dag":
            (brain / "dag.json").write_text(dag.model_dump_json(indent=2), encoding="utf-8")
        elif strategy == "checkpoint":
            EngineeringCheckpointStore(brain / "mission.json").save(
                dag=dag,
                workspace_root=root,
                metadata={"experiment": "exp1", "interruption_pct": interruption_pct},
            )
        else:
            raise ValueError(f"unknown strategy: {strategy}")

        if crash_window == "effect_before_state":
            _append_effect(root, next_step)
        elif crash_window != "clean":
            raise ValueError(f"unknown crash window: {crash_window}")

        blocked = False
        recovery_error = ""
        if strategy == "checkpoint":
            try:
                recovered, _, _ = EngineeringCheckpointStore(brain / "mission.json").recover(
                    workspace_root=root
                )
                succeeded = sum(
                    1 for node in recovered.nodes.values() if node.status == TaskNodeStatus.SUCCEEDED
                )
                _complete_from(root, succeeded + 1, total_steps)
            except EngineeringCheckpointError as exc:
                blocked = True
                recovery_error = str(exc)
        else:
            # The conversation and plain DAG baselines know durable logical state,
            # but have no workspace identity proof. They therefore resume the next
            # unfinished step even when the effect happened just before the crash.
            _complete_from(root, next_step, total_steps)

        duplicates, missing = _effect_metrics(root, total_steps)
        complete = missing == 0
        safe = duplicates == 0 and missing == 0
        safe_or_blocked = safe or (blocked and duplicates == 0)
        return ExperimentTrial(
            experiment_id="EXP1_INFORMATION_SET_RECOVERY",
            trial_id=f"exp1-{strategy}-{interruption_pct}-{crash_window}-{trial_index}",
            condition=crash_window,
            interruption_point=f"{interruption_pct}pct",
            strategy=strategy,
            passed=True,
            metrics={
                "duplicate_actions": duplicates,
                "missing_actions": missing,
                "mission_complete": complete,
                "blocked_for_replan": blocked,
                "safe_recovery": safe,
                "safe_or_blocked": safe_or_blocked,
            },
            details={
                "completed_steps_at_durable_state": completed,
                "next_step": next_step,
                "recovery_error": recovery_error,
            },
        )


def run_experiment_1(
    *,
    trials_per_condition: int = 3,
    total_steps: int = 20,
    interruption_points: tuple[int, ...] = (10, 25, 50, 75, 90),
) -> list[ExperimentTrial]:
    """Compare three recovery information sets under clean and ambiguous crash windows.

    This is a deterministic control lab, not an LLM quality benchmark.
    """
    trials: list[ExperimentTrial] = []
    for strategy in ("conversation", "dag", "checkpoint"):
        for point in interruption_points:
            for window in ("clean", "effect_before_state"):
                for trial_index in range(trials_per_condition):
                    trials.append(
                        _run_information_set_trial(
                            strategy=strategy,
                            interruption_pct=point,
                            crash_window=window,
                            total_steps=total_steps,
                            trial_index=trial_index,
                        )
                    )
    return trials


def run_experiment_2(*, trials_per_condition: int = 3) -> list[ExperimentTrial]:
    """Challenge workspace drift detection with canonical and excluded mutations."""
    conditions = {
        "clean": ("none", False),
        "source_change": ("src/main.py", True),
        "test_change": ("tests/test_main.py", True),
        "dependency_change": ("pyproject.toml", True),
        "generated_brain_change": (".brain/runtime.log", False),
        "cache_change": ("__pycache__/cache.bin", False),
        "multiple_source_changes": ("multiple", True),
    }
    trials: list[ExperimentTrial] = []
    for condition, (target, expect_block) in conditions.items():
        for trial_index in range(trials_per_condition):
            with tempfile.TemporaryDirectory(prefix="ub-exp2-") as directory:
                root = Path(directory)
                (root / "src").mkdir()
                (root / "tests").mkdir()
                (root / "src" / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
                (root / "tests" / "test_main.py").write_text(
                    "def test_value():\n    assert True\n", encoding="utf-8"
                )
                (root / "pyproject.toml").write_text("[project]\nname='lab'\n", encoding="utf-8")
                dag = _build_dag(3, 1, active_status=TaskNodeStatus.COGNITIVE_WORK)
                store = EngineeringCheckpointStore(root / ".brain" / "mission.json")
                store.save(dag=dag, workspace_root=root)

                if target == "multiple":
                    (root / "src" / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
                    (root / "src" / "extra.py").write_text("EXTRA = True\n", encoding="utf-8")
                elif target != "none":
                    path = root / target
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("mutated\n", encoding="utf-8")

                blocked = False
                error = ""
                try:
                    store.recover(workspace_root=root)
                except EngineeringCheckpointError as exc:
                    blocked = True
                    error = str(exc)

                passed = blocked == expect_block
                trials.append(
                    ExperimentTrial(
                        experiment_id="EXP2_WORKSPACE_DRIFT",
                        trial_id=f"exp2-{condition}-{trial_index}",
                        condition=condition,
                        passed=passed,
                        metrics={
                            "blocked": blocked,
                            "expected_block": expect_block,
                            "classification_correct": passed,
                        },
                        details={"target": target, "error": error},
                    )
                )
    return trials


_PHASE_STATUS: dict[str, TaskNodeStatus] = {
    "planning": TaskNodeStatus.COGNITIVE_WORK,
    "cognitive_work": TaskNodeStatus.COGNITIVE_WORK,
    "tool_proposal": TaskNodeStatus.TOOL_PROPOSED,
    "preflight": TaskNodeStatus.PREFLIGHT,
    "execution": TaskNodeStatus.EXECUTING,
    "verification": TaskNodeStatus.VERIFYING,
    "commit": TaskNodeStatus.EXECUTING,
    "integration": TaskNodeStatus.EXECUTING,
}
_EFFECTFUL_PHASES = {"execution", "commit", "integration"}


def _phase_worker(root: Path, phase: str, crash_window: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "artifact.txt").write_text("baseline\n", encoding="utf-8")
    status = _PHASE_STATUS[phase]
    dag = _build_dag(1, 0, active_status=status)
    store = EngineeringCheckpointStore(root / ".brain" / "mission.json")
    store.save(
        dag=dag,
        workspace_root=root,
        metadata={"experiment": "exp3", "phase": phase, "crash_window": crash_window},
    )
    if crash_window == "effect_before_state":
        with (root / "src" / "artifact.txt").open("a", encoding="utf-8") as handle:
            handle.write(f"effect:{phase}\n")
            handle.flush()
            os.fsync(handle.fileno())
    os._exit(91)


def _spawn_phase_worker(root: Path, phase: str, crash_window: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_root = str(Path(__file__).resolve().parents[2])
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_root if not existing else f"{src_root}{os.pathsep}{existing}"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "universal_brain.engineering.recovery_experiments",
            "_phase_worker",
            str(root),
            phase,
            crash_window,
        ],
        text=True,
        capture_output=True,
        shell=False,
        check=False,
        timeout=30,
        env=env,
    )


def run_experiment_3(*, trials_per_condition: int = 3) -> list[ExperimentTrial]:
    """Terminate a real Python process at each execution phase and recover in a new process."""
    trials: list[ExperimentTrial] = []
    for phase in _PHASE_STATUS:
        windows = ["after_checkpoint"]
        if phase in _EFFECTFUL_PHASES:
            windows.append("effect_before_state")
        for window in windows:
            for trial_index in range(trials_per_condition):
                with tempfile.TemporaryDirectory(prefix=f"ub-exp3-{phase}-") as directory:
                    root = Path(directory)
                    proc = _spawn_phase_worker(root, phase, window)
                    crashed_as_expected = proc.returncode == 91
                    store = EngineeringCheckpointStore(root / ".brain" / "mission.json")
                    blocked_on_drift = False
                    reset_to_replan = False
                    recovery_error = ""
                    try:
                        recovered, reset, _ = store.recover(workspace_root=root)
                        reset_to_replan = bool(reset) and all(
                            recovered.nodes[node_id].status == TaskNodeStatus.REPLAN_REQUIRED
                            for node_id in reset
                        )
                    except EngineeringCheckpointError as exc:
                        blocked_on_drift = True
                        recovery_error = str(exc)

                    if window == "effect_before_state":
                        passed = crashed_as_expected and blocked_on_drift
                    else:
                        passed = crashed_as_expected and reset_to_replan and not blocked_on_drift
                    trials.append(
                        ExperimentTrial(
                            experiment_id="EXP3_PHASE_CRASH_RECOVERY",
                            trial_id=f"exp3-{phase}-{window}-{trial_index}",
                            condition=window,
                            interruption_point=phase,
                            strategy="engineering_checkpoint",
                            passed=passed,
                            metrics={
                                "child_crashed_as_expected": crashed_as_expected,
                                "reset_to_replan": reset_to_replan,
                                "blocked_on_workspace_drift": blocked_on_drift,
                            },
                            details={
                                "return_code": proc.returncode,
                                "stderr": proc.stderr[-2000:],
                                "recovery_error": recovery_error,
                            },
                        )
                    )
    return trials


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class _AppendTool(BaseTool):
    name = "research_append"
    action_class = ActionClass.A1
    description = "Disposable non idempotent append action for crash window measurement"
    reversibility_class = ReversibilityClass.VERIFIED_REVERSIBLE

    def __init__(self, path: Path) -> None:
        self.path = path

    def preflight_check(self, args: dict[str, Any]) -> bool:
        return args.get("target") == str(self.path) and bool(args.get("operation_id"))

    def execute(self, args: dict[str, Any]) -> ToolResult:
        operation_id = str(args["operation_id"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(operation_id + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return ToolResult(
            success=True,
            output=operation_id,
            evidence={"operation_id": operation_id},
            rollback_data={"operation_id": operation_id},
            reversibility_class=self.reversibility_class,
        )

    def rollback(self, rollback_data: dict[str, Any]) -> bool:
        operation_id = str(rollback_data.get("operation_id") or "")
        lines = _read_lines(self.path)
        if operation_id not in lines:
            return True
        removed = False
        kept = []
        for line in lines:
            if line == operation_id and not removed:
                removed = True
                continue
            kept.append(line)
        self.path.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8")
        return True


class _CrashOnFirstEvidenceStore(EventStore):
    def __init__(self) -> None:
        super().__init__()
        self.crashed = False

    def append_event(self, event_type: EventType, *args: Any, **kwargs: Any):
        if event_type == EventType.EVIDENCE_PRODUCED and not self.crashed:
            self.crashed = True
            raise RuntimeError("injected crash after tool side effect before evidence receipt")
        return super().append_event(event_type, *args, **kwargs)


def _research_contract() -> AlignmentContract:
    source = OriginalInput(exact_content_ref="recovery_experiment")
    requirement = Requirement(
        requirement_id="REQ-RECOVERY-EXP",
        statement="Measure duplicate execution at the tool receipt crash boundary",
        source_input_ids=[source.input_id],
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        verification_method="controlled failure injection",
    )
    criterion = AcceptanceCriterion(
        criterion_id="AC-RECOVERY-EXP",
        statement="Repeated invocation is measured without concealing duplicates",
        evidence_type="experiment_output",
        verifier="deterministic",
    )
    contract = AlignmentContract.create_draft(
        objective="Recovery reliability experiment",
        requirements=[requirement],
        permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
        acceptance_criteria=[criterion],
        original_inputs=[source],
    )
    contract.activate()
    return contract


def run_experiment_4(*, trials_per_condition: int = 3) -> list[ExperimentTrial]:
    """Measure the tool side effect versus evidence receipt crash window.

    This intentionally observes current behavior. It does not add deduplication.
    """
    trials: list[ExperimentTrial] = []
    for trial_index in range(trials_per_condition):
        with tempfile.TemporaryDirectory(prefix="ub-exp4-") as directory:
            root = Path(directory)
            target = root / "effects.log"
            operation_id = f"op-{trial_index:04d}"
            store = _CrashOnFirstEvidenceStore()
            capability = CapabilityService()
            gateway = ToolGateway(event_store=store, capability_service=capability)
            gateway.register_tool(_AppendTool(target))
            contract = _research_contract()
            task_id = uuid4()
            token = capability.issue_token(
                project_id=uuid4(),
                task_id=task_id,
                contract_version=contract.version,
                action_class=ActionClass.A1,
                target_resource=str(target),
                allowed_operations=["research_append"],
                idempotency_key=operation_id,
            )
            args = {"target": str(target), "operation_id": operation_id}

            crash_seen = False
            try:
                gateway.execute_tool(
                    tool_name="research_append",
                    args=args,
                    capability_token=token,
                    contract=contract,
                    target_resource=str(target),
                )
            except RuntimeError as exc:
                crash_seen = "injected crash" in str(exc)

            count_after_crash = _read_lines(target).count(operation_id)
            retry_succeeded = False
            try:
                gateway.execute_tool(
                    tool_name="research_append",
                    args=args,
                    capability_token=token,
                    contract=contract,
                    target_resource=str(target),
                )
                retry_succeeded = True
            except Exception:
                retry_succeeded = False

            final_count = _read_lines(target).count(operation_id)
            duplicate_count = max(0, final_count - 1)
            harness_passed = crash_seen and count_after_crash == 1 and retry_succeeded
            trials.append(
                ExperimentTrial(
                    experiment_id="EXP4_SIDE_EFFECT_RECEIPT_WINDOW",
                    trial_id=f"exp4-{trial_index}",
                    condition="effect_succeeds_receipt_crashes_then_retry",
                    interruption_point="after_tool_effect_before_evidence_receipt",
                    strategy="current_tool_gateway",
                    passed=harness_passed,
                    metrics={
                        "effect_count_after_injected_crash": count_after_crash,
                        "effect_count_after_retry": final_count,
                        "duplicate_actions": duplicate_count,
                        "retry_succeeded": retry_succeeded,
                    },
                    details={
                        "operation_id": operation_id,
                        "crash_seen": crash_seen,
                        "tool_call_events": sum(
                            1 for event in store.get_all_events() if event.event_type == EventType.TOOL_CALLED
                        ),
                        "evidence_events": sum(
                            1
                            for event in store.get_all_events()
                            if event.event_type == EventType.EVIDENCE_PRODUCED
                        ),
                    },
                )
            )
    return trials


def _aggregate(trials: list[ExperimentTrial]) -> dict[str, Any]:
    by_experiment: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[ExperimentTrial]] = defaultdict(list)
    for trial in trials:
        grouped[trial.experiment_id].append(trial)
    for experiment_id, items in grouped.items():
        by_experiment[experiment_id] = {
            "trials": len(items),
            "harness_passes": sum(1 for item in items if item.passed),
            "harness_failures": sum(1 for item in items if not item.passed),
            "duplicate_actions": sum(int(item.metrics.get("duplicate_actions", 0)) for item in items),
            "blocked_for_replan": sum(
                1
                for item in items
                if bool(
                    item.metrics.get("blocked_for_replan", False)
                    or item.metrics.get("blocked_on_workspace_drift", False)
                )
            ),
        }
    return by_experiment


def run_all(*, trials_per_condition: int = 3) -> ExperimentReport:
    trials = [
        *run_experiment_1(trials_per_condition=trials_per_condition),
        *run_experiment_2(trials_per_condition=trials_per_condition),
        *run_experiment_3(trials_per_condition=trials_per_condition),
        *run_experiment_4(trials_per_condition=trials_per_condition),
    ]
    return ExperimentReport(trials=trials, summary=_aggregate(trials))


def write_report(report: ExperimentReport, path: Path) -> Path:
    sealed = report if report.verify_digest() else report.seal()
    _atomic_json(path, sealed.model_dump(mode="json"))
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Universal Brain recovery reliability experiments")
    sub = parser.add_subparsers(dest="command", required=True)

    worker = sub.add_parser("_phase_worker")
    worker.add_argument("root", type=Path)
    worker.add_argument("phase", choices=sorted(_PHASE_STATUS))
    worker.add_argument("crash_window", choices=["after_checkpoint", "effect_before_state"])

    run = sub.add_parser("run")
    run.add_argument("--experiment", choices=["1", "2", "3", "4", "all"], default="all")
    run.add_argument("--trials", type=int, default=3)
    run.add_argument(
        "--output",
        type=Path,
        default=Path(".brain/research/recovery_experiments_v1.json"),
    )

    args = parser.parse_args(argv)
    if args.command == "_phase_worker":
        _phase_worker(args.root, args.phase, args.crash_window)
        return 91

    if args.trials < 1:
        parser.error("--trials must be at least 1")

    if args.experiment == "1":
        trials = run_experiment_1(trials_per_condition=args.trials)
    elif args.experiment == "2":
        trials = run_experiment_2(trials_per_condition=args.trials)
    elif args.experiment == "3":
        trials = run_experiment_3(trials_per_condition=args.trials)
    elif args.experiment == "4":
        trials = run_experiment_4(trials_per_condition=args.trials)
    else:
        report = run_all(trials_per_condition=args.trials)
        write_report(report, args.output)
        print(json.dumps(report.summary, sort_keys=True, indent=2))
        print(f"report={args.output}")
        return 0

    report = ExperimentReport(trials=trials, summary=_aggregate(trials))
    write_report(report, args.output)
    print(json.dumps(report.summary, sort_keys=True, indent=2))
    print(f"report={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
