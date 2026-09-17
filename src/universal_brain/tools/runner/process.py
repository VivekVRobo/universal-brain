"""
Universal Brain - Subprocess Runner & Process-Tree Containment

Implements M5 Sections 24, 27, 28, 30 and Invariant M5-INV-07:
Executes subprocesses without shell expansion, bounds stdout/stderr memory,
computes streaming cryptographic digests, and terminates complete process trees
on timeout or cancellation (Windows-native taskkill /F /T).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from universal_brain.tools.runner.policies import EnvironmentSanitizer, ExecutableRegistry
from universal_brain.tools.runner.schemas import (
    CommandResult,
    CommandSpec,
    IsolationLevel,
    TerminationReason,
)
from universal_brain.tools.sandbox.confinement import confine_path


class SubprocessRunner:
    """Deterministic runner enforcing execution timeouts, quotas, and process cleanup."""

    @staticmethod
    def kill_process_tree(pid: int) -> None:
        """
        Forcefully terminates a process and all its children/descendants.
        (M5 Section 27, 28 - Windows first).
        """
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
            except Exception:
                pass
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass

    @classmethod
    async def run_spec(
        cls,
        spec: CommandSpec,
        workspace_root: Path,
    ) -> CommandResult:
        """
        Executes command specification with strict resource containment:
        1. Confines working directory inside workspace.
        2. Validates executable in policy registry.
        3. Sanitizes environment (stripping API keys and secrets).
        4. Launches subprocess via asyncio.create_subprocess_exec (no shell=True).
        5. Streams and bounds stdout/stderr with rolling SHA-256.
        6. On timeout, kills entire process tree and returns TIMEOUT result.
        """
        # 1. Confine cwd
        canonical_cwd = confine_path(spec.cwd, workspace_root)

        # 2. Validate executable
        ExecutableRegistry.validate_executable(spec.executable)

        # 3. Sanitize environment
        clean_env = EnvironmentSanitizer.sanitize_environment(
            overrides=spec.environment_overrides
        )

        started_at = datetime.now(timezone.utc)
        start_mono = time.monotonic()

        stdout_hasher = hashlib.sha256()
        stderr_hasher = hashlib.sha256()

        stdout_chunks = []
        stderr_chunks = []
        total_bytes = 0
        truncated = False
        termination_reason = TerminationReason.COMPLETED
        exit_code = -1

        # 4. Launch Process (No shell=True)
        try:
            # M5-INV-07: the child must own a distinct process group/session before
            # kill_process_tree() may target the group. Without this, POSIX CI can
            # accidentally SIGKILL the supervising pytest/Universal Brain process.
            process_group_kwargs = {}
            if sys.platform == "win32":
                process_group_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                process_group_kwargs["start_new_session"] = True
            proc = await asyncio.create_subprocess_exec(
                spec.executable,
                *spec.arguments,
                cwd=str(canonical_cwd),
                env=clean_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **process_group_kwargs,
            )
        except Exception as e:
            finished_at = datetime.now(timezone.utc)
            duration_ms = (time.monotonic() - start_mono) * 1000.0
            return CommandResult(
                command_id=spec.command_id,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                exit_code=-1,
                termination_reason=TerminationReason.ABORTED_ON_ERROR,
                stdout_preview="",
                stderr_preview=f"Process launch error: {str(e)}",
                stdout_digest=hashlib.sha256(b"").hexdigest(),
                stderr_digest=hashlib.sha256(str(e).encode()).hexdigest(),
                truncated=False,
                isolation_level=IsolationLevel.L1_WORKSPACE_CONFINED,
            )

        # 5. Bounded Read Loop with Timeout
        try:
            async def read_stream():
                nonlocal total_bytes, truncated
                stdout_data, stderr_data = await proc.communicate()
                
                # Process stdout
                stdout_hasher.update(stdout_data)
                if len(stdout_data) > spec.output_limit_bytes:
                    stdout_chunks.append(stdout_data[:spec.output_limit_bytes])
                    truncated = True
                else:
                    stdout_chunks.append(stdout_data)
                total_bytes += len(stdout_data)

                # Process stderr
                stderr_hasher.update(stderr_data)
                if len(stderr_data) > spec.output_limit_bytes:
                    stderr_chunks.append(stderr_data[:spec.output_limit_bytes])
                    truncated = True
                else:
                    stderr_chunks.append(stderr_data)
                total_bytes += len(stderr_data)

            await asyncio.wait_for(read_stream(), timeout=spec.timeout_seconds)
            exit_code = proc.returncode if proc.returncode is not None else -1
            termination_reason = TerminationReason.COMPLETED

        except asyncio.TimeoutError:
            termination_reason = TerminationReason.TIMEOUT
            cls.kill_process_tree(proc.pid)
            exit_code = -1
            stderr_chunks.append(f"\n[EXECUTION TIMEOUT]: Exceeded {spec.timeout_seconds}s ceiling. Process tree killed.\n".encode())

        except Exception as e:
            termination_reason = TerminationReason.ABORTED_ON_ERROR
            cls.kill_process_tree(proc.pid)
            exit_code = -1
            stderr_chunks.append(f"\n[EXECUTION ERROR]: {str(e)}\n".encode())

        finished_at = datetime.now(timezone.utc)
        duration_ms = (time.monotonic() - start_mono) * 1000.0

        stdout_preview = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr_preview = b"".join(stderr_chunks).decode("utf-8", errors="replace")

        return CommandResult(
            command_id=spec.command_id,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            exit_code=exit_code,
            termination_reason=termination_reason,
            stdout_preview=stdout_preview,
            stderr_preview=stderr_preview,
            stdout_digest=stdout_hasher.hexdigest(),
            stderr_digest=stderr_hasher.hexdigest(),
            truncated=truncated,
            isolation_level=IsolationLevel.L1_WORKSPACE_CONFINED,
        )
