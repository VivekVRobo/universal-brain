from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field


class RouteQuotaPolicy(BaseModel):
    window_seconds: int = Field(default=60, gt=0)
    max_requests: Optional[int] = Field(default=None, gt=0)
    max_input_tokens: Optional[int] = Field(default=None, gt=0)
    max_output_tokens: Optional[int] = Field(default=None, gt=0)
    default_rate_limit_cooldown_seconds: int = Field(default=60, gt=0)


class RouteQuotaSnapshot(BaseModel):
    route_id: str
    configured: bool
    requests_in_window: int = 0
    input_tokens_in_window: int = 0
    output_tokens_in_window: int = 0
    cooldown_until: Optional[datetime] = None
    eligibility_reason: Optional[str] = None
    policy: Optional[RouteQuotaPolicy] = None


@dataclass
class _Event:
    at: datetime
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class _State:
    policy: RouteQuotaPolicy
    events: deque = field(default_factory=deque)
    cooldown_until: Optional[datetime] = None


class RouteQuotaRegistry:
    def __init__(self):
        self._s: dict[str, _State] = {}

    def configure(self, route_id: str, policy: RouteQuotaPolicy):
        self._s[route_id] = _State(policy)

    @staticmethod
    def _prune(state: _State, now: datetime):
        cutoff = now - timedelta(seconds=state.policy.window_seconds)
        while state.events and state.events[0].at <= cutoff:
            state.events.popleft()
        if state.cooldown_until and now >= state.cooldown_until:
            state.cooldown_until = None

    def eligibility_reason(
        self,
        route_id: str,
        estimated_input_tokens: int = 0,
        estimated_output_tokens: int = 0,
    ):
        state = self._s.get(route_id)
        if not state:
            return None
        now = datetime.now(timezone.utc)
        self._prune(state, now)
        policy = state.policy
        if state.cooldown_until:
            return f"Route rate-limited until {state.cooldown_until.isoformat()}."
        if policy.max_requests is not None and len(state.events) + 1 > policy.max_requests:
            return "Route request quota would be exceeded."
        if (
            policy.max_input_tokens is not None
            and sum(event.input_tokens for event in state.events) + estimated_input_tokens
            > policy.max_input_tokens
        ):
            return "Route input-token quota would be exceeded."
        if (
            policy.max_output_tokens is not None
            and sum(event.output_tokens for event in state.events) + estimated_output_tokens
            > policy.max_output_tokens
        ):
            return "Route output-token quota would be exceeded."
        return None

    def record_attempt(self, route_id: str):
        if route_id in self._s:
            self._s[route_id].events.append(_Event(datetime.now(timezone.utc)))

    def record_usage(self, route_id: str, input_tokens: int = 0, output_tokens: int = 0):
        if route_id not in self._s:
            return
        if not self._s[route_id].events:
            self.record_attempt(route_id)
        event = self._s[route_id].events[-1]
        event.input_tokens += max(input_tokens, 0)
        event.output_tokens += max(output_tokens, 0)

    def mark_rate_limited(self, route_id: str, retry_after_seconds: int | None = None):
        state = self._s.setdefault(route_id, _State(RouteQuotaPolicy()))
        state.cooldown_until = datetime.now(timezone.utc) + timedelta(
            seconds=retry_after_seconds
            or state.policy.default_rate_limit_cooldown_seconds
        )

    def snapshot(self, route_id: str) -> RouteQuotaSnapshot:
        state = self._s.get(route_id)
        if state is None:
            return RouteQuotaSnapshot(route_id=route_id, configured=False)
        now = datetime.now(timezone.utc)
        self._prune(state, now)
        return RouteQuotaSnapshot(
            route_id=route_id,
            configured=True,
            requests_in_window=len(state.events),
            input_tokens_in_window=sum(event.input_tokens for event in state.events),
            output_tokens_in_window=sum(event.output_tokens for event in state.events),
            cooldown_until=state.cooldown_until,
            eligibility_reason=self.eligibility_reason(route_id),
            policy=state.policy,
        )
