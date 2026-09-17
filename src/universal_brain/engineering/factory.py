"""Composition root for the V5.2 Engineering Runtime Hardening stack."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agency import EngineeringAgencyRuntime
from .audit import EngineeringCausalAuditor
from .checkpointing import EngineeringCheckpointStore
from .code_graph import CodeGraphIndex, CodeGraphIndexer
from .dependency import DependencyFailureDiagnoser
from .distributed_leases import DurableWorkerLeaseStore
from .git_engine import GitTransactionEngine
from .merge_coordinator import ExecutableMergedTreeVerifier, SerializedMergeCoordinator
from .multirepo import MultiRepositoryGraph, MultiRepositoryGraphBuilder
from .replanning import AdaptiveEngineeringReplanner
from .verification import (
    ExecutableVerificationAdapter,
    ImpactAwareExecutableVerificationAdapter,
    VerificationPolicy,
)
from .worktrees import RequirementWorktreeManager, WorkspaceScopedToolExecutor


@dataclass(slots=True)
class EngineeringAgencyStack:
    code_graph: CodeGraphIndex
    code_indexer: CodeGraphIndexer
    git: GitTransactionEngine
    worktrees: RequirementWorktreeManager
    tool_executor: WorkspaceScopedToolExecutor
    verifier: ImpactAwareExecutableVerificationAdapter
    integration_verifier: ExecutableVerificationAdapter
    merge_coordinator: SerializedMergeCoordinator
    dependency_diagnoser: DependencyFailureDiagnoser
    replanner: AdaptiveEngineeringReplanner
    checkpoint_store: EngineeringCheckpointStore
    auditor: EngineeringCausalAuditor
    distributed_leases: DurableWorkerLeaseStore
    multi_repo_graph: MultiRepositoryGraph
    runtime: EngineeringAgencyRuntime
    service_supervisor: Any | None = None
    isolation_provider: Any | None = None
    semantic_backends: tuple[str, ...] = ()


def build_engineering_agency_stack(
    *,
    workspace,
    cognitive_runtime,
    tool_executor,
    verification_executor,
    git_executor,
    event_store,
    checkpoint_path: Path | None = None,
    lease_store_path: Path | None = None,
    verification_policy: VerificationPolicy | None = None,
    max_parallel_nodes: int = 4,
    max_tool_iterations: int = 8,
    multi_repo_roots: list[Path] | None = None,
    service_supervisor=None,
    isolation_provider=None,
    semantic_backends: tuple[str, ...] = (),
) -> EngineeringAgencyStack:
    """Wire V5.2 so merge verification/recovery/isolation hooks are default-safe.

    The builder never creates capabilities or bypasses ToolGateway. Supplied
    tool/git/verification/service/isolation backends remain authority-gated.
    """
    if max_parallel_nodes < 1:
        raise ValueError("max_parallel_nodes must be >= 1")

    indexer = CodeGraphIndexer()
    index = indexer.build(workspace.repository_root)
    git = GitTransactionEngine(workspace, git_executor)

    integration_verifier = ExecutableVerificationAdapter(
        workspace.repository_root,
        verification_executor,
        policy=verification_policy,
    )
    merge_coordinator = SerializedMergeCoordinator(
        git,
        ExecutableMergedTreeVerifier(integration_verifier),
    )

    def refresh_graph(_binding):
        indexer.refresh(index)

    worktrees = RequirementWorktreeManager(
        git,
        max_active=max_parallel_nodes,
        on_integrated=refresh_graph,
        merge_coordinator=merge_coordinator,
    )
    scoped_tools = WorkspaceScopedToolExecutor(tool_executor, worktrees.workspace_for_node)

    async def changed_files(node):
        root = worktrees.workspace_for_node(node).resolve()
        if root == workspace.repository_root.resolve():
            return []
        return await git.changed_files(root)

    verifier = ImpactAwareExecutableVerificationAdapter(
        workspace.repository_root,
        verification_executor,
        code_graph=index,
        changed_files_provider=changed_files,
        policy=verification_policy,
        workspace_resolver=worktrees.workspace_for_node,
    )
    dependency_diagnoser = DependencyFailureDiagnoser()
    replanner = AdaptiveEngineeringReplanner(
        dependency_diagnoser=dependency_diagnoser,
        workspace_resolver=worktrees.workspace_for_node,
    )
    checkpoint_store = EngineeringCheckpointStore(
        checkpoint_path
        or workspace.repository_root / ".brain" / "engineering" / "mission-checkpoint.json"
    )
    auditor = EngineeringCausalAuditor(event_store)
    distributed_leases = DurableWorkerLeaseStore(
        lease_store_path
        or workspace.repository_root / ".brain" / "engineering" / "distributed-worker-leases.json"
    )
    roots = multi_repo_roots or [workspace.repository_root]
    multi_repo_graph = MultiRepositoryGraphBuilder().build(roots)
    runtime = EngineeringAgencyRuntime(
        cognitive_runtime=cognitive_runtime,
        tool_executor=scoped_tools,
        verifier=verifier,
        max_tool_iterations=max_tool_iterations,
        max_parallel_nodes=max_parallel_nodes,
        parallel_isolation_verified=max_parallel_nodes > 1,
        replanner=replanner,
        auditor=auditor,
        worktree_manager=worktrees,
        checkpoint_store=checkpoint_store,
        workspace_root=workspace.repository_root,
    )
    return EngineeringAgencyStack(
        code_graph=index,
        code_indexer=indexer,
        git=git,
        worktrees=worktrees,
        tool_executor=scoped_tools,
        verifier=verifier,
        integration_verifier=integration_verifier,
        merge_coordinator=merge_coordinator,
        dependency_diagnoser=dependency_diagnoser,
        replanner=replanner,
        checkpoint_store=checkpoint_store,
        auditor=auditor,
        distributed_leases=distributed_leases,
        multi_repo_graph=multi_repo_graph,
        runtime=runtime,
        service_supervisor=service_supervisor,
        isolation_provider=isolation_provider,
        semantic_backends=semantic_backends,
    )
