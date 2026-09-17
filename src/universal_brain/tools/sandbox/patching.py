"""
Universal Brain - Text Patch Preflight & Reversibility Engine

Implements M5 Section 15 and ADR-0008:
Simulates forward and reverse diff application in memory.
Only certifies mutations as VERIFIED_REVERSIBLE if the reverse diff
dry-run mathematically restores the exact pre-state SHA-256 byte-for-byte.
"""

from __future__ import annotations

import difflib
import hashlib
from typing import Optional, Tuple

from universal_brain.kernel.errors import RollbackPreflightError
from universal_brain.tools.base import ReversibilityClass


class TextPatchReversibilityEngine:
    """Computes, simulates, and validates unified diffs and their mathematical inverses."""

    @classmethod
    def compute_diff(cls, original_text: str, new_text: str, filename: str = "file") -> str:
        """Generates unified forward diff."""
        orig_norm = original_text if (original_text.endswith("\n") or not original_text) else original_text + "\n"
        new_norm = new_text if (new_text.endswith("\n") or not new_text) else new_text + "\n"

        orig_lines = orig_norm.splitlines(keepends=True)
        new_lines = new_norm.splitlines(keepends=True)
        diff_lines = list(difflib.unified_diff(
            orig_lines,
            new_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        ))
        return "".join(diff_lines)

    @classmethod
    def compute_reverse_diff(cls, original_text: str, new_text: str, filename: str = "file") -> str:
        """Generates unified reverse diff (restoring original from new)."""
        return cls.compute_diff(new_text, original_text, filename)

    @classmethod
    def apply_diff(cls, base_text: str, patch_text: str) -> Optional[str]:
        """
        Applies a unified diff to base_text.
        Returns modified string on success, or None if patch fails to apply.
        """
        if not patch_text:
            return base_text

        base_norm = base_text if (base_text.endswith("\n") or not base_text) else base_text + "\n"
        base_lines = base_norm.splitlines(keepends=True)
        patch_lines = patch_text.splitlines(keepends=True)

        # Parse hunks from unified diff
        result_lines = []
        base_idx = 0

        i = 0
        while i < len(patch_lines):
            line = patch_lines[i]
            if line.startswith("---") or line.startswith("+++"):
                i += 1
                continue

            if line.startswith("@@"):
                # Parse hunk header: @@ -start,len +start,len @@
                parts = line.split("@@")
                if len(parts) < 3:
                    return None
                header = parts[1].strip()
                # Parse range: -1,3 +1,4
                try:
                    ranges = header.split(" ")
                    orig_range = ranges[0][1:]  # strip '-'
                    orig_start = int(orig_range.split(",")[0]) - 1
                except Exception:
                    return None

                # Advance base_lines up to orig_start
                while base_idx < orig_start and base_idx < len(base_lines):
                    result_lines.append(base_lines[base_idx])
                    base_idx += 1

                i += 1
                while i < len(patch_lines) and not patch_lines[i].startswith("@@"):
                    p_line = patch_lines[i]
                    if p_line.startswith(" "):
                        # Context line: must match base
                        expected = p_line[1:]
                        if base_idx < len(base_lines) and base_lines[base_idx] == expected:
                            result_lines.append(expected)
                            base_idx += 1
                        else:
                            return None  # Context mismatch
                    elif p_line.startswith("+"):
                        # Added line
                        result_lines.append(p_line[1:])
                    elif p_line.startswith("-"):
                        # Removed line: must match base
                        expected = p_line[1:]
                        if base_idx < len(base_lines) and base_lines[base_idx] == expected:
                            base_idx += 1
                        else:
                            return None  # Context mismatch
                    elif p_line.startswith("\\"):
                        # Comment e.g. \ No newline at end of file
                        pass
                    i += 1
                continue

            i += 1

        # Append remaining base lines
        while base_idx < len(base_lines):
            result_lines.append(base_lines[base_idx])
            base_idx += 1

        return "".join(result_lines)

    @classmethod
    def preflight_verify(
        cls,
        original_text: str,
        new_text: str,
        filename: str = "file",
    ) -> Tuple[ReversibilityClass, str, str, str]:
        """
        Performs full mathematical preflight verification:
        1. Generates forward diff and reverse diff.
        2. Applies forward diff to original -> simulated post-state.
        3. Applies reverse diff to simulated post-state -> simulated restored state.
        4. Verifies restored SHA-256 == original SHA-256.
        5. Returns (reversibility_class, forward_diff, reverse_diff, post_sha256).
        """
        orig_has_nl = original_text.endswith("\n") or not original_text
        new_has_nl = new_text.endswith("\n") or not new_text

        orig_sha = hashlib.sha256(original_text.encode("utf-8")).hexdigest()
        forward_diff = cls.compute_diff(original_text, new_text, filename)
        reverse_diff = cls.compute_reverse_diff(original_text, new_text, filename)

        # 1. Simulate forward apply
        sim_norm = cls.apply_diff(original_text, forward_diff)
        if sim_norm is None:
            raise RollbackPreflightError(f"Forward patch simulation failed for '{filename}'.")
        simulated_post = sim_norm if new_has_nl else sim_norm.rstrip("\r\n")
        if simulated_post != new_text:
            raise RollbackPreflightError(
                f"Forward patch simulation mismatch for '{filename}'."
            )

        post_sha = hashlib.sha256(simulated_post.encode("utf-8")).hexdigest()

        # 2. Simulate reverse apply (dry-run)
        sim_rest_norm = cls.apply_diff(simulated_post, reverse_diff)
        if sim_rest_norm is None:
            raise RollbackPreflightError(
                f"Reverse patch dry-run failed: could not invert patch for '{filename}'."
            )
        simulated_restored = sim_rest_norm if orig_has_nl else sim_rest_norm.rstrip("\r\n")

        restored_sha = hashlib.sha256(simulated_restored.encode("utf-8")).hexdigest()

        # 3. Assert cryptographic parity
        if restored_sha != orig_sha:
            raise RollbackPreflightError(
                f"Preflight reversibility mismatch for '{filename}': "
                f"Restored SHA ({restored_sha}) does not match original SHA ({orig_sha})."
            )

        return ReversibilityClass.VERIFIED_REVERSIBLE, forward_diff, reverse_diff, post_sha
