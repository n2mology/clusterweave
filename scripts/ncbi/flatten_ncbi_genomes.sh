#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd -P)}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_ROOT}")}"
GENOME_ROOT="${GENOME_ROOT:-${PROJECT_ROOT}/data/genomes/fungi/${PROJECT_NAME}}"
TAXON_GROUP="${TAXON_GROUP:-fungi}"
if [[ -z "${MAPPING_FILE+x}" ]]; then
  if [[ "${TAXON_GROUP}" == "bacteria" ]]; then
    MAPPING_FILE="${GENOME_ROOT}/accessions_bacteriaID_taxonomyID.txt"
  else
    MAPPING_FILE="${GENOME_ROOT}/accessions_fungusID_taxonomyID.txt"
  fi
fi

die(){ echo "ERROR: $*" >&2; exit 1; }
warn(){ echo "WARN: $*" >&2; }

[[ -d "${GENOME_ROOT}" ]] || die "GENOME_ROOT not found: ${GENOME_ROOT}"

genome_stem_has_file() {
  local stem="$1"
  local ext
  for ext in fna fa fsa fasta gb gbk gbff; do
    [[ -s "${GENOME_ROOT}/${stem}.${ext}" ]] && return 0
  done
  return 1
}

mapped_canonical_stem() {
  local stem="$1"
  [[ -f "${MAPPING_FILE}" ]] || return 1
  awk -F '\t' -v stem="${stem}" '$1 == stem && $2 != "" && $2 != stem { print $2; exit }' "${MAPPING_FILE}"
}

while IFS= read -r -d '' gdir; do
  data_sub="$(find "${gdir}/ncbi_dataset/data" -mindepth 1 -maxdepth 2 -type d 2>/dev/null | head -n 1 || true)"
  [[ -n "${data_sub}" && -d "${data_sub}" ]] || continue

  fungus_id="$(basename "${gdir}")"
  canonical_id="$(mapped_canonical_stem "${fungus_id}" || true)"
  if [[ -n "${canonical_id}" ]] && genome_stem_has_file "${canonical_id}"; then
    warn "skipping accession alias flatten: ${fungus_id} maps to existing ${canonical_id}"
    continue
  fi

  fna="$(find "${data_sub}" -maxdepth 1 -type f -iname "*.fna" 2>/dev/null | head -n 1 || true)"
  gff="$(find "${data_sub}" -maxdepth 1 -type f \( -iname "*.gff" -o -iname "*.gff3" \) 2>/dev/null | head -n 1 || true)"
  gbk="$(find "${data_sub}" -maxdepth 1 -type f \( -iname "*.gbff" -o -iname "*.gbk" -o -iname "*.gb" \) 2>/dev/null | head -n 1 || true)"

  if [[ -z "${fna}" ]]; then
    warn "no .fna found, skipping flatten: ${fungus_id}"
    continue
  fi

  fna_dst="${GENOME_ROOT}/${fungus_id}.fna"
  if [[ -e "${fna_dst}" ]]; then
    warn "destination exists, leaving .fna in place: ${fna_dst}"
  else
    mv -f "${fna}" "${fna_dst}"
  fi

  if [[ -n "${gff}" ]]; then
    gff_ext="${gff##*.}"
    gff_dst="${GENOME_ROOT}/${fungus_id}.${gff_ext}"
    if [[ -e "${gff_dst}" ]]; then
      warn "destination exists, leaving gff in place: ${gff_dst}"
    else
      mv -f "${gff}" "${gff_dst}"
    fi
  fi

  if [[ -n "${gbk}" ]]; then
    gbk_ext="${gbk##*.}"
    gbk_dst="${GENOME_ROOT}/${fungus_id}.${gbk_ext}"
    if [[ -e "${gbk_dst}" ]]; then
      warn "destination exists, leaving genbank in place: ${gbk_dst}"
    else
      mv -f "${gbk}" "${gbk_dst}"
    fi
  fi

  remaining="$(find "${data_sub}" -maxdepth 1 -type f \( -iname "*.fna" -o -iname "*.gff" -o -iname "*.gff3" -o -iname "*.gbff" -o -iname "*.gbk" -o -iname "*.gb" \) 2>/dev/null | head -n 1 || true)"
  if [[ -z "${remaining}" ]]; then
    rm -rf "${gdir}"
  else
    warn "kept directory (remaining files due to conflicts): ${fungus_id}"
  fi
done < <(find "${GENOME_ROOT}" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)
