"""Durable distributed worker leases with fencing tokens for V5.2.

Traceability: REQ-ENG-026, ALN-014, ALN-016. Leases are coordination state,
not authority grants. Capability tokens remain mandatory at ToolGateway.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DurableLeaseError(RuntimeError):
    pass


class DurableWorkerLease(BaseModel):
    lease_id: UUID = Field(default_factory=uuid4)
    task_id: str
    worker_id: str
    workspace_id: UUID
    generation: int = Field(ge=1)
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    heartbeat_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    metadata: dict = Field(default_factory=dict)

    def expired(self, now: datetime | None = None) -> bool:
        return self.expires_at <= (now or datetime.now(timezone.utc))


class DurableWorkerLeaseStore:
    """Cross-process file-backed lease registry with monotonic fencing generations."""

    def __init__(self, path: Path, *, lock_timeout_seconds: float = 5.0) -> None:
        self.path = path.resolve()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.lock_timeout_seconds = max(0.1, lock_timeout_seconds)

    def acquire(
        self,
        *,
        task_id: str,
        worker_id: str,
        workspace_id: UUID,
        ttl_seconds: int = 120,
        metadata: dict | None = None,
    ) -> DurableWorkerLease:
        if not task_id.strip() or not worker_id.strip():
            raise ValueError("task_id and worker_id are required")
        if ttl_seconds < 5:
            raise ValueError("ttl_seconds must be >= 5")
        with self._locked():
            state = self._load_state()
            now = datetime.now(timezone.utc)
            self._prune_expired(state, now)
            active_raw = state["leases"].get(task_id)
            if active_raw:
                active = DurableWorkerLease.model_validate(active_raw)
                if not active.expired(now):
                    if active.worker_id == worker_id and active.workspace_id == workspace_id:
                        return active
                    raise DurableLeaseError(
                        f"Task {task_id!r} is leased by {active.worker_id!r} until {active.expires_at.isoformat()}"
                    )
            generation = int(state["generations"].get(task_id, 0)) + 1
            lease = DurableWorkerLease(
                task_id=task_id,
                worker_id=worker_id,
                workspace_id=workspace_id,
                generation=generation,
                acquired_at=now,
                heartbeat_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
                metadata=dict(metadata or {}),
            )
            state["leases"][task_id] = lease.model_dump(mode="json")
            state["generations"][task_id] = generation
            self._persist_state(state)
            return lease

    def heartbeat(
        self,
        *,
        task_id: str,
        worker_id: str,
        generation: int,
        ttl_seconds: int = 120,
    ) -> DurableWorkerLease:
        with self._locked():
            state = self._load_state()
            raw = state["leases"].get(task_id)
            if raw is None:
                raise DurableLeaseError(f"No active lease for task {task_id!r}")
            lease = DurableWorkerLease.model_validate(raw)
            self._assert_holder(lease, worker_id, generation)
            now = datetime.now(timezone.utc)
            if lease.expired(now):
                state["leases"].pop(task_id, None)
                self._persist_state(state)
                raise DurableLeaseError("Lease expired; worker must reacquire with a new fencing generation")
            lease.heartbeat_at = now
            lease.expires_at = now + timedelta(seconds=max(5, ttl_seconds))
            state["leases"][task_id] = lease.model_dump(mode="json")
            self._persist_state(state)
            return lease

    def release(self, *, task_id: str, worker_id: str, generation: int) -> None:
        with self._locked():
            state = self._load_state()
            raw = state["leases"].get(task_id)
            if raw is None:
                return
            lease = DurableWorkerLease.model_validate(raw)
            self._assert_holder(lease, worker_id, generation)
            state["leases"].pop(task_id, None)
            self._persist_state(state)

    def validate_fence(self, *, task_id: str, worker_id: str, generation: int) -> bool:
        with self._locked():
            state = self._load_state()
            raw = state["leases"].get(task_id)
            if raw is None:
                return False
            lease = DurableWorkerLease.model_validate(raw)
            return (
                not lease.expired()
                and lease.worker_id == worker_id
                and lease.generation == generation
                and int(state["generations"].get(task_id, 0)) == generation
            )

    def get(self, task_id: str) -> DurableWorkerLease | None:
        with self._locked():
            state = self._load_state()
            raw = state["leases"].get(task_id)
            if raw is None:
                return None
            lease = DurableWorkerLease.model_validate(raw)
            if lease.expired():
                state["leases"].pop(task_id, None)
                self._persist_state(state)
                return None
            return lease

    def list_active(self) -> list[DurableWorkerLease]:
        with self._locked():
            state = self._load_state()
            now = datetime.now(timezone.utc)
            changed = self._prune_expired(state, now)
            if changed:
                self._persist_state(state)
            return [DurableWorkerLease.model_validate(raw) for _, raw in sorted(state["leases"].items())]

    @staticmethod
    def _assert_holder(lease: DurableWorkerLease, worker_id: str, generation: int) -> None:
        if lease.worker_id != worker_id or lease.generation != generation:
            raise DurableLeaseError(
                "Stale worker fencing token rejected; lease holder/generation does not match"
            )

    @staticmethod
    def _prune_expired(state: dict, now: datetime) -> bool:
        expired = [
            task_id
            for task_id, raw in state["leases"].items()
            if DurableWorkerLease.model_validate(raw).expired(now)
        ]
        for task_id in expired:
            state["leases"].pop(task_id, None)
        return bool(expired)

    def _load_state(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "leases": {}, "generations": {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DurableLeaseError(f"Could not load durable lease state: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise DurableLeaseError("Unsupported/corrupt durable lease state")
        raw.setdefault("leases", {})
        raw.setdefault("generations", {})
        return raw

    def _persist_state(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, sort_keys=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"pid={os.getpid()}\n".encode())
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                    if age > max(30.0, self.lock_timeout_seconds * 6):
                        self.lock_path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() - started >= self.lock_timeout_seconds:
                    raise DurableLeaseError("Timed out acquiring durable lease registry lock")
                time.sleep(0.02)
        try:
            yield
        finally:
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                self.lock_path.unlink(missing_ok=True)
