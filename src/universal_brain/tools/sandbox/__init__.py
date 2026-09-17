"""Universal Brain - Workspace Sandbox Subsystem."""

from .confinement import PathScopeViolationError, confine_path
from .file_tools import FileDeleteTool, FilePatchTool, FileReadTool, FileWriteTool
from .manifests import ManifestEngine, hash_file, hash_file_bytes
from .patching import TextPatchReversibilityEngine
from .restore import ContentAddressedBlobStore
from .schemas import (
    ManifestItem,
    MutationType,
    StateManifest,
    Workspace,
    WorkspaceCheckpoint,
    WorkspaceStatus,
)
from .workspace import (
    RollbackExecutionError,
    SlidingWindowPruner,
    StaleCheckpointError,
    WorkspaceTransactionManager,
)

__all__ = [
    "PathScopeViolationError",
    "confine_path",
    "ManifestEngine",
    "hash_file",
    "hash_file_bytes",
    "TextPatchReversibilityEngine",
    "ContentAddressedBlobStore",
    "WorkspaceStatus",
    "MutationType",
    "ManifestItem",
    "StateManifest",
    "WorkspaceCheckpoint",
    "Workspace",
    "WorkspaceTransactionManager",
    "SlidingWindowPruner",
    "StaleCheckpointError",
    "RollbackExecutionError",
    "FileReadTool",
    "FileWriteTool",
    "FilePatchTool",
    "FileDeleteTool",
]
