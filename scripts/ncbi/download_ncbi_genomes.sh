#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd -P)}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_ROOT}")}"
ACCESSIONS_FILE="${ACCESSIONS_FILE:-${PROJECT_ROOT}/accessions.txt}"
GENOME_ROOT="${GENOME_ROOT:-${PROJECT_ROOT}/data/genomes/fungi/${PROJECT_NAME}}"
NCBI_CLI_ROOT="${NCBI_CLI_ROOT:-${PROJECT_ROOT}/software/ncbi_cli}"

INCLUDE_SETS=(
  "genome,gff3,gbff"
  "genome,gbff"
  "genome"
)

MIN_STATUS_TO_SKIP="${MIN_STATUS_TO_SKIP:-partial}"
RETRIES="${RETRIES:-2}"
SLEEP_BETWEEN="${SLEEP_BETWEEN:-2}"

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

is_nonretryable_datasets_error() {
  local output_path="$1"
  grep -Eiq \
    "no genome assemblies that match your query|invalid.+accession|not a valid accession|unable to resolve accession" \
    "${output_path}"
}

download_and_extract_with_includes() {
  local datasets_cmd="$1"
  local acc="$2"
  local acc_dir="$3"
  local include_set="$4"

  local zip_path="${acc_dir}/${acc}.zip"
  local output_path="${acc_dir}/${acc}.datasets.log"
  local zip_arg
  zip_arg="$(to_maybe_win_mixed "${datasets_cmd}" "${zip_path}")"

  if ! "${datasets_cmd}" download genome accession "${acc}" \
        --include "${include_set}" \
        --filename "${zip_arg}" \
        --no-progressbar >"${output_path}" 2>&1; then
    cat "${output_path}" >&2
    rm -f "${zip_path}" 2>/dev/null || true
    if is_nonretryable_datasets_error "${output_path}"; then
      rm -f "${output_path}" 2>/dev/null || true
      return 10
    fi
    rm -f "${output_path}" 2>/dev/null || true
    return 1
  fi
  cat "${output_path}" >&2
  rm -f "${output_path}" 2>/dev/null || true

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
    nonretryable=0
    for include_set in "${INCLUDE_SETS[@]}"; do
      rc=0
      download_and_extract_with_includes "${datasets_cmd}" "${acc}" "${acc_dir}" "${include_set}" || rc=$?
      if [[ "${rc}" -eq 0 ]]; then
        used_set="${include_set}"
        break
      fi
      if [[ "${rc}" -eq 10 ]]; then
        nonretryable=1
        echo "       nonretryable=accession_not_found via --include ${include_set}"
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
    if [[ "${nonretryable}" -eq 1 ]]; then
      break
    fi
    sleep "${SLEEP_BETWEEN}"
  done

  if [[ "${success}" -ne 1 ]]; then
    echo "[FAIL] ${acc}"
  fi
done < "${ACCESSIONS_FILE}"
