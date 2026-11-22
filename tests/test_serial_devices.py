"""Verify automatic attachment eligibility without touching host serial hardware.

Depends on temporary Manager state and mocked device identities. Stop/recovery
states must never trigger an unexpected container restart.
"""
from manager.serial_devices import needs_attachment
from manager.configuration import SiteConfig
from manager.storage import Store


def test_attachment_only_runs_for_a_changed_device_on_an_installed_running_station(tmp_path,monkeypatch):
    store=Store(tmp_path)
    store.write('installed',{'lighting':{'sha':'a'*40}})
    store.write('installed-configuration',SiteConfig().model_dump())
    store.write('compose',{'services':{'gateway':{}}})
    signature={'path':'/dev/ttyUSB0','device':123,'inode':456,'group':20}
    monkeypatch.setattr('manager.serial_devices.device_signature',lambda config:signature)
    assert needs_attachment(store)
    store.write('serial-attachment',signature)
    assert not needs_attachment(store)
    store.write('serial-attachment',None)
    store.write('services-stopped',True)
    assert not needs_attachment(store)
    store.write('services-stopped',False)
    store.write('transaction',{'backup':'pending'})
    assert not needs_attachment(store)


def test_disconnected_device_does_not_disable_or_remove_any_application(tmp_path,monkeypatch):
    store=Store(tmp_path)
    store.write('installed',{'lighting':{'sha':'a'*40}})
    store.write('compose',{'services':{'gateway':{},'lighting':{}}})
    monkeypatch.setattr('manager.serial_devices.device_signature',lambda config:None)
    assert not needs_attachment(store)
    assert 'lighting' in store.read('compose')['services']


def test_start_removes_stale_usb_mapping_without_removing_lighting(tmp_path, monkeypatch):
    from manager.serial_devices import refresh_saved_serial_mapping
    store = Store(tmp_path)
    store.write('compose', {'services': {'lighting': {'image': 'pinned-release',
        'devices': ['/dev/missing:/dev/cabek-esp32'], 'group_add': ['20']},
        'backend': {'image': 'unchanged'}}})
    monkeypatch.setattr('manager.serial_devices.selected_serial_device', lambda config: None)
    refresh_saved_serial_mapping(store, SiteConfig())
    services = store.read('compose')['services']
    assert services['lighting'] == {'image': 'pinned-release'}
    assert services['backend'] == {'image': 'unchanged'}
