"""
Universal Brain - Realtime WebSocket Gateway & Event Cursor

Implements Section 6 of the Operator Console Specification:
- Durable sequence-ordered event streaming;
- Client cursor tracking (last_confirmed_sequence);
- Missed-event replay buffer;
- Fast snapshot recovery detection (SNAPSHOT_REQUIRED).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from fastapi import WebSocket

from universal_brain.api.schemas import WebSocketEnvelope
from universal_brain.config import settings

logger = logging.getLogger(__name__)


class WebSocketGateway:
    """Manages active WebSocket connections, sequence numbers, and replay buffers."""

    def __init__(self, stream_id: Optional[str] = None, max_replay_buffer: int = 500) -> None:
        self.stream_id = stream_id or settings.system_id
        self.max_replay_buffer = max_replay_buffer
        self._sequence_counter: int = 0
        self._replay_buffer: List[WebSocketEnvelope] = []
        self._active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def current_sequence(self) -> int:
        return self._sequence_counter

    async def connect(self, websocket: WebSocket) -> None:
        """Register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self._active_connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a disconnected WebSocket."""
        async with self._lock:
            self._active_connections.discard(websocket)

    async def broadcast(
        self,
        channel: str,
        event_type: str,
        payload: Dict[str, Any],
        entity_version: int = 1,
        event_id: Optional[UUID] = None,
    ) -> WebSocketEnvelope:
        """
        Assigns sequential monotonic sequence ID, stores in replay buffer,
        and broadcasts to all active subscribers.
        """
        async with self._lock:
            self._sequence_counter += 1
            envelope = WebSocketEnvelope(
                stream_id=self.stream_id,
                sequence=self._sequence_counter,
                event_id=event_id or uuid4(),
                occurred_at=datetime.now(timezone.utc),
                entity_version=entity_version,
                channel=channel,
                event_type=event_type,
                payload=payload,
            )

            # Append to rolling replay buffer
            self._replay_buffer.append(envelope)
            if len(self._replay_buffer) > self.max_replay_buffer:
                self._replay_buffer.pop(0)

            # Broadcast to clients
            disconnected = []
            message_json = envelope.model_dump_json()

            for ws in self._active_connections:
                try:
                    await ws.send_text(message_json)
                except Exception:
                    disconnected.append(ws)

            for ws in disconnected:
                self._active_connections.discard(ws)

            return envelope

    def get_replay_events(self, last_confirmed_sequence: int) -> Optional[List[WebSocketEnvelope]]:
        """
        Determines if missed events can be replayed from buffer.
        Returns:
        - List of envelopes if gap can be bridged.
        - None if gap exceeds replay buffer (triggers SNAPSHOT_REQUIRED).
        """
        if not self._replay_buffer:
            if last_confirmed_sequence == self._sequence_counter:
                return []
            return None

        oldest_buffered_seq = self._replay_buffer[0].sequence

        # If client is already up-to-date
        if last_confirmed_sequence == self._sequence_counter:
            return []

        # If client's sequence is older than our oldest retained event, gap cannot be bridged
        if last_confirmed_sequence < oldest_buffered_seq - 1:
            return None

        # Extract delta
        return [e for e in self._replay_buffer if e.sequence > last_confirmed_sequence]
