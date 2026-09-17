"""
Universal Brain - Local Ollama / Open-Weights Provider Adapter
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from universal_brain.executive.eap import ExecutiveAwarenessPackage
from universal_brain.executive.providers.base import (
    BaseModelProvider,
    ProviderMetadata,
)
from universal_brain.executive.schemas import ExecutiveModelResponse


class LocalOllamaProvider(BaseModelProvider):
    """Adapter for local, offline Ollama models (e.g. Llama-3, DeepSeek-R1)."""

    def __init__(
        self,
        model_id: str = "llama3:8b",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.base_url = base_url
        metadata = ProviderMetadata(
            provider_id="ollama-local",
            model_id=model_id,
            model_family="open_weights",
            context_window=32000,
            cost_per_million_input=0.00,  # Zero API cost
            cost_per_million_output=0.00,
            supports_structured_outputs=True,
            supports_tools=True,
            latency_class="fast",
        )
        super().__init__(metadata)

    async def generate_response(
        self,
        eap: ExecutiveAwarenessPackage,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ExecutiveModelResponse:
        return ExecutiveModelResponse(
            response_id=uuid4(),
            task_id=eap.identity.task_id,
            lease_id=eap.identity.lease_id,
            observations=[f"Local Ollama model '{self.metadata.model_id}' operating offline without egress."],
            proposed_decisions=[],
            requested_tool_calls=[],
            provider_metadata={"provider": "ollama-local", "model": self.metadata.model_id},
        )
