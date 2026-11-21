"""Exercise the real local HTTP boundary, validation, and persisted installation status.

Depends on TestClient and isolated state; no Docker commands or browser automation run.
"""
from fastapi.testclient import TestClient
import pytest

from manager.api import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, watch_releases=False)
    with TestClient(app) as value:
        yield value


def test_serves_setup_and_health(client):
    assert client.get("/").status_code == 200
    assert "Cabek AI Manager" in client.get("/").text
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/app.js").status_code == 200


def test_saving_configuration_does_not_echo_secrets(client):
    response = client.put("/api/configuration", json={"github_token": "never-return-this-secret"})
    assert response.status_code == 200
    assert "never-return-this-secret" not in response.text
    assert response.json()["github_token_configured"]


def test_untrusted_origin_cannot_start_an_installation(client):
    response = client.post("/api/install", json={}, headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 403
    assert client.get("/api/status").json()["job"] is None


def test_form_posts_and_unknown_settings_are_rejected(client):
    assert client.post("/api/install", data={}).status_code == 415
    response = client.put("/api/configuration", json={"unknown": "secret-value", "github_token": "new-private-token"})
    assert response.status_code == 400
    assert "secret-value" not in response.text and "new-private-token" not in response.text


def test_new_installation_has_no_fabricated_versions(client):
    state = client.get("/api/status").json()
    assert state["installed"] == {}
    assert not state["updates"]["updates_available"]


def test_cannot_start_an_uninstalled_stack(client):
    assert client.post("/api/start", json={}).status_code == 400
