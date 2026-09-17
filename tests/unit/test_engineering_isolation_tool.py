from __future__ import annotations

from pathlib import Path

from universal_brain.engineering.isolation import (
    IsolationCapabilities,
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


def test_isolation_tool_executes_only_registered_authorized_one_time_plan(tmp_path: Path, monkeypatch):
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
    plan = provider.build_plan(
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
    tool = IsolationPlanExecutionTool(tmp_path, allowed_wsl_distros={"Ubuntu-24.04"})
    plan_id = tool.register_plan(plan)
    assert tool.preflight_check({"plan_id": plan_id})

    monkeypatch.setattr("universal_brain.engineering.isolation_tool.subprocess.Popen", FakeProcess)
    result = tool.execute({"plan_id": plan_id})
    assert result.success
    assert result.output.strip() == "isolated-ok"
    assert result.evidence["isolation_provider"] == "wsl2"
    assert result.evidence["network_mode"] == "deny"

    # Opaque plan IDs are one-shot; replay is rejected.
    assert not tool.preflight_check({"plan_id": plan_id})
    replay = tool.execute({"plan_id": plan_id})
    assert not replay.success


def test_isolation_tool_fails_closed_without_authorized_distro(tmp_path: Path):
    provider = WSL2IsolationProvider(
        distro="Ubuntu",
        capabilities=IsolationCapabilities(
            memory_limit=True,
            cpu_limit=True,
            pid_limit=True,
            deny_network=True,
            wall_timeout=True,
        ),
    )
    plan = provider.build_plan(
        workspace_root=tmp_path,
        linux_workspace="/workspace",
        executable="pytest",
        arguments=[],
        quota=IsolationQuota(network_mode=NetworkMode.DENY),
        host_cwd=tmp_path,
    )
    tool = IsolationPlanExecutionTool(tmp_path)
    try:
        tool.register_plan(plan)
    except Exception as exc:
        assert "no WSL2 distro is authorized" in str(exc)
    else:
        raise AssertionError("plan should fail closed without an authorized distro")


def test_hyperv_attested_network_policy_is_accepted_for_authorized_vm(tmp_path: Path):
    from universal_brain.engineering.isolation import HyperVIsolationProvider

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
    plan = provider.build_plan(
        workspace_root=tmp_path,
        guest_workspace="C:\\workspace",
        executable="python.exe",
        arguments=["-c", "print('ok')"],
        quota=IsolationQuota(network_mode=NetworkMode.DENY),
        host_cwd=tmp_path,
    )
    tool = IsolationPlanExecutionTool(tmp_path, allowed_hyperv_vms={"UB-Sandbox"})
    plan_id = tool.register_plan(plan)
    assert tool.preflight_check({"plan_id": plan_id})
