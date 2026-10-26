from collections.abc import Generator
from functools import lru_cache

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when an endpoint requires a database URL that is not configured."""


@lru_cache(maxsize=8)
def get_engine(database_url: str, connect_timeout_seconds: int) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": connect_timeout_seconds},
    )


@lru_cache(maxsize=8)
def get_session_factory(
    database_url: str,
    connect_timeout_seconds: int,
) -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(database_url, connect_timeout_seconds),
        autoflush=False,
        expire_on_commit=False,
    )


def get_db_session(request: Request) -> Generator[Session, None, None]:
    settings: Settings = request.app.state.settings
    if settings.database_url is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is required for database access.")

    factory = get_session_factory(
        settings.database_url,
        settings.database_connect_timeout_seconds,
    )
    with factory() as session:
        yield session