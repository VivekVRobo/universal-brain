from __future__ import annotations

import json
from typing import Any, Iterable

from .schemas import NormalizedToolCall


class ToolCallNormalizer:
    """Normalize provider-specific tool/function call payloads.

    Unknown shapes are ignored instead of becoming executable authority. Invalid
    argument JSON is preserved as a plain value under ``value`` for inspection.
    """

    @staticmethod
    def coerce_arguments(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return {}
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return {"value": value}
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        return {"value": value}

    @classmethod
    def openai_responses(cls, items: Iterable[dict[str, Any]]) -> list[NormalizedToolCall]:
        calls: list[NormalizedToolCall] = []
        for item in items or ():
            if item.get("type") not in {"function_call", "tool_call"}:
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            calls.append(
                NormalizedToolCall(
                    tool_name=name,
                    arguments=cls.coerce_arguments(item.get("arguments")),
                    call_id=item.get("call_id") or item.get("id"),
                )
            )
        return calls

    @classmethod
    def openai_chat(cls, calls_payload: Iterable[dict[str, Any]]) -> list[NormalizedToolCall]:
        calls: list[NormalizedToolCall] = []
        for call in calls_payload or ():
            function = call.get("function") or {}
            name = str(function.get("name") or call.get("name") or "").strip()
            if not name:
                continue
            calls.append(
                NormalizedToolCall(
                    tool_name=name,
                    arguments=cls.coerce_arguments(
                        function.get("arguments", call.get("arguments"))
                    ),
                    call_id=call.get("id") or call.get("call_id"),
                )
            )
        return calls

    @classmethod
    def anthropic(cls, content: Iterable[dict[str, Any]]) -> list[NormalizedToolCall]:
        calls: list[NormalizedToolCall] = []
        for block in content or ():
            if block.get("type") != "tool_use":
                continue
            name = str(block.get("name") or "").strip()
            if not name:
                continue
            calls.append(
                NormalizedToolCall(
                    tool_name=name,
                    arguments=cls.coerce_arguments(block.get("input")),
                    call_id=block.get("id"),
                )
            )
        return calls

    @classmethod
    def gemini(cls, candidates: Iterable[dict[str, Any]]) -> list[NormalizedToolCall]:
        calls: list[NormalizedToolCall] = []
        for candidate in candidates or ():
            content = candidate.get("content") or {}
            for part in content.get("parts") or ():
                function_call = part.get("functionCall") or part.get("function_call")
                if not isinstance(function_call, dict):
                    continue
                name = str(function_call.get("name") or "").strip()
                if not name:
                    continue
                calls.append(
                    NormalizedToolCall(
                        tool_name=name,
                        arguments=cls.coerce_arguments(function_call.get("args")),
                        call_id=function_call.get("id"),
                    )
                )
        return calls
