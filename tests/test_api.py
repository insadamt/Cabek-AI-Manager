"""Exercise the real local HTTP boundary, validation, and persisted installation status.

Depends on TestClient and isolated state; no Docker commands or browser automation run.
"""
from fastapi.testclient import TestClient
import pytest
import time

from manager.api import create_app
from manager.configuration import SiteConfig


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


def test_pending_port_change_keeps_open_and_resume_on_installed_services(tmp_path, monkeypatch):
    app = create_app(tmp_path, watch_releases=False)
    app.state.store.write("installed-configuration", SiteConfig().model_dump())
    calls = []
    monkeypatch.setattr("manager.api.request_backend", lambda config, *args: calls.append(config.api_port) or {"maintenance": False})
    with TestClient(app) as client:
        assert client.put("/api/configuration", json={"app_port": 8380, "api_port": 8381}).status_code == 200
        status = client.get("/api/status").json()
        assert status["configuration_pending"]
        assert status["application_url"] == "http://localhost:8180"
        assert client.post("/api/resume", json={}).status_code == 200
    assert calls == [8181]


def test_pending_port_change_stops_the_installed_backend(tmp_path, monkeypatch):
    app = create_app(tmp_path, watch_releases=False)
    app.state.store.write("installed-configuration", SiteConfig().model_dump())
    ports = []
    commands = []
    monkeypatch.setattr("manager.backend.drain", lambda config, *args: ports.append(config.api_port))
    monkeypatch.setattr("manager.commands.CommandRunner.run", lambda self, arguments, **kwargs: commands.append(arguments) or "")
    with TestClient(app) as client:
        client.put("/api/configuration", json={"api_port": 8381})
        assert client.post("/api/stop", json={}).status_code == 200
        deadline = time.monotonic() + 2
        while app.state.jobs.snapshot()["status"] == "running" and time.monotonic() < deadline:
            time.sleep(.01)
        assert app.state.jobs.snapshot()["status"] == "completed"
    assert ports == [8181]
    assert commands[0][-1] == "stop"
