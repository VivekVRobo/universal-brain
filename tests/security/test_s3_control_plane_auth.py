"""S3 single-operator control-plane authentication regressions."""

from uuid import uuid4

from fastapi.testclient import TestClient

from universal_brain.api.app import app
from universal_brain.config import settings


def _auth_headers(token: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token or settings.operator_api_key}"}


def test_operator_api_rejects_missing_bearer_token():
    client = TestClient(app)
    response = client.get("/api/v1/runtime/health")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_operator_api_rejects_invalid_bearer_token():
    client = TestClient(app)
    response = client.get(
        "/api/v1/runtime/health",
        headers=_auth_headers("wrong-operator-token-that-is-definitely-not-valid"),
    )
    assert response.status_code == 401
    assert "Invalid operator bearer credential" in response.json()["detail"]


def test_operator_api_accepts_configured_bearer_token():
    client = TestClient(app)
    response = client.get("/api/v1/runtime/health", headers=_auth_headers())
    assert response.status_code == 200


def test_worker_registration_requires_operator_authentication():
    client = TestClient(app)
    payload = {
        "worker_id": f"auth-test-{uuid4()}",
        "worker_type": "test-worker",
        "capabilities": {"cpu": True},
    }
    denied = client.post("/api/v1/workers/register", json=payload)
    assert denied.status_code == 401

    allowed = client.post("/api/v1/workers/register", json=payload, headers=_auth_headers())
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "REGISTERED"
    assert allowed.json()["auth_token"]


def test_worker_progress_stays_on_worker_auth_boundary_not_operator_key():
    client = TestClient(app)
    response = client.post(
        "/api/v1/workers/progress",
        headers=_auth_headers(),
        json={
            "job_id": str(uuid4()),
            "worker_id": "not-a-real-worker",
            "lease_generation": 1,
            "sequence": 1,
            "progress_pct": 10.0,
        },
    )
    assert response.status_code == 401
    assert "Worker" in response.json()["detail"] or "token" in response.json()["detail"].lower()


def test_websocket_rejects_missing_operator_authentication():
    client = TestClient(app)
    try:
        with client.websocket_connect("/ws/stream"):
            raise AssertionError("unauthenticated WebSocket unexpectedly connected")
    except Exception as exc:
        code = getattr(exc, "code", None)
        assert code == 4401


def test_websocket_accepts_operator_token_and_ping():
    client = TestClient(app)
    with client.websocket_connect(f"/ws/stream?access_token={settings.operator_api_key}") as ws:
        ws.send_json({"action": "ping"})
        message = ws.receive_json()
        assert message["type"] == "PONG"
