"""Render one private Compose project from site settings and published revisions.

Depends on repository Dockerfiles and persistent host directories. Internal DNS
addresses and shared credentials are generated here instead of edited per repo.
"""
from pathlib import Path


def health(url):
    return {"test": ["CMD", "python", "-c", f"import urllib.request; urllib.request.urlopen('{url}',timeout=3)"],
            "interval": "10s", "timeout": "5s", "retries": 12, "start_period": "30s"}


def render_compose(root, config, credentials, revisions):
    root = Path(root).resolve()
    data = root / "data"
    for name in ("dossiers", "runtime", "mock-photos", "ocr-output", "ocr-models"):
        (data / name).mkdir(parents=True, exist_ok=True)
    project = "cabek-ai-manager"

    def source(key):
        return str(root / "sources" / key / revisions[key]["sha"])

    def application(key, target=None):
        build = {"context": source(key)}
        if target:
            build["target"] = target
        return {"build": build, "image": f"cabek-managed-{key}:{revisions[key]['sha'][:12]}" + ("-" + target if target else ""),
                "restart": "unless-stopped"}

    database = {
        "image": "mariadb:11.8", "restart": "unless-stopped",
        "environment": {"MARIADB_DATABASE": "cabek_autoestimate", "MARIADB_USER": "cabek",
                        "MARIADB_PASSWORD": credentials["db_password"],
                        "MARIADB_ROOT_PASSWORD": credentials["db_root_password"]},
        "volumes": ["pricing_database:/var/lib/mysql"],
        "healthcheck": {"test": ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"],
                        "interval": "5s", "timeout": "5s", "retries": 30, "start_period": "30s"},
    }
    pricing = application("autoestimate", "app")
    pricing["environment"] = {
        "APP_NAME": "Cabek AutoEstimate", "APP_ENV": "production", "APP_DEBUG": "false",
        "APP_KEY": credentials["app_key"], "APP_URL": "http://pricing-web",
        "LOG_CHANNEL": "stderr", "DB_CONNECTION": "mariadb", "DB_HOST": "database",
        "DB_PORT": "3306", "DB_DATABASE": "cabek_autoestimate", "DB_USERNAME": "cabek",
        "DB_PASSWORD": credentials["db_password"], "SESSION_DRIVER": "database",
        "CACHE_STORE": "database", "QUEUE_CONNECTION": "database", "AUTOESTIMATE_API_RATE_LIMIT": "600",
    }
    pricing["depends_on"] = {"database": {"condition": "service_healthy"}}
    pricing["volumes"] = [f"{source('autoestimate')}/data:/imports/bundled:ro"]
    for index, path in enumerate(config.dataset_paths):
        pricing["volumes"].append(f"{path}:/imports/custom-{index}:ro")
    pricing_web = application("autoestimate", "nginx")
    # The existing AutoEstimate Nginx configuration uses the upstream name app.
    pricing["networks"] = {"default": {"aliases": ["app"]}}
    pricing_web["depends_on"] = ["pricing"]
    pricing_web["healthcheck"] = {"test": ["CMD", "wget", "-qO-", "http://127.0.0.1/up"],
                                  "interval": "10s", "timeout": "5s", "retries": 12}
    backend = application("backend")
    backend["environment"] = {
        "CABEK_DOSSIERS_DIR": "/data/dossiers", "CABEK_RUNTIME_DIR": "/data/runtime",
        "CABEK_MODELS_DIR": "/app/models", "CABEK_TUNNEL_MODE": "tiandy" if config.profile == "station" else "mock",
        "CABEK_MOCK_PHOTOS_DIR": "/data/mock-photos", "CABEK_MANAGER_KEY": credentials["manager_key"],
        "AUTOESTIMATE_BASE_URL": "http://pricing-web/api/v1", "AUTOESTIMATE_TOKEN": credentials["autoestimate_token"],
        "CABEK_TIANDY_API_URL": "http://cameras:8001", "CABEK_TIANDY_API_KEY": credentials["camera_key"],
        "CABEK_LIGHTS_ENABLED": "1" if config.lighting_enabled else "0",
        "CABEK_LIGHTS_API_URL": "http://lighting:8001",
        "CABEK_INTERNAL_LIGHTS_ENABLED": "true" if config.interior_enabled else "false",
        "CABEK_INTERNAL_LIGHTS_URL": config.interior_url or "http://127.0.0.1",
        "CABEK_INTERNAL_LIGHTS_SWITCH_ID": str(config.interior_switch_id),
        "CABEK_ECONSTAT_API_URL": "http://ocr:8002",
        "CABEK_ECONSTAT_API_TOKEN": credentials["ocr_token"] if config.ocr_enabled else "",
        "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4",
    }
    backend["volumes"] = [f"{data}/{name}:/data/{name}" for name in ("dossiers", "runtime", "mock-photos")]
    backend["ports"] = [f"127.0.0.1:{config.api_port}:8000"]
    backend["healthcheck"] = health("http://127.0.0.1:8000/health")
    backend["depends_on"] = {"pricing-web": {"condition": "service_healthy"}}
    frontend = application("frontend")
    frontend["environment"] = {"CABEK_BACKEND_URL": "http://backend:8000", "CABEK_MANAGER_KEY": credentials["manager_key"]}
    frontend["ports"] = [f"127.0.0.1:{config.app_port}:80"]
    frontend["depends_on"] = {"backend": {"condition": "service_healthy"}}
    frontend["healthcheck"] = {"test": ["CMD", "wget", "-qO-", "http://127.0.0.1/health"],
                               "interval": "10s", "timeout": "5s", "retries": 12}
    services = {"database": database, "pricing": pricing, "pricing-web": pricing_web,
                "backend": backend, "frontend": frontend}
    if config.profile == "station":
        cameras = application("cameras")
        cameras["environment"] = {"API_HOST": "0.0.0.0", "API_PORT": "8001", "NVR_IP": config.nvr_host,
                                  "RTSP_USER": config.nvr_user, "RTSP_PASSWORD": config.nvr_password,
                                  "CAMERA_CHANNELS": ",".join(map(str, config.camera_channels)),
                                  "CAMERA_API_KEY": credentials["camera_key"]}
        cameras["healthcheck"] = health("http://127.0.0.1:8001/health")
        services["cameras"] = cameras
        backend["depends_on"]["cameras"] = {"condition": "service_healthy"}
    if config.lighting_enabled:
        lights = application("lighting")
        lights["environment"] = {"CABEK_LIGHTS_PORT": "/dev/cabek-esp32"}
        lights["devices"] = [f"{Path(config.serial_device).resolve()}:/dev/cabek-esp32"]
        lights["healthcheck"] = health("http://127.0.0.1:8001/health")
        services["lighting"] = lights
        backend["depends_on"]["lighting"] = {"condition": "service_healthy"}
    if config.ocr_enabled:
        ocr = application("ocr")
        ocr["environment"] = {"ECONSTAT_API_TOKEN": credentials["ocr_token"], "EASYOCR_MODULE_PATH": "/models",
                              "ECONSTAT_OUTPUT_DIR": "/output", "OMP_NUM_THREADS": "4"}
        ocr["volumes"] = [f"{data}/ocr-models:/models", f"{data}/ocr-output:/output"]
        ocr["healthcheck"] = health("http://127.0.0.1:8002/health")
        services["ocr"] = ocr
    return {"name": project, "services": services, "volumes": {"pricing_database": {}}, "networks": {"default": {}}}
