"""
Universal Brain - State Manifest Engine

Implements M5 Section 12: Canonical State Manifests.
Captures cryptographic digests and metadata for filesystem targets
prior to mutation to guarantee mathematical rollback validation.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import List, Union

from universal_brain.tools.sandbox.confinement import confine_path
from universal_brain.tools.sandbox.schemas import ManifestItem, StateManifest


def hash_file_bytes(data: bytes) -> str:
    """Computes SHA-256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def hash_file(file_path: Path) -> str:
    """Computes SHA-256 hex digest of a file on disk."""
    if not file_path.is_file():
        return hashlib.sha256(b"").hexdigest()
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class ManifestEngine:
    """Builds cryptographic state manifests for workspace files."""

    @staticmethod
    def capture_file(file_path: Path, workspace_root: Path) -> ManifestItem:
        """Captures metadata and SHA-256 for a single file."""
        canonical = confine_path(file_path, workspace_root)
        rel_path = str(canonical.relative_to(workspace_root)).replace("\\", "/")

        if not canonical.exists():
            return ManifestItem(
                relative_path=rel_path,
                object_type="missing",
                size_bytes=0,
                sha256="",
                permissions=0,
                mtime=0.0,
            )

        stat = canonical.stat()
        obj_type = "directory" if canonical.is_dir() else ("symlink" if canonical.is_symlink() else "file")
        digest = hash_file(canonical) if obj_type == "file" else ""

        return ManifestItem(
            relative_path=rel_path,
            object_type=obj_type,
            size_bytes=stat.st_size if obj_type == "file" else 0,
            sha256=digest,
            permissions=stat.st_mode,
            mtime=stat.st_mtime,
        )

    @classmethod
    def capture_manifest(cls, targets: List[Union[str, Path]], workspace_root: Path) -> StateManifest:
        """Captures manifest for a specific list of target paths."""
        items = {}
        for target in targets:
            canonical = confine_path(target, workspace_root)
            item = cls.capture_file(canonical, workspace_root)
            items[item.relative_path] = item

        manifest = StateManifest(items=items)
        manifest.manifest_digest = manifest.compute_digest()
        return manifest
