#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

###############################################################################
# Canonical stage wrapper for the ClusterWeave workflow
#
# This script intentionally wraps the modern project stages:
#   1. run_annotation_and_detection.sh
#   2. run_bigscape.sh
#   3. summarize_clusterweave.sh
#   4. run_clinker.sh (auto-enabled in atlas-first mode; TARGET_GENOME adds targeted tracks)
#
# Genome acquisition/prep remains a separate upstream step handled by:
#   install_ncbi_cli.sh
#   prepare_genomes_from_accessions.sh
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
DATA_ROOT="${DATA_ROOT:-${PROJECT_DIR}/Data}"
RESULTS_BASE="${RESULTS_BASE:-${DATA_ROOT}/Results}"
RESULTS_ROOT="${RESULTS_ROOT:-${RESULTS_BASE}/${PROJECT_NAME}}"
REPRO_ROOT="${REPRO_ROOT:-${RESULTS_ROOT}/reproducibility}"

RUN_ANNOTATION_STAGE="${PROJECT_DIR}/run_annotation_and_detection.sh"
RUN_BIGSCAPE="${PROJECT_DIR}/run_bigscape.sh"
RUN_SUMMARY="${PROJECT_DIR}/summarize_clusterweave.sh"
RUN_CLINKER_STAGE="${PROJECT_DIR}/run_clinker.sh"

# Backward-compatible alias: older drafts exposed RUN_STAGE_NEW.
if [[ -n "${RUN_STAGE_NEW+x}" && -z "${RUN_STAGE_ANNOTATION+x}" ]]; then
  LEGACY_RUN_STAGE_NEW_WAS_SET=1
else
  LEGACY_RUN_STAGE_NEW_WAS_SET=0
fi
RUN_STAGE_ANNOTATION="${RUN_STAGE_ANNOTATION:-${RUN_STAGE_NEW:-1}}"
RUN_STAGE_BIGSCAPE="${RUN_STAGE_BIGSCAPE:-1}"
RUN_STAGE_SUMMARY="${RUN_STAGE_SUMMARY:-1}"
RUN_STAGE_CLINKER="${RUN_STAGE_CLINKER:-auto}"
TARGET_GENOME="${TARGET_GENOME:-}"
CLINKER_MODE="${CLINKER_MODE:-auto}"

ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "[$(ts)] [INFO] $*"; }
die(){ echo "[$(ts)] [ERROR] $*" >&2; exit 1; }
warn(){ echo "[$(ts)] [WARN] $*" >&2; }
git_value() {
  local args=("$@")
  git -C "${PROJECT_DIR}" "${args[@]}" 2>/dev/null || true
}
write_provenance_manifest() {
  local manifest_path="${REPRO_ROOT}/run_clusterweave_manifest.tsv"
  local env_path="${REPRO_ROOT}/run_clusterweave_context.env"
  mkdir -p "${REPRO_ROOT}"
  {
    printf 'key\tvalue\n'
    printf 'timestamp\t%s\n' "$(ts)"
    printf 'project_dir\t%s\n' "${PROJECT_DIR}"
    printf 'project_name\t%s\n' "${PROJECT_NAME}"
    printf 'results_root\t%s\n' "${RESULTS_ROOT}"
    printf 'run_stage_annotation\t%s\n' "${RUN_STAGE_ANNOTATION}"
    printf 'run_stage_bigscape\t%s\n' "${RUN_STAGE_BIGSCAPE}"
    printf 'run_stage_summary\t%s\n' "${RUN_STAGE_SUMMARY}"
    printf 'run_stage_clinker\t%s\n' "${RUN_STAGE_CLINKER}"
    printf 'clinker_mode\t%s\n' "${CLINKER_MODE}"
    printf 'target_genome\t%s\n' "${TARGET_GENOME:-}"
    printf 'git_commit\t%s\n' "$(git_value rev-parse HEAD)"
    printf 'git_branch\t%s\n' "$(git_value rev-parse --abbrev-ref HEAD)"
    printf 'git_status_porcelain\t%s\n' "$(git_value status --short | tr '\n' ';' | sed 's/;*$//')"
  } > "${manifest_path}"
  {
    printf 'PROJECT_DIR=%s\n' "${PROJECT_DIR}"
    printf 'PROJECT_NAME=%s\n' "${PROJECT_NAME}"
    printf 'DATA_ROOT=%s\n' "${DATA_ROOT}"
    printf 'RESULTS_ROOT=%s\n' "${RESULTS_ROOT}"
    printf 'RUN_STAGE_ANNOTATION=%s\n' "${RUN_STAGE_ANNOTATION}"
    printf 'RUN_STAGE_BIGSCAPE=%s\n' "${RUN_STAGE_BIGSCAPE}"
    printf 'RUN_STAGE_SUMMARY=%s\n' "${RUN_STAGE_SUMMARY}"
    printf 'RUN_STAGE_CLINKER=%s\n' "${RUN_STAGE_CLINKER}"
    printf 'CLINKER_MODE=%s\n' "${CLINKER_MODE}"
    printf 'TARGET_GENOME=%s\n' "${TARGET_GENOME:-}"
  } > "${env_path}"
  log "Wrote run provenance: ${manifest_path}"
}

[[ -x "${RUN_ANNOTATION_STAGE}" ]] || die "Missing executable stage runner: ${RUN_ANNOTATION_STAGE}"
[[ -x "${RUN_BIGSCAPE}" ]] || die "Missing executable stage runner: ${RUN_BIGSCAPE}"
[[ -x "${RUN_SUMMARY}" ]] || die "Missing executable stage runner: ${RUN_SUMMARY}"
[[ -x "${RUN_CLINKER_STAGE}" ]] || die "Missing executable stage runner: ${RUN_CLINKER_STAGE}"

case "${RUN_STAGE_CLINKER}" in
  auto)
    SHOULD_RUN_CLINKER=1
    ;;
  1|true|TRUE|yes|YES)
    SHOULD_RUN_CLINKER=1
    ;;
  0|false|FALSE|no|NO)
    SHOULD_RUN_CLINKER=0
    ;;
  *)
    die "RUN_STAGE_CLINKER must be auto, 0, or 1 (got: ${RUN_STAGE_CLINKER})"
    ;;
esac

log "Canonical workflow wrapper for ${PROJECT_DIR##*/}"
if [[ "${LEGACY_RUN_STAGE_NEW_WAS_SET}" == "1" ]]; then
  warn "RUN_STAGE_NEW is a legacy alias. Prefer RUN_STAGE_ANNOTATION going forward."
fi
log "RUN_STAGE_ANNOTATION=${RUN_STAGE_ANNOTATION}"
log "RUN_STAGE_BIGSCAPE=${RUN_STAGE_BIGSCAPE}"
log "RUN_STAGE_SUMMARY=${RUN_STAGE_SUMMARY}"
log "RUN_STAGE_CLINKER=${RUN_STAGE_CLINKER}"
log "CLINKER_MODE=${CLINKER_MODE}"
log "TARGET_GENOME=${TARGET_GENOME:-unset}"

write_provenance_manifest

if [[ "${RUN_STAGE_ANNOTATION}" == "1" ]]; then
  log "Stage 1/4: running run_annotation_and_detection.sh"
  bash "${RUN_ANNOTATION_STAGE}"
else
  log "Stage 1/4: skipped"
fi

if [[ "${RUN_STAGE_BIGSCAPE}" == "1" ]]; then
  log "Stage 2/4: running run_bigscape.sh"
  bash "${RUN_BIGSCAPE}"
else
  log "Stage 2/4: skipped"
fi

if [[ "${RUN_STAGE_SUMMARY}" == "1" ]]; then
  log "Stage 3/4: running summarize_clusterweave.sh"
  bash "${RUN_SUMMARY}"
else
  log "Stage 3/4: skipped"
fi

if [[ "${SHOULD_RUN_CLINKER}" == "1" ]]; then
  log "Stage 4/4: running run_clinker.sh"
  bash "${RUN_CLINKER_STAGE}"
else
  log "Stage 4/4: skipped"
fi

log "Canonical workflow complete."
