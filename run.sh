#!/usr/bin/env bash
# SD-WAN Collector launcher (Linux / macOS).
#   ./run.sh                  -> web page (http://127.0.0.1:5050)
#   ./run.sh cli --url https://vmanage.example.com -u USER --customer "ACME"   -> command line
set -euo pipefail
cd "$(dirname "$0")"
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then echo "Python 3.9+ is required: https://www.python.org/downloads/"; exit 1; fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "Python 3.9 or newer is required."; exit 1; }
if [ ! -d .venv ]; then
  echo "First run: creating a private Python environment (.venv)..."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi
if [ "${1:-}" = "cli" ]; then shift; exec .venv/bin/python collect.py "$@"; fi
exec .venv/bin/python webapp.py "$@"
