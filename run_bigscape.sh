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
BIGSCAPE_DOCKER_MEMORY="${BIGSCAPE_DOCKER_MEMORY:-${CLUSTERWEAVE_TOOL_DOCKER_MEMORY:-}}"
BIGSCAPE_DOCKER_PIDS_LIMIT="${BIGSCAPE_DOCKER_PIDS_LIMIT:-${CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT:-}}"
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
FASTTREE_URL="${FASTTREE_URL:-https://raw.githubusercontent.com/morgannprice/fasttree/29c5e62fbcd93230ee325f9c6a17b81f00e3c72a/FastTree}"
FASTTREE_SHA256="${FASTTREE_SHA256:-55a9d997813aae2208bd4c2081bfa690e0ecdba2d6c491805d8689415c43e38e}"
FASTTREE_VERSION="${FASTTREE_VERSION:-2.2.0}"

MIBIG_VERSION_DEFAULT="${MIBIG_VERSION_DEFAULT:-4.0}"
MIBIG_CACHE="${MIBIG_CACHE:-${RES_DIR}/mibig_cache}"
MIBIG_AUTO_DOWNLOAD="${MIBIG_AUTO_DOWNLOAD:-1}"
MIBIG_URL_BASE="${MIBIG_URL_BASE:-https://dl.secondarymetabolites.org/mibig}"
MIBIG_GBK_URL="${MIBIG_GBK_URL:-}"

WORK_ROOT="${WORK_ROOT:-/tmp/$(basename "${RESULTS_ROOT}")_work}"
STAGE_DIR="${STAGE_DIR:-${WORK_ROOT}/bigscape_stage_region_gbks}"
GENOME_TAXON_MANIFEST="${GENOME_TAXON_MANIFEST:-${RESULTS_ROOT}/summary_tables/genome_taxon_manifest.tsv}"
BIGSCAPE_REGION_CROSSWALK="${BIGSCAPE_REGION_CROSSWALK:-${RESULTS_ROOT}/summary_tables/bigscape_region_crosswalk.tsv}"

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

file_sha256() {
  local path="$1"
  if have sha256sum; then
    sha256sum -- "${path}" | awk '{print tolower($1)}'
  elif have shasum; then
    shasum -a 256 -- "${path}" | awk '{print tolower($1)}'
  else
    return 127
  fi
}

verify_fasttree_checksum() {
  local path="$1"
  local actual
  [[ "${FASTTREE_SHA256}" =~ ^[0-9a-fA-F]{64}$ ]] || die "FASTTREE_SHA256 must be exactly 64 hexadecimal characters"
  actual="$(file_sha256 "${path}")" || die "sha256sum or shasum is required to verify FastTree"
  [[ "${actual}" == "${FASTTREE_SHA256,,}" ]] || die "FastTree checksum mismatch for ${path}"
}

normalize_positive_integer() {
  local name="$1"
  local fallback="$2"
  local value="${!name:-}"
  if [[ ! "${value}" =~ ^[0-9]+$ ]] || (( 10#${value} < 1 )); then
    warn "${name}=${value:-unset} is not a positive integer; using ${fallback}"
    printf -v "${name}" '%s' "${fallback}"
  fi
}

normalize_positive_integer THREADS 1
bounded_docker_cpu_limit() {
  local requested="${1:-}"
  local ceiling="${2:-}"
  if [[ "${ceiling}" =~ ^[0-9]+([.][0-9]+)?$ && "${ceiling}" != "0" && "${ceiling}" != "0.0" ]]; then
    awk -v requested="${requested}" -v ceiling="${ceiling}" \
      'BEGIN { print (requested + 0 <= ceiling + 0) ? requested : ceiling }'
  else
    printf '%s\n' "${requested}"
  fi
}
BIGSCAPE_DOCKER_CPUS="$(bounded_docker_cpu_limit "${THREADS}" "${CLUSTERWEAVE_TOOL_DOCKER_CPUS:-}")"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

# Only assembled, per-genome region files are valid BiG-SCAPE inputs. Raw
# antiSMASH shard outputs live below WORK_ROOT, and any future browseable shard
# views below a genome result directory must not be discovered recursively.
find_antismash_genome_regions() {
  find "${ANTISMASH_ROOT}" \
    -mindepth 2 -maxdepth 2 -type f -name "*region*.gbk" "$@"
}

###############################################################################
# MiBIG helpers
###############################################################################
mibig_cache_has_gbks() {
  local cache="$1"
  local ver="${2:-${MIBIG_VERSION_DEFAULT}}"
  local version_dir="${cache}/mibig_antismash_${ver}_gbk"
  [[ -d "${version_dir}" ]] || return 1
  find "${version_dir}" -type f \( -name "*.gbk" -o -name "*.gb" \) -print -quit 2>/dev/null | grep -q .
}

normalize_mibig_version_dir() {
  local cache="$1"
  local ver="$2"
  local expected="${cache}/mibig_antismash_${ver}_gbk"
  local candidate=""
  local match=""
  local matches=0

  [[ -d "${expected}" ]] && return 0
  for candidate in "${cache}"/mibig_antismash_"${ver}"_gbk*; do
    [[ -d "${candidate}" ]] || continue
    match="${candidate}"
    matches=$((matches + 1))
  done
  [[ "${matches}" -eq 1 ]] || return 1
  mv "${match}" "${expected}"
}

mibig_archive_candidates() {
  local cache="$1"
  local ver="$2"
  local candidate=""
  for candidate in "${cache}"/mibig_antismash_"${ver}"_gbk*.tar.bz2; do
    [[ -e "${candidate}" ]] || continue
    printf '%s\n' "${candidate}"
  done
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

  mkdir -p "${cache}"
  normalize_mibig_version_dir "${cache}" "${ver}" || true
  mibig_cache_has_gbks "${cache}" "${ver}" && return 0

  while IFS= read -r candidate; do
    if [[ -s "${candidate}" ]]; then
      archive="${candidate}"
      break
    fi
  done < <(mibig_archive_candidates "${cache}" "${ver}")

  if [[ -n "${archive}" ]]; then
    log "MiBIG cache empty; extracting local archive ${archive}"
    extract_mibig_archive "${archive}" "${cache}" || die "Failed to extract MiBIG archive ${archive}"
    normalize_mibig_version_dir "${cache}" "${ver}" || true
    mibig_cache_has_gbks "${cache}" "${ver}" || die "BiG-SCAPE-ready MiBIG archive extracted but no GBKs were found under ${cache}/mibig_antismash_${ver}_gbk"
    echo "${ver}" > "${cache}/.mibig_version" 2>/dev/null || true
    return 0
  fi

  [[ "${MIBIG_AUTO_DOWNLOAD}" == "1" ]] || return 1
  have curl || die "curl not found (needed to auto-download MiBIG GBKs)"
  have tar  || die "tar not found (needed to extract MiBIG GBKs)"

  if [[ -n "${MIBIG_GBK_URL}" ]]; then
    url="${MIBIG_GBK_URL}"
  elif [[ "${ver}" == "4.0" ]]; then
    url="${MIBIG_URL_BASE}/mibig_antismash_${ver}_gbk_as8b1.tar.bz2"
  else
    url="${MIBIG_URL_BASE}/mibig_antismash_${ver}_gbk.tar.bz2"
  fi

  log "BiG-SCAPE-ready MiBIG cache empty; downloading archive from ${url}"
  archive="$(mktemp -t mibig_antismash_${ver}.XXXXXX.tar.bz2)"
  curl -L --fail -o "${archive}" "${url}" 2>&1 | tee -a "${LOGFILE}" \
    || die "Failed to download MiBIG GBKs from ${url}"
  extract_mibig_archive "${archive}" "${cache}" || die "Failed to extract downloaded MiBIG archive"
  rm -f "${archive}" || true

  normalize_mibig_version_dir "${cache}" "${ver}" || true
  mibig_cache_has_gbks "${cache}" "${ver}" || die "BiG-SCAPE-ready MiBIG GBKs not detected after extraction into ${cache}/mibig_antismash_${ver}_gbk"
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
log "THREADS=${THREADS} BIGSCAPE_DOCKER_CPUS=${BIGSCAPE_DOCKER_CPUS} FORCE=${FORCE}"
log "ANTISMASH_ROOT=${ANTISMASH_ROOT}"
log "BIGSCAPE_OUT=${BIGSCAPE_OUT}"
log "SIF_PATH=${SIF_PATH}"
log "BIGSCAPE_DOCKER_IMAGE=${BIGSCAPE_DOCKER_IMAGE}"
log "PFAM_HMM=${PFAM_HMM}"
log "MIBIG_CACHE=${MIBIG_CACHE}"
log "STAGE_DIR=${STAGE_DIR}"
log "LOGFILE=${LOGFILE}"

[[ -d "${ANTISMASH_ROOT}" ]] || die "ANTISMASH_ROOT not found: ${ANTISMASH_ROOT}"

if ! find_antismash_genome_regions -print -quit 2>/dev/null | grep -q .; then
  # A valid antiSMASH run can contain zero regions.  Preserve that biological
  # result as an explicit empty BiG-SCAPE universe instead of turning the
  # whole bacterial workflow into a technical failure or retaining stale
  # clusters from an earlier rerun.
  rm -rf -- "${BIGSCAPE_OUT}" "${STAGE_DIR}" 2>/dev/null || true
  mkdir -p "${BIGSCAPE_OUT}/output_files" "${STAGE_DIR}" "$(dirname "${BIGSCAPE_REGION_CROSSWALK}")"
  printf 'staged_gbk\tgenome_id\ttaxon_group\tprediction_method\tsource_region_key\n' > "${BIGSCAPE_REGION_CROSSWALK}"
  log "No assembled region GBKs were detected; wrote a valid empty BiG-SCAPE result."
  printf 'BIGSCAPE_RESULT status=insufficient_data regions=0 families=0 message="No antiSMASH regions were detected"\n' | tee -a "${LOGFILE}"
  exit 0
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
if ! mibig_cache_has_gbks "${MIBIG_CACHE}" "${MIBIG_VERSION_DEFAULT}"; then
  ensure_mibig_cache "${MIBIG_CACHE}" "${MIBIG_VERSION_DEFAULT}" || true
fi

if mibig_cache_has_gbks "${MIBIG_CACHE}" "${MIBIG_VERSION_DEFAULT}"; then
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
  log "FastTree missing at ${FASTTREE_HOST}; downloading pinned v${FASTTREE_VERSION} Linux executable"
  have curl || die "curl not found (needed to download FastTree)"
  fasttree_download_tmp="$(mktemp "${FASTTREE_HOST}.download.XXXXXX")" || die "Failed to create a temporary FastTree download"
  trap 'rm -f -- "${fasttree_download_tmp}"' EXIT
  curl -L --fail -o "${fasttree_download_tmp}" "${FASTTREE_URL}" 2>&1 | tee -a "${LOGFILE}" || die "Failed to download FastTree"
  verify_fasttree_checksum "${fasttree_download_tmp}"
  chmod +x "${fasttree_download_tmp}" || die "Failed to chmod +x downloaded FastTree"
  mv -f -- "${fasttree_download_tmp}" "${FASTTREE_HOST}" || die "Failed to install FastTree"
  trap - EXIT
else
  log "FastTree already present: ${FASTTREE_HOST}"
fi
verify_fasttree_checksum "${FASTTREE_HOST}"

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
  local -a args=(
    --rm -i --user 0:0 --entrypoint ""
    --cpus "${BIGSCAPE_DOCKER_CPUS}"
    -e OMP_NUM_THREADS=1
    -e OPENBLAS_NUM_THREADS=1
    -e MKL_NUM_THREADS=1
    -e NUMEXPR_NUM_THREADS=1
  )
  if [[ -n "${BIGSCAPE_DOCKER_MEMORY}" ]]; then
    args+=(--memory "${BIGSCAPE_DOCKER_MEMORY}")
  fi
  if [[ -n "${BIGSCAPE_DOCKER_PIDS_LIMIT}" ]]; then
    args+=(--pids-limit "${BIGSCAPE_DOCKER_PIDS_LIMIT}")
  fi
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
  if [[ -n "${MIBIG_VERSION}" ]]; then
    if [[ -n "${BIGSCAPE_DOCKER_DATA_VOLUME}" && "${MIBIG_CACHE}" == /data/* ]]; then
      args+=(
        --mount
        "type=volume,src=${BIGSCAPE_DOCKER_DATA_VOLUME},dst=/home/mambauser/BiG-SCAPE/big_scape/MIBiG,volume-subpath=${MIBIG_CACHE#/data/}"
      )
    else
      args+=(-v "${MIBIG_CACHE}:/home/mambauser/BiG-SCAPE/big_scape/MIBiG")
    fi
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
mkdir -p "$(dirname "${BIGSCAPE_REGION_CROSSWALK}")"
printf 'staged_gbk\tgenome_id\ttaxon_group\tprediction_method\tsource_region_key\n' > "${BIGSCAPE_REGION_CROSSWALK}"

manifest_route_fields() {
  local genome_id="$1"
  if [[ -s "${GENOME_TAXON_MANIFEST}" ]]; then
    awk -F '\t' -v target="${genome_id}" '
      NR == 1 {
        for (i = 1; i <= NF; i++) h[$i] = i
        next
      }
      $(h["genome_id"]) == target {
        taxon = (h["taxon_group"] ? $(h["taxon_group"]) : "fungi")
        prediction = (h["prediction_method"] ? $(h["prediction_method"]) : "")
        print (taxon == "" ? "fungi" : taxon) "\t" prediction
        exit
      }
    ' "${GENOME_TAXON_MANIFEST}"
    return 0
  fi
  printf 'fungi\t\n'
}

manifest_taxon_source() {
  local genome_id="$1"
  if [[ -s "${GENOME_TAXON_MANIFEST}" ]]; then
    awk -F '\t' -v target="${genome_id}" '
      NR == 1 {
        for (i = 1; i <= NF; i++) h[$i] = i
        next
      }
      $(h["genome_id"]) == target {
        print (h["taxon_source"] ? $(h["taxon_source"]) : "")
        exit
      }
    ' "${GENOME_TAXON_MANIFEST}"
  fi
}

while IFS= read -r -d "" f; do
  relative="${f#"${ANTISMASH_ROOT%/}/"}"
  genome="${relative%%/*}"
  base="$(basename "$f")"
  # New IDs are taxon-neutral. Hide the historical NCBI-only prefix only when
  # provenance proves that it was synthesized by an older ClusterWeave run.
  label="${genome}"
  taxon_source="$(manifest_taxon_source "${genome}")"
  if [[ "${taxon_source,,}" =~ ^(ncbi|ncbi_taxonomy)$ && "${genome,,}" == bacteria_* ]]; then
    label="${genome#bacteria_}"
  fi
  label="${label//_/ }"
  out="${STAGE_DIR}/${genome}__${base}"
  route_fields="$(manifest_route_fields "${genome}")"
  [[ -n "${route_fields}" ]] || route_fields=$'fungi\t'

  if [[ -e "${out}" ]]; then
    die "Region staging name collision for ${f}: ${out}"
  fi

  cp -f "$f" "${out}"

  awk -v LABEL="${label}" '
    $1=="SOURCE"   { print "SOURCE      " LABEL; next }
    $1=="ORGANISM" { print "  ORGANISM  " LABEL; next }
    { print }
  ' "${out}" > "${out}.tmp" && mv -f "${out}.tmp" "${out}"
  printf '%s\t%s\t%s\t%s\n' "$(basename "${out}")" "${genome}" "${route_fields}" "${genome}/${base}" >> "${BIGSCAPE_REGION_CROSSWALK}"
done < <(find_antismash_genome_regions -print0)

region_n="$(find "${STAGE_DIR}" -maxdepth 1 -type f -name "*.gbk" | wc -l | tr -d " ")"
log "Staged region GBKs: ${region_n} (assembled per-genome roots only)"
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
