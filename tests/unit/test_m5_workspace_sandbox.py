"""
Universal Brain - Milestone M5 Workspace Sandbox Tests

Implements M5 Sections 88 and 92:
Tests path confinement, text patch simulation, binary blob restore,
tombstone deletion, stale checkpoint rejection, and sliding-window pruning.
"""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4
import pytest

from universal_brain.kernel.errors import RollbackPreflightError
from universal_brain.tools.base import ReversibilityClass
from universal_brain.tools.sandbox.confinement import PathScopeViolationError, confine_path
from universal_brain.tools.sandbox.file_tools import FileDeleteTool, FilePatchTool, FileReadTool, FileWriteTool
from universal_brain.tools.sandbox.manifests import hash_file
from universal_brain.tools.sandbox.patching import TextPatchReversibilityEngine
from universal_brain.tools.sandbox.workspace import (
    RollbackExecutionError,
    StaleCheckpointError,
    WorkspaceTransactionManager,
)


@pytest.fixture
def workspace_env():
    temp_dir = tempfile.mkdtemp(prefix="brain_ws_")
    ws_path = Path(temp_dir).resolve()
    p_id = uuid4()
    t_id = uuid4()
    tx_manager = WorkspaceTransactionManager(ws_path, p_id, t_id, max_active_checkpoints=10)
    yield ws_path, tx_manager
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_path_confinement_blocks_traversals(workspace_env):
    """Verify PathScopeViolationError on traversal or absolute escape."""
    ws_path, _ = workspace_env

    # 1. Valid path inside workspace
    valid = confine_path("src/robot.cpp", ws_path)
    assert str(valid).startswith(str(ws_path))

    # 2. Relative traversal escape
    with pytest.raises(PathScopeViolationError):
        confine_path("../../etc/shadow", ws_path)

    # 3. Absolute path escape
    with pytest.raises(PathScopeViolationError):
        confine_path("C:\\Windows\\System32\\cmd.exe", ws_path)

    # 4. UNC path escape
    with pytest.raises(PathScopeViolationError):
        confine_path("\\\\server\\share\\data", ws_path)


def test_text_write_and_rollback_parity(workspace_env):
    """Verify text patch dry-run simulation and exact SHA-256 rollback restoration."""
    ws_path, tx_manager = workspace_env
    target_rel = "src/controller.cpp"
    target_abs = ws_path / "src" / "controller.cpp"
    target_abs.parent.mkdir(parents=True, exist_ok=True)

    original_code = "void balance() {\n    // Original PID\n    double kp = 1.0;\n}\n"
    target_abs.write_text(original_code, encoding="utf-8")
    pre_sha = hash_file(target_abs)

    # Stage modification
    new_code = "void balance() {\n    // Tuned PID\n    double kp = 2.5;\n    double kd = 0.1;\n}\n"
    write_tool = FileWriteTool(tx_manager)

    # Preflight Check
    assert write_tool.preflight_check({"target": target_rel, "content": new_code}) is True

    # Execute
    res = write_tool.execute({"target": target_rel, "content": new_code})
    assert res.success is True
    assert res.reversibility_class == ReversibilityClass.VERIFIED_REVERSIBLE
    assert hash_file(target_abs) != pre_sha

    # Rollback
    rb_success = write_tool.rollback(res.rollback_data)
    assert rb_success is True

    # Verify exact pre-state cryptographic parity (M5-INV-04)
    assert hash_file(target_abs) == pre_sha
    assert target_abs.read_text(encoding="utf-8") == original_code


def test_binary_mutation_and_preimage_restore(workspace_env):
    """Verify content-addressed pre-image restore for binary files."""
    ws_path, tx_manager = workspace_env
    target_rel = "bin/model.weights"
    target_abs = ws_path / "bin" / "model.weights"
    target_abs.parent.mkdir(parents=True, exist_ok=True)

    orig_bytes = b"\x00\x01\x02\x03\x04\xDE\xAD\xBE\xEF"
    target_abs.write_bytes(orig_bytes)
    pre_sha = hashlib.sha256(orig_bytes).hexdigest()

    new_bytes = b"\xFF\xFE\xFD\xFC\x00\x11\x22\x33\x44"

    # Checkpoint and apply
    checkpoint = tx_manager.create_binary_checkpoint(target_rel, new_bytes)
    assert checkpoint.reversibility_class == ReversibilityClass.VERIFIED_REVERSIBLE
    tx_manager.apply_checkpoint(checkpoint, content_override=new_bytes)

    assert target_abs.read_bytes() == new_bytes

    # Rollback
    tx_manager.rollback_checkpoint(checkpoint)
    assert target_abs.read_bytes() == orig_bytes
    assert hash_file(target_abs) == pre_sha


def test_file_delete_tombstone_restore(workspace_env):
    """Verify safe deletion with tombstone backup and verified restoration."""
    ws_path, tx_manager = workspace_env
    target_rel = "config/params.yaml"
    target_abs = ws_path / "config" / "params.yaml"
    target_abs.parent.mkdir(parents=True, exist_ok=True)

    yaml_data = "robot:\n  rate_hz: 500\n  safety_limit: 0.8\n"
    target_abs.write_text(yaml_data, encoding="utf-8")
    pre_sha = hash_file(target_abs)

    del_tool = FileDeleteTool(tx_manager)
    assert del_tool.preflight_check({"target": target_rel}) is True

    res = del_tool.execute({"target": target_rel})
    assert res.success is True
    assert not target_abs.exists()

    # Rollback restores file
    rb_success = del_tool.rollback(res.rollback_data)
    assert rb_success is True
    assert target_abs.is_file()
    assert hash_file(target_abs) == pre_sha


def test_stale_checkpoint_optimistic_concurrency(workspace_env):
    """Verify StaleCheckpointError if file is modified externally after preflight."""
    ws_path, tx_manager = workspace_env
    target_rel = "src/main.py"
    target_abs = ws_path / "src" / "main.py"
    target_abs.parent.mkdir(parents=True, exist_ok=True)
    target_abs.write_text("print('version 1')", encoding="utf-8")

    # Stage checkpoint based on version 1
    checkpoint = tx_manager.create_text_checkpoint(target_rel, "print('version 2')")

    # External modification occurs before apply
    target_abs.write_text("print('external rogue edit')", encoding="utf-8")

    # Apply attempt must fail closed (M5-INV-05)
    with pytest.raises(StaleCheckpointError):
        tx_manager.apply_checkpoint(checkpoint, content_override="print('version 2')")


def test_sliding_window_checkpoint_pruning(workspace_env):
    """Verify active checkpoints are capped at 10 and older ones are archived."""
    ws_path, tx_manager = workspace_env
    target_rel = "logs/counter.txt"
    target_abs = ws_path / "logs" / "counter.txt"
    target_abs.parent.mkdir(parents=True, exist_ok=True)

    # Perform 13 consecutive mutations
    for i in range(13):
        content = f"count = {i}\n"
        cp = tx_manager.create_text_checkpoint(target_rel, content)
        tx_manager.apply_checkpoint(cp, content_override=content)

    # Active checkpoints must be capped at 10
    assert len(tx_manager.workspace.active_checkpoints) == 10

    # 3 checkpoints must be archived as .gz files
    archives = list((ws_path / ".brain" / "archives").glob("*.json.gz"))
    assert len(archives) == 3
