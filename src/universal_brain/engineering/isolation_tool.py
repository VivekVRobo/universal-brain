"""Authority-gated execution tool for attested V5.2 isolation plans.

Traceability: REQ-ENG-024, REQ-ENG-025, REQ-ENG-033, ALN-007,
ALN-008, ALN-016.

The ToolGateway invocation carries only an opaque, one-time plan ID. Full host
commands are registered by trusted runtime code before authority is requested, so
a model cannot smuggle an arbitrary PowerShell/WSL command through tool args.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from universal_brain.kernel.events import ActionClass
from universal_brain.tools.base import BaseTool, ReversibilityClass, ToolResult
from universal_brain.tools.runner.policies import EnvironmentSanitizer
from universal_brain.tools.runner.process import SubprocessRunner
from universal_brain.tools.sandbox.confinement import confine_path

from .isolation import IsolationCommandPlan, IsolationError, NetworkMode
from .schemas import EngineeringToolObservation


class IsolationPlanExecutionTool(BaseTool):
    """Execute only runtime-registered, one-time WSL2/Hyper-V plans."""

    name = "run_isolated_command"
    action_class = ActionClass.A1
    description = "Executes a pre-registered, attested WSL2/Hyper-V isolation plan."
    reversibility_class = ReversibilityClass.REVERSIBLE_WITH_LIMITATIONS

    def __init__(
        self,
        workspace_root: Path,
        *,
        allowed_wsl_distros: set[str] | None = None,
        allowed_hyperv_vms: set[str] | None = None,
        output_limit_bytes: int = 500_000,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.allowed_wsl_distros = {item.strip() for item in (allowed_wsl_distros or set()) if item.strip()}
        self.allowed_hyperv_vms = {item.strip() for item in (allowed_hyperv_vms or set()) if item.strip()}
        self.output_limit_bytes = max(4096, int(output_limit_bytes))
        self._plans: dict[str, IsolationCommandPlan] = {}

    def register_plan(self, plan: IsolationCommandPlan) -> str:
        self._validate_plan(plan)
        plan_id = str(uuid4())
        self._plans[plan_id] = plan
        return plan_id

    def preflight_check(self, args: dict[str, Any]) -> bool:
        plan_id = str(args.get("plan_id") or "")
        plan = self._plans.get(plan_id)
        if plan is None:
            return False
        try:
            self._validate_plan(plan)
        except (IsolationError, ValueError):
            return False
        return True

    def execute(self, args: dict[str, Any]) -> ToolResult:
        plan_id = str(args.get("plan_id") or "")
        plan = self._plans.pop(plan_id, None)
        if plan is None:
            return ToolResult(
                success=False,
                output="",
                error_message="Unknown, expired, or already-consumed isolation plan",
                reversibility_class=self.reversibility_class,
            )
        try:
            self._validate_plan(plan)
        except (IsolationError, ValueError) as exc:
            return ToolResult(
                success=False,
                output="",
                error_message=f"Isolation plan rejected: {exc}",
                reversibility_class=self.reversibility_class,
            )

        clean_env = EnvironmentSanitizer.sanitize_environment(base_env=dict(os.environ))
        stdout = b""
        stderr = b""
        timed_out = False
        exit_code = -1
        try:
            kwargs: dict[str, Any] = {
                "cwd": str(plan.host_cwd),
                "env": clean_env,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "shell": False,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            process = subprocess.Popen([plan.host_executable, *plan.host_arguments], **kwargs)
            try:
                stdout, stderr = process.communicate(timeout=plan.quota.wall_seconds)
                exit_code = int(process.returncode or 0)
            except subprocess.TimeoutExpired:
                timed_out = True
                SubprocessRunner.kill_process_tree(process.pid)
                stdout, stderr = process.communicate()
        except OSError as exc:
            stderr = f"Process launch error: {exc}".encode("utf-8", errors="replace")

        stdout_digest = hashlib.sha256(stdout).hexdigest()
        stderr_digest = hashlib.sha256(stderr).hexdigest()
        preview_budget = self.output_limit_bytes
        stdout_preview = stdout[:preview_budget].decode("utf-8", errors="replace")
        stderr_preview = stderr[:preview_budget].decode("utf-8", errors="replace")
        success = exit_code == 0 and not timed_out
        return ToolResult(
            success=success,
            output=stdout_preview if success else f"{stdout_preview}\n{stderr_preview}".strip(),
            error_message=("isolated command timed out" if timed_out else None if success else "isolated command failed"),
            evidence={
                "isolation_provider": plan.provider,
                "enforced_controls": list(plan.enforced_controls),
                "network_mode": plan.quota.network_mode.value,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "stdout_sha256": stdout_digest,
                "stderr_sha256": stderr_digest,
                "plan_id": plan_id,
            },
            reversibility_class=self.reversibility_class,
            post_digest=stdout_digest,
        )

    def rollback(self, rollback_data: dict[str, Any]) -> bool:
        # The command runs inside an isolated workspace/runtime but arbitrary
        # command side effects are not generically reversible. Repository-level
        # rollback remains the responsibility of Git/checkpoint transactions.
        return False

    def _validate_plan(self, plan: IsolationCommandPlan) -> None:
        root = plan.workspace_root.resolve()
        if root != self.workspace_root:
            raise IsolationError("isolation plan workspace does not match configured workspace")
        confine_path(plan.host_cwd.resolve(), self.workspace_root)
        controls = set(plan.enforced_controls)
        required = {"memory", "cpu", "pids", "wall-timeout"}
        if not required.issubset(controls):
            raise IsolationError(f"isolation plan is missing required controls: {sorted(required - controls)}")
        if plan.quota.network_mode == NetworkMode.DENY and not ({"network-deny", "network-policy"} & controls):
            raise IsolationError("network-deny plan lacks attested network enforcement evidence")
        if plan.quota.network_mode == NetworkMode.ALLOWLIST and "network-allowlist" not in controls and "network-policy" not in controls:
            raise IsolationError("network allowlist plan lacks allowlist enforcement evidence")

        executable = Path(plan.host_executable).name.lower()
        if plan.provider == "wsl2":
            if executable not in {"wsl", "wsl.exe"}:
                raise IsolationError("WSL2 plan must execute through wsl.exe")
            if not self.allowed_wsl_distros:
                raise IsolationError("no WSL2 distro is authorized for isolated execution")
            try:
                idx = plan.host_arguments.index("--distribution")
                distro = plan.host_arguments[idx + 1]
            except (ValueError, IndexError) as exc:
                raise IsolationError("WSL2 plan is missing an explicit distribution") from exc
            if distro not in self.allowed_wsl_distros:
                raise IsolationError(f"WSL2 distro is not authorized: {distro}")
        elif plan.provider == "hyperv":
            if executable not in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
                raise IsolationError("Hyper-V plan must execute through PowerShell")
            if not self.allowed_hyperv_vms:
                raise IsolationError("no Hyper-V VM is authorized for isolated execution")
            command_text = " ".join(plan.host_arguments)
            if not any(vm in command_text for vm in self.allowed_hyperv_vms):
                raise IsolationError("Hyper-V plan does not target an authorized VM")
        else:
            raise IsolationError(f"unsupported isolation provider: {plan.provider}")


class ToolGatewayIsolationBackend:
    """Bridge ``AuthorityGatedIsolationRuntime`` to ToolGateway.

    Capability minting is injected and remains external to this backend.
    """

    def __init__(
        self,
        *,
        gateway,
        tool: IsolationPlanExecutionTool,
        contract,
        capability_token_provider: Callable[[IsolationCommandPlan], Any],
    ) -> None:
        self.gateway = gateway
        self.tool = tool
        self.contract = contract
        self.capability_token_provider = capability_token_provider

    async def execute_plan(self, plan: IsolationCommandPlan) -> EngineeringToolObservation:
        plan_id = self.tool.register_plan(plan)
        token = self.capability_token_provider(plan)
        try:
            result = self.gateway.execute_tool(
                tool_name=self.tool.name,
                args={"plan_id": plan_id},
                capability_token=token,
                contract=self.contract,
                actor_id="engineering_isolation_runtime",
                target_resource=str(plan.workspace_root),
            )
            return EngineeringToolObservation(
                tool_name=self.tool.name,
                call_id=plan_id,
                success=bool(result.success),
                output=str(result.output),
                evidence=dict(result.evidence or {}),
                error=result.error_message,
            )
        except Exception as exc:
            # Prevent plan replay if authority validation fails before tool execution.
            self.tool._plans.pop(plan_id, None)
            return EngineeringToolObservation(
                tool_name=self.tool.name,
                call_id=plan_id,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )
