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
