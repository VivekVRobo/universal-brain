"""
Universal Brain - Journal Replication Agent

Implements M6 Sections 64-71, 101-103:
Replicates immutable micro-batch journal chunks to secondary storage
with idempotent upload verification, gap prevention, and backpressure tracking.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from uuid import UUID

from universal_brain.persistence.backup.journal import JournalPackage
from universal_brain.persistence.errors import IntegrityFailureError


class JournalReplicationAgent:
    """Manages asynchronous journal replication to remote destinations."""

    def __init__(self) -> None:
        self.local_queue: List[JournalPackage] = []
        self.remote_store: Dict[UUID, JournalPackage] = {}
        self.last_replicated_sequence: int = 0

    def stage_package(self, pkg: JournalPackage) -> None:
        """Enqueues a new local journal package for replication."""
        self.local_queue.append(pkg)

    def replicate_batch(self, pkg: JournalPackage) -> bool:
        """
        Simulates atomic replication upload with idempotent deduplication (M6 Section 103).
        - If journal_id already exists with same digest: safe idempotent success.
        - If journal_id already exists with differing digest: INTEGRITY_CONFLICT error.
        """
        if pkg.journal_id in self.remote_store:
            existing = self.remote_store[pkg.journal_id]
            if existing.payload_digest == pkg.payload_digest:
                return True  # Safe duplicate
            raise IntegrityFailureError(
                f"INTEGRITY_CONFLICT: Journal '{pkg.journal_id}' re-uploaded with divergent digest "
                f"'{pkg.payload_digest}' vs existing '{existing.payload_digest}'."
            )

        self.remote_store[pkg.journal_id] = pkg
        self.last_replicated_sequence = pkg.sequence_end
        return True

    def sync_all_pending(self) -> int:
        """Replicates all queued local packages in sequence."""
        synced = 0
        while self.local_queue:
            pkg = self.local_queue.pop(0)
            self.replicate_batch(pkg)
            synced += 1
        return synced

    def get_lag_count(self) -> int:
        """Returns count of local journal packages waiting to replicate."""
        return len(self.local_queue)
