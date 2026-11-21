"""Drain admitted Cabek work through its authenticated management API.

Depends on backend manager-control routes. A timeout leaves the installed
version running and releases maintenance rather than terminating a live scan.
"""
import json
import time
from urllib.request import Request, urlopen


def request_backend(config, credentials, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(f"http://127.0.0.1:{config.api_port}/api/manager/{path}", data=data,
                      headers={"Content-Type": "application/json", "X-Cabek-Manager-Key": credentials["manager_key"]})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def drain(config, credentials, log, timeout=1900):
    request_backend(config, credentials, "maintenance", {"enabled": True})
    deadline = time.monotonic() + timeout
    log("Waiting for active capture, analysis, and OCR jobs to finish.")
    while request_backend(config, credentials, "status")["busy"]:
        if time.monotonic() > deadline:
            raise ValueError("Active work did not finish in time. No update was applied.")
        time.sleep(2)
    log("Station is idle; write admission remains closed during the update.")
