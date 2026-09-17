"""
Universal Brain - Hermetic Deterministic Mock Provider

Enables reliable, zero-cost, hermetic testing of:
- EAP consumption;
- Provider error handling and circuit breaking;
- Cognitive handoff triggers (context overflow, rate limit, outage);
- Adversarial model failure modes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from universal_brain.executive.eap import ExecutiveAwarenessPackage
from universal_brain.executive.providers.base import (
    BaseModelProvider,
    ProviderContextLimitError,
    ProviderMetadata,
    ProviderOutageError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from universal_brain.executive.schemas import ExecutiveModelResponse


class MockModelProvider(BaseModelProvider):
    """Deterministic, configurable mock provider for hermetic testing."""

    def __init__(
        self,
        provider_id: str = "mock-anthropic",
        model_id: str = "claude-3-5-sonnet",
        metadata: Optional[ProviderMetadata] = None,
    ) -> None:
        meta = metadata or ProviderMetadata(
            provider_id=provider_id,
            model_id=model_id,
            model_family="claude",
            context_window=200000,
            cost_per_million_input=3.00,
            cost_per_million_output=15.00,
        )
        super().__init__(meta)

        # Injected failure flags
        self.inject_rate_limit: bool = False
        self.inject_timeout: bool = False
        self.inject_outage: bool = False
        self.inject_context_limit: bool = False
        self.recommend_handoff: bool = False
        self.claim_completion: bool = False
        self.tool_call_to_request: Optional[Dict[str, Any]] = None

    async def generate_response(
        self,
        eap: ExecutiveAwarenessPackage,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ExecutiveModelResponse:
        """Emulates provider execution with configurable failure modes."""
        if self.inject_outage:
            raise ProviderOutageError(f"Provider '{self.metadata.provider_id}' is experiencing an outage (500).")
        if self.inject_rate_limit:
            raise ProviderRateLimitError(f"Provider '{self.metadata.provider_id}' rate limit exceeded.", retry_after_seconds=30)
        if self.inject_timeout:
            raise ProviderTimeoutError(f"Provider '{self.metadata.provider_id}' call timed out after 30s.")
        if self.inject_context_limit:
            raise ProviderContextLimitError("Context window exceeded maximum tokens.")

        # Construct deterministic response reflecting EAP state
        tool_calls = []
        if self.tool_call_to_request:
            tool_calls.append(self.tool_call_to_request)
        elif eap.task.active_node:
            tool_name = eap.resources.available_tools[0] if eap.resources.available_tools else "read_file"
            tool_calls.append({
                "tool_name": tool_name,
                "arguments": {"target": "./src/robot_controller.cpp", "diff": "+ // PID implementation"},
            })

        return ExecutiveModelResponse(
            response_id=uuid4(),
            task_id=eap.identity.task_id,
            lease_id=eap.identity.lease_id,
            observations=[
                f"Consuming canonical EAP (digest: {eap.eap_digest[:12]}).",
                f"Active goal: {eap.task.goal}.",
                f"Contract requirements count: {len(eap.governance.requirements)}.",
            ],
            proposed_decisions=[{"decision": "Proceed with ROS 2 node generation"}],
            requested_tool_calls=tool_calls,
            handoff_recommended=self.recommend_handoff,
            completion_candidate=self.claim_completion,
            provider_metadata={"mock": True, "model": self.metadata.model_id},
        )
