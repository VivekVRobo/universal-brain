"""
Universal Brain - Source Sessions & Epoch Fencing
Implements Sections 13-14 of Milestone M8 Specification (M8-INV-19).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from uuid import UUID, uuid4

from universal_brain.world.errors import SourceFencedError
from universal_brain.world.schemas import SourceSession


class SourceSessionManager:
    """
    Manages active source runtime sessions, binding them to the monotonic
    kernel epoch to prevent zombie/pre-reboot adapters from injecting stale observations.
    """

    def __init__(self, current_epoch: int = 1) -> None:
        self.current_epoch = current_epoch
        self._sessions: Dict[UUID, SourceSession] = {}

    def set_epoch(self, epoch: int) -> None:
        self.current_epoch = epoch

    def create_session(
        self,
        source_id: str,
        duration_sec: int = 3600,
        credential_binding: str = "",
    ) -> SourceSession:
        now = datetime.now(timezone.utc)
        session = SourceSession(
            source_session_id=uuid4(),
            source_id=source_id,
            kernel_epoch=self.current_epoch,
            started_at=now,
            expires_at=now + timedelta(seconds=duration_sec),
            protocol_version="1.0",
            credential_binding=credential_binding,
            status="ACTIVE",
        )
        self._sessions[session.source_session_id] = session
        return session

    def validate_session(self, session_id: UUID) -> SourceSession:
        """
        Validates session existence, expiry, and monotonic kernel epoch.
        Raises SourceFencedError if kernel_epoch < current_epoch.
        """
        if session_id not in self._sessions:
            raise SourceFencedError(
                f"Source session {session_id} does not exist or has expired.",
                {"session_id": str(session_id)},
            )
        session = self._sessions[session_id]
        now = datetime.now(timezone.utc)

        if session.kernel_epoch < self.current_epoch:
            session.status = "FENCED"
            raise SourceFencedError(
                f"Source session {session_id} belongs to superseded kernel epoch {session.kernel_epoch} (current is {self.current_epoch}).",
                {"session_id": str(session_id), "session_epoch": session.kernel_epoch, "current_epoch": self.current_epoch},
            )

        if now > session.expires_at:
            session.status = "EXPIRED"
            raise SourceFencedError(
                f"Source session {session_id} expired at {session.expires_at.isoformat()}.",
                {"session_id": str(session_id), "expires_at": session.expires_at.isoformat()},
            )

        return session
