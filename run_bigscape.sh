#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

###############################################################################
# run_bigscape.sh
# - Runs BiG-SCAPE on antiSMASH outputs for the active ClusterWeave project
# - Uses the shared BiG-SCAPE software/resources area by default
# - Reuses a prepopulated MiBIG cache when present
# - Falls back to extracting a local MiBIG archive or downloading one archive
###############################################################################

###############################################################################
# Env-backed project paths
###############################################################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
PROJECTS_ROOT="${PROJECTS_ROOT:-${PROJECT_DIR}}"
DATA_ROOT="${DATA_ROOT:-${PROJECTS_ROOT}/data}"
SOFTWARE_ROOT="${SOFTWARE_ROOT:-${PROJECTS_ROOT}/software}"
RESULTS_BASE="${RESULTS_BASE:-${DATA_ROOT}/results}"
RESULTS_ROOT="${RESULTS_ROOT:-${RESULTS_BASE}/${PROJECT_NAME}}"

ANTISMASH_ROOT="${ANTISMASH_ROOT:-${RESULTS_ROOT}/antismash}"
BIGSCAPE_OUT="${BIGSCAPE_OUT:-${RESULTS_ROOT}/big_scape}"

###############################################################################
# Tunables
###############################################################################
THREADS="${THREADS:-6}"
FORCE="${FORCE:-0}"
ENGINE="${ENGINE:-}"
CLUSTERWEAVE_RUNTIME_MODE="${CLUSTERWEAVE_RUNTIME_MODE:-hpc-singularity}"
AUTO_PULL_BIGSCAPE_SIF="${AUTO_PULL_BIGSCAPE_SIF:-1}"
AUTO_DOWNLOAD_PFAM="${AUTO_DOWNLOAD_PFAM:-1}"
AUTO_DOWNLOAD_FASTTREE="${AUTO_DOWNLOAD_FASTTREE:-1}"
BIGSCAPE_USE_DOCKER_IMAGE="${BIGSCAPE_USE_DOCKER_IMAGE:-0}"
BIGSCAPE_DOCKER_IMAGE="${BIGSCAPE_DOCKER_IMAGE:-ghcr.io/medema-group/big-scape:2.0.0-beta.6}"
BIGSCAPE_DOCKER_DATA_VOLUME="${BIGSCAPE_DOCKER_DATA_VOLUME:-${DOCKER_DATA_VOLUME:-}}"
BIGSCAPE_DOCKER_PFAM_VOLUME="${BIGSCAPE_DOCKER_PFAM_VOLUME:-${DOCKER_PFAM_VOLUME:-}}"

BIGSCAPE_SOFTDIR="${BIGSCAPE_SOFTDIR:-${SOFTWARE_ROOT}/big_scape}"
BIGSCAPE_SIF_PATH="${BIGSCAPE_SIF_PATH:-${BIGSCAPE_SOFTDIR}/bigscape_2.0.0-beta.6.sif}"
BIGSCAPE_SIF_SOURCE="${BIGSCAPE_SIF_SOURCE:-docker://ghcr.io/medema-group/big-scape:2.0.0-beta.6}"
SIF_PATH="${SIF_PATH:-${BIGSCAPE_SIF_PATH}}"
SIF_SOURCE="${SIF_SOURCE:-${BIGSCAPE_SIF_SOURCE}}"

RES_DIR="${RES_DIR:-${BIGSCAPE_SOFTDIR}/resources}"
PFAM_DIR="${PFAM_DIR:-${RES_DIR}/pfam}"
PFAM_HMM="${PFAM_HMM:-${PFAM_DIR}/Pfam-A.hmm}"
PFAM_GZ="${PFAM_GZ:-${PFAM_DIR}/Pfam-A.hmm.gz}"
PFAM_URL="${PFAM_URL:-https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release/Pfam-A.hmm.gz}"

LOCAL_BIN="${LOCAL_BIN:-${BIGSCAPE_SOFTDIR}/bin}"
FASTTREE_HOST="${FASTTREE_HOST:-${LOCAL_BIN}/fasttree}"
FASTTREE_URL="${FASTTREE_URL:-https://github.com/morgannprice/fasttree/raw/main/FastTree}"

MIBIG_VERSION_DEFAULT="${MIBIG_VERSION_DEFAULT:-4.0}"
MIBIG_CACHE="${MIBIG_CACHE:-${RES_DIR}/mibig_cache}"
MIBIG_AUTO_DOWNLOAD="${MIBIG_AUTO_DOWNLOAD:-1}"
MIBIG_URL_BASE="${MIBIG_URL_BASE:-https://dl.secondarymetabolites.org/mibig}"
MIBIG_GBK_URL="${MIBIG_GBK_URL:-}"

WORK_ROOT="${WORK_ROOT:-/tmp/$(basename "${RESULTS_ROOT}")_work}"
STAGE_DIR="${STAGE_DIR:-${WORK_ROOT}/bigscape_stage_region_gbks}"

LOGDIR="${LOGDIR:-${RESULTS_ROOT}/logs}"
mkdir -p "${LOGDIR}"
LOGFILE="${LOGFILE:-${LOGDIR}/run_bigscape.$(date +%Y%m%d_%H%M%S).log}"

###############################################################################
# Helpers
###############################################################################
ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "[$(ts)] [INFO] $*" | tee -a "${LOGFILE}"; }
warn(){ echo "[$(ts)] [WARN] $*" | tee -a "${LOGFILE}" >&2; }
err(){ echo "[$(ts)] [ERROR] $*" | tee -a "${LOGFILE}" >&2; }
die(){ err "$*"; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }

###############################################################################
# MiBIG helpers
###############################################################################
mibig_cache_has_gbks() {
  local cache="$1"
  [[ -d "${cache}" ]] || return 1
  find "${cache}" -type f \( -name "*.gbk" -o -name "*.gb" \) -print -quit 2>/dev/null | grep -q .
}

mibig_archive_candidates() {
  local cache="$1"
  local ver="$2"
  printf '%s\n' \
    "${cache}/mibig_antismash_${ver}_gbk.tar.bz2" \
    "${cache}/mibig_gbk_${ver}.tar.gz" \
    "${cache}/mibig_gbk_${ver}.tar.bz2"
}

extract_mibig_archive() {
  local archive="$1"
  local cache="$2"

  [[ -s "${archive}" ]] || return 1
  mkdir -p "${cache}"

  case "${archive}" in
    *.tar.gz|*.tgz)
      tar -xzf "${archive}" -C "${cache}" 2>&1 | tee -a "${LOGFILE}" || return 1
      ;;
    *.tar.bz2|*.tbz2)
      tar -xjf "${archive}" -C "${cache}" 2>&1 | tee -a "${LOGFILE}" || return 1
      ;;
    *)
      return 1
      ;;
  esac
}

ensure_mibig_cache() {
  local cache="$1"
  local ver="$2"
  local archive=""
  local url=""

  mibig_cache_has_gbks "${cache}" && return 0
  mkdir -p "${cache}"

  while IFS= read -r candidate; do
    if [[ -s "${candidate}" ]]; then
      archive="${candidate}"
      break
    fi
  done < <(mibig_archive_candidates "${cache}" "${ver}")

  if [[ -n "${archive}" ]]; then
    log "MiBIG cache empty; extracting local archive ${archive}"
    extract_mibig_archive "${archive}" "${cache}" || die "Failed to extract MiBIG archive ${archive}"
    mibig_cache_has_gbks "${cache}" || die "MiBIG archive extracted but no GBKs were found in ${cache}"
    echo "${ver}" > "${cache}/.mibig_version" 2>/dev/null || true
    return 0
  fi

  [[ "${MIBIG_AUTO_DOWNLOAD}" == "1" ]] || return 1
  have curl || die "curl not found (needed to auto-download MiBIG GBKs)"
  have tar  || die "tar not found (needed to extract MiBIG GBKs)"

  if [[ -n "${MIBIG_GBK_URL}" ]]; then
    url="${MIBIG_GBK_URL}"
  else
    url="${MIBIG_URL_BASE}/mibig_gbk_${ver}.tar.gz"
  fi

  log "MiBIG cache empty; downloading archive from ${url}"
  archive="$(mktemp -t mibig_gbk_${ver}.XXXXXX.tar.gz)"
  curl -L --fail -o "${archive}" "${url}" 2>&1 | tee -a "${LOGFILE}" \
    || die "Failed to download MiBIG GBKs from ${url}"
  extract_mibig_archive "${archive}" "${cache}" || die "Failed to extract downloaded MiBIG archive"
  rm -f "${archive}" || true

  mibig_cache_has_gbks "${cache}" || die "MiBIG GBKs not detected after extraction into ${cache}"
  echo "${ver}" > "${cache}/.mibig_version" 2>/dev/null || true
  log "MiBIG GBKs ready under ${cache}"
}

###############################################################################
# Detect container engine
###############################################################################
if [[ -z "${ENGINE}" ]]; then
  if [[ "${BIGSCAPE_USE_DOCKER_IMAGE}" == "1" ]] && have docker; then ENGINE="docker"
  elif have singularity; then ENGINE="singularity"
  elif have apptainer; then ENGINE="apptainer"
  else die "singularity/apptainer not found in PATH"
  fi
fi

case "${ENGINE}" in
  singularity|apptainer|docker) ;;
  *) die "Unsupported ENGINE=${ENGINE}; use singularity, apptainer, or docker" ;;
esac
if [[ "${ENGINE}" == "docker" ]] && ! have docker; then
  die "ENGINE=docker requested but docker is not available in PATH"
fi

###############################################################################
# Preconditions
###############################################################################
log "ENGINE=${ENGINE}"
log "THREADS=${THREADS} FORCE=${FORCE}"
log "ANTISMASH_ROOT=${ANTISMASH_ROOT}"
log "BIGSCAPE_OUT=${BIGSCAPE_OUT}"
log "SIF_PATH=${SIF_PATH}"
log "BIGSCAPE_DOCKER_IMAGE=${BIGSCAPE_DOCKER_IMAGE}"
log "PFAM_HMM=${PFAM_HMM}"
log "MIBIG_CACHE=${MIBIG_CACHE}"
log "STAGE_DIR=${STAGE_DIR}"
log "LOGFILE=${LOGFILE}"

[[ -d "${ANTISMASH_ROOT}" ]] || die "ANTISMASH_ROOT not found: ${ANTISMASH_ROOT}"

if ! find "${ANTISMASH_ROOT}" -type f -name "*region*.gbk" -print -quit 2>/dev/null | grep -q .; then
  die "No *region*.gbk files found under ANTISMASH_ROOT=${ANTISMASH_ROOT}"
fi

if [[ "${FORCE}" != "1" ]] && [[ -d "${BIGSCAPE_OUT}" ]] && \
   find "${BIGSCAPE_OUT}" -maxdepth 3 -type f \( -name "*.gml" -o -name "*.tsv" -o -name "*Network*.html" -o -name "index.html" \) \
   -print -quit 2>/dev/null | grep -q .; then
  log "SKIP: BiG-SCAPE outputs already exist at ${BIGSCAPE_OUT} (set FORCE=1 to rerun)"
  exit 0
fi

mkdir -p "${BIGSCAPE_SOFTDIR}" "${PFAM_DIR}" "${MIBIG_CACHE}" "${BIGSCAPE_OUT}"

###############################################################################
# Ensure container image present
###############################################################################
if [[ "${ENGINE}" == "docker" ]]; then
  if docker image inspect "${BIGSCAPE_DOCKER_IMAGE}" >/dev/null 2>&1; then
    log "BiG-SCAPE Docker image already present: ${BIGSCAPE_DOCKER_IMAGE}"
  else
    [[ "${AUTO_PULL_BIGSCAPE_SIF}" == "1" ]] || die "BiG-SCAPE Docker image missing: ${BIGSCAPE_DOCKER_IMAGE}. Set AUTO_PULL_BIGSCAPE_SIF=1 to fetch it."
    log "Pulling BiG-SCAPE Docker image: ${BIGSCAPE_DOCKER_IMAGE}"
    docker pull "${BIGSCAPE_DOCKER_IMAGE}" 2>&1 | tee -a "${LOGFILE}" || die "Docker image pull failed"
  fi
elif [[ ! -s "${SIF_PATH}" ]]; then
  [[ "${AUTO_PULL_BIGSCAPE_SIF}" == "1" ]] || die "BiG-SCAPE SIF missing: ${SIF_PATH}. Set AUTO_PULL_BIGSCAPE_SIF=1 to fetch it."
  log "Pulling BiG-SCAPE container: ${SIF_SOURCE} -> ${SIF_PATH}"
  "${ENGINE}" pull "${SIF_PATH}" "${SIF_SOURCE}" 2>&1 | tee -a "${LOGFILE}" || die "Container pull failed"
else
  log "Container SIF already present: ${SIF_PATH}"
fi

###############################################################################
# Ensure Pfam present
###############################################################################
if [[ ! -s "${PFAM_HMM}" ]]; then
  [[ "${AUTO_DOWNLOAD_PFAM}" == "1" ]] || die "Pfam-A.hmm missing: ${PFAM_HMM}. Set AUTO_DOWNLOAD_PFAM=1 to fetch it."
  log "Pfam-A.hmm missing; downloading to ${PFAM_GZ}"
  have curl || die "curl not found (needed to download Pfam)"
  curl -L --fail -o "${PFAM_GZ}" "${PFAM_URL}" 2>&1 | tee -a "${LOGFILE}" || die "Failed to download Pfam-A.hmm.gz"
  gunzip -f "${PFAM_GZ}" 2>&1 | tee -a "${LOGFILE}" || die "Failed to gunzip Pfam-A.hmm.gz"
  [[ -s "${PFAM_HMM}" ]] || die "Pfam-A.hmm still missing after download"
else
  log "Pfam already present: ${PFAM_HMM}"
fi

###############################################################################
# MiBIG: prefer the shared cache; extract/download only if genuinely missing
###############################################################################
MIBIG_VERSION=""
if ! mibig_cache_has_gbks "${MIBIG_CACHE}"; then
  ensure_mibig_cache "${MIBIG_CACHE}" "${MIBIG_VERSION_DEFAULT}" || true
fi

if mibig_cache_has_gbks "${MIBIG_CACHE}"; then
  MIBIG_VERSION="${MIBIG_VERSION_DEFAULT}"
  log "MiBIG cache detected; enabling --mibig-version ${MIBIG_VERSION}"
else
  warn "MiBIG cache is empty at ${MIBIG_CACHE}; running without MiBIG integration"
fi

###############################################################################
# Ensure FastTree exists
###############################################################################
mkdir -p "${LOCAL_BIN}"
if [[ ! -x "${FASTTREE_HOST}" ]]; then
  [[ "${AUTO_DOWNLOAD_FASTTREE}" == "1" ]] || die "FastTree missing: ${FASTTREE_HOST}. Set AUTO_DOWNLOAD_FASTTREE=1 to fetch it."
  log "FastTree missing at ${FASTTREE_HOST}; downloading Linux executable"
  have curl || die "curl not found (needed to download FastTree)"
  curl -L --fail -o "${FASTTREE_HOST}" "${FASTTREE_URL}" 2>&1 | tee -a "${LOGFILE}" || die "Failed to download FastTree"
  chmod +x "${FASTTREE_HOST}" || die "Failed to chmod +x ${FASTTREE_HOST}"
else
  log "FastTree already present: ${FASTTREE_HOST}"
fi

###############################################################################
# Container exec wrapper
###############################################################################
BIND_ARGS=(
  --bind "${PROJECT_DIR}:${PROJECT_DIR}"
  --bind "${RESULTS_ROOT}:${RESULTS_ROOT}"
  --bind "${BIGSCAPE_SOFTDIR}:${BIGSCAPE_SOFTDIR}"
  --bind "${PFAM_DIR}:${PFAM_DIR}"
  --bind "${LOCAL_BIN}:${LOCAL_BIN}"
  --bind "${BIGSCAPE_OUT}:${BIGSCAPE_OUT}"
  --bind "${WORK_ROOT}:${WORK_ROOT}"
)

if [[ -n "${MIBIG_VERSION}" ]]; then
  BIND_ARGS+=( --bind "${MIBIG_CACHE}:/home/mambauser/BiG-SCAPE/big_scape/MIBiG" )
  BIND_ARGS+=( --bind "${MIBIG_CACHE}:/home/mambauser/BiG-SCAPE/MIBiG" )
fi

docker_run_args() {
  local -a args=(--rm -i --user 0:0 --entrypoint "")
  if [[ -n "${CLUSTERWEAVE_JOB_ID:-}" ]]; then
    args+=(--label "clusterweave.job_id=${CLUSTERWEAVE_JOB_ID}" --label "clusterweave.project=${PROJECT_NAME:-}")
  fi
  if [[ -n "${BIGSCAPE_DOCKER_DATA_VOLUME}" ]]; then
    args+=(-v "${BIGSCAPE_DOCKER_DATA_VOLUME}:/data")
  else
    args+=(-v "${PROJECT_DIR}:${PROJECT_DIR}" -v "${RESULTS_ROOT}:${RESULTS_ROOT}" -v "${BIGSCAPE_SOFTDIR}:${BIGSCAPE_SOFTDIR}" -v "${LOCAL_BIN}:${LOCAL_BIN}" -v "${BIGSCAPE_OUT}:${BIGSCAPE_OUT}" -v "${STAGE_DIR}:${STAGE_DIR}")
  fi
  if [[ -n "${BIGSCAPE_DOCKER_PFAM_VOLUME}" ]]; then
    args+=(-v "${BIGSCAPE_DOCKER_PFAM_VOLUME}:${PFAM_DIR}")
  elif [[ -z "${BIGSCAPE_DOCKER_DATA_VOLUME}" ]]; then
    args+=(-v "${PFAM_DIR}:${PFAM_DIR}")
  fi
  printf '%s\0' "${args[@]}"
}

cexec() {
  if [[ "${ENGINE}" == "docker" ]]; then
    local -a args=()
    mapfile -d '' -t args < <(docker_run_args)
    docker run "${args[@]}" "${BIGSCAPE_DOCKER_IMAGE}" "$@"
  else
    "${ENGINE}" exec "${BIND_ARGS[@]}" "${SIF_PATH}" "$@"
  fi
}

###############################################################################
# Sanity check container
###############################################################################
log "Sanity check: bigscape help (container)"
cexec bash -lc '/opt/conda/bin/python /home/mambauser/BiG-SCAPE/bigscape.py --help' \
  2>&1 | tee -a "${LOGFILE}" || die "Container bigscape.py not runnable"

###############################################################################
# Stage antiSMASH region GBKs to a flat directory
###############################################################################
log "Staging region GBKs -> ${STAGE_DIR}"
rm -rf "${STAGE_DIR}" 2>/dev/null || true
mkdir -p "${STAGE_DIR}"

collisions=0
while IFS= read -r -d "" f; do
  parent="$(basename "$(dirname "$f")")"
  base="$(basename "$f")"
  label="$parent"
  out="${STAGE_DIR}/${parent}__${base}"

  if [[ -e "${out}" ]]; then
    collisions=$((collisions + 1))
    continue
  fi

  cp -f "$f" "${out}"

  awk -v LABEL="${label}" '
    $1=="SOURCE"   { print "SOURCE      " LABEL; next }
    $1=="ORGANISM" { print "  ORGANISM  " LABEL; next }
    { print }
  ' "${out}" > "${out}.tmp" && mv -f "${out}.tmp" "${out}"
done < <(find "${ANTISMASH_ROOT}" -type f -name "*region*.gbk" -print0)

region_n="$(find "${STAGE_DIR}" -maxdepth 1 -type f -name "*.gbk" | wc -l | tr -d " ")"
log "Staged region GBKs: ${region_n} (collisions=${collisions})"
[[ "${region_n}" -gt 0 ]] || die "No region GBKs staged; cannot run BiG-SCAPE"

###############################################################################
# Run BiG-SCAPE
###############################################################################
INPUT_MODE="flat"
if [[ -n "${MIBIG_VERSION}" ]]; then
  INPUT_MODE="recursive"
fi

RUN_CMD=(
  /opt/conda/bin/python /home/mambauser/BiG-SCAPE/bigscape.py cluster
  -i "${STAGE_DIR}"
  -o "${BIGSCAPE_OUT}"
  --input-mode "${INPUT_MODE}"
  --include-gbk "*"
  --pfam-path "${PFAM_HMM}"
  --cores "${THREADS}"
  --include-singletons
  --mix
)

if [[ -n "${MIBIG_VERSION}" ]]; then
  RUN_CMD+=( --mibig-version "${MIBIG_VERSION}" )
fi

mkdir -p "${BIGSCAPE_OUT}"

log "Running BiG-SCAPE (inside container) with FastTree on PATH"
set +e
cexec env "PATH=${LOCAL_BIN}:$PATH" "${RUN_CMD[@]}" 2>&1 | tee -a "${LOGFILE}"
rc=${PIPESTATUS[0]}
set -e

[[ "${rc}" -eq 0 ]] || die "BiG-SCAPE failed (rc=${rc})"
log "BiG-SCAPE complete. Output: ${BIGSCAPE_OUT}"
