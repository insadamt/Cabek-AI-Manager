"""Deploy every native Cabek application using Manager-owned recipes and controls.

Depends on published stable releases, private state, native application contracts,
and backups. Application source archives are never patched or used for deployment files.
"""
import hashlib
from pathlib import Path
from manager.backend import drain, request_gateway, request_native, resume
from manager.backups import create_backup, restore_backup
from manager.catalog import COMPONENTS
from manager.commands import CommandRunner
from manager.configuration import SiteConfig, RETIRED_FIELDS, data_root
from manager.compose import render_compose, prepare_runtime_directories
from manager.migration import quarantine_test_artifacts
from manager.native_idle import idle_station
from manager.provisioning import provision_pricing, configure_real_station
from manager.releases import GitHub, version_tuple
from manager.self_update import prepare_manager
from manager.system import compose_command, preflight, require_free_ports


class Orchestrator:
    def __init__(self, store, configuration):
        self.store = store
        self.configuration = configuration

    def create_runner(self, log=None):
        config = self.configuration.load()
        private = [value for values in config.native_environment.values() for name, value in values.items() if any(word in name.lower() for word in ('token', 'password', 'secret', 'key'))]
        return CommandRunner([config.github_token, config.nvr_password, *private, *self.configuration.ensure_credentials().values()], log)

    def check_updates(self):
        config = self.configuration.load()
        github = GitHub(self.create_runner(), config.github_token)
        installed = self.store.read('installed', {})
        components = []
        for component in COMPONENTS:
            current = installed.get(component.key)
            try:
                latest = github.latest(component.repository)
                newer = not current or version_tuple(latest['tag']) > version_tuple(current['tag'])
                if current and current['tag'] == latest['tag'] and current['sha'] != latest['sha']:
                    raise ValueError('A published version changed its revision. Publish a new release instead.')
                components.append({'key': component.key, 'name': component.name, 'repository': component.repository,
                    'installed': current, 'latest': latest, 'update_available': newer, 'error': None})
            except (ValueError, RuntimeError, OSError) as error:
                components.append({'key': component.key, 'name': component.name, 'repository': component.repository,
                    'installed': current, 'latest': None, 'update_available': False,
                    'error': self.create_runner().redact(str(error))})
        result = {'components': components, 'updates_available': any(item['update_available'] for item in components)}
        self.store.write('updates', result)
        return result

    def install(self, log):
        self.apply(log, updating=False)

    def update_all(self, log):
        if not self.store.read('installed', {}):
            raise ValueError('Install the ecosystem before updating it.')
        self.apply(log, updating=True)

    def active_configuration(self):
        saved = self.store.read('installed-configuration', self.configuration.load().model_dump())
        return SiteConfig.model_construct(**{key: value for key, value in saved.items() if key not in RETIRED_FIELDS})

    def stop(self, log):
        config = self.active_configuration()
        credentials = self.configuration.ensure_credentials()
        runner = self.create_runner(log)
        try:
            drain(config, credentials, log)
            with idle_station(self.store.root, config, lambda path: request_native(config, path), log):
                runner.run(compose_command(self.store, 'stop', 'backend'), timeout=120)
            runner.run(compose_command(self.store, 'stop'), timeout=120)
            self.store.write('services-stopped', True)
        except Exception:
            resume(config, credentials)
            raise

    def start(self, log):
        from manager.serial_devices import refresh_saved_serial_mapping, device_signature
        config = self.active_configuration()
        refresh_saved_serial_mapping(self.store, config)
        runner = self.create_runner(log)
        runner.run(compose_command(self.store, 'up', '-d', '--wait', '--wait-timeout', '240'), timeout=300)
        resume(self.active_configuration(), self.configuration.ensure_credentials())
        self.store.write('services-stopped', False)
        self.store.write('serial-attachment', device_signature(config))

    def apply(self, log, updating):
        if self.store.read('transaction', None):
            raise ValueError('Recover the interrupted operation before installing or updating.')
        config = SiteConfig.model_validate(self.configuration.load().model_dump())
        config.require_installation_settings()
        runner = self.create_runner(log)
        checks = preflight(runner, config.github_token)
        if not checks['ready']:
            raise ValueError('Prerequisites failed: ' + '; '.join(item['name'] for item in checks['checks'] if not item['ok']))
        previous = self.store.read('installed', {})
        if previous and not updating:
            raise ValueError('The ecosystem is installed. Use Update All or Start services.')
        if not previous:
            require_free_ports(config)
        updates = self.check_updates()
        failures = [item['name'] + ': ' + item['error'] for item in updates['components'] if item['error']]
        if failures:
            raise ValueError('\n'.join(failures))
        targets = {item['key']: item['latest'] if item['update_available'] else item['installed'] for item in updates['components']}
        if targets == previous and self.store.read('installed-configuration') == config.model_dump():
            log('Every application is at its latest published stable release.')
            return
        github = GitHub(runner, config.github_token)
        for component in COMPONENTS:
            destination = self.store.root / 'sources' / component.key / targets[component.key]['sha']
            if not destination.exists():
                log(f"Downloading {component.name} {targets[component.key]['tag']}.")
                github.download(component.repository, targets[component.key]['sha'], destination)
        prepare_runtime_directories(self.store.root, config)
        credentials = self.configuration.ensure_credentials()
        candidate = render_compose(self.store.root, config, credentials, targets)
        self.store.write('candidate-compose', candidate)
        candidate_command = ['docker', 'compose', '-p', 'cabek-ai-manager', '-f', str(self.store.root / 'candidate-compose.json')]
        log('Building all applications using Manager-owned recipes and unchanged sources.')
        runner.run([*candidate_command, 'config', '--quiet'], timeout=30)
        runner.run([*candidate_command, 'build'], timeout=3600)
        manager_update = prepare_manager(self.store, targets['manager'], runner, log)
        previous_config = self.active_configuration()
        backup = None
        drained = False
        backend_stopped = False
        committed = False
        old_compose = self.store.read('compose', {})
        legacy = bool(old_compose) and 'gateway' not in old_compose.get('services', {})
        try:
            if previous and not legacy:
                drained = True
                drain(previous_config, credentials, log)
                with idle_station(self.store.root, previous_config, lambda path: request_native(previous_config, path), log):
                    runner.run(compose_command(self.store, 'stop', 'backend'), timeout=120)
                    backend_stopped = True
                backup = create_backup(self.store, runner, log)
                self.store.write('transaction', {'backup': str(backup), 'first_install': False})
                runner.run(compose_command(self.store, 'stop'), timeout=120)
            elif legacy:
                correction = self.store.read('correction', {})
                if not correction.get('backup'):
                    raise ValueError('Legacy installation requires the backed-up corrective handover.')
                backup = Path(correction['backup'])
                self.store.write('transaction', {'backup': str(backup), 'first_install': False})
            else:
                self.store.write('transaction', {'backup': None, 'first_install': True})
            quarantine_test_artifacts(self.store, self.configuration, log)
            (data_root(self.store.root, config) / 'runtime/gateway-closed').touch(mode=0o600)
            self.store.write('compose', candidate)
            runner.run(compose_command(self.store, 'up', '-d', '--wait', '--wait-timeout', '180', 'database'), timeout=240)
            log('Applying native migrations, canonical seeders, and pricing initialization.')
            for command in (['migrate', '--force'], ['db:seed', '--force']):
                runner.run(compose_command(self.store, 'run', '--rm', '--no-deps', 'pricing', 'php', 'artisan', *command), timeout=240)
            provision_pricing(self.store, self.configuration, runner, log)
            self.store.write('compose', render_compose(self.store.root, config, self.configuration.ensure_credentials(), targets))
            self.import_datasets(config, targets, runner, log)
            runner.run(compose_command(self.store, 'up', '-d', '--wait', '--wait-timeout', '300', '--remove-orphans', '--force-recreate'), timeout=420)
            if not self.store.read('real-operation-configured', False):
                configure_real_station(self.store, runner)
            log('Preparing persistent OCR models and checking native application connectivity.')
            runner.run(compose_command(self.store, 'exec', '-T', 'ocr', 'python', '-c', "import easyocr; easyocr.Reader(['fr','en'], gpu=False, verbose=False)"), timeout=1200)
            request_native(config, '/api/settings/operation')
            request_native(config, '/api/vehicles/marques')
            request_native(config, '/api/cameras')
            self.store.write('real-operation-configured', True)
            self.store.write('installed', targets)
            self.store.write('installed-configuration', config.model_dump())
            self.configuration.save({})
            self.store.write('updates', {'components': [{**item, 'installed': targets[item['key']], 'update_available': False} for item in updates['components']], 'updates_available': False})
            if manager_update:
                self.store.write('manager-next', manager_update)
            if self.store.read('correction', None):
                correction = self.store.read('correction')
                self.store.write('correction', {**correction, 'phase': 'completed'})
            from manager.serial_devices import device_signature
            self.store.write('serial-attachment', device_signature(config))
            self.store.write('services-stopped', False)
            self.store.write('transaction', None)
            committed = True
            try:
                resume(config, self.configuration.ensure_credentials())
            except OSError:
                log('Deployment committed; use Start services to resume gateway admission.')
            log('All applications installed. Hardware readiness is reported separately.')
        except Exception:
            if committed:
                raise
            (self.store.root / 'manager-next.json').unlink(missing_ok=True)
            if backup:
                log('Deployment failed; restoring the previous application and database backup.')
                runner.run(compose_command(self.store, 'stop'), timeout=120)
                restore_backup(self.store, runner, backup, log)
                self.store.write('transaction', None)
            elif previous:
                if backend_stopped:
                    runner.run(compose_command(self.store, 'up', '-d', '--no-deps', '--wait', 'backend'), timeout=180)
            elif self.store.read('transaction', None):
                runner.run(compose_command(self.store, 'stop'), timeout=120)
                self.store.write('transaction', None)
            raise
        finally:
            if drained:
                try:
                    resume(config if self.store.read('installed', {}) == targets else previous_config, self.configuration.ensure_credentials())
                except OSError:
                    log('Gateway unavailable; use recovery or start services to resume admission.')

    def import_datasets(self, config, revisions, runner, log):
        source = self.store.root / 'sources/autoestimate' / revisions['autoestimate']['sha'] / 'data'
        paths = [(path, '/imports/bundled/' + path.name) for path in source.glob('*.zip')]
        paths += [(Path(path), f'/imports/custom-{index}') for index, path in enumerate(config.dataset_paths)]
        imported = self.store.read('imports', {})
        for path, container_path in paths:
            files = [path] if path.is_file() else sorted(path.rglob('*.json'))
            digest = hashlib.sha256()
            for item in files:
                digest.update(item.name.encode())
                with item.open('rb') as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
            key = digest.hexdigest()
            if key in imported:
                continue
            log('Validating and importing dataset: ' + path.name)
            command = compose_command(self.store, 'run', '--rm', '--no-deps', 'pricing', 'php', 'artisan', 'observations:import', container_path)
            runner.run([*command, '--dry-run'], timeout=600)
            runner.run([*command, '--yes'], timeout=900)
            imported[key] = path.name
            self.store.write('imports', imported)

    def recover_interrupted_update(self, log):
        transaction = self.store.read('transaction', None)
        if not transaction:
            raise ValueError('No interrupted operation requires recovery.')
        runner = self.create_runner(log)
        runner.run(compose_command(self.store, 'stop'), timeout=120)
        if transaction.get('backup'):
            folder = Path(transaction['backup']).resolve()
            if not folder.is_relative_to(self.store.root / 'backups') or not folder.is_dir():
                raise ValueError('Recovery backup is missing or outside this installation.')
            restore_backup(self.store, runner, folder, log)
            if 'gateway' in self.store.read('compose', {}).get('services', {}):
                resume(self.active_configuration(), self.configuration.ensure_credentials())
        (self.store.root / 'manager-next.json').unlink(missing_ok=True)
        self.store.write('transaction', None)
        log('Recovery complete; installation data preserved.')
