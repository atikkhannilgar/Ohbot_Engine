#!/usr/bin/env bash
# Start the Dockerized engine + the host Avalonia GUI (auto-attaches to :8765).
#
# Prefer:  ./docker/compose up --build
# (same as this script — kept for compatibility)
#
# Why the GUI runs on the host: Avalonia needs a real desktop display. Docker Desktop
# on macOS cannot show a native UI window from inside a container.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BUILD=0
ENGINE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --engine-only) ENGINE_ONLY=1 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
  esac
done

if [[ ! -f config.json ]]; then
  echo "[start] copying config.example.json → config.json"
  cp config.example.json config.json
fi
mkdir -p ohbotData

echo "[start] starting engine (python -m obot --serve)…"
if [[ "$BUILD" -eq 1 ]]; then
  docker compose up --build -d obot
else
  docker compose up -d obot
fi

echo "[start] waiting for engine on ws://127.0.0.1:8765 …"
ready=0
for _ in $(seq 1 60); do
  if python3 -c 'import socket; s=socket.create_connection(("127.0.0.1",8765),1); s.close()' 2>/dev/null; then
    ready=1
    break
  fi
  sleep 0.5
done

if [[ "$ready" -ne 1 ]]; then
  echo "[start] engine did not become ready; check: docker compose logs obot" >&2
  exit 1
fi
echo "[start] engine is up (ws://127.0.0.1:8765)"

if [[ "$ENGINE_ONLY" -eq 1 ]]; then
  echo "[start] --engine-only: skipping GUI (docker compose logs -f obot)"
  exec docker compose logs -f obot
fi

export DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.dotnet}"
export PATH="$DOTNET_ROOT:$PATH"

if ! command -v dotnet >/dev/null 2>&1; then
  echo "[start] 'dotnet' not found. Install .NET 10 SDK, or use: ./docker/compose up --engine-only" >&2
  exit 1
fi

echo "[start] opening GUI (auto-attach)…"
cd "$ROOT/gui"
exec dotnet run --project ObotControl.App/ObotControl.App.csproj -- \
  --host 127.0.0.1 --port 8765 --attach
