import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app

pytestmark = pytest.mark.integration


def test_readiness_connects_to_postgresql() -> None:
    settings = get_settings()
    if not settings.test_database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")

    application = create_app(
        settings.model_copy(update={"database_url": settings.test_database_url})
    )
    with TestClient(application) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}