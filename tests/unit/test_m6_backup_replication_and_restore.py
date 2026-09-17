"""
Universal Brain - Backup, Replication & Disaster Recovery Tests

Implements M6 Sections 59-74, 89-108, and Invariants M6-INV-16, M6-INV-17:
Tests HMAC authenticated backup manifests, unbroken replication journal hash chains,
sequence gap detection, idempotent remote replication, and cold-start disaster restoration.
"""

import tempfile
from pathlib import Path
from uuid import uuid4
import pytest

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventEnvelope, EventType
from universal_brain.persistence.backup.journal import JournalPackage, ReplicationJournalPackager
from universal_brain.persistence.backup.manifest import BackupManifest
from universal_brain.persistence.backup.replication import JournalReplicationAgent
from universal_brain.persistence.backup.restore import DisasterRecoveryEngine
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.errors import IntegrityFailureError
from universal_brain.persistence.unit_of_work import UnitOfWork


def test_backup_manifest_signing_and_tamper_detection():
    """Verify HMAC manifest signing and tamper rejection (M6 Section 92)."""
    manifest = BackupManifest(
        kernel_epoch=3,
        schema_version=1,
        event_sequence_head=1420,
        database_digest="a" * 64,
        artifact_manifest_digest="b" * 64,
    )
    manifest.sign("secret-key-42")
    assert manifest.verify_signature("secret-key-42") is True
    assert manifest.verify_signature("wrong-key") is False

    # Tamper with event sequence head
    manifest.event_sequence_head = 9999
    assert manifest.verify_signature("secret-key-42") is False


def test_replication_journal_chain_and_gap_detection():
    """Verify unbroken journal hash chaining and gap detection (M6 Sections 98, 99)."""
    store = EventStore()
    e1 = store.append_event(EventType.USER_INPUT, "operator", {"cmd": "build"})
    e2 = store.append_event(EventType.TOOL_CALLED, "gateway", {"tool": "compile"})
    e3 = store.append_event(EventType.EVIDENCE_PRODUCED, "compiler", {"status": "ok"})
    e4 = store.append_event(EventType.VERIFICATION_RUN, "verifier", {"passed": True})

    # Batch 1: Events 1 & 2 (seq 1..2)
    pkg1 = ReplicationJournalPackager.package_events(
        events=[e1, e2],
        previous_journal_digest="",
        sequence_start=1,
    )

    # Batch 2: Events 3 & 4 (seq 3..4)
    pkg2 = ReplicationJournalPackager.package_events(
        events=[e3, e4],
        previous_journal_digest=pkg1.payload_digest,
        sequence_start=3,
    )

    # Verify contiguous chain
    assert ReplicationJournalPackager.verify_journal_chain([pkg1, pkg2]) is True

    # Inject GAP: batch 3 jumps from sequence 3 to sequence 10
    pkg_gapped = ReplicationJournalPackager.package_events(
        events=[e3],
        previous_journal_digest=pkg1.payload_digest,
        sequence_start=10,  # Gap!
    )
    with pytest.raises(IntegrityFailureError, match="JOURNAL_GAP detected"):
        ReplicationJournalPackager.verify_journal_chain([pkg1, pkg_gapped])


def test_journal_replication_agent_idempotency_and_conflict():
    """Verify idempotent upload vs integrity conflict on divergent payload (M6 Section 103)."""
    agent = JournalReplicationAgent()
    store = EventStore()
    e1 = store.append_event(EventType.USER_INPUT, "operator", {"data": "ping"})

    pkg = ReplicationJournalPackager.package_events([e1], sequence_start=1)

    # 1. First upload
    assert agent.replicate_batch(pkg) is True

    # 2. Duplicate upload with same payload digest (Idempotent Safe Duplicate)
    assert agent.replicate_batch(pkg) is True

    # 3. Duplicate journal_id with altered payload (INTEGRITY_CONFLICT)
    tampered_pkg = JournalPackage(
        journal_id=pkg.journal_id,
        sequence_start=pkg.sequence_start,
        sequence_end=pkg.sequence_end,
        payload_digest="f" * 64,  # Divergent!
        events_jsonl="altered payload",
    )
    with pytest.raises(IntegrityFailureError, match="INTEGRITY_CONFLICT"):
        agent.replicate_batch(tampered_pkg)


@pytest.mark.asyncio
async def test_disaster_recovery_engine_restores_clean_database():
    """Verify DisasterRecoveryEngine restores canonical state into fresh empty environment."""
    # 1. Source database setup with 2 events
    source_dir = tempfile.mkdtemp(prefix="brain_m6_source_")
    source_db = DatabaseManager(database_url=f"sqlite+aiosqlite:///{Path(source_dir) / 'source.db'}")
    await source_db.init_db()
    await source_db.create_tables()

    source_store = EventStore()
    e1 = source_store.append_event(EventType.USER_INPUT, "operator", {"step": 1})
    e2 = source_store.append_event(EventType.TOOL_CALLED, "gateway", {"step": 2}, caused_by_event_id=e1.event_id)

    pkg = ReplicationJournalPackager.package_events([e1, e2], sequence_start=1)

    manifest = BackupManifest(
        kernel_epoch=1,
        event_sequence_head=2,
        database_digest=source_store.latest_hash,
    )
    manifest.sign()

    # 2. Target empty database (fresh machine simulation)
    target_dir = tempfile.mkdtemp(prefix="brain_m6_target_")
    target_db = DatabaseManager(database_url=f"sqlite+aiosqlite:///{Path(target_dir) / 'target.db'}")
    await target_db.init_db()
    await target_db.create_tables()

    engine = DisasterRecoveryEngine(target_db)
    report = await engine.restore_from_backup_and_journal(
        manifest=manifest,
        journal_packages=[pkg],
        new_instance_id="restored-cloud-node",
    )

    assert report["status"] == "RESTORE_VERIFIED"
    assert report["events_replayed"] == 2
    assert report["new_kernel_epoch"] == 1
    assert report["hash_chain_integrity"] == "PASS"
    assert report["event_chain_head"] == source_store.latest_hash

    await source_db.close()
    await target_db.close()
