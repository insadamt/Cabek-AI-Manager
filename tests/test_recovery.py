"""Verify interrupted operations require recovery before further mutations.

Depends on temporary journals and mocked Docker boundaries; actual SQL restore
is exercised separately against the isolated integration database.
"""
import pytest
from fastapi.testclient import TestClient

from manager.api import create_app
from manager.configuration import Configuration
from manager.orchestrator import Orchestrator
from manager.storage import Store


def test_incomplete_transaction_blocks_installation_before_docker(tmp_path):
    store = Store(tmp_path)
    store.write('transaction', {'backup': None, 'first_install': True})
    with pytest.raises(ValueError, match='Recover'):
        Orchestrator(store, Configuration(store)).install(lambda message: None)


def test_first_install_recovery_stops_only_its_project_and_preserves_data(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.write('transaction', {'backup': None, 'first_install': True})
    store.write('compose', {'name': 'cabek-recovery-test'})
    data = tmp_path / 'data/dossiers/important.txt'
    data.parent.mkdir(parents=True)
    data.write_text('preserve this data')
    commands = []
    monkeypatch.setattr('manager.commands.CommandRunner.run', lambda self, args, **kwargs: commands.append(args) or '')
    Orchestrator(store, Configuration(store)).recover_interrupted_update(lambda message: None)
    assert store.read('transaction', None) is None
    assert data.read_text() == 'preserve this data'
    assert commands[0][3] == 'cabek-recovery-test'
    assert commands[0][-1] == 'stop'


def test_recovery_is_visible_and_start_is_blocked(tmp_path):
    app = create_app(tmp_path, watch_releases=False)
    app.state.store.write('transaction', {'backup': None, 'first_install': True})
    with TestClient(app) as client:
        assert client.get('/api/status').json()['recovery_required'] is True
        assert client.post('/api/start', json={}).status_code == 400
        assert client.post('/api/resume', json={}).status_code == 400
