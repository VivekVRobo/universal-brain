"""
Universal Brain - Base Model Provider Abstraction

Implements Section 9 of the God-Level Specification:
- Strict provider interface contract;
- Provider metadata and capabilities;
- Standardized provider error taxonomy;
- Rule: Provider-specific behavior must never leak into the planner.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from universal_brain.executive.eap import ExecutiveAwarenessPackage
from universal_brain.executive.schemas import ExecutiveModelResponse


# -----------------------------------------------------------------------------
# 1. Error Taxonomy
# -----------------------------------------------------------------------------


class ProviderError(Exception):
    """Base error for all model provider failures."""
    pass


class ProviderAuthError(ProviderError):
    """Authentication or credential failure."""
    pass


class ProviderRateLimitError(ProviderError):
    """Provider rate limit or quota exceeded."""
    def __init__(self, message: str, retry_after_seconds: Optional[int] = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderTimeoutError(ProviderError):
    """Provider request timed out."""
    pass


class ProviderContextLimitError(ProviderError):
    """Prompt payload exceeded model context window."""
    pass


class ProviderOutageError(ProviderError):
    """Provider upstream 500 error or total service outage."""
    pass


# -----------------------------------------------------------------------------
# 2. Metadata Contract
# -----------------------------------------------------------------------------


class ProviderMetadata(BaseModel):
    """Formal capabilities and cost metrics of a model."""

    provider_id: str
    model_id: str
    model_family: str
    context_window: int = 128000
    cost_per_million_input: float = 3.00
    cost_per_million_output: float = 15.00
    supports_structured_outputs: bool = True
    supports_tools: bool = True
    supports_vision: bool = False
    latency_class: str = "standard"  # fast | standard | slow
    health_status: str = "HEALTHY"  # HEALTHY | DEGRADED | OPEN | DISABLED


# -----------------------------------------------------------------------------
# 3. Abstract Provider Interface
# -----------------------------------------------------------------------------


class BaseModelProvider(ABC):
    """Vendor-neutral contract for all LLM intelligence providers."""

    def __init__(self, metadata: ProviderMetadata) -> None:
        self.metadata = metadata

    @abstractmethod
    async def generate_response(
        self,
        eap: ExecutiveAwarenessPackage,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ExecutiveModelResponse:
        """
        Takes canonical EAP, communicates with provider, and returns
        a validated, structured ExecutiveModelResponse.
        """
        pass
