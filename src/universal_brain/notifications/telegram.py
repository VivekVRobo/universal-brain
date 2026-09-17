"""
Universal Brain - Out-of-Band Telegram Alert Service

Implements FREE_CLOUD_ORCHESTRATION.md (Section 4) and ADR-0007.
Dispatches critical push notifications to the operator's mobile device for:
- A2 Action Approval Requests (with 6-hour dead-man's countdown);
- System Health & Invariant Failures (ALN-014);
- Budget Utilization Warnings (70% and 85%);
- Storage Warnings (80% warning, 90% action pause).
"""

from __future__ import annotations

import logging
from typing import Optional
import httpx

from universal_brain.config import settings

logger = logging.getLogger(__name__)


class TelegramAlertService:
    """Out-of-band push alert dispatcher."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        admin_chat_id: Optional[str] = None,
    ) -> None:
        self.bot_token = bot_token or settings.telegram_bot_token
        self.chat_id = admin_chat_id or settings.telegram_admin_chat_id
        self.is_configured = bool(self.bot_token and self.chat_id)

    async def send_alert(self, message: str, level: str = "INFO") -> bool:
        """
        Dispatches an alert message to the operator.
        In local/dev mode without credentials, logs to stderr safely.
        """
        prefix = {
            "INFO": "ℹ️ [Universal Brain]",
            "WARNING": "⚠️ [Universal Brain Warning]",
            "CRITICAL": "🚨 [Universal Brain CRITICAL]",
            "A2_APPROVAL": "🛑 [ACTION APPROVAL REQUIRED - A2]",
        }.get(level, "📢 [Universal Brain]")

        formatted_text = f"{prefix}\n\n{message}"

        if not self.is_configured:
            logger.info("Telegram not configured. Local alert: %s", formatted_text)
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": formatted_text,
            "parse_mode": "Markdown",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
        except Exception as e:
            logger.error("Failed to deliver Telegram alert: %s", e)
            return False
