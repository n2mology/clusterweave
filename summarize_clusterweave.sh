#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

###############################################################################
# Env-backed project paths
###############################################################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
PROJECTS_ROOT="${PROJECTS_ROOT:-${PROJECT_DIR}}"
DATA_ROOT="${DATA_ROOT:-${PROJECTS_ROOT}/data}"
RESULTS_BASE="${RESULTS_BASE:-${DATA_ROOT}/results}"
RESULTS_ROOT="${RESULTS_ROOT:-${RESULTS_BASE}/${PROJECT_NAME}}"

###############################################################################

ANTISMASH_ROOT="${ANTISMASH_ROOT:-${RESULTS_ROOT}/antismash}"
FUNBGCEX_ROOT="${FUNBGCEX_ROOT:-${RESULTS_ROOT}/funbgcex}"
BIGSCAPE_ROOT="${BIGSCAPE_ROOT:-${RESULTS_ROOT}/big_scape}"
INPUT_GBKS_ROOT="${INPUT_GBKS_ROOT:-${RESULTS_ROOT}/input_gbks}"
OUTDIR="${OUTDIR:-${RESULTS_ROOT}/summary}"
SUMMARY_TABLES_ROOT="${SUMMARY_TABLES_ROOT:-${RESULTS_ROOT}/summary_tables}"
mkdir -p "${OUTDIR}"
mkdir -p "${SUMMARY_TABLES_ROOT}"

SCAFFOLD_COMPARISON_CSV="${SCAFFOLD_COMPARISON_CSV:-${OUTDIR}/all_tools_scaffold_comparison.csv}"
BGC_COMPARISON_CSV="${BGC_COMPARISON_CSV:-${OUTDIR}/all_tools_bgc_comparison.csv}"
SUMMARY_CSV="${SUMMARY_CSV:-${OUTDIR}/all_tools_shared_unshared_summary.csv}"
GENOME_TAXON_MANIFEST="${GENOME_TAXON_MANIFEST:-${SUMMARY_TABLES_ROOT}/genome_taxon_manifest.tsv}"
ANTISMASH_PRODUCT_TYPES_TSV="${ANTISMASH_PRODUCT_TYPES_TSV:-${SUMMARY_TABLES_ROOT}/antismash_product_types_exact.tsv}"

export ANTISMASH_ROOT FUNBGCEX_ROOT BIGSCAPE_ROOT INPUT_GBKS_ROOT SCAFFOLD_COMPARISON_CSV BGC_COMPARISON_CSV SUMMARY_CSV GENOME_TAXON_MANIFEST ANTISMASH_PRODUCT_TYPES_TSV

have(){ command -v "$1" >/dev/null 2>&1; }
resolve_python_cmd() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if [[ -x "${PYTHON_BIN}" ]]; then
      printf '%s\n' "${PYTHON_BIN}"
      return 0
    fi
    if have "${PYTHON_BIN}"; then
      printf '%s\n' "${PYTHON_BIN}"
      return 0
    fi
    echo "ERROR: PYTHON_BIN is not executable or not found: ${PYTHON_BIN}" >&2
    exit 1
  fi
  if have python3; then
    printf '%s\n' "python3"
    return 0
  fi
  if have python; then
    printf '%s\n' "python"
    return 0
  fi
  echo "ERROR: neither python3 nor python found" >&2
  exit 1
}
PYTHON_BIN="$(resolve_python_cmd)"

BGC_GCF_CROSSWALK_PY="${BGC_GCF_CROSSWALK_PY:-${PROJECT_DIR}/bin/build_bgc_gcf_crosswalk.py}"
BIGSCAPE_GCF_CATEGORY="${BIGSCAPE_GCF_CATEGORY:-${BIGSCAPE_NETWORK_CATEGORY:-mix}}"
BIGSCAPE_GCF_THRESHOLD="${BIGSCAPE_GCF_THRESHOLD:-${BIGSCAPE_NETWORK_CLUSTERING_THRESHOLD:-0.3}}"
TARGETED_ANALYSIS_PY="${TARGETED_ANALYSIS_PY:-${PROJECT_DIR}/bin/build_candidate_tables.py}"
NORMALIZE_METADATA_PY="${NORMALIZE_METADATA_PY:-${PROJECT_DIR}/bin/normalize_metadata.py}"
ANALYSIS_SCOPE="${ANALYSIS_SCOPE:-fungi}"
if [[ "${ANALYSIS_SCOPE}" == "bacteria" ]]; then
  DEFAULT_ECOLOGY_FIELD="ecobac_primary"
  DEFAULT_METADATA_NAME="ecobac_metadata_normalized.tsv"
  DEFAULT_METADATA_TEMPLATE_NAME="ecobac_metadata_template.tsv"
else
  DEFAULT_ECOLOGY_FIELD="ecofun_primary"
  DEFAULT_METADATA_NAME="ecofun_metadata_normalized.tsv"
  DEFAULT_METADATA_TEMPLATE_NAME="ecofun_metadata_template.tsv"
fi
ECOLOGY_FIELD="${ECOLOGY_FIELD:-${DEFAULT_ECOLOGY_FIELD}}"
FOCUS_ECOLOGY_LABEL="${FOCUS_ECOLOGY_LABEL:-}"
RUN_ECOLOGY_ANALYSIS="${RUN_ECOLOGY_ANALYSIS:-0}"
AUTO_NORMALIZE_METADATA="${AUTO_NORMALIZE_METADATA:-1}"
ACCESSIONS_MAP="${ACCESSIONS_MAP:-${DATA_ROOT}/genomes/fungi/${PROJECT_NAME}/accessions_fungusID_taxonomyID.txt}"
METADATA_TSV="${METADATA_TSV:-${RESULTS_ROOT}/summary_tables/${DEFAULT_METADATA_NAME}}"
METADATA_TEMPLATE_TSV="${METADATA_TEMPLATE_TSV:-${RESULTS_ROOT}/summary_tables/${DEFAULT_METADATA_TEMPLATE_NAME}}"

SUMMARY_BUILDER_PY="${SCRIPT_DIR}/bin/summarize_clusterweave.py"
[[ -f "${SUMMARY_BUILDER_PY}" ]] || { echo "ERROR: summary builder not found: ${SUMMARY_BUILDER_PY}" >&2; exit 1; }
"${PYTHON_BIN}" "${SUMMARY_BUILDER_PY}"

[[ -f "${BGC_GCF_CROSSWALK_PY}" ]] || { echo "ERROR: crosswalk builder not found: ${BGC_GCF_CROSSWALK_PY}" >&2; exit 1; }
[[ -f "${TARGETED_ANALYSIS_PY}" ]] || { echo "ERROR: targeted analysis script not found: ${TARGETED_ANALYSIS_PY}" >&2; exit 1; }

"${PYTHON_BIN}" "${BGC_GCF_CROSSWALK_PY}" \
  --project-root "${PROJECTS_ROOT}" \
  --project-name "${PROJECT_NAME}" \
  --selected-gcf-category "${BIGSCAPE_GCF_CATEGORY}" \
  --selected-gcf-threshold "${BIGSCAPE_GCF_THRESHOLD}"

if [[ "${RUN_ECOLOGY_ANALYSIS}" != "1" ]]; then
  echo "Skipped ecology-aware ranking: set RUN_ECOLOGY_ANALYSIS=1 to enable metadata-driven candidate tables."
  echo "Done."
  exit 0
fi

if [[ ! -f "${METADATA_TSV}" && "${AUTO_NORMALIZE_METADATA}" == "1" ]]; then
  if [[ -f "${NORMALIZE_METADATA_PY}" && -f "${ACCESSIONS_MAP}" ]]; then
    echo "Metadata TSV missing; generating a normalized scaffold from ${ACCESSIONS_MAP}"
    "${PYTHON_BIN}" "${NORMALIZE_METADATA_PY}" \
      --accessions "${ACCESSIONS_MAP}" \
      --out "${METADATA_TSV}" \
      --template-out "${METADATA_TEMPLATE_TSV}" \
      --allow-missing-legacy
  else
    echo "WARN: metadata TSV missing and auto-normalization inputs are incomplete." >&2
    [[ -f "${NORMALIZE_METADATA_PY}" ]] || echo "WARN: normalize_metadata.py not found: ${NORMALIZE_METADATA_PY}" >&2
    [[ -f "${ACCESSIONS_MAP}" ]] || echo "WARN: accession mapping not found: ${ACCESSIONS_MAP}" >&2
  fi
fi

if [[ ! -f "${METADATA_TSV}" ]]; then
  echo "WARN: skipping candidate ranking because metadata is missing: ${METADATA_TSV}" >&2
  echo "Done."
  exit 0
fi

candidate_args=(
  "${PYTHON_BIN}" "${TARGETED_ANALYSIS_PY}"
  --project-root "${PROJECTS_ROOT}"
  --project-name "${PROJECT_NAME}"
  --metadata "${METADATA_TSV}"
  --ecology-field "${ECOLOGY_FIELD}"
)
if [[ -n "${TARGET_GENOME:-}" ]]; then
  candidate_args+=(--target-genome "${TARGET_GENOME}")
fi
if [[ -n "${FOCUS_ECOLOGY_LABEL}" ]]; then
  candidate_args+=(--focus-ecology-label "${FOCUS_ECOLOGY_LABEL}")
fi
"${candidate_args[@]}"

echo "Done."
