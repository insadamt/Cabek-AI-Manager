"""Proxy native application HTTP and close write admission during Manager updates.

Depends on FastAPI/httpx and a private Manager key. Application paths, payloads,
headers and loopback requests stay native; no application hooks are injected.
"""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import secrets
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

HOP_HEADERS = {b'connection', b'keep-alive', b'proxy-authenticate', b'proxy-authorization',
               b'te', b'trailer', b'transfer-encoding', b'upgrade'}
READ_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def transport_headers(headers):
    excluded = set(HOP_HEADERS)
    for name, value in headers:
        if name.lower() == b'connection':
            excluded.update(part.strip().lower() for part in value.split(b','))
    return [(name, value) for name, value in headers if name.lower() not in excluded]


class AdmissionGate:
    def __init__(self, marker):
        self.marker = Path(marker)
        self.closed = self.marker.exists()
        self.active_mutations = 0
        self.lock = asyncio.Lock()
        self.previews = set()

    async def admit(self, mutation):
        async with self.lock:
            if mutation and self.closed:
                return False
            if mutation:
                self.active_mutations += 1
            return True

    async def finish(self, mutation):
        if mutation:
            async with self.lock:
                self.active_mutations -= 1

    async def set_closed(self, closed):
        async with self.lock:
            if closed:
                self.marker.parent.mkdir(parents=True, exist_ok=True)
                self.marker.touch(mode=0o600)
            else:
                self.marker.unlink(missing_ok=True)
            self.closed = closed
        if closed:
            # Preview streams must not hold application shutdown open after accepted work finishes.
            for response in list(self.previews):
                await response.aclose()

    def status(self):
        return {'closed': self.closed, 'active_mutations': self.active_mutations}


def create_app(upstream=None, key=None, marker=None, transport=None):
    upstream = upstream or os.getenv('CABEK_UPSTREAM', 'http://127.0.0.1:8000')
    key = key if key is not None else os.getenv('CABEK_GATEWAY_KEY', '')
    gate = AdmissionGate(marker or os.getenv('CABEK_GATEWAY_MARKER', '/state/gateway-closed'))

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(connect=10, read=None, write=120, pool=30),
                                     follow_redirects=False, trust_env=False) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None)
    app.state.gate = gate

    def authorized(request):
        return bool(key and secrets.compare_digest(request.headers.get('x-cabek-gateway-key', ''), key))

    @app.get('/_manager/health')
    def health():
        return {'status': 'ok'}

    @app.get('/_manager/status')
    def status(request: Request):
        return gate.status() if authorized(request) else JSONResponse({'error': 'Manager credentials required.'}, status_code=403)

    @app.post('/_manager/gate')
    async def set_gate(payload: dict, request: Request):
        if not authorized(request):
            return JSONResponse({'error': 'Manager credentials required.'}, status_code=403)
        if set(payload) != {'closed'} or type(payload['closed']) is not bool:
            return JSONResponse({'error': 'A closed boolean is required.'}, status_code=422)
        await gate.set_closed(payload['closed'])
        return gate.status()

    @app.api_route('/{path:path}', methods=['GET', 'HEAD', 'OPTIONS', 'POST', 'PUT', 'PATCH', 'DELETE'])
    async def forward(path: str, request: Request):
        if path.startswith('_manager/'):
            return JSONResponse({'error': 'Unknown Manager control.'}, status_code=404)
        mutation = request.method not in READ_METHODS
        if not await gate.admit(mutation):
            return JSONResponse({'error': {'code': 'maintenance', 'message': 'An update is in progress. Try again shortly.'}}, status_code=503)
        raw_path = request.scope.get('raw_path', request.url.path.encode()).decode('ascii')
        query = request.scope.get('query_string', b'').decode('ascii')
        url = upstream.rstrip('/') + raw_path + ('?' + query if query else '')
        headers = [(name, value) for name, value in transport_headers(request.headers.raw)
                   if name.lower() not in {b'host', b'x-forwarded-for', b'forwarded', b'x-cabek-gateway-key'}]
        try:
            outgoing = app.state.client.build_request(request.method, url, headers=headers, content=request.stream())
            response = await app.state.client.send(outgoing, stream=True)
        except (httpx.HTTPError, OSError):
            await gate.finish(mutation)
            return JSONResponse({'error': {'code': 'upstream_unavailable', 'message': 'The Cabek API is starting or unavailable.'}}, status_code=502)
        except BaseException:
            await gate.finish(mutation)
            raise
        is_preview = any(value in response.headers.get('content-type', '') for value in ('multipart/x-mixed-replace', 'text/event-stream'))
        if is_preview:
            if gate.closed:
                await response.aclose()
                await gate.finish(mutation)
                return JSONResponse({'error': 'Preview paused during maintenance.'}, status_code=503)
            gate.previews.add(response)

        async def response_body():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            except (httpx.ReadError, httpx.StreamClosed):
                if not (is_preview and gate.closed):
                    raise
            finally:
                gate.previews.discard(response)
                await response.aclose()
                await gate.finish(mutation)

        result = StreamingResponse(response_body(), status_code=response.status_code)
        result.raw_headers = transport_headers(response.headers.raw)
        return result

    return app
