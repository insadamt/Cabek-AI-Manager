"""Verify automatic configuration and credential persistence across repeated setup.

Depends on temporary private state, never real workstation credentials or hardware.
"""
import stat
import pytest

from manager.configuration import Configuration, SiteConfig
from manager.storage import Store
from manager.compose import render_compose
from manager.catalog import enabled_components


def test_setup_preserves_and_never_returns_secrets(tmp_path):
    store = Store(tmp_path)
    configuration = Configuration(store)
    configuration.save({"github_token": "private-test-token", "nvr_password": "private-camera-password"})
    original = configuration.credentials()
    configuration.save({"github_token": "", "nvr_password": "", "app_port": 8280})
    assert configuration.load().github_token == "private-test-token"
    assert configuration.credentials() == original
    public = configuration.public()
    assert "github_token" not in public and "nvr_password" not in public
    assert public["github_token_configured"] is True
    assert stat.S_IMODE((tmp_path / "configuration.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("changes", [{"app_port": 8181}, {"profile": "unknown"},
                                       {"profile": "station"}, {"camera_channels": [1, 1]},
                                       {"dataset_paths": ["relative.zip"]}, {"lighting_enabled": True}])
def test_rejects_incomplete_or_conflicting_configuration(changes):
    with pytest.raises(ValueError):
        SiteConfig(**changes)


def test_compose_connects_programs_and_excludes_unwanted_frontends(tmp_path):
    config = SiteConfig()
    credentials = Configuration(Store(tmp_path)).credentials()
    components = enabled_components(config)
    revisions = {item.key: {"tag": "v0.1.0", "sha": "a" * 40} for item in components}
    compose = render_compose(tmp_path, config, credentials, revisions)
    services = compose["services"]
    assert set(services) == {"database", "pricing", "pricing-web", "backend", "frontend", "ocr"}
    assert services["backend"]["environment"]["AUTOESTIMATE_BASE_URL"] == "http://pricing-web/api/v1"
    assert services["backend"]["environment"]["CABEK_ECONSTAT_API_TOKEN"] == services["ocr"]["environment"]["ECONSTAT_API_TOKEN"]
    assert "ports" not in services["database"]
    assert services["database"]["volumes"] == ["pricing_database:/var/lib/mysql"]


def test_process_lock_rejects_second_mutation(tmp_path):
    first, second = Store(tmp_path), Store(tmp_path)
    with first.operation_lock():
        with pytest.raises(ValueError, match="Another"):
            with second.operation_lock():
                pass


def test_scraper_is_excluded_from_installation_and_legacy_settings(tmp_path):
    store = Store(tmp_path)
    store.write('configuration', {'scraper_enabled': True})
    configuration = Configuration(store)
    assert all(item.key != 'scraper' for item in enabled_components(configuration.load()))
    assert 'scraper_enabled' not in configuration.public()
    configuration.save({'app_port': 8280})
    assert 'scraper_enabled' not in store.read('configuration')
