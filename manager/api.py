"""Serve the local setup interface and long-running manager operations.

Depends on FastAPI, private state, and the orchestrator. Only localhost clients
and same-origin JSON actions can control Docker or change site settings.
"""
from contextlib import asynccontextmanager
import asyncio
import os
from threading import Timer
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from manager import VERSION
from manager.backend import request_backend
from manager.configuration import Configuration
from manager.jobs import Jobs
from manager.orchestrator import Orchestrator
from manager.storage import Store
from manager.system import compose_command, preflight, service_status


def create_app(root=None, watch_releases=True):
    store = Store(root or os.getenv("CABEK_MANAGER_HOME", Path(__file__).resolve().parents[1] / ".local"))
    configuration = Configuration(store)
    operations = Orchestrator(store, configuration)
    def restart_manager():
        if store.read("manager-next", None) and os.getenv("CABEK_MANAGER_BOOTSTRAP") == "1":
            # Commit job completion before the browser reconnects to the new manager process.
            Timer(3, lambda: os._exit(42)).start()
    jobs = Jobs(store, on_complete=restart_manager)

    @asynccontextmanager
    async def lifespan(app):
        async def poll_releases():
            while True:
                if (jobs.snapshot() or {}).get("status") != "running":
                    try:
                        await asyncio.to_thread(operations.check_updates)
                    except Exception:
                        pass
                await asyncio.sleep(900)
        watcher = asyncio.create_task(poll_releases()) if watch_releases else None
        try:
            yield
        finally:
            if watcher:
                watcher.cancel()
                try:
                    await watcher
                except asyncio.CancelledError:
                    pass
            jobs.close()

    app = FastAPI(title="Cabek AI Manager", version=VERSION, lifespan=lifespan)
    app.state.store = store
    app.state.operations = operations
    app.state.jobs = jobs

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        host = getattr(request.client, "host", "")
        if host not in ("127.0.0.1", "::1", "testclient"):
            return JSONResponse(status_code=403, content={"error": "Manager is available on the station PC only."})
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse(status_code=403, content={"error": "Use the local manager interface."})
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse(status_code=415, content={"error": "Send a JSON request."})
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def validation_error(request, error):
        if isinstance(error, ValidationError):
            return JSONResponse(status_code=400, content={"error": "; ".join(item["msg"] for item in error.errors())})
        return JSONResponse(status_code=400, content={"error": operations.create_runner().redact(str(error))})

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request, error):
        # Pydantic's default error response includes supplied secret field values.
        return JSONResponse(status_code=422, content={"error": "Invalid request fields or values."})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": VERSION}

    @app.get("/api/configuration")
    def get_configuration():
        return configuration.public()

    @app.put("/api/configuration")
    def save_configuration(payload: dict):
        if (jobs.snapshot() or {}).get("status") == "running":
            raise ValueError("Wait for the current operation before changing configuration.")
        configuration.save(dict(payload))
        return configuration.public()

    @app.get("/api/status")
    def status():
        config = configuration.load()
        return {"version": VERSION, "installed": store.read("installed", {}),
                "updates": store.read("updates", {"components": [], "updates_available": False}),
                "job": jobs.snapshot(), "application_url": f"http://localhost:{config.app_port}",
                "recovery_required": bool(store.read("transaction", None)),
                "configuration_pending": store.read("installed-configuration", None) != config.model_dump()}

    @app.get("/api/services")
    def services():
        try:
            return {"services": service_status(store, operations.create_runner()), "error": None}
        except (RuntimeError, OSError) as error:
            return {"services": [], "error": str(error)}

    @app.get("/api/prerequisites")
    def prerequisites():
        config = configuration.load()
        return preflight(operations.create_runner(), config.github_token)

    @app.get("/api/logs/{service}")
    def logs(service: str):
        compose = store.read("compose", {})
        if service not in compose.get("services", {}):
            raise ValueError("Unknown managed service.")
        output = operations.create_runner().run(compose_command(store, "logs", "--no-color", "--tail", "100", service), quiet=True)
        return {"text": operations.create_runner().redact(output)}

    @app.post("/api/check-updates")
    def check_updates():
        def operation(log):
            result = operations.check_updates()
            errors = [item["name"] + ": " + item["error"] for item in result["components"] if item["error"]]
            if errors:
                raise ValueError("\n".join(errors))
            log("Release check finished.")
        return jobs.submit("Check published releases", operation)

    @app.post("/api/install")
    def install():
        return jobs.submit("Install ecosystem", operations.install)

    @app.post("/api/update-all")
    def update_all():
        return jobs.submit("Update all repositories", operations.update_all)

    @app.post("/api/start")
    def start():
        if store.read("transaction", None):
            raise ValueError("Recover the interrupted operation first.")
        if not store.read("installed", {}):
            raise ValueError("Install the ecosystem first.")
        def operation(log):
            operations.create_runner(log).run(compose_command(store, "up", "-d", "--wait", "--wait-timeout", "180"), timeout=240)
            from manager.configuration import SiteConfig
            active = SiteConfig.model_construct(**store.read("installed-configuration", configuration.load().model_dump()))
            request_backend(active, configuration.ensure_credentials(), "maintenance", {"enabled": False})
        return jobs.submit("Start services", operation)

    @app.post("/api/stop")
    def stop():
        def operation(log):
            config = configuration.load()
            from manager.backend import drain
            try:
                drain(config, configuration.ensure_credentials(), log)
                operations.create_runner(log).run(compose_command(store, "stop"), timeout=120)
            except Exception:
                request_backend(config, configuration.ensure_credentials(), "maintenance", {"enabled": False})
                raise
        return jobs.submit("Stop services", operation)

    @app.post("/api/resume")
    def resume():
        if store.read("transaction", None):
            raise ValueError("Recover the interrupted operation first.")
        return request_backend(configuration.load(), configuration.ensure_credentials(), "maintenance", {"enabled": False})

    @app.post("/api/recover")
    def recover():
        return jobs.submit("Recover interrupted operation", operations.recover_interrupted_update, allow_pending_restart=True)

    app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent / "web", html=True), name="interface")
    return app
