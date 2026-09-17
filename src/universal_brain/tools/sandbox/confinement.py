"""
Universal Brain - Workspace Root Confinement

Implements M5 Section 9 and Invariant M5-INV-02:
Enforces strict canonical path containment within the workspace root.
Protects against traversal attacks (../), symlink escapes, Windows junctions,
UNC shares, and cross-drive escapes.
"""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Union

from universal_brain.kernel.errors import UniversalBrainError


class PathScopeViolationError(UniversalBrainError):
    """Raised when an operation attempts to access paths outside the authorized workspace."""

    def __init__(self, target_path: str, workspace_root: str, reason: str = "Path escapes workspace root") -> None:
        super().__init__(f"PATH_SCOPE_VIOLATION: Target '{target_path}' outside '{workspace_root}': {reason}")
        self.target_path = target_path
        self.workspace_root = workspace_root


def confine_path(target_path: Union[str, Path], workspace_root: Union[str, Path]) -> Path:
    """
    Canonically resolves and verifies target_path is confined strictly inside workspace_root.
    
    1. Rejects UNC paths (\\\\server\\share).
    2. Resolves absolute realpaths (evaluating symlinks and junctions).
    3. Normalizes path casing on Windows.
    4. Asserts resolved target is relative to / a descendant of workspace_root.
    5. Returns the canonical Path object.
    """
    target_str = str(target_path).strip()
    
    # 1. Reject UNC paths
    if target_str.startswith("\\\\") or target_str.startswith("//"):
        raise PathScopeViolationError(target_str, str(workspace_root), "UNC paths are prohibited")
    windows_view = PureWindowsPath(target_str)
    if os.name != "nt" and (windows_view.is_absolute() or bool(windows_view.drive)):
        raise PathScopeViolationError(
            target_str,
            str(workspace_root),
            "Foreign Windows absolute/cross-drive path is prohibited",
        )

    # 2. Canonicalize Root
    root_resolved = Path(os.path.realpath(workspace_root)).resolve()
    root_norm = os.path.normcase(str(root_resolved))

    # 3. Canonicalize Target
    if os.path.isabs(target_str):
        candidate = Path(os.path.realpath(target_str)).resolve()
    else:
        # Join relative to root before resolving
        joined = os.path.join(str(root_resolved), target_str)
        candidate = Path(os.path.realpath(joined)).resolve()

    candidate_norm = os.path.normcase(str(candidate))

    # 4. Check ancestry / containment
    # Candidate must equal root or start with root + separator
    if candidate_norm == root_norm:
        return candidate

    root_norm_with_sep = root_norm if root_norm.endswith(os.sep) else root_norm + os.sep
    if not candidate_norm.startswith(root_norm_with_sep):
        raise PathScopeViolationError(target_str, str(root_resolved), "Resolved path is outside workspace root")

    return candidate
