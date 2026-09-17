"""
Universal Brain - Workspace Transaction Manager

Implements M5 Sections 8, 10, 11, 14, 18, 19, 21 and ADR-0008:
Coordinates atomic workspace transactions, preflight reversibility verification,
sliding-window checkpoint retention, and cryptographic rollback proofs.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from universal_brain.kernel.errors import (
    RollbackPreflightError,
    UniversalBrainError,
)
from universal_brain.tools.base import ReversibilityClass
from universal_brain.tools.sandbox.confinement import confine_path
from universal_brain.tools.sandbox.manifests import ManifestEngine, hash_file
from universal_brain.tools.sandbox.patching import TextPatchReversibilityEngine
from universal_brain.tools.sandbox.restore import ContentAddressedBlobStore
from universal_brain.tools.sandbox.schemas import (
    MutationType,
    StateManifest,
    Workspace,
    WorkspaceCheckpoint,
    WorkspaceStatus,
)


class StaleCheckpointError(UniversalBrainError):
    """Raised when target file hash changed externally between preflight and execution."""

    def __init__(self, path: str, recorded_hash: str, actual_hash: str) -> None:
        super().__init__(
            f"STALE_CHECKPOINT: Target '{path}' was modified concurrently. "
            f"Recorded preflight={recorded_hash}, Actual={actual_hash}."
        )


class RollbackExecutionError(UniversalBrainError):
    """Raised when a rollback operation fails to restore the exact pre-state."""

    def __init__(self, target: str, expected_hash: str, actual_hash: str) -> None:
        super().__init__(
            f"ROLLBACK_FAILED: Target '{target}' could not be restored to pre-state. "
            f"Expected SHA-256={expected_hash}, Actual SHA-256={actual_hash}."
        )


class SlidingWindowPruner:
    """Limits active rollback checkpoints to max 10, archiving older entries to disk."""

    def __init__(self, archive_dir: Path, max_active: int = 10) -> None:
        self.archive_dir = archive_dir.resolve()
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.max_active = max_active

    def prune(self, active_checkpoints: List[WorkspaceCheckpoint]) -> List[WorkspaceCheckpoint]:
        """Compresses and archives checkpoints older than max_active."""
        if len(active_checkpoints) <= self.max_active:
            return active_checkpoints

        excess_count = len(active_checkpoints) - self.max_active
        to_archive = active_checkpoints[:excess_count]
        remaining = active_checkpoints[excess_count:]

        for cp in to_archive:
            archive_path = self.archive_dir / f"checkpoint_{cp.checkpoint_id}.json.gz"
            data_bytes = json.dumps(cp.model_dump(mode="json"), sort_keys=True).encode("utf-8")
            with gzip.open(archive_path, "wb") as f:
                f.write(data_bytes)

        return remaining


class WorkspaceTransactionManager:
    """Governs execution workspaces, mutation staging, and verified rollback."""

    def __init__(
        self,
        workspace_root: Path,
        project_id: UUID,
        task_id: UUID,
        blob_store_dir: Optional[Path] = None,
        tombstone_dir: Optional[Path] = None,
        archive_dir: Optional[Path] = None,
        max_active_checkpoints: int = 10,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

        self.project_id = project_id
        self.task_id = task_id

        self.blob_store = ContentAddressedBlobStore(
            blob_store_dir or (self.workspace_root / ".brain" / "blobs")
        )
        self.tombstone_dir = tombstone_dir or (self.workspace_root / ".brain" / "tombstones")
        self.tombstone_dir.mkdir(parents=True, exist_ok=True)

        self.pruner = SlidingWindowPruner(
            archive_dir or (self.workspace_root / ".brain" / "archives"),
            max_active=max_active_checkpoints,
        )

        self.workspace = Workspace(
            project_id=project_id,
            task_id=task_id,
            root_path=self.workspace_root,
            status=WorkspaceStatus.READY,
        )

    def create_text_checkpoint(
        self,
        target_relative_path: str,
        new_content: str,
    ) -> WorkspaceCheckpoint:
        """
        Stages a text mutation and computes mathematical reversibility proof.
        Validates path confinement and optimism concurrency pre-state.
        """
        canonical_target = confine_path(target_relative_path, self.workspace_root)
        self.workspace.status = WorkspaceStatus.STAGING

        # 1. Capture pre-state
        original_content = ""
        pre_hash = ""
        blob_ref = ""
        if canonical_target.is_file():
            with open(canonical_target, "rb") as f:
                raw_bytes = f.read()
            original_content = raw_bytes.decode("utf-8", errors="replace")
            pre_hash = hash_file(canonical_target)
            blob_ref = self.blob_store.store_bytes(raw_bytes)

        # 2. Preflight reversibility check
        rel_target = str(canonical_target.relative_to(self.workspace_root)).replace("\\", "/")
        rev_class, forward_diff, reverse_diff, post_sha = TextPatchReversibilityEngine.preflight_verify(
            original_content,
            new_content,
            filename=rel_target,
        )

        pre_manifest = ManifestEngine.capture_manifest([canonical_target], self.workspace_root)

        checkpoint = WorkspaceCheckpoint(
            workspace_id=self.workspace.workspace_id,
            task_id=self.task_id,
            operation_type=MutationType.TEXT_PATCH,
            targets=[rel_target],
            pre_state_manifest=pre_manifest,
            forward_delta=forward_diff,
            reverse_delta=reverse_diff,
            blob_refs={rel_target: blob_ref} if blob_ref else {},
            pre_hashes={rel_target: pre_hash},
            expected_post_hashes={rel_target: post_sha},
            reversibility_class=rev_class,
            reversibility_proof={
                "engine": "TextPatchReversibilityEngine",
                "dry_run": "PASS",
                "verified_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        checkpoint.checkpoint_digest = checkpoint.calculate_digest()

        self.workspace.status = WorkspaceStatus.PREFLIGHTED
        return checkpoint

    def create_binary_checkpoint(
        self,
        target_relative_path: str,
        new_bytes: bytes,
    ) -> WorkspaceCheckpoint:
        """Stages binary / artifact replacement backed by content-addressed pre-image."""
        canonical_target = confine_path(target_relative_path, self.workspace_root)
        self.workspace.status = WorkspaceStatus.STAGING

        rel_target = str(canonical_target.relative_to(self.workspace_root)).replace("\\", "/")
        pre_hash = hash_file(canonical_target) if canonical_target.is_file() else ""
        blob_ref = ""
        if canonical_target.is_file():
            blob_ref = self.blob_store.store_file(canonical_target)

        import hashlib
        post_sha = hashlib.sha256(new_bytes).hexdigest()
        pre_manifest = ManifestEngine.capture_manifest([canonical_target], self.workspace_root)

        checkpoint = WorkspaceCheckpoint(
            workspace_id=self.workspace.workspace_id,
            task_id=self.task_id,
            operation_type=MutationType.BINARY_REPLACE,
            targets=[rel_target],
            pre_state_manifest=pre_manifest,
            blob_refs={rel_target: blob_ref} if blob_ref else {},
            pre_hashes={rel_target: pre_hash},
            expected_post_hashes={rel_target: post_sha},
            reversibility_class=ReversibilityClass.VERIFIED_REVERSIBLE,
            reversibility_proof={
                "mechanism": "content_addressed_pre_image",
                "pre_blob": blob_ref,
            },
        )
        checkpoint.checkpoint_digest = checkpoint.calculate_digest()
        self.workspace.status = WorkspaceStatus.PREFLIGHTED
        return checkpoint

    def create_delete_checkpoint(
        self,
        target_relative_path: str,
    ) -> WorkspaceCheckpoint:
        """Stages file deletion by creating a safe tombstone backup."""
        canonical_target = confine_path(target_relative_path, self.workspace_root)
        if not canonical_target.is_file():
            raise FileNotFoundError(f"Cannot stage deletion for nonexistent file: '{canonical_target}'")

        self.workspace.status = WorkspaceStatus.STAGING
        rel_target = str(canonical_target.relative_to(self.workspace_root)).replace("\\", "/")
        pre_hash = hash_file(canonical_target)

        # Store pre-image in blob store
        blob_ref = self.blob_store.store_file(canonical_target)

        # Store tombstone backup
        tombstone_name = f"{uuid4()}_{canonical_target.name}"
        tombstone_path = self.tombstone_dir / tombstone_name
        shutil.copy2(canonical_target, tombstone_path)

        pre_manifest = ManifestEngine.capture_manifest([canonical_target], self.workspace_root)

        checkpoint = WorkspaceCheckpoint(
            workspace_id=self.workspace.workspace_id,
            task_id=self.task_id,
            operation_type=MutationType.FILE_DELETE,
            targets=[rel_target],
            pre_state_manifest=pre_manifest,
            tombstone_refs={rel_target: str(tombstone_path)},
            blob_refs={rel_target: blob_ref},
            pre_hashes={rel_target: pre_hash},
            expected_post_hashes={rel_target: ""},
            reversibility_class=ReversibilityClass.VERIFIED_REVERSIBLE,
            reversibility_proof={
                "tombstone": str(tombstone_path),
                "blob_sha256": blob_ref,
            },
        )
        checkpoint.checkpoint_digest = checkpoint.calculate_digest()
        self.workspace.status = WorkspaceStatus.PREFLIGHTED
        return checkpoint

    def apply_checkpoint(self, checkpoint: WorkspaceCheckpoint, content_override: Optional[Union[str, bytes]] = None) -> bool:
        """
        Applies staged mutation atomically with optimistic concurrency verification.
        (M5 Section 14, 19).
        """
        # 1. Verify Checkpoint Digest Integrity
        if not checkpoint.verify_digest():
            raise RollbackPreflightError("Checkpoint digest verification failed: checkpoint data was corrupted.")

        self.workspace.status = WorkspaceStatus.EXECUTING

        for target in checkpoint.targets:
            canonical = confine_path(target, self.workspace_root)
            current_hash = hash_file(canonical) if canonical.is_file() else ""

            # Optimistic Concurrency Check (M5 Section 19)
            expected_pre = checkpoint.pre_hashes.get(target, "")
            if current_hash != expected_pre:
                self.workspace.status = WorkspaceStatus.FAILED_SAFE
                raise StaleCheckpointError(target, expected_pre, current_hash)

            # Apply Mutation
            canonical.parent.mkdir(parents=True, exist_ok=True)
            temp_path = canonical.parent / f".tmp.{canonical.name}.{uuid4().hex[:8]}"

            if checkpoint.operation_type == MutationType.TEXT_PATCH:
                new_text = str(content_override) if content_override is not None else ""
                with open(temp_path, "wb") as f:
                    f.write(new_text.encode("utf-8"))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, canonical)

            elif checkpoint.operation_type == MutationType.BINARY_REPLACE:
                new_bytes = content_override if isinstance(content_override, bytes) else b""
                with open(temp_path, "wb") as f:
                    f.write(new_bytes)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, canonical)

            elif checkpoint.operation_type == MutationType.FILE_DELETE:
                if canonical.is_file():
                    canonical.unlink()

            # Verify post hash
            observed_post = hash_file(canonical) if canonical.is_file() else ""
            expected_post = checkpoint.expected_post_hashes.get(target, "")
            if observed_post != expected_post:
                # Immediate safety abort: restore pre-state
                self.rollback_checkpoint(checkpoint)
                raise UniversalBrainError(
                    f"Post-apply verification failed for '{target}': "
                    f"Observed SHA={observed_post}, Expected SHA={expected_post}."
                )

        # Record post manifest
        checkpoint.post_state_manifest = ManifestEngine.capture_manifest(
            [confine_path(t, self.workspace_root) for t in checkpoint.targets],
            self.workspace_root,
        )

        # Register checkpoint & prune
        self.workspace.active_checkpoints.append(checkpoint)
        self.workspace.active_checkpoints = self.pruner.prune(self.workspace.active_checkpoints)
        self.workspace.status = WorkspaceStatus.READY
        return True

    def verify_checkpoint_restored(self, checkpoint: WorkspaceCheckpoint) -> bool:
        """Verify that every checkpoint target exactly matches its recorded pre-state."""
        if not checkpoint.verify_digest():
            return False
        for target in checkpoint.targets:
            canonical = confine_path(target, self.workspace_root)
            observed_hash = hash_file(canonical) if canonical.is_file() else ""
            if observed_hash != checkpoint.pre_hashes.get(target, ""):
                return False
        return True

    def rollback_checkpoint(self, checkpoint: WorkspaceCheckpoint) -> bool:
        """
        Executes formal rollback and verifies restored-state postcondition.
        (M5 Section 70, 71, Invariant M5-INV-04).
        """
        self.workspace.status = WorkspaceStatus.EXECUTING

        for target in reversed(checkpoint.targets):
            canonical = confine_path(target, self.workspace_root)
            expected_pre_hash = checkpoint.pre_hashes.get(target, "")

            # If file was newly created by this checkpoint, rollback means unlinking it
            if not expected_pre_hash:
                if canonical.exists():
                    if canonical.is_file():
                        canonical.unlink()
                    elif canonical.is_dir():
                        shutil.rmtree(canonical)
            else:
                # 1. Restore from Tombstone if delete
                if checkpoint.operation_type == MutationType.FILE_DELETE:
                    tombstone = checkpoint.tombstone_refs.get(target)
                    if tombstone and Path(tombstone).is_file():
                        canonical.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(tombstone, canonical)
                    else:
                        # Fallback to blob store
                        blob_ref = checkpoint.blob_refs.get(target)
                        if blob_ref:
                            self.blob_store.restore_file(blob_ref, canonical)

                # 2. Restore from Blob Store or Reverse Diff
                elif checkpoint.operation_type in [MutationType.TEXT_PATCH, MutationType.BINARY_REPLACE]:
                    blob_ref = checkpoint.blob_refs.get(target)
                    if blob_ref:
                        self.blob_store.restore_file(blob_ref, canonical)
                    elif checkpoint.reverse_delta and canonical.is_file():
                        with open(canonical, "r", encoding="utf-8", errors="replace") as f:
                            current_content = f.read()
                        restored = TextPatchReversibilityEngine.apply_diff(current_content, checkpoint.reverse_delta)
                        if restored is not None:
                            with open(canonical, "wb") as f:
                                f.write(restored.encode("utf-8"))

            # 3. Cryptographic Restored-State Verification (M5-INV-04)
            restored_hash = hash_file(canonical) if canonical.is_file() else ""
            if restored_hash != expected_pre_hash:
                self.workspace.status = WorkspaceStatus.RECOVERY_REQUIRED
                raise RollbackExecutionError(target, expected_pre_hash, restored_hash)

        self.workspace.status = WorkspaceStatus.ROLLED_BACK
        return True
