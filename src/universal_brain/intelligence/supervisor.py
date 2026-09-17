from __future__ import annotations

import inspect
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .schemas import RouteHealth, TransportKind


class SessionProbe(BaseModel):
    route_id: str
    transport: TransportKind
    available: bool
    authenticated: bool | None = None
    health: RouteHealth
    reason: str | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionRecoveryStatus(str, Enum):
    RECOVERED = "recovered"
    HEALTHY_NOOP = "healthy_noop"
    AUTH_REQUIRED = "auth_required"
    UNAVAILABLE = "unavailable"
    DRIVER_MISSING = "driver_missing"
    FAILED = "failed"


class SessionRecoveryResult(BaseModel):
    route_id: str
    transport: TransportKind
    status: SessionRecoveryStatus
    recovered_bindings: int = 0
    attempted_bindings: int = 0
    new_conversation_refs: dict[str, str] = Field(default_factory=dict)
    reason: str | None = None
    recovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InteractionSessionSupervisor:
    """Supervises user-authorized browser/desktop cognitive sessions.

    It never enters credentials, bypasses MFA/CAPTCHA, or attempts stealth. Session
    loss is converted into route health plus conversation invalidation. Recovery is
    limited to reopening already-authorized application/browser state after the
    operator has restored authentication when necessary.
    """

    def __init__(
        self,
        *,
        browser_transport,
        desktop_transport,
        conversations,
        health_registry,
    ) -> None:
        self.browser_transport = browser_transport
        self.desktop_transport = desktop_transport
        self.conversations = conversations
        self.health_registry = health_registry

    async def probe_route(self, route) -> SessionProbe:
        if route.transport == TransportKind.BROWSER:
            driver = self.browser_transport.drivers.get(route.route_id)
            if driver is None:
                self.health_registry.record_failure(route.route_id, "browser driver missing")
                return SessionProbe(
                    route_id=route.route_id,
                    transport=route.transport,
                    available=False,
                    authenticated=False,
                    health=self.health_registry.get_state(route.route_id),
                    reason="browser_driver_missing",
                )
            try:
                authenticated = bool(await driver.is_authenticated(route))
            except Exception as exc:  # Probe must not crash the control plane.
                self.health_registry.record_failure(route.route_id, str(exc))
                return SessionProbe(
                    route_id=route.route_id,
                    transport=route.transport,
                    available=False,
                    authenticated=None,
                    health=self.health_registry.get_state(route.route_id),
                    reason=type(exc).__name__,
                )
            if not authenticated:
                self.health_registry.mark_auth_required(
                    route.route_id, "operator authentication required"
                )
                self.conversations.invalidate_route(route.route_id, "authentication_required")
                return SessionProbe(
                    route_id=route.route_id,
                    transport=route.transport,
                    available=True,
                    authenticated=False,
                    health=RouteHealth.AUTH_REQUIRED,
                    reason="operator_authentication_required",
                )
            self.health_registry.enable(route.route_id)
            return SessionProbe(
                route_id=route.route_id,
                transport=route.transport,
                available=True,
                authenticated=True,
                health=RouteHealth.HEALTHY,
            )

        if route.transport == TransportKind.DESKTOP_APP:
            driver = self.desktop_transport.drivers.get(route.route_id)
            if driver is None:
                self.health_registry.record_failure(route.route_id, "desktop driver missing")
                return SessionProbe(
                    route_id=route.route_id,
                    transport=route.transport,
                    available=False,
                    health=self.health_registry.get_state(route.route_id),
                    reason="desktop_driver_missing",
                )
            try:
                available = bool(await driver.is_available(route))
            except Exception as exc:
                self.health_registry.record_failure(route.route_id, str(exc))
                return SessionProbe(
                    route_id=route.route_id,
                    transport=route.transport,
                    available=False,
                    health=self.health_registry.get_state(route.route_id),
                    reason=type(exc).__name__,
                )
            if not available:
                self.health_registry.record_failure(route.route_id, "desktop app unavailable")
                self.conversations.invalidate_route(route.route_id, "desktop_app_unavailable")
                return SessionProbe(
                    route_id=route.route_id,
                    transport=route.transport,
                    available=False,
                    health=self.health_registry.get_state(route.route_id),
                    reason="desktop_app_unavailable",
                )
            self.health_registry.enable(route.route_id)
            return SessionProbe(
                route_id=route.route_id,
                transport=route.transport,
                available=True,
                health=RouteHealth.HEALTHY,
            )

        return SessionProbe(
            route_id=route.route_id,
            transport=route.transport,
            available=True,
            health=self.health_registry.get_state(route.route_id),
            reason="not_interactive_transport",
        )

    async def _call_recover(self, driver, route, conversation_ref: str | None):
        recover = getattr(driver, "recover_session", None)
        if recover is None:
            return conversation_ref
        result = recover(route, conversation_ref=conversation_ref)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict):
            return result.get("conversation_ref") or conversation_ref
        if isinstance(result, str):
            return result
        if result is None:
            return conversation_ref
        raise TypeError("recover_session must return str, dict, or None")

    async def recover_route(self, route) -> SessionRecoveryResult:
        """Recover continuity only after the interactive route is usable again.

        Authentication is never automated. If the operator still needs to log in, the
        result is AUTH_REQUIRED and inactive bindings remain inactive.
        """
        if route.transport == TransportKind.BROWSER:
            driver = self.browser_transport.drivers.get(route.route_id)
            if driver is None:
                return SessionRecoveryResult(
                    route_id=route.route_id,
                    transport=route.transport,
                    status=SessionRecoveryStatus.DRIVER_MISSING,
                    reason="browser_driver_missing",
                )
            try:
                if not await driver.is_authenticated(route):
                    self.health_registry.mark_auth_required(
                        route.route_id, "operator authentication required"
                    )
                    return SessionRecoveryResult(
                        route_id=route.route_id,
                        transport=route.transport,
                        status=SessionRecoveryStatus.AUTH_REQUIRED,
                        reason="operator_authentication_required",
                    )
            except Exception as exc:
                self.health_registry.record_failure(route.route_id, str(exc))
                return SessionRecoveryResult(
                    route_id=route.route_id,
                    transport=route.transport,
                    status=SessionRecoveryStatus.FAILED,
                    reason=type(exc).__name__,
                )
        elif route.transport == TransportKind.DESKTOP_APP:
            driver = self.desktop_transport.drivers.get(route.route_id)
            if driver is None:
                return SessionRecoveryResult(
                    route_id=route.route_id,
                    transport=route.transport,
                    status=SessionRecoveryStatus.DRIVER_MISSING,
                    reason="desktop_driver_missing",
                )
            try:
                if not await driver.is_available(route):
                    return SessionRecoveryResult(
                        route_id=route.route_id,
                        transport=route.transport,
                        status=SessionRecoveryStatus.UNAVAILABLE,
                        reason="desktop_app_unavailable",
                    )
            except Exception as exc:
                self.health_registry.record_failure(route.route_id, str(exc))
                return SessionRecoveryResult(
                    route_id=route.route_id,
                    transport=route.transport,
                    status=SessionRecoveryStatus.FAILED,
                    reason=type(exc).__name__,
                )
        else:
            return SessionRecoveryResult(
                route_id=route.route_id,
                transport=route.transport,
                status=SessionRecoveryStatus.HEALTHY_NOOP,
                reason="not_interactive_transport",
            )

        inactive = self.conversations.list_route(route.route_id, active_only=False)
        if not inactive:
            self.health_registry.enable(route.route_id)
            return SessionRecoveryResult(
                route_id=route.route_id,
                transport=route.transport,
                status=SessionRecoveryStatus.HEALTHY_NOOP,
            )

        recovered = 0
        refs: dict[str, str] = {}
        errors: list[str] = []
        for binding in inactive:
            try:
                new_ref = await self._call_recover(driver, route, binding.conversation_ref)
                if not new_ref:
                    errors.append(f"{binding.binding_id}: no conversation reference")
                    continue
                updated = self.conversations.reactivate(
                    binding.binding_id,
                    conversation_ref=str(new_ref),
                )
                recovered += 1
                refs[str(updated.binding_id)] = updated.conversation_ref
            except Exception as exc:  # Keep other bindings recoverable.
                errors.append(f"{binding.binding_id}: {type(exc).__name__}: {exc}")

        if recovered:
            self.health_registry.enable(route.route_id)
            return SessionRecoveryResult(
                route_id=route.route_id,
                transport=route.transport,
                status=SessionRecoveryStatus.RECOVERED,
                recovered_bindings=recovered,
                attempted_bindings=len(inactive),
                new_conversation_refs=refs,
                reason="; ".join(errors) if errors else None,
            )

        self.health_registry.record_failure(
            route.route_id, "session recovery failed" + (f": {'; '.join(errors)}" if errors else "")
        )
        return SessionRecoveryResult(
            route_id=route.route_id,
            transport=route.transport,
            status=SessionRecoveryStatus.FAILED,
            recovered_bindings=0,
            attempted_bindings=len(inactive),
            reason="; ".join(errors) or "session_recovery_failed",
        )

    async def recover_all(self, catalog) -> list[SessionRecoveryResult]:
        results = []
        for route in catalog.list_routes(enabled_only=False):
            if route.transport in {TransportKind.BROWSER, TransportKind.DESKTOP_APP}:
                results.append(await self.recover_route(route))
        return results

    async def probe_all(self, catalog) -> list[SessionProbe]:
        probes = []
        for route in catalog.list_routes(enabled_only=False):
            if route.transport in {TransportKind.BROWSER, TransportKind.DESKTOP_APP}:
                probes.append(await self.probe_route(route))
        return probes

    async def close_all(self) -> None:
        seen: set[int] = set()
        drivers = [
            *self.browser_transport.drivers.values(),
            *self.desktop_transport.drivers.values(),
        ]
        for driver in drivers:
            if id(driver) in seen:
                continue
            seen.add(id(driver))
            close = getattr(driver, "close", None)
            if close is None:
                continue
            result = close()
            if inspect.isawaitable(result):
                await result
