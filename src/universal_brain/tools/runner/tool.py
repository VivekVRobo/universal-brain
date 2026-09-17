"""
Universal Brain - Command Runner Tool

Implements M5 Sections 22-31, 40:
Concrete BaseTool wrapping SubprocessRunner for integration with ToolGateway.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID, uuid4

from universal_brain.kernel.events import ActionClass
from universal_brain.tools.base import BaseTool, ReversibilityClass, ToolResult
from universal_brain.tools.runner.policies import ExecutableRegistry
from universal_brain.tools.runner.process import SubprocessRunner
from universal_brain.tools.runner.schemas import CommandSpec, NetworkPolicy, TerminationReason
from universal_brain.tools.sandbox.confinement import confine_path


class CommandRunnerTool(BaseTool):
    """Subprocess command runner tool (ActionClass A1 or A0 depending on command)."""

    name: str = "run_command"
    action_class: ActionClass = ActionClass.A1
    description: str = "Executes approved commands with strict timeouts, quotas, and process-tree containment."
    reversibility_class: ReversibilityClass = ReversibilityClass.REVERSIBLE_WITH_LIMITATIONS

    def __init__(
        self,
        workspace_root: Path,
        default_timeout_seconds: int = 60,
        default_output_limit_bytes: int = 500_000,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.default_timeout_seconds = default_timeout_seconds
        self.default_output_limit_bytes = default_output_limit_bytes

    def preflight_check(self, args: Dict[str, Any], target_resource: str = "*") -> bool:
        executable = args.get("executable") or (args.get("command", "").split()[0] if args.get("command") else "")
        if not executable:
            return False
        ExecutableRegistry.validate_executable(executable)

        cwd = args.get("cwd") or str(self.workspace_root)
        confine_path(cwd, self.workspace_root)
        return True

    def execute(self, args: Dict[str, Any], target_resource: str = "*") -> ToolResult:
        executable = args.get("executable")
        arguments = args.get("arguments", [])
        if not executable and args.get("command"):
            parts = args["command"].split()
            executable = parts[0]
            arguments = parts[1:]

        cwd = Path(args.get("cwd") or self.workspace_root)
        timeout = int(args.get("timeout_seconds", self.default_timeout_seconds))
        output_limit = int(args.get("output_limit_bytes", self.default_output_limit_bytes))

        spec = CommandSpec(
            task_id=uuid4(),
            workspace_id=uuid4(),
            executable=executable,
            arguments=arguments,
            cwd=cwd,
            timeout_seconds=timeout,
            output_limit_bytes=output_limit,
            environment_overrides=args.get("env", {}),
            network_policy=NetworkPolicy.LOCAL_ONLY,
            action_class=self.action_class,
        )

        # Run synchronously via asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(asyncio.run, SubprocessRunner.run_spec(spec, self.workspace_root)).result()
        else:
            result = asyncio.run(SubprocessRunner.run_spec(spec, self.workspace_root))

        success = (result.exit_code == 0 and result.termination_reason == TerminationReason.COMPLETED)

        recorded_rollback = None
        compensation = args.get("compensation_command")
        verification = args.get("verification_command")
        if (
            isinstance(compensation, list)
            and compensation
            and isinstance(verification, list)
            and verification
        ):
            recorded_rollback = {
                "compensation_command": [str(item) for item in compensation],
                "verification_command": [str(item) for item in verification],
                "cwd": str(cwd.resolve()),
                "timeout_seconds": int(args.get("rollback_timeout_seconds", 30)),
            }

        return ToolResult(
            success=success,
            output=result.stdout_preview if success else f"{result.stdout_preview}\n{result.stderr_preview}",
            evidence={
                "command_id": str(result.command_id),
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "termination_reason": result.termination_reason.value,
                "stdout_sha256": result.stdout_digest,
                "stderr_sha256": result.stderr_digest,
                "truncated": result.truncated,
                "isolation_level": result.isolation_level.value,
                "rollback_recipe_recorded": recorded_rollback is not None,
            },
            rollback_data=recorded_rollback,
            reversibility_class=self.reversibility_class,
            post_digest=result.stdout_digest,
        )

    def _run_rollback_command(
        self,
        command: List[str],
        rollback_data: Dict[str, Any],
    ):
        if not command:
            return None
        executable = str(command[0])
        ExecutableRegistry.validate_executable(executable)
        cwd = Path(rollback_data.get("cwd") or self.workspace_root)
        confined_cwd = confine_path(cwd, self.workspace_root)
        spec = CommandSpec(
            task_id=uuid4(),
            workspace_id=uuid4(),
            executable=executable,
            arguments=[str(item) for item in command[1:]],
            cwd=confined_cwd,
            timeout_seconds=int(rollback_data.get("timeout_seconds", 30)),
            output_limit_bytes=self.default_output_limit_bytes,
            environment_overrides={},
            network_policy=NetworkPolicy.LOCAL_ONLY,
            action_class=self.action_class,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run,
                    SubprocessRunner.run_spec(spec, self.workspace_root),
                ).result()
        return asyncio.run(SubprocessRunner.run_spec(spec, self.workspace_root))

    def rollback(self, rollback_data: Dict[str, Any]) -> bool:
        """Run only an explicitly recorded compensation command.

        A generic "checkpoint" marker is not a rollback mechanism and is rejected.
        """
        command = rollback_data.get("compensation_command")
        if not isinstance(command, list) or not command:
            return False
        try:
            result = self._run_rollback_command([str(item) for item in command], rollback_data)
        except Exception:
            return False
        return bool(
            result
            and result.exit_code == 0
            and result.termination_reason == TerminationReason.COMPLETED
        )

    def verify_rollback(self, rollback_data: Dict[str, Any]) -> bool:
        """Verify compensation with a separate, explicitly recorded probe."""
        command = rollback_data.get("verification_command")
        if not isinstance(command, list) or not command:
            return False
        try:
            result = self._run_rollback_command([str(item) for item in command], rollback_data)
        except Exception:
            return False
        return bool(
            result
            and result.exit_code == 0
            and result.termination_reason == TerminationReason.COMPLETED
        )
