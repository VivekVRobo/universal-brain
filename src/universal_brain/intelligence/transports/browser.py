from __future__ import annotations

from abc import ABC, abstractmethod

from .base import BaseModelTransport, TransportAuthError, TransportOutageError
from ..schemas import TransportKind


class BrowserModelDriver(ABC):
    @abstractmethod
    async def is_authenticated(self, route): ...

    @abstractmethod
    async def submit(self, model, route, request): ...

    async def recover_session(self, route, conversation_ref=None):
        """Optional continuity recovery hook after operator-authorized auth is healthy."""
        return conversation_ref


class BrowserHumanTransport(BaseModelTransport):
    def __init__(self, drivers=None):
        self.drivers = drivers or {}

    def register_driver(self, route_id, driver):
        self.drivers[route_id] = driver

    def supports(self, route):
        return route.transport == TransportKind.BROWSER and route.route_id in self.drivers

    async def invoke(self, model, route, request):
        driver = self.drivers.get(route.route_id)
        if not driver:
            raise TransportAuthError(f"No authorized browser driver for {route.route_id}")
        if not await driver.is_authenticated(route):
            raise TransportAuthError(
                f"Browser route {route.route_id} requires operator authentication"
            )
        result = await driver.submit(model, route, request)
        result.evidence.setdefault("interaction_mode", "authorized_browser_session")
        action = str(request.metadata.get("action_class", "A0"))
        if action in {"A1", "A2"} and not (
            result.evidence.get("session_artifact") or result.evidence.get("session_capture")
        ):
            raise TransportOutageError(
                f"Browser route {route.route_id} returned no session evidence for {action}"
            )
        return result
