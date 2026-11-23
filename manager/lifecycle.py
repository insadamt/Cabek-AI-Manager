"""Replace application containers without replacing the persistent database.

Depends on Compose's service graph and the saved project name. Namespace consumers
must be removed before their gateway, including during rollback and recovery.
"""
from manager.system import compose_command


def remove_application_containers(store, runner):
    saved = store.read('compose', {})
    services = saved.get('services', {})
    project = saved.get('name', 'cabek-ai-manager')
    inventory = runner.run(['docker', 'ps', '--all', '--filter',
                            'label=com.docker.compose.project=' + project, '--filter',
                            'label=com.docker.compose.oneoff=False', '--format',
                            '{{.ID}} {{.Label "com.docker.compose.service"}}'], timeout=20, quiet=True)
    stale = []
    for line in inventory.splitlines():
        identity, service = line.split(maxsplit=1)
        if service != 'database' and service not in services:
            stale.append(identity)
    if stale:
        runner.run(['docker', 'rm', '--force', *stale], timeout=120)
    consumers = [name for name in services if name not in ('database', 'gateway')]
    if consumers:
        runner.run(compose_command(store, 'rm', '--stop', '--force', *consumers), timeout=180)
    if 'gateway' in services:
        runner.run(compose_command(store, 'rm', '--stop', '--force', 'gateway'), timeout=120)


def start_database(store, runner):
    # Application configuration changes must never trigger implicit MariaDB replacement.
    runner.run(compose_command(store, 'up', '-d', '--no-recreate', '--wait',
                               '--wait-timeout', '180', 'database'), timeout=240)


def start_applications(store, runner):
    services = store.read('compose', {}).get('services', {})
    for group in (('gateway', 'pricing'), ('cameras', 'lighting', 'ocr', 'pricing-web'),
                  ('backend', 'frontend')):
        selected = [name for name in group if name in services]
        if selected:
            runner.run(compose_command(store, 'up', '-d', '--no-deps', '--wait',
                                       '--wait-timeout', '300', *selected), timeout=420)
