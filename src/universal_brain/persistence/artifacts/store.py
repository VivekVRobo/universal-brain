"""
Universal Brain - Content-Addressed Artifact Store

Implements M6 Sections 47-52 and Invariant M6-INV-14:
Content-addressed binary storage keyed by cryptographic SHA-256 digests
with atomic write finalization (temp -> verify -> atomic rename).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional, Union

from universal_brain.config import settings
from universal_brain.persistence.errors import IntegrityFailureError


class ContentAddressedArtifactStore:
    """Content-addressed filesystem blob store keyed by SHA-256."""

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        self.root_dir = (root_dir or settings.evidence_dir).resolve()
        self.temp_dir = self.root_dir / ".tmp"
        self.blobs_dir = self.root_dir / "sha256"

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.blobs_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_blob_path(self, digest: str) -> Path:
        """Layout: root_dir/sha256/ab/cd/<full_digest>"""
        if len(digest) < 4:
            return self.blobs_dir / digest
        prefix1 = digest[:2]
        prefix2 = digest[2:4]
        return self.blobs_dir / prefix1 / prefix2 / digest

    def store_bytes(self, data: bytes) -> str:
        """
        Atomically stores data bytes under its SHA-256 digest.
        Returns the hex digest.
        """
        digest = hashlib.sha256(data).hexdigest()
        target_path = self._resolve_blob_path(digest)

        if target_path.is_file():
            # Already exists (deduplication)
            return digest

        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.temp_dir / f"{digest}.tmp.{os.getpid()}"

        try:
            with open(temp_file, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

            # Verification before commit
            with open(temp_file, "rb") as f:
                actual_digest = hashlib.sha256(f.read()).hexdigest()

            if actual_digest != digest:
                raise IntegrityFailureError(f"Artifact digest mismatch: expected {digest}, got {actual_digest}")

            os.replace(temp_file, target_path)
            return digest
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

    def get_bytes(self, digest: str) -> Optional[bytes]:
        """Retrieves raw bytes for digest, or None if missing."""
        path = self._resolve_blob_path(digest)
        if not path.is_file():
            return None
        with open(path, "rb") as f:
            return f.read()

    def get_path(self, digest: str) -> Optional[Path]:
        """Returns canonical file path for digest if it exists."""
        path = self._resolve_blob_path(digest)
        return path if path.is_file() else None

    def exists(self, digest: str) -> bool:
        """Checks if a blob is present on disk."""
        return self._resolve_blob_path(digest).is_file()
