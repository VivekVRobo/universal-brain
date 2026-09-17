"""
Universal Brain - Memory Replicator Daemon

Implements MEMORY_ARCHITECTURE.md (Section 2 & 3) and ADR-0007.
Replaces single-file appending with 60-second chunked micro-batches
(journal/YYYY-MM-DD/HH/events_HHMM_000.jsonl) to avoid cloud rate limits.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from universal_brain.config import settings
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventEnvelope


class MemoryReplicator:
    """
    Micro-batch replication daemon that periodically drains events from
    the Kernel's transactional outbox and packages them into chunked JSONL files.
    """

    def __init__(
        self,
        event_store: EventStore,
        target_journal_dir: Optional[Path] = None,
        batch_limit: int = 100,
    ) -> None:
        self.store = event_store
        self.journal_dir = target_journal_dir or settings.journal_dir
        self.batch_limit = batch_limit
        self.journal_dir.mkdir(parents=True, exist_ok=True)

    def generate_chunk_path(self, timestamp: Optional[datetime] = None) -> Path:
        """
        Generates deterministic chunk directory and filename:
        journal/YYYY-MM-DD/HH/events_HHMM_000.jsonl
        """
        now = timestamp or datetime.now(timezone.utc)
        date_folder = now.strftime("%Y-%m-%d")
        hour_folder = now.strftime("%H")
        minute_file = now.strftime("events_%H%M_000.jsonl")

        target_dir = self.journal_dir / date_folder / hour_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / minute_file

    def sync_outbox_batch(self, current_time: Optional[datetime] = None) -> Optional[Path]:
        """
        Drains up to `batch_limit` events from the Kernel outbox and writes
        an immutable chunk file to the replication destination.
        Returns the written chunk Path, or None if no events were queued.
        """
        events: List[EventEnvelope] = self.store.drain_outbox(max_batch_size=self.batch_limit)
        if not events:
            return None

        chunk_path = self.generate_chunk_path(current_time)
        with open(chunk_path, "a", encoding="utf-8") as f:
            for event in events:
                f.write(event.to_canonical_json() + "\n")

        return chunk_path
