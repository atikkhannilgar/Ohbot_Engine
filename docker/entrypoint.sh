#!/bin/sh
set -e

# Seed config.json from the example if the mounted volume is empty.
if [ ! -f /app/config.json ]; then
  echo "[docker] config.json missing — copying config.example.json"
  cp /app/config.example.json /app/config.json
fi

exec "$@"
