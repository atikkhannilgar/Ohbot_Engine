#!/usr/bin/env bash
# Compatibility entry point for the local engine and desktop.
# First run: python3.12 scripts/setup.py
set -euo pipefail
OBOT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -x "$OBOT_ROOT/.venv/bin/python" ]]; then
  OBOT_RUNNER="$OBOT_ROOT/.venv/bin/python"
elif command -v python3.12 >/dev/null 2>&1; then
  OBOT_RUNNER="$(command -v python3.12)"
else
  echo "Python 3.12 is required. Install it, then run: python3.12 scripts/setup.py" >&2
  exit 1
fi
exec "$OBOT_RUNNER" "$OBOT_ROOT/scripts/run.py" "$@"
