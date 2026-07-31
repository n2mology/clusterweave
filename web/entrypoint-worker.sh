#!/usr/bin/env bash
set -euo pipefail

RUNTIME_PREPARATION="${RUNTIME_PREPARATION:-/clusterweave/bin/prepare_runtime.py}"
RUNTIME_PREPARATION_MANIFEST="${RUNTIME_PREPARATION_MANIFEST:-${CLUSTERWEAVE_SOFTWARE_ROOT:-/data/software}/runtime-preparation.v1.json}"
WORKER_STATUS_FILE="${WORKER_STATUS_FILE:-/data/worker/status.json}"

log() { echo "[$(date +'%H:%M:%S')] [entrypoint] $*"; }

runtime_profile() {
  if [[ "${CLUSTERWEAVE_RUNTIME_MODE:-}" == "lab-docker" ]]; then
    printf '%s\n' local-docker
  else
    printf '%s\n' external
  fi
}

case "${1:-}" in
  prepare-runtime)
    shift
    exec python3 "${RUNTIME_PREPARATION}" prepare \
      --profile "$(runtime_profile)" \
      --manifest "${RUNTIME_PREPARATION_MANIFEST}" "$@"
    ;;
  check-runtime)
    shift
    exec python3 "${RUNTIME_PREPARATION}" check \
      --profile "$(runtime_profile)" \
      --manifest "${RUNTIME_PREPARATION_MANIFEST}" "$@"
    ;;
esac

mkdir -p /data/jobs /data/queue /data/worker
log "Preparing ClusterWeave worker runtime ..."
if ! python3 "${RUNTIME_PREPARATION}" prepare \
  --profile "$(runtime_profile)" \
  --scope startup \
  --keep-going \
  --manifest "${RUNTIME_PREPARATION_MANIFEST}" \
  --status-file "${WORKER_STATUS_FILE}"; then
  log "WARNING: runtime preparation is incomplete; unavailable stages will remain disabled."
fi

log "Starting ClusterWeave worker ..."
exec python3 /app/worker.py
