"""
Universal Brain - Storage Lifecycle Management & Retention Policy

Implements MEMORY_ARCHITECTURE.md (Section 5) and REQ-STA-009.
Enforces 3-tier lifecycle policies (Hot, Cold, Deep Archive) and disk
utilization safety gates (80% warning alert, 90% fail-closed pause).
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field

from universal_brain.kernel.errors import HealthGateError


class StorageTier(str, Enum):
    """Lifecycle retention storage tiers."""

    HOT = "HOT"                  # 0 - 30 days (Local SSD / VM)
    COLD = "COLD"                # 30 - 90 days (Google Drive / R2 compressed archives)
    DEEP_ARCHIVE = "DEEP_ARCHIVE" # > 90 days (Telegram Channel / Backblaze B2)


class DiskStatus(BaseModel):
    """Host disk capacity metrics."""

    total_bytes: int
    used_bytes: int
    free_bytes: int
    utilization_pct: float = Field(..., ge=0.0, le=100.0)
    is_warning: bool = False  # >= 80%
    is_critical: bool = False # >= 90%


class StorageRetentionManager:
    """Evaluates disk utilization gates and governs artifact age classification."""

    def __init__(
        self,
        monitored_path: Optional[Path] = None,
        warning_threshold_pct: float = 80.0,
        critical_threshold_pct: float = 90.0,
        disk_usage_provider: Optional[Callable[[Path], object]] = None,
    ) -> None:
        self.path = monitored_path or Path(".")
        self.warning_threshold_pct = warning_threshold_pct
        self.critical_threshold_pct = critical_threshold_pct
        self.disk_usage_provider = disk_usage_provider or shutil.disk_usage

    def check_disk_capacity(self) -> DiskStatus:
        """
        Inspects host storage.
        Enforces warning gate and fail-closed pause gate.
        """
        usage = self.disk_usage_provider(self.path)
        utilization = (usage.used / usage.total) * 100.0

        is_warning = utilization >= self.warning_threshold_pct
        is_critical = utilization >= self.critical_threshold_pct

        return DiskStatus(
            total_bytes=usage.total,
            used_bytes=usage.used,
            free_bytes=usage.free,
            utilization_pct=round(utilization, 2),
            is_warning=is_warning,
            is_critical=is_critical,
        )

    def assert_write_permitted(self, action_class_name: str) -> None:
        """
        Enforces ALN-014 fail-closed gate: If disk utilization >= 90%,
        all state-changing A1 and A2 writes are blocked.
        """
        status = self.check_disk_capacity()
        if status.is_critical and action_class_name != "A0":
            raise HealthGateError(
                f"Disk utilization is critical ({status.utilization_pct:.1f}% >= 90.0%). "
                f"State-changing action '{action_class_name}' is halted to prevent filesystem corruption."
            )

    @staticmethod
    def classify_artifact_age(file_created_at: datetime, current_time: Optional[datetime] = None) -> StorageTier:
        """Categorizes an artifact into Hot, Cold, or Deep Archive based on age."""
        now = current_time or datetime.now(timezone.utc)
        age = now - file_created_at

        if age <= timedelta(days=30):
            return StorageTier.HOT
        if age <= timedelta(days=90):
            return StorageTier.COLD
        return StorageTier.DEEP_ARCHIVE
