"""Verify corrective sample quarantine preserves business data and every file.

Depends on known Manager artifact IDs and temporary backup directories only.
"""
from manager.configuration import Configuration
from manager.migration import quarantine_test_artifacts,TEST_DOSSIERS
from manager.storage import Store


def test_only_known_artifacts_move_out_of_active_data(tmp_path):
    store=Store(tmp_path)
    backup=tmp_path/'backups/original';backup.mkdir(parents=True)
    store.write('correction',{'backup':str(backup),'phase':'backed_up'})
    business=tmp_path/'data/dossiers/BUSINESS/document.pdf';business.parent.mkdir(parents=True);business.write_bytes(b'keep')
    sample=tmp_path/'data/dossiers'/TEST_DOSSIERS[0]/'metadata.json';sample.parent.mkdir(parents=True);sample.write_text('{}')
    quarantine_test_artifacts(store,Configuration(store),lambda message:None)
    assert business.read_bytes()==b'keep'
    assert not sample.exists()
    assert (backup/'quarantined-test-artifacts'/TEST_DOSSIERS[0]/'metadata.json').exists()
    quarantine_test_artifacts(store,Configuration(store),lambda message:None)
    assert business.exists()
