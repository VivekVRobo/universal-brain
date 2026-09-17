"""
Universal Brain - Model Provider Registry & Circuit Breaker

Implements Section 18 & 23 of the God-Level Specification:
- Central registry of configured, healthy, and circuit-broken models;
- Circuit breaker state machine (HEALTHY -> DEGRADED -> OPEN -> HALF_OPEN);
- Invariant: The planner never contains 'if model == vendor-x'.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from universal_brain.executive.providers.base import BaseModelProvider


class CircuitBreaker:
    """Manages failure counts and circuit state for a provider."""

    def __init__(self, failure_threshold: int = 3, reset_timeout_seconds: int = 60) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self.failure_count = 0
        self.state = "HEALTHY"  # HEALTHY | DEGRADED | OPEN | HALF_OPEN

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "HEALTHY"

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
        elif self.failure_count >= 1:
            self.state = "DEGRADED"

    @property
    def is_available(self) -> bool:
        return self.state in ["HEALTHY", "DEGRADED", "HALF_OPEN"]


class ModelProviderRegistry:
    """Central registry maintaining model providers and their operational health."""

    def __init__(self) -> None:
        self._providers: Dict[str, BaseModelProvider] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

    def register_provider(self, provider: BaseModelProvider) -> None:
        """Register a provider instance."""
        p_id = provider.metadata.provider_id
        self._providers[p_id] = provider
        self._circuit_breakers[p_id] = CircuitBreaker()

    def get_provider(self, provider_id: str) -> Optional[BaseModelProvider]:
        """Fetch provider by ID."""
        return self._providers.get(provider_id)

    def list_healthy_providers(self) -> List[BaseModelProvider]:
        """List providers whose circuit breakers are not OPEN."""
        return [
            p for p_id, p in self._providers.items()
            if self._circuit_breakers[p_id].is_available
        ]

    def record_failure(self, provider_id: str) -> None:
        """Record provider failure and update circuit breaker."""
        if provider_id in self._circuit_breakers:
            self._circuit_breakers[provider_id].record_failure()
            # Sync health state to provider metadata
            if provider_id in self._providers:
                self._providers[provider_id].metadata.health_status = self._circuit_breakers[provider_id].state

    def record_success(self, provider_id: str) -> None:
        """Record provider success and reset circuit breaker."""
        if provider_id in self._circuit_breakers:
            self._circuit_breakers[provider_id].record_success()
            if provider_id in self._providers:
                self._providers[provider_id].metadata.health_status = "HEALTHY"
