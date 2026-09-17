"""Authority-gated Git transaction/worktree engine.

Traceability: REQ-ENG-006, REQ-ENG-007, REQ-TOL-001, ALN-007, ALN-016.
The engine emits Git command proposals only through an injected authorized executor.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from .schemas import EngineeringToolObservation, EngineeringWorkspace


class GitTransactionError(RuntimeError):
    pass


class AuthorizedGitExecutor(Protocol):
    async def run_git(self, arguments: list[str], *, cwd: Path, operation: str) -> EngineeringToolObservation: ...


class GitTransactionEngine:
    BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")

    def __init__(self, workspace: EngineeringWorkspace, executor: AuthorizedGitExecutor):
        self.workspace = workspace
        self.executor = executor

    def worktree_path(self, task_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id).strip("-")[:80] or "task"
        root = self.workspace.normalized_worktree_root()
        candidate = (root / safe).resolve()
        if candidate != root and root not in candidate.parents:
            raise GitTransactionError("worktree path escaped configured worktree root")
        return candidate

    async def create_task_worktree(self, task_id: str, *, branch: str | None = None) -> Path:
        branch_name = branch or f"brain/{re.sub(r'[^A-Za-z0-9._-]+', '-', task_id)[:80]}"
        if not self.BRANCH_RE.fullmatch(branch_name) or ".." in branch_name or branch_name.startswith("-"):
            raise GitTransactionError(f"Unsafe git branch name: {branch_name!r}")
        path = self.worktree_path(task_id)
        if not path.parent.exists():
            raise GitTransactionError(
                "managed worktree root does not exist; create it through an authorized workspace tool before Git execution"
            )
        obs = await self.executor.run_git(
            ["worktree", "add", "-b", branch_name, str(path), self.workspace.base_ref],
            cwd=self.workspace.repository_root,
            operation="git_worktree_add",
        )
        if not obs.success:
            raise GitTransactionError(obs.error or obs.output or "git worktree add failed")
        return path

    async def commit(self, worktree: Path, *, message: str, paths: list[str] | None = None) -> str:
        worktree = worktree.resolve()
        allowed_root = self.workspace.normalized_worktree_root()
        if worktree != allowed_root and allowed_root not in worktree.parents:
            raise GitTransactionError("commit worktree is outside managed worktree root")
        if not message.strip():
            raise GitTransactionError("commit message cannot be empty")
        safe_paths = self._validate_relative_paths(paths or ["."])
        add_args = ["add", "--", *safe_paths]
        add = await self.executor.run_git(add_args, cwd=worktree, operation="git_add")
        if not add.success:
            raise GitTransactionError(add.error or add.output or "git add failed")
        commit = await self.executor.run_git(["commit", "-m", message[:500]], cwd=worktree, operation="git_commit")
        if not commit.success:
            raise GitTransactionError(commit.error or commit.output or "git commit failed")
        rev = await self.executor.run_git(["rev-parse", "HEAD"], cwd=worktree, operation="git_rev_parse")
        if not rev.success:
            raise GitTransactionError(rev.error or rev.output or "git rev-parse failed")
        return rev.output.strip().splitlines()[-1] if rev.output.strip() else ""


    async def integrate_branch(self, branch: str) -> str:
        """Serialize a previously verified branch into the base repository.

        The executor remains the authority boundary. A dirty base checkout fails
        closed so autonomous integration cannot overwrite unrelated operator work.
        """
        if not self.BRANCH_RE.fullmatch(branch) or ".." in branch or branch.startswith("-"):
            raise GitTransactionError(f"Unsafe git branch name: {branch!r}")
        status = await self.executor.run_git(
            ["status", "--porcelain"],
            cwd=self.workspace.repository_root,
            operation="git_status",
        )
        if not status.success:
            raise GitTransactionError(status.error or status.output or "git status failed")
        if status.output.strip():
            raise GitTransactionError("Base checkout is dirty; verified branch integration fails closed")
        merge = await self.executor.run_git(
            ["merge", "--no-ff", "--no-edit", branch],
            cwd=self.workspace.repository_root,
            operation="git_merge_verified_branch",
        )
        if not merge.success:
            raise GitTransactionError(merge.error or merge.output or "verified branch merge failed")
        rev = await self.executor.run_git(
            ["rev-parse", "HEAD"],
            cwd=self.workspace.repository_root,
            operation="git_integration_rev_parse",
        )
        if not rev.success:
            raise GitTransactionError(rev.error or rev.output or "git rev-parse after integration failed")
        return rev.output.strip().splitlines()[-1] if rev.output.strip() else ""

    async def status_porcelain(self, *, cwd: Path | None = None) -> str:
        root = (cwd or self.workspace.repository_root).resolve()
        obs = await self.executor.run_git(
            ["status", "--porcelain"],
            cwd=root,
            operation="git_status",
        )
        if not obs.success:
            raise GitTransactionError(obs.error or obs.output or "git status failed")
        return obs.output

    async def rev_parse(self, ref: str = "HEAD", *, cwd: Path | None = None) -> str:
        if not ref.strip() or ref.startswith("-") or "\x00" in ref:
            raise GitTransactionError(f"Unsafe git ref: {ref!r}")
        root = (cwd or self.workspace.repository_root).resolve()
        obs = await self.executor.run_git(
            ["rev-parse", ref],
            cwd=root,
            operation="git_rev_parse",
        )
        if not obs.success:
            raise GitTransactionError(obs.error or obs.output or f"git rev-parse {ref} failed")
        return obs.output.strip().splitlines()[-1] if obs.output.strip() else ""

    async def merge_no_commit(self, branch: str) -> EngineeringToolObservation:
        if not self.BRANCH_RE.fullmatch(branch) or ".." in branch or branch.startswith("-"):
            raise GitTransactionError(f"Unsafe git branch name: {branch!r}")
        return await self.executor.run_git(
            ["merge", "--no-ff", "--no-commit", branch],
            cwd=self.workspace.repository_root,
            operation="git_merge_no_commit",
        )

    async def conflicted_files(self) -> list[str]:
        obs = await self.executor.run_git(
            ["diff", "--name-only", "--diff-filter=U", "--"],
            cwd=self.workspace.repository_root,
            operation="git_merge_conflicts",
        )
        if not obs.success:
            raise GitTransactionError(obs.error or obs.output or "git conflict inspection failed")
        return [line.strip() for line in obs.output.splitlines() if line.strip()]

    async def abort_merge(self) -> None:
        obs = await self.executor.run_git(
            ["merge", "--abort"],
            cwd=self.workspace.repository_root,
            operation="git_merge_abort",
        )
        if not obs.success:
            raise GitTransactionError(obs.error or obs.output or "git merge --abort failed")

    async def commit_merge(self, *, message: str | None = None) -> str:
        args = ["commit", "--no-edit"] if not message else ["commit", "-m", message[:500]]
        obs = await self.executor.run_git(
            args,
            cwd=self.workspace.repository_root,
            operation="git_merge_commit",
        )
        if not obs.success:
            raise GitTransactionError(obs.error or obs.output or "merge commit failed")
        return await self.rev_parse("HEAD")

    async def reset_hard(self, ref: str, *, cwd: Path) -> None:
        if not ref.strip() or ref.startswith("-") or "\x00" in ref:
            raise GitTransactionError(f"Unsafe reset ref: {ref!r}")
        target = cwd.resolve()
        allowed_root = self.workspace.normalized_worktree_root()
        if target != self.workspace.repository_root.resolve() and target != allowed_root and allowed_root not in target.parents:
            raise GitTransactionError("reset target is outside managed engineering roots")
        obs = await self.executor.run_git(
            ["reset", "--hard", ref],
            cwd=target,
            operation="git_reset_hard",
        )
        if not obs.success:
            raise GitTransactionError(obs.error or obs.output or "git reset --hard failed")

    async def changed_files(self, worktree: Path) -> list[str]:
        worktree = worktree.resolve()
        allowed_root = self.workspace.normalized_worktree_root()
        if worktree != allowed_root and allowed_root not in worktree.parents:
            raise GitTransactionError("worktree is outside managed worktree root")
        obs = await self.executor.run_git(
            ["diff", "--name-only", self.workspace.base_ref, "--"],
            cwd=worktree,
            operation="git_changed_files",
        )
        if not obs.success:
            raise GitTransactionError(obs.error or obs.output or "git diff --name-only failed")
        return [line.strip() for line in obs.output.splitlines() if line.strip()]

    @staticmethod
    def _validate_relative_paths(paths: list[str]) -> list[str]:
        safe: list[str] = []
        for raw in paths:
            value = str(raw).replace("\\", "/")
            if value == ".":
                safe.append(value)
                continue
            candidate = Path(value)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise GitTransactionError(f"Unsafe git path: {raw!r}")
            safe.append(value)
        return safe

    async def remove_worktree(self, task_id: str, *, force: bool = False) -> None:
        path = self.worktree_path(task_id)
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(path))
        obs = await self.executor.run_git(args, cwd=self.workspace.repository_root, operation="git_worktree_remove")
        if not obs.success:
            raise GitTransactionError(obs.error or obs.output or "git worktree remove failed")
