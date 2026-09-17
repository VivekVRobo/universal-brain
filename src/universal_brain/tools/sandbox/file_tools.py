"""
Universal Brain - Production Filesystem Tools

Implements M5 Sections 40 and 87:
Concrete BaseTool implementations for reading, writing, patching, and deleting
files inside a bounded workspace with verified preflight reversibility.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID

from universal_brain.kernel.events import ActionClass
from universal_brain.tools.base import BaseTool, ReversibilityClass, ToolResult
from universal_brain.tools.sandbox.confinement import confine_path
from universal_brain.tools.sandbox.manifests import hash_file
from universal_brain.tools.sandbox.workspace import WorkspaceCheckpoint, WorkspaceTransactionManager


class FileReadTool(BaseTool):
    """Safe bounded file reader within workspace (ActionClass A0 - Observe only)."""

    name: str = "read_file"
    action_class: ActionClass = ActionClass.A0
    description: str = "Reads file content safely from within the workspace."
    reversibility_class: ReversibilityClass = ReversibilityClass.VERIFIED_REVERSIBLE

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def preflight_check(self, args: Dict[str, Any], target_resource: str = "*") -> bool:
        target = args.get("target") or target_resource
        confine_path(target, self.workspace_root)
        return True

    def execute(self, args: Dict[str, Any], target_resource: str = "*") -> ToolResult:
        target = args.get("target") or target_resource
        canonical = confine_path(target, self.workspace_root)

        if not canonical.is_file():
            return ToolResult(
                success=False,
                output=None,
                error_message=f"File '{target}' not found.",
                reversibility_class=self.reversibility_class,
            )

        with open(canonical, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        file_hash = hash_file(canonical)
        return ToolResult(
            success=True,
            output=content,
            evidence={"sha256": file_hash, "size_bytes": len(content)},
            reversibility_class=self.reversibility_class,
            post_digest=file_hash,
        )

    def rollback(self, rollback_data: Dict[str, Any]) -> bool:
        return True  # Read has no side-effects


class FileWriteTool(BaseTool):
    """Atomic file writer with preflight reversibility (ActionClass A1 - Reversible)."""

    name: str = "write_file"
    action_class: ActionClass = ActionClass.A1
    description: str = "Writes file atomically inside workspace with verified reversibility."
    reversibility_class: ReversibilityClass = ReversibilityClass.VERIFIED_REVERSIBLE

    def __init__(self, tx_manager: WorkspaceTransactionManager) -> None:
        self.tx_manager = tx_manager
        self._staged_checkpoint: Optional[WorkspaceCheckpoint] = None

    def preflight_check(self, args: Dict[str, Any], target_resource: str = "*") -> bool:
        target = args.get("target") or target_resource
        content = args.get("content", "")
        self._staged_checkpoint = self.tx_manager.create_text_checkpoint(target, content)
        return self._staged_checkpoint.reversibility_class == ReversibilityClass.VERIFIED_REVERSIBLE

    def execute(self, args: Dict[str, Any], target_resource: str = "*") -> ToolResult:
        target = args.get("target") or target_resource
        content = args.get("content", "")

        if not self._staged_checkpoint:
            self._staged_checkpoint = self.tx_manager.create_text_checkpoint(target, content)

        checkpoint = self._staged_checkpoint
        self.tx_manager.apply_checkpoint(checkpoint, content_override=content)

        return ToolResult(
            success=True,
            output=f"Successfully wrote {len(content)} characters to '{target}'.",
            evidence={
                "checkpoint_id": str(checkpoint.checkpoint_id),
                "pre_hash": checkpoint.pre_hashes.get(target),
                "post_hash": checkpoint.expected_post_hashes.get(target),
            },
            rollback_data={"checkpoint": checkpoint.model_dump(mode="json")},
            reversibility_class=checkpoint.reversibility_class,
            checkpoint_id=str(checkpoint.checkpoint_id),
            pre_digest=checkpoint.pre_hashes.get(target),
            post_digest=checkpoint.expected_post_hashes.get(target),
        )

    def rollback(self, rollback_data: Dict[str, Any]) -> bool:
        cp_data = rollback_data.get("checkpoint")
        if not cp_data:
            return False
        checkpoint = WorkspaceCheckpoint.model_validate(cp_data)
        return self.tx_manager.rollback_checkpoint(checkpoint)

    def verify_rollback(self, rollback_data: Dict[str, Any]) -> bool:
        cp_data = rollback_data.get("checkpoint")
        if not cp_data:
            return False
        try:
            checkpoint = WorkspaceCheckpoint.model_validate(cp_data)
        except Exception:
            return False
        return self.tx_manager.verify_checkpoint_restored(checkpoint)


class FilePatchTool(BaseTool):
    """Line-oriented diff patch tool with dry-run reversibility (ActionClass A1)."""

    name: str = "patch_file"
    action_class: ActionClass = ActionClass.A1
    description: str = "Applies text patches with mathematical dry-run inverse verification."
    reversibility_class: ReversibilityClass = ReversibilityClass.VERIFIED_REVERSIBLE

    def __init__(self, tx_manager: WorkspaceTransactionManager) -> None:
        self.tx_manager = tx_manager
        self._staged_checkpoint: Optional[WorkspaceCheckpoint] = None

    def preflight_check(self, args: Dict[str, Any], target_resource: str = "*") -> bool:
        target = args.get("target") or target_resource
        new_content = args.get("new_content", "")
        self._staged_checkpoint = self.tx_manager.create_text_checkpoint(target, new_content)
        return self._staged_checkpoint.reversibility_class == ReversibilityClass.VERIFIED_REVERSIBLE

    def execute(self, args: Dict[str, Any], target_resource: str = "*") -> ToolResult:
        target = args.get("target") or target_resource
        new_content = args.get("new_content", "")

        if not self._staged_checkpoint:
            self._staged_checkpoint = self.tx_manager.create_text_checkpoint(target, new_content)

        checkpoint = self._staged_checkpoint
        self.tx_manager.apply_checkpoint(checkpoint, content_override=new_content)

        return ToolResult(
            success=True,
            output=f"Successfully patched '{target}'.",
            evidence={
                "checkpoint_id": str(checkpoint.checkpoint_id),
                "forward_delta": checkpoint.forward_delta,
                "reverse_delta": checkpoint.reverse_delta,
                "post_hash": checkpoint.expected_post_hashes.get(target),
            },
            rollback_data={"checkpoint": checkpoint.model_dump(mode="json")},
            reversibility_class=checkpoint.reversibility_class,
            checkpoint_id=str(checkpoint.checkpoint_id),
            pre_digest=checkpoint.pre_hashes.get(target),
            post_digest=checkpoint.expected_post_hashes.get(target),
        )

    def rollback(self, rollback_data: Dict[str, Any]) -> bool:
        cp_data = rollback_data.get("checkpoint")
        if not cp_data:
            return False
        checkpoint = WorkspaceCheckpoint.model_validate(cp_data)
        return self.tx_manager.rollback_checkpoint(checkpoint)

    def verify_rollback(self, rollback_data: Dict[str, Any]) -> bool:
        cp_data = rollback_data.get("checkpoint")
        if not cp_data:
            return False
        try:
            checkpoint = WorkspaceCheckpoint.model_validate(cp_data)
        except Exception:
            return False
        return self.tx_manager.verify_checkpoint_restored(checkpoint)


class FileDeleteTool(BaseTool):
    """File deletion with safe tombstone backup for micro-reversibility (ActionClass A1)."""

    name: str = "delete_file"
    action_class: ActionClass = ActionClass.A1
    description: str = "Deletes file with automatic tombstone archiving for deterministic restore."
    reversibility_class: ReversibilityClass = ReversibilityClass.VERIFIED_REVERSIBLE

    def __init__(self, tx_manager: WorkspaceTransactionManager) -> None:
        self.tx_manager = tx_manager
        self._staged_checkpoint: Optional[WorkspaceCheckpoint] = None

    def preflight_check(self, args: Dict[str, Any], target_resource: str = "*") -> bool:
        target = args.get("target") or target_resource
        self._staged_checkpoint = self.tx_manager.create_delete_checkpoint(target)
        return self._staged_checkpoint.reversibility_class == ReversibilityClass.VERIFIED_REVERSIBLE

    def execute(self, args: Dict[str, Any], target_resource: str = "*") -> ToolResult:
        target = args.get("target") or target_resource

        if not self._staged_checkpoint:
            self._staged_checkpoint = self.tx_manager.create_delete_checkpoint(target)

        checkpoint = self._staged_checkpoint
        self.tx_manager.apply_checkpoint(checkpoint)

        return ToolResult(
            success=True,
            output=f"Successfully deleted '{target}' (tombstone preserved).",
            evidence={
                "checkpoint_id": str(checkpoint.checkpoint_id),
                "tombstone": checkpoint.tombstone_refs.get(target),
                "pre_hash": checkpoint.pre_hashes.get(target),
            },
            rollback_data={"checkpoint": checkpoint.model_dump(mode="json")},
            reversibility_class=checkpoint.reversibility_class,
            checkpoint_id=str(checkpoint.checkpoint_id),
            pre_digest=checkpoint.pre_hashes.get(target),
            post_digest="",
        )

    def rollback(self, rollback_data: Dict[str, Any]) -> bool:
        cp_data = rollback_data.get("checkpoint")
        if not cp_data:
            return False
        checkpoint = WorkspaceCheckpoint.model_validate(cp_data)
        return self.tx_manager.rollback_checkpoint(checkpoint)

    def verify_rollback(self, rollback_data: Dict[str, Any]) -> bool:
        cp_data = rollback_data.get("checkpoint")
        if not cp_data:
            return False
        try:
            checkpoint = WorkspaceCheckpoint.model_validate(cp_data)
        except Exception:
            return False
        return self.tx_manager.verify_checkpoint_restored(checkpoint)
