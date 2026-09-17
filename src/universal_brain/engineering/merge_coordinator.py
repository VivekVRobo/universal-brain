"""Serialized verified Git merge coordination for Universal Brain V5.2.

Traceability: REQ-ENG-028, REQ-ENG-017, ALN-007, ALN-016, ALN-020.
A source branch is not integrated merely because a worker says it is verified.
The coordinator binds verification to an immutable branch commit, performs a
no-commit merge under a serialization lock, runs integration verification on the
actual merged tree, and commits only after acceptance.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from universal_brain.executive.schemas import TaskNode

from pydantic import BaseModel, Field

from .git_engine import GitTransactionEngine, GitTransactionError


class MergeVerificationDecision(BaseModel):
    accepted: bool
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str = ""


class IntegrationVerifier(Protocol):
    async def verify_integration(
        self, *, branch: str, source_commit: str, node: TaskNode
    ) -> MergeVerificationDecision: ...


class MergeIntegrationResult(BaseModel):
    branch: str
    source_commit: str
    base_commit_before: str
    integrated_commit: str | None = None
    accepted: bool = False
    conflict_files: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str = ""


class SerializedMergeCoordinator:
    def __init__(self, git: GitTransactionEngine, verifier: IntegrationVerifier) -> None:
        self.git = git
        self.verifier = verifier
        self._lock = asyncio.Lock()

    async def integrate_verified_branch(
        self,
        *,
        branch: str,
        verified_source_commit: str,
        node: TaskNode,
    ) -> MergeIntegrationResult:
        async with self._lock:
            status = await self.git.status_porcelain()
            if status.strip():
                return MergeIntegrationResult(
                    branch=branch,
                    source_commit=verified_source_commit,
                    base_commit_before=await self.git.rev_parse("HEAD"),
                    accepted=False,
                    reason="Base checkout is dirty; integration fails closed",
                )

            base_before = await self.git.rev_parse("HEAD")
            actual_source = await self.git.rev_parse(branch)
            if actual_source != verified_source_commit:
                return MergeIntegrationResult(
                    branch=branch,
                    source_commit=verified_source_commit,
                    base_commit_before=base_before,
                    accepted=False,
                    reason=(
                        "Verified source commit drifted before integration: "
                        f"expected {verified_source_commit}, found {actual_source}"
                    ),
                )

            merge = await self.git.merge_no_commit(branch)
            conflicts = await self.git.conflicted_files()
            if conflicts:
                await self._safe_abort()
                return MergeIntegrationResult(
                    branch=branch,
                    source_commit=verified_source_commit,
                    base_commit_before=base_before,
                    accepted=False,
                    conflict_files=conflicts,
                    reason="Merge conflict requires explicit resolution/replanning",
                )
            if not merge.success:
                await self._safe_abort()
                return MergeIntegrationResult(
                    branch=branch,
                    source_commit=verified_source_commit,
                    base_commit_before=base_before,
                    accepted=False,
                    reason=merge.error or merge.output or "git merge --no-commit failed",
                )

            decision = await self.verifier.verify_integration(
                branch=branch,
                source_commit=verified_source_commit,
                node=node,
            )
            if not decision.accepted:
                await self._safe_abort()
                return MergeIntegrationResult(
                    branch=branch,
                    source_commit=verified_source_commit,
                    base_commit_before=base_before,
                    accepted=False,
                    evidence_refs=decision.evidence_refs,
                    reason=f"Integration verification rejected merged tree: {decision.reason}",
                )

            try:
                integrated = await self.git.commit_merge(message=f"Integrate verified {branch}")
            except Exception:
                await self._safe_abort()
                raise
            return MergeIntegrationResult(
                branch=branch,
                source_commit=verified_source_commit,
                base_commit_before=base_before,
                integrated_commit=integrated,
                accepted=True,
                evidence_refs=decision.evidence_refs,
                reason="Verified branch integrated after merged-tree verification",
            )

    async def _safe_abort(self) -> None:
        try:
            await self.git.abort_merge()
        except GitTransactionError:
            # Preserve the original integration failure while leaving recovery to
            # the existing checkpoint/recovery path. Callers should surface both
            # states through audit/observability.
            pass


class ExecutableMergedTreeVerifier:
    """Bridge the existing executable verification engine to merge coordination."""

    def __init__(self, adapter) -> None:
        self.adapter = adapter

    async def verify_integration(
        self,
        *,
        branch: str,
        source_commit: str,
        node: TaskNode,
    ) -> MergeVerificationDecision:
        from uuid import uuid4
        from universal_brain.intelligence.schemas import NormalizedModelResult

        result = NormalizedModelResult(
            request_id=uuid4(),
            model_key="deterministic/integration-verifier",
            route_id="engineering-verification",
            output_text=f"Verify merged tree for {branch}@{source_commit}",
        )
        decision = await self.adapter.verify(node, result)
        return MergeVerificationDecision(
            accepted=bool(decision.accepted),
            evidence_refs=list(decision.evidence_refs),
            reason=decision.reason,
        )
