#!/usr/bin/env bash
# Bootstrap the local manager API; depends on Python 3.11+, Docker, and GitHub access.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python bootstrap.py "$@"
