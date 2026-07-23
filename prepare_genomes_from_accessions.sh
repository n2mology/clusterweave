#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${PROJECT_ROOT:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_ROOT}")}"
ACCESSIONS_FILE="${ACCESSIONS_FILE:-${PROJECT_ROOT}/accessions.txt}"
DATA_ROOT="${DATA_ROOT:-${PROJECT_ROOT}/data}"
RESULTS_ROOT="${RESULTS_ROOT:-${DATA_ROOT}/results/${PROJECT_NAME}}"
FUNGI_GENOME_ROOT="${FUNGI_GENOME_ROOT:-${GENOME_ROOT:-${DATA_ROOT}/genomes/fungi/${PROJECT_NAME}}}"
BACTERIA_GENOME_ROOT="${BACTERIA_GENOME_ROOT:-${DATA_ROOT}/genomes/bacteria/${PROJECT_NAME}}"
GENOME_ROOT="${GENOME_ROOT:-${FUNGI_GENOME_ROOT}}"
GENOME_TAXON_MANIFEST="${GENOME_TAXON_MANIFEST:-${RESULTS_ROOT}/summary_tables/genome_taxon_manifest.tsv}"
WORK_ROOT="${WORK_ROOT:-/tmp/$(basename "${RESULTS_ROOT}")_work}"
PREP_ROOT="${WORK_ROOT}/genome_prep"
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
log "FUNGI_GENOME_ROOT=${FUNGI_GENOME_ROOT}"
log "BACTERIA_GENOME_ROOT=${BACTERIA_GENOME_ROOT}"
log "GENOME_TAXON_MANIFEST=${GENOME_TAXON_MANIFEST}"
log "This wrapper intentionally runs download -> rename -> flatten once per non-empty taxon root."

mkdir -p "${PREP_ROOT}" "${FUNGI_GENOME_ROOT}" "${BACTERIA_GENOME_ROOT}" "$(dirname "${GENOME_TAXON_MANIFEST}")"
FUNGI_ACCESSIONS="${PREP_ROOT}/accessions.fungi.txt"
BACTERIA_ACCESSIONS="${PREP_ROOT}/accessions.bacteria.txt"
: > "${FUNGI_ACCESSIONS}"
: > "${BACTERIA_ACCESSIONS}"

manifest_has_routes=0
if [[ -s "${GENOME_TAXON_MANIFEST}" ]] && awk -F '\t' 'NR > 1 && $2 != "" { found=1; exit } END { exit !found }' "${GENOME_TAXON_MANIFEST}"; then
  manifest_has_routes=1
fi

count_accessions() {
  awk '
    {
      sub(/\r$/, "")
      gsub(/^[[:space:]]+|[[:space:]]+$/, "")
      if ($0 != "" && $0 !~ /^#/) count++
    }
    END { print count + 0 }
  ' "$1"
}

if [[ "${manifest_has_routes}" -eq 1 ]]; then
  awk -F '\t' -v fungi_out="${FUNGI_ACCESSIONS}" -v bacteria_out="${BACTERIA_ACCESSIONS}" '
    FNR == NR {
      line=$0
      sub(/\r$/, "", line)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
      if (line != "" && line !~ /^#/) requested[toupper(line)]=line
      next
    }
    FNR == 1 {
      for (i=1; i<=NF; i++) h[$i]=i
      next
    }
    {
      accession=$(h["source_accession"])
      if (accession == "" && $(h["input_key"]) ~ /^GC[AF]_[0-9]+([.][0-9]+)?$/) accession=$(h["input_key"])
      key=toupper(accession)
      status=tolower($(h["route_status"]))
      if (!(key in requested) || status ~ /^(failed|invalid|rejected|unresolved|unsupported)$/) next
      taxon=tolower($(h["taxon_group"]))
      if (taxon == "fungi") print requested[key] >> fungi_out
      else if (taxon == "bacteria") print requested[key] >> bacteria_out
    }
  ' "${ACCESSIONS_FILE}" "${GENOME_TAXON_MANIFEST}"

  requested_count="$(count_accessions "${ACCESSIONS_FILE}")"
  routed_count=$(( $(count_accessions "${FUNGI_ACCESSIONS}") + $(count_accessions "${BACTERIA_ACCESSIONS}") ))
  [[ "${routed_count}" -eq "${requested_count}" ]] \
    || die "Immutable taxon routes cover ${routed_count}/${requested_count} requested accessions"
else
  cp -f "${ACCESSIONS_FILE}" "${FUNGI_ACCESSIONS}"
fi

prepare_taxon() {
  local taxon_group="$1"
  local accession_file="$2"
  local genome_root="$3"
  local mapping_file="$4"
  local accession_count=""
  accession_count="$(count_accessions "${accession_file}")"
  [[ "${accession_count}" -gt 0 ]] || {
    log "Skipping ${taxon_group} genome preparation: no routed accessions"
    return 0
  }

  local common_env=(
    PROJECT_ROOT="${PROJECT_ROOT}"
    PROJECT_NAME="${PROJECT_NAME}"
    DATA_ROOT="${DATA_ROOT}"
    RESULTS_ROOT="${RESULTS_ROOT}"
    ACCESSIONS_FILE="${accession_file}"
    GENOME_ROOT="${genome_root}"
    GENOME_TAXON_MANIFEST="${GENOME_TAXON_MANIFEST}"
    TAXON_GROUP="${taxon_group}"
    MAPPING_FILE="${mapping_file}"
  )

  log "Preparing ${accession_count} ${taxon_group} accession(s) under ${genome_root}"
  if [[ "${RUN_DOWNLOAD}" == "1" ]]; then
    log "${taxon_group} stage 1/3: downloading NCBI genomes"
    env "${common_env[@]}" bash "${DOWNLOAD_SCRIPT}"
  else
    log "${taxon_group} stage 1/3: skipped"
  fi

  if [[ "${RUN_RENAME}" == "1" ]]; then
    log "${taxon_group} stage 2/3: renaming NCBI genomes"
    env "${common_env[@]}" bash "${RENAME_SCRIPT}"
  else
    log "${taxon_group} stage 2/3: skipped"
  fi

  if [[ "${RUN_FLATTEN}" == "1" ]]; then
    log "${taxon_group} stage 3/3: flattening renamed genomes"
    env "${common_env[@]}" bash "${FLATTEN_SCRIPT}"
  else
    log "${taxon_group} stage 3/3: skipped"
  fi
}

prepare_taxon \
  fungi "${FUNGI_ACCESSIONS}" "${FUNGI_GENOME_ROOT}" \
  "${FUNGI_GENOME_ROOT}/accessions_fungusID_taxonomyID.txt"
prepare_taxon \
  bacteria "${BACTERIA_ACCESSIONS}" "${BACTERIA_GENOME_ROOT}" \
  "${BACTERIA_GENOME_ROOT}/accessions_bacteriaID_taxonomyID.txt"

if [[ "${manifest_has_routes}" -eq 0 ]]; then
  fungal_mapping="${FUNGI_GENOME_ROOT}/accessions_fungusID_taxonomyID.txt"
  if [[ -s "${fungal_mapping}" ]]; then
    {
      printf 'input_key\tgenome_id\ttaxon_group\ttaxon_source\ttaxid\torganism_name\tsource_accession\tprediction_method\tdetector_profile\tinput_path_key\troute_status\troute_reason\n'
      awk -F '\t' -v project="${PROJECT_NAME}" '
        NF >= 2 && $1 != "" && $2 != "" {
          printf "%s\t%s\tfungi\tncbi\t%s\t%s\t%s\tfunannotate\tantismash+funbgcex\tgenomes/fungi/%s/%s\trouted\thistorical fungal accession route\n",
            $1, $2, $3, $5, $1, project, $2
        }
      ' "${fungal_mapping}"
    } > "${GENOME_TAXON_MANIFEST}"
  fi
fi

log "Genome preparation complete."
