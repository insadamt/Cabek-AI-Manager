"""Control the Manager gateway while preserving native application endpoints.

Depends on the private gateway key. Application management hooks are unnecessary.
"""
import json
import time
from urllib.request import Request, urlopen


def request_native(config, path, payload=None, method=None):
    request = Request(f'http://127.0.0.1:{config.api_port}' + path,
                      data=json.dumps(payload).encode() if payload is not None else None,
                      method=method, headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def request_gateway(config, credentials, path, payload=None):
    request = Request(f'http://127.0.0.1:{config.api_port}/_manager/{path}',
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Content-Type': 'application/json', 'X-Cabek-Gateway-Key': credentials['gateway_key']})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def drain(config, credentials, log, timeout=180):
    request_gateway(config, credentials, 'gate', {'closed': True})
    deadline = time.monotonic() + timeout
    log('Gateway write admission closed; waiting for admitted HTTP requests.')
    while request_gateway(config, credentials, 'status')['active_mutations']:
        if time.monotonic() > deadline:
            raise ValueError('Admitted HTTP requests did not finish. Retry the update later.')
        time.sleep(.25)


def resume(config, credentials):
    return request_gateway(config, credentials, 'gate', {'closed': False})
