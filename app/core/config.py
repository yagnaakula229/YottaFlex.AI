import logging
from datetime import UTC, datetime

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
    scenario_as_of: datetime = datetime(2026, 10, 22, tzinfo=UTC)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    @field_validator("database_url", "test_database_url")
    @classmethod
    def validate_database_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None

        try:
            url = make_url(value)
        except ArgumentError as exc:
            raise ValueError("Database URLs must be valid PostgreSQL URLs.") from exc

        if url.drivername != "postgresql+psycopg":
            raise ValueError("Database URLs must use the postgresql+psycopg driver.")

        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError("LOG_LEVEL must be a recognized Python logging level.")
        return normalized


def get_settings() -> Settings:
    return Settings()