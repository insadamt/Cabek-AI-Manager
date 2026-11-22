"""Configure native AutoEstimate and station preferences from Manager-owned code.

Depends on original Artisan commands and the existing backend settings API.
Credentials are captured privately, reused, and never printed in operation logs.
"""
import re
import secrets
from manager.system import compose_command


def provision_pricing(store, configuration, runner, log):
    credentials = configuration.ensure_credentials()
    token = credentials.get('autoestimate_token', '')
    command = compose_command(store, 'run', '--rm', '--no-deps', '-T', 'pricing')
    if token:
        try:
            runner.run([*command, 'php', '/manager/check-client.php'], input_text=token, quiet=True)
            log('Existing AutoEstimate credentials verified and retained.')
            return
        except RuntimeError:
            pass
    name = 'Cabek AI Manager ' + secrets.token_hex(8)
    output = runner.run([*command, 'php', 'artisan', 'api:token:create', name], quiet=True)
    match = re.search(r'\bcae_[A-Za-z0-9]{64}\b', output)
    if not match:
        raise ValueError('The native AutoEstimate token command did not return a usable token.')
    credentials['autoestimate_token'] = match.group(0)
    store.write('credentials', credentials)
    runner.private_values.append(credentials['autoestimate_token'])
    store.write('pricing-client', {'name': name})
    log('AutoEstimate client created through its native token command.')


def configure_real_station(store, runner):
    # New native backends default to real operation; private demo preferences survive updates.
    return None
