"""Local/Ollama resource admission manager.

Traceability: REQ-ENG-009, REQ-ENG-018, REQ-STA-006, ALN-008. This module manages compute
admission only; it does not change model permissions or unload processes by itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class LocalModelResourceProfile(BaseModel):
    model_key: str
    estimated_vram_mb: int = Field(ge=0)
    estimated_ram_mb: int = Field(ge=0)
    max_concurrency: int = Field(default=1, ge=1)
    cold_start_seconds: float = Field(default=0, ge=0)
    expected_tokens_per_second: float = Field(default=0, ge=0)


class LocalResourceSnapshot(BaseModel):
    available_vram_mb: int = Field(ge=0)
    available_ram_mb: int = Field(ge=0)
    loaded_models: set[str] = Field(default_factory=set)
    gpu_utilization_pct: float = Field(default=0, ge=0, le=100)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResourceReservation(BaseModel):
    reservation_id: UUID = Field(default_factory=uuid4)
    model_key: str
    estimated_vram_mb: int
    estimated_ram_mb: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OllamaResourceManager:
    """Deterministic local-model admission/reservation for multi-model Ollama use."""

    def __init__(self, profiles: list[LocalModelResourceProfile] | None = None):
        self._profiles = {profile.model_key: profile for profile in (profiles or [])}
        self._reservations: dict[UUID, ResourceReservation] = {}
        self._active_by_model: dict[str, int] = {}
        self._lock = RLock()

    def register(self, profile: LocalModelResourceProfile) -> None:
        with self._lock:
            self._profiles[profile.model_key] = profile

    def can_admit(self, model_key: str, snapshot: LocalResourceSnapshot) -> tuple[bool, str]:
        profile = self._profiles.get(model_key)
        if profile is None:
            return False, "resource profile unavailable"
        active = self._active_by_model.get(model_key, 0)
        if active >= profile.max_concurrency:
            return False, "model concurrency ceiling reached"
        reserved_vram = sum(item.estimated_vram_mb for item in self._reservations.values())
        reserved_ram = sum(item.estimated_ram_mb for item in self._reservations.values())
        additional_vram = 0 if model_key in snapshot.loaded_models else profile.estimated_vram_mb
        if reserved_vram + additional_vram > snapshot.available_vram_mb:
            return False, "insufficient VRAM for admission"
        if reserved_ram + profile.estimated_ram_mb > snapshot.available_ram_mb:
            return False, "insufficient RAM for admission"
        return True, "admissible"

    def score(self, model_key: str, snapshot: LocalResourceSnapshot) -> float:
        ok, _ = self.can_admit(model_key, snapshot)
        if not ok:
            return 0.0
        profile = self._profiles[model_key]
        warm_bonus = 0.25 if model_key in snapshot.loaded_models else 0.0
        speed = min(1.0, profile.expected_tokens_per_second / 50.0) * 0.45
        cold_penalty = min(0.25, profile.cold_start_seconds / 120.0 * 0.25)
        utilization_penalty = snapshot.gpu_utilization_pct / 100.0 * 0.20
        return max(0.0, min(1.0, 0.45 + warm_bonus + speed - cold_penalty - utilization_penalty))

    def reserve(self, model_key: str, snapshot: LocalResourceSnapshot) -> ResourceReservation:
        with self._lock:
            ok, reason = self.can_admit(model_key, snapshot)
            if not ok:
                raise RuntimeError(f"Local model admission denied for {model_key}: {reason}")
            profile = self._profiles[model_key]
            reservation = ResourceReservation(
                model_key=model_key,
                estimated_vram_mb=0 if model_key in snapshot.loaded_models else profile.estimated_vram_mb,
                estimated_ram_mb=profile.estimated_ram_mb,
            )
            self._reservations[reservation.reservation_id] = reservation
            self._active_by_model[model_key] = self._active_by_model.get(model_key, 0) + 1
            return reservation

    def release(self, reservation_id: UUID) -> None:
        with self._lock:
            reservation = self._reservations.pop(reservation_id, None)
            if not reservation:
                return
            active = max(0, self._active_by_model.get(reservation.model_key, 0) - 1)
            if active:
                self._active_by_model[reservation.model_key] = active
            else:
                self._active_by_model.pop(reservation.model_key, None)


class OllamaRouteResourcePolicy:
    """Duck-typed IntelligenceRouter policy for local-model resource admission.

    The router remains model-agnostic. Local routes opt in by setting
    route.config['resource_model_key']; otherwise the route's model_key is used.
    """

    def __init__(self, manager: OllamaResourceManager, snapshot_provider):
        self.manager = manager
        self.snapshot_provider = snapshot_provider

    @staticmethod
    def _is_local(route) -> bool:
        value = getattr(getattr(route, "transport", None), "value", getattr(route, "transport", None))
        return value == "local"

    def _resource_key(self, model, route) -> str:
        return str(route.config.get("resource_model_key") or model.model_key)

    def eligibility_reason(self, model, route, task) -> str | None:
        if not self._is_local(route):
            return None
        snapshot = self.snapshot_provider()
        ok, reason = self.manager.can_admit(self._resource_key(model, route), snapshot)
        return None if ok else f"Local resource admission denied: {reason}"

    def score_multiplier(self, model, route, task) -> float:
        if not self._is_local(route):
            return 1.0
        snapshot = self.snapshot_provider()
        score = self.manager.score(self._resource_key(model, route), snapshot)
        return 0.60 + 0.40 * score

    def reserve_for_route(self, model, route):
        if not self._is_local(route):
            return None
        return self.manager.reserve(self._resource_key(model, route), self.snapshot_provider())

    def release(self, reservation) -> None:
        if reservation is not None:
            self.manager.release(reservation.reservation_id)
