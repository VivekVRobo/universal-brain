"""
Universal Brain - Milestone M5 Command Runner Tests

Implements M5 Sections 89 and 93:
Tests structured execution, process-tree containment on timeout, output flood
truncation, environment secret scrubbing, directory confinement, and policy rejection.
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4
import pytest

from universal_brain.tools.runner.policies import EnvironmentSanitizer, ExecutableRegistry, ExecutionPolicyError
from universal_brain.tools.runner.process import SubprocessRunner
from universal_brain.tools.runner.schemas import CommandSpec, NetworkPolicy, TerminationReason
from universal_brain.tools.runner.tool import CommandRunnerTool
from universal_brain.tools.sandbox.confinement import PathScopeViolationError


@pytest.fixture
def runner_env():
    temp_dir = tempfile.mkdtemp(prefix="brain_runner_")
    ws_path = Path(temp_dir).resolve()
    yield ws_path
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_command_runner_normal_execution(runner_env):
    """Verify normal structured command completes with exit code 0 and cryptographic evidence."""
    ws_path = runner_env
    tool = CommandRunnerTool(ws_path)

    res = tool.execute({
        "executable": "python",
        "arguments": ["-c", "print('hello sovereign brain')"],
    })

    assert res.success is True
    assert "hello sovereign brain" in res.output
    assert res.evidence["exit_code"] == 0
    assert res.evidence["termination_reason"] == "COMPLETED"
    assert len(res.evidence["stdout_sha256"]) == 64


def test_command_runner_timeout_terminates_process_tree(runner_env):
    """Verify that timeout triggers process-tree containment without hung processes."""
    ws_path = runner_env

    # Run command that sleeps longer than timeout
    spec = CommandSpec(
        task_id=uuid4(),
        workspace_id=uuid4(),
        executable="python",
        arguments=["-c", "import time; time.sleep(10)"],
        cwd=ws_path,
        timeout_seconds=1,  # 1 second limit
    )

    result = asyncio.run(SubprocessRunner.run_spec(spec, ws_path))

    assert result.termination_reason == TerminationReason.TIMEOUT
    assert result.exit_code == -1
    assert "TIMED OUT" in result.stderr_preview or "TIMEOUT" in result.stderr_preview


def test_output_flood_protection_truncates(runner_env):
    """Verify that stdout flood is truncated at output_limit_bytes ceiling."""
    ws_path = runner_env

    # Script outputs 50,000 bytes
    spec = CommandSpec(
        task_id=uuid4(),
        workspace_id=uuid4(),
        executable="python",
        arguments=["-c", "print('A' * 50000)"],
        cwd=ws_path,
        output_limit_bytes=2048,  # Truncate at 2KB
    )

    result = asyncio.run(SubprocessRunner.run_spec(spec, ws_path))

    assert result.termination_reason == TerminationReason.COMPLETED
    assert result.truncated is True
    assert len(result.stdout_preview.encode("utf-8")) <= 3000
    assert len(result.stdout_digest) == 64


def test_environment_sanitizer_scrubs_secrets(runner_env):
    """Verify Invariant M5-INV-06: subprocesses cannot inherit secrets or API keys."""
    ws_path = runner_env

    # Simulate dirty host environment
    dirty_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "OPENAI_API_KEY": "sk-proj-super-secret-key-12345",
        "ANTHROPIC_API_KEY": "sk-ant-secret-67890",
        "HMAC_SECRET_KEY": "super-sensitive-signing-token",
        "DATABASE_URL": "postgresql://admin:secret@prod:5432/brain",
        "SAFE_VAR": "harmless_config_value",
    }

    clean = EnvironmentSanitizer.sanitize_environment(dirty_env)

    # Secrets must be scrubbed
    assert "OPENAI_API_KEY" not in clean
    assert "ANTHROPIC_API_KEY" not in clean
    assert "HMAC_SECRET_KEY" not in clean
    assert "DATABASE_URL" not in clean

    # Standard safe keys preserved
    assert "PATH" in clean
    if "SYSTEMROOT" in os.environ:
        assert "SYSTEMROOT" in clean


def test_command_runner_rejects_cwd_escape(runner_env):
    """Verify cwd outside workspace is blocked with PathScopeViolationError."""
    ws_path = runner_env
    tool = CommandRunnerTool(ws_path)

    # Attempt to run command with cwd escaping to parent
    with pytest.raises(PathScopeViolationError):
        tool.preflight_check({
            "executable": "python",
            "cwd": str(ws_path.parent),
        })


def test_executable_registry_blocks_unauthorized_binaries(runner_env):
    """Verify non-allowlisted executable is rejected with ExecutionPolicyError."""
    ws_path = runner_env
    tool = CommandRunnerTool(ws_path)

    with pytest.raises(ExecutionPolicyError):
        tool.preflight_check({
            "executable": "malicious_binary.exe",
            "cwd": str(ws_path),
        })
