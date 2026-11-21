"""Verify update selection and failure barriers around real orchestration entry points.

Depends on mocked external boundaries. Missing releases must stop installation
before Docker changes, and failed builds must leave the current stack untouched.
"""
from pathlib import Path
import pytest

from manager.configuration import Configuration
from manager.orchestrator import Orchestrator
from manager.releases import GitHub
from manager.storage import Store


def revision(tag="v1.0.0", sha="a" * 40):
    return {"tag": tag, "sha": sha, "url": "https://github.com/test/releases/1", "release_id": 1,
            "published_at": "2026-11-21", "notes": ""}


def test_published_updates_are_compared_per_component(tmp_path, monkeypatch):
    store = Store(tmp_path)
    orchestrator = Orchestrator(store, Configuration(store))
    store.write("installed", {"backend": revision(), "frontend": revision("v2.0.0")})
    monkeypatch.setattr(GitHub, "latest", lambda self, repo: revision("v1.1.0", "b" * 40))
    result = orchestrator.check_updates()
    items = {item["key"]: item for item in result["components"]}
    assert items["backend"]["update_available"]
    assert not items["frontend"]["update_available"]


def test_retagged_version_is_not_silently_installed(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.write("installed", {"backend": revision()})
    monkeypatch.setattr(GitHub, "latest", lambda self, repo: revision(sha="b" * 40))
    item = next(item for item in Orchestrator(store, Configuration(store)).check_updates()["components"] if item["key"] == "backend")
    assert "changed its revision" in item["error"]
    assert not item["update_available"]


def test_missing_release_stops_before_source_download_or_docker(tmp_path, monkeypatch):
    store = Store(tmp_path)
    orchestrator = Orchestrator(store, Configuration(store))
    monkeypatch.setattr("manager.orchestrator.preflight", lambda *args: {"ready": True})
    monkeypatch.setattr("manager.orchestrator.require_free_ports", lambda *args: None)
    def missing(*args):
        raise ValueError("No published stable release is available.")
    monkeypatch.setattr(GitHub, "latest", missing)
    monkeypatch.setattr(GitHub, "download", lambda *args: pytest.fail("Must not download without a release"))
    with pytest.raises(ValueError, match="No published stable"):
        orchestrator.install(lambda message: None)
    assert not (tmp_path / "compose.json").exists()


def test_failed_build_does_not_enter_maintenance_or_replace_installed_state(tmp_path, monkeypatch):
    store = Store(tmp_path)
    configuration = Configuration(store)
    orchestrator = Orchestrator(store, configuration)
    original = {key: revision() for key in ("backend", "frontend", "autoestimate", "ocr")}
    store.write("installed", original)
    store.write("compose", {"name": "old-installation"})
    monkeypatch.setattr("manager.orchestrator.preflight", lambda *args: {"ready": True})
    monkeypatch.setattr(GitHub, "latest", lambda *args: revision("v1.1.0", "b" * 40))
    def download(self, repository, sha, destination):
        destination.mkdir(parents=True)
        (destination / "Dockerfile").write_text("FROM scratch\n")
    monkeypatch.setattr(GitHub, "download", download)
    def run(self, arguments, **kwargs):
        if arguments[-1] == "build":
            raise RuntimeError("Build failed")
        return ""
    monkeypatch.setattr("manager.commands.CommandRunner.run", run)
    monkeypatch.setattr("manager.orchestrator.drain", lambda *args: pytest.fail("Build failure must not drain"))
    with pytest.raises(RuntimeError, match="Build failed"):
        orchestrator.update_all(lambda message: None)
    assert store.read("compose") == {"name": "old-installation"}
    assert store.read("installed") == original
