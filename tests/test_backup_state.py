"""Verify native-mode and device-state rollback alongside application data.

Depends on real local archives and temporary Store files; SQL process execution
is replaced here because isolated real SQL restoration is checked separately.
"""
from types import SimpleNamespace
from manager.backups import create_backup,restore_backup
from manager.configuration import Configuration
from manager.storage import Store


def test_restore_recovers_mode_and_serial_state_instead_of_retaining_failed_deployment_flags(tmp_path,monkeypatch):
    store=Store(tmp_path)
    Configuration(store).save({})
    store.write('compose',{'name':'own-recovery-test','services':{'gateway':{}}})
    store.write('real-operation-configured',False)
    store.write('serial-attachment',{'path':'previous-device'})
    data=tmp_path/'data/dossiers/REAL/document.txt';data.parent.mkdir(parents=True);data.write_text('original')
    class Runner:
        def run(self,args,**kwargs):
            if kwargs.get('output_path'):
                kwargs['output_path'].write_text('SELECT 1;')
            return ''
    private=tmp_path/'data/private-demo/templates/private.json';private.parent.mkdir(parents=True);private.write_text('private-original')
    sample=tmp_path/'data/demo-photos/front.jpg';sample.parent.mkdir(parents=True);sample.write_bytes(b'original-photo')
    backup=create_backup(store,Runner(),lambda message:None)
    private.write_text('changed');sample.unlink()
    store.write('real-operation-configured',True)
    store.write('serial-attachment',{'path':'failed-device'})
    data.write_text('modified')
    monkeypatch.setattr('subprocess.run',lambda *args,**kwargs:SimpleNamespace(returncode=0))
    restore_backup(store,Runner(),backup,lambda message:None)
    assert store.read('real-operation-configured') is False
    assert store.read('serial-attachment')=={'path':'previous-device'}
    assert data.read_text()=='original'
    assert private.read_text()=='private-original'
    assert sample.read_bytes()==b'original-photo'
