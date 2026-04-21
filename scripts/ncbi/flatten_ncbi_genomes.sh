#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd -P)}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_ROOT}")}"
GENOME_ROOT="${GENOME_ROOT:-${PROJECT_ROOT}/Data/Genomes/Fungi/${PROJECT_NAME}}"

die(){ echo "ERROR: $*" >&2; exit 1; }
warn(){ echo "WARN: $*" >&2; }

[[ -d "${GENOME_ROOT}" ]] || die "GENOME_ROOT not found: ${GENOME_ROOT}"

while IFS= read -r -d '' gdir; do
  data_sub="$(find "${gdir}/ncbi_dataset/data" -mindepth 1 -maxdepth 2 -type d 2>/dev/null | head -n 1 || true)"
  [[ -n "${data_sub}" && -d "${data_sub}" ]] || continue

  fungus_id="$(basename "${gdir}")"

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

