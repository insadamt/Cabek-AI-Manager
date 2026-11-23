"""Validate private SQL/data snapshots before any rollback mutation.

Depends on a drained backend, Compose, and the installed data location. Restores
retain replaced files for recovery and restore configuration before starting apps.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
from uuid import uuid4

from manager.system import compose_command
from manager.configuration import Configuration, SiteConfig, data_root
from manager.lifecycle import remove_application_containers, start_database, start_applications
from manager.runtime_storage import WRITABLE_DIRECTORIES

STATE_FILES = ('installed', 'installed-configuration', 'imports', 'configuration', 'credentials',
               'real-operation-configured', 'serial-attachment', 'pricing-client')


def installed_data_root(store):
    saved = store.read('installed-configuration', Configuration(store).load().model_dump())
    return data_root(store.root, SiteConfig.model_construct(**saved))


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def database_tables(store, runner):
    command = compose_command(store, 'exec', '-T', 'database', 'sh', '-c',
        'exec mariadb --batch --skip-column-names --user="$MARIADB_USER" '
        '--password="$MARIADB_PASSWORD" "$MARIADB_DATABASE"')
    output = runner.run(command, input_text="SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE';", quiet=True, timeout=30)
    return output.strip().splitlines() if output.strip() else []


def create_backup(store, runner, log):
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = store.root / 'backups' / name
    folder.mkdir(parents=True, mode=0o700)
    (folder / 'database-tables.json').write_text(json.dumps(database_tables(store, runner)))
    runner.run(compose_command(store, 'exec', '-T', 'database', 'sh', '-c',
               'exec mariadb-dump --user="$MARIADB_USER" --password="$MARIADB_PASSWORD" '
               '--single-transaction --routines --triggers "$MARIADB_DATABASE"'),
               timeout=600, output_path=folder / 'database.sql', quiet=True)
    with tarfile.open(folder / 'station-data.tar.gz', 'w:gz') as bundle:
        for name in WRITABLE_DIRECTORIES:
            path = installed_data_root(store) / name
            if path.exists():
                bundle.add(path, arcname=name)
    shutil.copy2(store.root / 'compose.json', folder / 'compose.json')
    for name in STATE_FILES:
        source = store.root / (name + '.json')
        if source.exists():
            shutil.copy2(source, folder / source.name)
    files = [path for path in folder.iterdir() if path.is_file()]
    manifest = {path.name: file_digest(path) for path in files}
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    for path in folder.iterdir():
        path.chmod(0o600)
    validate_backup(folder)
    log('Verified backup saved: ' + folder.name)
    return folder


def validate_backup(folder):
    folder = Path(folder)
    manifest_path = folder / 'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for name, expected in manifest.items():
            if Path(name).name != name or not (folder / name).is_file() or file_digest(folder / name) != expected:
                raise ValueError('Backup checksum validation failed: ' + name)
        if not {'database.sql', 'station-data.tar.gz', 'compose.json'} <= manifest.keys():
            raise ValueError('Backup manifest is incomplete.')
    if not (folder / 'database.sql').is_file() or not (folder / 'database.sql').stat().st_size:
        raise ValueError('Backup database dump is missing or empty.')
    compose = json.loads((folder / 'compose.json').read_text())
    with tarfile.open(folder / 'station-data.tar.gz') as bundle:
        for item in bundle:
            path = PurePosixPath(item.name)
            if (path.is_absolute() or '..' in path.parts or not path.parts
                    or path.parts[0] not in WRITABLE_DIRECTORIES or not (item.isfile() or item.isdir())):
                raise ValueError('Backup contains an unsafe persistent-data entry.')
    for name in STATE_FILES:
        path = folder / (name + '.json')
        if path.exists():
            json.loads(path.read_text())
    table_file = folder / 'database-tables.json'
    if table_file.exists():
        tables = json.loads(table_file.read_text())
        if not isinstance(tables, list) or not all(isinstance(name, str) and name for name in tables):
            raise ValueError('Backup table manifest is invalid.')
    return compose


def restore_sql(store, runner, source):
    command = compose_command(store, 'exec', '-T', 'database', 'sh', '-c',
                              'exec mariadb --user=root --password="$MARIADB_ROOT_PASSWORD"')
    table_file = source.parent / 'database-tables.json'
    if table_file.exists():
        previous_tables = json.loads(table_file.read_text())
    else:
        # Older backups predate the table manifest; native mariadb-dump quotes identifiers.
        with source.open() as stream:
            previous_tables = [match.group(1).replace('``', '`') for line in stream
                if (match := re.match(r'CREATE TABLE (?:IF NOT EXISTS )?`((?:``|[^`])+)`', line))]
    if not isinstance(previous_tables, list) or not all(isinstance(name, str) for name in previous_tables):
        raise ValueError('Backup table manifest is invalid.')
    introduced = sorted(set(database_tables(store, runner)) - set(previous_tables))
    with tempfile.TemporaryFile() as restored_sql, source.open('rb') as stream:
        # Keep the database and grants intact; only discard tables added by the failed migration.
        restored_sql.write(b'USE `cabek_autoestimate`; SET FOREIGN_KEY_CHECKS=0;\n')
        for table in introduced:
            quoted = '`' + table.replace('`', '``') + '`'
            restored_sql.write(('DROP TABLE IF EXISTS ' + quoted + ';\n').encode())
        shutil.copyfileobj(stream, restored_sql)
        restored_sql.write(b'\nSET FOREIGN_KEY_CHECKS=1;\n')
        restored_sql.seek(0)
        result = subprocess.run(command, stdin=restored_sql, capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError('Database restoration failed; retain the backup and recovery transaction.')


def restore_backup(store, runner, folder, log):
    folder = Path(folder)
    restored_compose = validate_backup(folder)
    saved_config = folder / 'installed-configuration.json'
    if not saved_config.exists():
        saved_config = folder / 'configuration.json'
    values = json.loads(saved_config.read_text()) if saved_config.exists() else {}
    data = data_root(store.root, SiteConfig.model_construct(**values))
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=data) as temporary:
        stage = Path(temporary)
        # Fully decompress before touching live SQL or replacing station directories.
        with tarfile.open(folder / 'station-data.tar.gz') as bundle:
            bundle.extractall(stage, filter='data')
        remove_application_containers(store, runner)
        store.write('compose', restored_compose)
        start_database(store, runner)
        restore_sql(store, runner, folder / 'database.sql')
        retained = data / 'recovery' / uuid4().hex
        for name in WRITABLE_DIRECTORIES:
            current, restored = data / name, stage / name
            if not restored.exists():
                continue
            if name == 'ocr-models' and current.is_dir():
                # Retain new cache files too; EasyOCR verifies their checksums before reuse.
                for cached in current.rglob('*'):
                    destination = restored / cached.relative_to(current)
                    if cached.is_file() and not cached.is_symlink() and not destination.exists():
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(cached, destination)
            if current.exists():
                retained.mkdir(parents=True, exist_ok=True, mode=0o700)
                current.rename(retained / name)
            restored.rename(current)
    for name in STATE_FILES:
        source = folder / (name + '.json')
        if source.exists():
            store.write(name, json.loads(source.read_text()))
        else:
            (store.root / (name + '.json')).unlink(missing_ok=True)
    if 'gateway' not in restored_compose.get('services', {}):
        (data / 'runtime/manager-maintenance.lock').unlink(missing_ok=True)
    start_applications(store, runner)
    log('Previous applications, database and private state restored; replaced data retained under data/recovery.')
