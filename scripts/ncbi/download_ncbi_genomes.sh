#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd -P)}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_ROOT}")}"
ACCESSIONS_FILE="${ACCESSIONS_FILE:-${PROJECT_ROOT}/accessions.txt}"
GENOME_ROOT="${GENOME_ROOT:-${PROJECT_ROOT}/Data/Genomes/Fungi/${PROJECT_NAME}}"
NCBI_CLI_ROOT="${NCBI_CLI_ROOT:-${PROJECT_ROOT}/Software/ncbi_cli}"

INCLUDE_SETS=(
  "genome,gff3,gbff"
  "genome,gbff"
  "genome"
)

MIN_STATUS_TO_SKIP="${MIN_STATUS_TO_SKIP:-partial}"
RETRIES="${RETRIES:-2}"
SLEEP_BETWEEN="${SLEEP_BETWEEN:-2}"

die(){ echo "ERROR: $*" >&2; exit 1; }

resolve_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    command -v "${PYTHON_BIN}" >/dev/null 2>&1 || die "PYTHON_BIN not found in PATH: ${PYTHON_BIN}"
    printf '%s\n' "${PYTHON_BIN}"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
    return 0
  fi
  die "No Python interpreter found. Install python3 or set PYTHON_BIN."
}

detect_datasets() {
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

to_maybe_win_mixed() {
  if [[ "$1" =~ \.exe$ ]] && command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$2"
  else
    printf '%s' "$2"
  fi
}

extract_zip() {
  local zip_path="$1"
  local out_dir="$2"

  if command -v unzip >/dev/null 2>&1; then
    unzip -q -o "${zip_path}" -d "${out_dir}"
    return 0
  fi

  "${PYTHON_CMD}" - "${zip_path}" "${out_dir}" <<'PY'
from pathlib import Path
import sys
import zipfile

zip_path = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
with zipfile.ZipFile(zip_path) as zf:
    zf.extractall(out_dir)
PY
}

get_status() {
  local acc_dir="$1"
  local base="${acc_dir}/ncbi_dataset/data"

  local fna gff gbff
  fna="$(find "${base}" -maxdepth 3 -type f -name "*.fna" 2>/dev/null | head -n 1 || true)"
  gff="$(find "${base}" -maxdepth 3 -type f \( -name "genomic.gff" -o -name "genomic.gff3" -o -name "*.gff" -o -name "*.gff3" \) 2>/dev/null | head -n 1 || true)"
  gbff="$(find "${base}" -maxdepth 3 -type f -name "*.gbff" 2>/dev/null | head -n 1 || true)"

  if [[ -n "${fna}" && -f "${fna}" && -n "${gff}" && -f "${gff}" && -n "${gbff}" && -f "${gbff}" ]]; then
    printf "complete"
  elif [[ -n "${fna}" && -f "${fna}" && -n "${gbff}" && -f "${gbff}" ]]; then
    printf "partial"
  elif [[ -n "${fna}" && -f "${fna}" ]]; then
    printf "genome"
  else
    printf "none"
  fi
}

should_skip() {
  local status="$1"
  case "${MIN_STATUS_TO_SKIP}" in
    complete) [[ "${status}" == "complete" ]] ;;
    partial)  [[ "${status}" == "complete" || "${status}" == "partial" ]] ;;
    genome)   [[ "${status}" == "complete" || "${status}" == "partial" || "${status}" == "genome" ]] ;;
    *) die "Invalid MIN_STATUS_TO_SKIP=${MIN_STATUS_TO_SKIP}" ;;
  esac
}

clean_partial() {
  local acc_dir="$1"
  rm -rf "${acc_dir}/ncbi_dataset" \
         "${acc_dir}/dataset_catalog.json" \
         "${acc_dir}/README.md" \
         "${acc_dir}/md5sum.txt" 2>/dev/null || true
}

download_and_extract_with_includes() {
  local datasets_cmd="$1"
  local acc="$2"
  local acc_dir="$3"
  local include_set="$4"

  local zip_path="${acc_dir}/${acc}.zip"
  local zip_arg
  zip_arg="$(to_maybe_win_mixed "${datasets_cmd}" "${zip_path}")"

  if ! "${datasets_cmd}" download genome accession "${acc}" \
        --include "${include_set}" \
        --filename "${zip_arg}" \
        --no-progressbar; then
    rm -f "${zip_path}" 2>/dev/null || true
    return 1
  fi

  if ! extract_zip "${zip_path}" "${acc_dir}"; then
    rm -f "${zip_path}" 2>/dev/null || true
    return 2
  fi

  rm -f "${zip_path}"
  return 0
}

[[ -f "${ACCESSIONS_FILE}" ]] || die "ACCESSIONS_FILE not found: ${ACCESSIONS_FILE}"
datasets_cmd="$(detect_datasets)" || die "datasets not found in PATH or ${NCBI_CLI_ROOT}"
PYTHON_CMD="$(resolve_python)"
mkdir -p "${GENOME_ROOT}"

while IFS= read -r acc || [[ -n "${acc}" ]]; do
  acc="${acc//$'\r'/}"
  acc="$(printf "%s" "${acc}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [[ -z "${acc}" || "${acc}" =~ ^# ]] && continue

  acc_dir="${GENOME_ROOT}/${acc}"
  mkdir -p "${acc_dir}"

  status_now="$(get_status "${acc_dir}")"
  if should_skip "${status_now}"; then
    echo "[SKIP] ${acc} (status=${status_now})"
    continue
  fi

  echo "[WORK] ${acc} (current=${status_now})"
  clean_partial "${acc_dir}"

  attempt=0
  success=0
  while [[ "${attempt}" -le "${RETRIES}" ]]; do
    attempt=$((attempt + 1))
    used_set=""
    for include_set in "${INCLUDE_SETS[@]}"; do
      if download_and_extract_with_includes "${datasets_cmd}" "${acc}" "${acc_dir}" "${include_set}"; then
        used_set="${include_set}"
        break
      fi
    done

    status_after="$(get_status "${acc_dir}")"
    if [[ -n "${used_set}" && "${status_after}" != "none" ]]; then
      echo "       got=${status_after} via --include ${used_set}"
      success=1
      break
    fi

    clean_partial "${acc_dir}"
    sleep "${SLEEP_BETWEEN}"
  done

  if [[ "${success}" -ne 1 ]]; then
    echo "[FAIL] ${acc}"
  fi
done < "${ACCESSIONS_FILE}"
