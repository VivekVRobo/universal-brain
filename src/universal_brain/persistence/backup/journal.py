"""
Universal Brain - Micro-Batch Journal Packager

Implements M6 Sections 64-66, 97-100:
Packages immutable event micro-batches into signed, sequential journal chunks
with previous_journal_digest hash chaining and gap detection.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from universal_brain.kernel.events import EventEnvelope
from universal_brain.persistence.errors import IntegrityFailureError


class JournalPackage(BaseModel):
    """Immutable replication journal package."""

    journal_id: UUID = Field(default_factory=uuid4)
    sequence_start: int
    sequence_end: int
    previous_journal_digest: str = ""
    payload_digest: str
    events_jsonl: str
    schema_version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def compute_payload_digest(events_jsonl: str) -> str:
        return hashlib.sha256(events_jsonl.encode("utf-8")).hexdigest()


class ReplicationJournalPackager:
    """Constructs verifiable micro-batch journal packages from drained events."""

    @classmethod
    def package_events(
        cls,
        events: List[EventEnvelope],
        previous_journal_digest: str = "",
        journal_id: Optional[UUID] = None,
        sequence_start: int = 1,
    ) -> JournalPackage:
        """Packages a list of events into a contiguous journal chunk."""
        if not events:
            raise ValueError("Cannot package empty event list into journal.")

        lines = [e.to_canonical_json() for e in events]
        events_jsonl = "\n".join(lines)
        payload_digest = JournalPackage.compute_payload_digest(events_jsonl)

        seq_start = sequence_start
        seq_end = sequence_start + len(events) - 1

        return JournalPackage(
            journal_id=journal_id or uuid4(),
            sequence_start=seq_start,
            sequence_end=seq_end,
            previous_journal_digest=previous_journal_digest,
            payload_digest=payload_digest,
            events_jsonl=events_jsonl,
        )

    @classmethod
    def verify_journal_chain(cls, packages: List[JournalPackage]) -> bool:
        """
        Traverses a sequence of journal packages and verifies:
        1. Monotonic sequence continuity without gaps (M6 Section 99).
        2. Unbroken previous_journal_digest hash chain (M6 Section 98).
        3. Payload digest integrity.
        """
        expected_prev_digest = ""
        expected_next_seq: Optional[int] = None

        for idx, pkg in enumerate(packages):
            # 1. Sequence gap check
            if expected_next_seq is not None and pkg.sequence_start != expected_next_seq:
                raise IntegrityFailureError(
                    f"JOURNAL_GAP detected at index {idx}: expected sequence {expected_next_seq}, "
                    f"found {pkg.sequence_start}."
                )

            # 2. Hash chain check
            if idx > 0 and pkg.previous_journal_digest != expected_prev_digest:
                raise IntegrityFailureError(
                    f"Journal chain broken at package {pkg.journal_id}: expected prev digest "
                    f"'{expected_prev_digest}', got '{pkg.previous_journal_digest}'."
                )

            # 3. Payload integrity
            actual_digest = JournalPackage.compute_payload_digest(pkg.events_jsonl)
            if actual_digest != pkg.payload_digest:
                raise IntegrityFailureError(
                    f"Journal payload tampered at package {pkg.journal_id}: expected digest "
                    f"'{pkg.payload_digest}', recomputed '{actual_digest}'."
                )

            expected_prev_digest = pkg.payload_digest
            expected_next_seq = pkg.sequence_end + 1

        return True
