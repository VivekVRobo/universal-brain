"""
Universal Brain - Transactional Outbox Dispatcher

Implements M6 Sections 18-21, 53-57, and Invariant M6-INV-07:
Asynchronously claims pending outbox records committed with domain events
and dispatches them to registered listeners with at-least-once delivery guarantees.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List
from uuid import UUID

from universal_brain.persistence.engine import DatabaseManager
from universal_brain.persistence.unit_of_work import UnitOfWork

OutboxHandler = Callable[[str, Dict[str, Any]], Awaitable[None]]


class TransactionalOutboxDispatcher:
    """Dispatches staged outbox events to registered delivery subscribers."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager
        self._handlers: Dict[str, List[OutboxHandler]] = {}

    def register_handler(self, topic: str, handler: OutboxHandler) -> None:
        """Registers a consumer callback for a specific topic (or '*' for all)."""
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)

    async def dispatch_pending_batch(self, batch_size: int = 50, max_retries: int = 5) -> int:
        """
        Polls, claims, and delivers up to batch_size outbox records.
        Returns the number of records successfully delivered or handled.
        """
        async with UnitOfWork(self.db_manager) as uow:
            records = await uow.outbox.claim_pending(batch_size=batch_size)
            if not records:
                return 0

            for rec in records:
                # Find matching handlers (exact topic or wildcard '*')
                handlers = self._handlers.get(rec.topic, []) + self._handlers.get("*", [])

                if not handlers:
                    # No subscribers registered; mark delivered
                    await uow.outbox.mark_delivered(rec.outbox_id)
                    continue

                all_ok = True
                last_err = ""
                for h in handlers:
                    try:
                        await h(rec.topic, rec.payload)
                    except Exception as e:
                        all_ok = False
                        last_err = str(e)

                if all_ok:
                    await uow.outbox.mark_delivered(rec.outbox_id)
                else:
                    await uow.outbox.mark_failed(rec.outbox_id, error=last_err, max_retries=max_retries)

            await uow.commit()
            return len(records)
