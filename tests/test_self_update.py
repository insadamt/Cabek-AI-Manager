"""Verify manager revision preparation without replacing the current process.

Depends on a simulated command runner and private temporary revision directories.
"""
import sys
import pytest

from manager import VERSION
from manager.self_update import prepare_manager
from manager.storage import Store


def test_first_install_pins_manager_to_its_published_source(tmp_path):
    revision = {'tag': 'v' + VERSION, 'sha': 'a' * 40}
    class Runner:
        def run(self, *args, **kwargs):
            pytest.fail('The same tested version does not need a new environment')
    result = prepare_manager(Store(tmp_path), revision, Runner(), lambda message: None)
    assert result['python'] == sys.executable
    assert result['source'].endswith('sources/manager/' + 'a' * 40)


def test_dependency_failure_does_not_queue_a_restart(tmp_path):
    revision = {'tag': 'v99.0.0', 'sha': 'b' * 40}
    class Runner:
        def run(self, *args, **kwargs):
            raise RuntimeError('Dependency installation failed')
    store = Store(tmp_path)
    with pytest.raises(RuntimeError):
        prepare_manager(store, revision, Runner(), lambda message: None)
    assert store.read('manager-next', None) is None
