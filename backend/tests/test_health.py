from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health_returns_service_status() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Accessibility Repair Engine",
    }
