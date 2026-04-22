#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
R_BIN="${R_BIN:-}"
RENDER_FIGURES_R="${RENDER_FIGURES_R:-${PROJECT_DIR}/bin/render_summary_figures.R}"

ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "[$(ts)] [INFO] $*"; }
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

  die "Rscript not found. Install R, add Rscript to PATH, or set R_BIN."
}

[[ -f "${RENDER_FIGURES_R}" ]] || die "Missing R helper: ${RENDER_FIGURES_R}"
R_BIN="$(resolve_r_bin)"

log "Rendering summary figures for ${PROJECT_NAME}"
"${R_BIN}" "${RENDER_FIGURES_R}" \
  --project-root "${PROJECT_DIR}" \
  --project-name "${PROJECT_NAME}"
log "run_figures.sh complete."
