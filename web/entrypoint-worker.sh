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
  setup-status)
    case "${2:-}" in prepare|error) ;; *) exit 2 ;; esac
    exec python3 - "${WORKER_STATUS_FILE}" "$2" <<'STATUS'
import json
import os
from datetime import datetime
from pathlib import Path
import sys
path, phase = Path(sys.argv[1]), sys.argv[2]
failed = phase == "error"
payload = {"ready": False, "state": "error" if failed else "bootstrapping",
           "phase": phase, "progress": 0, "updated_at": datetime.now().isoformat(),
           "detail": "Preparation stopped. Check the terminal, then run ./bin/local_instance.sh weave again." if failed else "Web service starting. Runtime preparation follows in the terminal.",
           "substep": "Saved settings and data are kept." if failed else "Keep the setup terminal open."}
path.parent.mkdir(parents=True, exist_ok=True)
temporary = path.with_name("." + path.name + ".setup-tmp")
temporary.write_text(json.dumps(payload))
os.replace(temporary, path)
STATUS
    ;;
  prepare-runtime)
    python3 "${CLUSTERWEAVE_ROOT:-/clusterweave}/bin/bootstrap_versions.py" --observe
    shift
    exec python3 "${RUNTIME_PREPARATION}" prepare \
      --profile "$(runtime_profile)" \
      --manifest "${RUNTIME_PREPARATION_MANIFEST}" "$@"
    ;;
  check-runtime)
    python3 "${CLUSTERWEAVE_ROOT:-/clusterweave}/bin/bootstrap_versions.py" --observe
    shift
    exec python3 "${RUNTIME_PREPARATION}" check \
      --profile "$(runtime_profile)" \
      --manifest "${RUNTIME_PREPARATION_MANIFEST}" "$@"
    ;;
esac

# Only the dedicated Compose mount is automatically provisioned. Custom roots
# remain operator-managed and are never migrated here.
if [[ "${CLUSTERWEAVE_ACCESSION_CACHE_ROOT:-}" == /var/cache/clusterweave/accessions ]]; then
  install -d -m 0700 /var/cache/clusterweave/accessions
fi
runtime_operation=prepare
if [[ "${CLUSTERWEAVE_LOCAL_PREPARED_ONLY:-0}" == 1 ]]; then
  runtime_operation=check
fi
mkdir -p /data/jobs /data/queue /data/worker
python3 "${CLUSTERWEAVE_ROOT:-/clusterweave}/bin/bootstrap_versions.py" --observe --scope startup
log "Preparing ClusterWeave worker runtime ..."
if ! python3 "${RUNTIME_PREPARATION}" "${runtime_operation}" \
  --profile "$(runtime_profile)" \
  --scope startup \
  --keep-going \
  --manifest "${RUNTIME_PREPARATION_MANIFEST}" \
  --status-file "${WORKER_STATUS_FILE}"; then
  log "WARNING: runtime preparation is incomplete; unavailable stages will remain disabled."
fi

log "Starting ClusterWeave worker ..."
exec python3 /app/worker.py
