"""Guard rootless Docker mounts, Python health checks and deployment ordering.

These tests use mocked Docker boundaries; real rootless deployment remains a
separate station-level acceptance requirement.
"""
import os
import shlex

import pytest

from manager.catalog import enabled_components
from manager.compose import python_health, render_compose
from manager.configuration import Configuration, SiteConfig
from manager.orchestrator import Orchestrator
from manager.releases import GitHub
from manager.storage import Store
from manager.system import docker_is_rootless


class SecurityOptionsRunner:
    def __init__(self, value):
        self.value = value

    def run(self, command, **kwargs):
        assert command == ["docker", "info", "--format", "{{json .SecurityOptions}}"]
        return self.value


def test_docker_mode_is_taken_from_daemon_security_options():
    assert docker_is_rootless(SecurityOptionsRunner('["name=apparmor","name=seccomp,profile=default","name=rootless"]'))
    assert not docker_is_rootless(SecurityOptionsRunner('["name=apparmor","name=seccomp,profile=default"]'))
    with pytest.raises(RuntimeError, match="invalid security options"):
        docker_is_rootless(SecurityOptionsRunner("not-json"))


def test_python_healthcheck_preserves_entire_program_as_one_argument():
    code = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8008/_manager/health',timeout=3)"
    test = python_health(code)["test"]
    assert test[0] == "CMD-SHELL"
    assert shlex.split(test[1]) == ["python", "-c", code]


def test_rootless_render_uses_namespace_root_for_host_writable_services(tmp_path):
    config = SiteConfig()
    credentials = Configuration(Store(tmp_path)).ensure_credentials()
    revisions = {item.key: {"sha": "a" * 40} for item in enabled_components()}
    rootless = render_compose(tmp_path, config, credentials, revisions, rootless=True)
    rootful = render_compose(tmp_path, config, credentials, revisions, rootless=False)
    for name in ("gateway", "backend", "ocr", "cameras", "lighting"):
        assert rootless["services"][name]["user"] == "0:0"
        assert rootful["services"][name]["user"] == f"{os.getuid()}:{os.getgid()}"
    assert rootless["services"]["ocr"]["volumes"][0].endswith(":/models")
    assert rootless["services"]["ocr"]["volumes"][1].endswith(":/app/output")
    assert rootless["services"]["backend"]["volumes"][2].endswith(":/data/private-demo")
    for name in ("gateway", "backend", "ocr", "cameras"):
        assert rootless["services"][name]["healthcheck"]["test"][0] == "CMD-SHELL"


def test_first_install_removes_stale_containers_before_starting_database(tmp_path, monkeypatch):
    store = Store(tmp_path)
    configuration = Configuration(store)
    configuration.save({"nvr_host": "192.0.2.1", "nvr_password": "test-password",
                        "interior_url": "http://192.0.2.2"})
    # Simulate remnants from a failed install; no installed revision is recorded.
    store.write("compose", {"name": "cabek-ai-manager", "services": {"gateway": {}}})
    commands = []

    def run(self, command, **kwargs):
        commands.append(command)
        if command[:3] == ["docker", "info", "--format"]:
            return '["name=rootless"]'
        return ""

    def download(self, repository, sha, destination):
        destination.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("manager.orchestrator.preflight", lambda *args: {"ready": True})
    monkeypatch.setattr("manager.orchestrator.require_free_ports", lambda *args: None)
    monkeypatch.setattr(GitHub, "latest",
                        lambda *args: {"tag": "v1.0.0", "sha": "a" * 40, "url": "", "release_id": 1,
                                       "published_at": "2026-11-23", "notes": ""})
    monkeypatch.setattr(GitHub, "download", download)
    monkeypatch.setattr("manager.commands.CommandRunner.run", run)
    monkeypatch.setattr("manager.orchestrator.prepare_manager", lambda *args: None)
    monkeypatch.setattr("manager.orchestrator.provision_pricing", lambda *args: None)
    monkeypatch.setattr("manager.orchestrator.initialize_storage", lambda *args, **kwargs: None)
    monkeypatch.setattr("manager.orchestrator.request_native", lambda *args: {})
    monkeypatch.setattr("manager.orchestrator.resume", lambda *args: None)
    monkeypatch.setattr("manager.serial_devices.device_signature", lambda *args: None)

    Orchestrator(store, configuration).install(lambda message: None)

    removal = next(i for i, c in enumerate(commands) if "rm" in c and c[-1] == "gateway")
    db = next(i for i, c in enumerate(commands) if c[-1] == "database" and "up" in c)
    full = next(i for i, c in enumerate(commands) if "up" in c and "300" in c)
    assert removal < db < full
    assert not any('down' in command for command in commands)
    assert '--no-recreate' in commands[db]
    assert "--force-recreate" not in commands[full]
    assert store.read("compose")["services"]["ocr"]["user"] == "0:0"
    assert store.read("installed")["manager"]["tag"] == "v1.0.0"
