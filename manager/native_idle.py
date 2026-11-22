"""Wait for native captures, scan workers, and OCR without adding application APIs.

Depends on existing application locks, persisted job states, and the OCR GET API.
Admission locks bridge capture-to-scan handoff; unreadable state blocks replacement.
"""
from contextlib import ExitStack, contextmanager
import json
import time
from filelock import FileLock, Timeout
from manager.configuration import data_root


@contextmanager
def idle_station(root, config, get_native, log, timeout=1900):
    dossiers = data_root(root, config) / 'dossiers'
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with ExitStack() as locks:
                folders = sorted(path for path in dossiers.iterdir() if path.is_dir() and not path.name.startswith('.'))
                for folder in folders:
                    admission = dossiers / '.lifecycle-locks' / (folder.name + '.lock')
                    admission.parent.mkdir(exist_ok=True)
                    for path in (admission, folder / '.capture.lock', folder / 'analysis/.scan.lock', folder / 'analysis/.worker.lock'):
                        if path.parent.is_dir():
                            locks.enter_context(FileLock(str(path)).acquire(timeout=0))
                busy = False
                for folder in folders:
                    metadata = json.loads((folder / 'metadata.json').read_text())
                    busy |= any(value.get('status') == 'capturing' for value in metadata.get('captures', {}).values())
                    status = folder / 'analysis/status.json'
                    if status.exists():
                        record = json.loads(status.read_text())
                        if (record.get('progress') or {}).get('stage') == 'awaiting_metadata':
                            raise ValueError('Complete the pending vehicle metadata before stopping or updating the station.')
                        busy |= record.get('status') in ('queued', 'processing')
                    if metadata.get('econstat'):
                        busy |= get_native(f'/api/dossiers/{folder.name}/econstat')['status'] == 'processing'
                busy |= (data_root(root, config) / 'runtime/tunnel-lease.json').exists()
                if not busy:
                    log('Native application jobs are idle; replacement can begin.')
                    yield
                    return
        except Timeout:
            pass
        time.sleep(.5)
    raise ValueError('Accepted application work is still active. No replacement was forced.')
