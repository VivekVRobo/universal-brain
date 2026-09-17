"""
Universal Brain - Artifact Reconciler & Garbage Collector

Implements M6 Sections 50-52:
Detects orphaned, missing, and corrupted blobs using reachability analysis
and performs safe garbage collection with time-bounded grace periods.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Dict, List, Set

from universal_brain.persistence.artifacts.store import ContentAddressedArtifactStore


class ArtifactReconciler:
    """Audits disk blobs against reachability sets and safely cleans unreachable data."""

    def __init__(self, store: ContentAddressedArtifactStore) -> None:
        self.store = store

    def audit_reachability(self, reachable_digests: Set[str]) -> Dict[str, List[str]]:
        """
        Audits the blob store against the set of reachable database digests:
        - 'orphans': on disk, but not in reachable_digests.
        - 'missing': in reachable_digests, but absent on disk.
        - 'corrupted': on disk, but content digest doesn't match filename.
        """
        orphans: List[str] = []
        corrupted: List[str] = []
        found_digests: Set[str] = set()

        for file_path in self.store.blobs_dir.rglob("*"):
            if not file_path.is_file():
                continue
            digest = file_path.name
            if len(digest) != 64:
                continue

            found_digests.add(digest)

            # Check integrity
            with open(file_path, "rb") as f:
                actual = hashlib.sha256(f.read()).hexdigest()
            if actual != digest:
                corrupted.append(digest)

            if digest not in reachable_digests:
                orphans.append(digest)

        missing = list(reachable_digests - found_digests)

        return {
            "orphans": orphans,
            "missing": missing,
            "corrupted": corrupted,
        }

    def garbage_collect(
        self,
        reachable_digests: Set[str],
        grace_period_seconds: int = 3600,
    ) -> int:
        """
        Safely deletes orphaned blobs that exceed the safety grace window.
        (M6 Section 52). Returns the count of pruned blobs.
        """
        audit = self.audit_reachability(reachable_digests)
        now = time.time()
        deleted_count = 0

        for orphan_digest in audit["orphans"]:
            path = self.store.get_path(orphan_digest)
            if not path or not path.is_file():
                continue

            # Respect safety grace window
            mtime = os.path.getmtime(path)
            if (now - mtime) >= grace_period_seconds:
                try:
                    path.unlink()
                    deleted_count += 1
                except Exception:
                    pass

        return deleted_count
