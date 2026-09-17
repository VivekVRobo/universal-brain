from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..schemas import (
    AccessRoute,
    ModelDescriptor,
    ModelRequest,
    ModelStreamEvent,
    StreamEventType,
    NormalizedModelResult,
)


class TransportError(Exception):
    pass


class TransportAuthError(TransportError):
    pass


class TransportRateLimitError(TransportError):
    def __init__(self, message: str, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class TransportTimeoutError(TransportError):
    pass


class TransportContextLimitError(TransportError):
    pass


class TransportOutageError(TransportError):
    pass


class StreamInterruptedError(TransportError):
    pass


class BaseModelTransport(ABC):
    @abstractmethod
    def supports(self, route: AccessRoute) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def invoke(
        self,
        model: ModelDescriptor,
        route: AccessRoute,
        request: ModelRequest,
    ) -> NormalizedModelResult:
        raise NotImplementedError

    async def stream(
        self,
        model: ModelDescriptor,
        route: AccessRoute,
        request: ModelRequest,
    ) -> AsyncIterator[ModelStreamEvent]:
        """Provider-neutral streaming fallback.

        Transports with true upstream streaming can override this method. The default
        wraps a normal invocation into a stable event protocol so downstream code
        never depends on provider SSE formats.
        """
        yield ModelStreamEvent(
            event_type=StreamEventType.STARTED,
            request_id=request.request_id,
            model_key=model.model_key,
            route_id=route.route_id,
            sequence=0,
        )
        result = await self.invoke(model, route, request)
        sequence = 1
        if result.output_text:
            yield ModelStreamEvent(
                event_type=StreamEventType.TEXT_DELTA,
                request_id=request.request_id,
                model_key=model.model_key,
                route_id=route.route_id,
                sequence=sequence,
                delta_text=result.output_text,
            )
            sequence += 1
        for tool_call in result.tool_calls:
            yield ModelStreamEvent(
                event_type=StreamEventType.TOOL_CALL,
                request_id=request.request_id,
                model_key=model.model_key,
                route_id=route.route_id,
                sequence=sequence,
                tool_call=tool_call,
            )
            sequence += 1
        yield ModelStreamEvent(
            event_type=StreamEventType.USAGE,
            request_id=request.request_id,
            model_key=model.model_key,
            route_id=route.route_id,
            sequence=sequence,
            usage=result.usage,
        )
        sequence += 1
        yield ModelStreamEvent(
            event_type=StreamEventType.COMPLETED,
            request_id=request.request_id,
            model_key=model.model_key,
            route_id=route.route_id,
            sequence=sequence,
            final_result=result,
        )
