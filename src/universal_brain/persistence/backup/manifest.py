"""
Universal Brain - Cryptographic Backup Manifest

Implements M6 Sections 59-61, 89-93, and Invariant M6-INV-16:
Immutable, HMAC-authenticated backup manifest tying database snapshot,
event sequence head, and artifact digest into an atomic consistency point.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from universal_brain.config import settings


class BackupManifest(BaseModel):
    """Authenticated consistency manifest for disaster recovery."""

    backup_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    kernel_epoch: int = 1
    schema_version: int = 1
    event_sequence_head: int = 0
    database_digest: str
    artifact_manifest_digest: str = ""
    manifest_signature: str = ""

    def calculate_signature(self, secret_key: Optional[str] = None) -> str:
        """Computes HMAC-SHA256 authentication over manifest fields (Section 92)."""
        key = (secret_key or settings.hmac_secret_key).encode("utf-8")
        payload = (
            f"{self.backup_id}:{self.kernel_epoch}:{self.schema_version}:"
            f"{self.event_sequence_head}:{self.database_digest}:{self.artifact_manifest_digest}"
        ).encode("utf-8")
        return hmac.new(key, payload, hashlib.sha256).hexdigest()

    def sign(self, secret_key: Optional[str] = None) -> None:
        """Signs the manifest in-place."""
        self.manifest_signature = self.calculate_signature(secret_key)

    def verify_signature(self, secret_key: Optional[str] = None) -> bool:
        """Asserts signature validity."""
        expected = self.calculate_signature(secret_key)
        return hmac.compare_digest(self.manifest_signature, expected)
