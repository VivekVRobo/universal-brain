from __future__ import annotations

import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from .health import RouteHealthRegistry
from .quota import RouteQuotaRegistry
from .schemas import FabricRoutingDecision, ModelRequest, ModelStreamEvent, ModelUsage, StreamEventType
from .telemetry import RouteTelemetryRegistry
from .transports.base import (
    BaseModelTransport,
    TransportAuthError,
    TransportError,
    TransportOutageError,
    TransportRateLimitError,
)


class IntelligenceRuntime:
    def __init__(
        self,
        catalog,
        transports,
        health_registry: RouteHealthRegistry | None = None,
        quota_registry: RouteQuotaRegistry | None = None,
        telemetry_registry: RouteTelemetryRegistry | None = None,
        execution_policies=None,
    ) -> None:
        self.catalog = catalog
        self.transports: list[BaseModelTransport] = list(transports)
        self.health_registry = health_registry or RouteHealthRegistry()
        self.quota_registry = quota_registry or RouteQuotaRegistry()
        self.telemetry_registry = telemetry_registry or RouteTelemetryRegistry()
        self.execution_policies = list(execution_policies or [])

    def _reserve_route(self, model, route):
        reservations = []
        try:
            for policy in self.execution_policies:
                hook = getattr(policy, "reserve_for_route", None)
                if hook is None:
                    continue
                reservation = hook(model, route)
                if reservation is not None:
                    reservations.append((policy, reservation))
            return reservations
        except Exception as exc:
            for policy, reservation in reversed(reservations):
                release = getattr(policy, "release", None)
                if release is not None:
                    release(reservation)
            raise TransportOutageError(f"Route resource admission failed for {route.route_id}: {exc}") from exc

    @staticmethod
    def _release_route(reservations):
        for policy, reservation in reversed(reservations):
            release = getattr(policy, "release", None)
            if release is not None:
                release(reservation)

    def _transport_for(self, route):
        for transport in self.transports:
            if transport.supports(route):
                return transport
        raise TransportOutageError(f"No runtime transport supports {route.route_id}")

    def _record_failure(self, route, request, started_at, started_perf, error, *, streamed=False):
        record = self.telemetry_registry.make_record(
            request_id=request.request_id,
            model_key=route.model_key,
            route_id=route.route_id,
            transport=route.transport,
            task_kind=str(request.metadata.get("task_kind") or "general"),
            status="failure",
            started_at=started_at,
            latency_ms=(time.perf_counter() - started_perf) * 1000,
            error=error,
            streamed=streamed,
        )
        self.telemetry_registry.record(record)

    def _record_success(self, route, request, started_at, started_perf, usage, *, streamed=False):
        record = self.telemetry_registry.make_record(
            request_id=request.request_id,
            model_key=route.model_key,
            route_id=route.route_id,
            transport=route.transport,
            task_kind=str(request.metadata.get("task_kind") or "general"),
            status="success",
            started_at=started_at,
            latency_ms=(time.perf_counter() - started_perf) * 1000,
            usage=usage,
            streamed=streamed,
        )
        self.telemetry_registry.record(record)

    def _handle_transport_error(self, route_id: str, error: TransportError) -> None:
        if isinstance(error, TransportAuthError):
            self.health_registry.mark_auth_required(route_id, str(error))
        elif isinstance(error, TransportRateLimitError):
            self.quota_registry.mark_rate_limited(route_id, error.retry_after_seconds)
        else:
            self.health_registry.record_failure(route_id, str(error))

    async def invoke(self, decision: FabricRoutingDecision, request: ModelRequest):
        model = self.catalog.require_model(decision.model_key)
        route = self.catalog.require_route(decision.route_id)
        transport = self._transport_for(route)
        reservations = self._reserve_route(model, route)
        self.quota_registry.record_attempt(route.route_id)
        started_at = datetime.now(timezone.utc)
        started_perf = time.perf_counter()
        try:
            result = await transport.invoke(model, route, request)
        except TransportError as error:
            self._handle_transport_error(route.route_id, error)
            self._record_failure(route, request, started_at, started_perf, error)
            raise
        finally:
            self._release_route(reservations)
        self.health_registry.record_success(route.route_id)
        self.quota_registry.record_usage(
            route.route_id, result.usage.input_tokens, result.usage.output_tokens
        )
        self._record_success(route, request, started_at, started_perf, result.usage)
        return result

    async def stream(
        self,
        decision: FabricRoutingDecision,
        request: ModelRequest,
    ) -> AsyncIterator[ModelStreamEvent]:
        model = self.catalog.require_model(decision.model_key)
        route = self.catalog.require_route(decision.route_id)
        transport = self._transport_for(route)
        reservations = self._reserve_route(model, route)
        self.quota_registry.record_attempt(route.route_id)
        started_at = datetime.now(timezone.utc)
        started_perf = time.perf_counter()
        final_usage = ModelUsage()
        try:
            async for event in transport.stream(model, route, request):
                if event.usage is not None:
                    final_usage = event.usage
                if event.final_result is not None:
                    final_usage = event.final_result.usage
                yield event
        except TransportError as error:
            self._handle_transport_error(route.route_id, error)
            self._record_failure(
                route,
                request,
                started_at,
                started_perf,
                error,
                streamed=True,
            )
            raise
        finally:
            self._release_route(reservations)
        self.health_registry.record_success(route.route_id)
        self.quota_registry.record_usage(
            route.route_id, final_usage.input_tokens, final_usage.output_tokens
        )
        self._record_success(
            route,
            request,
            started_at,
            started_perf,
            final_usage,
            streamed=True,
        )
