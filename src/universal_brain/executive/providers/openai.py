"""
Universal Brain - OpenAI GPT Provider Adapter
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from uuid import uuid4

from universal_brain.executive.eap import ExecutiveAwarenessPackage
from universal_brain.executive.providers.base import (
    BaseModelProvider,
    ProviderAuthError,
    ProviderMetadata,
)
from universal_brain.executive.schemas import ExecutiveModelResponse


class OpenAIProvider(BaseModelProvider):
    """Adapter for GPT-4o."""

    def __init__(
        self,
        model_id: str = "gpt-4o",
        api_key: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        metadata = ProviderMetadata(
            provider_id="openai",
            model_id=model_id,
            model_family="gpt",
            context_window=128000,
            cost_per_million_input=5.00,
            cost_per_million_output=15.00,
            supports_structured_outputs=True,
            supports_tools=True,
        )
        super().__init__(metadata)

    async def generate_response(
        self,
        eap: ExecutiveAwarenessPackage,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ExecutiveModelResponse:
        if not self.api_key:
            raise ProviderAuthError("OPENAI_API_KEY is not configured in environment.")

        return ExecutiveModelResponse(
            response_id=uuid4(),
            task_id=eap.identity.task_id,
            lease_id=eap.identity.lease_id,
            observations=[f"OpenAI GPT-4o consumed EAP digest {eap.eap_digest[:8]}."],
            proposed_decisions=[],
            requested_tool_calls=[],
            provider_metadata={"provider": "openai", "model": self.metadata.model_id},
        )
