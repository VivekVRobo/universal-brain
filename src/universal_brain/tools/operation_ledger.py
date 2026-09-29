"""Durable operation ledger for crash safe tool execution.

This module narrows duplicate execution risk by persisting an operation intent
before an external effect and by requiring reconciliation when execution outcome
is uncertain after a crash.

It does not claim universal exactly once semantics. External systems that do not
offer idempotency or an observable reconciliation mechanism can still leave an
operation in an indeterminate state. In that case the runtime fails closed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from universal_brain.tools.base import ToolResult


class OperationLedgerError(RuntimeError):
    pass


class OperationState(str, Enum):
    PREPARED = "PREPARED"
    EXECUTING = "EXECUTING"
    EFFECT_CONFIRMED = "EFFECT_CONFIRMED"
    EVIDENCE_COMMITTED = "EVIDENCE_COMMITTED"
    IN_DOUBT = "IN_DOUBT"


class OperationRecord(BaseModel):
    operation_id: str
    project_id: UUID
    task_id: UUID
    tool_name: str
    target_resource: str
    idempotency_key: str
    request_digest: str
    state: OperationState
    result: ToolResult | None = None
    call_event_id: UUID | None = None
    evidence_event_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    last_error: str = ""


class DurableOperationLedger:
    """SQLite backed operation state with transactional state transitions."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operation_ledger (
                    operation_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    target_resource TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    result_json TEXT,
                    call_event_id TEXT,
                    evidence_event_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_operation_idempotency
                ON operation_ledger(project_id, task_id, tool_name, idempotency_key)
                """
            )

    @staticmethod
    def operation_id(
        *,
        project_id: UUID,
        task_id: UUID,
        tool_name: str,
        idempotency_key: str,
    ) -> str:
        raw = json.dumps(
            {
                "project_id": str(project_id),
                "task_id": str(task_id),
                "tool_name": tool_name,
                "idempotency_key": idempotency_key,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> OperationRecord:
        result = None
        if row["result_json"]:
            result = ToolResult.model_validate_json(row["result_json"])
        return OperationRecord(
            operation_id=row["operation_id"],
            project_id=UUID(row["project_id"]),
            task_id=UUID(row["task_id"]),
            tool_name=row["tool_name"],
            target_resource=row["target_resource"],
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
            state=OperationState(row["state"]),
            result=result,
            call_event_id=UUID(row["call_event_id"]) if row["call_event_id"] else None,
            evidence_event_id=UUID(row["evidence_event_id"]) if row["evidence_event_id"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_error=row["last_error"] or "",
        )

    def get(self, operation_id: str) -> OperationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM operation_ledger WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def prepare(
        self,
        *,
        project_id: UUID,
        task_id: UUID,
        tool_name: str,
        target_resource: str,
        idempotency_key: str,
        request_digest: str,
    ) -> OperationRecord:
        operation_id = self.operation_id(
            project_id=project_id,
            task_id=task_id,
            tool_name=tool_name,
            idempotency_key=idempotency_key,
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operation_ledger WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO operation_ledger (
                        operation_id, project_id, task_id, tool_name, target_resource,
                        idempotency_key, request_digest, state, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation_id,
                        str(project_id),
                        str(task_id),
                        tool_name,
                        target_resource,
                        idempotency_key,
                        request_digest,
                        OperationState.PREPARED.value,
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM operation_ledger WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
            connection.commit()

        record = self._row_to_record(row)
        if record.request_digest != request_digest:
            raise OperationLedgerError(
                "idempotency key was reused for a different canonical request"
            )
        if record.target_resource != target_resource:
            raise OperationLedgerError(
                "idempotency key was reused for a different target resource"
            )
        return record

    def _transition(
        self,
        operation_id: str,
        state: OperationState,
        *,
        result: ToolResult | None = None,
        call_event_id: UUID | None = None,
        evidence_event_id: UUID | None = None,
        last_error: str = "",
    ) -> OperationRecord:
        current = self.get(operation_id)
        if current is None:
            raise OperationLedgerError(f"unknown operation: {operation_id}")
        now = datetime.now(timezone.utc).isoformat()
        result_json = (
            result.model_dump_json()
            if result is not None
            else current.result.model_dump_json()
            if current.result is not None
            else None
        )
        call_id = str(call_event_id or current.call_event_id) if (call_event_id or current.call_event_id) else None
        evidence_id = (
            str(evidence_event_id or current.evidence_event_id)
            if (evidence_event_id or current.evidence_event_id)
            else None
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE operation_ledger
                SET state = ?, result_json = ?, call_event_id = ?,
                    evidence_event_id = ?, updated_at = ?, last_error = ?
                WHERE operation_id = ?
                """,
                (
                    state.value,
                    result_json,
                    call_id,
                    evidence_id,
                    now,
                    last_error,
                    operation_id,
                ),
            )
            connection.commit()
        updated = self.get(operation_id)
        if updated is None:
            raise OperationLedgerError(f"operation disappeared after transition: {operation_id}")
        return updated

    def mark_executing(self, operation_id: str, *, call_event_id: UUID) -> OperationRecord:
        return self._transition(
            operation_id,
            OperationState.EXECUTING,
            call_event_id=call_event_id,
        )

    def mark_effect_confirmed(
        self,
        operation_id: str,
        *,
        result: ToolResult,
    ) -> OperationRecord:
        return self._transition(
            operation_id,
            OperationState.EFFECT_CONFIRMED,
            result=result,
        )

    def mark_evidence_committed(
        self,
        operation_id: str,
        *,
        evidence_event_id: UUID,
    ) -> OperationRecord:
        return self._transition(
            operation_id,
            OperationState.EVIDENCE_COMMITTED,
            evidence_event_id=evidence_event_id,
        )

    def mark_in_doubt(self, operation_id: str, *, error: str) -> OperationRecord:
        return self._transition(
            operation_id,
            OperationState.IN_DOUBT,
            last_error=error,
        )
