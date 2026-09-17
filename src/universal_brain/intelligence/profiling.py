from __future__ import annotations

import re
from typing import Iterable

from pydantic import BaseModel, Field

from universal_brain.kernel.events import ActionClass

from .schemas import (
    ModelCapability,
    ModelRequest,
    SensitivityLevel,
    TaskComplexity,
    TaskProfile,
)


class TaskAnalysis(BaseModel):
    profile: TaskProfile
    complexity_score: float = Field(ge=0, le=1)
    signals: list[str] = Field(default_factory=list)


class DeterministicTaskProfiler:
    """Deterministic task profiler used before model routing.

    This profiler never grants authority and never infers permission expansion. It
    only derives routing hints from request shape and explicit metadata.
    """

    CODE_TERMS = {
        "code",
        "coding",
        "debug",
        "bug",
        "refactor",
        "repository",
        "repo",
        "pytest",
        "typescript",
        "python",
        "rust",
        "java",
        "ros2",
        "compile",
        "implementation",
    }
    ARCH_TERMS = {
        "architecture",
        "architect",
        "system design",
        "distributed",
        "runtime",
        "orchestrator",
        "framework",
        "protocol",
        "migration",
    }
    RESEARCH_TERMS = {
        "research",
        "compare",
        "survey",
        "sources",
        "evidence",
        "literature",
        "benchmark",
        "fact check",
    }
    VERIFY_TERMS = {
        "verify",
        "verification",
        "test",
        "tests",
        "validate",
        "audit",
        "review",
        "prove",
        "evidence",
    }
    TOOL_TERMS = {
        "run",
        "execute",
        "terminal",
        "shell",
        "browser",
        "file",
        "git",
        "github",
        "deploy",
    }
    VISION_TERMS = {"image", "screenshot", "photo", "vision", "diagram", "video", "visual"}

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        words = set(re.findall(r"[a-zA-Z0-9_+#.-]+", text.lower()))
        return words

    @staticmethod
    def _contains_any(text: str, words: Iterable[str]) -> bool:
        lower = text.lower()
        return any(term in lower for term in words)

    @staticmethod
    def _parse_action_class(value: object, fallback: ActionClass) -> ActionClass:
        if value is None:
            return fallback
        try:
            return value if isinstance(value, ActionClass) else ActionClass(str(value))
        except ValueError:
            return fallback

    @staticmethod
    def _parse_sensitivity(value: object, fallback: SensitivityLevel) -> SensitivityLevel:
        if value is None:
            return fallback
        try:
            return value if isinstance(value, SensitivityLevel) else SensitivityLevel(str(value))
        except ValueError:
            return fallback

    def profile(self, request: ModelRequest, base: TaskProfile | None = None) -> TaskAnalysis:
        base = base or TaskProfile()
        explicit_profile_text = request.metadata.get("profile_text")
        if explicit_profile_text is not None:
            text = str(explicit_profile_text)
        else:
            # System/role boilerplate can contain words such as "tool", "evidence",
            # or "verify" that describe governance rather than the user task. Do not
            # let those instructions distort capability discovery/routing.
            text = "\n".join(
                message.content
                for message in request.messages
                if message.role.lower() != "system"
            )
        lower = text.lower()
        tokens = self._tokenize(text)
        signals: list[str] = []
        capabilities = set(base.required_capabilities)
        weights = dict(base.capability_weights)
        minimums = dict(base.minimum_capability_scores)

        if self._contains_any(lower, self.CODE_TERMS) or "```" in text:
            capabilities.add(ModelCapability.CODING)
            weights.setdefault(ModelCapability.CODING, 1.2)
            signals.append("coding")
        if self._contains_any(lower, self.ARCH_TERMS):
            capabilities.update({ModelCapability.REASONING, ModelCapability.ARCHITECTURE})
            weights.setdefault(ModelCapability.ARCHITECTURE, 1.3)
            signals.append("architecture")
        if self._contains_any(lower, self.RESEARCH_TERMS):
            capabilities.update({ModelCapability.REASONING, ModelCapability.RESEARCH})
            weights.setdefault(ModelCapability.RESEARCH, 1.1)
            signals.append("research")
        if self._contains_any(lower, self.VERIFY_TERMS):
            capabilities.add(ModelCapability.VERIFICATION)
            weights.setdefault(ModelCapability.VERIFICATION, 1.1)
            signals.append("verification")
        if self._contains_any(lower, self.TOOL_TERMS) or request.tools:
            capabilities.add(ModelCapability.TOOL_USE)
            signals.append("tool_use")
        if self._contains_any(lower, self.VISION_TERMS) or request.metadata.get("has_images"):
            capabilities.add(ModelCapability.VISION)
            signals.append("vision")
        if request.response_schema:
            capabilities.add(ModelCapability.STRUCTURED_OUTPUT)
            signals.append("structured_output")

        explicit_context = int(request.metadata.get("context_tokens", 0) or 0)
        estimated_prompt_tokens = max(1, len(text) // 4)
        required_context = max(base.required_context_tokens, explicit_context + estimated_prompt_tokens)
        if required_context >= 100_000:
            capabilities.add(ModelCapability.LONG_CONTEXT)
            signals.append("long_context")

        # Complexity is intentionally conservative and deterministic.
        score = 0.18
        score += min(len(text) / 80_000, 0.22)
        score += min(len(capabilities) * 0.055, 0.22)
        score += 0.12 if "architecture" in signals else 0
        score += 0.10 if "verification" in signals else 0
        score += 0.08 if required_context >= 100_000 else 0
        score += 0.08 if request.tools else 0
        score += min(len(tokens) / 4_000, 0.08)
        score = min(score, 1.0)

        if score < 0.28:
            complexity = TaskComplexity.TRIVIAL
            min_floor = 0.45
        elif score < 0.53:
            complexity = TaskComplexity.STANDARD
            min_floor = 0.58
        elif score < 0.77:
            complexity = TaskComplexity.COMPLEX
            min_floor = 0.72
        else:
            complexity = TaskComplexity.FRONTIER
            min_floor = 0.86

        for capability in capabilities:
            minimums.setdefault(capability, min_floor)

        sensitivity = self._parse_sensitivity(request.metadata.get("sensitivity"), base.sensitivity)
        action_class = self._parse_action_class(request.metadata.get("action_class"), base.action_class)
        local_only = base.local_only or sensitivity == SensitivityLevel.SECRET

        metadata = dict(base.metadata)
        metadata["profiler"] = {
            "complexity_score": round(score, 6),
            "signals": sorted(set(signals)),
            "deterministic": True,
        }

        profile = base.model_copy(
            update={
                "task_id": base.task_id or request.task_id,
                "task_kind": str(request.metadata.get("task_kind") or base.task_kind),
                "complexity": complexity,
                "required_context_tokens": required_context,
                "estimated_output_tokens": request.max_output_tokens
                or base.estimated_output_tokens,
                "required_capabilities": capabilities,
                "capability_weights": weights,
                "minimum_capability_scores": minimums,
                "sensitivity": sensitivity,
                "action_class": action_class,
                "require_structured_output": base.require_structured_output
                or bool(request.response_schema),
                "require_tools": base.require_tools or bool(request.tools),
                "require_vision": base.require_vision or "vision" in signals,
                "local_only": local_only,
                "metadata": metadata,
            }
        )
        return TaskAnalysis(profile=profile, complexity_score=round(score, 6), signals=signals)
