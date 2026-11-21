"""Back up only managed persistent data before replacing services or migrating SQL.

Depends on a drained backend and the manager's Compose project. Database dumps
are streamed to private files and never appear in logs or API responses.
"""
from datetime import datetime, timezone
import shutil
import tarfile

from manager.system import compose_command


def create_backup(store, runner, log):
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = store.root / "backups" / name
    folder.mkdir(parents=True, mode=0o700)
    runner.run(compose_command(store, "exec", "-T", "database", "sh", "-c",
               'exec mariadb-dump --user="$MARIADB_USER" --password="$MARIADB_PASSWORD" '
               '--single-transaction --routines --triggers "$MARIADB_DATABASE"'),
               timeout=600, output_path=folder / "database.sql", quiet=True)
    with tarfile.open(folder / "station-data.tar.gz", "w:gz") as bundle:
        for name in ("dossiers", "runtime"):
            path = store.root / "data" / name
            if path.exists():
                bundle.add(path, arcname=name)
    shutil.copy2(store.root / "compose.json", folder / "compose.json")
    for name in ("installed", "installed-configuration", "imports", "configuration", "credentials"):
        source = store.root / (name + ".json")
        if source.exists():
            shutil.copy2(source, folder / source.name)
    log("Backup saved: " + folder.name)
    return folder


def restore_backup(store, runner, folder, log):
    shutil.copy2(folder / "compose.json", store.root / "compose.json")
    runner.run(compose_command(store, "up", "-d", "--wait", "database"), timeout=180)
    # Restore from a file descriptor, keeping both SQL and credentials out of command arguments.
    import subprocess
    import tempfile
    command = compose_command(store, "exec", "-T", "database", "sh", "-c",
                              'exec mariadb --user=root --password="$MARIADB_ROOT_PASSWORD"')
    with tempfile.TemporaryFile() as restored_sql, (folder / "database.sql").open("rb") as source:
        # Drop newly introduced tables too, rather than restoring only pre-existing table names.
        restored_sql.write(b'DROP DATABASE IF EXISTS `cabek_autoestimate`; '
                          b'CREATE DATABASE `cabek_autoestimate` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; '
                          b'USE `cabek_autoestimate`;\n')
        shutil.copyfileobj(source, restored_sql)
        restored_sql.seek(0)
        result = subprocess.run(command, stdin=restored_sql, capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError("Database restoration failed; preserve the backup and inspect database logs.")
    data = store.root / "data"
    with tarfile.open(folder / "station-data.tar.gz") as bundle:
        for name in ("dossiers", "runtime"):
            path = data / name
            if path.exists():
                shutil.rmtree(path)
        bundle.extractall(data, filter="data")
    runner.run(compose_command(store, "up", "-d", "--wait", "--wait-timeout", "180", "--remove-orphans"), timeout=240)
    for name in ("installed", "installed-configuration", "imports"):
        source = folder / (name + ".json")
        if source.exists():
            shutil.copy2(source, store.root / source.name)
        else:
            (store.root / (name + ".json")).unlink(missing_ok=True)
    log("Previous application version and database restored.")
