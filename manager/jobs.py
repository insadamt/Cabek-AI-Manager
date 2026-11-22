"""Serialize long installation jobs and persist their progress for the local interface.

Depends on Store and a single executor. Interrupted work is reported explicitly
after restart rather than silently displayed as a successful installation.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Jobs:
    def __init__(self, store, on_complete=None):
        self.store = store
        self.on_complete = on_complete
        self.lock = RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cabek-manager")
        previous = store.read("job", {})
        if previous.get("status") == "running":
            previous.update(status="interrupted", finished_at=timestamp(),
                            error="Manager restarted during this operation. Check service status before retrying.")
            store.write("job", previous)

    def snapshot(self):
        return self.store.read("job", None)

    def log(self, message):
        with self.lock:
            job = self.snapshot()
            if job:
                job["events"] = (job["events"] + [{"at": timestamp(), "message": message}])[-150:]
                self.store.write("job", job)

    def submit(self, name, operation, allow_pending_restart=False):
        with self.lock:
            if (self.snapshot() or {}).get("status") == "running":
                raise ValueError("Another operation is already running.")
            if self.store.read("manager-next", None) and not allow_pending_restart:
                raise ValueError("The manager update is restarting. Reload the interface shortly.")
            job = {"id": uuid4().hex, "name": name, "status": "running", "started_at": timestamp(), "events": []}
            self.store.write("job", job)
            self.executor.submit(self.run, operation)
            return job

    def run(self, operation):
        try:
            with self.store.operation_lock():
                operation(self.log)
            status, error = "completed", None
        except Exception as failure:
            status, error = "failed", str(failure)
        with self.lock:
            job = self.snapshot()
            job.update(status=status, error=error, finished_at=timestamp())
            self.store.write("job", job)
        if status == "completed" and self.on_complete:
            self.on_complete()

    def close(self):
        self.executor.shutdown(wait=True)
