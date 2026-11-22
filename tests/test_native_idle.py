"""Verify update barriers across the original capture-to-scan handoff locks.

Depends on isolated native state files and cross-thread file locks, not app hooks.
"""
from threading import Thread, Event
import json
import time
from filelock import FileLock
from manager.configuration import SiteConfig
from manager.native_idle import idle_station


def test_capture_handoff_cannot_be_mistaken_for_idle(tmp_path):
    folder = tmp_path/'data/dossiers/REAL'
    folder.mkdir(parents=True)
    (folder/'metadata.json').write_text(json.dumps({'captures': {'single': {'status': 'completed'}}}))
    capture = FileLock(str(folder/'.capture.lock'), thread_local=False)
    capture.acquire()
    acquired = Event()
    def wait():
        with idle_station(tmp_path, SiteConfig(), lambda path: {}, lambda message: None, timeout=3):
            acquired.set()
    thread = Thread(target=wait)
    thread.start()
    time.sleep(.1)
    assert not acquired.is_set()
    capture.release()
    thread.join(timeout=3)
    assert acquired.is_set()


def test_ocr_processing_defers_replacement(tmp_path):
    folder=tmp_path/'data/dossiers/OCR'
    folder.mkdir(parents=True)
    (folder/'metadata.json').write_text(json.dumps({'econstat': {'path':'document.pdf'}}))
    count=[]
    def status(path):
        count.append(path)
        return {'status': 'processing' if len(count)==1 else 'ready'}
    with idle_station(tmp_path, SiteConfig(), status, lambda message: None, timeout=2):
        assert len(count)==2
