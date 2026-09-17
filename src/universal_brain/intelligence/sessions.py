from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ConversationBinding(BaseModel):
    binding_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    role: str
    model_key: str
    route_id: str
    conversation_ref: str
    last_task_id: Optional[UUID] = None
    context_version: int = Field(default=1, ge=1)
    active: bool = True
    inactive_reason: Optional[str] = None
    recovery_count: int = Field(default=0, ge=0)
    last_failure_at: Optional[datetime] = None
    last_recovered_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationRegistry:
    """Non-canonical continuity registry with recovery metadata.

    The registry may be deleted without losing canonical goals, permissions,
    commitments, or evidence. It stores only provider/UI conversation references and
    continuity metadata.
    """

    SCHEMA_VERSION = 1

    def __init__(self, persistence_path=None):
        self._bindings: dict[UUID, ConversationBinding] = {}
        self.path = Path(persistence_path).expanduser() if persistence_path else None
        if self.path and self.path.exists():
            self._load()

    def _load(self):
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported conversation registry schema")
        for item in raw.get("bindings", []):
            binding = ConversationBinding.model_validate(item)
            self._bindings[binding.binding_id] = binding

    def _persist(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "schema_version": self.SCHEMA_VERSION,
                    "bindings": [
                        binding.model_dump(mode="json")
                        for binding in self._bindings.values()
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def get(self, binding_id: UUID) -> ConversationBinding | None:
        return self._bindings.get(binding_id)

    def find(self, project_id, role, model_key=None, route_id=None):
        matches = [
            binding
            for binding in self._bindings.values()
            if binding.active
            and binding.project_id == project_id
            and binding.role == role
            and (model_key is None or binding.model_key == model_key)
            and (route_id is None or binding.route_id == route_id)
        ]
        matches.sort(key=lambda binding: binding.updated_at, reverse=True)
        return matches[0] if matches else None

    def upsert(
        self,
        *,
        project_id,
        role,
        model_key,
        route_id,
        conversation_ref,
        last_task_id=None,
    ):
        if not conversation_ref.strip():
            raise ValueError("conversation_ref required")
        binding = self.find(project_id, role, model_key, route_id)
        now = datetime.now(timezone.utc)
        if binding:
            binding.conversation_ref = conversation_ref
            binding.last_task_id = last_task_id
            binding.context_version += 1
            binding.updated_at = now
            binding.active = True
            binding.inactive_reason = None
        else:
            # Reuse the newest inactive continuity slot for the same role/route so
            # recovery history remains attached to one logical binding.
            inactive = [
                item
                for item in self._bindings.values()
                if not item.active
                and item.project_id == project_id
                and item.role == role
                and item.model_key == model_key
                and item.route_id == route_id
            ]
            inactive.sort(key=lambda item: item.updated_at, reverse=True)
            if inactive:
                binding = inactive[0]
                binding.conversation_ref = conversation_ref
                binding.last_task_id = last_task_id
                binding.context_version += 1
                binding.active = True
                binding.inactive_reason = None
                binding.last_recovered_at = now
                binding.recovery_count += 1
                binding.updated_at = now
            else:
                binding = ConversationBinding(
                    project_id=project_id,
                    role=role,
                    model_key=model_key,
                    route_id=route_id,
                    conversation_ref=conversation_ref,
                    last_task_id=last_task_id,
                )
                self._bindings[binding.binding_id] = binding
        self._persist()
        return binding

    def invalidate(self, binding_id: UUID, reason="route_session_lost") -> bool:
        binding = self._bindings.get(binding_id)
        if binding is None or not binding.active:
            return False
        now = datetime.now(timezone.utc)
        binding.active = False
        binding.inactive_reason = reason
        binding.last_failure_at = now
        binding.updated_at = now
        self._persist()
        return True

    def invalidate_route(self, route_id, reason="route_session_lost"):
        count = 0
        now = datetime.now(timezone.utc)
        for binding in self._bindings.values():
            if binding.route_id == route_id and binding.active:
                binding.active = False
                binding.inactive_reason = reason
                binding.last_failure_at = now
                binding.updated_at = now
                count += 1
        if count:
            self._persist()
        return count

    def reactivate(
        self,
        binding_id: UUID,
        *,
        conversation_ref: str | None = None,
        reason: str = "session_recovered",
    ) -> ConversationBinding:
        binding = self._bindings.get(binding_id)
        if binding is None:
            raise KeyError(f"unknown conversation binding {binding_id}")
        if conversation_ref is not None:
            if not conversation_ref.strip():
                raise ValueError("conversation_ref required")
            binding.conversation_ref = conversation_ref
        now = datetime.now(timezone.utc)
        binding.active = True
        binding.inactive_reason = None
        binding.last_recovered_at = now
        binding.recovery_count += 1
        binding.context_version += 1
        binding.updated_at = now
        self._persist()
        return binding

    def list_route(
        self,
        route_id: str,
        *,
        active_only: bool | None = None,
    ) -> list[ConversationBinding]:
        bindings = [binding for binding in self._bindings.values() if binding.route_id == route_id]
        if active_only is True:
            bindings = [binding for binding in bindings if binding.active]
        elif active_only is False:
            bindings = [binding for binding in bindings if not binding.active]
        return sorted(bindings, key=lambda binding: binding.updated_at, reverse=True)

    def list_project(self, project_id):
        return sorted(
            [
                binding
                for binding in self._bindings.values()
                if binding.project_id == project_id
            ],
            key=lambda binding: binding.updated_at,
            reverse=True,
        )

    def list_all(self, *, active_only: bool = False) -> list[ConversationBinding]:
        bindings = list(self._bindings.values())
        if active_only:
            bindings = [binding for binding in bindings if binding.active]
        return sorted(bindings, key=lambda binding: binding.updated_at, reverse=True)
