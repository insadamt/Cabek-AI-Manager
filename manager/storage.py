"""Atomically persist private configuration, operations, and installed revisions.

Depends on a writable installation directory. Atomic rename prevents a crash
from leaving partially written state; a process lock protects destructive work.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = RLock()

    def read(self, name, default=None):
        with self.lock:
            path = self.root / (name + ".json")
            if not path.exists():
                return default
            return json.loads(path.read_text())

    def write(self, name, value):
        with self.lock:
            path = self.root / (name + ".json")
            temporary = path.with_name(path.name + "." + uuid4().hex)
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(descriptor, "w") as stream:
                    json.dump(value, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)

    @contextmanager
    def operation_lock(self):
        with (self.root / "operation.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Another installation or update is running.") from None
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
