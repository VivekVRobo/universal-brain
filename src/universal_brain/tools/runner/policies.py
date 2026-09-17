"""
Universal Brain - Command Execution Policies & Environment Sanitizer

Implements M5 Sections 25, 26, 32 and Invariant M5-INV-06:
Sanitizes environment variables to prevent secret leakage (API keys, HMAC keys, DB passwords).
Registers standard executable profiles with safe parameter rules.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Set

from universal_brain.kernel.errors import UniversalBrainError


class ExecutionPolicyError(UniversalBrainError):
    """Raised when a command violates execution safety policies."""
    pass


class EnvironmentSanitizer:
    """Strips credentials, API keys, and internal secrets from subprocess environments."""

    # Standard safe keys needed for process bootstrapping
    SAFE_KEY_ALLOWLIST: Set[str] = {
        "PATH",
        "SYSTEMROOT",
        "COMSPEC",
        "TEMP",
        "TMP",
        "PYTHONPATH",
        "PYTHONHOME",
        "WINDIR",
        "APPDATA",
        "LOCALAPPDATA",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "OS",
        "PROCESSOR_ARCHITECTURE",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
    }

    # Patterns matching secrets to strip aggressively
    SECRET_KEY_PATTERNS: List[re.Pattern] = [
        re.compile(r".*(KEY|SECRET|TOKEN|PASSWORD|PASSWD|AUTH|CREDENTIAL|DATABASE_URL).*", re.IGNORECASE),
        re.compile(r"^(OPENAI|ANTHROPIC|GEMINI|AWS|GCP|AZURE|TELEGRAM|HMAC).*", re.IGNORECASE),
    ]

    @classmethod
    def sanitize_environment(
        cls,
        base_env: Optional[Dict[str, str]] = None,
        overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """
        Creates clean, sanitized environment for child process.
        Strips all secrets and internal sensitive variables.
        """
        source = base_env if base_env is not None else dict(os.environ)
        sanitized: Dict[str, str] = {}

        for k, v in source.items():
            k_upper = k.upper()

            # 1. Check if explicitly in safe allowlist
            if k_upper in cls.SAFE_KEY_ALLOWLIST:
                # Still verify value doesn't match a secret pattern
                is_secret = any(p.match(k_upper) for p in cls.SECRET_KEY_PATTERNS)
                if not is_secret:
                    sanitized[k] = v
                continue

            # 2. Reject any key matching secret pattern
            if any(p.match(k_upper) for p in cls.SECRET_KEY_PATTERNS):
                continue

            # Default: omit unknown arbitrary host variables
            # Unless explicitly safe prefix (e.g. PYTHON)
            if k_upper.startswith("PYTHON") or k_upper.startswith("ROS_"):
                sanitized[k] = v

        # Apply explicitly authorized safe overrides
        if overrides:
            for ok, ov in overrides.items():
                sanitized[ok] = ov

        return sanitized


class ExecutableRegistry:
    """Registry of verified executables with policy constraints (M5 Section 26)."""

    ALLOWED_EXECUTABLES: Set[str] = {
        "python",
        "python.exe",
        "pytest",
        "git",
        "git.exe",
        "colcon",
        "colcon.exe",
        "node",
        "node.exe",
        "npm",
        "npm.cmd",
        "cargo",
        "cargo.exe",
    }

    @classmethod
    def validate_executable(cls, executable: str) -> None:
        """Validates that executable is within permitted registry."""
        exe_clean = os.path.basename(executable).lower()
        if exe_clean not in cls.ALLOWED_EXECUTABLES:
            raise ExecutionPolicyError(
                f"Executable '{executable}' is not in the allowed executable registry. "
                f"Allowed: {sorted(cls.ALLOWED_EXECUTABLES)}"
            )
