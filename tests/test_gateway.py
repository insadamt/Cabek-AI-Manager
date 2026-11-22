"""Verify native HTTP transparency and durable admission with a real local upstream.

Depends on lightweight stdlib HTTP threads and FastAPI TestClient; no browser,
Docker daemon, application modifications, or physical device commands are used.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
import time
import pytest
from fastapi.testclient import TestClient
from manager.gateway import create_app


@pytest.fixture
def station(tmp_path):
    admitted, finish = Event(), Event()
    requests = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            requests.append((self.path, body, dict(self.headers)))
            if self.path == '/api/wait':
                admitted.set()
                finish.wait(5)
            self.send_response(422 if self.path == '/api/invalid' else 201)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('X-Native', 'unchanged')
            self.send_header('Set-Cookie', 'first=1')
            self.send_header('Set-Cookie', 'second=2')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            if self.path == '/api/preview':
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                admitted.set()
                try:
                    for _ in range(100):
                        body=b'--frame\r\nContent-Type: image/jpeg\r\n\r\nbytes\r\n'
                        self.wfile.write(format(len(body),'x').encode()+b'\r\n'+body+b'\r\n')
                        self.wfile.flush()
                        time.sleep(.02)
                    self.wfile.write(b'0\r\n\r\n')
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'{}')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    app = create_app(upstream=f'http://127.0.0.1:{server.server_port}', key='private-gateway-key', marker=tmp_path/'closed')
    with TestClient(app) as client:
        yield client, requests, admitted, finish, app
    finish.set()
    server.shutdown()
    server.server_close()
    thread.join()


HEADERS = {'X-Cabek-Gateway-Key': 'private-gateway-key'}


def test_native_multipart_bytes_headers_query_and_status_are_preserved(station):
    client, requests, *_ = station
    body = b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="native.bin"\r\n\r\n\x00\xff\r\n--boundary--\r\n'
    response = client.post('/api/upload?path=a%2Fb', content=body, headers={'Content-Type': 'multipart/form-data; boundary=boundary', 'Authorization': 'Bearer native-client', 'X-Forwarded-For': 'untrusted'})
    assert response.status_code == 201 and response.content == body
    assert response.headers['x-native'] == 'unchanged'
    assert response.headers.get_list('set-cookie') == ['first=1', 'second=2']
    assert requests[0][0] == '/api/upload?path=a%2Fb'
    assert requests[0][1] == body
    assert {key.lower(): value for key, value in requests[0][2].items()}['authorization'] == 'Bearer native-client'
    assert 'x-forwarded-for' not in {key.lower() for key in requests[0][2]}


def test_native_error_payload_is_not_rewritten(station):
    response = station[0].post('/api/invalid', content=b'native-error')
    assert response.status_code == 422 and response.content == b'native-error'


def test_control_requires_private_key_and_strict_boolean(station):
    client = station[0]
    assert client.post('/_manager/gate', json={'closed': True}).status_code == 403
    assert client.post('/_manager/gate', json={'closed': 'yes'}, headers=HEADERS).status_code == 422


def test_gate_blocks_new_mutations_but_finishes_admitted_requests(station):
    client, _, admitted, finish, app = station
    responses = []
    thread = Thread(target=lambda: responses.append(client.post('/api/wait', content=b'accepted')))
    thread.start()
    assert admitted.wait(2)
    assert client.get('/_manager/status', headers=HEADERS).json()['active_mutations'] == 1
    assert client.post('/_manager/gate', json={'closed': True}, headers=HEADERS).status_code == 200
    assert client.post('/api/new', content=b'new').status_code == 503
    assert client.get('/api/progress').status_code == 200
    finish.set()
    thread.join(timeout=3)
    assert not thread.is_alive() and responses[0].content == b'accepted'
    assert app.state.gate.active_mutations == 0


def test_closed_state_survives_gateway_replacement(station):
    client, _, _, _, app = station
    client.post('/_manager/gate', json={'closed': True}, headers=HEADERS)
    replacement = create_app(key='private-gateway-key', marker=app.state.gate.marker)
    assert replacement.state.gate.closed
    client.post('/_manager/gate', json={'closed': False}, headers=HEADERS)
    assert not create_app(key='private-gateway-key', marker=app.state.gate.marker).state.gate.closed


def test_maintenance_closes_native_preview_stream_without_blocking_reads(station):
    client, _, admitted, _, app = station
    results=[]
    thread=Thread(target=lambda:results.append(client.get('/api/preview')))
    thread.start()
    assert admitted.wait(2)
    deadline=time.monotonic()+2
    while not app.state.gate.previews and time.monotonic()<deadline:
        time.sleep(.01)
    assert app.state.gate.previews
    client.post('/_manager/gate', json={'closed':True}, headers=HEADERS)
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert results[0].status_code==200
    assert results[0].headers['content-type']=='multipart/x-mixed-replace; boundary=frame'
    assert client.get('/api/progress').status_code==200
