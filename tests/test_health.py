from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


def test_health() -> None:
    application = create_app(Settings(app_name="test-api", environment="test", _env_file=None))

    with TestClient(application) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": "test-api",
        "environment": "test",
    }
