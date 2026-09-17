from __future__ import annotations

import json
import os

import httpx

from ..schemas import (
    AccessRoute,
    AuthMode,
    ModelDescriptor,
    ModelRequest,
    ModelUsage,
    NormalizedModelResult,
    TransportKind,
)
from ..tool_calls import ToolCallNormalizer
from .base import (
    BaseModelTransport,
    TransportAuthError,
    TransportOutageError,
    TransportRateLimitError,
    TransportTimeoutError,
)


class OpenAICompatibleTransport(BaseModelTransport):
    PROTOCOLS = {"openai-responses", "openai-compatible-chat-completions"}

    def __init__(self, timeout_seconds: int = 90):
        self.timeout_seconds = timeout_seconds

    def supports(self, route: AccessRoute) -> bool:
        return (
            route.transport in {TransportKind.API, TransportKind.LOCAL}
            and bool(route.config.get("base_url"))
            and str(
                route.config.get("protocol", "openai-compatible-chat-completions")
            )
            in self.PROTOCOLS
        )

    @staticmethod
    def _credential(route: AccessRoute) -> str | None:
        env_name = route.config.get("api_key_env")
        return os.getenv(str(env_name)) if env_name else None

    @staticmethod
    def _raise_for_response(response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise TransportAuthError(f"authentication failed ({response.status_code})")
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            raise TransportRateLimitError(
                "rate limit exceeded",
                int(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if response.status_code >= 500:
            raise TransportOutageError(f"upstream {response.status_code}")
        if response.status_code >= 400:
            raise TransportOutageError(
                f"HTTP {response.status_code}: {response.text[:300]}"
            )

    @staticmethod
    def _structured_from_text(text: str) -> dict | None:
        stripped = text.strip()
        if not stripped.startswith("{"):
            return None
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    async def invoke(
        self,
        model: ModelDescriptor,
        route: AccessRoute,
        request: ModelRequest,
    ) -> NormalizedModelResult:
        base_url = str(route.config.get("base_url", "")).rstrip("/")
        credential = self._credential(route)
        if route.auth_mode == AuthMode.API_KEY and not credential:
            raise TransportAuthError(
                f"credential env '{route.config.get('api_key_env', '<unset>')}' missing"
            )

        headers = {"content-type": "application/json"}
        if credential:
            headers["authorization"] = f"Bearer {credential}"

        protocol = str(
            route.config.get("protocol", "openai-compatible-chat-completions")
        )
        if protocol == "openai-responses":
            body: dict = {
                "model": model.model_id,
                "input": [message.model_dump(mode="json") for message in request.messages],
            }
            if request.metadata.get("conversation_ref"):
                body["previous_response_id"] = str(request.metadata["conversation_ref"])
            if request.max_output_tokens:
                body["max_output_tokens"] = request.max_output_tokens
            if request.tools and route.supports_tools:
                body["tools"] = request.tools
            if request.response_schema and route.supports_structured_outputs:
                body["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": "universal_brain_response",
                        "schema": request.response_schema,
                        "strict": True,
                    }
                }
            path = "/responses"
        else:
            body = {
                "model": model.model_id,
                "messages": [
                    message.model_dump(mode="json") for message in request.messages
                ],
            }
            if request.max_output_tokens:
                body["max_tokens"] = request.max_output_tokens
            if request.tools and route.supports_tools:
                body["tools"] = request.tools
            if request.response_schema and route.supports_structured_outputs:
                body["response_format"] = {"type": "json_object"}
            path = "/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(base_url + path, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise TransportTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise TransportOutageError(str(exc)) from exc

        self._raise_for_response(response)
        data = response.json()

        if protocol == "openai-responses":
            text = str(data.get("output_text") or "")
            output_items = data.get("output") or []
            if not text:
                fragments: list[str] = []
                for item in output_items:
                    for part in item.get("content") or []:
                        if part.get("text"):
                            fragments.append(str(part["text"]))
                text = "".join(fragments)
            tool_calls = ToolCallNormalizer.openai_responses(output_items)
            usage = data.get("usage") or {}
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            conversation_ref = str(data.get("id")) if data.get("id") else None
        else:
            choices = data.get("choices") or []
            message = (choices[0].get("message") if choices else {}) or {}
            content = message.get("content")
            if isinstance(content, list):
                text = "".join(
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict)
                )
            else:
                text = str(content or "")
            tool_calls = ToolCallNormalizer.openai_chat(message.get("tool_calls") or [])
            usage = data.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens") or 0)
            output_tokens = int(usage.get("completion_tokens") or 0)
            conversation_ref = None

        cost = (
            input_tokens / 1_000_000 * route.cost_per_million_input
            + output_tokens / 1_000_000 * route.cost_per_million_output
        )
        return NormalizedModelResult(
            request_id=request.request_id,
            model_key=model.model_key,
            route_id=route.route_id,
            output_text=text,
            structured_output=self._structured_from_text(text),
            tool_calls=tool_calls,
            usage=ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 8),
            ),
            provider_request_id=data.get("id"),
            conversation_ref=conversation_ref,
            raw_metadata={"protocol": protocol},
        )
