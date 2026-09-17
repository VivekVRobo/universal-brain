"""
Universal Brain - Content-Addressed Pre-Image Blob Store

Implements M5 Section 13: Content-Addressed Pre-Images.
Stores exact binary pre-images keyed by SHA-256 for files that cannot
be represented as line diffs (binaries, images, archives, encoding-sensitive data).
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Optional


class ContentAddressedBlobStore:
    """Stores and retrieves file pre-images addressed by their SHA-256 hash."""

    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir.resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def store_bytes(self, data: bytes) -> str:
        """Stores bytes into the blob store, returning its SHA-256 digest."""
        digest = hashlib.sha256(data).hexdigest()
        blob_path = self.storage_dir / digest
        if not blob_path.exists():
            temp_path = self.storage_dir / f"{digest}.tmp.{os.getpid()}"
            with open(temp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, blob_path)
        return digest

    def store_file(self, source_path: Path) -> str:
        """Stores a file's content into the blob store, returning its SHA-256 digest."""
        with open(source_path, "rb") as f:
            data = f.read()
        return self.store_bytes(data)

    def get_bytes(self, digest: str) -> Optional[bytes]:
        """Retrieves raw bytes for a given digest."""
        blob_path = self.storage_dir / digest
        if not blob_path.is_file():
            return None
        with open(blob_path, "rb") as f:
            return f.read()

    def restore_file(self, digest: str, destination_path: Path) -> bool:
        """Restores a blob to a destination file atomically, verifying the restored hash."""
        data = self.get_bytes(digest)
        if data is None:
            return False

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temp_dest = destination_path.parent / f".tmp.{destination_path.name}.{digest[:8]}"
        with open(temp_dest, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        # Verify hash before replacing
        check_hasher = hashlib.sha256(data).hexdigest()
        if check_hasher != digest:
            if temp_dest.exists():
                temp_dest.unlink()
            return False

        os.replace(temp_dest, destination_path)
        return True
