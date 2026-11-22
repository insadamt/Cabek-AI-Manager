"""Run bounded argument-list commands and redact private values from operation logs.

Depends on installed Git and Docker executables. Commands never use a shell;
timeouts terminate the whole process group instead of leaving child builds alive.
"""
import os
import signal
import subprocess
import tempfile
import time
from urllib.parse import quote, quote_plus


class CommandRunner:
    def __init__(self, private_values=(), log=None):
        self.private_values = [variant for value in private_values if value for variant in (value, value.replace("$", "$$"), quote(value, safe=""), quote_plus(value))]
        self.log = log or (lambda message: None)

    def redact(self, value):
        for secret in self.private_values:
            value = value.replace(secret, "[redacted]")
        return value

    def run(self, arguments, *, cwd=None, timeout=300, env=None, input_text=None, quiet=False, output_path=None, progress_label=None):
        environment = {**os.environ, **(env or {})}
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                [str(arg) for arg in arguments], cwd=cwd, env=environment,
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=output, stderr=errors if output_path is not None else subprocess.STDOUT, start_new_session=True,
            )
            if input_text is not None:
                process.stdin.write(input_text.encode())
                process.stdin.close()
            started = time.monotonic()
            last_progress = started
            last_output_size = 0
            while process.poll() is None:
                if time.monotonic() - started > timeout:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise RuntimeError("Command timed out: " + str(arguments[0]))
                if (not quiet or progress_label) and time.monotonic() - last_progress >= 8:
                    size = os.fstat(output.fileno()).st_size
                    if progress_label:
                        self.log(f"{progress_label} · {size // 1024**2} MiB received")
                    elif size > last_output_size:
                        start = max(last_output_size, size - 5000)
                        progress = os.pread(output.fileno(), size - start, start).decode(errors="replace")
                        self.log(self.redact(progress))
                        last_output_size = size
                    else:
                        self.log(f"Still running {arguments[0]} · {int(time.monotonic() - started)} seconds")
                    last_progress = time.monotonic()
                time.sleep(0.1)
            output.seek(0)
            if output_path is not None and process.returncode:
                errors.seek(0)
                detail = self.redact(errors.read().decode(errors="replace")[-1500:])
                raise RuntimeError(f"Private data transfer failed ({arguments[0]}, exit {process.returncode}): " + detail)
            if output_path is not None and process.returncode == 0:
                import shutil
                with open(output_path, "wb") as destination:
                    shutil.copyfileobj(output, destination)
                os.chmod(output_path, 0o600)
                return str(output_path)
            text = output.read().decode(errors="replace")
            if not quiet and text.strip():
                self.log(self.redact(text[-12000:]))
            if process.returncode:
                raise RuntimeError(self.redact(text[-5000:]) or "Command failed: " + str(arguments[0]))
            return text
