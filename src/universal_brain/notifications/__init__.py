"""Notifications subsystem for Universal Brain (Out-of-band mobile alerts)."""
from .telegram import TelegramAlertService

__all__ = [
    "TelegramAlertService",
]
