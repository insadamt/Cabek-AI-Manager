"""Keep the local manager available across its own published-release updates.

Depends only on Python's standard library and the initial virtualenv. New
manager code uses the same private installation directory and a separate venv.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("CABEK_MANAGER_HOME", ROOT / ".local")).resolve()


def read(name):
    path = HOME / (name + ".json")
    return json.loads(path.read_text()) if path.exists() else None


def main():
    HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    initial = {"source": str(ROOT), "python": str(ROOT / ".venv/bin/python")}
    while True:
        active = read("manager-active") or initial
        previous = active
        pending = HOME / "manager-next.json"
        candidate_update = pending.exists()
        if candidate_update:
            (HOME / "manager-previous.json").write_text(json.dumps(previous))
            pending.replace(HOME / "manager-active.json")
            active = read("manager-active")
        environment = dict(os.environ, CABEK_MANAGER_HOME=str(HOME), CABEK_MANAGER_BOOTSTRAP="1")
        process = subprocess.Popen([active["python"], "-m", "manager", *sys.argv[1:]],
                                   cwd=active["source"], env=environment)
        if not candidate_update:
            code = process.wait()
            if code == 42 and pending.exists():
                continue
            return code
        port = 8179
        if "--port" in sys.argv:
            port = int(sys.argv[sys.argv.index("--port") + 1])
        healthy = False
        for _ in range(60):
            if process.poll() is not None:
                break
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                    payload = json.load(response)
                    healthy = payload["version"] == active["revision"]["tag"].lstrip("v")
                if healthy:
                    break
            except OSError:
                pass
            time.sleep(1)
        if not healthy:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            (HOME / "manager-active.json").write_text(json.dumps(previous))
            installed = read("installed") or {}
            if previous.get("revision"):
                installed["manager"] = previous["revision"]
            else:
                installed.pop("manager", None)
            (HOME / "installed.json").write_text(json.dumps(installed))
            print("The new manager did not become healthy. Restoring the previous manager.", flush=True)
            continue
        code = process.wait()
        if code == 42 and pending.exists():
            continue
        return code


if __name__ == "__main__":
    raise SystemExit(main())
