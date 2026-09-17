"""OS-level engineering execution isolation plans for Universal Brain V5.2.

Traceability: REQ-ENG-024, REQ-ENG-025, REQ-TOL-001, ALN-007, ALN-016.
This module never launches subprocesses directly. It produces deterministic,
reviewable isolation plans and delegates execution to an injected authority-gated
backend (normally ToolGateway/run_command on Windows).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from .schemas import EngineeringToolObservation


class IsolationError(RuntimeError):
    pass


class NetworkMode(str, Enum):
    DENY = "deny"
    ALLOWLIST = "allowlist"
    FULL = "full"


class IsolationQuota(BaseModel):
    memory_mb: int = Field(default=4096, ge=128)
    cpu_percent: int = Field(default=200, ge=1, le=1600)
    pids_max: int = Field(default=256, ge=8, le=65535)
    wall_seconds: int = Field(default=900, ge=1, le=86400)
    network_mode: NetworkMode = NetworkMode.DENY
    allowed_hosts: list[str] = Field(default_factory=list)

    @field_validator("allowed_hosts")
    @classmethod
    def hosts_only_with_allowlist(cls, value: list[str]) -> list[str]:
        return sorted({host.strip().lower() for host in value if host.strip()})


class IsolationCapabilities(BaseModel):
    memory_limit: bool = False
    cpu_limit: bool = False
    pid_limit: bool = False
    deny_network: bool = False
    allowlist_network: bool = False
    wall_timeout: bool = True


class IsolationCommandPlan(BaseModel):
    provider: str
    host_executable: str
    host_arguments: list[str]
    host_cwd: Path
    workspace_root: Path
    quota: IsolationQuota
    enforced_controls: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class IsolationExecutionBackend(Protocol):
    async def execute_plan(self, plan: IsolationCommandPlan) -> EngineeringToolObservation: ...


class WSL2IsolationProvider:
    """Build bounded WSL2 execution plans using systemd-run/unshare when available.

    WSL2 itself is not assumed to provide a security boundary automatically. The
    caller supplies probed capabilities; requested controls that cannot be enforced
    cause a fail-closed error instead of being silently ignored.
    """

    def __init__(
        self,
        *,
        distro: str,
        capabilities: IsolationCapabilities,
        systemd_run_path: str = "/usr/bin/systemd-run",
        unshare_path: str = "/usr/bin/unshare",
    ) -> None:
        if not distro.strip():
            raise ValueError("WSL2 distro is required")
        self.distro = distro
        self.capabilities = capabilities
        self.systemd_run_path = systemd_run_path
        self.unshare_path = unshare_path

    def build_plan(
        self,
        *,
        workspace_root: Path,
        linux_workspace: str,
        executable: str,
        arguments: list[str],
        quota: IsolationQuota,
        host_cwd: Path,
    ) -> IsolationCommandPlan:
        self._validate_quota_support(quota)
        if not linux_workspace.startswith("/"):
            raise IsolationError("linux_workspace must be an absolute WSL path")
        if not executable.strip() or executable.startswith("-"):
            raise IsolationError("isolated executable must be explicit")

        controls: list[str] = []
        command: list[str] = [
            self.systemd_run_path,
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--same-dir",
        ]
        if self.capabilities.memory_limit:
            command += ["-p", f"MemoryMax={quota.memory_mb}M"]
            controls.append("memory")
        if self.capabilities.cpu_limit:
            command += ["-p", f"CPUQuota={quota.cpu_percent}%"]
            controls.append("cpu")
        if self.capabilities.pid_limit:
            command += ["-p", f"TasksMax={quota.pids_max}"]
            controls.append("pids")

        command += ["--working-directory", linux_workspace, "--"]
        if quota.network_mode == NetworkMode.DENY:
            command += [self.unshare_path, "--net", "--"]
            controls.append("network-deny")
        elif quota.network_mode == NetworkMode.ALLOWLIST:
            # Allowlisting must be implemented by a preconfigured egress guard in
            # the authority-gated backend. Hosts are recorded in the plan so the
            # executor can apply/verify policy before launching the command.
            controls.append("network-allowlist")
        command += [executable, *arguments]
        if self.capabilities.wall_timeout:
            controls.append("wall-timeout")

        return IsolationCommandPlan(
            provider="wsl2",
            host_executable="wsl.exe",
            host_arguments=["--distribution", self.distro, "--", *command],
            host_cwd=host_cwd.resolve(),
            workspace_root=workspace_root.resolve(),
            quota=quota,
            enforced_controls=controls,
            notes=(
                [f"egress_allowlist={','.join(quota.allowed_hosts)}"]
                if quota.network_mode == NetworkMode.ALLOWLIST
                else []
            ),
        )

    def _validate_quota_support(self, quota: IsolationQuota) -> None:
        required = {
            "memory_limit": self.capabilities.memory_limit,
            "cpu_limit": self.capabilities.cpu_limit,
            "pid_limit": self.capabilities.pid_limit,
            "wall_timeout": self.capabilities.wall_timeout,
        }
        missing = [name for name, supported in required.items() if not supported]
        if missing:
            raise IsolationError(f"WSL2 isolation cannot enforce requested controls: {', '.join(missing)}")
        if quota.network_mode == NetworkMode.DENY and not self.capabilities.deny_network:
            raise IsolationError("WSL2 isolation cannot enforce network deny policy")
        if quota.network_mode == NetworkMode.ALLOWLIST:
            if not quota.allowed_hosts:
                raise IsolationError("network allowlist mode requires at least one host")
            if not self.capabilities.allowlist_network:
                raise IsolationError("WSL2 isolation cannot enforce network allowlist policy")
            raise IsolationError(
                "WSL2 network allowlist has no executable enforcement backend; "
                "use network DENY until an egress guard is configured and verified"
            )


class HyperVIsolationProvider:
    """Create a PowerShell-Direct plan for an existing managed Hyper-V VM.

    VM creation, credentials and network policy are deployment concerns. Universal
    Brain only targets a pre-authorized VM and fails closed if deployment has not
    attested the requested resource/network controls.
    """

    def __init__(self, *, vm_name: str, capabilities: IsolationCapabilities) -> None:
        if not vm_name.strip():
            raise ValueError("Hyper-V vm_name is required")
        self.vm_name = vm_name
        self.capabilities = capabilities

    def build_plan(
        self,
        *,
        workspace_root: Path,
        guest_workspace: str,
        executable: str,
        arguments: list[str],
        quota: IsolationQuota,
        host_cwd: Path,
    ) -> IsolationCommandPlan:
        self._validate(quota)
        # This is deliberately a declarative PowerShell Direct invocation. The
        # authority-gated backend is responsible for credential/session binding.
        quoted_args = ",".join(repr(arg) for arg in arguments)
        script = (
            f"Set-Location -LiteralPath {guest_workspace!r}; "
            f"& {executable!r} @({quoted_args}); exit $LASTEXITCODE"
        )
        return IsolationCommandPlan(
            provider="hyperv",
            host_executable="powershell.exe",
            host_arguments=[
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"Invoke-Command -VMName {self.vm_name!r} -ScriptBlock {{ {script} }}",
            ],
            host_cwd=host_cwd.resolve(),
            workspace_root=workspace_root.resolve(),
            quota=quota,
            enforced_controls=[],
            notes=["runtime Hyper-V policy attestation required before execution"],
        )

    def _validate(self, quota: IsolationQuota) -> None:
        checks = [
            self.capabilities.memory_limit,
            self.capabilities.cpu_limit,
            self.capabilities.pid_limit,
            self.capabilities.wall_timeout,
        ]
        if not all(checks):
            raise IsolationError("Hyper-V deployment has not attested all requested resource controls")
        if quota.network_mode == NetworkMode.DENY and not self.capabilities.deny_network:
            raise IsolationError("Hyper-V deployment cannot attest network deny")
        if quota.network_mode == NetworkMode.ALLOWLIST and not self.capabilities.allowlist_network:
            raise IsolationError("Hyper-V deployment cannot attest network allowlist")


class AuthorityGatedIsolationRuntime:
    """Execute previously validated isolation plans through an authority boundary."""

    def __init__(self, backend: IsolationExecutionBackend) -> None:
        self.backend = backend

    async def execute(self, plan: IsolationCommandPlan) -> EngineeringToolObservation:
        observation = await self.backend.execute_plan(plan)
        if not observation.success:
            return observation

        evidence = dict(observation.evidence)
        verified_controls = set(evidence.get("verified_controls") or [])
        required_controls = {"memory", "cpu", "pids", "wall-timeout"}
        if plan.quota.network_mode == NetworkMode.DENY:
            required_controls.add("network-deny")
        elif plan.quota.network_mode == NetworkMode.ALLOWLIST:
            required_controls.add("network-allowlist")

        missing = sorted(required_controls - verified_controls)
        if missing:
            raise IsolationError(
                "isolation backend did not prove required controls: "
                + ", ".join(missing)
            )

        evidence["isolation_provider"] = plan.provider
        evidence["network_mode"] = plan.quota.network_mode.value
        evidence["verified_controls"] = sorted(verified_controls)
        return observation.model_copy(update={"evidence": evidence})
