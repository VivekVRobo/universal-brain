"""
Universal Brain - Perception Adapter Interface
Implements Sections 101-102 of Milestone M8 Specification.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from uuid import UUID

from universal_brain.world.schemas import (
    Observation,
    ObservationType,
    PrivacyClass,
    SourceHealth,
)


class PerceptionAdapter(ABC):
    """
    Abstract base interface for perception adapters.
    Adapters ingest raw external signals, normalize them to canonical Observations,
    and output them to the Observation Ingest Gate.
    Adapters NEVER directly modify world entities, trigger mission actions,
    or issue capability tokens (Section 102).
    """

    def __init__(
        self,
        source_id: str,
        source_session_id: UUID,
        privacy_class: PrivacyClass = PrivacyClass.INTERNAL,
    ) -> None:
        self.source_id = source_id
        self.source_session_id = source_session_id
        self.privacy_class = privacy_class
        self.sequence_counter: int = 0
        self.health_status: SourceHealth = SourceHealth.HEALTHY

    @abstractmethod
    def start(self) -> None:
        """Starts adapter background capture or connections."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Gracefully halts adapter capture."""
        pass

    def health(self) -> SourceHealth:
        """Reports current source adapter health."""
        return self.health_status

    def next_sequence(self) -> int:
        self.sequence_counter += 1
        return self.sequence_counter

    @abstractmethod
    def observe(self, raw_signal: Any) -> Optional[Observation]:
        """Normalizes an external raw signal into a canonical Observation envelope."""
        pass
