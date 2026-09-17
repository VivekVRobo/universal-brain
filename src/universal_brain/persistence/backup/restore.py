"""
Universal Brain - Disaster Recovery & Restoration Engine

Implements M6 Sections 72-74, 104-108, and Invariant M6-INV-17:
Restores canonical state into a clean/empty database environment,
replays uncommitted journal tails, verifies hash chain continuity,
advances kernel epoch, and generates an authoritative verification report.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventEnvelope, EventType
from universal_brain.persistence.backup.journal import JournalPackage, ReplicationJournalPackager
from universal_brain.persistence.backup.manifest import BackupManifest
from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.errors import IntegrityFailureError
from universal_brain.persistence.unit_of_work import UnitOfWork


class DisasterRecoveryEngine:
    """Orchestrates cold and warm disaster recovery restorations."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    async def restore_from_backup_and_journal(
        self,
        manifest: BackupManifest,
        journal_packages: List[JournalPackage],
        new_instance_id: str = "ub-restored-node",
        secret_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes complete restoration pipeline (M6 Section 105):
        1. Verifies backup manifest HMAC signature.
        2. Validates journal tail continuity without sequence gaps.
        3. Replays journal events into target database.
        4. Reconstructs and verifies EventStore hash chain.
        5. Advances kernel epoch to fence old instances.
        6. Emits authoritative restore verification report.
        """
        # 1. Verify Manifest
        if not manifest.verify_signature(secret_key):
            raise IntegrityFailureError("RESTORE_FAILED: Backup manifest HMAC signature verification failed.")

        # 2. Verify Journal Tail
        if journal_packages:
            ReplicationJournalPackager.verify_journal_chain(journal_packages)

        replayed_events: List[EventEnvelope] = []
        for pkg in journal_packages:
            for line in pkg.events_jsonl.strip().split("\n"):
                if not line.strip():
                    continue
                data = json.loads(line)
                raw_ts = data["timestamp"]
                if isinstance(raw_ts, str) and raw_ts.endswith("Z") and ("+" in raw_ts or raw_ts.count("-") > 2):
                    raw_ts = raw_ts[:-1]
                from datetime import datetime, timezone
                parsed_ts = datetime.fromisoformat(raw_ts) if isinstance(raw_ts, str) else raw_ts
                if parsed_ts.tzinfo is None:
                    parsed_ts = parsed_ts.replace(tzinfo=timezone.utc)

                envelope = EventEnvelope(
                    event_id=data["event_id"],
                    timestamp=parsed_ts,
                    event_type=EventType(data["event_type"]) if data["event_type"] in EventType.__members__.values() else EventType.INTENT_PARSED,
                    actor_id=data["actor_id"],
                    project_id=data.get("project_id"),
                    task_id=data.get("task_id"),
                    contract_version=data.get("contract_version"),
                    payload=data.get("payload", {}),
                    prev_event_hash=data["prev_event_hash"],
                    event_hash=data["event_hash"],
                )
                replayed_events.append(envelope)

        # 3. Replay into Target Database
        restored_count = 0
        new_epoch = 1

        async with UnitOfWork(self.db_manager) as uow:
            # Advance Kernel Epoch (M6 Section 107)
            marker = await uow.lifecycle.acquire_or_advance_epoch(new_instance_id)
            new_epoch = marker.kernel_epoch

            for env in replayed_events:
                # Check if event already exists
                existing = await uow.events.get_event(env.event_id)
                if not existing:
                    await uow.events.append_event(env)
                    restored_count += 1

            await uow.commit()

        # 4. Verify Hash Chain Integrity on Restored Store
        test_store = EventStore()
        async with UnitOfWork(self.db_manager) as uow:
            persisted = await uow.events.get_all_events_ordered()
            test_store._events.clear()
            test_store._events_by_id.clear()
            test_store._latest_hash = ""

            for p in persisted:
                ts = p.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                env = EventEnvelope(
                    event_id=p.event_id,
                    timestamp=ts,
                    event_type=EventType(p.event_type) if p.event_type in EventType.__members__.values() else EventType.INTENT_PARSED,
                    actor_id=p.actor_id,
                    project_id=p.project_id,
                    task_id=p.task_id,
                    contract_version=p.contract_version,
                    payload=p.payload,
                    prev_event_hash=p.prev_event_hash,
                    event_hash=p.event_hash,
                )
                test_store._events.append(env)
                test_store._events_by_id[env.event_id] = env
                test_store._latest_hash = env.event_hash

            test_store.verify_chain_integrity()

        # 5. Build Authoritative Verification Report (M6 Section 108)
        return {
            "status": "RESTORE_VERIFIED",
            "backup_id": str(manifest.backup_id),
            "new_kernel_epoch": new_epoch,
            "events_replayed": restored_count,
            "total_persisted_events": len(test_store._events),
            "event_chain_head": test_store.latest_hash,
            "hash_chain_integrity": "PASS",
        }
