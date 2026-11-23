"""Build a disposable nine-service station from explicitly selected local sources.

Depends on Git, Docker, Manager dependencies and six application checkouts. Only
an empty audit home is accepted; physical devices and production state are excluded.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from manager.catalog import COMPONENTS
from manager.commands import CommandRunner
from manager.compose import prepare_runtime_directories, render_compose
from manager.configuration import Configuration, SiteConfig
from manager.lifecycle import start_database, start_applications
from manager.provisioning import provision_pricing
from manager.runtime_storage import initialize_storage
from manager.storage import Store
from manager.system import compose_command, docker_is_rootless


def snapshot_source(source, destination_root):
    output = subprocess.check_output(['git', '-C', str(source), 'ls-files', '-z',
                                      '--cached', '--others', '--exclude-standard'])
    excluded = {'.git', '.local', '.venv', '.agents', '.codex', '.aws', '.ai', '.claude', '.cursor',
                'node_modules', '.instructions.md', '.instruction.md', '.instrcutions.md', 'AGENTS.md'}
    names = sorted({name for name in output.decode().split('\0') if name
                    and not set(Path(name).parts) & excluded
                    and not Path(name).name.startswith('.env') and (source / name).is_file()})
    digest = hashlib.sha256()
    for name in names:
        path = source / name
        if path.is_symlink():
            raise ValueError('Audit source files must not be symlinks: ' + name)
        digest.update(name.encode())
        digest.update(path.read_bytes())
    revision = digest.hexdigest()[:40]
    destination = destination_root / revision
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    return {'tag': 'v0.0.0', 'sha': revision, 'source_commit': subprocess.check_output(
        ['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()}


def prepare_station(home, sources, app_port, api_port, model_cache=None):
    if home.exists() and any(home.iterdir()):
        raise ValueError('Use a new empty audit home; existing data is never cleared.')
    store = Store(home)
    revisions = {key: snapshot_source(path, home / 'sources' / key) for key, path in sources.items()}
    config = SiteConfig(app_port=app_port, api_port=api_port, nvr_host='192.0.2.1',
        nvr_password='isolated-audit-not-production', interior_url='http://192.0.2.2',
        serial_device='/dev/cabek-audit-disconnected')
    configuration = Configuration(store)
    configuration.save(config.model_dump())
    runner = CommandRunner(configuration.ensure_credentials().values(), print)
    rootless = docker_is_rootless(runner)
    prepare_runtime_directories(home, config)
    if model_cache:
        shutil.copytree(model_cache, home / 'data/ocr-models', dirs_exist_ok=True)
    compose = render_compose(home, config, configuration.ensure_credentials(), revisions, rootless=rootless)
    compose['name'] = 'cabek-audit-' + uuid4().hex[:12]
    store.write('compose', compose)
    store.write('audit-sources', revisions)
    runner.run(compose_command(store, 'config', '--quiet'))
    runner.run(compose_command(store, 'build'), timeout=3600)
    initialize_storage(home, config, compose, runner, rootless=rootless)
    start_database(store, runner)
    for command in (['migrate', '--force'], ['db:seed', '--force']):
        runner.run(compose_command(store, 'run', '--rm', '--no-deps', '-T', 'pricing',
                                   'php', 'artisan', *command), timeout=240)
    provision_pricing(store, configuration, runner, print)
    revised = render_compose(home, config, configuration.ensure_credentials(), revisions, rootless=rootless)
    revised['name'] = compose['name']
    store.write('compose', revised)
    start_applications(store, runner)
    store.write('installed', revisions)
    store.write('installed-configuration', config.model_dump())
    print('Audit station ready:', home)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--source', action='append', required=True, metavar='COMPONENT=/absolute/checkout')
    parser.add_argument('--app-port', type=int, default=28180)
    parser.add_argument('--api-port', type=int, default=28181)
    parser.add_argument('--model-cache', type=Path)
    arguments = parser.parse_args()
    sources = dict(value.split('=', 1) for value in arguments.source)
    expected = {component.key for component in COMPONENTS} - {'manager'}
    if set(sources) != expected:
        parser.error('Supply each application source: ' + ', '.join(sorted(expected)))
    sources = {key: Path(path).resolve() for key, path in sources.items()}
    sources['manager'] = Path(__file__).resolve().parents[2]
    prepare_station(arguments.home.resolve(), sources, arguments.app_port, arguments.api_port, arguments.model_cache)


if __name__ == '__main__':
    main()
