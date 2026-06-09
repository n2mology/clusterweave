#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${PROJECT_ROOT:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_ROOT}")}"
ACCESSIONS_FILE="${ACCESSIONS_FILE:-${PROJECT_ROOT}/accessions.txt}"
GENOME_ROOT="${GENOME_ROOT:-${PROJECT_ROOT}/data/genomes/fungi/${PROJECT_NAME}}"
NCBI_SCRIPTS_ROOT="${NCBI_SCRIPTS_ROOT:-${PROJECT_ROOT}/scripts/ncbi}"

RUN_DOWNLOAD="${RUN_DOWNLOAD:-1}"
RUN_RENAME="${RUN_RENAME:-1}"
RUN_FLATTEN="${RUN_FLATTEN:-1}"

ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "[$(ts)] [INFO] $*"; }
die(){ echo "[$(ts)] [ERROR] $*" >&2; exit 1; }

DOWNLOAD_SCRIPT="${NCBI_SCRIPTS_ROOT}/download_ncbi_genomes.sh"
RENAME_SCRIPT="${NCBI_SCRIPTS_ROOT}/rename_ncbi_genomes.sh"
FLATTEN_SCRIPT="${NCBI_SCRIPTS_ROOT}/flatten_ncbi_genomes.sh"

[[ -f "${ACCESSIONS_FILE}" ]] || die "ACCESSIONS_FILE not found: ${ACCESSIONS_FILE}"
[[ -f "${DOWNLOAD_SCRIPT}" ]] || die "Missing helper: ${DOWNLOAD_SCRIPT}"
[[ -f "${RENAME_SCRIPT}" ]] || die "Missing helper: ${RENAME_SCRIPT}"
[[ -f "${FLATTEN_SCRIPT}" ]] || die "Missing helper: ${FLATTEN_SCRIPT}"

log "Preparing genomes for ${PROJECT_NAME}"
log "ACCESSIONS_FILE=${ACCESSIONS_FILE}"
log "GENOME_ROOT=${GENOME_ROOT}"
log "This wrapper intentionally runs download -> rename -> flatten."

common_env=(
  PROJECT_ROOT="${PROJECT_ROOT}"
  PROJECT_NAME="${PROJECT_NAME}"
  ACCESSIONS_FILE="${ACCESSIONS_FILE}"
  GENOME_ROOT="${GENOME_ROOT}"
)

if [[ "${RUN_DOWNLOAD}" == "1" ]]; then
  log "Stage 1/3: downloading NCBI genomes"
  env "${common_env[@]}" bash "${DOWNLOAD_SCRIPT}"
else
  log "Stage 1/3: skipped"
fi

if [[ "${RUN_RENAME}" == "1" ]]; then
  log "Stage 2/3: renaming NCBI genomes"
  env "${common_env[@]}" bash "${RENAME_SCRIPT}"
else
  log "Stage 2/3: skipped"
fi

if [[ "${RUN_FLATTEN}" == "1" ]]; then
  log "Stage 3/3: flattening renamed genomes"
  env "${common_env[@]}" bash "${FLATTEN_SCRIPT}"
else
  log "Stage 3/3: skipped"
fi

log "Genome preparation complete."

