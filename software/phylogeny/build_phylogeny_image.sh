#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
PHYLOGENY_DOCKER_IMAGE="${PHYLOGENY_DOCKER_IMAGE:-clusterweave-phylogeny:1.0.0}"
PHYLOGENY_IMAGE_DIGEST_FILE="${PHYLOGENY_IMAGE_DIGEST_FILE:-${SCRIPT_DIR}/phylogeny_image_digest.txt}"

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required for explicit phylogeny runtime setup" >&2; exit 1; }

docker build \
  --file "${SCRIPT_DIR}/Dockerfile" \
  --tag "${PHYLOGENY_DOCKER_IMAGE}" \
  "${REPO_ROOT}"

digest="$(docker image inspect --format '{{index .RepoDigests 0}}' "${PHYLOGENY_DOCKER_IMAGE}" 2>/dev/null || true)"
image_id="$(docker image inspect --format '{{.Id}}' "${PHYLOGENY_DOCKER_IMAGE}")"
{
  printf 'image=%s\n' "${PHYLOGENY_DOCKER_IMAGE}"
  printf 'repo_digest=%s\n' "${digest:-unavailable_for_local_build}"
  printf 'image_id=%s\n' "${image_id}"
} > "${PHYLOGENY_IMAGE_DIGEST_FILE}"

docker run --rm --network none "${PHYLOGENY_DOCKER_IMAGE}" clusterweave-phylogeny-versions
echo "Wrote pinned runtime identity: ${PHYLOGENY_IMAGE_DIGEST_FILE}"
