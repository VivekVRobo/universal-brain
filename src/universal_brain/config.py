"""
Universal Brain - Global Configuration & Settings

Provides environment-based configuration using Pydantic Settings.
Enforces default fail-safe boundaries for budgets, paths, and secrets.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global system configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment & Identity
    app_env: str = Field("development", description="development | staging | production")
    system_id: str = Field("ub-local-node-01", description="Unique node identifier")
    debug: bool = Field(False, description="Debug mode")

    # Storage & Database
    database_url: str = Field(
        "postgresql+asyncpg://brain_admin:brain_dev_password@localhost:5432/universal_brain",
        description="Async PostgreSQL connection URI",
    )
    data_dir: Path = Field(Path("./data"), description="Base local data directory")
    journal_dir: Path = Field(Path("./data/journal"), description="Local micro-batch journal buffer")
    evidence_dir: Path = Field(Path("./data/evidence"), description="Visual & cryptographic evidence directory")

    # Cost Control & Budget Ceilings
    global_monthly_budget_usd: float = Field(20.00, description="Global monthly spending limit in USD")
    per_task_budget_cap_usd: float = Field(1.00, description="Maximum single-task spending cap in USD")
    soft_warning_threshold_pct: float = Field(0.70, description="70% warning threshold")
    downgrade_threshold_pct: float = Field(0.85, description="85% model downgrade threshold")

    # Security & Tokens
    hmac_secret_key: str = Field(
        "dev-secret-key-change-in-production-min-32-chars-long",
        description="Secret key for signing capability tokens",
        min_length=32,
    )
    capability_token_ttl_seconds: int = Field(3600, description="Default capability token TTL (1 hour)")

    # Out-of-Band Alerting (Optional in Dev)
    telegram_bot_token: Optional[str] = Field(None, description="Telegram Bot API Token")
    telegram_admin_chat_id: Optional[str] = Field(None, description="Admin Chat ID for critical alerts")
    telegram_cold_channel_id: Optional[str] = Field(None, description="Tertiary Cold Storage Channel ID")

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Settings:
        """Enforces Gate S1 secret guardrail: reject development keys outside development mode."""
        if self.app_env in ("production", "staging"):
            if "dev-secret" in self.hmac_secret_key.lower():
                raise ValueError(
                    f"FATAL: In '{self.app_env}' mode, hmac_secret_key must be an externally configured secret, "
                    "not the default development key."
                )
            if "brain_dev_password" in self.database_url:
                raise ValueError(
                    f"FATAL: In '{self.app_env}' mode, database_url must not contain default development credentials ('brain_dev_password')."
                )
            if len(self.hmac_secret_key) < 32:
                raise ValueError("hmac_secret_key must be at least 32 characters in production.")
        return self


# Global singleton instance
settings = Settings()
