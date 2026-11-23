"""Exercise real Docker health, imports, namespace replacement and SQL rollback.

Depends on an explicitly isolated, already built station supplied through
CABEK_TEST_HOME. Never targets the production project or restarts the host daemon.
"""
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from manager.backups import create_backup, restore_backup
from manager.commands import CommandRunner
from manager.configuration import Configuration
from manager.dossier_import import import_dossiers
from manager.lifecycle import remove_application_containers, start_database, start_applications
from manager.orchestrator import Orchestrator
from manager.storage import Store
from manager.system import compose_command

pytestmark = pytest.mark.skipif(not os.getenv('CABEK_TEST_HOME'), reason='Requires opt-in isolated Docker station')
IDENTITIES = ['DOS-ECONSTAT-875915-A', 'DOS-ECONSTAT-892246-A', 'DOS-ECONSTAT-892323-B', 'DOS-ECONSTAT-895671-A']


@pytest.fixture
def station():
    store = Store(os.environ['CABEK_TEST_HOME'])
    assert store.read('compose')['name'].startswith('cabek-audit-'), 'Production projects are forbidden'
    credentials = Configuration(store).ensure_credentials()
    runner = CommandRunner(credentials.values())
    return store, runner


def container_id(store, runner, service):
    return runner.run(compose_command(store, 'ps', '--all', '-q', service), quiet=True).strip()


def sql(store, runner, program):
    return runner.run(compose_command(store, 'exec', '-T', 'database', 'sh', '-c',
        'exec mariadb --batch --skip-column-names --user=root --password="$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE"'),
        input_text=program, quiet=True)


def test_all_nine_services_have_healthy_software_and_exact_serialized_checks(station):
    store, runner = station
    normalized = json.loads(runner.run(compose_command(store, 'config', '--format', 'json'), quiet=True))
    assert len(normalized['services']) == 9
    for service, definition in normalized['services'].items():
        identity = container_id(store, runner, service)
        status = runner.run(['docker', 'inspect', identity, '--format', '{{.State.Health.Status}}'], quiet=True).strip()
        assert status == 'healthy', service
        actual = json.loads(runner.run(['docker', 'inspect', identity, '--format', '{{json .Config.Healthcheck.Test}}'], quiet=True))
        assert actual == definition['healthcheck']['test'], service


def test_gateway_frontend_backend_pricing_and_private_boundary(station):
    store, runner = station
    config = Configuration(store).load()
    for url in (f'http://127.0.0.1:{config.app_port}/health',
                f'http://127.0.0.1:{config.api_port}/_manager/health',
                f'http://127.0.0.1:{config.api_port}/api/settings/operation',
                f'http://127.0.0.1:{config.api_port}/api/vehicles/marques',
                f'http://127.0.0.1:{config.api_port}/api/cameras'):
        with urlopen(url, timeout=15) as response:
            assert response.status == 200
    with pytest.raises(HTTPError) as denied:
        urlopen(f'http://127.0.0.1:{config.api_port}/api/private-demo/templates', timeout=10)
    assert denied.value.code == 401
    code = "import os,json,urllib.request; r=urllib.request.Request('http://127.0.0.1:8001/api/cameras',headers={'X-API-Key':os.environ['CAMERA_API_KEY']}); assert len(json.load(urllib.request.urlopen(r))['cameras'])==4"
    runner.run(compose_command(store, 'exec', '-T', 'cameras', 'python', '-c', code), quiet=True)


def test_real_dossier_import_is_validated_additive_and_duplicate_safe(station):
    source = os.getenv('CABEK_TEST_DOSSIERS')
    if not source:
        pytest.skip('Supply actual dossier sources explicitly')
    store, runner = station
    events = []
    import_dossiers(store, runner, source, False, events.append, IDENTITIES)
    import_dossiers(store, runner, source, True, events.append, IDENTITIES)
    import_dossiers(store, runner, source, False, events.append, IDENTITIES)
    report = json.loads(events[-1].strip().splitlines()[-1])
    assert {item['id'] for item in report['dossiers']} == set(IDENTITIES)
    assert all(item['state'] == 'duplicate' for item in report['dossiers'])
    from manager.configuration import data_root
    data = data_root(store.root, Configuration(store).load())
    for identity in IDENTITIES:
        original = Path(source) / identity
        imported = data / 'dossiers' / identity
        for document in original.rglob('*'):
            if document.is_file() and document.suffix.lower() in ('.pdf', '.jpg', '.jpeg', '.png', '.webp'):
                assert (imported / document.relative_to(original)).read_bytes() == document.read_bytes()


def test_repeat_replacement_keeps_database_identity_and_persistent_files(station):
    store, runner = station
    database = container_id(store, runner, 'database')
    from manager.configuration import data_root
    data = data_root(store.root, Configuration(store).load())
    sentinel = data / 'ocr-models/restart-sentinel'
    sentinel.write_text('preserve-model-cache')
    credentials = store.read('credentials')
    remove_application_containers(store, runner)
    start_database(store, runner)
    start_applications(store, runner)
    assert container_id(store, runner, 'database') == database
    assert sentinel.read_text() == 'preserve-model-cache'
    assert store.read('credentials') == credentials


def test_real_mariadb_backup_restore_preserves_rows_credentials_and_model_cache(station):
    store, runner = station
    sql(store, runner, "CREATE TABLE IF NOT EXISTS audit_preservation (id INT PRIMARY KEY, value VARCHAR(40)); REPLACE INTO audit_preservation VALUES (1, 'before-update');")
    database = container_id(store, runner, 'database')
    credentials = store.read('credentials')
    runner.run(compose_command(store, 'stop', 'backend'), quiet=True)
    backup = create_backup(store, runner, lambda message: None)
    sql(store, runner, "UPDATE audit_preservation SET value='failed-update'; CREATE TABLE audit_new_table (id INT);")
    restore_backup(store, runner, backup, lambda message: None)
    assert sql(store, runner, 'SELECT value FROM audit_preservation WHERE id=1;').strip() == 'before-update'
    assert sql(store, runner, "SHOW TABLES LIKE 'audit_new_table';").strip() == ''
    assert container_id(store, runner, 'database') == database
    assert store.read('credentials') == credentials


def test_interrupted_pre_backup_recovery_restarts_previous_apps(station):
    store, runner = station
    database = container_id(store, runner, 'database')
    runner.run(compose_command(store, 'stop', 'backend'), quiet=True)
    store.write('transaction', {'first_install': False, 'backup': None, 'phase': 'before-backup'})
    Orchestrator(store, Configuration(store)).recover_interrupted_update(lambda message: None)
    assert store.read('transaction') is None
    assert container_id(store, runner, 'database') == database


def test_managed_initializer_repairs_previous_container_ownership(station):
    from manager.configuration import data_root
    from manager.runtime_storage import initialize_storage
    from manager.system import docker_is_rootless
    store, runner = station
    config = Configuration(store).load()
    compose = store.read('compose')
    data = data_root(store.root, config)
    program = "from pathlib import Path; import os; p=Path('/output/old-owner'); p.mkdir(exist_ok=True); f=p/'preserve.txt'; f.write_text('preserved'); os.chown(f,12345,12345); os.chown(p,12345,12345); p.chmod(0o700)"
    runner.run(['docker', 'run', '--rm', '--network', 'none', '--user', '0:0',
        '--mount', f'type=bind,source={data / "ocr-output"},target=/output',
        '--entrypoint', 'python', compose['services']['backend']['image'], '-c', program], quiet=True)
    initialize_storage(store.root, config, compose, runner, rootless=docker_is_rootless(runner))
    restored = data / 'ocr-output/old-owner/preserve.txt'
    assert restored.read_text() == 'preserved'
    assert restored.stat().st_uid == os.getuid()
    assert (data / 'private-demo').stat().st_mode & 0o777 == 0o700


def test_real_econstat_document_is_processed_by_ocr_http_api(station):
    import base64
    source = os.getenv('CABEK_TEST_DOSSIERS')
    if not source:
        pytest.skip('Supply actual E-Constat source documents explicitly')
    store, runner = station
    dossier = Path(source) / IDENTITIES[0]
    metadata = json.loads((dossier / 'metadata.json').read_text())
    content = {'registration': metadata['matricule'],
               'pdf': base64.b64encode((dossier / 'documents/econstat.pdf').read_bytes()).decode()}
    program = """
import base64,json,os,sys,urllib.request
value=json.load(sys.stdin)
boundary='cabek_audit_document_boundary'
body=(f'--{boundary}\\r\\nContent-Disposition: form-data; name="immatriculation"\\r\\n\\r\\n{value["registration"]}\\r\\n'
      f'--{boundary}\\r\\nContent-Disposition: form-data; name="constat"; filename="audit.pdf"\\r\\nContent-Type: application/pdf\\r\\n\\r\\n').encode()
body+=base64.b64decode(value['pdf'])+f'\\r\\n--{boundary}--\\r\\n'.encode()
request=urllib.request.Request('http://127.0.0.1:8002/api/v1/constats',data=body,headers={
 'Authorization':'Bearer '+os.environ['ECONSTAT_API_TOKEN'],
 'Content-Type':'multipart/form-data; boundary='+boundary})
with urllib.request.urlopen(request,timeout=240) as response:
 result=json.load(response)
 assert response.status==200 and result['schema_version']=='1.0'
 assert result['vehicle']['registration_match'] is True
 print('Real E-Constat PDF processed successfully through authenticated OCR API')
"""
    result = runner.run(compose_command(store, 'exec', '-T', 'ocr', 'python', '-c', program),
                        input_text=json.dumps(content), quiet=True, timeout=300)
    assert 'processed successfully' in result


def test_french_english_cpu_models_initialize_and_cached_document_ocr_succeeds(station):
    store, runner = station
    program = """
import easyocr,numpy as np
from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
reader=easyocr.Reader(['fr','en'],gpu=False,verbose=False)
image=Image.new('RGB',(1000,180),'white')
ImageDraw.Draw(image).text((35,45),'BONJOUR CABEK 123456',font=ImageFont.load_default(size=60),fill='black')
words=reader.readtext(np.asarray(image),detail=0)
assert any('CABEK' in word.upper() for word in words)
cached={p.name:p.stat().st_mtime_ns for p in Path('/models/model').glob('*.pth')}
assert cached
easyocr.Reader(['fr','en'],gpu=False,verbose=False)
assert cached=={p.name:p.stat().st_mtime_ns for p in Path('/models/model').glob('*.pth')}
"""
    runner.run(compose_command(store, 'exec', '-T', 'ocr', 'python', '-c', program), quiet=True, timeout=1200)


def test_complete_update_and_failed_update_rollback_use_real_docker(station, monkeypatch):
    from manager.catalog import COMPONENTS
    store, runner = station
    configuration = Configuration(store)
    targets = store.read('audit-sources')
    if not targets:
        pytest.skip('Requires local source snapshots from prepare_station.py')
    store.write('installed', targets)
    store.write('real-operation-configured', True)
    database = container_id(store, runner, 'database')
    credentials = store.read('credentials')
    updates = {'components': [{'key': component.key, 'name': component.name,
        'latest': targets[component.key], 'installed': targets[component.key],
        'update_available': False, 'error': None} for component in COMPONENTS]}
    # Only release lookup and host self-restart are replaced; Docker, SQL, model
    # initialization, admission, idle locks, backups and rollback remain real.
    monkeypatch.setattr(Orchestrator, 'check_updates', lambda self: updates)
    monkeypatch.setattr('manager.orchestrator.prepare_manager', lambda *args: None)
    configuration.save({'native_environment': {'backend': {'CABEK_AUDIT_REGRESSION': 'successful-update'}}})
    Orchestrator(store, configuration).update_all(lambda message: None)
    successful = store.read('installed-configuration')
    assert successful == configuration.load().model_dump()
    assert container_id(store, runner, 'database') == database
    assert store.read('credentials') == credentials
    configuration.save({'native_environment': {'backend': {'CABEK_AUDIT_REGRESSION': 'failed-update'}}})
    def interrupted_import(*args):
        raise RuntimeError('Deliberate integration failure after native migrations')
    monkeypatch.setattr(Orchestrator, 'import_datasets', interrupted_import)
    with pytest.raises(RuntimeError, match='Deliberate integration failure'):
        Orchestrator(store, configuration).update_all(lambda message: None)
    assert store.read('installed-configuration') == successful
    assert store.read('transaction') is None
    assert store.read('credentials') == credentials
    assert container_id(store, runner, 'database') == database
