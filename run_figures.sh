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
RENDER_PHYLO_TAXON_PROFILE_PY="${RENDER_PHYLO_TAXON_PROFILE_PY:-${SCRIPT_DIR}/bin/render_phylo_taxon_profile.py}"
ANALYSIS_SCOPE="${ANALYSIS_SCOPE:-fungi}"
GENOME_TAXON_MANIFEST="${GENOME_TAXON_MANIFEST:-${RESULTS_ROOT}/summary_tables/genome_taxon_manifest.tsv}"
RUN_SUMMARY_FIGURES="${RUN_SUMMARY_FIGURES:-0}"
RUN_BGC_OVERLAP_FIGURE="${RUN_BGC_OVERLAP_FIGURE:-1}"
RUN_BIGSCAPE_NETWORK_FIGURE="${RUN_BIGSCAPE_NETWORK_FIGURE:-1}"
RUN_BIGSCAPE_MULTIPANEL_FIGURE="${RUN_BIGSCAPE_MULTIPANEL_FIGURE:-1}"
RUN_TAXON_TREE_FIGURE="${RUN_TAXON_TREE_FIGURE:-1}"
TAXON_TREE_REQUIRED="${TAXON_TREE_REQUIRED:-0}"
PHYLOGENY_MAX_VISIBLE_ARCS="${PHYLOGENY_MAX_VISIBLE_ARCS:-80}"
BIGSCAPE_NETWORK_METADATA_TSV="${BIGSCAPE_NETWORK_METADATA_TSV:-${METADATA_TSV:-${RESULTS_ROOT}/summary_tables/ecofun_metadata_normalized.tsv}}"
BIGSCAPE_NETWORK_ANNOTATION_TABLE="${BIGSCAPE_NETWORK_ANNOTATION_TABLE:-${RESULTS_ROOT}/summary/candidate_bgc_gcf_crosswalk.tsv}"
BIGSCAPE_REGION_CROSSWALK_TSV="${BIGSCAPE_REGION_CROSSWALK_TSV:-${RESULTS_ROOT}/summary_tables/bigscape_region_crosswalk.tsv}"
FUNGAL_BIGSCAPE_METADATA_TSV="${FUNGAL_BIGSCAPE_METADATA_TSV:-${RESULTS_ROOT}/summary_tables/ecofun_metadata_normalized.tsv}"
BACTERIAL_BIGSCAPE_METADATA_TSV="${BACTERIAL_BIGSCAPE_METADATA_TSV:-${RESULTS_ROOT}/summary_tables/ecobac_metadata_normalized.tsv}"
FUNGAL_BIGSCAPE_ECOLOGY_FIELD="${FUNGAL_BIGSCAPE_ECOLOGY_FIELD:-ecofun_primary}"
BACTERIAL_BIGSCAPE_ECOLOGY_FIELD="${BACTERIAL_BIGSCAPE_ECOLOGY_FIELD:-ecobac_primary}"
SUMMARY_TABLE="${SUMMARY_TABLE:-${RESULTS_ROOT}/summary/all_tools_shared_unshared_summary.csv}"
BIGSCAPE_NETWORK_ECOLOGY_FIELD="${BIGSCAPE_NETWORK_ECOLOGY_FIELD:-${ECOLOGY_FIELD:-ecofun_primary}}"
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
BACTERIAL_EXACT_PRODUCTS_TSV="${BACTERIAL_EXACT_PRODUCTS_TSV:-${RESULTS_ROOT}/summary_tables/antismash_product_types_exact.tsv}"
BACTERIAL_CROSSWALK_TSV="${BACTERIAL_CROSSWALK_TSV:-${RESULTS_ROOT}/summary/candidate_bgc_gcf_crosswalk.tsv}"
TAXONOMY_METADATA_TSV="${TAXONOMY_METADATA_TSV:-${RESULTS_ROOT}/summary_tables/taxonomy_metadata_normalized.tsv}"
TAXON_TREE_OUTPUT_DIR="${TAXON_TREE_OUTPUT_DIR:-${RESULTS_ROOT}/figures/phylogeny}"

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

bigscape_clustering_inputs_ready() {
  local input_root="$1"
  [[ -d "${input_root}" ]] || return 1
  find "${input_root}" -type f -name "*_clustering_c*.tsv" -size +0c -print -quit 2>/dev/null | grep -q .
}

clear_bigscape_cluster_figures() {
  local output_dir="$1"
  local stale=(
    "${output_dir}/bigscape_network.svg"
    "${output_dir}/bigscape_network.png"
    "${output_dir}/bigscape_network.pdf"
    "${output_dir}/bigscape_network.graphml"
    "${output_dir}/bigscape_network_node_attributes.tsv"
    "${output_dir}/bigscape_network_edge_attributes.tsv"
    "${output_dir}/bigscape_network_fungal_id_legend.tsv"
    "${output_dir}/bigscape_network_warnings.txt"
    "${output_dir}/big_scape_multipanel.svg"
    "${output_dir}/big_scape_multipanel.png"
    "${output_dir}/big_scape_multipanel.pdf"
    "${output_dir}/big_scape_multipanel_warnings.txt"
    "${output_dir}/bacterial_multipanel.svg"
    "${output_dir}/bacterial_multipanel.png"
    "${output_dir}/fungi_big_scape_multipanel.svg"
    "${output_dir}/fungi_big_scape_multipanel.png"
    "${output_dir}/fungi_big_scape_multipanel.pdf"
    "${output_dir}/bacteria_big_scape_multipanel.svg"
    "${output_dir}/bacteria_big_scape_multipanel.png"
    "${output_dir}/bacteria_big_scape_multipanel.pdf"
  )
  local path=""
  for path in "${stale[@]}"; do
    [[ ! -e "${path}" ]] || rm -f -- "${path}"
  done
}

taxon_tree_outputs_ready() {
  local output_dir="$1"
  local required=(
    clusterweave_taxon_tree.svg
    clusterweave_taxon_tree.nwk
    clusterweave_taxon_tree_leaf_profiles.tsv
    clusterweave_gcf_network_edges.tsv
    clusterweave_taxon_tree.graphml
    clusterweave_tree_manifest.json
    clusterweave_tree_methods.json
    clusterweave_tree_bundle.zip
  )
  local filename=""
  for filename in "${required[@]}"; do
    [[ -s "${output_dir}/${filename}" ]] || return 1
  done
  return 0
}

cleanup_redundant_figure_outputs() {
  local output_dir="$1"
  local legacy=(
    "${output_dir}/big_scape_multipanel.svg"
    "${output_dir}/big_scape_multipanel.png"
    "${output_dir}/big_scape_multipanel.pdf"
    "${output_dir}/big_scape_multipanel_warnings.txt"
    "${output_dir}/bacterial_multipanel.svg"
    "${output_dir}/bacterial_multipanel.png"
  )
  local legacy_path=""
  for legacy_path in "${legacy[@]}"; do
    [[ ! -e "${legacy_path}" ]] || rm -f -- "${legacy_path}"
  done
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
    stale+=(
      "${output_dir}/fungi_big_scape_multipanel.pdf"
      "${output_dir}/bacteria_big_scape_multipanel.pdf"
    )
  fi
  if [[ "${multipanel_formats}" != *",png,"* ]]; then
    stale+=(
      "${output_dir}/fungi_big_scape_multipanel.png"
      "${output_dir}/bacteria_big_scape_multipanel.png"
    )
  fi
  if [[ "${multipanel_formats}" != *",svg,"* ]]; then
    stale+=(
      "${output_dir}/fungi_big_scape_multipanel.svg"
      "${output_dir}/bacteria_big_scape_multipanel.svg"
    )
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

FUNGI_COUNT=0
BACTERIA_COUNT=0
if [[ -s "${GENOME_TAXON_MANIFEST}" ]]; then
  read -r FUNGI_COUNT BACTERIA_COUNT < <(
    awk -F '\t' '
      NR == 1 { for (i = 1; i <= NF; i++) h[$i] = i; next }
      { taxon = $(h["taxon_group"]); if (taxon == "fungi") fungi++; else if (taxon == "bacteria") bacteria++ }
      END { print fungi + 0, bacteria + 0 }
    ' "${GENOME_TAXON_MANIFEST}"
  )
else
  case "${ANALYSIS_SCOPE}" in
    bacteria) BACTERIA_COUNT=1 ;;
    both) FUNGI_COUNT=1; BACTERIA_COUNT=1 ;;
    *) FUNGI_COUNT=1 ;;
  esac
fi
log "FIGURE_TAXON_CONTEXT scope=${ANALYSIS_SCOPE} fungi=${FUNGI_COUNT} bacteria=${BACTERIA_COUNT}"

FUNGAL_SUMMARY_TABLE="${SUMMARY_TABLE}"
if [[ "${FUNGI_COUNT}" -gt 0 && "${BACTERIA_COUNT}" -gt 0 && -s "${SUMMARY_TABLE}" ]]; then
  FIGURE_WORK_ROOT="${WORK_ROOT:-${RESULTS_ROOT}/tmp}/figures"
  mkdir -p "${FIGURE_WORK_ROOT}"
  FUNGAL_SUMMARY_TABLE="${FIGURE_WORK_ROOT}/fungal_summary.csv"
  PYTHON_BIN="$(resolve_python_bin)"
  "${PYTHON_BIN}" - "${SUMMARY_TABLE}" "${GENOME_TAXON_MANIFEST}" "${FUNGAL_SUMMARY_TABLE}" <<'PY'
import csv
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])
with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
    fungal_ids = {
        str(row.get("genome_id") or row.get("genome") or "").strip()
        for row in csv.DictReader(handle, delimiter="\t")
        if str(row.get("taxon_group") or "").strip().lower() == "fungi"
    }
with summary_path.open(newline="", encoding="utf-8-sig") as source:
    reader = csv.DictReader(source)
    fields = list(reader.fieldnames or [])
    if not fields:
        raise SystemExit("mixed summary CSV has no header")
    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            taxon = str(row.get("taxon_group") or "").strip().lower()
            genome = str(row.get("genome") or row.get("genome_id") or "").strip()
            if taxon == "fungi" or (not taxon and genome in fungal_ids):
                writer.writerow(row)
PY
fi

if [[ "${RUN_BGC_OVERLAP_FIGURE}" == "1" && "${FUNGI_COUNT}" -gt 0 ]]; then
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
      --summary-table "${FUNGAL_SUMMARY_TABLE}"
      --output-dir "${BIGSCAPE_NETWORK_OUTPUT_DIR}"
      --formats "${BGC_OVERLAP_FORMATS}"
    )
    if [[ "${FORCE}" == "1" ]]; then
      log "FORCE=1: refreshing BGC overlap figure for ${PROJECT_NAME}"
    else
      log "Rendering BGC overlap figure for ${PROJECT_NAME}"
    fi
    if ! "${overlap_args[@]}"; then
      warn "BGC overlap rendering failed; continuing to remaining core figures."
    fi
  fi
else
  log "Skipping BGC overlap figure because RUN_BGC_OVERLAP_FIGURE=${RUN_BGC_OVERLAP_FIGURE} fungi=${FUNGI_COUNT}"
fi

BIGSCAPE_CLUSTERING_READY=0
if bigscape_clustering_inputs_ready "${BIGSCAPE_OUTPUT_FILES}"; then
  BIGSCAPE_CLUSTERING_READY=1
elif [[ "${RUN_BIGSCAPE_NETWORK_FIGURE}" == "1" || "${RUN_BIGSCAPE_MULTIPANEL_FIGURE}" == "1" ]]; then
  clear_bigscape_cluster_figures "${BIGSCAPE_NETWORK_OUTPUT_DIR}"
  log "BIGSCAPE_FIGURE_RESULT status=insufficient_data families=0 message=\"No BiG-SCAPE clustering tables were produced\""
fi

if [[ "${RUN_BIGSCAPE_NETWORK_FIGURE}" == "1" ]]; then
  if [[ "${BIGSCAPE_CLUSTERING_READY}" == "1" ]]; then
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
      if ! "${network_args[@]}"; then
        warn "BiG-SCAPE network rendering failed; continuing to remaining core figures."
      fi
    fi
  else
    log "Skipping BiG-SCAPE network figure; no clustering data are available."
  fi
else
  log "Skipping BiG-SCAPE network figure because RUN_BIGSCAPE_NETWORK_FIGURE=${RUN_BIGSCAPE_NETWORK_FIGURE}"
fi

render_taxon_bigscape_multipanel() {
  local taxon_group="$1"
  local count="$2"
  local prefix="$3"
  local summary_table="$4"
  local metadata_table="$5"
  local ecology_field="$6"
  if [[ "${RUN_BIGSCAPE_MULTIPANEL_FIGURE}" != "1" || "${count}" -le 0 ]]; then
    log "Skipping ${taxon_group} BiG-SCAPE multipanel because RUN_BIGSCAPE_MULTIPANEL_FIGURE=${RUN_BIGSCAPE_MULTIPANEL_FIGURE} count=${count}"
    return 0
  fi
  if [[ "${BIGSCAPE_CLUSTERING_READY}" != "1" ]]; then
    log "Skipping ${taxon_group} BiG-SCAPE multipanel; no clustering data are available."
    return 0
  fi
  if [[ ! -f "${RENDER_BIGSCAPE_MULTIPANEL_PY}" ]]; then
    warn "Missing BiG-SCAPE multipanel helper: ${RENDER_BIGSCAPE_MULTIPANEL_PY}; skipping ${taxon_group} multipanel."
    return 0
  fi
  if [[ ! -s "${summary_table}" || ! -s "${BIGSCAPE_REGION_CROSSWALK_TSV}" ]]; then
    warn "${taxon_group^} multipanel inputs are incomplete; summary and canonical region crosswalk are required."
    return 0
  fi
  if [[ "${FORCE}" != "1" ]] && bigscape_multipanel_outputs_ready "${BIGSCAPE_NETWORK_OUTPUT_DIR}" "${prefix}"; then
    log "Skipping ${taxon_group} BiG-SCAPE multipanel; outputs already exist (set FORCE=1 to refresh)"
    return 0
  fi
  PYTHON_BIN="$(resolve_python_bin)"
  local args=(
    "${PYTHON_BIN}" "${RENDER_BIGSCAPE_MULTIPANEL_PY}"
    --project-root "${PROJECT_DIR}"
    --project-name "${PROJECT_NAME}"
    --bigscape-root "${BIGSCAPE_OUTPUT_FILES}"
    --summary-table "${summary_table}"
    --output-dir "${BIGSCAPE_NETWORK_OUTPUT_DIR}"
    --prefix "${prefix}"
    --taxon-group "${taxon_group}"
    --taxon-manifest "${GENOME_TAXON_MANIFEST}"
    --region-crosswalk "${BIGSCAPE_REGION_CROSSWALK_TSV}"
    --ecology-field "${ecology_field}"
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
  [[ -f "${metadata_table}" ]] && args+=(--metadata "${metadata_table}")
  [[ -f "${BIGSCAPE_NETWORK_ANNOTATION_TABLE}" ]] && args+=(--annotation-table "${BIGSCAPE_NETWORK_ANNOTATION_TABLE}")
  [[ -n "${BIGSCAPE_NETWORK_DISTANCE_THRESHOLD}" ]] && args+=(--distance-threshold "${BIGSCAPE_NETWORK_DISTANCE_THRESHOLD}")
  [[ -n "${BIGSCAPE_NETWORK_SIMILARITY_THRESHOLD}" ]] && args+=(--similarity-threshold "${BIGSCAPE_NETWORK_SIMILARITY_THRESHOLD}")
  log "Rendering ${taxon_group} BiG-SCAPE multipanel for ${PROJECT_NAME}"
  "${args[@]}" || warn "${taxon_group^} BiG-SCAPE multipanel rendering failed; continuing to remaining core figures."
}

render_taxon_bigscape_multipanel \
  fungi "${FUNGI_COUNT}" fungi_big_scape_multipanel \
  "${FUNGAL_SUMMARY_TABLE}" "${FUNGAL_BIGSCAPE_METADATA_TSV}" \
  "${FUNGAL_BIGSCAPE_ECOLOGY_FIELD}"
render_taxon_bigscape_multipanel \
  bacteria "${BACTERIA_COUNT}" bacteria_big_scape_multipanel \
  "${SUMMARY_TABLE}" "${BACTERIAL_BIGSCAPE_METADATA_TSV}" \
  "${BACTERIAL_BIGSCAPE_ECOLOGY_FIELD}"

if [[ "${RUN_TAXON_TREE_FIGURE}" == "1" ]]; then
  if [[ ! -f "${RENDER_PHYLO_TAXON_PROFILE_PY}" ]]; then
    tree_error="Missing taxonomy context helper: ${RENDER_PHYLO_TAXON_PROFILE_PY}"
  elif [[ ! -s "${GENOME_TAXON_MANIFEST}" ]]; then
    tree_error="Canonical taxon manifest is missing: ${GENOME_TAXON_MANIFEST}"
  elif [[ "${FORCE}" != "1" ]] && taxon_tree_outputs_ready "${TAXON_TREE_OUTPUT_DIR}"; then
    tree_error=""
    log "Skipping taxonomy/BGC/GCF context tree; outputs already exist (set FORCE=1 to refresh)"
  else
    tree_error=""
    PYTHON_BIN="$(resolve_python_bin)"
    tree_args=(
      "${PYTHON_BIN}" "${RENDER_PHYLO_TAXON_PROFILE_PY}"
      --manifest "${GENOME_TAXON_MANIFEST}"
      --output-dir "${TAXON_TREE_OUTPUT_DIR}"
      --max-visible-arcs "${PHYLOGENY_MAX_VISIBLE_ARCS}"
      --gcf-category "${BIGSCAPE_NETWORK_CATEGORY}"
      --gcf-threshold "${BIGSCAPE_NETWORK_CLUSTERING_THRESHOLD}"
    )
    [[ -s "${TAXONOMY_METADATA_TSV}" ]] && tree_args+=(--taxonomy "${TAXONOMY_METADATA_TSV}")
    [[ -s "${BACTERIAL_EXACT_PRODUCTS_TSV}" ]] && tree_args+=(--exact-products "${BACTERIAL_EXACT_PRODUCTS_TSV}")
    [[ -s "${BACTERIAL_CROSSWALK_TSV}" ]] && tree_args+=(--crosswalk "${BACTERIAL_CROSSWALK_TSV}")
    if "${PYTHON_BIN}" -c 'import cairosvg' >/dev/null 2>&1; then
      tree_args+=(--png)
    fi
    log "Rendering taxonomy/BGC/GCF context tree for ${PROJECT_NAME}"
    tree_started="${SECONDS}"
    if "${tree_args[@]}"; then
      log "TREE_ARTIFACT kind=taxonomy_context basis=taxonomy status=success elapsed_s=$((SECONDS - tree_started))"
    else
      tree_error="Taxonomy/BGC/GCF context rendering failed"
    fi
  fi
  if [[ -n "${tree_error:-}" ]]; then
    if [[ "${TAXON_TREE_REQUIRED}" == "1" ]]; then
      die "${tree_error}"
    fi
    warn "${tree_error}; continuing because TAXON_TREE_REQUIRED=${TAXON_TREE_REQUIRED}."
  fi
else
  log "Skipping taxonomy/BGC/GCF context tree because RUN_TAXON_TREE_FIGURE=${RUN_TAXON_TREE_FIGURE}"
fi

cleanup_redundant_figure_outputs "${BIGSCAPE_NETWORK_OUTPUT_DIR}"
log "run_figures.sh complete."
