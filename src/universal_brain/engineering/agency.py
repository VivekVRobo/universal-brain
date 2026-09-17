"""Closed cognition -> ToolGateway -> observation -> cognition engineering loop.

Traceability: REQ-ENG-003, REQ-ENG-004, REQ-TOL-001, ALN-009, ALN-010,
ALN-014, ALN-020. Models may propose actions; this runtime cannot mint authority.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Callable, Any
from uuid import UUID

from universal_brain.executive.schemas import TaskDAG, TaskNode, TaskNodeStatus
from universal_brain.intelligence.schemas import ModelMessage, ModelRequest, NormalizedToolCall

from .planning import TaskDAGMutator
from .schemas import EngineeringDAGRun, EngineeringNodeRun, EngineeringToolObservation


class EngineeringToolExecutor(Protocol):
    async def execute(self, node: TaskNode, call: NormalizedToolCall) -> EngineeringToolObservation: ...


class ToolGatewayProposalExecutor:
    """Concrete bridge from normalized model proposals to ToolGateway authority."""

    def __init__(self, gateway, contract, capability_token_provider: Callable[[TaskNode, NormalizedToolCall], Any]):
        self.gateway = gateway
        self.contract = contract
        self.capability_token_provider = capability_token_provider
        self._cause_event_id = None

    def set_cause_event(self, event_id) -> None:
        self._cause_event_id = event_id

    async def execute(self, node: TaskNode, call: NormalizedToolCall) -> EngineeringToolObservation:
        if call.tool_name not in node.tool_scope:
            return EngineeringToolObservation(
                tool_name=call.tool_name,
                call_id=call.call_id,
                success=False,
                error=f"Tool {call.tool_name!r} is outside node tool_scope",
            )
        token = self.capability_token_provider(node, call)
        try:
            result = self.gateway.execute_tool(
                tool_name=call.tool_name,
                args=dict(call.arguments),
                capability_token=token,
                contract=self.contract,
                actor_id="engineering_agent",
                target_resource=self._target(call.arguments),
                caused_by_event_id=self._cause_event_id,
            )
            return EngineeringToolObservation(
                tool_name=call.tool_name,
                call_id=call.call_id,
                success=bool(result.success),
                output=str(result.output),
                evidence=dict(result.evidence or {}),
                error=None if result.success else "tool returned unsuccessful result",
            )
        except Exception as exc:
            return EngineeringToolObservation(
                tool_name=call.tool_name,
                call_id=call.call_id,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _target(arguments: dict) -> str:
        for key in ("target", "path", "file_path", "filename", "resource", "cwd"):
            value = arguments.get(key)
            if isinstance(value, str) and value:
                return value
        return "*"


class EngineeringAgencyRuntime:
    """Long-running engineering loop with bounded iterations and deterministic completion."""

    def __init__(
        self,
        *,
        cognitive_runtime,
        tool_executor: EngineeringToolExecutor,
        verifier,
        max_tool_iterations: int = 8,
        max_parallel_nodes: int = 1,
        parallel_isolation_verified: bool = False,
        replanner=None,
        auditor=None,
        worktree_manager=None,
        checkpoint_store=None,
        workspace_root: Path | None = None,
    ) -> None:
        self.cognitive_runtime = cognitive_runtime
        self.tool_executor = tool_executor
        self.verifier = verifier
        self.max_tool_iterations = max_tool_iterations
        if max_parallel_nodes > 1 and not parallel_isolation_verified:
            raise ValueError("REQ-ENG-007: parallel engineering requires verified isolated workspaces")
        self.max_parallel_nodes = max_parallel_nodes
        self.parallel_isolation_verified = parallel_isolation_verified
        self.mutator = TaskDAGMutator()
        self.replanner = replanner
        self.auditor = auditor
        self.worktree_manager = worktree_manager
        self.checkpoint_store = checkpoint_store
        self.workspace_root = workspace_root.resolve() if workspace_root else None

    @staticmethod
    def _observation_request(base: ModelRequest, observations: list[EngineeringToolObservation], iteration: int) -> ModelRequest:
        lines = [
            f"OBSERVATION_ITERATION={iteration}",
            "The following are authoritative tool observations. Diagnose them and continue the same task.",
        ]
        for obs in observations:
            lines.append(
                f"TOOL={obs.tool_name} SUCCESS={obs.success} ERROR={obs.error or ''}\n"
                f"OUTPUT={obs.output[-6000:]}\nEVIDENCE={obs.evidence}"
            )
        lines.append(
            "If more actions are needed, propose only tools inside TOOL_SCOPE. Otherwise provide a completion candidate; verification is external."
        )
        return base.model_copy(
            update={
                "messages": [*base.messages, ModelMessage(role="user", content="\n\n".join(lines))],
                "metadata": {**base.metadata, "engineering_observation_iteration": iteration},
            }
        )

    @staticmethod
    def _last_evidence_event_id(observations: list[EngineeringToolObservation]):
        for observation in reversed(observations):
            raw = observation.evidence.get("evidence_event_id") if observation.evidence else None
            if raw:
                try:
                    return UUID(str(raw))
                except (TypeError, ValueError):
                    continue
        return None

    def _set_tool_cause(self, event_id) -> None:
        setter = getattr(self.tool_executor, "set_cause_event", None)
        if setter is not None:
            setter(event_id)
        delegate = getattr(self.tool_executor, "delegate", None)
        setter = getattr(delegate, "set_cause_event", None)
        if setter is not None:
            setter(event_id)

    def _checkpoint_workspace_root(self) -> Path | None:
        if self.workspace_root is not None:
            return self.workspace_root
        manager = self.worktree_manager
        if manager is not None:
            return manager.git.workspace.repository_root
        return None

    def recover_from_checkpoint(self):
        if self.checkpoint_store is None:
            raise RuntimeError("No engineering checkpoint store configured")
        root = self._checkpoint_workspace_root()
        if root is None:
            raise RuntimeError("No engineering workspace root configured for recovery")
        dag, reset_nodes, checkpoint = self.checkpoint_store.recover(workspace_root=root)
        if self.worktree_manager is not None:
            self.worktree_manager.restore_bindings(checkpoint.requirement_worktrees)
        return dag, reset_nodes, checkpoint

    async def execute_node(self, node: TaskNode, *, project_id: UUID) -> EngineeringNodeRun:
        before = node.status
        started = datetime.now(timezone.utc)
        if self.worktree_manager is not None:
            await self.worktree_manager.acquire_for_node(node)

        initial_request = self.cognitive_runtime.mapper.request(node, project_id=project_id)
        request_event = None
        if self.auditor is not None:
            request_event = self.auditor.record_request(
                initial_request, project_id=project_id, node_id=node.node_id
            )
        initial = await self.cognitive_runtime.execute_node(node, project_id=project_id)
        result = initial.result
        response_event = None
        if self.auditor is not None:
            response_event = self.auditor.record_response(
                result,
                project_id=project_id,
                node_id=node.node_id,
                caused_by_event_id=request_event.event_id if request_event else None,
            )
            self._set_tool_cause(response_event.event_id)
        observations: list[EngineeringToolObservation] = []
        iterations = 0

        while result.tool_calls and iterations < self.max_tool_iterations:
            iterations += 1
            node.status = TaskNodeStatus.EXECUTING
            batch: list[EngineeringToolObservation] = []
            for call in result.tool_calls:
                if call.tool_name not in node.tool_scope:
                    batch.append(
                        EngineeringToolObservation(
                            tool_name=call.tool_name,
                            call_id=call.call_id,
                            success=False,
                            error=f"Tool {call.tool_name!r} is outside node tool_scope",
                        )
                    )
                    continue
                batch.append(await self.tool_executor.execute(node, call))
            observations.extend(batch)
            if any(not item.success for item in batch):
                # A failed command is an observation, not automatic mission failure: allow cognition to diagnose.
                pass

            node.status = TaskNodeStatus.COGNITIVE_WORK
            base_profile = self.cognitive_runtime.mapper.map(node, project_id=project_id)
            base_request = self.cognitive_runtime.mapper.request(node, project_id=project_id)
            followup = self._observation_request(base_request, batch, iterations)
            followup_request_event = None
            if self.auditor is not None:
                followup_request_event = self.auditor.record_request(
                    followup,
                    project_id=project_id,
                    node_id=node.node_id,
                    caused_by_event_id=self._last_evidence_event_id(batch),
                )
            analysis = self.cognitive_runtime.fabric.analyze_task(followup, base_task=base_profile)
            result = await self.cognitive_runtime.escalator.invoke(analysis.profile, followup)
            if self.auditor is not None:
                response_event = self.auditor.record_response(
                    result,
                    project_id=project_id,
                    node_id=node.node_id,
                    caused_by_event_id=(
                        followup_request_event.event_id if followup_request_event else None
                    ),
                )
                self._set_tool_cause(response_event.event_id)

        if result.tool_calls:
            node.status = TaskNodeStatus.REPLAN_REQUIRED
            return EngineeringNodeRun(
                node_id=node.node_id,
                status_before=before,
                status_after=node.status,
                iterations=iterations,
                observations=observations,
                model_result_id=result.result_id,
                replan_reason=f"tool iteration budget exhausted at {self.max_tool_iterations}",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
            )

        node.status = TaskNodeStatus.VERIFYING
        decision = await self.verifier.verify(node, result)
        node.status = TaskNodeStatus.SUCCEEDED if decision.accepted else TaskNodeStatus.REPLAN_REQUIRED
        integration_error = None
        if (
            decision.accepted
            and self.worktree_manager is not None
            and node.node_id.endswith("_verify")
            and len(node.requirement_refs) == 1
        ):
            try:
                await self.worktree_manager.finalize_verified_requirement(node)
            except Exception as exc:
                node.status = TaskNodeStatus.REPLAN_REQUIRED
                integration_error = f"verified branch integration failed: {type(exc).__name__}: {exc}"
        checks = list(getattr(self.verifier, "last_results", []))
        return EngineeringNodeRun(
            node_id=node.node_id,
            status_before=before,
            status_after=node.status,
            iterations=iterations,
            observations=observations,
            verification_checks=checks,
            model_result_id=result.result_id,
            replan_reason=(integration_error or (None if decision.accepted else decision.reason)),
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        )

    async def run_dag(self, dag: TaskDAG, *, max_cycles: int = 128) -> EngineeringDAGRun:
        if not dag.validate_acyclic():
            raise ValueError("ALN-021: engineering task graph contains a cycle")
        runs: list[EngineeringNodeRun] = []
        cycles = 0
        semaphore = asyncio.Semaphore(self.max_parallel_nodes)

        async def guarded(node: TaskNode) -> EngineeringNodeRun:
            async with semaphore:
                return await self.execute_node(node, project_id=dag.project_id)

        while cycles < max_cycles:
            cycles += 1
            ready = self.mutator.ready_nodes(dag)
            if not ready:
                break
            if self.worktree_manager is not None:
                ready = self.worktree_manager.select_schedulable(
                    ready, limit=self.max_parallel_nodes
                )
            else:
                ready = ready[: self.max_parallel_nodes]
            if not ready:
                break
            # REQ-ENG-007: independent READY branches can make progress concurrently.
            cycle_runs = await asyncio.gather(*(guarded(node) for node in ready))
            runs.extend(cycle_runs)
            if self.checkpoint_store is not None:
                root = self._checkpoint_workspace_root()
                if root is None:
                    raise RuntimeError("Checkpoint store configured without engineering workspace root")
                bindings = (
                    self.worktree_manager.export_bindings()
                    if self.worktree_manager is not None
                    else {}
                )
                self.checkpoint_store.save(
                    dag=dag,
                    workspace_root=root,
                    runs=runs,
                    requirement_worktrees=bindings,
                    metadata={"cycle": cycles},
                )
            replan_runs = [run for run in cycle_runs if run.status_after == TaskNodeStatus.REPLAN_REQUIRED]
            if replan_runs:
                if self.replanner is None:
                    # Replanning is explicit; do not advance dependent branches through failed evidence.
                    break
                inserted = 0
                for run in replan_runs:
                    recovery_id = self.replanner.replan(dag, run.node_id, run)
                    if recovery_id:
                        inserted += 1
                if inserted == 0:
                    break
                continue

        complete = bool(dag.nodes) and all(node.status == TaskNodeStatus.SUCCEEDED for node in dag.nodes.values())
        blocked = [
            node.node_id
            for node in dag.nodes.values()
            if node.status in {
                TaskNodeStatus.BLOCKED,
                TaskNodeStatus.FAILED,
                TaskNodeStatus.REPLAN_REQUIRED,
                TaskNodeStatus.TOOL_PROPOSED,
                TaskNodeStatus.VERIFYING,
            }
        ]
        return EngineeringDAGRun(dag_id=dag.dag_id, runs=runs, cycles=cycles, complete=complete, blocked_nodes=blocked)
