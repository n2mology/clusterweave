#!/usr/bin/env bash
set -euo pipefail

ANTISMASH_DB_DIR="${ANTISMASH_DB_DIR:-/databases/antismash}"
PFAM_DIR="${PFAM_DIR:-/databases/pfam}"
PFAM_HMM="${PFAM_DIR}/Pfam-A.hmm"
PFAM_URL="${PFAM_URL:-https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release/Pfam-A.hmm.gz}"
AUTO_INSTALL_NCBI_CLI="${AUTO_INSTALL_NCBI_CLI:-1}"
NCBI_CLI_ROOT="${NCBI_CLI_ROOT:-${CLUSTERWEAVE_SOFTWARE_ROOT:-/data/software}/ncbi_cli}"
INSTALL_DIR="${INSTALL_DIR:-${NCBI_CLI_ROOT}}"
NCBI_CLI_INSTALLER="${NCBI_CLI_INSTALLER:-/clusterweave/install_ncbi_cli.sh}"
PREPULL_CLINKER_IMAGE="${PREPULL_CLINKER_IMAGE:-1}"
CLINKER_DOCKER_IMAGE="${CLINKER_DOCKER_IMAGE:-quay.io/biocontainers/clinker-py:0.0.32--pyhdfd78af_0}"
PREPULL_BIGSCAPE_IMAGE="${PREPULL_BIGSCAPE_IMAGE:-1}"
BIGSCAPE_DOCKER_IMAGE="${BIGSCAPE_DOCKER_IMAGE:-ghcr.io/medema-group/big-scape:2.0.0-beta.6}"
PREPULL_FUNBGCEX_IMAGE="${PREPULL_FUNBGCEX_IMAGE:-1}"
AUTO_BUILD_FUNBGCEX_DOCKER="${AUTO_BUILD_FUNBGCEX_DOCKER:-1}"
FUNBGCEX_DOCKER_IMAGE="${FUNBGCEX_DOCKER_IMAGE:-clusterweave-funbgcex:latest}"
FUNBGCEX_DOCKERFILE="${FUNBGCEX_DOCKERFILE:-/clusterweave/software/funbgcex/Dockerfile}"
FUNBGCEX_BUILD_CONTEXT="${FUNBGCEX_BUILD_CONTEXT:-/clusterweave/software/funbgcex}"

log() { echo "[$(date +'%H:%M:%S')] [entrypoint] $*"; }
have() { command -v "$1" >/dev/null 2>&1; }
phase_name() {
  case "$1" in
    antismash) echo "antiSMASH" ;;
    pfam) echo "Pfam" ;;
    ncbi_cli) echo "NCBI CLI" ;;
    funbgcex_image) echo "FunBGCeX" ;;
    clinker_image) echo "clinker" ;;
    bigscape_image) echo "BiG-SCAPE" ;;
    starting_worker) echo "Worker startup" ;;
    prepare) echo "Preparation" ;;
    *) echo "$1" ;;
  esac
}

normalize_substep() {
  local line="$1"
  line="${line//$'\r'/}"
  line="$(echo "$line" | sed 's/^\s\+//;s/\s\+$//')"
  if [[ -z "$line" ]]; then
    echo "Working..."
    return
  fi

  if [[ "$line" =~ ^Downloading[[:space:]]+([^:]+):[[:space:]]*([0-9.]+%) ]]; then
    echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"
    return
  fi

  if [[ "$line" =~ ^Downloading[[:space:]]+(.+) ]]; then
    echo "${BASH_REMATCH[1]}"
    return
  fi

  if [[ "$line" =~ ^Creating[[:space:]]+checksum[[:space:]]+of[[:space:]]+(.+) ]]; then
    echo "Checksum ${BASH_REMATCH[1]}"
    return
  fi

  if [[ "$line" =~ ^Extraction[[:space:]]+of[[:space:]]+(.+)[[:space:]]+finished[[:space:]]+successfully\.?$ ]]; then
    echo "Extracted ${BASH_REMATCH[1]}"
    return
  fi

  if [[ "$line" =~ ^PFAM[[:space:]]+file[[:space:]]+present ]]; then
    echo "PFAM validation complete"
    return
  fi

  if [[ "$line" =~ ^Status:[[:space:]]+(.+) ]]; then
    echo "${BASH_REMATCH[1]}"
    return
  fi

  if [[ "$line" =~ Installing[[:space:]]+NCBI[[:space:]]+CLI[[:space:]]+tools[[:space:]]+into[[:space:]]+(.+) ]]; then
    echo "Installing into ${BASH_REMATCH[1]}"
    return
  fi

  if [[ "$line" =~ Installed[[:space:]]+datasets[[:space:]]+and[[:space:]]+dataformat ]]; then
    echo "datasets and dataformat installed"
    return
  fi

  # curl progress line examples can include a trailing percentage token.
  if [[ "$line" =~ ([0-9]{1,3}(\.[0-9]+)?)%$ ]]; then
    echo "Transfer ${BASH_REMATCH[1]}%"
    return
  fi

  if [[ "$line" =~ ^Digest:[[:space:]]+(.+) ]]; then
    echo "Image digest verified"
    return
  fi

  echo "$line"
}

set_status() {
  local phase="$1"
  local progress="$2"
  local detail="$3"
  local substep="${4:-}"
  python3 - "$phase" "$progress" "$detail" "$substep" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app")
try:
    from runtime_capabilities import runtime_health
except Exception:
    runtime_health = None

phase = sys.argv[1]
progress = int(sys.argv[2])
detail = sys.argv[3]
substep = sys.argv[4]
capabilities = runtime_health() if runtime_health is not None else {}

payload = {
    "ready": False,
    "state": "bootstrapping",
    "phase": phase,
    "progress": max(0, min(100, progress)),
    "detail": detail,
    "substep": substep,
    "updated_at": datetime.now().isoformat(),
    "runtime": {
        "mode": capabilities.get("mode"),
        "engine": capabilities.get("engine"),
        "docker_ready": capabilities.get("docker_ready"),
        "docker_socket_enabled": capabilities.get("docker_socket_enabled"),
    } if capabilities else {},
    "capabilities": capabilities,
}

path = Path("/data/worker/status.json")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
PY
}

run_with_progress() {
  local phase="$1"
  local detail="$2"
  shift 2

  local phase_label
  phase_label="$(phase_name "$phase")"
  local progress=0
  local tmp_out
  tmp_out="$(mktemp)"

  set_status "$phase" "$progress" "$detail" "Starting ${phase_label}"

  "$@" >"$tmp_out" 2>&1 &
  local cmd_pid=$!
  local last_substep="Starting ${phase_label}"

  while kill -0 "$cmd_pid" >/dev/null 2>&1; do
    if [[ -s "$tmp_out" ]]; then
      local raw
      # Convert carriage-return progress updates into line breaks so we can
      # read in-place transfer updates (e.g. curl progress meter).
      raw="$(tr '\r' '\n' < "$tmp_out" | tail -n 1)"
      if [[ -n "$raw" ]]; then
        last_substep="$(normalize_substep "$raw")"
      fi
    fi

    if [[ "$phase" == "pfam" ]]; then
      # Derive progress from curl transfer percentage
      if [[ "$last_substep" =~ Transfer[[:space:]]+([0-9]+)(\.[0-9]+)?% ]]; then
        local transfer_pct="${BASH_REMATCH[1]}"
        if (( transfer_pct > progress )); then progress="$transfer_pct"; fi
      else
        if (( progress < 1 )); then progress=1; fi
      fi
      if (( progress > 99 )); then progress=99; fi

    elif [[ "$phase" == "clinker_image" || "$phase" == "bigscape_image" ]]; then
      # Count docker pull layers to derive progress:
      # "Pulling fs layer" lines = total layers seen
      # "Pull complete"    lines = layers fully done
      local total_layers done_layers
      total_layers="$(grep -c 'Pulling fs layer' "$tmp_out" 2>/dev/null || true)"
      done_layers="$(grep -c 'Pull complete'     "$tmp_out" 2>/dev/null || true)"
      if (( total_layers > 0 )); then
        local layer_pct=$(( done_layers * 100 / total_layers ))
        if (( layer_pct > progress )); then progress="$layer_pct"; fi
        last_substep="Layers ${done_layers}/${total_layers} complete"
      else
        # No layers seen yet — just show a small initial tick
        if (( progress < 2 )); then progress=2; fi
      fi
      if (( progress > 99 )); then progress=99; fi

    else
      if (( progress < 99 )); then progress=$((progress + 1)); fi
    fi

    set_status "$phase" "$progress" "$detail" "$last_substep"
    sleep 2
  done

  local exit_code=0
  wait "$cmd_pid" || exit_code=$?

  if [[ -s "$tmp_out" ]]; then
    while IFS= read -r line; do
      [[ -n "$line" ]] && echo "$line"
    done < "$tmp_out"
  fi
  rm -f "$tmp_out"

  if (( exit_code == 0 )); then
    set_status "$phase" 100 "$detail" "Completed ${phase_label}"
    return 0
  fi
  set_status "$phase" 100 "$detail" "${phase_label} failed"
  return "$exit_code"
}

mkdir -p "${ANTISMASH_DB_DIR}" "${PFAM_DIR}" /data/jobs /data/queue /data/worker
set_status "prepare" 100 "Preparing worker bootstrap" "Worker bootstrap plan created"

if [[ ! -f "${ANTISMASH_DB_DIR}/.databases_downloaded" ]]; then
  log "Downloading antiSMASH databases to ${ANTISMASH_DB_DIR} ..."
  if run_with_progress "antismash" "Downloading antiSMASH databases" download-antismash-databases --database-dir "${ANTISMASH_DB_DIR}"; then
    touch "${ANTISMASH_DB_DIR}/.databases_downloaded"
    log "antiSMASH databases ready."
    set_status "antismash" 100 "antiSMASH databases ready" "Database bundle available"
  else
    log "WARNING: antiSMASH database download failed."
    touch "${ANTISMASH_DB_DIR}/.databases_downloaded_failed"
    set_status "antismash" 100 "antiSMASH database download failed; continuing" "Continuing with partial bootstrap"
  fi
else
  log "antiSMASH databases already present."
  set_status "antismash" 100 "antiSMASH databases already present" "Using cached antiSMASH databases"
fi

ncbi_cli_ready() {
  have datasets && return 0
  [[ -x "${NCBI_CLI_ROOT}/datasets" ]] && return 0
  [[ -f "${NCBI_CLI_ROOT}/datasets.exe" ]] && return 0
  return 1
}

if [[ ! -f "${PFAM_HMM}" ]]; then
  log "Downloading Pfam-A.hmm ..."
  pfam_gz="${PFAM_DIR}/Pfam-A.hmm.gz"
  if run_with_progress "pfam" "Downloading Pfam-A database" curl -fL --retry 3 --show-error --progress-bar -o "${pfam_gz}" "${PFAM_URL}"; then
    run_with_progress "pfam" "Preparing Pfam-A database" gunzip -f "${pfam_gz}" || true
    run_with_progress "pfam" "Indexing Pfam-A database" hmmpress "${PFAM_HMM}" || log "WARNING: hmmpress failed for Pfam-A.hmm"
    log "Pfam-A.hmm ready."
    set_status "pfam" 100 "Pfam-A database ready" "Pfam index ready"
  else
    log "WARNING: Pfam-A.hmm download failed."
    set_status "pfam" 100 "Pfam-A download failed; continuing" "Continuing with partial bootstrap"
  fi
else
  log "Pfam-A.hmm already present."
  set_status "pfam" 100 "Pfam-A database already present" "Using cached Pfam database"
fi

if [[ "${AUTO_INSTALL_NCBI_CLI}" == "1" ]]; then
  if ncbi_cli_ready; then
    log "NCBI datasets CLI already present."
    set_status "ncbi_cli" 100 "NCBI Datasets CLI ready" "Using cached datasets/dataformat"
  elif [[ -f "${NCBI_CLI_INSTALLER}" ]]; then
    log "Installing NCBI datasets CLI into ${NCBI_CLI_ROOT} ..."
    mkdir -p "${NCBI_CLI_ROOT}"
    if run_with_progress "ncbi_cli" "Installing NCBI Datasets CLI" \
      env PROJECT_ROOT=/clusterweave INSTALL_DIR="${INSTALL_DIR}" bash "${NCBI_CLI_INSTALLER}"; then
      set_status "ncbi_cli" 100 "NCBI Datasets CLI ready" "datasets/dataformat installed"
      log "NCBI datasets CLI ready."
    else
      log "WARNING: NCBI datasets CLI install failed; accession jobs will stay unavailable until it is installed."
      set_status "ncbi_cli" 100 "NCBI Datasets CLI unavailable" "Install failed; accession jobs will be rejected"
    fi
  else
    log "WARNING: NCBI CLI installer missing: ${NCBI_CLI_INSTALLER}"
    set_status "ncbi_cli" 100 "NCBI Datasets CLI unavailable" "Installer missing"
  fi
else
  set_status "ncbi_cli" 100 "Skipping NCBI Datasets CLI install" "Auto-install disabled"
fi

if [[ "${PREPULL_CLINKER_IMAGE}" == "1" ]] && have docker; then
  log "Pre-pulling clinker image: ${CLINKER_DOCKER_IMAGE}"
  run_with_progress "clinker_image" "Pulling clinker container image" docker pull "${CLINKER_DOCKER_IMAGE}" || log "WARNING: clinker image pull failed (will retry at runtime)."
  set_status "clinker_image" 100 "clinker container image ready" "Image ready"
else
  set_status "clinker_image" 100 "Skipping clinker image pre-pull" "Pre-pull disabled"
fi

if [[ "${PREPULL_BIGSCAPE_IMAGE}" == "1" ]] && have docker; then
  log "Pre-pulling BiG-SCAPE image: ${BIGSCAPE_DOCKER_IMAGE}"
  run_with_progress "bigscape_image" "Pulling BiG-SCAPE container image" docker pull "${BIGSCAPE_DOCKER_IMAGE}" || log "WARNING: BiG-SCAPE image pull failed (will retry at runtime)."
  set_status "bigscape_image" 100 "BiG-SCAPE container image ready" "Image ready"
else
  set_status "bigscape_image" 100 "Skipping BiG-SCAPE image pre-pull" "Pre-pull disabled"
fi

if [[ "${PREPULL_FUNBGCEX_IMAGE}" == "1" && "${AUTO_BUILD_FUNBGCEX_DOCKER}" == "1" ]] && have docker; then
  if docker image inspect "${FUNBGCEX_DOCKER_IMAGE}" >/dev/null 2>&1; then
    log "FunBGCeX Docker image already present: ${FUNBGCEX_DOCKER_IMAGE}"
    set_status "funbgcex_image" 100 "FunBGCeX container image ready" "Image already present"
  elif [[ -f "${FUNBGCEX_DOCKERFILE}" ]]; then
    log "Building FunBGCeX image: ${FUNBGCEX_DOCKER_IMAGE}"
    run_with_progress "funbgcex_image" "Building FunBGCeX container image" \
      docker build -t "${FUNBGCEX_DOCKER_IMAGE}" -f "${FUNBGCEX_DOCKERFILE}" "${FUNBGCEX_BUILD_CONTEXT}" \
      || log "WARNING: FunBGCeX image build failed (will retry at runtime)."
    set_status "funbgcex_image" 100 "FunBGCeX container image ready" "Image build attempted"
  else
    log "WARNING: FunBGCeX Dockerfile missing: ${FUNBGCEX_DOCKERFILE}"
    set_status "funbgcex_image" 100 "FunBGCeX image build skipped" "Dockerfile missing"
  fi
else
  set_status "funbgcex_image" 100 "Skipping FunBGCeX image build" "Pre-build disabled"
fi

set_status "starting_worker" 100 "Starting worker process" "Handing off to worker loop"
log "Starting ClusterWeave worker ..."
exec python3 /app/worker.py
