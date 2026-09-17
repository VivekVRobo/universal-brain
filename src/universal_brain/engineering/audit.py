"""Causal audit bridge for engineering cognition.

Traceability: REQ-ENG-016, ALN-016, ALN-021. Only cryptographic digests and
routing metadata are committed to the canonical EventStore. Raw prompts/responses
remain outside the governance ledger.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from universal_brain.intelligence.schemas import ModelRequest, NormalizedModelResult
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventEnvelope, EventType


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class EngineeringCausalAuditor:
    """Hash-link model cognition to later ToolGateway evidence without raw content."""

    def __init__(self, store: EventStore, *, actor_id: str = "engineering_cognition") -> None:
        self.store = store
        self.actor_id = actor_id

    @staticmethod
    def request_digest(request: ModelRequest) -> str:
        body = {
            "messages": [message.model_dump(mode="json") for message in request.messages],
            "tools": request.tools,
            "response_schema": request.response_schema,
            "max_output_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "metadata": request.metadata,
        }
        return _stable_digest(body)

    @staticmethod
    def response_digest(result: NormalizedModelResult) -> str:
        body = {
            "output_text": result.output_text,
            "structured_output": result.structured_output,
            "tool_calls": [call.model_dump(mode="json") for call in result.tool_calls],
            "artifacts": result.artifacts,
            "citations": result.citations,
        }
        return _stable_digest(body)

    def record_request(
        self,
        request: ModelRequest,
        *,
        project_id: UUID,
        node_id: str,
        caused_by_event_id: UUID | None = None,
    ) -> EventEnvelope:
        return self.store.append_event(
            event_type=EventType.MODEL_REQUESTED,
            actor_id=self.actor_id,
            project_id=project_id,
            payload={
                "node_id": node_id,
                "request_id": str(request.request_id),
                "request_sha256": self.request_digest(request),
                "message_count": len(request.messages),
                "tool_schema_count": len(request.tools),
                "raw_content_stored": False,
            },
            caused_by_event_id=caused_by_event_id,
        )

    def record_response(
        self,
        result: NormalizedModelResult,
        *,
        project_id: UUID,
        node_id: str,
        caused_by_event_id: UUID | None = None,
    ) -> EventEnvelope:
        tool_digest = _stable_digest([call.model_dump(mode="json") for call in result.tool_calls])
        return self.store.append_event(
            event_type=EventType.MODEL_RESPONSE,
            actor_id=self.actor_id,
            project_id=project_id,
            payload={
                "node_id": node_id,
                "request_id": str(result.request_id),
                "result_id": str(result.result_id),
                "model_key": result.model_key,
                "route_id": result.route_id,
                "response_sha256": self.response_digest(result),
                "tool_calls_sha256": tool_digest,
                "tool_call_count": len(result.tool_calls),
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "raw_content_stored": False,
            },
            caused_by_event_id=caused_by_event_id,
        )
