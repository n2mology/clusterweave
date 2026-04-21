#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${PROJECT_ROOT:-${SCRIPT_DIR}}"
INSTALL_DIR="${INSTALL_DIR:-${PROJECT_ROOT}/Software/ncbi_cli}"
NCBI_CLI_TARGET="${NCBI_CLI_TARGET:-auto}"

ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "[$(ts)] [INFO] $*"; }
die(){ echo "[$(ts)] [ERROR] $*" >&2; exit 1; }

have(){ command -v "$1" >/dev/null 2>&1; }

detect_target() {
  if [[ "${NCBI_CLI_TARGET}" != "auto" ]]; then
    printf '%s\n' "${NCBI_CLI_TARGET}"
    return 0
  fi

  case "$(uname -s)" in
    Linux*) printf 'linux-amd64\n' ;;
    Darwin*) printf 'mac\n' ;;
    MINGW*|MSYS*|CYGWIN*) printf 'win64\n' ;;
    *) die "Unsupported platform for automatic NCBI CLI target detection. Set NCBI_CLI_TARGET manually." ;;
  esac
}

target="$(detect_target)"
mkdir -p "${INSTALL_DIR}"

case "${target}" in
  linux-amd64)
    datasets_name="datasets"
    dataformat_name="dataformat"
    datasets_url="https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/linux-amd64/datasets"
    dataformat_url="https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/linux-amd64/dataformat"
    ;;
  mac)
    datasets_name="datasets"
    dataformat_name="dataformat"
    datasets_url="https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/mac/datasets"
    dataformat_url="https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/mac/dataformat"
    ;;
  win64)
    datasets_name="datasets.exe"
    dataformat_name="dataformat.exe"
    datasets_url="https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/win64/datasets.exe"
    dataformat_url="https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/win64/dataformat.exe"
    ;;
  *)
    die "Unsupported NCBI_CLI_TARGET=${target}. Use linux-amd64, mac, or win64."
    ;;
esac

have curl || die "curl is required to download the NCBI CLI tools."

log "Installing NCBI CLI tools into ${INSTALL_DIR}"
curl -L --fail -o "${INSTALL_DIR}/${datasets_name}" "${datasets_url}"
curl -L --fail -o "${INSTALL_DIR}/${dataformat_name}" "${dataformat_url}"

if [[ "${target}" != "win64" ]]; then
  chmod +x "${INSTALL_DIR}/${datasets_name}" "${INSTALL_DIR}/${dataformat_name}"
fi

log "Installed ${datasets_name} and ${dataformat_name}"

