"""
Universal Brain - Content-Addressed Artifact Store & Reconciler Tests

Implements M6 Sections 47-52, and Invariant M6-INV-14:
Tests content-addressed storage (SHA-256), atomic write finalization,
reachability auditing (orphans, missing, corrupted), and safe grace-window GC.
"""

import os
import tempfile
import time
from pathlib import Path
import pytest

from universal_brain.persistence.artifacts.reconcile import ArtifactReconciler
from universal_brain.persistence.artifacts.store import ContentAddressedArtifactStore


@pytest.fixture
def artifact_fixture():
    temp_dir = tempfile.mkdtemp(prefix="brain_m6_artifacts_")
    store = ContentAddressedArtifactStore(root_dir=Path(temp_dir))
    reconciler = ArtifactReconciler(store)
    return store, reconciler


def test_content_addressed_storage_and_deduplication(artifact_fixture):
    """Verify SHA-256 content-addressing and deduplication."""
    store, _ = artifact_fixture
    payload = b"Autonomous Sovereign Kernel - Deterministic Artifact"

    digest1 = store.store_bytes(payload)
    digest2 = store.store_bytes(payload)

    assert digest1 == digest2
    assert store.exists(digest1)
    assert store.get_bytes(digest1) == payload


def test_artifact_reachability_audit_and_garbage_collection(artifact_fixture):
    """Verify orphan detection, missing detection, corruption detection, and safe GC."""
    store, reconciler = artifact_fixture

    # 1. Stored blob that is active & reachable
    active_data = b"Active valid artifact"
    active_digest = store.store_bytes(active_data)

    # 2. Stored blob that is orphaned (not in reachable_set)
    orphan_data = b"Old discarded temporary trace"
    orphan_digest = store.store_bytes(orphan_data)

    # 3. Corrupted blob (overwrite content with non-matching bytes)
    corrupted_data = b"Soon to be corrupted"
    corrupted_digest = store.store_bytes(corrupted_data)
    corrupted_path = store.get_path(corrupted_digest)
    with open(corrupted_path, "wb") as f:
        f.write(b"TAMPERED_BYTES")

    # 4. Missing digest (in reachable_set, but absent on disk)
    missing_digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    reachable_set = {active_digest, corrupted_digest, missing_digest}

    audit = reconciler.audit_reachability(reachable_set)
    assert orphan_digest in audit["orphans"]
    assert missing_digest in audit["missing"]
    assert corrupted_digest in audit["corrupted"]

    # 5. Test Garbage Collection with zero grace period
    # Age the orphan file artificially
    orphan_path = store.get_path(orphan_digest)
    os.utime(orphan_path, (time.time() - 100, time.time() - 100))

    pruned = reconciler.garbage_collect(reachable_set, grace_period_seconds=10)
    assert pruned == 1
    assert not store.exists(orphan_digest)
    # Active digest remains safe and untouched
    assert store.exists(active_digest)
