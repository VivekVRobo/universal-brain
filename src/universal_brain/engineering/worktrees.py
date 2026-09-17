"""Requirement-scoped Git worktree ownership and verified integration.

Traceability: REQ-ENG-006, REQ-ENG-007, REQ-ENG-017, ALN-007, ALN-016.
One requirement chain keeps one isolated branch across analyze/implement/verify.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from universal_brain.executive.schemas import TaskNode
from universal_brain.intelligence.schemas import NormalizedToolCall

from .git_engine import GitTransactionEngine
from .schemas import EngineeringToolObservation


class WorktreeCapacityError(RuntimeError):
    pass


class RequirementWorktreeBinding(BaseModel):
    requirement_ref: str
    branch: str
    path: Path
    node_ids: set[str] = Field(default_factory=set)
    verified_commit: str | None = None
    integrated_commit: str | None = None


class RequirementWorktreeManager:
    def __init__(
        self,
        git: GitTransactionEngine,
        *,
        max_active: int = 4,
        branch_prefix: str = "brain/req-",
        on_integrated=None,
        merge_coordinator=None,
    ) -> None:
        if max_active < 1:
            raise ValueError("max_active must be >= 1")
        self.git = git
        self.max_active = max_active
        self.branch_prefix = branch_prefix
        self.on_integrated = on_integrated
        self.merge_coordinator = merge_coordinator
        self._bindings: dict[str, RequirementWorktreeBinding] = {}
        self._lock = asyncio.Lock()
        self._integration_lock = asyncio.Lock()

    @staticmethod
    def _single_requirement(node: TaskNode) -> str | None:
        if len(node.requirement_refs) != 1:
            return None
        return node.requirement_refs[0]

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:72] or "requirement"

    async def acquire_for_node(self, node: TaskNode) -> RequirementWorktreeBinding | None:
        requirement = self._single_requirement(node)
        if requirement is None:
            return None
        async with self._lock:
            existing = self._bindings.get(requirement)
            if existing:
                existing.node_ids.add(node.node_id)
                return existing
            if len(self._bindings) >= self.max_active:
                raise WorktreeCapacityError(
                    f"Requirement worktree capacity reached ({self.max_active}); scheduler must wait"
                )
            branch = f"{self.branch_prefix}{self._slug(requirement)}"
            path = await self.git.create_task_worktree(requirement, branch=branch)
            binding = RequirementWorktreeBinding(
                requirement_ref=requirement,
                branch=branch,
                path=path,
                node_ids={node.node_id},
            )
            self._bindings[requirement] = binding
            return binding

    def workspace_for_node(self, node: TaskNode) -> Path:
        requirement = self._single_requirement(node)
        if requirement and requirement in self._bindings:
            return self._bindings[requirement].path
        return self.git.workspace.repository_root

    def select_schedulable(self, nodes: list[TaskNode], *, limit: int) -> list[TaskNode]:
        """Select READY nodes without overcommitting requirement worktree capacity.

        Existing requirement bindings are always reusable. New requirement chains are
        admitted only while capacity remains. Multi-requirement/global nodes do not
        consume a requirement worktree slot.
        """
        if limit < 1:
            return []
        available_new = max(0, self.max_active - len(self._bindings))
        selected: list[TaskNode] = []
        newly_reserved: set[str] = set()
        for node in nodes:
            if len(selected) >= limit:
                break
            requirement = self._single_requirement(node)
            if requirement is None or requirement in self._bindings or requirement in newly_reserved:
                selected.append(node)
                continue
            if available_new <= 0:
                continue
            selected.append(node)
            newly_reserved.add(requirement)
            available_new -= 1
        return selected

    def export_bindings(self) -> dict[str, dict[str, Any]]:
        return {
            key: binding.model_dump(mode="json")
            for key, binding in sorted(self._bindings.items())
        }

    def restore_bindings(self, payload: dict[str, dict[str, Any]]) -> None:
        root = self.git.workspace.normalized_worktree_root()
        restored: dict[str, RequirementWorktreeBinding] = {}
        for key, raw in payload.items():
            binding = RequirementWorktreeBinding.model_validate(raw)
            path = binding.path.resolve()
            if path != root and root not in path.parents:
                raise ValueError(f"Recovered worktree escapes managed root: {path}")
            restored[key] = binding.model_copy(update={"path": path})
        self._bindings = restored

    async def finalize_verified_requirement(self, node: TaskNode) -> RequirementWorktreeBinding | None:
        requirement = self._single_requirement(node)
        if requirement is None:
            return None
        binding = self._bindings.get(requirement)
        if binding is None:
            return None
        async with self._integration_lock:
            if binding.verified_commit is None:
                binding.verified_commit = await self.git.commit(
                    binding.path,
                    message=f"Implement {requirement}",
                )
            if binding.integrated_commit is None:
                if self.merge_coordinator is not None:
                    integration = await self.merge_coordinator.integrate_verified_branch(
                        branch=binding.branch,
                        verified_source_commit=binding.verified_commit,
                        node=node,
                    )
                    if not integration.accepted or not integration.integrated_commit:
                        raise RuntimeError(
                            f"Verified branch integration rejected: {integration.reason}; "
                            f"conflicts={integration.conflict_files}"
                        )
                    binding.integrated_commit = integration.integrated_commit
                else:
                    binding.integrated_commit = await self.git.integrate_branch(binding.branch)
            await self.git.remove_worktree(requirement)
            self._bindings.pop(requirement, None)
            if self.on_integrated is not None:
                maybe = self.on_integrated(binding)
                if hasattr(maybe, "__await__"):
                    await maybe
            return binding


class WorkspaceScopedToolExecutor:
    """Rebase relative model tool proposals into the node's isolated workspace.

    Absolute paths outside the assigned workspace are rejected before reaching the
    ToolGateway. The wrapper does not grant additional tool operations.
    """

    PATH_KEYS = ("target", "path", "file_path", "filename", "cwd")

    def __init__(self, delegate, workspace_resolver) -> None:
        self.delegate = delegate
        self.workspace_resolver = workspace_resolver

    async def execute(self, node: TaskNode, call: NormalizedToolCall) -> EngineeringToolObservation:
        root = Path(self.workspace_resolver(node)).resolve()
        arguments = dict(call.arguments)
        try:
            for key in self.PATH_KEYS:
                raw = arguments.get(key)
                if not isinstance(raw, str) or not raw or raw == "*":
                    continue
                candidate = Path(raw)
                resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
                if resolved != root and root not in resolved.parents:
                    raise ValueError(f"Tool path escapes assigned engineering workspace: {raw!r}")
                arguments[key] = str(resolved)
        except ValueError as exc:
            return EngineeringToolObservation(
                tool_name=call.tool_name,
                call_id=call.call_id,
                success=False,
                error=str(exc),
            )
        scoped = call.model_copy(update={"arguments": arguments})
        return await self.delegate.execute(node, scoped)
