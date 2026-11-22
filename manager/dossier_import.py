"""Run additive dossier import through the backend's native validator.

Depends on Manager-owned read-only mounts and the native idle barrier. Existing
production folders are never replaced and dry runs precede explicit publication.
"""
from pathlib import Path
from manager.backend import drain, resume, request_native
from manager.configuration import Configuration, SiteConfig
from manager.native_idle import idle_station
from manager.system import compose_command


def import_dossiers(store, runner, source, apply, log, identities=None):
    path = Path(source)
    if not path.is_absolute() or not path.exists() or path.is_symlink():
        raise ValueError('Choose an existing absolute local dossier directory or ZIP archive.')
    if path.is_file() and (path.suffix.lower() != '.zip' or path.stat().st_size > 512 * 1024**2):
        raise ValueError('Choose a ZIP archive no larger than 512 MiB.')
    config = SiteConfig.model_construct(**store.read('installed-configuration'))
    credentials = Configuration(store).ensure_credentials()
    command = compose_command(store, 'run', '--rm', '--no-deps', '-T', '--volume', f'{path.resolve()}:/manager-import:ro',
                              'backend', 'python', 'scripts/import_dossiers.py', '/manager-import', '--destination', '/data/dossiers')
    if identities:
        import re
        if not isinstance(identities, list) or not all(isinstance(identity, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', identity) for identity in identities):
            raise ValueError('Invalid dossier IDs.')
        command.extend(['--ids', *identities])
    if not apply:
        log(runner.run(command, timeout=600, quiet=True))
        return
    try:
        drain(config, credentials, log)
        with idle_station(store.root, config, lambda endpoint:request_native(config, endpoint), log):
            log(runner.run([*command, '--apply'], timeout=600, quiet=True))
    finally:
        resume(config, credentials)
