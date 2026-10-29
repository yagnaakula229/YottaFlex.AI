import logging
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db_session
from app.main import create_app

pytestmark = pytest.mark.unit


def test_application_starts_and_liveness_is_independent_of_database() -> None:
    application = create_app(Settings(_env_file=None))

    with TestClient(application) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_readiness_executes_database_probe() -> None:
    application = create_app(
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://user:pass@localhost/db",
        )
    )
    session = Mock(spec=Session)

    def override_session():
        yield session

    application.dependency_overrides[get_db_session] = override_session
    with TestClient(application) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    session.execute.assert_called_once()


def test_readiness_reports_missing_database_configuration() -> None:
    application = create_app(Settings(_env_file=None, database_url=None))

    with TestClient(application) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not configured"}


def test_database_url_must_use_psycopg_postgresql_driver() -> None:
    with pytest.raises(ValueError, match=r"postgresql\+psycopg"):
        Settings(_env_file=None, database_url="sqlite:///not-postgresql.db")


def test_placeholder_database_urls_are_treated_as_unconfigured() -> None:
    assert Settings(_env_file=None, database_url="postgresql+psycopg://USER:PASSWORD@localhost:5432/DB_NAME") is not None
    assert Settings(_env_file=None, database_url="postgresql+psycopg://USER:PASSWORD@localhost:5432/DB_NAME") == Settings(_env_file=None, database_url=None)


def test_json_formatter_includes_structured_fields() -> None:
    from app.core.logging import JsonFormatter

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="probe",
        args=(),
        exc_info=None,
    )
    record.event = "test_event"

    formatted = JsonFormatter().format(record)

    assert '"message": "probe"' in formatted
    assert '"event": "test_event"' in formatted


def test_readiness_returns_503_when_postgresql_connection_fails() -> None:
    from app.db.session import get_engine, get_session_factory

    database_url = "postgresql+psycopg://invalid:invalid@127.0.0.1:1/unavailable"
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        database_connect_timeout_seconds=1,
    )
    get_session_factory.cache_clear()
    get_engine.cache_clear()

    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")

    get_session_factory.cache_clear()
    get_engine.cache_clear()
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not ready"}