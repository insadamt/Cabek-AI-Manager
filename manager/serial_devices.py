"""Reconcile a connected ESP32 with its Manager-owned Docker device mapping.

Depends on native USB identities and the gateway's idle barrier. Reconnection
restarts only the lighting container; application code and firmware stay unchanged.
"""
from manager.backend import drain, request_native, resume
from manager.compose import selected_serial_device, render_compose
from manager.configuration import Configuration, SiteConfig
from manager.native_idle import idle_station
from manager.system import compose_command, docker_is_rootless


def device_signature(config):
    device = selected_serial_device(config)
    if not device:
        return None
    details = device.stat()
    return {'path': str(device.resolve()), 'device': details.st_rdev, 'inode': details.st_ino, 'group': details.st_gid}


def needs_attachment(store):
    if store.read('services-stopped', False) or store.read('transaction', None) or store.read('manager-next', None):
        return False
    installed = store.read('installed', {})
    if 'lighting' not in installed or 'gateway' not in store.read('compose', {}).get('services', {}):
        return False
    config = SiteConfig.model_construct(**store.read('installed-configuration', {}))
    signature = device_signature(config)
    return bool(signature and signature != store.read('serial-attachment', None))


def attach_serial(store, runner, log):
    config = SiteConfig.model_construct(**store.read('installed-configuration', {}))
    signature = device_signature(config)
    if not signature:
        return
    credentials = Configuration(store).ensure_credentials()
    original = store.read('compose')
    replacement = render_compose(store.root, config, credentials, store.read('installed'),
                                 rootless=docker_is_rootless(runner))
    changed = False
    try:
        drain(config, credentials, log)
        with idle_station(store.root, config, lambda path: request_native(config, path), log):
            changed = True
            store.write('compose', {**original, 'services': {**original['services'], 'lighting': replacement['services']['lighting']}})
            runner.run(compose_command(store, 'up', '-d', '--no-deps', '--wait', '--force-recreate', 'lighting'), timeout=180)
        store.write('serial-attachment', signature)
        log('ESP32 mapping refreshed. Verify physical output with the existing Cabek controls.')
    except Exception:
        if changed:
            store.write('compose', original)
            runner.run(compose_command(store, 'up', '-d', '--no-deps', 'lighting'), timeout=120)
        raise
    finally:
        try:
            resume(config, credentials)
        except OSError:
            log('Gateway unavailable; resume admission after recovering its connection.')


def refresh_saved_serial_mapping(store, config):
    """Refresh transient USB paths at startup without changing installed image revisions."""
    compose = store.read('compose')
    lighting = compose['services']['lighting']
    lighting.pop('devices', None)
    lighting.pop('group_add', None)
    device = selected_serial_device(config)
    if device:
        lighting['devices'] = [f'{device.resolve()}:/dev/cabek-esp32']
        lighting['group_add'] = [str(device.stat().st_gid)]
    store.write('compose', compose)
