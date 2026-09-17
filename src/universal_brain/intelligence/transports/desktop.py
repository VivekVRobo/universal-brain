from __future__ import annotations

from abc import ABC, abstractmethod

from .base import BaseModelTransport, TransportOutageError
from ..schemas import TransportKind


class DesktopModelDriver(ABC):
    @abstractmethod
    async def is_available(self, route): ...

    @abstractmethod
    async def submit(self, model, route, request): ...

    async def recover_session(self, route, conversation_ref=None):
        return conversation_ref


class DesktopAppTransport(BaseModelTransport):
    def __init__(self, drivers=None):
        self.drivers = drivers or {}

    def register_driver(self, route_id, driver):
        self.drivers[route_id] = driver

    def supports(self, route):
        return route.transport == TransportKind.DESKTOP_APP and route.route_id in self.drivers

    async def invoke(self, model, route, request):
        driver = self.drivers.get(route.route_id)
        if not driver or not await driver.is_available(route):
            raise TransportOutageError(f"Desktop route {route.route_id} unavailable")
        result = await driver.submit(model, route, request)
        result.evidence.setdefault("interaction_mode", "authorized_desktop_app")
        action = str(request.metadata.get("action_class", "A0"))
        if action in {"A1", "A2"} and not (
            result.evidence.get("session_artifact") or result.evidence.get("session_capture")
        ):
            raise TransportOutageError(
                f"Desktop route {route.route_id} returned no session evidence for {action}"
            )
        return result
