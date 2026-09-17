"""Persistent long-running engineering service supervision.

Traceability: REQ-ENG-020, REQ-TOL-001, ALN-007, ALN-016. The supervisor
persists process metadata but delegates start/stop/status/log access to an injected
authority-gated backend.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ServiceState(str):
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ServiceRecord(BaseModel):
    service_id: UUID = Field(default_factory=uuid4)
    name: str
    command: list[str]
    cwd: Path
    pid: int | None = None
    state: str = ServiceState.UNKNOWN
    log_ref: str | None = None
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = Field(default_factory=dict)


class ServiceProcessBackend(Protocol):
    async def start(self, record: ServiceRecord) -> tuple[int, str | None]: ...
    async def stop(self, record: ServiceRecord) -> bool: ...
    async def is_running(self, record: ServiceRecord) -> bool: ...
    async def tail_logs(self, record: ServiceRecord, max_lines: int = 200) -> str: ...


class PersistentServiceSupervisor:
    def __init__(self, registry_path: Path, backend: ServiceProcessBackend) -> None:
        self.registry_path = registry_path.resolve()
        self.backend = backend
        self._records: dict[str, ServiceRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.registry_path.exists():
            return
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
            self._records = {
                key: ServiceRecord.model_validate(value)
                for key, value in (raw.get("services", {}) if isinstance(raw, dict) else {}).items()
            }
        except (OSError, ValueError, json.JSONDecodeError):
            self._records = {}

    def _persist(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.registry_path.with_name(f".{self.registry_path.name}.{os.getpid()}.tmp")
        payload = {
            "services": {key: value.model_dump(mode="json") for key, value in sorted(self._records.items())}
        }
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.registry_path)

    async def start(self, name: str, command: list[str], *, cwd: Path, metadata: dict | None = None) -> ServiceRecord:
        if not name.strip() or not command:
            raise ValueError("service name and command are required")
        existing = self._records.get(name)
        if existing and await self.backend.is_running(existing):
            return existing
        record = ServiceRecord(name=name, command=list(command), cwd=cwd.resolve(), metadata=dict(metadata or {}))
        pid, log_ref = await self.backend.start(record)
        record.pid = pid
        record.log_ref = log_ref
        record.state = ServiceState.RUNNING
        record.started_at = datetime.now(timezone.utc)
        record.updated_at = record.started_at
        self._records[name] = record
        self._persist()
        return record

    async def stop(self, name: str) -> ServiceRecord:
        record = self._records.get(name)
        if record is None:
            raise KeyError(name)
        success = await self.backend.stop(record)
        record.state = ServiceState.STOPPED if success else ServiceState.FAILED
        record.updated_at = datetime.now(timezone.utc)
        self._persist()
        return record

    async def status(self, name: str) -> ServiceRecord:
        record = self._records.get(name)
        if record is None:
            raise KeyError(name)
        running = await self.backend.is_running(record)
        record.state = ServiceState.RUNNING if running else (
            ServiceState.STOPPED if record.state == ServiceState.STOPPED else ServiceState.FAILED
        )
        record.updated_at = datetime.now(timezone.utc)
        self._persist()
        return record

    async def logs(self, name: str, max_lines: int = 200) -> str:
        record = self._records.get(name)
        if record is None:
            raise KeyError(name)
        return await self.backend.tail_logs(record, max_lines=max_lines)

    async def recover(self) -> list[ServiceRecord]:
        recovered: list[ServiceRecord] = []
        for name in sorted(self._records):
            recovered.append(await self.status(name))
        return recovered

    def list_records(self) -> list[ServiceRecord]:
        return list(self._records.values())


class ToolGatewayServiceBackend:
    """Concrete authority-gated backend for ``PersistentServiceSupervisor``.

    It expects ``ManagedServiceProcessTool`` to be registered as ``manage_service``.
    Capability creation remains external and operator/contract scoped.
    """

    def __init__(self, gateway, contract, capability_token_provider) -> None:
        self.gateway = gateway
        self.contract = contract
        self.capability_token_provider = capability_token_provider

    def _execute(self, operation: str, record: ServiceRecord, extra: dict | None = None):
        token = self.capability_token_provider(operation, record)
        args = {
            "operation": operation,
            "service_id": str(record.service_id),
            **(extra or {}),
        }
        return self.gateway.execute_tool(
            tool_name="manage_service",
            args=args,
            capability_token=token,
            contract=self.contract,
            actor_id="engineering_service_supervisor",
            target_resource=str(record.cwd),
        )

    async def start(self, record: ServiceRecord) -> tuple[int, str | None]:
        result = self._execute(
            "start",
            record,
            {
                "executable": record.command[0],
                "arguments": record.command[1:],
                "cwd": str(record.cwd),
                "environment_overrides": record.metadata.get("environment_overrides", {}),
            },
        )
        if not result.success or not isinstance(result.output, dict):
            raise RuntimeError(result.error_message or "manage_service start failed")
        return int(result.output["pid"]), result.output.get("log_ref")

    async def stop(self, record: ServiceRecord) -> bool:
        result = self._execute("stop", record)
        return bool(result.success)

    async def is_running(self, record: ServiceRecord) -> bool:
        result = self._execute("status", record)
        return bool(
            result.success
            and isinstance(result.output, dict)
            and result.output.get("state") == ServiceState.RUNNING
        )

    async def tail_logs(self, record: ServiceRecord, max_lines: int = 200) -> str:
        result = self._execute("logs", record, {"max_lines": max_lines})
        if not result.success:
            return result.error_message or "service logs unavailable"
        return str(result.output)
