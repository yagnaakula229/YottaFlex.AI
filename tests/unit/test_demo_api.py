import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.unit


def test_demo_summary_returns_synthetic_dashboard_payload() -> None:
    application = create_app(Settings(_env_file=None))

    with TestClient(application) as client:
        response = client.get("/api/demo/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "synthetic-demo"
    assert payload["synthetic"] is True
    assert payload["backend_health"]["live"] == "live"
    assert "recovery_candidates" in payload
