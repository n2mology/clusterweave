#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8080}"

echo "[$(date +'%H:%M:%S')] [entrypoint] Starting ClusterWeave web server on port ${PORT} ..."
exec python3 /app/app.py