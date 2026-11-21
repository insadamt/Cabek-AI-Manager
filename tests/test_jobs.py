"""Verify durable job outcomes and exclusive execution across asynchronous operations.

Depends on real worker threads and temporary storage, with no Docker side effects.
"""
from threading import Event
import pytest

from manager.jobs import Jobs
from manager.storage import Store


def test_job_completes_before_restart_callback(tmp_path):
    store = Store(tmp_path)
    callback = Event()
    def finished():
        assert store.read('job')['status'] == 'completed'
        callback.set()
    jobs = Jobs(store, on_complete=finished)
    try:
        jobs.submit('test operation', lambda log: log('step completed'))
        assert callback.wait(3)
        assert jobs.snapshot()['events'][0]['message'] == 'step completed'
    finally:
        jobs.close()


def test_only_one_operation_runs_at_once(tmp_path):
    jobs = Jobs(Store(tmp_path))
    started, release = Event(), Event()
    def work(log):
        started.set()
        release.wait(3)
    try:
        jobs.submit('first', work)
        assert started.wait(3)
        with pytest.raises(ValueError, match='Another'):
            jobs.submit('second', work)
    finally:
        release.set()
        jobs.close()


def test_restart_reports_interrupted_operation(tmp_path):
    store = Store(tmp_path)
    store.write('job', {'status': 'running', 'events': []})
    jobs = Jobs(store)
    try:
        assert jobs.snapshot()['status'] == 'interrupted'
    finally:
        jobs.close()
