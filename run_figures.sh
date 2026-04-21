#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
R_BIN="${R_BIN:-Rscript}"
RENDER_FIGURES_R="${RENDER_FIGURES_R:-${PROJECT_DIR}/bin/render_summary_figures.R}"
FIGURES_TOP_N="${FIGURES_TOP_N:-15}"

ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "[$(ts)] [INFO] $*"; }
die(){ echo "[$(ts)] [ERROR] $*" >&2; exit 1; }

[[ -f "${RENDER_FIGURES_R}" ]] || die "Missing R helper: ${RENDER_FIGURES_R}"
command -v "${R_BIN}" >/dev/null 2>&1 || die "Rscript not found. Install R or set R_BIN."

log "Rendering summary figures for ${PROJECT_NAME}"
"${R_BIN}" "${RENDER_FIGURES_R}" \
  --project-root "${PROJECT_DIR}" \
  --project-name "${PROJECT_NAME}" \
  --top-n "${FIGURES_TOP_N}"
log "run_figures.sh complete."
