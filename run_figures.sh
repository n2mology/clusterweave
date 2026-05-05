#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
R_BIN="${R_BIN:-}"
FORCE="${FORCE:-0}"
RENDER_FIGURES_R="${RENDER_FIGURES_R:-${PROJECT_DIR}/bin/render_summary_figures.R}"
RENDER_BIGSCAPE_NETWORK_PY="${RENDER_BIGSCAPE_NETWORK_PY:-${PROJECT_DIR}/bin/render_bigscape_network.py}"
RUN_BIGSCAPE_NETWORK_FIGURE="${RUN_BIGSCAPE_NETWORK_FIGURE:-1}"
BIGSCAPE_NETWORK_METADATA_TSV="${BIGSCAPE_NETWORK_METADATA_TSV:-${PROJECT_DIR}/Data/Results/${PROJECT_NAME}/summary_tables/ecofun_metadata_normalized.tsv}"
BIGSCAPE_NETWORK_ANNOTATION_TABLE="${BIGSCAPE_NETWORK_ANNOTATION_TABLE:-${PROJECT_DIR}/Data/Results/${PROJECT_NAME}/summary/candidate_bgc_gcf_crosswalk.tsv}"
BIGSCAPE_NETWORK_ECOLOGY_FIELD="${BIGSCAPE_NETWORK_ECOLOGY_FIELD:-ecofun_primary}"
BIGSCAPE_NETWORK_FORMATS="${BIGSCAPE_NETWORK_FORMATS:-svg,graphml}"
BIGSCAPE_NETWORK_CATEGORY="${BIGSCAPE_NETWORK_CATEGORY:-mix}"
BIGSCAPE_NETWORK_CLUSTERING_THRESHOLD="${BIGSCAPE_NETWORK_CLUSTERING_THRESHOLD:-0.3}"
BIGSCAPE_NETWORK_DISTANCE_THRESHOLD="${BIGSCAPE_NETWORK_DISTANCE_THRESHOLD:-}"
BIGSCAPE_NETWORK_SIMILARITY_THRESHOLD="${BIGSCAPE_NETWORK_SIMILARITY_THRESHOLD:-}"
BIGSCAPE_NETWORK_MAX_NODES="${BIGSCAPE_NETWORK_MAX_NODES:-0}"
BIGSCAPE_NETWORK_MAX_COMPONENTS="${BIGSCAPE_NETWORK_MAX_COMPONENTS:-0}"
BIGSCAPE_NETWORK_INCLUDE_MIBIG_ONLY="${BIGSCAPE_NETWORK_INCLUDE_MIBIG_ONLY:-0}"
BIGSCAPE_NETWORK_CANVAS_WIDTH="${BIGSCAPE_NETWORK_CANVAS_WIDTH:-1200}"

ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "[$(ts)] [INFO] $*"; }
warn(){ echo "[$(ts)] [WARN] $*" >&2; }
die(){ echo "[$(ts)] [ERROR] $*" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }

append_glob_matches() {
  local pattern="$1"
  local path=""
  while IFS= read -r path; do
    [[ -n "${path}" ]] && R_CANDIDATES+=("${path}")
  done < <(compgen -G "${pattern}" || true)
}

resolve_r_bin() {
  local candidate=""
  R_CANDIDATES=()

  if [[ -n "${R_BIN}" ]]; then
    R_CANDIDATES+=("${R_BIN}")
  fi
  R_CANDIDATES+=("Rscript" "Rscript.exe")
  append_glob_matches "/mnt/c/Program Files/R/R-*/bin/Rscript.exe"
  append_glob_matches "/mnt/c/Program Files/R/R-*/bin/x64/Rscript.exe"
  append_glob_matches "/c/Program Files/R/R-*/bin/Rscript.exe"
  append_glob_matches "/c/Program Files/R/R-*/bin/x64/Rscript.exe"

  for candidate in "${R_CANDIDATES[@]}"; do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
    if have "${candidate}"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  die "Rscript not found. Install R, add Rscript to PATH, or set R_BIN."
}

resolve_python_bin() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if [[ -x "${PYTHON_BIN}" ]] || have "${PYTHON_BIN}"; then
      printf '%s\n' "${PYTHON_BIN}"
      return 0
    fi
    die "PYTHON_BIN is not executable or not found: ${PYTHON_BIN}"
  fi
  if have python3; then
    printf '%s\n' "python3"
    return 0
  fi
  if have python; then
    printf '%s\n' "python"
    return 0
  fi
  die "python3/python not found. Install Python or set PYTHON_BIN."
}

is_windows_exe() {
  [[ "${1,,}" == *.exe ]]
}

native_path_for_windows_exe() {
  local path="$1"
  if have wslpath; then
    wslpath -w "${path}"
    return 0
  fi
  if have cygpath; then
    cygpath -w "${path}"
    return 0
  fi
  printf '%s\n' "${path}"
}

bigscape_network_outputs_ready() {
  local output_dir="$1"
  local prefix="$2"
  local formats=",${BIGSCAPE_NETWORK_FORMATS// /},"
  local expected=(
    "${output_dir}/${prefix}.svg"
    "${output_dir}/${prefix}_node_attributes.tsv"
    "${output_dir}/${prefix}_edge_attributes.tsv"
    "${output_dir}/${prefix}_fungal_id_legend.tsv"
    "${output_dir}/${prefix}_warnings.txt"
  )
  if [[ "${formats}" == *",graphml,"* ]]; then
    expected+=("${output_dir}/${prefix}.graphml")
  fi
  if [[ "${formats}" == *",png,"* ]]; then
    expected+=("${output_dir}/${prefix}.png")
  fi
  if [[ "${formats}" == *",pdf,"* ]]; then
    expected+=("${output_dir}/${prefix}.pdf")
  fi

  local path=""
  for path in "${expected[@]}"; do
    [[ -e "${path}" ]] || return 1
  done
  return 0
}

[[ -f "${RENDER_FIGURES_R}" ]] || die "Missing R helper: ${RENDER_FIGURES_R}"
R_BIN="$(resolve_r_bin)"
RENDER_FIGURES_R_ARG="${RENDER_FIGURES_R}"
PROJECT_DIR_FOR_R="${PROJECT_DIR}"
if is_windows_exe "${R_BIN}"; then
  RENDER_FIGURES_R_ARG="$(native_path_for_windows_exe "${RENDER_FIGURES_R}")"
  PROJECT_DIR_FOR_R="$(native_path_for_windows_exe "${PROJECT_DIR}")"
fi

log "Rendering summary figures for ${PROJECT_NAME}"
if ! "${R_BIN}" "${RENDER_FIGURES_R_ARG}" \
  --project-root "${PROJECT_DIR_FOR_R}" \
  --project-name "${PROJECT_NAME}"; then
  warn "Summary figure rendering failed for ${PROJECT_NAME}; continuing to BiG-SCAPE network rendering."
fi

if [[ "${RUN_BIGSCAPE_NETWORK_FIGURE}" == "1" ]]; then
  BIGSCAPE_OUTPUT_FILES="${PROJECT_DIR}/Data/Results/${PROJECT_NAME}/big_scape/output_files"
  BIGSCAPE_NETWORK_OUTPUT_DIR="${PROJECT_DIR}/Data/Results/${PROJECT_NAME}/figures"
  if [[ -d "${BIGSCAPE_OUTPUT_FILES}" ]]; then
    [[ -f "${RENDER_BIGSCAPE_NETWORK_PY}" ]] || die "Missing BiG-SCAPE network helper: ${RENDER_BIGSCAPE_NETWORK_PY}"
    if [[ "${FORCE}" != "1" ]] && bigscape_network_outputs_ready "${BIGSCAPE_NETWORK_OUTPUT_DIR}" "bigscape_network"; then
      log "Skipping BiG-SCAPE network figure; outputs already exist (set FORCE=1 to refresh)"
    else
      PYTHON_BIN="$(resolve_python_bin)"
      network_args=(
        "${PYTHON_BIN}" "${RENDER_BIGSCAPE_NETWORK_PY}"
        --project-root "${PROJECT_DIR}"
        --project-name "${PROJECT_NAME}"
        --bigscape-root "${BIGSCAPE_OUTPUT_FILES}"
        --ecology-field "${BIGSCAPE_NETWORK_ECOLOGY_FIELD}"
        --formats "${BIGSCAPE_NETWORK_FORMATS}"
        --category "${BIGSCAPE_NETWORK_CATEGORY}"
        --clustering-threshold "${BIGSCAPE_NETWORK_CLUSTERING_THRESHOLD}"
        --max-nodes "${BIGSCAPE_NETWORK_MAX_NODES}"
        --max-components "${BIGSCAPE_NETWORK_MAX_COMPONENTS}"
        --canvas-width "${BIGSCAPE_NETWORK_CANVAS_WIDTH}"
      )
      if [[ -f "${BIGSCAPE_NETWORK_METADATA_TSV}" ]]; then
        network_args+=(--metadata "${BIGSCAPE_NETWORK_METADATA_TSV}")
      fi
      if [[ -f "${BIGSCAPE_NETWORK_ANNOTATION_TABLE}" ]]; then
        network_args+=(--annotation-table "${BIGSCAPE_NETWORK_ANNOTATION_TABLE}")
      fi
      if [[ -n "${BIGSCAPE_NETWORK_DISTANCE_THRESHOLD}" ]]; then
        network_args+=(--distance-threshold "${BIGSCAPE_NETWORK_DISTANCE_THRESHOLD}")
      fi
      if [[ -n "${BIGSCAPE_NETWORK_SIMILARITY_THRESHOLD}" ]]; then
        network_args+=(--similarity-threshold "${BIGSCAPE_NETWORK_SIMILARITY_THRESHOLD}")
      fi
      if [[ "${BIGSCAPE_NETWORK_INCLUDE_MIBIG_ONLY}" == "1" ]]; then
        network_args+=(--include-mibig-only)
      fi
      if [[ "${FORCE}" == "1" ]]; then
        log "FORCE=1: refreshing BiG-SCAPE network figure for ${PROJECT_NAME}"
      else
        log "Rendering BiG-SCAPE network figure for ${PROJECT_NAME}"
      fi
      "${network_args[@]}"
    fi
  else
    log "Skipping BiG-SCAPE network figure; output_files not found at ${BIGSCAPE_OUTPUT_FILES}"
  fi
else
  log "Skipping BiG-SCAPE network figure because RUN_BIGSCAPE_NETWORK_FIGURE=${RUN_BIGSCAPE_NETWORK_FIGURE}"
fi
log "run_figures.sh complete."
