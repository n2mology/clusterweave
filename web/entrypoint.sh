#!/usr/bin/env bash
set -euo pipefail

SERVICE_MODE="${SERVICE_MODE:-web}"
ANTISMASH_DB_DIR="${ANTISMASH_DB_DIR:-/databases/antismash}"
PFAM_DIR="${PFAM_DIR:-/databases/pfam}"
PFAM_HMM="${PFAM_DIR}/Pfam-A.hmm"
PFAM_URL="${PFAM_URL:-https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release/Pfam-A.hmm.gz}"
PORT="${PORT:-8080}"
PREPULL_CLINKER_IMAGE="${PREPULL_CLINKER_IMAGE:-1}"
CLINKER_DOCKER_IMAGE="${CLINKER_DOCKER_IMAGE:-quay.io/biocontainers/clinker-py:0.0.32--pyhdfd78af_0}"
PREPULL_BIGSCAPE_IMAGE="${PREPULL_BIGSCAPE_IMAGE:-1}"
BIGSCAPE_DOCKER_IMAGE="${BIGSCAPE_DOCKER_IMAGE:-ghcr.io/medema-group/big-scape:2.0.0-beta.6}"

log() { echo "[$(date +'%H:%M:%S')] [entrypoint] $*"; }
have() { command -v "$1" >/dev/null 2>&1; }

setup_worker_dependencies() {
  mkdir -p "${ANTISMASH_DB_DIR}" "${PFAM_DIR}" /data/jobs /data/queue

  if [[ ! -f "${ANTISMASH_DB_DIR}/.databases_downloaded" ]]; then
    log "Downloading antiSMASH databases to ${ANTISMASH_DB_DIR} ..."
    if download-antismash-databases --database-dir "${ANTISMASH_DB_DIR}"; then
      touch "${ANTISMASH_DB_DIR}/.databases_downloaded"
      log "antiSMASH databases ready."
    else
      log "WARNING: antiSMASH database download failed."
      touch "${ANTISMASH_DB_DIR}/.databases_downloaded_failed"
    fi
  else
    log "antiSMASH databases already present."
  fi

  if [[ ! -f "${PFAM_HMM}" ]]; then
    log "Downloading Pfam-A.hmm ..."
    pfam_gz="${PFAM_DIR}/Pfam-A.hmm.gz"
    if curl -fsSL --retry 3 -o "${pfam_gz}" "${PFAM_URL}"; then
      gunzip -f "${pfam_gz}"
      hmmpress "${PFAM_HMM}" || log "WARNING: hmmpress failed for Pfam-A.hmm"
      log "Pfam-A.hmm ready."
    else
      log "WARNING: Pfam-A.hmm download failed."
    fi
  else
    log "Pfam-A.hmm already present."
  fi

  if [[ "${PREPULL_CLINKER_IMAGE}" == "1" ]] && have docker; then
    log "Pre-pulling clinker image: ${CLINKER_DOCKER_IMAGE}"
    docker pull "${CLINKER_DOCKER_IMAGE}" || log "WARNING: clinker image pull failed (will retry at runtime)."
  fi

  if [[ "${PREPULL_BIGSCAPE_IMAGE}" == "1" ]] && have docker; then
    log "Pre-pulling BiG-SCAPE image: ${BIGSCAPE_DOCKER_IMAGE}"
    docker pull "${BIGSCAPE_DOCKER_IMAGE}" || log "WARNING: BiG-SCAPE image pull failed (will retry at runtime)."
  fi
}

case "${SERVICE_MODE}" in
  web)
    mkdir -p /data/jobs /data/queue
    log "Starting ClusterWeave web server on port ${PORT} ..."
    exec python3 /app/app.py
    ;;
  worker)
    setup_worker_dependencies
    log "Starting ClusterWeave worker ..."
    exec python3 /app/worker.py
    ;;
  *)
    log "ERROR: unknown SERVICE_MODE=${SERVICE_MODE} (expected web or worker)"
    exit 1
    ;;
esac
