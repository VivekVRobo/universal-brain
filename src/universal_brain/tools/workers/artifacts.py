"""
Universal Brain - Worker Artifact Intake & Integrity Validator

Implements M5 Sections 56 and 64:
Validates remote worker artifact hashes and enforces safe archive extraction
boundaries to prevent path traversal attacks during file intake.
"""

from __future__ import annotations

import hashlib
import os
import tarfile
import zipfile
from pathlib import Path
from typing import BinaryIO, Optional, Union

from universal_brain.kernel.errors import UniversalBrainError
from universal_brain.tools.sandbox.confinement import PathScopeViolationError


class ArtifactValidationError(UniversalBrainError):
    """Raised when an uploaded artifact fails cryptographic verification or scope boundaries."""
    pass


class ArtifactValidator:
    """Validates digests, size limits, and safe extraction for worker outputs."""

    MAX_ARTIFACT_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB ceiling

    @staticmethod
    def verify_file_digest(file_path: Path, expected_sha256: str) -> bool:
        """Asserts file on disk exactly matches expected SHA-256."""
        if not file_path.is_file():
            return False
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest() == expected_sha256

    @classmethod
    def safe_extract_zip(cls, zip_path: Path, destination_dir: Path) -> None:
        """
        Extracts ZIP file ensuring no archive entry escapes destination_dir.
        Guards against ZipSlip path traversal vulnerability.
        """
        dest_resolved = destination_dir.resolve()
        dest_resolved.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as z:
            for member in z.infolist():
                # Check target path
                target_path = (dest_resolved / member.filename).resolve()
                dest_str = os.path.normcase(str(dest_resolved))
                target_str = os.path.normcase(str(target_path))

                if not target_str.startswith(dest_str):
                    raise ArtifactValidationError(
                        f"ZipSlip traversal attack detected: entry '{member.filename}' "
                        f"escapes destination '{dest_resolved}'."
                    )
            z.extractall(dest_resolved)
