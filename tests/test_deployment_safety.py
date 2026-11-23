"""Regress deployment ordering, validated backups and disconnected diagnostics.

Depends on real temporary files and mocked Docker boundaries; the opt-in Docker
suite separately exercises these same lifecycle helpers against actual containers.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from manager.backups import create_backup, restore_backup, validate_backup
from manager.configuration import Configuration, SiteConfig
from manager.lifecycle import remove_application_containers, start_database, start_applications
from manager.readiness import hardware_readiness
from manager.runtime_storage import prepare_directories
from manager.storage import Store
from manager.system import docker_is_rootless


class RecordingRunner:
    def __init__(self):
        self.commands = []

    def run(self, args, **kwargs):
        self.commands.append(args)
        if kwargs.get('output_path'):
            kwargs['output_path'].write_text('SELECT 1;')
        return ''


def test_namespace_consumers_are_removed_before_gateway_and_database_is_retained(tmp_path):
    store = Store(tmp_path)
    store.write('compose', {'name': 'cabek-test', 'services': {
        name: {} for name in ('database', 'gateway', 'backend', 'ocr', 'frontend', 'pricing')}})
    runner = RecordingRunner()
    remove_application_containers(store, runner)
    removals = [command for command in runner.commands if 'rm' in command]
    assert set(removals[0][9:]) == {'backend', 'ocr', 'frontend', 'pricing'}
    assert removals[1][-1] == 'gateway'
    assert all('database' not in command and 'down' not in command for command in runner.commands)
    start_database(store, runner)
    assert '--no-recreate' in runner.commands[-1]
    start_applications(store, runner)
    assert all('database' not in command for command in runner.commands[4:])


def test_empty_daemon_mode_fails_closed():
    with pytest.raises(RuntimeError, match='empty security options'):
        docker_is_rootless(RecordingRunner())


def test_runtime_roots_are_private_and_symlinks_are_rejected(tmp_path):
    config = SiteConfig(data_directory=str(tmp_path / 'custom'))
    prepare_directories(tmp_path, config)
    assert (tmp_path / 'custom/private-demo').stat().st_mode & 0o777 == 0o700
    (tmp_path / 'custom/dossiers').rmdir()
    (tmp_path / 'custom/dossiers').symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError, match='symlinks'):
        prepare_directories(tmp_path, config)


def test_camera_outage_does_not_crash_hardware_status(monkeypatch):
    monkeypatch.setattr('manager.network_diagnostics.network_readiness', lambda host: {})
    def disconnected(*args):
        raise OSError('disconnected')
    monkeypatch.setattr('manager.readiness.request_native', disconnected)
    checks = hardware_readiness(SiteConfig())
    assert next(c for c in checks if c.get('name') == 'NVR cameras')['state'] == 'disconnected'


def test_backup_preserves_models_and_validates_before_any_docker_or_sql_mutation(tmp_path):
    store = Store(tmp_path / 'manager')
    config = SiteConfig(data_directory=str(tmp_path / 'custom'))
    Configuration(store).save(config.model_dump())
    store.write('installed-configuration', config.model_dump())
    store.write('compose', {'name': 'cabek-test', 'services': {}})
    prepare_directories(store.root, config)
    model = Path(config.data_directory) / 'ocr-models/model/cached.pth'
    model.parent.mkdir()
    model.write_bytes(b'existing-model')
    runner = RecordingRunner()
    backup = create_backup(store, runner, lambda message: None)
    model.write_bytes(b'changed-model')
    (backup / 'database.sql').write_text('corruption')
    runner.commands.clear()
    with pytest.raises(ValueError, match='checksum'):
        restore_backup(store, runner, backup, lambda message: None)
    assert not runner.commands
    assert model.read_bytes() == b'changed-model'


def test_custom_storage_and_model_cache_are_restored_and_replaced_data_retained(tmp_path, monkeypatch):
    store = Store(tmp_path / 'manager')
    config = SiteConfig(data_directory=str(tmp_path / 'custom'))
    Configuration(store).save(config.model_dump())
    store.write('installed-configuration', config.model_dump())
    store.write('compose', {'name': 'cabek-test', 'services': {}})
    prepare_directories(store.root, config)
    model = Path(config.data_directory) / 'ocr-models/cached.pth'
    model.write_bytes(b'original-model')
    backup = create_backup(store, RecordingRunner(), lambda message: None)
    model.write_bytes(b'new-model')
    monkeypatch.setattr('manager.backups.subprocess.run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    restore_backup(store, RecordingRunner(), backup, lambda message: None)
    assert model.read_bytes() == b'original-model'
    assert next((Path(config.data_directory) / 'recovery').glob('*/ocr-models/cached.pth')).read_bytes() == b'new-model'


def test_default_camera_topology_is_four_streams_and_existing_selection_is_preserved(tmp_path):
    assert SiteConfig().camera_channels == [4, 13, 14, 10]
    configuration = Configuration(Store(tmp_path))
    configured = [1, 4, 10, 13, 14]
    configuration.save({'camera_channels': configured})
    assert configuration.load().camera_channels == configured


def test_existing_database_never_gets_replacement_credentials(tmp_path):
    store = Store(tmp_path)
    store.write('compose', {'services': {'database': {}}})
    with pytest.raises(ValueError, match='credentials are incomplete'):
        Configuration(store).ensure_credentials()
    assert not (tmp_path / 'credentials.json').exists()


def test_serial_reconnect_preserves_rootless_runtime_user(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from manager.serial_devices import attach_serial
    from manager.catalog import COMPONENTS
    store = Store(tmp_path)
    configuration = Configuration(store)
    configuration.ensure_credentials()
    store.write('installed-configuration', SiteConfig().model_dump())
    store.write('installed', {component.key: {'sha': 'a' * 40} for component in COMPONENTS})
    store.write('compose', {'services': {'gateway': {}, 'lighting': {'user': '0:0'}}})
    monkeypatch.setattr('manager.serial_devices.device_signature', lambda config: {'device': 1})
    monkeypatch.setattr('manager.serial_devices.docker_is_rootless', lambda runner: True)
    monkeypatch.setattr('manager.serial_devices.drain', lambda *args: None)
    monkeypatch.setattr('manager.serial_devices.resume', lambda *args: None)
    monkeypatch.setattr('manager.serial_devices.idle_station', lambda *args: nullcontext())
    attach_serial(store, RecordingRunner(), lambda message: None)
    assert store.read('compose')['services']['lighting']['user'] == '0:0'


def test_pricing_verification_failure_preserves_the_existing_token(tmp_path):
    from manager.provisioning import provision_pricing
    store = Store(tmp_path)
    configuration = Configuration(store)
    credentials = configuration.ensure_credentials()
    credentials['autoestimate_token'] = 'existing-private-token'
    store.write('credentials', credentials)
    class OfflineRunner:
        def run(self, *args, **kwargs):
            raise RuntimeError('Database is unavailable')
    with pytest.raises(RuntimeError, match='Database is unavailable'):
        provision_pricing(store, configuration, OfflineRunner(), lambda message: None)
    assert store.read('credentials') == credentials


def test_pricing_verdict_ignores_compose_progress_without_regenerating_credentials(tmp_path):
    from manager.provisioning import provision_pricing
    store = Store(tmp_path)
    configuration = Configuration(store)
    credentials = configuration.ensure_credentials()
    credentials['autoestimate_token'] = 'existing-private-token'
    store.write('credentials', credentials)
    class ComposeRunner:
        def run(self, *args, **kwargs):
            return ' Container cabek-pricing-run Creating\n Container cabek-pricing-run Created\nvalid\n'
    provision_pricing(store, configuration, ComposeRunner(), lambda message: None)
    assert store.read('credentials') == credentials


def test_four_stream_readiness_ignores_unconfigured_optional_camera_registry(monkeypatch):
    monkeypatch.setattr('manager.network_diagnostics.network_readiness', lambda host: {})
    configured = SiteConfig().camera_channels
    catalog = {'source': 'tiandy', 'cameras': [
        {'channel': channel, 'online': channel in configured} for channel in range(1, 15)]}
    monkeypatch.setattr('manager.readiness.request_native', lambda config, path:
        catalog if path == '/api/cameras' else {'output': False})
    check = next(item for item in hardware_readiness(SiteConfig()) if item.get('name') == 'NVR cameras')
    assert check['state'] == 'ready'
    assert check['message'] == '4 of 4 configured cameras delivering images.'
