"""Quarantine only Manager-created sample artifacts during the corrective handover.

Depends on the pre-correction backup and known acceptance-test dossier IDs.
Business data and all pricing observations remain in place; nothing is deleted.
"""
from pathlib import Path
import shutil
from uuid import uuid4
from manager.configuration import data_root

TEST_DOSSIERS = ('DOS-20261122-103305-66018ed237cd4fe2a3deb1096e58e1ca', 'MANAGER-OCR-INTEGRATION')


def quarantine_test_artifacts(store, configuration, log):
    correction = store.read('correction', None)
    if not correction or correction.get('phase') == 'completed':
        return
    destination = Path(correction['backup']) / 'quarantined-test-artifacts'
    destination.mkdir(mode=0o700, exist_ok=True)
    data = data_root(store.root, configuration.load())
    candidates = [data / 'dossiers' / name for name in TEST_DOSSIERS]
    candidates += [data / 'mock-photos', data / 'runtime/manager-maintenance.lock']
    for source in candidates:
        if source.exists():
            target = destination / source.name
            if target.exists():
                target = destination / (source.name + '-' + uuid4().hex[:8])
            shutil.move(str(source), target)
    correction['artifacts_quarantined'] = True
    store.write('correction', correction)
    log('Known Manager test artifacts quarantined outside active station data.')
