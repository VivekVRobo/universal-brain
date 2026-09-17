from __future__ import annotations

from pathlib import Path

import pytest

from universal_brain.engineering.isolation import (
    HyperVIsolationProvider,
    IsolationCapabilities,
    IsolationError,
    IsolationQuota,
    NetworkMode,
    WSL2IsolationProvider,
)
from universal_brain.engineering.isolation_tool import IsolationPlanExecutionTool


class FakeProcess:
    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.returncode = 0
        self.pid = 12345

    def communicate(self, timeout=None):
        return b"isolated-ok\n", b""


def _wsl_plan(tmp_path: Path):
    provider = WSL2IsolationProvider(
        distro="Ubuntu-24.04",
        capabilities=IsolationCapabilities(
            memory_limit=True,
            cpu_limit=True,
            pid_limit=True,
            deny_network=True,
            wall_timeout=True,
        ),
    )
    return provider.build_plan(
        workspace_root=tmp_path,
        linux_workspace="/mnt/c/project",
        executable="pytest",
        arguments=["-q"],
        quota=IsolationQuota(
            memory_mb=512,
            cpu_percent=100,
            pids_max=32,
            wall_seconds=30,
            network_mode=NetworkMode.DENY,
        ),
        host_cwd=tmp_path,
    )


def test_isolation_tool_executes_only_registered_authorized_one_time_plan(tmp_path: Path, monkeypatch):
    plan = _wsl_plan(tmp_path)
    tool = IsolationPlanExecutionTool(tmp_path, allowed_wsl_distros={"Ubuntu-24.04"})
    plan_id = tool.register_plan(plan)
    assert tool.preflight_check({"plan_id": plan_id})

    monkeypatch.setattr("universal_brain.engineering.isolation_tool.subprocess.Popen", FakeProcess)
    result = tool.execute({"plan_id": plan_id})
    assert result.success
    assert result.output.strip() == "isolated-ok"
    assert result.evidence["isolation_provider"] == "wsl2"
    assert result.evidence["network_mode"] == "deny"
    assert set(result.evidence["verified_controls"]) == {
        "memory",
        "cpu",
        "pids",
        "network-deny",
        "wall-timeout",
    }

    assert not tool.preflight_check({"plan_id": plan_id})
    replay = tool.execute({"plan_id": plan_id})
    assert not replay.success


def test_isolation_tool_fails_closed_without_authorized_distro(tmp_path: Path):
    plan = _wsl_plan(tmp_path)
    tool = IsolationPlanExecutionTool(tmp_path)
    with pytest.raises(IsolationError, match="no WSL2 distro is authorized"):
        tool.register_plan(plan)


def test_wsl_control_labels_cannot_forge_missing_command_enforcement(tmp_path: Path):
    plan = _wsl_plan(tmp_path)
    tampered_args = [
        arg for arg in plan.host_arguments
        if arg != f"MemoryMax={plan.quota.memory_mb}M"
    ]
    tampered = plan.model_copy(
        update={
            "host_arguments": tampered_args,
            "enforced_controls": [
                "memory",
                "cpu",
                "pids",
                "network-deny",
                "wall-timeout",
            ],
        }
    )
    tool = IsolationPlanExecutionTool(tmp_path, allowed_wsl_distros={"Ubuntu-24.04"})
    with pytest.raises(IsolationError, match="required memory control"):
        tool.register_plan(tampered)


def test_wsl_allowlist_fails_closed_without_executable_egress_guard(tmp_path: Path):
    provider = WSL2IsolationProvider(
        distro="Ubuntu-24.04",
        capabilities=IsolationCapabilities(
            memory_limit=True,
            cpu_limit=True,
            pid_limit=True,
            deny_network=True,
            allowlist_network=True,
            wall_timeout=True,
        ),
    )
    with pytest.raises(IsolationError, match="no executable enforcement backend"):
        provider.build_plan(
            workspace_root=tmp_path,
            linux_workspace="/mnt/c/project",
            executable="pytest",
            arguments=[],
            quota=IsolationQuota(
                network_mode=NetworkMode.ALLOWLIST,
                allowed_hosts=["pypi.org"],
            ),
            host_cwd=tmp_path,
        )


def _hyperv_plan(tmp_path: Path):
    provider = HyperVIsolationProvider(
        vm_name="UB-Sandbox",
        capabilities=IsolationCapabilities(
            memory_limit=True,
            cpu_limit=True,
            pid_limit=True,
            deny_network=True,
            wall_timeout=True,
        ),
    )
    return provider.build_plan(
        workspace_root=tmp_path,
        guest_workspace="C:\\workspace",
        executable="python.exe",
        arguments=["-c", "print('ok')"],
        quota=IsolationQuota(network_mode=NetworkMode.DENY),
        host_cwd=tmp_path,
    )


def test_hyperv_plan_is_rejected_without_runtime_attestation(tmp_path: Path):
    plan = _hyperv_plan(tmp_path)
    assert plan.enforced_controls == []
    tool = IsolationPlanExecutionTool(tmp_path, allowed_hyperv_vms={"UB-Sandbox"})
    with pytest.raises(IsolationError, match="runtime policy attestation verifier"):
        tool.register_plan(plan)


def test_hyperv_runtime_attestation_must_cover_all_required_controls(tmp_path: Path):
    plan = _hyperv_plan(tmp_path)

    incomplete = IsolationPlanExecutionTool(
        tmp_path,
        allowed_hyperv_vms={"UB-Sandbox"},
        hyperv_attestation_verifier=lambda _plan: {"memory", "cpu"},
    )
    with pytest.raises(IsolationError, match="missing required controls"):
        incomplete.register_plan(plan)

    verified = IsolationPlanExecutionTool(
        tmp_path,
        allowed_hyperv_vms={"UB-Sandbox"},
        hyperv_attestation_verifier=lambda _plan: {
            "memory",
            "cpu",
            "pids",
            "network-deny",
            "wall-timeout",
        },
    )
    plan_id = verified.register_plan(plan)
    assert verified.preflight_check({"plan_id": plan_id})
