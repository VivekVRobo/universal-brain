"""Authority-gated persistent engineering service process tool (V5.2).

The tool is registered behind ToolGateway, so every start/stop/status/log action
still requires a capability token and is causally audited. It never uses shell=True.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from threading import RLock
from typing import Any, Dict
from uuid import uuid4

from universal_brain.kernel.events import ActionClass
from universal_brain.tools.base import BaseTool, ReversibilityClass, ToolResult
from universal_brain.tools.runner.policies import EnvironmentSanitizer, ExecutableRegistry
from universal_brain.tools.runner.process import SubprocessRunner
from universal_brain.tools.sandbox.confinement import confine_path


class ManagedServiceProcessTool(BaseTool):
    name = "manage_service"
    action_class = ActionClass.A1
    description = "Start, inspect, stop, and tail an authorized long-running engineering process."
    reversibility_class = ReversibilityClass.REVERSIBLE_WITH_LIMITATIONS

    def __init__(self, workspace_root: Path, *, log_root: Path | None = None) -> None:
        self.workspace_root = workspace_root.resolve()
        self.log_root = (log_root or self.workspace_root / ".brain" / "services" / "logs").resolve()
        self._processes: dict[str, subprocess.Popen] = {}
        self._logs: dict[str, Path] = {}
        self._lock = RLock()

    def preflight_check(self, args: Dict[str, Any]) -> bool:
        operation = str(args.get("operation", "")).lower()
        if operation not in {"start", "stop", "status", "logs"}:
            return False
        service_id = str(args.get("service_id", "")).strip()
        if operation != "start" and not service_id:
            return False
        if operation == "start":
            executable = str(args.get("executable", "")).strip()
            if not executable:
                return False
            ExecutableRegistry.validate_executable(executable)
            confine_path(args.get("cwd") or self.workspace_root, self.workspace_root)
            if self.log_root != self.workspace_root and self.workspace_root not in self.log_root.parents:
                return False
        return True

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        operation = str(args.get("operation", "")).lower()
        if operation == "start":
            return self._start(args)
        if operation == "stop":
            return self._stop(str(args["service_id"]))
        if operation == "status":
            return self._status(str(args["service_id"]))
        if operation == "logs":
            return self._logs_result(str(args["service_id"]), int(args.get("max_lines", 200)))
        return ToolResult(success=False, output={}, error_message="unsupported service operation")

    def rollback(self, rollback_data: Dict[str, Any]) -> bool:
        service_id = str(rollback_data.get("service_id", ""))
        if not service_id:
            return False
        return self._stop(service_id).success

    def verify_rollback(self, rollback_data: Dict[str, Any]) -> bool:
        service_id = str(rollback_data.get("service_id", ""))
        if not service_id:
            return False
        with self._lock:
            proc = self._processes.get(service_id)
            return proc is not None and proc.poll() is not None

    def _start(self, args: Dict[str, Any]) -> ToolResult:
        executable = str(args["executable"])
        arguments = [str(item) for item in args.get("arguments", [])]
        cwd = confine_path(args.get("cwd") or self.workspace_root, self.workspace_root)
        ExecutableRegistry.validate_executable(executable)
        service_id = str(args.get("service_id") or uuid4())
        with self._lock:
            existing = self._processes.get(service_id)
            if existing is not None and existing.poll() is None:
                return ToolResult(
                    success=True,
                    output={"service_id": service_id, "pid": existing.pid, "state": "running"},
                    evidence={"service_id": service_id, "pid": existing.pid, "already_running": True},
                    rollback_data={"service_id": service_id},
                    reversibility_class=self.reversibility_class,
                )
            self.log_root.mkdir(parents=True, exist_ok=True)
            log_path = (self.log_root / f"{service_id}.log").resolve()
            if self.workspace_root not in log_path.parents:
                return ToolResult(success=False, output={}, error_message="service log path escaped workspace")
            clean_env = EnvironmentSanitizer.sanitize_environment(overrides=args.get("environment_overrides"))
            creation: dict[str, Any] = {}
            if sys.platform == "win32":
                creation["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                creation["start_new_session"] = True
            try:
                with log_path.open("ab", buffering=0) as log_handle:
                    proc = subprocess.Popen(
                        [executable, *arguments],
                        cwd=str(cwd),
                        env=clean_env,
                        stdin=subprocess.DEVNULL,
                        stdout=log_handle,
                        stderr=log_handle,
                        shell=False,
                        close_fds=(sys.platform != "win32"),
                        **creation,
                    )
            except Exception as exc:
                return ToolResult(
                    success=False,
                    output={},
                    error_message=f"service launch failed: {type(exc).__name__}: {exc}",
                    reversibility_class=self.reversibility_class,
                )
            self._processes[service_id] = proc
            self._logs[service_id] = log_path
            return ToolResult(
                success=True,
                output={"service_id": service_id, "pid": proc.pid, "state": "running", "log_ref": str(log_path)},
                evidence={"service_id": service_id, "pid": proc.pid, "log_ref": str(log_path)},
                rollback_data={"service_id": service_id},
                reversibility_class=self.reversibility_class,
            )

    def _stop(self, service_id: str) -> ToolResult:
        with self._lock:
            proc = self._processes.get(service_id)
            if proc is None:
                # Never kill an arbitrary persisted PID after a runtime restart: PID
                # reuse makes that unsafe without an OS-level identity handle.
                return ToolResult(
                    success=False,
                    output={"service_id": service_id, "state": "unknown"},
                    error_message="service process identity is not owned by this runtime instance",
                    reversibility_class=self.reversibility_class,
                )
            if proc.poll() is None:
                SubprocessRunner.kill_process_tree(proc.pid)
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
            return ToolResult(
                success=True,
                output={"service_id": service_id, "pid": proc.pid, "state": "stopped"},
                evidence={"service_id": service_id, "pid": proc.pid, "exit_code": proc.poll()},
                reversibility_class=self.reversibility_class,
            )

    def _status(self, service_id: str) -> ToolResult:
        with self._lock:
            proc = self._processes.get(service_id)
            if proc is None:
                return ToolResult(
                    success=True,
                    output={"service_id": service_id, "state": "unknown", "owned": False},
                    evidence={"service_id": service_id, "owned": False},
                    reversibility_class=self.reversibility_class,
                )
            code = proc.poll()
            state = "running" if code is None else "stopped"
            return ToolResult(
                success=True,
                output={"service_id": service_id, "pid": proc.pid, "state": state, "exit_code": code},
                evidence={"service_id": service_id, "pid": proc.pid, "state": state, "exit_code": code},
                reversibility_class=self.reversibility_class,
            )

    def _logs_result(self, service_id: str, max_lines: int) -> ToolResult:
        with self._lock:
            path = self._logs.get(service_id)
            if path is None or not path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error_message="service log unavailable in this runtime instance",
                    reversibility_class=self.reversibility_class,
                )
            max_lines = max(1, min(max_lines, 1000))
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
            except OSError as exc:
                return ToolResult(success=False, output="", error_message=str(exc))
            return ToolResult(
                success=True,
                output="\n".join(lines),
                evidence={"service_id": service_id, "log_ref": str(path), "line_count": len(lines)},
                reversibility_class=self.reversibility_class,
            )
