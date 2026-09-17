"""Dependency remediation with deterministic rollback for Universal Brain V5.2.

Traceability: REQ-ENG-029, REQ-ENG-019, ALN-007, ALN-016, ALN-020.
Repair commands are taken only from a diagnosed plan, executed through an injected
authority-gated backend, and rolled back to a captured Git commit if execution or
post-remediation verification fails.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from .dependency import DependencyRepairPlan
from .git_engine import GitTransactionEngine
from .schemas import EngineeringToolObservation


class DependencyCommandExecutor(Protocol):
    async def run_dependency_command(
        self,
        command: list[str],
        *,
        cwd: Path,
        operation: str,
    ) -> EngineeringToolObservation: ...


class DependencyPostVerifier(Protocol):
    async def verify_dependency_state(self, *, cwd: Path) -> tuple[bool, list[str], str]: ...


class DependencyRemediationResult(BaseModel):
    accepted: bool
    baseline_commit: str
    commands_executed: list[list[str]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    rolled_back: bool = False
    reason: str = ""


class DependencyRemediationCoordinator:
    def __init__(
        self,
        *,
        git: GitTransactionEngine,
        executor: DependencyCommandExecutor,
        verifier: DependencyPostVerifier,
    ) -> None:
        self.git = git
        self.executor = executor
        self.verifier = verifier

    async def remediate(
        self,
        plan: DependencyRepairPlan,
        *,
        worktree: Path,
        manifest_review_approved: bool,
    ) -> DependencyRemediationResult:
        worktree = worktree.resolve()
        if plan.requires_manifest_review and not manifest_review_approved:
            baseline = await self.git.rev_parse("HEAD", cwd=worktree)
            return DependencyRemediationResult(
                accepted=False,
                baseline_commit=baseline,
                reason="Dependency repair requires manifest review/authorization",
            )
        if not plan.suggested_commands:
            baseline = await self.git.rev_parse("HEAD", cwd=worktree)
            return DependencyRemediationResult(
                accepted=False,
                baseline_commit=baseline,
                reason="No deterministic dependency repair command is available",
            )

        status = await self.git.status_porcelain(cwd=worktree)
        if status.strip():
            baseline = await self.git.rev_parse("HEAD", cwd=worktree)
            return DependencyRemediationResult(
                accepted=False,
                baseline_commit=baseline,
                reason="Dependency remediation requires a clean isolated worktree",
            )

        baseline = await self.git.rev_parse("HEAD", cwd=worktree)
        executed: list[list[str]] = []
        evidence_refs: list[str] = []
        for index, command in enumerate(plan.suggested_commands, start=1):
            observation = await self.executor.run_dependency_command(
                list(command),
                cwd=worktree,
                operation=f"dependency_repair_{plan.ecosystem.value}_{index}",
            )
            executed.append(list(command))
            if observation.evidence.get("command_id"):
                evidence_refs.append(f"tool://run_command/{observation.evidence['command_id']}")
            if not observation.success:
                await self.git.reset_hard(baseline, cwd=worktree)
                return DependencyRemediationResult(
                    accepted=False,
                    baseline_commit=baseline,
                    commands_executed=executed,
                    evidence_refs=evidence_refs,
                    rolled_back=True,
                    reason=observation.error or observation.output or "dependency command failed",
                )

        verified, verify_evidence, reason = await self.verifier.verify_dependency_state(cwd=worktree)
        evidence_refs.extend(verify_evidence)
        if not verified:
            await self.git.reset_hard(baseline, cwd=worktree)
            return DependencyRemediationResult(
                accepted=False,
                baseline_commit=baseline,
                commands_executed=executed,
                evidence_refs=evidence_refs,
                rolled_back=True,
                reason=f"Post-remediation verification failed: {reason}",
            )

        return DependencyRemediationResult(
            accepted=True,
            baseline_commit=baseline,
            commands_executed=executed,
            evidence_refs=evidence_refs,
            reason="Dependency remediation verified; changes remain reviewable in isolated worktree",
        )
