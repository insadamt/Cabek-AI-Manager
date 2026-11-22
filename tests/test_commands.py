"""Check command isolation, private output handling, and bounded execution.

Depends on harmless local Python subprocesses, never Docker or workstation data.
"""
import sys
import time
import pytest

from manager.commands import CommandRunner


def test_secret_output_is_redacted_in_logs_and_errors():
    events = []
    runner = CommandRunner(['private-token-value'], events.append)
    runner.run([sys.executable, '-c', "print('private-token-value')"])
    assert events == ['[redacted]\n']
    with pytest.raises(RuntimeError) as failure:
        runner.run([sys.executable, '-c', "print('private-token-value'); raise SystemExit(1)"])
    assert 'private-token-value' not in str(failure.value)


def test_timeout_terminates_long_running_command():
    started = time.monotonic()
    with pytest.raises(RuntimeError, match='timed out'):
        CommandRunner().run([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=.1)
    assert time.monotonic() - started < 4


def test_large_private_output_is_streamed_to_file_without_logging(tmp_path):
    events = []
    output = tmp_path / 'database.sql'
    CommandRunner(log=events.append).run([sys.executable, '-c', "print('private database contents')"],
                                       output_path=output, quiet=True)
    assert output.read_text() == 'private database contents\n'
    assert events == []


def test_warnings_cannot_corrupt_sql_or_source_archives(tmp_path):
    output = tmp_path / 'archive.bin'
    CommandRunner().run([sys.executable, '-c', "import sys; sys.stdout.buffer.write(b'archive-bytes'); print('warning',file=sys.stderr)"],
                        output_path=output, quiet=True)
    assert output.read_bytes() == b'archive-bytes'
