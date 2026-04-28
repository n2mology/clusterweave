#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ENGINE="${ENGINE:-}"
SIF_OUT="${SIF_OUT:-${SCRIPT_DIR}/funbgcex_bundle.sif}"
DEF="${DEF:-${SCRIPT_DIR}/Singularity.def}"
DOCKERFILE="${DOCKERFILE:-${SCRIPT_DIR}/Dockerfile}"
BUILD_CONTEXT="${BUILD_CONTEXT:-${SCRIPT_DIR}}"
IMAGE_TAG="${IMAGE_TAG:-funbgcex:local-build}"

have() { command -v "$1" >/dev/null 2>&1; }

build_from_def() {
  local builder="$1"
  echo "Using ${builder} to build ${SIF_OUT} from ${DEF}"
  if "${builder}" build --fakeroot "${SIF_OUT}" "${DEF}"; then
    echo "Built ${SIF_OUT} (${builder} --fakeroot)"
    return 0
  fi
  echo "fakeroot failed; trying ${builder} build without fakeroot"
  "${builder}" build "${SIF_OUT}" "${DEF}"
  echo "Built ${SIF_OUT} (${builder})"
}

build_from_docker() {
  local builder="$1"
  [[ -s "${DOCKERFILE}" ]] || { echo "ERROR: Dockerfile not found: ${DOCKERFILE}" >&2; exit 1; }
  echo "Building Docker image ${IMAGE_TAG} from ${DOCKERFILE}"
  docker build -t "${IMAGE_TAG}" -f "${DOCKERFILE}" "${BUILD_CONTEXT}"
  echo "Converting Docker image ${IMAGE_TAG} to ${SIF_OUT} with ${builder}"
  "${builder}" build "${SIF_OUT}" "docker-daemon://${IMAGE_TAG}:latest"
  echo "Built ${SIF_OUT} (${builder} from docker-daemon)"
}

[[ -s "${DEF}" ]] || { echo "ERROR: definition file not found: ${DEF}" >&2; exit 1; }

mkdir -p "$(dirname "${SIF_OUT}")"

if [[ -n "${ENGINE}" ]]; then
  have "${ENGINE}" || { echo "ERROR: requested ENGINE not found: ${ENGINE}" >&2; exit 1; }
  build_from_def "${ENGINE}"
  exit 0
fi

if have singularity; then
  build_from_def singularity
  exit 0
fi

if have apptainer; then
  build_from_def apptainer
  exit 0
fi

if have docker; then
  if have singularity; then
    build_from_docker singularity
    exit 0
  fi
  if have apptainer; then
    build_from_docker apptainer
    exit 0
  fi
fi

echo "ERROR: no suitable builder found (singularity/apptainer, optionally docker)." >&2
exit 1
