#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ENGINE="${ENGINE:-}"
SIF_OUT="${SIF_OUT:-${SCRIPT_DIR}/funannotate_v1.8.17.sif}"
DEF="${DEF:-${SCRIPT_DIR}/Singularity.def}"
DOCKERFILE="${DOCKERFILE:-${SCRIPT_DIR}/Dockerfile}"
BUILD_CONTEXT="${BUILD_CONTEXT:-${SCRIPT_DIR}}"
IMAGE_TAG="${IMAGE_TAG:-clusterweave-funannotate:v1.8.17-busco}"
FUNANNOTATE_BASE_IMAGE="${FUNANNOTATE_BASE_IMAGE:-nextgenusfs/funannotate:v1.8.17}"
FUNANNOTATE_DB="${FUNANNOTATE_DB:-/opt/databases}"
FUNANNOTATE_BUSCO_DBS="${FUNANNOTATE_BUSCO_DBS:-ascomycota basidiomycota microsporidia dikarya fungi}"

have() { command -v "$1" >/dev/null 2>&1; }

path_with_absolute_parent() {
  local path="$1"
  local parent
  local name
  parent="$(dirname "${path}")"
  name="$(basename "${path}")"
  mkdir -p "${parent}"
  parent="$(cd "${parent}" && pwd -P)"
  printf '%s/%s\n' "${parent}" "${name}"
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [build|docker|sif|inventory|validate]

Builds a ClusterWeave funannotate SIF with selected old funannotate-compatible
BUSCO DBs baked into FUNANNOTATE_DB. DB installation happens once during image/SIF
preparation, never during a public job.

Environment:
  SIF_OUT=...                  Output SIF (default: ${SIF_OUT})
  ENGINE=singularity|apptainer Optional SIF builder
  IMAGE_TAG=...                Intermediate Docker image tag (default: ${IMAGE_TAG})
  FUNANNOTATE_BASE_IMAGE=...   Base Docker image (default: ${FUNANNOTATE_BASE_IMAGE})
  FUNANNOTATE_DB=...           Runtime DB root (default: ${FUNANNOTATE_DB})
  FUNANNOTATE_BUSCO_DBS=...    Space-separated old DB names
                               (default: ${FUNANNOTATE_BUSCO_DBS})

Commands:
  build      Build the best available local runtime, then inventory it
  docker     Build the local Docker image, then inventory it
  sif        Build the local SIF, then inventory it
  inventory  Print installed DB status from SIF_OUT or IMAGE_TAG
  validate   Fail unless every requested DB has hmms/ files and predict accepts it
EOF
}

db_check_snippet() {
  cat <<'EOF'
set -eu
base="${FUNANNOTATE_DB:-/opt/databases}"
for db in "$@"; do
  if test -d "${base}/${db}/hmms" && find "${base}/${db}/hmms" -type f -print -quit | grep -q .; then
    printf '%s\tinstalled\n' "${db}"
  else
    printf '%s\tmissing\n' "${db}"
    exit_code=1
  fi
done
exit "${exit_code:-0}"
EOF
}

predict_accepts_snippet() {
  cat <<'EOF'
set -eu
if ! command -v python >/dev/null 2>&1; then
  printf 'python\tmissing\n'
  exit 1
fi
funannotate_probe="$("/venv/bin/funannotate" --help 2>&1 || true)"
if ! printf '%s\n' "${funannotate_probe}" | grep -Eqi 'Usage:|Description:|funannotate'; then
  printf 'funannotate\texecutable_failed\n'
  exit 1
fi
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
for db in "$@"; do
  log="${tmp}/predict-${db}.log"
  if /venv/bin/funannotate predict -i "${tmp}/missing.fna" -o "${tmp}/predict-${db}" \
      --species "ClusterWeave probe" --organism fungus --busco_db "${db}" \
      --cpus 1 --name "cw${db}_" --tmpdir "${tmp}/tmp-${db}" --force >"${log}" 2>&1; then
    printf '%s\taccepted\n' "${db}"
  elif grep -Eq "busco database is not found|database not properly configured|Can't find Repeat Database" "${log}"; then
    printf '%s\trejected\n' "${db}"
    exit_code=1
  else
    printf '%s\taccepted\n' "${db}"
  fi
done
exit "${exit_code:-0}"
EOF
}

docker_image_exists() {
  have docker && docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1
}

run_in_runtime() {
  if [[ -s "${SIF_OUT}" ]]; then
    if have singularity; then
      singularity exec "${SIF_OUT}" "$@"
      return $?
    fi
    if have apptainer; then
      apptainer exec "${SIF_OUT}" "$@"
      return $?
    fi
  fi
  if docker_image_exists; then
    docker run --rm --entrypoint "" -e "FUNANNOTATE_DB=${FUNANNOTATE_DB}" "${IMAGE_TAG}" "$@"
    return $?
  fi
  echo "ERROR: no built runtime found. Build first or provide SIF_OUT/IMAGE_TAG." >&2
  return 1
}

build_docker_image() {
  have docker || { echo "ERROR: docker is required to build ${IMAGE_TAG}" >&2; exit 1; }
  [[ -s "${DOCKERFILE}" ]] || { echo "ERROR: Dockerfile not found: ${DOCKERFILE}" >&2; exit 1; }
  echo "Building Docker image ${IMAGE_TAG} with BUSCO DBs: ${FUNANNOTATE_BUSCO_DBS}"
  docker build \
    --build-arg "FUNANNOTATE_BASE_IMAGE=${FUNANNOTATE_BASE_IMAGE}" \
    --build-arg "FUNANNOTATE_DB=${FUNANNOTATE_DB}" \
    --build-arg "FUNANNOTATE_BUSCO_DBS=${FUNANNOTATE_BUSCO_DBS}" \
    -t "${IMAGE_TAG}" \
    -f "${DOCKERFILE}" \
    "${BUILD_CONTEXT}"
}

build_sif_from_def() {
  local builder="$1"
  local def_dir
  local def_file

  def_dir="$(cd "$(dirname "${DEF}")" && pwd -P)" || {
    echo "ERROR: definition directory not found: $(dirname "${DEF}")" >&2
    exit 1
  }
  def_file="$(basename "${DEF}")"
  [[ -s "${def_dir}/${def_file}" ]] || { echo "ERROR: definition file not found: ${DEF}" >&2; exit 1; }
  SIF_OUT="$(path_with_absolute_parent "${SIF_OUT}")"
  echo "Building ${SIF_OUT} with ${builder}; BUSCO DBs: ${FUNANNOTATE_BUSCO_DBS}"
  if (
      cd "${def_dir}"
      FUNANNOTATE_BUSCO_DBS="${FUNANNOTATE_BUSCO_DBS}" FUNANNOTATE_DB="${FUNANNOTATE_DB}" \
        "${builder}" build --fakeroot "${SIF_OUT}" "${def_file}"
    ); then
    echo "Built ${SIF_OUT} (${builder} --fakeroot)"
    return 0
  fi
  echo "fakeroot failed; trying ${builder} build without fakeroot"
  (
    cd "${def_dir}"
    FUNANNOTATE_BUSCO_DBS="${FUNANNOTATE_BUSCO_DBS}" FUNANNOTATE_DB="${FUNANNOTATE_DB}" \
      "${builder}" build "${SIF_OUT}" "${def_file}"
  )
  echo "Built ${SIF_OUT} (${builder})"
}

convert_docker_to_sif() {
  local builder="$1"
  mkdir -p "$(dirname "${SIF_OUT}")"
  echo "Converting ${IMAGE_TAG} to ${SIF_OUT} with ${builder}"
  "${builder}" build "${SIF_OUT}" "docker-daemon://${IMAGE_TAG}"
  echo "Built ${SIF_OUT} (${builder} from docker-daemon)"
}

build_runtime() {
  if [[ -n "${ENGINE}" ]]; then
    have "${ENGINE}" || { echo "ERROR: requested ENGINE not found: ${ENGINE}" >&2; exit 1; }
    build_sif_from_def "${ENGINE}"
  elif have singularity; then
    build_sif_from_def singularity
  elif have apptainer; then
    build_sif_from_def apptainer
  else
    build_docker_image
  fi

  if [[ ! -s "${SIF_OUT}" ]] && docker_image_exists; then
    if have singularity; then
      convert_docker_to_sif singularity
    elif have apptainer; then
      convert_docker_to_sif apptainer
    fi
  fi

  validate_funannotate_busco_db_inventory
}

build_docker_runtime() {
  build_docker_image
  validate_funannotate_busco_db_inventory
}

build_sif_runtime() {
  if [[ -n "${ENGINE}" ]]; then
    have "${ENGINE}" || { echo "ERROR: requested ENGINE not found: ${ENGINE}" >&2; exit 1; }
    build_sif_from_def "${ENGINE}"
  elif have singularity; then
    build_sif_from_def singularity
  elif have apptainer; then
    build_sif_from_def apptainer
  elif have docker; then
    build_docker_image
    if have singularity; then
      convert_docker_to_sif singularity
    elif have apptainer; then
      convert_docker_to_sif apptainer
    else
      echo "ERROR: docker image built, but no singularity/apptainer is available to create ${SIF_OUT}" >&2
      exit 1
    fi
  else
    echo "ERROR: no suitable builder found for ${SIF_OUT}" >&2
    exit 1
  fi
  validate_funannotate_busco_db_inventory
}

validate_funannotate_busco_db_inventory() {
  echo "Checking FUNANNOTATE_DB inventory for: ${FUNANNOTATE_BUSCO_DBS}"
  # shellcheck disable=SC2086
  run_in_runtime sh -lc "$(db_check_snippet)" sh ${FUNANNOTATE_BUSCO_DBS}
}

assert_funannotate_predict_accepts_busco_dbs() {
  echo "Checking funannotate predict accepts: ${FUNANNOTATE_BUSCO_DBS}"
  # shellcheck disable=SC2086
  run_in_runtime sh -lc "$(predict_accepts_snippet)" sh ${FUNANNOTATE_BUSCO_DBS}
}

cmd="${1:-build}"
case "${cmd}" in
  build)
    build_runtime
    ;;
  docker)
    build_docker_runtime
    ;;
  sif)
    build_sif_runtime
    ;;
  inventory)
    validate_funannotate_busco_db_inventory
    ;;
  validate)
    validate_funannotate_busco_db_inventory
    assert_funannotate_predict_accepts_busco_dbs
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
