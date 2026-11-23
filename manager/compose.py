"""Build the entire native ecosystem with Manager-owned deployment recipes.

Depends on exact release archives, a shared loopback namespace, and private data.
Application source trees are read-only inputs; Docker/configuration files live here.
"""
import hashlib
import json
import os
import shlex
from pathlib import Path
from manager.configuration import data_root


def escape_compose_literals(value):
    if isinstance(value, str):
        return value.replace('$', '$$')
    if isinstance(value, list):
        return [escape_compose_literals(item) for item in value]
    if isinstance(value, dict):
        return {key: escape_compose_literals(item) for key, item in value.items()}
    return value


def selected_serial_device(config):
    if config.serial_device not in ('', 'auto'):
        path = Path(config.serial_device)
        return path if path.exists() and path.is_char_device() else None
    devices = sorted(Path('/dev/serial/by-id').glob('*'))
    return devices[0] if len(devices) == 1 else None


def prepare_runtime_directories(root, config=None):
    from manager.configuration import SiteConfig
    from manager.runtime_storage import prepare_directories
    prepare_directories(root, config or SiteConfig())


def python_health(code):
    return {'test': ['CMD-SHELL', 'python -c ' + shlex.quote(code)], 'interval': '10s', 'timeout': '5s', 'retries': 18, 'start_period': '30s'}


def render_compose(root, config, credentials, revisions, *, rootless=False):
    root = Path(root).resolve()
    data = data_root(root, config)
    manager_source = root / 'sources/manager' / revisions['manager']['sha']
    recipes = manager_source / 'deploy'
    digest = hashlib.sha256()
    for file in sorted(recipes.rglob('*')):
        if file.is_file() and '__pycache__' not in file.parts:
            digest.update(str(file.relative_to(recipes)).encode())
            digest.update(file.read_bytes())
    recipe_hash = digest.hexdigest()[:12]

    def source(key):
        return str(root / 'sources' / key / revisions[key]['sha'])

    def application(key, target=None):
        context = source(key) if key != 'gateway' else str(manager_source)
        recipe = key if key != 'autoestimate' else 'autoestimate'
        build = {'context': context, 'dockerfile': str(recipes / recipe / 'Dockerfile'),
                 'additional_contexts': {'deployment': str(recipes)}}
        if target:
            build['target'] = target
        parameters = {'app_port': config.app_port} if key == 'frontend' else {}
        if parameters:
            build['args'] = {'VITE_API_BASE_URL': f'http://localhost:{config.app_port}'}
        identity = hashlib.sha256(json.dumps([recipe_hash, target, parameters], sort_keys=True).encode()).hexdigest()[:12]
        revision = revisions['manager' if key == 'gateway' else key]['sha'][:12]
        service = {'build': build, 'image': f'cabek-managed-{key}:{revision}-{identity}',
                   'pull_policy': 'never', 'restart': 'unless-stopped'}
        if key in ('backend', 'gateway', 'cameras', 'lighting', 'ocr'):
            service['user'] = '0:0' if rootless else f'{os.getuid()}:{os.getgid()}'
            service['cap_drop'] = ['ALL']
            service['security_opt'] = ['no-new-privileges:true']
        if key in ('backend', 'frontend', 'cameras', 'lighting', 'ocr'):
            service['network_mode'] = 'service:gateway'
        return service

    gateway = application('gateway')
    gateway['ports'] = [f'127.0.0.1:{config.app_port}:80', f'127.0.0.1:{config.api_port}:8008']
    gateway['environment'] = {'CABEK_GATEWAY_KEY': credentials['gateway_key'],
                              'CABEK_GATEWAY_MARKER': '/state/gateway-closed'}
    gateway['volumes'] = [f'{data}/runtime:/state']
    gateway['healthcheck'] = python_health("import urllib.request; urllib.request.urlopen('http://127.0.0.1:8008/_manager/health',timeout=3)")
    database = {'image': 'mariadb:11.8', 'restart': 'unless-stopped',
                'environment': {'MARIADB_DATABASE': 'cabek_autoestimate', 'MARIADB_USER': 'cabek',
                                'MARIADB_PASSWORD': credentials['db_password'], 'MARIADB_ROOT_PASSWORD': credentials['db_root_password']},
                'volumes': ['pricing_database:/var/lib/mysql'],
                'healthcheck': {'test': ['CMD', 'healthcheck.sh', '--connect', '--innodb_initialized'],
                                'interval': '5s', 'timeout': '5s', 'retries': 30, 'start_period': '30s'}}
    pricing = application('autoestimate', 'app')
    pricing['environment'] = {'APP_NAME': 'Cabek AutoEstimate', 'APP_ENV': 'production', 'APP_DEBUG': 'false',
        'APP_KEY': credentials['app_key'], 'APP_URL': 'http://pricing-web', 'LOG_CHANNEL': 'stderr',
        'DB_CONNECTION': 'mariadb', 'DB_HOST': 'database', 'DB_PORT': '3306', 'DB_DATABASE': 'cabek_autoestimate',
        'DB_USERNAME': 'cabek', 'DB_PASSWORD': credentials['db_password'], 'SESSION_DRIVER': 'database',
        'CACHE_STORE': 'database', 'QUEUE_CONNECTION': 'database'}
    pricing['networks'] = {'default': {'aliases': ['app']}}
    pricing['depends_on'] = {'database': {'condition': 'service_healthy'}}
    pricing['volumes'] = [f"{source('autoestimate')}/data:/imports/bundled:ro", f'{recipes}/autoestimate:/manager:ro']
    pricing['volumes'] += [f'{path}:/imports/custom-{index}:ro' for index, path in enumerate(config.dataset_paths)]
    pricing['healthcheck'] = {'test': ['CMD', 'php', '/manager/health.php'], 'interval': '10s',
                              'timeout': '5s', 'retries': 18, 'start_period': '30s'}
    pricing_web = application('autoestimate', 'nginx')
    pricing_web['depends_on'] = ['pricing']
    pricing_web['healthcheck'] = {'test': ['CMD', 'wget', '-qO-', 'http://127.0.0.1/up'], 'interval': '10s', 'timeout': '5s', 'retries': 18}
    cameras = application('cameras')
    cameras['environment'] = {'API_HOST': '127.0.0.1', 'API_PORT': '8001', 'NVR_IP': config.nvr_host,
        'RTSP_USER': config.nvr_user, 'RTSP_PASSWORD': config.nvr_password, 'CAMERA_API_KEY': credentials['camera_key'],
        'CAMERA_CHANNELS': ','.join(map(str, config.camera_channels))}
    cameras['healthcheck'] = python_health("import os,urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8001/api/cameras',headers={'X-API-Key':os.environ['CAMERA_API_KEY']}),timeout=3)")
    lights = application('lighting')
    lights['environment'] = {'CABEK_LIGHTS_PORT': '/dev/cabek-esp32'}
    device = selected_serial_device(config)
    if device:
        lights['devices'] = [f'{device.resolve()}:/dev/cabek-esp32']
        lights['group_add'] = [str(device.stat().st_gid)]
    lights['healthcheck'] = python_health("import http.client; c=http.client.HTTPConnection('127.0.0.1',9001,timeout=3); c.request('GET','/api/lights/set'); r=c.getresponse(); assert r.status==405 and 'POST' in r.getheader('Allow','')")
    ocr = application('ocr')
    ocr['environment'] = {'ECONSTAT_API_TOKEN': credentials['ocr_token'], 'EASYOCR_MODULE_PATH': '/models',
                          'OMP_NUM_THREADS': '4', 'TORCH_HOME': '/tmp/torch'}
    ocr['volumes'] = [f'{data}/ocr-models:/models', f'{data}/ocr-output:/app/output']
    ocr['healthcheck'] = python_health("import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/health',timeout=3)")
    backend = application('backend')
    backend['environment'] = {'CABEK_DOSSIERS_DIR': '/data/dossiers', 'CABEK_RUNTIME_DIR': '/data/runtime',
        'CABEK_MODELS_DIR': '/app/models', 'CABEK_MOCK_PHOTOS_DIR': '/data/demo-photos',
        'CABEK_DEMO_DIR': '/data/private-demo', 'CABEK_DEMO_SECRET_FILE': '/data/private-demo/secret.json', 'CABEK_TUNNEL_MODE': 'tiandy',
        'AUTOESTIMATE_BASE_URL': 'http://pricing-web/api/v1', 'AUTOESTIMATE_TOKEN': credentials.get('autoestimate_token', ''),
        'CABEK_TIANDY_API_URL': 'http://127.0.0.1:8001', 'CABEK_TIANDY_API_KEY': credentials['camera_key'],
        'CABEK_LIGHTS_ENABLED': '1', 'CABEK_LIGHTS_API_URL': 'http://127.0.0.1:9001',
        'CABEK_INTERNAL_LIGHTS_ENABLED': 'true', 'CABEK_INTERNAL_LIGHTS_URL': config.interior_url,
        'CABEK_INTERNAL_LIGHTS_SWITCH_ID': str(config.interior_switch_id),
        'CABEK_ECONSTAT_API_URL': 'http://127.0.0.1:8002', 'CABEK_ECONSTAT_API_TOKEN': credentials['ocr_token'],
        'OMP_NUM_THREADS': '4', 'OPENBLAS_NUM_THREADS': '4', 'TORCH_HOME': '/tmp/torch'}
    backend['volumes'] = [f'{data}/{name}:/data/{name}' for name in ('dossiers', 'runtime', 'private-demo')] + [f'{data}/demo-photos:/data/demo-photos:ro']
    backend['depends_on'] = {name: {'condition': 'service_healthy'} for name in ('gateway', 'cameras', 'lighting', 'ocr', 'pricing-web')}
    backend['healthcheck'] = python_health("import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/settings/operation',timeout=3)")
    frontend = application('frontend')
    frontend['environment'] = {'CABEK_APPLICATION_PORT': str(config.app_port)}
    frontend['healthcheck'] = {'test': ['CMD', 'wget', '-qO-', 'http://127.0.0.1/health'], 'interval': '10s', 'timeout': '5s', 'retries': 18}
    services = {'gateway': gateway, 'database': database, 'pricing': pricing, 'pricing-web': pricing_web,
                'cameras': cameras, 'lighting': lights, 'ocr': ocr, 'backend': backend, 'frontend': frontend}
    # Retain native tuning while Manager resolves connection keys, paths and real station mode.
    protected = {'CABEK_MOCK_PHOTOS_DIR', 'CABEK_TUNNEL_MODE', 'CABEK_MANAGER_KEY', 'CABEK_RUNTIME_DIR',
                 'CABEK_DOSSIERS_DIR', 'CABEK_MODELS_DIR', 'API_HOST', 'API_PORT', 'ECONSTAT_OUTPUT_DIR'}
    for component, values in config.native_environment.items():
        if component in services:
            managed = services[component].get('environment', {})
            services[component]['environment'] = {**{key: value for key, value in values.items() if key not in protected}, **managed}
    return escape_compose_literals({'name': 'cabek-ai-manager', 'services': services,
                                   'volumes': {'pricing_database': {}}, 'networks': {'default': {}}})
