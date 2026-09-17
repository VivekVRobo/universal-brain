"""Synchronous append-only journal for the canonical Universal Brain event ledger.

The journal is the local-first durability boundary for EventStore. A record is
fsync'd before the corresponding in-memory projection is mutated, so callers
never receive a successful state transition that exists only in RAM.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from universal_brain.kernel.errors import UniversalBrainError
from universal_brain.kernel.events import EventEdge, EventEnvelope


class CanonicalJournalError(UniversalBrainError):
    """Raised when the canonical journal cannot be written or replayed safely."""


class CanonicalEventJournal:
    SCHEMA_VERSION = "ub-canonical-event-journal/v1"

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _append(self, record: dict[str, Any]) -> None:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            **record,
        }
        encoded = (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        try:
            with self._lock:
                with self.path.open("ab", buffering=0) as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
        except OSError as exc:
            raise CanonicalJournalError(
                f"canonical event journal append failed: {type(exc).__name__}: {exc}"
            ) from exc

    def append_event(
        self,
        event: EventEnvelope,
        causal_edge: EventEdge | None = None,
    ) -> None:
        """Persist an event and its optional CAUSED_BY edge as one journal record."""
        self._append(
            {
                "kind": "event",
                "event": event.model_dump(mode="json"),
                "causal_edge": (
                    causal_edge.model_dump(mode="json")
                    if causal_edge is not None
                    else None
                ),
            }
        )

    def append_edge(self, edge: EventEdge) -> None:
        self._append(
            {
                "kind": "edge",
                "edge": edge.model_dump(mode="json"),
            }
        )

    def initialize_from_history(
        self,
        events: Iterable[EventEnvelope],
        edges: Iterable[EventEdge],
    ) -> None:
        """Atomically initialize an empty journal from already verified history.

        This is used only to migrate a legacy SQL-only deployment. Existing
        canonical journal content is never overwritten.
        """
        with self._lock:
            if self.path.exists() and self.path.stat().st_size > 0:
                raise CanonicalJournalError(
                    "refusing to overwrite a non-empty canonical event journal"
                )

            records: list[dict[str, Any]] = []
            for event in events:
                records.append(
                    {
                        "schema_version": self.SCHEMA_VERSION,
                        "kind": "event",
                        "event": event.model_dump(mode="json"),
                        "causal_edge": None,
                    }
                )
            for edge in edges:
                records.append(
                    {
                        "schema_version": self.SCHEMA_VERSION,
                        "kind": "edge",
                        "edge": edge.model_dump(mode="json"),
                    }
                )

            temp_path = self.path.with_name(self.path.name + ".bootstrap.tmp")
            try:
                with temp_path.open("wb", buffering=0) as handle:
                    for record in records:
                        encoded = (
                            json.dumps(
                                record,
                                sort_keys=True,
                                separators=(",", ":"),
                                ensure_ascii=False,
                            )
                            + "\n"
                        ).encode("utf-8")
                        handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self.path)

                # Persist the directory entry where supported.
                if hasattr(os, "O_DIRECTORY"):
                    directory_fd = os.open(str(self.path.parent), os.O_DIRECTORY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            except OSError as exc:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise CanonicalJournalError(
                    f"canonical journal bootstrap failed: {type(exc).__name__}: {exc}"
                ) from exc

    def load_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        records: list[dict[str, Any]] = []
        try:
            with self._lock:
                with self.path.open("rb") as handle:
                    for line_number, raw in enumerate(handle, start=1):
                        if not raw.strip():
                            continue
                        try:
                            record = json.loads(raw.decode("utf-8"))
                        except Exception as exc:
                            raise CanonicalJournalError(
                                f"canonical journal record {line_number} is malformed"
                            ) from exc
                        if record.get("schema_version") != self.SCHEMA_VERSION:
                            raise CanonicalJournalError(
                                f"unsupported canonical journal schema at record {line_number}"
                            )
                        if record.get("kind") not in {"event", "edge"}:
                            raise CanonicalJournalError(
                                f"unknown canonical journal record kind at line {line_number}"
                            )
                        records.append(record)
        except OSError as exc:
            raise CanonicalJournalError(
                f"canonical event journal read failed: {type(exc).__name__}: {exc}"
            ) from exc
        return records
