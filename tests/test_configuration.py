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
    original = configuration.ensure_credentials()
    configuration.save({"github_token": "", "nvr_password": "", "app_port": 8280})
    assert configuration.load().github_token == "private-test-token"
    assert configuration.ensure_credentials() == original
    public = configuration.public()
    assert "github_token" not in public and "nvr_password" not in public
    assert public["github_token_configured"] is True
    assert stat.S_IMODE((tmp_path / "configuration.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("changes", [{"app_port": 8181}, {"profile": "unknown"},
                                       {"camera_channels": [1, 2]}, {"camera_channels": [1, 1]},
                                       {"dataset_paths": ["relative.zip"]}, {"lighting_enabled": True}])
def test_rejects_incomplete_or_conflicting_configuration(changes):
    with pytest.raises(ValueError):
        SiteConfig(**changes)


def test_compose_connects_programs_and_excludes_unwanted_frontends(tmp_path):
    config = SiteConfig()
    credentials = Configuration(Store(tmp_path)).ensure_credentials()
    components = enabled_components(config)
    revisions = {item.key: {"tag": "v0.1.0", "sha": "a" * 40} for item in components}
    compose = render_compose(tmp_path, config, credentials, revisions)
    services = compose["services"]
    assert set(services) == {"gateway", "database", "pricing", "pricing-web", "backend", "frontend", "cameras", "lighting", "ocr"}
    assert services["backend"]["environment"]["AUTOESTIMATE_BASE_URL"] == "http://pricing-web/api/v1"
    assert services["backend"]["environment"]["CABEK_ECONSTAT_API_TOKEN"] == services["ocr"]["environment"]["ECONSTAT_API_TOKEN"]
    assert "ports" not in services["database"]
    assert services["database"]["volumes"] == ["pricing_database:/var/lib/mysql"]
    import os
    assert services['backend']['user'] == f'{os.getuid()}:{os.getgid()}'


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


def test_nvr_password_dollar_signs_are_escaped_for_compose(tmp_path):
    config = SiteConfig(nvr_host='192.0.2.1', nvr_password='my$literal$password')
    credentials = Configuration(Store(tmp_path)).ensure_credentials()
    revisions = {item.key: {'sha': 'a' * 40} for item in enabled_components(config)}
    compose = render_compose(tmp_path, config, credentials, revisions)
    assert compose['services']['cameras']['environment']['RTSP_PASSWORD'] == 'my$$literal$$password'


def test_every_application_is_mandatory_and_legacy_switches_are_removed(tmp_path):
    store = Store(tmp_path)
    store.write('configuration', {'profile': 'demo', 'lighting_enabled': False, 'ocr_enabled': False})
    configuration = Configuration(store)
    assert len(enabled_components(configuration.load())) == 7
    assert not {'profile', 'lighting_enabled', 'ocr_enabled', 'interior_enabled'} & configuration.public().keys()
    configuration.save({})
    assert 'profile' not in store.read('configuration')


def test_disconnected_serial_device_is_a_valid_station_setting():
    assert SiteConfig(serial_device='/dev/serial/by-id/disconnected').serial_device.endswith('disconnected')


def test_frontend_configuration_changes_image_identity_without_editing_sources(tmp_path):
    credentials = Configuration(Store(tmp_path)).ensure_credentials()
    revisions = {item.key: {'sha': 'a' * 40} for item in enabled_components()}
    first = render_compose(tmp_path, SiteConfig(), credentials, revisions)
    second = render_compose(tmp_path, SiteConfig(app_port=8280), credentials, revisions)
    assert first['services']['frontend']['image'] != second['services']['frontend']['image']
    assert first['services']['backend']['image'] == second['services']['backend']['image']
    assert first['services']['backend']['network_mode'] == 'service:gateway'
    assert first['services']['backend']['environment']['CABEK_TUNNEL_MODE'] == 'tiandy'
    assert 'CABEK_MANAGER_KEY' not in first['services']['backend']['environment']
    assert first['services']['ocr']['volumes'][1].endswith(':/app/output')


def test_import_preserves_native_tuning_privately_and_manager_resolves_wiring(tmp_path):
    station=tmp_path/'station'
    (station/'Tiandy_CABEK_API').mkdir(parents=True)
    (station/'Tiandy_CABEK_API/.env').write_text('NVR_IP=192.0.2.1\nRTSP_USER=operator\nRTSP_PASSWORD=private-import\nRTSP_STREAM=1\nAPI_PORT=9999\nPYTHONPATH=untrusted\n')
    configuration=Configuration(Store(tmp_path/'private'))
    public=configuration.import_existing(str(station))
    assert 'native_environment' not in public and 'private-import' not in str(public)
    config=configuration.load()
    revisions={item.key:{'sha':'a'*40} for item in enabled_components()}
    rendered=render_compose(tmp_path,config,configuration.ensure_credentials(),revisions)
    camera_env=rendered['services']['cameras']['environment']
    assert camera_env['RTSP_STREAM']=='1'
    assert camera_env['API_PORT']=='8001'
    assert 'PYTHONPATH' not in camera_env
