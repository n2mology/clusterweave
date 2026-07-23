#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PHYLOGENY_SIF_PATH="${PHYLOGENY_SIF_PATH:-${SCRIPT_DIR}/clusterweave_phylogeny_1.0.0.sif}"
if [[ "${PHYLOGENY_SIF_PATH}" != /* ]]; then
  PHYLOGENY_SIF_PATH="$(pwd -P)/${PHYLOGENY_SIF_PATH}"
fi
ENGINE="${ENGINE:-}"
if [[ -z "${ENGINE}" ]]; then
  if command -v apptainer >/dev/null 2>&1; then ENGINE=apptainer
  elif command -v singularity >/dev/null 2>&1; then ENGINE=singularity
  else echo "ERROR: apptainer or singularity is required" >&2; exit 1
  fi
fi

(cd "${SCRIPT_DIR}" && "${ENGINE}" build "${PHYLOGENY_SIF_PATH}" "${SCRIPT_DIR}/Singularity.def")
"${ENGINE}" exec "${PHYLOGENY_SIF_PATH}" clusterweave-phylogeny-versions
sha256sum "${PHYLOGENY_SIF_PATH}" > "${PHYLOGENY_SIF_PATH}.sha256"
echo "Wrote pinned SIF and checksum: ${PHYLOGENY_SIF_PATH}"
