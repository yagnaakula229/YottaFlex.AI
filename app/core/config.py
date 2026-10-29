import logging
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "YottaFlex AI"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str | None = None
    test_database_url: str | None = None
    cors_allow_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )
    scenario_as_of: datetime = datetime(2026, 10, 22, tzinfo=UTC)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    recovery_policy_version: str = "recovery-v1-provisional"
    abandoned_cart_inactivity_minutes: int = Field(default=60, ge=1)
    recovery_qualifying_cart_event_types: tuple[str, ...] = (
        "cart_created",
        "cart_activity",
        "cart_line_added",
        "cart_line_updated",
        "cart_line_removed",
    )
    recovery_purchase_blocking_statuses: tuple[str, ...] = ("pending", "paid", "refunded")
    recovery_frequency_cap_24h: int = Field(default=1, ge=0)
    recovery_frequency_cap_7d: int = Field(default=3, ge=0)
    recovery_qualifying_attempt_states: tuple[str, ...] = ("accepted",)
    recovery_rolling_window_boundary: Literal["(lower, upper]", "[lower, upper]"] = "(lower, upper]"
    recovery_conversion_window_days: int = Field(default=7, ge=1)
    recovery_campaign_selection_policy: Literal["campaign-id-priority-template-id-v1"] = (
        "campaign-id-priority-template-id-v1"
    )
    recovery_use_cart_updated_at_fallback: bool = True
    recovery_policy_version: str = "recovery-v1-provisional"
    abandoned_cart_inactivity_minutes: int = Field(default=60, ge=1)
    recovery_qualifying_cart_event_types: tuple[str, ...] = (
        "cart_created",
        "cart_activity",
        "cart_line_added",
        "cart_line_updated",
        "cart_line_removed",
    )
    recovery_purchase_blocking_statuses: tuple[str, ...] = ("pending", "paid", "refunded")
    recovery_frequency_cap_24h: int = Field(default=1, ge=0)
    recovery_frequency_cap_7d: int = Field(default=3, ge=0)
    recovery_qualifying_attempt_states: tuple[str, ...] = ("accepted",)
    recovery_conversion_window_days: int = Field(default=7, ge=1)
    recovery_campaign_selection_policy: Literal["campaign-id-priority-template-id-v1"] = (
        "campaign-id-priority-template-id-v1"
    )
    recovery_use_cart_updated_at_fallback: bool = True

    @staticmethod
    def _is_placeholder_database_url(value: str) -> bool:
        upper_value = value.upper()
        placeholder_tokens = ("USER", "PASSWORD", "DB_NAME", "DB_NAME_TEST")
        return any(token in upper_value for token in placeholder_tokens)

    @field_validator("database_url", "test_database_url")
    @classmethod
    def validate_database_url(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None

        normalized = str(value).strip()
        if cls._is_placeholder_database_url(normalized):
            return None

        try:
            url = make_url(normalized)
        except ArgumentError as exc:
            raise ValueError("Database URLs must be valid PostgreSQL URLs.") from exc

        if url.drivername != "postgresql+psycopg":
            raise ValueError("Database URLs must use the postgresql+psycopg driver.")

        return normalized

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError("LOG_LEVEL must be a recognized Python logging level.")
        return normalized


def get_settings() -> Settings:
    return Settings()