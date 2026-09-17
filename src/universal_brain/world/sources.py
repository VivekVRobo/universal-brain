"""
Universal Brain - Observation Source Registry & Scope Security
Implements Sections 12, 15, 16 of Milestone M8 Specification (M8-INV-06).
"""

from __future__ import annotations

from typing import Dict, List, Optional
from universal_brain.world.errors import (
    SourceAuthenticationError,
    SourceScopeError,
    SourceUnavailableError,
)
from universal_brain.world.schemas import (
    ObservationSource,
    ObservationType,
    SourceHealth,
    SourceTrustClass,
    SourceType,
)


class ObservationSourceRegistry:
    """
    Registry for external and internal observation sources.
    Enforces authentication, health state, and authorized entity/type scopes.
    """

    def __init__(self) -> None:
        self._sources: Dict[str, ObservationSource] = {}

    def register_source(self, source: ObservationSource) -> None:
        self._sources[source.source_id] = source

    def get_source(self, source_id: str) -> Optional[ObservationSource]:
        return self._sources.get(source_id)

    def authenticate_source(self, source_id: str, token: str) -> ObservationSource:
        """Verifies source existence and authentication credentials."""
        if source_id not in self._sources:
            raise SourceUnavailableError(
                f"Observation source '{source_id}' is not registered.",
                {"source_id": source_id},
            )
        source = self._sources[source_id]
        if source.health == SourceHealth.REVOKED:
            raise SourceUnavailableError(
                f"Observation source '{source_id}' has been revoked.",
                {"source_id": source_id},
            )
        if source.authentication_token and source.authentication_token != token:
            raise SourceAuthenticationError(
                f"Invalid authentication token for source '{source_id}'.",
                {"source_id": source_id},
            )
        return source

    def validate_scope(
        self,
        source_id: str,
        obs_type: ObservationType,
        subject_ref: str,
        property_key: str,
    ) -> None:
        """
        Enforces Section 15: Sources can only report observation types and entity scopes
        they are explicitly authorized for.
        """
        if source_id not in self._sources:
            raise SourceUnavailableError(f"Source '{source_id}' not found.", {"source_id": source_id})
        source = self._sources[source_id]

        if source.allowed_types and obs_type not in source.allowed_types:
            raise SourceScopeError(
                f"Source '{source_id}' is not authorized to submit observation type '{obs_type.value}'.",
                {"source_id": source_id, "attempted_type": obs_type.value, "allowed_types": [t.value for t in source.allowed_types]},
            )

        if source.allowed_entity_scopes:
            from universal_brain.kernel.capability import is_resource_authorized
            # Enforce boundary-safe matching (safe/* does NOT authorize safeevil)
            matched = any(
                is_resource_authorized(scope, subject_ref)
                for scope in source.allowed_entity_scopes
            )
            if not matched:
                raise SourceScopeError(
                    f"Source '{source_id}' is not authorized for entity scope '{subject_ref}'. Allowed: {source.allowed_entity_scopes}",
                    {"source_id": source_id, "subject_ref": subject_ref, "allowed_scopes": source.allowed_entity_scopes},
                )
