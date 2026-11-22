"""Detect private mounts missing after an older Manager performs an upgrade.

Depends only on persisted deployment state. Detection exposes Apply configuration;
it never starts an update or changes running applications automatically.
"""
from manager.releases import version_tuple


def needs_private_storage(store):
    installed=store.read('installed',{})
    if not installed.get('manager') or not installed.get('backend'):return False
    if version_tuple(installed['manager']['tag']) < (0,3,0) or version_tuple(installed['backend']['tag']) < (0,2,0):return False
    backend=store.read('compose',{}).get('services',{}).get('backend',{})
    bindings=backend.get('volumes',[])
    return (backend.get('environment',{}).get('CABEK_DEMO_DIR')!='/data/private-demo'
            or not any(':/data/private-demo' in value for value in bindings)
            or not any(':/data/demo-photos' in value for value in bindings))
