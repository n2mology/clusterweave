#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
PROJECTS_ROOT="${PROJECTS_ROOT:-${PROJECT_DIR}}"
DATA_ROOT="${DATA_ROOT:-${PROJECTS_ROOT}/data}"
RESULTS_BASE="${RESULTS_BASE:-${DATA_ROOT}/results}"
RESULTS_ROOT="${RESULTS_ROOT:-${RESULTS_BASE}/${PROJECT_NAME}}"
R_BIN="${R_BIN:-}"
FORCE="${FORCE:-0}"
RENDER_FIGURES_R="${RENDER_FIGURES_R:-${SCRIPT_DIR}/bin/render_summary_figures.R}"
RENDER_BGC_OVERLAP_PY="${RENDER_BGC_OVERLAP_PY:-${SCRIPT_DIR}/bin/render_bgc_overlap.py}"
RENDER_BIGSCAPE_NETWORK_PY="${RENDER_BIGSCAPE_NETWORK_PY:-${SCRIPT_DIR}/bin/render_bigscape_network.py}"
RENDER_BIGSCAPE_MULTIPANEL_PY="${RENDER_BIGSCAPE_MULTIPANEL_PY:-${SCRIPT_DIR}/bin/render_bigscape_multipanel.py}"
RUN_SUMMARY_FIGURES="${RUN_SUMMARY_FIGURES:-0}"
RUN_BGC_OVERLAP_FIGURE="${RUN_BGC_OVERLAP_FIGURE:-1}"
RUN_BIGSCAPE_NETWORK_FIGURE="${RUN_BIGSCAPE_NETWORK_FIGURE:-1}"
RUN_BIGSCAPE_MULTIPANEL_FIGURE="${RUN_BIGSCAPE_MULTIPANEL_FIGURE:-1}"
BIGSCAPE_NETWORK_METADATA_TSV="${BIGSCAPE_NETWORK_METADATA_TSV:-${RESULTS_ROOT}/summary_tables/ecofun_metadata_normalized.tsv}"
BIGSCAPE_NETWORK_ANNOTATION_TABLE="${BIGSCAPE_NETWORK_ANNOTATION_TABLE:-${RESULTS_ROOT}/summary/candidate_bgc_gcf_crosswalk.tsv}"
SUMMARY_TABLE="${SUMMARY_TABLE:-${RESULTS_ROOT}/summary/all_tools_shared_unshared_summary.csv}"
BIGSCAPE_NETWORK_ECOLOGY_FIELD="${BIGSCAPE_NETWORK_ECOLOGY_FIELD:-ecofun_primary}"
BIGSCAPE_NETWORK_FORMATS="${BIGSCAPE_NETWORK_FORMATS:-graphml}"
BIGSCAPE_MULTIPANEL_FORMATS="${BIGSCAPE_MULTIPANEL_FORMATS:-svg,png}"
BGC_OVERLAP_FORMATS="${BGC_OVERLAP_FORMATS:-svg,png}"
BIGSCAPE_NETWORK_CATEGORY="${BIGSCAPE_NETWORK_CATEGORY:-mix}"
BIGSCAPE_NETWORK_CLUSTERING_THRESHOLD="${BIGSCAPE_NETWORK_CLUSTERING_THRESHOLD:-0.3}"
BIGSCAPE_NETWORK_DISTANCE_THRESHOLD="${BIGSCAPE_NETWORK_DISTANCE_THRESHOLD:-}"
BIGSCAPE_NETWORK_SIMILARITY_THRESHOLD="${BIGSCAPE_NETWORK_SIMILARITY_THRESHOLD:-}"
BIGSCAPE_NETWORK_MAX_NODES="${BIGSCAPE_NETWORK_MAX_NODES:-0}"
BIGSCAPE_NETWORK_MAX_COMPONENTS="${BIGSCAPE_NETWORK_MAX_COMPONENTS:-0}"
BIGSCAPE_NETWORK_INCLUDE_MIBIG_ONLY="${BIGSCAPE_NETWORK_INCLUDE_MIBIG_ONLY:-0}"
BIGSCAPE_NETWORK_CANVAS_WIDTH="${BIGSCAPE_NETWORK_CANVAS_WIDTH:-1200}"
BIGSCAPE_MULTIPANEL_CANVAS_WIDTH="${BIGSCAPE_MULTIPANEL_CANVAS_WIDTH:-2400}"
BIGSCAPE_MULTIPANEL_MIN_HEIGHT="${BIGSCAPE_MULTIPANEL_MIN_HEIGHT:-0}"
KEEP_REDUNDANT_FIGURE_OUTPUTS="${KEEP_REDUNDANT_FIGURE_OUTPUTS:-0}"

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

  return 1
}

resolve_python_bin() {
  python_candidate_works() {
    "$1" -c "import sys; print(sys.executable)" >/dev/null 2>&1
  }

  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if ([[ -x "${PYTHON_BIN}" ]] || have "${PYTHON_BIN}") && python_candidate_works "${PYTHON_BIN}"; then
      printf '%s\n' "${PYTHON_BIN}"
      return 0
    fi
    die "PYTHON_BIN is not executable or cannot run Python code: ${PYTHON_BIN}"
  fi
  if have python3 && python_candidate_works python3; then
    printf '%s\n' "python3"
    return 0
  fi
  if have python && python_candidate_works python; then
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
    "${output_dir}/${prefix}_node_attributes.tsv"
    "${output_dir}/${prefix}_edge_attributes.tsv"
  )
  if [[ "${formats}" == *",svg,"* ]]; then
    expected+=("${output_dir}/${prefix}.svg")
  fi
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

bigscape_multipanel_outputs_ready() {
  local output_dir="$1"
  local prefix="$2"
  local formats=",${BIGSCAPE_MULTIPANEL_FORMATS// /},"
  local expected=()
  if [[ "${formats}" == *",svg,"* ]]; then
    expected+=("${output_dir}/${prefix}.svg")
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

bgc_overlap_outputs_ready() {
  local output_dir="$1"
  local prefix="$2"
  local formats=",${BGC_OVERLAP_FORMATS// /},"
  local expected=()
  if [[ "${formats}" == *",svg,"* ]]; then
    expected+=("${output_dir}/${prefix}.svg")
  fi
  if [[ "${formats}" == *",png,"* ]]; then
    expected+=("${output_dir}/${prefix}.png")
  fi

  local path=""
  for path in "${expected[@]}"; do
    [[ -e "${path}" ]] || return 1
  done
  return 0
}

cleanup_redundant_figure_outputs() {
  local output_dir="$1"
  [[ "${KEEP_REDUNDANT_FIGURE_OUTPUTS}" == "1" ]] && return 0

  local network_formats=",${BIGSCAPE_NETWORK_FORMATS// /},"
  local multipanel_formats=",${BIGSCAPE_MULTIPANEL_FORMATS// /},"
  local overlap_formats=",${BGC_OVERLAP_FORMATS// /},"
  local stale=(
    "${output_dir}/bgc_calls_by_tool_category.svg"
    "${output_dir}/bgc_calls_by_tool_category.png"
    "${output_dir}/bgc_calls_by_tool_class.png"
    "${output_dir}/gcf_calls_by_tool_category.svg"
    "${output_dir}/top_prioritized_bgcs.png"
    "${output_dir}/bigscape_network_fungal_id_legend.tsv"
    "${output_dir}/bigscape_network_warnings.txt"
    "${output_dir}/big_scape_multipanel_warnings.txt"
    "${output_dir}/figure_manifest.txt"
  )
  if [[ "${network_formats}" != *",svg,"* ]]; then
    stale+=("${output_dir}/bigscape_network.svg")
  fi
  if [[ "${network_formats}" != *",png,"* ]]; then
    stale+=("${output_dir}/bigscape_network.png")
  fi
  if [[ "${network_formats}" != *",pdf,"* ]]; then
    stale+=("${output_dir}/bigscape_network.pdf")
  fi
  if [[ "${multipanel_formats}" != *",pdf,"* ]]; then
    stale+=("${output_dir}/big_scape_multipanel.pdf")
  fi
  if [[ "${overlap_formats}" != *",svg,"* ]]; then
    stale+=("${output_dir}/bgc_overlap.svg")
  fi
  if [[ "${overlap_formats}" != *",png,"* ]]; then
    stale+=("${output_dir}/bgc_overlap.png")
  fi

  local path=""
  for path in "${stale[@]}"; do
    if [[ -e "${path}" ]]; then
      rm -f -- "${path}"
    fi
  done
  return 0
}

if [[ "${RUN_SUMMARY_FIGURES}" == "1" ]] && R_BIN="$(resolve_r_bin)"; then
  [[ -f "${RENDER_FIGURES_R}" ]] || die "Missing R helper: ${RENDER_FIGURES_R}"
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
elif [[ "${RUN_SUMMARY_FIGURES}" == "1" ]]; then
  warn "Rscript not found. Skipping R summary figures; continuing to BiG-SCAPE rendering."
else
  log "Skipping R summary figures because RUN_SUMMARY_FIGURES=${RUN_SUMMARY_FIGURES}"
fi

BIGSCAPE_OUTPUT_FILES="${BIGSCAPE_OUTPUT_FILES:-${RESULTS_ROOT}/big_scape/output_files}"
BIGSCAPE_NETWORK_OUTPUT_DIR="${BIGSCAPE_NETWORK_OUTPUT_DIR:-${RESULTS_ROOT}/figures}"

if [[ "${RUN_BGC_OVERLAP_FIGURE}" == "1" ]]; then
  if [[ ! -f "${RENDER_BGC_OVERLAP_PY}" ]]; then
    warn "Missing BGC overlap helper: ${RENDER_BGC_OVERLAP_PY}; skipping overlap figure."
  elif [[ "${FORCE}" != "1" ]] && bgc_overlap_outputs_ready "${BIGSCAPE_NETWORK_OUTPUT_DIR}" "bgc_overlap"; then
    log "Skipping BGC overlap figure; outputs already exist (set FORCE=1 to refresh)"
  else
    PYTHON_BIN="$(resolve_python_bin)"
    overlap_args=(
      "${PYTHON_BIN}" "${RENDER_BGC_OVERLAP_PY}"
      --project-root "${PROJECT_DIR}"
      --project-name "${PROJECT_NAME}"
      --summary-table "${SUMMARY_TABLE}"
      --output-dir "${BIGSCAPE_NETWORK_OUTPUT_DIR}"
      --formats "${BGC_OVERLAP_FORMATS}"
    )
    if [[ "${FORCE}" == "1" ]]; then
      log "FORCE=1: refreshing BGC overlap figure for ${PROJECT_NAME}"
    else
      log "Rendering BGC overlap figure for ${PROJECT_NAME}"
    fi
    "${overlap_args[@]}"
  fi
else
  log "Skipping BGC overlap figure because RUN_BGC_OVERLAP_FIGURE=${RUN_BGC_OVERLAP_FIGURE}"
fi

if [[ "${RUN_BIGSCAPE_NETWORK_FIGURE}" == "1" ]]; then
  if [[ -d "${BIGSCAPE_OUTPUT_FILES}" ]]; then
    if [[ ! -f "${RENDER_BIGSCAPE_NETWORK_PY}" ]]; then
      warn "Missing BiG-SCAPE network helper: ${RENDER_BIGSCAPE_NETWORK_PY}; skipping network figure."
    elif [[ "${FORCE}" != "1" ]] && bigscape_network_outputs_ready "${BIGSCAPE_NETWORK_OUTPUT_DIR}" "bigscape_network"; then
      log "Skipping BiG-SCAPE network figure; outputs already exist (set FORCE=1 to refresh)"
    else
      PYTHON_BIN="$(resolve_python_bin)"
      network_args=(
        "${PYTHON_BIN}" "${RENDER_BIGSCAPE_NETWORK_PY}"
        --project-root "${PROJECT_DIR}"
        --project-name "${PROJECT_NAME}"
        --bigscape-root "${BIGSCAPE_OUTPUT_FILES}"
        --output-dir "${BIGSCAPE_NETWORK_OUTPUT_DIR}"
        --ecology-field "${BIGSCAPE_NETWORK_ECOLOGY_FIELD}"
        --formats "${BIGSCAPE_NETWORK_FORMATS}"
        --category "${BIGSCAPE_NETWORK_CATEGORY}"
        --clustering-threshold "${BIGSCAPE_NETWORK_CLUSTERING_THRESHOLD}"
        --max-nodes "${BIGSCAPE_NETWORK_MAX_NODES}"
        --max-components "${BIGSCAPE_NETWORK_MAX_COMPONENTS}"
        --canvas-width "${BIGSCAPE_NETWORK_CANVAS_WIDTH}"
        --no-warnings-file
        --no-fungal-id-legend
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

if [[ "${RUN_BIGSCAPE_MULTIPANEL_FIGURE}" == "1" ]]; then
  if [[ -d "${BIGSCAPE_OUTPUT_FILES}" ]]; then
    if [[ ! -f "${RENDER_BIGSCAPE_MULTIPANEL_PY}" ]]; then
      warn "Missing BiG-SCAPE multipanel helper: ${RENDER_BIGSCAPE_MULTIPANEL_PY}; skipping multipanel figure."
    elif [[ "${FORCE}" != "1" ]] && bigscape_multipanel_outputs_ready "${BIGSCAPE_NETWORK_OUTPUT_DIR}" "big_scape_multipanel"; then
      log "Skipping BiG-SCAPE multipanel figure; outputs already exist (set FORCE=1 to refresh)"
    else
      PYTHON_BIN="$(resolve_python_bin)"
      multipanel_args=(
        "${PYTHON_BIN}" "${RENDER_BIGSCAPE_MULTIPANEL_PY}"
        --project-root "${PROJECT_DIR}"
        --project-name "${PROJECT_NAME}"
        --bigscape-root "${BIGSCAPE_OUTPUT_FILES}"
        --summary-table "${SUMMARY_TABLE}"
        --output-dir "${BIGSCAPE_NETWORK_OUTPUT_DIR}"
        --ecology-field "${BIGSCAPE_NETWORK_ECOLOGY_FIELD}"
        --formats "${BIGSCAPE_MULTIPANEL_FORMATS}"
        --category "${BIGSCAPE_NETWORK_CATEGORY}"
        --clustering-threshold "${BIGSCAPE_NETWORK_CLUSTERING_THRESHOLD}"
        --max-nodes "${BIGSCAPE_NETWORK_MAX_NODES}"
        --max-components "${BIGSCAPE_NETWORK_MAX_COMPONENTS}"
        --canvas-width "${BIGSCAPE_MULTIPANEL_CANVAS_WIDTH}"
        --min-height "${BIGSCAPE_MULTIPANEL_MIN_HEIGHT}"
        --no-standalone-chart
        --no-warnings-file
        --no-manifest
      )
      if [[ -f "${BIGSCAPE_NETWORK_METADATA_TSV}" ]]; then
        multipanel_args+=(--metadata "${BIGSCAPE_NETWORK_METADATA_TSV}")
      fi
      if [[ -f "${BIGSCAPE_NETWORK_ANNOTATION_TABLE}" ]]; then
        multipanel_args+=(--annotation-table "${BIGSCAPE_NETWORK_ANNOTATION_TABLE}")
      fi
      if [[ -n "${BIGSCAPE_NETWORK_DISTANCE_THRESHOLD}" ]]; then
        multipanel_args+=(--distance-threshold "${BIGSCAPE_NETWORK_DISTANCE_THRESHOLD}")
      fi
      if [[ -n "${BIGSCAPE_NETWORK_SIMILARITY_THRESHOLD}" ]]; then
        multipanel_args+=(--similarity-threshold "${BIGSCAPE_NETWORK_SIMILARITY_THRESHOLD}")
      fi
      if [[ "${BIGSCAPE_NETWORK_INCLUDE_MIBIG_ONLY}" == "1" ]]; then
        multipanel_args+=(--include-mibig-only)
      fi
      if [[ "${FORCE}" == "1" ]]; then
        log "FORCE=1: refreshing BiG-SCAPE multipanel figure for ${PROJECT_NAME}"
      else
        log "Rendering BiG-SCAPE multipanel figure for ${PROJECT_NAME}"
      fi
      "${multipanel_args[@]}"
    fi
  else
    log "Skipping BiG-SCAPE multipanel figure; output_files not found at ${BIGSCAPE_OUTPUT_FILES}"
  fi
else
  log "Skipping BiG-SCAPE multipanel figure because RUN_BIGSCAPE_MULTIPANEL_FIGURE=${RUN_BIGSCAPE_MULTIPANEL_FIGURE}"
fi
cleanup_redundant_figure_outputs "${BIGSCAPE_NETWORK_OUTPUT_DIR}"
log "run_figures.sh complete."
