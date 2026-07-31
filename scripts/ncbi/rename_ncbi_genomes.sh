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
GENOME_TAXON_MANIFEST="${GENOME_TAXON_MANIFEST:-${PROJECT_ROOT}/data/results/${PROJECT_NAME}/summary_tables/genome_taxon_manifest.tsv}"
NCBI_CLI_ROOT="${NCBI_CLI_ROOT:-${PROJECT_ROOT}/software/ncbi_cli}"

die(){ echo "ERROR: $*" >&2; exit 1; }

is_windowsapps_alias() {
  local candidate_path="${1:-}"
  [[ -n "${candidate_path}" ]] || return 1
  case "${candidate_path}" in
    *"/Appdata/Local/Microsoft/WindowsApps/"*|*"\\AppData\\Local\\Microsoft\\WindowsApps\\"*)
      return 0
      ;;
  esac
  return 1
}

usable_python() {
  local candidate="${1:-}"
  [[ -n "${candidate}" ]] || return 1
  command -v "${candidate}" >/dev/null 2>&1 || return 1
  local resolved
  resolved="$(command -v "${candidate}" 2>/dev/null || true)"
  is_windowsapps_alias "${resolved}" && return 1
  "${candidate}" -c "import sys; print(sys.executable)" >/dev/null 2>&1 || return 1
  return 0
}

resolve_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    usable_python "${PYTHON_BIN}" || die "PYTHON_BIN is not a usable Python interpreter: ${PYTHON_BIN}"
    printf '%s\n' "${PYTHON_BIN}"
    return 0
  fi
  if usable_python python3; then
    printf '%s\n' "python3"
    return 0
  fi
  if usable_python python; then
    printf '%s\n' "python"
    return 0
  fi
  die "No usable Python interpreter found. Install python3 or set PYTHON_BIN to a real interpreter."
}

detect_datasets() {
  if [[ -n "${DATASETS_CMD:-}" ]]; then
    command -v "${DATASETS_CMD}" >/dev/null 2>&1 && printf '%s\n' "${DATASETS_CMD}" && return 0
    [[ -x "${DATASETS_CMD}" ]] && printf '%s\n' "${DATASETS_CMD}" && return 0
    return 1
  fi
  if command -v datasets >/dev/null 2>&1; then
    printf '%s\n' "datasets"
    return 0
  fi
  if [[ -x "${NCBI_CLI_ROOT}/datasets" ]]; then
    printf '%s\n' "${NCBI_CLI_ROOT}/datasets"
    return 0
  fi
  if [[ -f "${NCBI_CLI_ROOT}/datasets.exe" ]]; then
    printf '%s\n' "${NCBI_CLI_ROOT}/datasets.exe"
    return 0
  fi
  return 1
}

[[ -d "${GENOME_ROOT}" ]] || die "GENOME_ROOT not found: ${GENOME_ROOT}"
mkdir -p "$(dirname "${MAPPING_FILE}")"
PYTHON_CMD="$(resolve_python)"
DATASETS_CMD_RESOLVED="$(detect_datasets || true)"

RENAME_HELPER_PY="${SCRIPT_DIR}/rename_ncbi_genomes.py"
[[ -f "${RENAME_HELPER_PY}" ]] || die "Missing NCBI genome renamer helper: ${RENAME_HELPER_PY}"
"${PYTHON_CMD}" "${RENAME_HELPER_PY}" "${GENOME_ROOT}" "${MAPPING_FILE}" "${DATASETS_CMD_RESOLVED}" "${TAXON_GROUP}" "${GENOME_TAXON_MANIFEST}"

[[ -f "${MAPPING_FILE}" ]] || die "Failed to create mapping file: ${MAPPING_FILE}"

while IFS=$'\t' read -r acc fungus_id taxid genome_size_mb _mapping_rest || [[ -n "${acc:-}" ]]; do
  [[ -z "${acc:-}" || -z "${fungus_id:-}" ]] && continue

  old_dir="${GENOME_ROOT}/${acc}"
  new_dir="${GENOME_ROOT}/${fungus_id}"
  [[ -d "${old_dir}" ]] || continue

  if [[ -e "${new_dir}" && "${old_dir}" != "${new_dir}" ]]; then
    echo "WARN: target exists, skipping outer rename: ${new_dir}" >&2
    continue
  fi

  data_dir="${old_dir}/ncbi_dataset/data"
  if [[ -d "${data_dir}" ]]; then
    sub_old=""
    if [[ -d "${data_dir}/${acc}" ]]; then
      sub_old="${data_dir}/${acc}"
    else
      sub_old="$(find "${data_dir}" -mindepth 1 -maxdepth 1 -type d -name "${acc}*" 2>/dev/null | head -n 1 || true)"
    fi

    if [[ -n "${sub_old}" && -d "${sub_old}" ]]; then
      sub_new="${data_dir}/${fungus_id}"
      if [[ "${sub_old}" == "${sub_new}" ]]; then
        :
      elif [[ -e "${sub_new}" ]]; then
        echo "WARN: target exists, skipping subfolder rename: ${sub_new}" >&2
      else
        mv -f "${sub_old}" "${sub_new}"
      fi

      work_sub="${sub_new}"
      if [[ ! -d "${work_sub}" ]]; then
        work_sub="${sub_old}"
      fi
      work_sub="$(cd "${work_sub}" && pwd -P)"

      while IFS= read -r -d '' f; do
        b="$(basename "$f")"
        d="$(dirname "$f")"
        nb="${b//$acc/$fungus_id}"
        [[ "${nb}" == "${b}" ]] && continue
        [[ -e "${d}/${nb}" ]] && continue
        mv -f "$f" "${d}/${nb}"
      done < <(find "${work_sub}" -maxdepth 1 -type f -name "*${acc}*" -print0 2>/dev/null)

      fna="$(find "${work_sub}" -maxdepth 1 -type f -iname "*.fna" 2>/dev/null | head -n 1 || true)"
      if [[ -n "${fna}" ]]; then
        d="$(dirname "${fna}")"
        target="${d}/${fungus_id}.fna"
        [[ "${fna}" != "${target}" && ! -e "${target}" ]] && mv -f "${fna}" "${target}"
      fi

      gff="$(find "${work_sub}" -maxdepth 1 -type f \( -iname "genomic.gff" -o -iname "genomic.gff3" \) 2>/dev/null | head -n 1 || true)"
      if [[ -n "${gff}" ]]; then
        d="$(dirname "${gff}")"
        ext="${gff##*.}"
        target="${d}/${fungus_id}.${ext}"
        [[ "${gff}" != "${target}" && ! -e "${target}" ]] && mv -f "${gff}" "${target}"
      fi

      gbff="$(find "${work_sub}" -maxdepth 1 -type f -iname "genomic.gbff" 2>/dev/null | head -n 1 || true)"
      if [[ -n "${gbff}" ]]; then
        d="$(dirname "${gbff}")"
        target="${d}/${fungus_id}.gbff"
        [[ "${gbff}" != "${target}" && ! -e "${target}" ]] && mv -f "${gbff}" "${target}"
      fi
    fi
  fi

  if [[ "${old_dir}" != "${new_dir}" ]]; then
    mv -f "${old_dir}" "${new_dir}"
  fi
done < "${MAPPING_FILE}"
