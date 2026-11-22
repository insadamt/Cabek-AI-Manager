"""Prepare a published manager revision for the persistent host bootstrap.

Depends on a separate virtualenv per revision. Dependency installation finishes
before the current manager exits, leaving the existing process usable on failure.
"""
import sys
from pathlib import Path
from manager import VERSION
from manager.releases import version_tuple


def prepare_manager(store, revision, runner, log):
    source = store.root / "sources/manager" / revision["sha"]
    if source.resolve() == Path(__file__).resolve().parents[1]:
        return None
    if version_tuple(revision["tag"]) == version_tuple(VERSION):
        # Pin the first installation to its published source archive as well.
        return {"source": str(source), "python": sys.executable, "revision": revision}
    environment = store.root / "manager-envs" / revision["sha"]
    python = environment / "bin/python"
    log("Preparing the manager update and its isolated dependencies.")
    runner.run([sys.executable, "-m", "venv", str(environment)], timeout=90)
    runner.run([str(python), "-m", "pip", "install", "-r", str(source / "requirements.txt")], timeout=600)
    return {"source": str(source), "python": str(python), "revision": revision}
