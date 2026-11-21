"""Inspect local prerequisites and Docker state without changing existing projects.

Depends on the host Docker socket, GitHub credentials, and Linux serial devices.
Only the manager's explicitly named Compose project is controlled.
"""
import json
from pathlib import Path
import platform
import shutil
import socket


def preflight(runner, token=""):
    checks = []
    for name, command in (("docker", ["docker", "info", "--format", "{{.ServerVersion}}"]),
                          ("compose", ["docker", "compose", "version", "--short"]),
                          ("buildx", ["docker", "buildx", "version"]),
                          ("github", ["gh", "api", "user", "--jq", ".login"])):
        if name == "github" and token:
            checks.append({"name": name, "ok": True, "detail": "A token is configured; repository access is checked on release lookup."})
            continue
        try:
            text = runner.run(command, timeout=15, quiet=True).strip()
            checks.append({"name": name, "ok": True, "detail": text})
        except (RuntimeError, OSError) as error:
            checks.append({"name": name, "ok": False, "detail": str(error)})
    checks.append({"name": "linux", "ok": platform.system() == "Linux", "detail": platform.system()})
    usage = shutil.disk_usage(Path.cwd())
    checks.append({"name": "disk", "ok": usage.free > 8 * 1024**3, "detail": f"{usage.free // 1024**3} GiB available"})
    return {"ready": all(item["ok"] for item in checks), "checks": checks,
            "serial_devices": [str(path) for path in Path("/dev/serial/by-id").glob("*")]}


def require_free_ports(config):
    for port in (config.app_port, config.api_port):
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError:
                raise ValueError(f"Port {port} is already in use. Choose a free port in setup.") from None


def compose_command(store, *arguments):
    project = store.read("compose", {}).get("name", "cabek-ai-manager")
    return ["docker", "compose", "--project-name", project, "--file", str(store.root / "compose.json"), *arguments]


def service_status(store, runner):
    if not (store.root / "compose.json").exists():
        return []
    output = runner.run(compose_command(store, "ps", "--all", "--format", "json"), timeout=20, quiet=True)
    if not output.strip():
        return []
    if output.lstrip().startswith("["):
        return json.loads(output)
    return [json.loads(line) for line in output.splitlines() if line.strip()]
