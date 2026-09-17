"""
Universal Brain - Google Gemini Provider Adapter
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


class GeminiProvider(BaseModelProvider):
    """Adapter for Gemini 1.5 Pro / Flash."""

    def __init__(
        self,
        model_id: str = "gemini-1.5-pro",
        api_key: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        metadata = ProviderMetadata(
            provider_id="gemini",
            model_id=model_id,
            model_family="gemini",
            context_window=1000000,
            cost_per_million_input=1.25,
            cost_per_million_output=5.00,
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
            raise ProviderAuthError("GEMINI_API_KEY is not configured in environment.")

        return ExecutiveModelResponse(
            response_id=uuid4(),
            task_id=eap.identity.task_id,
            lease_id=eap.identity.lease_id,
            observations=[f"Gemini processed EAP digest {eap.eap_digest[:8]}."],
            proposed_decisions=[],
            requested_tool_calls=[],
            provider_metadata={"provider": "gemini", "model": self.metadata.model_id},
        )
