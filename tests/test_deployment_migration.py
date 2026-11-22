"""Verify mount detection is read-only and requires an explicit configuration apply.

Depends on temporary persisted Compose state; no Docker or hardware runs.
"""
from manager.storage import Store
from manager.deployment_migration import needs_private_storage


def test_old_renderer_mounts_require_explicit_apply_and_detection_never_mutates(tmp_path):
    store=Store(tmp_path)
    store.write('installed',{'manager':{'tag':'v0.3.0'},'backend':{'tag':'v0.2.0'}})
    compose={'services':{'backend':{'environment':{},'volumes':[]}}}
    store.write('compose',compose)
    assert needs_private_storage(store)
    assert store.read('compose')==compose
    assert store.read('job',None) is None
    store.write('compose',{'services':{'backend':{'environment':{'CABEK_DEMO_DIR':'/data/private-demo'},'volumes':['/private:/data/private-demo','/photos:/data/demo-photos:ro']}}})
    assert not needs_private_storage(store)


def test_older_native_versions_do_not_require_unsupported_mounts(tmp_path):
    store=Store(tmp_path)
    store.write('installed',{'manager':{'tag':'v0.2.2'},'backend':{'tag':'v0.1.1'}})
    assert not needs_private_storage(store)


def test_explicit_apply_does_not_skip_missing_mounts_when_releases_are_current(tmp_path,monkeypatch):
    import pytest
    from manager.catalog import COMPONENTS
    from manager.configuration import Configuration
    from manager.orchestrator import Orchestrator
    from manager.releases import GitHub
    store=Store(tmp_path);configuration=Configuration(store)
    configuration.save({'nvr_host':'192.0.2.1','nvr_password':'test','interior_url':'http://192.0.2.2'})
    installed={component.key:{'tag':'v0.3.0' if component.key=='manager' else 'v0.2.0','sha':'a'*40} for component in COMPONENTS}
    store.write('installed',installed);store.write('installed-configuration',configuration.load().model_dump())
    store.write('compose',{'services':{'backend':{'environment':{},'volumes':[]}}})
    monkeypatch.setattr('manager.orchestrator.preflight',lambda *args:{'ready':True})
    revisions={component.repository:installed[component.key] for component in COMPONENTS}
    monkeypatch.setattr(GitHub,'latest',lambda self,repository:revisions[repository])
    def reached_build(*args):raise RuntimeError('explicit mount deployment reached')
    monkeypatch.setattr(GitHub,'download',reached_build)
    with pytest.raises(RuntimeError,match='explicit mount deployment reached'):
        Orchestrator(store,configuration).update_all(lambda message:None)
