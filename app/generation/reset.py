from __future__ import annotations

import re

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.core.config import get_settings

SAFE_DATABASE_NAME = re.compile(r"yottaflex(?:_dev|_test(?:_[a-z0-9]+)?)?\Z")
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def validate_destructive_target(database_url: str, environment: str, confirmed: bool) -> str:
    if not confirmed:
        raise PermissionError("Pass --confirm-destructive to rebuild a database.")
    if environment.lower() != "development":
        raise PermissionError("Destructive rebuild is restricted to ENVIRONMENT=development.")

    url = make_url(database_url)
    if url.host not in LOOPBACK_HOSTS:
        raise PermissionError("Destructive rebuild requires a loopback PostgreSQL host.")
    if not url.database or SAFE_DATABASE_NAME.fullmatch(url.database) is None:
        raise PermissionError("Database name is not on the local YottaFlex development allowlist.")
    if url.drivername != "postgresql+psycopg":
        raise PermissionError("Destructive rebuild requires the configured PostgreSQL driver.")
    return url.database


def rebuild_schema(database_name: str) -> None:
    settings = get_settings()
    if settings.database_url is None or make_url(settings.database_url).database != database_name:
        raise PermissionError("DATABASE_URL changed after destructive target validation.")
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")