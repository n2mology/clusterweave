#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8080}"
DATA_DIR="${DATA_DIR:-/data}"
CLUSTERWEAVE_UPLOAD_STAGING_DIR="${CLUSTERWEAVE_UPLOAD_STAGING_DIR:-${DATA_DIR}/.upload_staging}"
mkdir -p "${CLUSTERWEAVE_UPLOAD_STAGING_DIR}"
chmod 700 "${CLUSTERWEAVE_UPLOAD_STAGING_DIR}" 2>/dev/null || true
export CLUSTERWEAVE_UPLOAD_STAGING_DIR
export TMPDIR="${CLUSTERWEAVE_UPLOAD_STAGING_DIR}"

echo "[$(date +'%H:%M:%S')] [entrypoint] Starting ClusterWeave web server on port ${PORT} ..."
exec python3 /app/app.py
