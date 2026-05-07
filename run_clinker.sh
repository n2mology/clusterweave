#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

###############################################################################
# Shareable clinker staging/runner for ClusterWeave BGC panels
#
# Typical usage:
#   bash run_clinker.sh
#
# Default atlas-first run:
#   bash run_clinker.sh
#
# Atlas plus target-specific tracks when a genome is provided:
#   TARGET_GENOME=Your_Target_Genome_ID bash run_clinker.sh
#
# Restrict to one targeted track if needed:
#   CLINKER_MODE=targeted PANEL_TARGET_SET=priority TARGET_GENOME=Your_Target_Genome_ID bash run_clinker.sh
#   CLINKER_MODE=targeted PANEL_TARGET_SET=shared_family TARGET_GENOME=Your_Target_Genome_ID bash run_clinker.sh
#
# Stage inputs only with custom limits:
#   ATLAS_STAGE_LIMIT=6 MAX_COMPARATORS=2 bash run_clinker.sh
#
# Run clinker after staging when clinker is installed:
#   RUN_CLINKER=1 bash run_clinker.sh
#
# Keep the default dataset-wide atlas only:
#   CLINKER_MODE=atlas bash run_clinker.sh
#
# Force atlas + targeted tracks together:
#   CLINKER_MODE=both TARGET_GENOME=Your_Target_Genome_ID bash run_clinker.sh
#
# Re-run already staged panels without refreshing shortlist outputs:
#   REFRESH_FAMILY_ATLAS=0 REFRESH_REVIEWER_SHORTLIST=0 REFRESH_PRIORITY_SHORTLIST=0 \
#   REFRESH_SHARED_FAMILY_SHORTLIST=0 STAGE_PANELS=0 bash run_clinker.sh
#
# Force the shared Singularity/Apptainer container backend:
#   PREFER_CLINKER_CONTAINER=1 RUN_CLINKER=1 bash run_clinker.sh
#
# Add optional local MIBiG GenBank files:
#   MIBIG_ROOT=/path/to/mibig_gbk RUN_CLINKER=1 bash run_clinker.sh
#
# Override the BioContainers tag/source if needed:
#   CLINKER_CONTAINER_TAG=0.0.32--pyhdfd78af_0 bash run_clinker.sh
###############################################################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
PROJECTS_ROOT="${PROJECTS_ROOT:-${PROJECT_DIR}}"
DATA_ROOT="${DATA_ROOT:-${PROJECTS_ROOT}/Data}"
SOFTWARE_ROOT="${SOFTWARE_ROOT:-${PROJECTS_ROOT}/Software}"
RESULTS_BASE="${RESULTS_BASE:-${DATA_ROOT}/Results}"
RESULTS_ROOT="${RESULTS_ROOT:-${RESULTS_BASE}/${PROJECT_NAME}}"
SUMMARY_ROOT="${SUMMARY_ROOT:-${RESULTS_ROOT}/summary}"
CLINKER_SOFTDIR="${CLINKER_SOFTDIR:-${SOFTWARE_ROOT}/clinker}"
BIGSCAPE_SOFTDIR="${BIGSCAPE_SOFTDIR:-${SOFTWARE_ROOT}/big_scape}"
RES_DIR="${RES_DIR:-${BIGSCAPE_SOFTDIR}/resources}"
MIBIG_CACHE="${MIBIG_CACHE:-${RES_DIR}/mibig_cache}"

TARGET_GENOME="${TARGET_GENOME:-}"
ECOLOGY_FIELD="${ECOLOGY_FIELD:-ecofun_primary}"
FOCUS_ECOLOGY_LABEL="${FOCUS_ECOLOGY_LABEL:-}"
CLINKER_MODE="${CLINKER_MODE:-auto}"
PANEL_TARGET_SET="${PANEL_TARGET_SET:-both}"
REFRESH_FAMILY_ATLAS="${REFRESH_FAMILY_ATLAS:-1}"
REFRESH_REVIEWER_SHORTLIST="${REFRESH_REVIEWER_SHORTLIST:-1}"
REFRESH_PRIORITY_SHORTLIST="${REFRESH_PRIORITY_SHORTLIST:-1}"
REFRESH_SHARED_FAMILY_SHORTLIST="${REFRESH_SHARED_FAMILY_SHORTLIST:-1}"
STAGE_PANELS="${STAGE_PANELS:-1}"
RUN_CLINKER="${RUN_CLINKER:-1}"
SHORTLIST_BUCKET="${SHORTLIST_BUCKET:-}"
SHORTLIST_PATH="${SHORTLIST_PATH:-}"
SHORTLIST_LIMIT="${SHORTLIST_LIMIT:-12}"
ATLAS_STAGE_LIMIT="${ATLAS_STAGE_LIMIT:-12}"
ATLAS_MIN_RECORDS="${ATLAS_MIN_RECORDS:-2}"
SHARED_FAMILY_STAGE_LIMIT="${SHARED_FAMILY_STAGE_LIMIT:-12}"
SHARED_FAMILY_MIN_RECORDS="${SHARED_FAMILY_MIN_RECORDS:-4}"
MAX_SAME_ECOLOGY="${MAX_SAME_ECOLOGY:-20}"
MAX_OTHER_ECOLOGY="${MAX_OTHER_ECOLOGY:-20}"
MAX_COMPARATORS="${MAX_COMPARATORS:-50}"
ATLAS_MAX_SAME_ECOLOGY="${ATLAS_MAX_SAME_ECOLOGY:-${MAX_SAME_ECOLOGY}}"
ATLAS_MAX_OTHER_ECOLOGY="${ATLAS_MAX_OTHER_ECOLOGY:-${MAX_OTHER_ECOLOGY}}"
ATLAS_MAX_COMPARATORS="${ATLAS_MAX_COMPARATORS:-${MAX_COMPARATORS}}"
PRIORITY_MAX_SAME_ECOLOGY="${PRIORITY_MAX_SAME_ECOLOGY:-${MAX_SAME_ECOLOGY}}"
PRIORITY_MAX_OTHER_ECOLOGY="${PRIORITY_MAX_OTHER_ECOLOGY:-${MAX_OTHER_ECOLOGY}}"
PRIORITY_MAX_COMPARATORS="${PRIORITY_MAX_COMPARATORS:-${MAX_COMPARATORS}}"
SHARED_FAMILY_MAX_SAME_ECOLOGY="${SHARED_FAMILY_MAX_SAME_ECOLOGY:-${MAX_SAME_ECOLOGY}}"
SHARED_FAMILY_MAX_OTHER_ECOLOGY="${SHARED_FAMILY_MAX_OTHER_ECOLOGY:-${MAX_OTHER_ECOLOGY}}"
SHARED_FAMILY_MAX_COMPARATORS="${SHARED_FAMILY_MAX_COMPARATORS:-${MAX_COMPARATORS}}"
CLINKER_ROOT="${CLINKER_ROOT:-${RESULTS_ROOT}/clinker}"
ATLAS_CLINKER_ROOT="${ATLAS_CLINKER_ROOT:-${CLINKER_ROOT}}"
PRIORITY_CLINKER_ROOT="${PRIORITY_CLINKER_ROOT:-${CLINKER_ROOT}}"
SHARED_FAMILY_CLINKER_ROOT="${SHARED_FAMILY_CLINKER_ROOT:-${CLINKER_ROOT}}"
ATLAS_PANELS_SUBDIR="${ATLAS_PANELS_SUBDIR:-panels/atlas}"
PRIORITY_PANELS_SUBDIR="${PRIORITY_PANELS_SUBDIR:-panels/priority}"
SHARED_FAMILY_PANELS_SUBDIR="${SHARED_FAMILY_PANELS_SUBDIR:-panels/shared_family}"
ATLAS_MANIFEST_NAME="${ATLAS_MANIFEST_NAME:-panels_manifest.atlas.tsv}"
PRIORITY_MANIFEST_NAME="${PRIORITY_MANIFEST_NAME:-panels_manifest.priority.tsv}"
SHARED_FAMILY_MANIFEST_NAME="${SHARED_FAMILY_MANIFEST_NAME:-panels_manifest.shared_family.tsv}"
ATLAS_MASTER_SCRIPT_NAME="${ATLAS_MASTER_SCRIPT_NAME:-run_all_clinker_panels.atlas.sh}"
PRIORITY_MASTER_SCRIPT_NAME="${PRIORITY_MASTER_SCRIPT_NAME:-run_all_clinker_panels.priority.sh}"
SHARED_FAMILY_MASTER_SCRIPT_NAME="${SHARED_FAMILY_MASTER_SCRIPT_NAME:-run_all_clinker_panels.shared_family.sh}"
COMBINED_MASTER_SCRIPT_NAME="${COMBINED_MASTER_SCRIPT_NAME:-run_all_clinker_panels.sh}"
ATLAS_SHORTLIST_PATH="${ATLAS_SHORTLIST_PATH:-${SUMMARY_ROOT}/family_atlas_shortlist.tsv}"
PRIORITY_SHORTLIST_PATH="${PRIORITY_SHORTLIST_PATH:-${SUMMARY_ROOT}/priority_shortlist.tsv}"
SHARED_FAMILY_SHORTLIST_PATH="${SHARED_FAMILY_SHORTLIST_PATH:-${SUMMARY_ROOT}/shared_family_shortlist.tsv}"
ATLAS_SHORTLIST_BUCKET="${ATLAS_SHORTLIST_BUCKET:-atlas_now}"
PRIORITY_SHORTLIST_BUCKET="${PRIORITY_SHORTLIST_BUCKET:-clinker_now}"
SHARED_FAMILY_SHORTLIST_BUCKET="${SHARED_FAMILY_SHORTLIST_BUCKET:-shared_family_now}"
ATLAS_EXISTING_MANIFEST="${ATLAS_EXISTING_MANIFEST:-}"
PRIORITY_EXISTING_MANIFEST="${PRIORITY_EXISTING_MANIFEST:-${RESULTS_ROOT}/clinker/panels_manifest.tsv}"
SHARED_FAMILY_EXISTING_MANIFEST="${SHARED_FAMILY_EXISTING_MANIFEST:-${RESULTS_ROOT}/clinker_shared_family/panels_manifest.tsv}"
MIBIG_ROOT="${MIBIG_ROOT:-}"
ENGINE="${ENGINE:-}"
INSTALL_CLINKER_SIF="${INSTALL_CLINKER_SIF:-1}"
FORCE_PULL_CLINKER_SIF="${FORCE_PULL_CLINKER_SIF:-0}"
PREFER_CLINKER_CONTAINER="${PREFER_CLINKER_CONTAINER:-0}"
CLINKER_CONTAINER_TAG="${CLINKER_CONTAINER_TAG:-0.0.32--pyhdfd78af_0}"
CLINKER_SIF_SOURCE="${CLINKER_SIF_SOURCE:-docker://quay.io/biocontainers/clinker-py:${CLINKER_CONTAINER_TAG}}"
CLINKER_SIF_PATH="${CLINKER_SIF_PATH:-${CLINKER_SOFTDIR}/clinker-py_${CLINKER_CONTAINER_TAG}.sif}"
CLINKER_USE_DOCKER_IMAGE="${CLINKER_USE_DOCKER_IMAGE:-0}"
CLINKER_DOCKER_IMAGE="${CLINKER_DOCKER_IMAGE:-quay.io/biocontainers/clinker-py:${CLINKER_CONTAINER_TAG}}"
CLINKER_DOCKER_DATA_VOLUME="${CLINKER_DOCKER_DATA_VOLUME:-${DOCKER_DATA_VOLUME:-}}"

TARGETED_ANALYSIS_PY="${TARGETED_ANALYSIS_PY:-${PROJECT_DIR}/bin/build_candidate_tables.py}"
EXPORT_FAMILY_ATLAS_PY="${EXPORT_FAMILY_ATLAS_PY:-${PROJECT_DIR}/bin/export_dataset_family_atlas.py}"
EXPORT_SHORTLIST_PY="${EXPORT_SHORTLIST_PY:-${PROJECT_DIR}/bin/export_priority_shortlist.py}"
EXPORT_SHARED_FAMILY_PY="${EXPORT_SHARED_FAMILY_PY:-${PROJECT_DIR}/bin/export_shared_family_shortlist.py}"
STAGE_CLINKER_PY="${STAGE_CLINKER_PY:-${PROJECT_DIR}/bin/stage_clinker_panels.py}"
NORMALIZE_METADATA_PY="${NORMALIZE_METADATA_PY:-${PROJECT_DIR}/bin/normalize_metadata.py}"
AUTO_NORMALIZE_METADATA="${AUTO_NORMALIZE_METADATA:-1}"
ACCESSIONS_MAP="${ACCESSIONS_MAP:-${DATA_ROOT}/Genomes/Fungi/${PROJECT_NAME}/accessions_fungusID_taxonomyID.txt}"
METADATA_TSV="${METADATA_TSV:-${RESULTS_ROOT}/summary_tables/ecofun_metadata_normalized.tsv}"
METADATA_TEMPLATE_TSV="${METADATA_TEMPLATE_TSV:-${RESULTS_ROOT}/summary_tables/ecofun_metadata_template.tsv}"

ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "[$(ts)] [INFO] $*"; }
warn(){ echo "[$(ts)] [WARN] $*" >&2; }
die(){ echo "[$(ts)] [ERROR] $*" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
mibig_cache_has_gbks() {
  local cache="$1"
  [[ -d "${cache}" ]] || return 1
  find "${cache}" -type f \( -name "*.gbk" -o -name "*.gb" \) -print -quit 2>/dev/null | grep -q .
}
detect_engine() {
  if [[ -n "${ENGINE}" ]]; then
    return 0
  fi
  if have singularity; then
    ENGINE="singularity"
    return 0
  fi
  if have apptainer; then
    ENGINE="apptainer"
    return 0
  fi
  return 1
}
ensure_clinker_sif() {
  detect_engine || die "singularity/apptainer not found in PATH and clinker is not installed locally"
  mkdir -p "${CLINKER_SOFTDIR}"
  if [[ "${FORCE_PULL_CLINKER_SIF}" != "1" && -s "${CLINKER_SIF_PATH}" ]]; then
    log "Using existing clinker SIF: ${CLINKER_SIF_PATH}"
    return 0
  fi
  [[ "${INSTALL_CLINKER_SIF}" == "1" ]] || die "Clinker SIF missing and INSTALL_CLINKER_SIF=0"
  log "Pulling clinker container: ${CLINKER_SIF_SOURCE} -> ${CLINKER_SIF_PATH}"
  "${ENGINE}" pull "${CLINKER_SIF_PATH}" "${CLINKER_SIF_SOURCE}" || die "Failed to pull clinker container"
}

ensure_clinker_docker_image() {
  have docker || die "CLINKER_USE_DOCKER_IMAGE=1 but docker is not available in PATH"
  if docker image inspect "${CLINKER_DOCKER_IMAGE}" >/dev/null 2>&1; then
    log "Using existing clinker Docker image: ${CLINKER_DOCKER_IMAGE}"
    return 0
  fi
  log "Pulling clinker Docker image: ${CLINKER_DOCKER_IMAGE}"
  docker pull "${CLINKER_DOCKER_IMAGE}" || die "Failed to pull clinker Docker image"
}

ensure_metadata_tsv() {
  if [[ -f "${METADATA_TSV}" ]]; then
    log "Using metadata TSV: ${METADATA_TSV}"
    return 0
  fi

  [[ "${AUTO_NORMALIZE_METADATA}" == "1" ]] || return 1
  [[ -f "${NORMALIZE_METADATA_PY}" ]] || return 1
  [[ -f "${ACCESSIONS_MAP}" ]] || return 1

  log "Metadata TSV missing; generating a normalized scaffold from ${ACCESSIONS_MAP}"
  "${PYTHON_BIN}" "${NORMALIZE_METADATA_PY}" \
    --accessions "${ACCESSIONS_MAP}" \
    --out "${METADATA_TSV}" \
    --template-out "${METADATA_TEMPLATE_TSV}" \
    --allow-missing-legacy
}

resolve_python_cmd() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if [[ -x "${PYTHON_BIN}" ]]; then
      printf '%s\n' "${PYTHON_BIN}"
      return 0
    fi
    have "${PYTHON_BIN}" || die "PYTHON_BIN is not executable or not found: ${PYTHON_BIN}"
    printf '%s\n' "${PYTHON_BIN}"
    return 0
  fi
  if have python3; then
    printf '%s\n' "python3"
    return 0
  fi
  if have python; then
    printf '%s\n' "python"
    return 0
  fi
  die "Neither python3 nor python is available."
}
PYTHON_BIN="$(resolve_python_cmd)"

[[ -f "${TARGETED_ANALYSIS_PY}" ]] || die "Missing Python helper: ${TARGETED_ANALYSIS_PY}"
[[ -f "${EXPORT_FAMILY_ATLAS_PY}" ]] || die "Missing Python helper: ${EXPORT_FAMILY_ATLAS_PY}"
[[ -f "${EXPORT_SHORTLIST_PY}" ]] || die "Missing Python helper: ${EXPORT_SHORTLIST_PY}"
[[ -f "${EXPORT_SHARED_FAMILY_PY}" ]] || die "Missing Python helper: ${EXPORT_SHARED_FAMILY_PY}"
[[ -f "${STAGE_CLINKER_PY}" ]] || die "Missing Python helper: ${STAGE_CLINKER_PY}"

case "${PANEL_TARGET_SET}" in
  both)
    TARGET_TRACKS=(priority shared_family)
    ;;
  priority)
    TARGET_TRACKS=(priority)
    PRIORITY_CLINKER_ROOT="${CLINKER_ROOT:-${PRIORITY_CLINKER_ROOT}}"
    PRIORITY_SHORTLIST_PATH="${SHORTLIST_PATH:-${PRIORITY_SHORTLIST_PATH}}"
    PRIORITY_SHORTLIST_BUCKET="${SHORTLIST_BUCKET:-${PRIORITY_SHORTLIST_BUCKET}}"
    ;;
  shared_family)
    TARGET_TRACKS=(shared_family)
    SHARED_FAMILY_CLINKER_ROOT="${CLINKER_ROOT:-${SHARED_FAMILY_CLINKER_ROOT}}"
    SHARED_FAMILY_SHORTLIST_PATH="${SHORTLIST_PATH:-${SHARED_FAMILY_SHORTLIST_PATH}}"
    SHARED_FAMILY_SHORTLIST_BUCKET="${SHORTLIST_BUCKET:-${SHARED_FAMILY_SHORTLIST_BUCKET}}"
    ;;
  *)
    die "Unsupported PANEL_TARGET_SET=${PANEL_TARGET_SET}. Use both, priority, or shared_family."
    ;;
esac

case "${CLINKER_MODE}" in
  auto)
    if [[ -n "${TARGET_GENOME}" ]]; then
      TRACKS=(atlas "${TARGET_TRACKS[@]}")
    else
      TRACKS=(atlas)
    fi
    ;;
  atlas)
    TRACKS=(atlas)
    ;;
  targeted)
    TRACKS=("${TARGET_TRACKS[@]}")
    ;;
  both)
    TRACKS=(atlas "${TARGET_TRACKS[@]}")
    ;;
  *)
    die "Unsupported CLINKER_MODE=${CLINKER_MODE}. Use auto, atlas, targeted, or both."
    ;;
esac

track_clinker_root() {
  case "$1" in
    atlas) printf '%s\n' "${ATLAS_CLINKER_ROOT}" ;;
    priority) printf '%s\n' "${PRIORITY_CLINKER_ROOT}" ;;
    shared_family) printf '%s\n' "${SHARED_FAMILY_CLINKER_ROOT}" ;;
    *) return 1 ;;
  esac
}

track_panels_subdir() {
  case "$1" in
    atlas) printf '%s\n' "${ATLAS_PANELS_SUBDIR}" ;;
    priority) printf '%s\n' "${PRIORITY_PANELS_SUBDIR}" ;;
    shared_family) printf '%s\n' "${SHARED_FAMILY_PANELS_SUBDIR}" ;;
    *) return 1 ;;
  esac
}

track_manifest_name() {
  case "$1" in
    atlas) printf '%s\n' "${ATLAS_MANIFEST_NAME}" ;;
    priority) printf '%s\n' "${PRIORITY_MANIFEST_NAME}" ;;
    shared_family) printf '%s\n' "${SHARED_FAMILY_MANIFEST_NAME}" ;;
    *) return 1 ;;
  esac
}

track_master_script_name() {
  case "$1" in
    atlas) printf '%s\n' "${ATLAS_MASTER_SCRIPT_NAME}" ;;
    priority) printf '%s\n' "${PRIORITY_MASTER_SCRIPT_NAME}" ;;
    shared_family) printf '%s\n' "${SHARED_FAMILY_MASTER_SCRIPT_NAME}" ;;
    *) return 1 ;;
  esac
}

track_existing_manifest() {
  case "$1" in
    atlas) printf '%s\n' "${ATLAS_EXISTING_MANIFEST}" ;;
    priority) printf '%s\n' "${PRIORITY_EXISTING_MANIFEST}" ;;
    shared_family) printf '%s\n' "${SHARED_FAMILY_EXISTING_MANIFEST}" ;;
    *) return 1 ;;
  esac
}

track_shortlist_path() {
  case "$1" in
    atlas) printf '%s\n' "${ATLAS_SHORTLIST_PATH}" ;;
    priority) printf '%s\n' "${PRIORITY_SHORTLIST_PATH}" ;;
    shared_family) printf '%s\n' "${SHARED_FAMILY_SHORTLIST_PATH}" ;;
    *) return 1 ;;
  esac
}

track_shortlist_bucket() {
  case "$1" in
    atlas) printf '%s\n' "${ATLAS_SHORTLIST_BUCKET}" ;;
    priority) printf '%s\n' "${PRIORITY_SHORTLIST_BUCKET}" ;;
    shared_family) printf '%s\n' "${SHARED_FAMILY_SHORTLIST_BUCKET}" ;;
    *) return 1 ;;
  esac
}

track_stage_limit() {
  case "$1" in
    atlas) printf '%s\n' "${ATLAS_STAGE_LIMIT}" ;;
    priority) printf '%s\n' "${SHORTLIST_LIMIT}" ;;
    shared_family) printf '%s\n' "${SHARED_FAMILY_STAGE_LIMIT}" ;;
    *) return 1 ;;
  esac
}

track_max_same_ecology() {
  case "$1" in
    atlas) printf '%s\n' "${ATLAS_MAX_SAME_ECOLOGY}" ;;
    priority) printf '%s\n' "${PRIORITY_MAX_SAME_ECOLOGY}" ;;
    shared_family) printf '%s\n' "${SHARED_FAMILY_MAX_SAME_ECOLOGY}" ;;
    *) return 1 ;;
  esac
}

track_max_other_ecology() {
  case "$1" in
    atlas) printf '%s\n' "${ATLAS_MAX_OTHER_ECOLOGY}" ;;
    priority) printf '%s\n' "${PRIORITY_MAX_OTHER_ECOLOGY}" ;;
    shared_family) printf '%s\n' "${SHARED_FAMILY_MAX_OTHER_ECOLOGY}" ;;
    *) return 1 ;;
  esac
}

track_max_comparators() {
  case "$1" in
    atlas) printf '%s\n' "${ATLAS_MAX_COMPARATORS}" ;;
    priority) printf '%s\n' "${PRIORITY_MAX_COMPARATORS}" ;;
    shared_family) printf '%s\n' "${SHARED_FAMILY_MAX_COMPARATORS}" ;;
    *) return 1 ;;
  esac
}

stage_track() {
  local track="$1"
  local clinker_root panels_subdir manifest_name master_script_name shortlist_path shortlist_bucket existing_manifest
  local stage_limit max_same_ecology max_other_ecology max_comparators
  local -a stage_args
  clinker_root="$(track_clinker_root "${track}")" || die "Unknown track: ${track}"
  panels_subdir="$(track_panels_subdir "${track}")" || die "Unknown track: ${track}"
  manifest_name="$(track_manifest_name "${track}")" || die "Unknown track: ${track}"
  master_script_name="$(track_master_script_name "${track}")" || die "Unknown track: ${track}"
  shortlist_path="$(track_shortlist_path "${track}")" || die "Unknown track: ${track}"
  shortlist_bucket="$(track_shortlist_bucket "${track}")" || die "Unknown track: ${track}"
  existing_manifest="$(track_existing_manifest "${track}")" || die "Unknown track: ${track}"
  stage_limit="$(track_stage_limit "${track}")" || die "Unknown track: ${track}"
  max_same_ecology="$(track_max_same_ecology "${track}")" || die "Unknown track: ${track}"
  max_other_ecology="$(track_max_other_ecology "${track}")" || die "Unknown track: ${track}"
  max_comparators="$(track_max_comparators "${track}")" || die "Unknown track: ${track}"

  log "Staging ${track} panels"
  log "${track} CLINKER_ROOT=${clinker_root}"
  log "${track} PANELS_SUBDIR=${panels_subdir}"
  log "${track} MANIFEST_NAME=${manifest_name}"
  log "${track} MASTER_SCRIPT_NAME=${master_script_name}"
  log "${track} SHORTLIST_PATH=${shortlist_path}"
  log "${track} SHORTLIST_BUCKET=${shortlist_bucket}"
  log "${track} STAGE_LIMIT=${stage_limit}"
  log "${track} MAX_SAME_ECOLOGY=${max_same_ecology}"
  log "${track} MAX_OTHER_ECOLOGY=${max_other_ecology}"
  log "${track} MAX_COMPARATORS=${max_comparators}"

  stage_args=(
    "${PYTHON_BIN}" "${STAGE_CLINKER_PY}"
    --project-root "${PROJECTS_ROOT}"
    --project-name "${PROJECT_NAME}"
    --genome "${TARGET_GENOME}"
    --shortlist "${shortlist_path}"
    --bucket "${shortlist_bucket}"
    --panels-subdir "${panels_subdir}"
    --manifest-name "${manifest_name}"
    --master-script-name "${master_script_name}"
    --limit "${stage_limit}"
    --max-same-ecology "${max_same_ecology}"
    --max-other-ecology "${max_other_ecology}"
    --max-comparators "${max_comparators}"
    --output-root "${clinker_root}"
  )
  if [[ -n "${existing_manifest}" ]]; then
    stage_args+=(--existing-manifest "${existing_manifest}")
  fi
  if [[ -n "${MIBIG_ROOT}" ]]; then
    stage_args+=(--mibig-root "${MIBIG_ROOT}")
  fi
  "${stage_args[@]}"
}

run_track() {
  local track="$1"
  local clinker_root master_run_script
  clinker_root="$(track_clinker_root "${track}")" || die "Unknown track: ${track}"
  master_run_script="${clinker_root}/$(track_master_script_name "${track}")"
  [[ -f "${master_run_script}" ]] || die "Missing staged master run script for ${track}: ${master_run_script}"
  log "Running ${track} clinker panels"
  bash "${master_run_script}"
}

write_combined_master_script() {
  local combined_path="${CLINKER_ROOT}/${COMBINED_MASTER_SCRIPT_NAME}"
  mkdir -p "${CLINKER_ROOT}"
  {
    echo "#!/usr/bin/env bash"
    echo "set -euo pipefail"
    echo "IFS=\$' \\n\\t'"
    echo
    echo "SCRIPT_DIR=\"\$(cd \"\$(dirname \"\${BASH_SOURCE[0]}\")\" && pwd -P)\""
    for track in "${TRACKS[@]}"; do
      echo "bash \"\${SCRIPT_DIR}/$(track_master_script_name "${track}")\""
    done
  } > "${combined_path}"
  chmod +x "${combined_path}" 2>/dev/null || true
}

write_combined_manifest() {
  local combined_manifest="${CLINKER_ROOT}/panels_manifest.tsv"
  local wrote_header=0
  mkdir -p "${CLINKER_ROOT}"
  : > "${combined_manifest}"
  for track in "${TRACKS[@]}"; do
    local manifest_path="${CLINKER_ROOT}/$(track_manifest_name "${track}")"
    local line_number=0
    [[ -f "${manifest_path}" ]] || continue
    while IFS= read -r line; do
      if [[ "${line_number}" -eq 0 ]]; then
        if [[ "${wrote_header}" -eq 0 ]]; then
          printf 'track\t%s\n' "${line}" >> "${combined_manifest}"
          wrote_header=1
        fi
      else
        printf '%s\t%s\n' "${track}" "${line}" >> "${combined_manifest}"
      fi
      line_number=$((line_number + 1))
    done < "${manifest_path}"
  done
}

infer_target_genome_from_table() {
  local table_path="$1"
  local inferred=""
  [[ -f "${table_path}" ]] || return 1
  inferred="$("${PYTHON_BIN}" - "${table_path}" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open("r", newline="", encoding="utf-8-sig") as handle:
    rows = csv.DictReader(handle, delimiter="\t")
    genomes = sorted({(row.get("genome") or "").strip() for row in rows if (row.get("genome") or "").strip()})
if len(genomes) == 1:
    print(genomes[0])
PY
)"
  [[ -n "${inferred}" ]] || return 1
  TARGET_GENOME="${inferred}"
  log "Inferred TARGET_GENOME=${TARGET_GENOME} from ${table_path}"
  return 0
}

infer_target_genome_from_existing_outputs() {
  local table_path
  for table_path in \
    "${PRIORITY_SHORTLIST_PATH}" \
    "${SHARED_FAMILY_SHORTLIST_PATH}" \
    "${SUMMARY_ROOT}/reviewer_shortlist.tsv" \
    "${SUMMARY_ROOT}/targeted_candidate_ranking.tsv"
  do
    infer_target_genome_from_table "${table_path}" && return 0
  done
  return 1
}

mode_includes_track() {
  local wanted="$1"
  local track
  for track in "${TRACKS[@]}"; do
    [[ "${track}" == "${wanted}" ]] && return 0
  done
  return 1
}

mode_includes_targeted() {
  mode_includes_track priority || mode_includes_track shared_family
}

requires_target_genome() {
  mode_includes_targeted || return 1
  [[ "${REFRESH_PRIORITY_SHORTLIST}" == "1" ]] && return 0
  [[ "${REFRESH_SHARED_FAMILY_SHORTLIST}" == "1" ]] && return 0
  [[ "${STAGE_PANELS}" == "1" ]] && return 0
  return 1
}

has_staged_outputs_for_track() {
  local track="$1"
  local clinker_root master_run_script
  clinker_root="$(track_clinker_root "${track}")" || return 1
  master_run_script="${clinker_root}/$(track_master_script_name "${track}")"
  [[ -f "${master_run_script}" ]]
}

can_run_existing_panels_without_target() {
  local track
  mode_includes_targeted || return 1
  [[ "${RUN_CLINKER}" == "1" ]] || return 1
  [[ "${REFRESH_REVIEWER_SHORTLIST}" == "0" ]] || return 1
  [[ "${REFRESH_PRIORITY_SHORTLIST}" == "0" ]] || return 1
  [[ "${REFRESH_SHARED_FAMILY_SHORTLIST}" == "0" ]] || return 1
  [[ "${STAGE_PANELS}" == "0" ]] || return 1
  for track in "${TRACKS[@]}"; do
    [[ "${track}" == "atlas" ]] && continue
    has_staged_outputs_for_track "${track}" || return 1
  done
  return 0
}

if [[ -z "${TARGET_GENOME}" ]] && mode_includes_targeted; then
  warn "TARGET_GENOME is unset; trying to infer it from existing shortlist outputs."
  infer_target_genome_from_existing_outputs || true
fi

if [[ -z "${TARGET_GENOME}" ]] && mode_includes_targeted; then
  if can_run_existing_panels_without_target; then
    warn "Execution-only clinker rerun selected without TARGET_GENOME; reusing existing staged panels."
  elif requires_target_genome; then
    die "TARGET_GENOME must be set for targeted clinker staging. Leave CLINKER_MODE=auto for the default atlas-first workflow, set TARGET_GENOME=<genome> for targeted tracks, or rerun existing staged targeted panels with REFRESH_REVIEWER_SHORTLIST=0 REFRESH_PRIORITY_SHORTLIST=0 REFRESH_SHARED_FAMILY_SHORTLIST=0 STAGE_PANELS=0."
  fi
fi

log "run_clinker.sh for ${PROJECT_NAME}"
log "CLINKER_MODE=${CLINKER_MODE}"
log "TARGET_GENOME=${TARGET_GENOME}"
log "PANEL_TARGET_SET=${PANEL_TARGET_SET}"
log "RUN_CLINKER=${RUN_CLINKER}"
log "PREFER_CLINKER_CONTAINER=${PREFER_CLINKER_CONTAINER}"
log "CLINKER_USE_DOCKER_IMAGE=${CLINKER_USE_DOCKER_IMAGE}"
log "CLINKER_ROOT=${CLINKER_ROOT}"
if [[ -z "${MIBIG_ROOT}" ]] && mibig_cache_has_gbks "${MIBIG_CACHE}"; then
  MIBIG_ROOT="${MIBIG_CACHE}"
fi
log "MIBIG_CACHE=${MIBIG_CACHE}"
log "MIBIG_ROOT=${MIBIG_ROOT:-none}"
log "CLINKER_SIF_PATH=${CLINKER_SIF_PATH}"
log "CLINKER_DOCKER_IMAGE=${CLINKER_DOCKER_IMAGE}"
log "CLINKER_DOCKER_DATA_VOLUME=${CLINKER_DOCKER_DATA_VOLUME:-none}"
log "AUTO_NORMALIZE_METADATA=${AUTO_NORMALIZE_METADATA}"
log "METADATA_TSV=${METADATA_TSV}"
for track in "${TRACKS[@]}"; do
  log "${track} CLINKER_ROOT=$(track_clinker_root "${track}")"
  log "${track} PANELS_SUBDIR=$(track_panels_subdir "${track}")"
  log "${track} MANIFEST_NAME=$(track_manifest_name "${track}")"
  log "${track} MASTER_SCRIPT_NAME=$(track_master_script_name "${track}")"
  log "${track} SHORTLIST_PATH=$(track_shortlist_path "${track}")"
  log "${track} SHORTLIST_BUCKET=$(track_shortlist_bucket "${track}")"
done

if [[ "${REFRESH_FAMILY_ATLAS}" == "1" || "${REFRESH_REVIEWER_SHORTLIST}" == "1" || "${REFRESH_SHARED_FAMILY_SHORTLIST}" == "1" ]]; then
  ensure_metadata_tsv || die "Metadata TSV missing. Provide ${METADATA_TSV}, or enable AUTO_NORMALIZE_METADATA=1 with a valid accession mapping."
fi

if [[ "${REFRESH_REVIEWER_SHORTLIST}" == "1" || "${REFRESH_FAMILY_ATLAS}" == "1" ]]; then
  if [[ -n "${TARGET_GENOME}" ]]; then
    log "Refreshing candidate ranking and reviewer shortlist inputs"
  else
    log "Refreshing dataset-wide candidate ranking inputs"
  fi
  reviewer_args=(
    "${PYTHON_BIN}" "${TARGETED_ANALYSIS_PY}"
    --project-root "${PROJECTS_ROOT}"
    --project-name "${PROJECT_NAME}"
    --ecology-field "${ECOLOGY_FIELD}"
  )
  if [[ -n "${TARGET_GENOME}" ]]; then
    reviewer_args+=(--target-genome "${TARGET_GENOME}")
  fi
  if [[ -n "${FOCUS_ECOLOGY_LABEL}" ]]; then
    reviewer_args+=(--focus-ecology-label "${FOCUS_ECOLOGY_LABEL}")
  fi
  "${reviewer_args[@]}"
else
  log "Skipping candidate ranking refresh"
fi

if mode_includes_track atlas; then
  if [[ "${REFRESH_FAMILY_ATLAS}" == "1" ]]; then
    log "Refreshing dataset-wide family atlas outputs"
    atlas_args=(
      "${PYTHON_BIN}" "${EXPORT_FAMILY_ATLAS_PY}"
      --project-root "${PROJECTS_ROOT}"
      --project-name "${PROJECT_NAME}"
      --stage-limit "${ATLAS_STAGE_LIMIT}"
      --min-records "${ATLAS_MIN_RECORDS}"
      --ecology-field "${ECOLOGY_FIELD}"
    )
    if [[ -n "${FOCUS_ECOLOGY_LABEL}" ]]; then
      atlas_args+=(--focus-ecology-label "${FOCUS_ECOLOGY_LABEL}")
    fi
    "${atlas_args[@]}"
  else
    log "Skipping dataset-wide family atlas refresh"
  fi
fi

if mode_includes_track priority && [[ "${REFRESH_PRIORITY_SHORTLIST}" == "1" ]]; then
  log "Refreshing priority shortlist outputs"
  "${PYTHON_BIN}" "${EXPORT_SHORTLIST_PY}" \
    --project-root "${PROJECTS_ROOT}" \
    --project-name "${PROJECT_NAME}" \
    --genome "${TARGET_GENOME}"
elif mode_includes_track priority; then
  log "Skipping priority shortlist refresh"
else
  log "Priority track not selected"
fi

if mode_includes_track shared_family && [[ "${REFRESH_SHARED_FAMILY_SHORTLIST}" == "1" ]]; then
  log "Refreshing BiG-SCAPE shared-family shortlist outputs"
  shared_family_args=(
    "${PYTHON_BIN}" "${EXPORT_SHARED_FAMILY_PY}"
    --project-root "${PROJECTS_ROOT}"
    --project-name "${PROJECT_NAME}"
    --genome "${TARGET_GENOME}"
    --stage-limit "${SHARED_FAMILY_STAGE_LIMIT}"
    --min-records "${SHARED_FAMILY_MIN_RECORDS}"
    --ecology-field "${ECOLOGY_FIELD}"
  )
  if [[ -n "${FOCUS_ECOLOGY_LABEL}" ]]; then
    shared_family_args+=(--focus-ecology-label "${FOCUS_ECOLOGY_LABEL}")
  fi
  "${shared_family_args[@]}"
elif mode_includes_track shared_family; then
  log "Skipping shared-family shortlist refresh"
else
  log "Shared-family track not selected"
fi

if [[ "${STAGE_PANELS}" == "1" ]]; then
  for track in "${TRACKS[@]}"; do
    stage_track "${track}"
  done
  write_combined_manifest
  write_combined_master_script
else
  log "Skipping clinker panel staging"
fi

if [[ "${RUN_CLINKER}" == "1" ]]; then
  if command -v clinker >/dev/null 2>&1 && [[ "${PREFER_CLINKER_CONTAINER}" != "1" ]]; then
    log "Using local clinker from PATH"
  elif [[ "${CLINKER_USE_DOCKER_IMAGE}" == "1" ]]; then
    ensure_clinker_docker_image
    export CLINKER_DOCKER_IMAGE
    export CLINKER_DOCKER_DATA_VOLUME
    export PREFER_CLINKER_CONTAINER=1
    log "Using clinker Docker image: ${CLINKER_DOCKER_IMAGE}"
    docker run --rm -i --user 0:0 "${CLINKER_DOCKER_IMAGE}" clinker --help >/dev/null 2>&1 \
      || die "Clinker Docker image sanity check failed"
  else
    ensure_clinker_sif
    export CLINKER_ENGINE="${ENGINE}"
    export CLINKER_SIF_PATH="${CLINKER_SIF_PATH}"
    export PREFER_CLINKER_CONTAINER=1
    log "Using clinker container via ${CLINKER_ENGINE}: ${CLINKER_SIF_PATH}"
    "${CLINKER_ENGINE}" exec "${CLINKER_SIF_PATH}" clinker --help >/dev/null 2>&1 \
      || die "Clinker container sanity check failed"
  fi
  for track in "${TRACKS[@]}"; do
    run_track "${track}"
  done
else
  log "RUN_CLINKER=0, so clinker execution was skipped after staging."
fi

log "run_clinker.sh complete."
