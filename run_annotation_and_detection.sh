#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

###############################################################################
# Env-backed project paths
###############################################################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
PROJECTS_ROOT="${PROJECTS_ROOT:-${PROJECT_DIR}}"
DATA_ROOT="${DATA_ROOT:-${PROJECTS_ROOT}/data}"
SOFTWARE_ROOT="${SOFTWARE_ROOT:-${PROJECTS_ROOT}/software}"
GENOMES_ROOT="${GENOMES_ROOT:-${DATA_ROOT}/genomes/fungi}"
RESULTS_BASE="${RESULTS_BASE:-${DATA_ROOT}/results}"

GENOME_ROOT="${GENOME_ROOT:-${GENOMES_ROOT}/${PROJECT_NAME}}"
FUNGI_GENOME_ROOT="${FUNGI_GENOME_ROOT:-${GENOME_ROOT}}"
BACTERIA_GENOME_ROOT="${BACTERIA_GENOME_ROOT:-${DATA_ROOT}/genomes/bacteria/${PROJECT_NAME}}"
RESULTS_ROOT="${RESULTS_ROOT:-${RESULTS_BASE}/${PROJECT_NAME}}"
GENOME_TAXON_MANIFEST="${GENOME_TAXON_MANIFEST:-${RESULTS_ROOT}/summary_tables/genome_taxon_manifest.tsv}"

PLANTS_GENOME_ROOT="${PLANTS_GENOME_ROOT:-${DATA_ROOT}/genomes/plants/${PROJECT_NAME}}"
PLANTISMASH_SIF="${PLANTISMASH_SIF:-${SOFTWARE_ROOT}/plantismash/plant.sif}"
PLANTISMASH_ENGINE="${PLANTISMASH_ENGINE:-apptainer}"

ANTISMASH_SIF="${ANTISMASH_SIF:-${SOFTWARE_ROOT}/antismash/antismash_standalone.sif}"
FUNBGCEX_SIF="${FUNBGCEX_SIF:-${SOFTWARE_ROOT}/funbgcex/funbgcex_bundle.sif}"
BRAKER_SIF="${BRAKER_SIF:-${SOFTWARE_ROOT}/braker/braker3.sif}"
FUNANNOTATE_SIF="${FUNANNOTATE_SIF:-${SOFTWARE_ROOT}/funannotate/funannotate_v1.8.17.sif}"
ANTISMASH_DB_DIR="${ANTISMASH_DB_DIR:-${SOFTWARE_ROOT}/antismash/databases}"


###############################################################################
# Tunables / knobs
###############################################################################
CPUS_REQUEST_EXPLICIT=0
if [[ -n "${CPUS+x}" || -n "${THREADS+x}" ]]; then
  CPUS_REQUEST_EXPLICIT=1
fi
THREADS="${THREADS:-6}"     # recorded; alias for CPUS unless CPUS is explicit
CPUS="${CPUS:-${THREADS}}"  # total CPU budget for this job
WORKERS="${WORKERS:-2}"     # funbgcex --workers
GENOME_PARALLELISM="${GENOME_PARALLELISM:-${ANNOTATION_GENOME_PARALLELISM:-1}}"  # concurrent genomes in annotation stage
ANTISMASH_RECORD_PARALLELISM="${ANTISMASH_RECORD_PARALLELISM:-1}"  # concurrent antiSMASH records within one genome
ANTISMASH_SHARD_CPUS="${ANTISMASH_SHARD_CPUS:-}"  # per-record antiSMASH cpus; derived after CLI parsing when unset
ANTISMASH_LEGACY_CPUS="${ANTISMASH_LEGACY_CPUS:-}"  # single-run antiSMASH cpus; defaults to CPUS
ANTISMASH_RETAIN_SHARD_WORK="${ANTISMASH_RETAIN_SHARD_WORK:-0}"  # 1 retains complete raw antiSMASH shard directories
ANTISMASH_SHARD_COMPACTOR="${ANTISMASH_SHARD_COMPACTOR:-${SCRIPT_DIR}/bin/compact_antismash_shard.py}"
ANTISMASH_WEB_RESULTS_PREPARER="${ANTISMASH_WEB_RESULTS_PREPARER:-${SCRIPT_DIR}/bin/prepare_antismash_web_results.py}"
ANTISMASH_INPUT_PREPARER="${ANTISMASH_INPUT_PREPARER:-${SCRIPT_DIR}/bin/prepare_antismash_input.py}"
ANNOTATION_GENBANK_HELPER="${ANNOTATION_GENBANK_HELPER:-${SCRIPT_DIR}/bin/annotation_genbank.py}"
ANNOTATION_RUNTIME_HELPER="${ANNOTATION_RUNTIME_HELPER:-${SCRIPT_DIR}/bin/annotation_runtime.py}"
BACTERIAL_GENBANK_SANITIZER="${BACTERIAL_GENBANK_SANITIZER:-${SCRIPT_DIR}/bin/sanitize_bacterial_genbank.py}"
ANTISMASH_MIN_RECORD_BP="${ANTISMASH_MIN_RECORD_BP:-1000}"
ANTISMASH_MAX_RECORD_BP="${ANTISMASH_MAX_RECORD_BP:-50000000}"
FORCE="${FORCE:-0}"         # FORCE=1 clears staged gbk + tool outputs per genome
ENGINE="${ENGINE:-}"        # singularity, apptainer, or docker
CLUSTERWEAVE_RUNTIME_MODE="${CLUSTERWEAVE_RUNTIME_MODE:-hpc-singularity}"
DOCKER_DATA_VOLUME="${DOCKER_DATA_VOLUME:-${CLUSTERWEAVE_DOCKER_DATA_VOLUME:-}}"
DOCKER_ANTISMASH_DB_VOLUME="${DOCKER_ANTISMASH_DB_VOLUME:-}"

# Resource planning remains manual/conservative unless explicitly enabled. Auto
# planning is local/HPC opt-in and freezes one bounded plan after genome discovery.
PIPELINE_RESOURCE_MODE="${PIPELINE_RESOURCE_MODE:-conservative}"
PIPELINE_MEMORY_BUDGET_MB="${PIPELINE_MEMORY_BUDGET_MB:-}"
PIPELINE_AUTO_MAX_CPUS="${PIPELINE_AUTO_MAX_CPUS:-32}"
PIPELINE_AUTO_MAX_GENOME_PARALLELISM="${PIPELINE_AUTO_MAX_GENOME_PARALLELISM:-4}"
PIPELINE_AUTO_MIN_CPUS_PER_GENOME="${PIPELINE_AUTO_MIN_CPUS_PER_GENOME:-2}"
PIPELINE_AUTO_MEMORY_PERCENT="${PIPELINE_AUTO_MEMORY_PERCENT:-70}"
PIPELINE_AUTO_MEMORY_PER_GENOME_MB="${PIPELINE_AUTO_MEMORY_PER_GENOME_MB:-8192}"
PIPELINE_AUTO_MAX_ANNO_CPUS="${PIPELINE_AUTO_MAX_ANNO_CPUS:-8}"
PIPELINE_AUTO_MAX_FUNBGCEX_WORKERS="${PIPELINE_AUTO_MAX_FUNBGCEX_WORKERS:-2}"
PIPELINE_AUTO_MAX_ANTISMASH_RECORD_PARALLELISM="${PIPELINE_AUTO_MAX_ANTISMASH_RECORD_PARALLELISM:-3}"

# Optional hard limits for each Docker tool child. Empty values leave Docker's
# limits unchanged; pipeline/native tool arguments remain the primary CPU caps.
CLUSTERWEAVE_TOOL_DOCKER_CPUS="${CLUSTERWEAVE_TOOL_DOCKER_CPUS:-}"
CLUSTERWEAVE_TOOL_DOCKER_MEMORY="${CLUSTERWEAVE_TOOL_DOCKER_MEMORY:-}"
CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT="${CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT:-}"
CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS="${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS:-1}"

# Annotation knobs
ANNO_CPUS="${ANNO_CPUS:-6}"
ANNOTATION_FALLBACK_ORDER="${ANNOTATION_FALLBACK_ORDER:-funannotate}"
BRAKER3_ENABLED="${BRAKER3_ENABLED:-0}"
BRAKER_SPECIES_PREFIX="${BRAKER_SPECIES_PREFIX:-braker3}"
FUNANNOTATE_ORGANISM_NAME="${FUNANNOTATE_ORGANISM_NAME:-auto}"
FUNANNOTATE_BUSCO_DB="${FUNANNOTATE_BUSCO_DB:-auto}"
FUNANNOTATE_BUSCO_SEED_SPECIES="${FUNANNOTATE_BUSCO_SEED_SPECIES:-}"
ANNOTATION_FALLBACK_FAILURE_REASON=""
ANNOTATION_FALLBACK_FAILURE_DETAIL=""
FUNANNOTATE_LAST_FAILURE_STATUS=""
FUNANNOTATE_LAST_FAILURE_DETAIL=""
BRAKER_BAM="${BRAKER_BAM:-}"
BRAKER_PROT_SEQ="${BRAKER_PROT_SEQ:-}"
AUTO_PULL_IMAGES="${AUTO_PULL_IMAGES:-always}"   # ask|always|never
ANTISMASH_IMAGE_URI="${ANTISMASH_IMAGE_URI:-docker://antismash/standalone:8.0.4}"
ANTISMASH_DOCKER_IMAGE="${ANTISMASH_DOCKER_IMAGE:-antismash/standalone:8.0.4}"
FUNBGCEX_IMAGE_URI="${FUNBGCEX_IMAGE_URI:-}"
AUTO_BUILD_FUNBGCEX_SIF="${AUTO_BUILD_FUNBGCEX_SIF:-1}"
FUNBGCEX_USE_DOCKER_IMAGE="${FUNBGCEX_USE_DOCKER_IMAGE:-0}"
FUNBGCEX_DOCKER_IMAGE="${FUNBGCEX_DOCKER_IMAGE:-clusterweave-funbgcex:latest}"
AUTO_BUILD_FUNBGCEX_DOCKER="${AUTO_BUILD_FUNBGCEX_DOCKER:-1}"
BRAKER_IMAGE_URI="${BRAKER_IMAGE_URI:-docker://teambraker/braker3:v3.0.7.6@sha256:5f8b3c508a9fe1bbc2e9a74dcc013eeed82f91dd5945adca7823514d9c8aecf8}"
FUNANNOTATE_BASE_IMAGE_URI="${FUNANNOTATE_BASE_IMAGE_URI:-docker://nextgenusfs/funannotate:v1.8.17}"
FUNANNOTATE_IMAGE_URI="${FUNANNOTATE_IMAGE_URI:-docker://clusterweave-funannotate:v1.8.17-busco}"
AUTO_BUILD_FUNANNOTATE_SIF="${AUTO_BUILD_FUNANNOTATE_SIF:-1}"
AUTO_BUILD_FUNANNOTATE_DOCKER="${AUTO_BUILD_FUNANNOTATE_DOCKER:-1}"
FUNANNOTATE_BUILD_SCRIPT="${FUNANNOTATE_BUILD_SCRIPT:-${PROJECT_DIR}/software/funannotate/build_funannotate_sif.sh}"
FUNBGCEX_BOOTSTRAP="${FUNBGCEX_BOOTSTRAP:-0}"
FUNBGCEX_VERSION="${FUNBGCEX_VERSION:-1.0.1}"
FUNBGCEX_VENV_DIR="${FUNBGCEX_VENV_DIR:-${SOFTWARE_ROOT}/funbgcex/venv}"
FUNBGCEX_PIP_CACHE="${FUNBGCEX_PIP_CACHE:-${SOFTWARE_ROOT}/funbgcex/pip_cache}"
FUNBGCEX_DEF="${FUNBGCEX_DEF:-${PROJECT_DIR}/software/funbgcex/Singularity.def}"
FUNBGCEX_DOCKERFILE="${FUNBGCEX_DOCKERFILE:-${PROJECT_DIR}/software/funbgcex/Dockerfile}"
FUNBGCEX_BUILD_SCRIPT="${FUNBGCEX_BUILD_SCRIPT:-${PROJECT_DIR}/software/funbgcex/build_funbgcex_sif.sh}"
TOOL_ACTIVITY_HEARTBEAT_SECONDS="${TOOL_ACTIVITY_HEARTBEAT_SECONDS:-45}"
TOOL_ACTIVITY_RAW_LIMIT="${TOOL_ACTIVITY_RAW_LIMIT:-1200}"
FUNANNOTATE_RETRY_WITHOUT_PROTEIN_EVIDENCE="${FUNANNOTATE_RETRY_WITHOUT_PROTEIN_EVIDENCE:-1}"
FUNANNOTATE_MIN_TRAINING_MODELS_FALLBACK="${FUNANNOTATE_MIN_TRAINING_MODELS_FALLBACK:-150}"

FUNBGCEX_RUNTIME="unresolved"
FUNBGCEX_CMD=""
FUNBGCEX_PYTHON_CMD=""

export CUDA_VISIBLE_DEVICES=""

###############################################################################
# Container engine + bind handling (ARRAY-BASED; REQUIRED for paths w/ spaces)
###############################################################################
have() { command -v "$1" >/dev/null 2>&1; }

if [[ -z "${ENGINE}" ]]; then
  if [[ "${FUNBGCEX_USE_DOCKER_IMAGE}" == "1" ]] && have docker; then ENGINE="docker"
  elif have singularity; then ENGINE="singularity"
  elif have apptainer; then ENGINE="apptainer"
  else
    echo "ERROR: singularity/apptainer not found in PATH" >&2
    exit 1
  fi
fi

case "${ENGINE}" in
  singularity|apptainer|docker) ;;
  *) echo "ERROR: unsupported ENGINE=${ENGINE}; use singularity, apptainer, or docker" >&2; exit 1 ;;
esac

if [[ "${ENGINE}" == "docker" ]] && ! have docker; then
  echo "ERROR: ENGINE=docker requested but docker is not available in PATH" >&2
  exit 1
fi

# Binds as an array (paths contain spaces; do NOT store binds in a single string)
BIND_ARGS=(
  --bind "${PROJECT_DIR}:${PROJECT_DIR}"
  --bind "${FUNGI_GENOME_ROOT}:${FUNGI_GENOME_ROOT}"
  --bind "${BACTERIA_GENOME_ROOT}:${BACTERIA_GENOME_ROOT}"
  --bind "${RESULTS_ROOT}:${RESULTS_ROOT}"
)

# Helper: exec inside a Singularity/Apptainer container safely
sing_exec() {
  local image="$1"; shift
  local -a workdir_args=()
  if [[ -n "${CLUSTERWEAVE_CHILD_SIF_WORKDIR:-}" ]]; then
    workdir_args+=(--pwd "${CLUSTERWEAVE_CHILD_SIF_WORKDIR}")
  fi
  "${ENGINE}" exec "${workdir_args[@]}" "${BIND_ARGS[@]}" "${image}" "$@"
}

docker_image_from_uri() {
  local uri="$1"
  printf '%s\n' "${uri#docker://}"
}

bounded_docker_cpu_limit() {
  local requested="${1:-}"
  local ceiling="${2:-}"
  local numeric_re='^[0-9]+([.][0-9]+)?$'
  if [[ "${requested}" =~ ${numeric_re} && "${requested}" != "0" && "${requested}" != "0.0" ]]; then
    if [[ "${ceiling}" =~ ${numeric_re} && "${ceiling}" != "0" && "${ceiling}" != "0.0" ]]; then
      awk -v requested="${requested}" -v ceiling="${ceiling}" \
        'BEGIN { print (requested + 0 <= ceiling + 0) ? requested : ceiling }'
    else
      printf '%s\n' "${requested}"
    fi
  elif [[ "${ceiling}" =~ ${numeric_re} && "${ceiling}" != "0" && "${ceiling}" != "0.0" ]]; then
    printf '%s\n' "${ceiling}"
  fi
}

docker_run_args() {
  local -a args=(--rm -i --user 0:0 --entrypoint "")
  if [[ -n "${CLUSTERWEAVE_CHILD_DOCKER_WORKDIR:-}" ]]; then
    args+=(--workdir "${CLUSTERWEAVE_CHILD_DOCKER_WORKDIR}")
  fi
  local child_cpus=""
  local child_memory="${CLUSTERWEAVE_CHILD_DOCKER_MEMORY:-${CLUSTERWEAVE_TOOL_DOCKER_MEMORY}}"
  local child_pids="${CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT:-${CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT}}"
  child_cpus="$(bounded_docker_cpu_limit "${CLUSTERWEAVE_CHILD_DOCKER_CPUS:-}" "${CLUSTERWEAVE_TOOL_DOCKER_CPUS}")"
  if [[ -n "${CLUSTERWEAVE_JOB_ID:-}" ]]; then
    args+=(--label "clusterweave.job_id=${CLUSTERWEAVE_JOB_ID}" --label "clusterweave.project=${PROJECT_NAME:-}")
  fi
  if [[ "${child_cpus}" =~ ^[0-9]+([.][0-9]+)?$ && "${child_cpus}" != "0" && "${child_cpus}" != "0.0" ]]; then
    args+=(--cpus "${child_cpus}")
  fi
  if [[ "${child_memory}" =~ ^[0-9]+([.][0-9]+)?[bBkKmMgG]?$ && "${child_memory}" != "0" ]]; then
    args+=(--memory "${child_memory}")
  fi
  if [[ "${child_pids}" =~ ^[0-9]+$ && "${child_pids}" -ge 1 ]]; then
    args+=(--pids-limit "${child_pids}")
  fi
  if [[ -n "${DOCKER_DATA_VOLUME}" ]]; then
    args+=(-v "${DOCKER_DATA_VOLUME}:/data")
  else
    args+=(
      -v "${PROJECT_DIR}:${PROJECT_DIR}"
      -v "${FUNGI_GENOME_ROOT}:${FUNGI_GENOME_ROOT}"
      -v "${BACTERIA_GENOME_ROOT}:${BACTERIA_GENOME_ROOT}"
      -v "${RESULTS_ROOT}:${RESULTS_ROOT}"
    )
  fi
  if [[ -n "${DOCKER_ANTISMASH_DB_VOLUME}" ]]; then
    args+=(-v "${DOCKER_ANTISMASH_DB_VOLUME}:${ANTISMASH_DB_DIR}")
  elif [[ -d "${ANTISMASH_DB_DIR}" ]]; then
    args+=(-v "${ANTISMASH_DB_DIR}:${ANTISMASH_DB_DIR}")
  fi
  if [[ -z "${DOCKER_DATA_VOLUME}" ]]; then
    args+=(-v "${WORK_ROOT}:${WORK_ROOT}")
  fi
  args+=(
    -e "CUDA_VISIBLE_DEVICES="
    -e "ANTISMASH_DB_DIR=${ANTISMASH_DB_DIR}"
    -e "FUNANNOTATE_DB=${FUNANNOTATE_DB:-/opt/databases}"
    -e "OMP_NUM_THREADS=${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
    -e "OPENBLAS_NUM_THREADS=${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
    -e "MKL_NUM_THREADS=${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
    -e "NUMEXPR_NUM_THREADS=${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
    -e "VECLIB_MAXIMUM_THREADS=${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
    -e "BLIS_NUM_THREADS=${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
  )
  printf '%s\0' "${args[@]}"
}

docker_exec() {
  local image="$1"; shift
  local -a args=()
  mapfile -d '' -t args < <(docker_run_args)
  docker run "${args[@]}" "${image}" "$@"
}

ensure_docker_image() {
  local label="$1"
  local image="$2"
  [[ -n "${image}" ]] || return 1
  if docker image inspect "${image}" >/dev/null 2>&1; then
    log "${label} Docker image present: ${image}"
    return 0
  fi
  warn "${label} Docker image missing: ${image}"
  runtime_preparation_hint
  return 1
}

antismash_exec() {
  # Every invocation, including overlapping shards, owns its writable cache.
  local scratch
  mkdir -p "${WORK_ROOT}/tmp"
  scratch="$(mktemp -d "${WORK_ROOT}/tmp/antismash-exec.XXXXXXXX")" || return 1
  local -a scratch_env=("TMPDIR=${scratch}" "TMP=${scratch}" "TEMP=${scratch}"
    "MPLCONFIGDIR=${scratch}/matplotlib" "XDG_CACHE_HOME=${scratch}/cache")
  if [[ "${ENGINE}" == "docker" ]]; then
    if have antismash; then
      env "ANTISMASH_DB_DIR=${ANTISMASH_DB_DIR}" "${scratch_env[@]}" "$@"
    else
      docker_exec "${ANTISMASH_DOCKER_IMAGE}" env "${scratch_env[@]}" "$@"
    fi
  else
    # Prodigal also writes piped training input into its current directory.
    # The repository and SIF stay read-only inside the existing confinement.
    "${ENGINE}" exec "${BIND_ARGS[@]}" --pwd "${scratch}" "${ANTISMASH_SIF}" \
      env "${scratch_env[@]}" "$@"
  fi
}

###############################################################################
# Paths / working dirs
###############################################################################
mkdir -p "${RESULTS_ROOT}"/{antismash,funbgcex,braker3,funannotate,summary_tables,input_gbks,tmp,logs}
mkdir -p "${FUNGI_GENOME_ROOT}" "${BACTERIA_GENOME_ROOT}"

LOGDIR="${LOGDIR:-${RESULTS_ROOT}/logs}"
mkdir -p "${LOGDIR}"
PIPELOG="${LOGDIR}/run_annotation_and_detection.$(date +%Y%m%d_%H%M%S).log"

WORK_ROOT="${WORK_ROOT:-/tmp/$(basename "${RESULTS_ROOT}")_work}"
mkdir -p "${WORK_ROOT}"/{logs,tmp,bin}

if [[ "${ENGINE}" != "docker" ]]; then
  BIND_ARGS+=(--bind "${WORK_ROOT}:${WORK_ROOT}")
fi

###############################################################################
# Logging helpers
###############################################################################
ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "[$(ts)] [INFO] $*" | tee -a "${PIPELOG}"; }
warn(){ echo "[$(ts)] [WARN] $*" | tee -a "${PIPELOG}" >&2; }
err(){ echo "[$(ts)] [ERROR] $*" | tee -a "${PIPELOG}" >&2; }
die(){ err "$*"; exit 1; }
join_by() { local IFS="$1"; shift; echo "$*"; }

positive_int_or_default() {
  local value="${1:-}"
  local default="${2:-1}"
  if [[ "${value}" =~ ^[0-9]+$ ]] && [[ "${value}" -ge 1 ]]; then
    printf '%s\n' "${value}"
  else
    printf '%s\n' "${default}"
  fi
}

minimum_int() {
  local minimum="${1}"
  shift
  local value=""
  for value in "$@"; do
    if [[ "${value}" -lt "${minimum}" ]]; then
      minimum="${value}"
    fi
  done
  printf '%s\n' "${minimum}"
}

count_cpuset_cpus() {
  "${VENV_PY}" "${ANNOTATION_RUNTIME_HELPER}" count-cpuset --spec "${1:-}"
}

detect_online_cpus() {
  "${VENV_PY}" "${ANNOTATION_RUNTIME_HELPER}" online-cpus
}

detect_effective_cpus() {
  local cgroup_root="${1:-/sys/fs/cgroup}"
  "${VENV_PY}" "${ANNOTATION_RUNTIME_HELPER}" effective-cpus \
    --cgroup-root "${cgroup_root}"
}

detect_effective_memory_mb() {
  "${VENV_PY}" "${ANNOTATION_RUNTIME_HELPER}" effective-memory
}

freeze_resource_plan() {
  local total_genomes="$(positive_int_or_default "${1:-}" 1)"
  local requested_cpus="${CPUS}"
  local plan_fields=""
  local annotation_slots=0 funbgcex_slots=0 antismash_shard_slots=0 antismash_legacy_slots=0
  RESOURCE_EFFECTIVE_CPUS="$(detect_effective_cpus)"
  RESOURCE_EFFECTIVE_MEMORY_MB="$(detect_effective_memory_mb)"
  plan_fields="$(
    "${VENV_PY}" "${ANNOTATION_RUNTIME_HELPER}" resource-plan \
      --mode "${PIPELINE_RESOURCE_MODE}" \
      --requested-cpus "${CPUS}" \
      --cpus-explicit "${CPUS_REQUEST_EXPLICIT}" \
      --effective-cpus "${RESOURCE_EFFECTIVE_CPUS}" \
      --effective-memory-mb "${RESOURCE_EFFECTIVE_MEMORY_MB}" \
      --total-genomes "${total_genomes}" \
      --genome-parallelism "${GENOME_PARALLELISM}" \
      --anno-cpus "${ANNO_CPUS}" \
      --funbgcex-workers "${WORKERS}" \
      --antismash-record-parallelism "${ANTISMASH_RECORD_PARALLELISM}" \
      --antismash-shard-cpus "${ANTISMASH_SHARD_CPUS_REQUESTED}" \
      --antismash-legacy-cpus "${ANTISMASH_LEGACY_CPUS_REQUESTED}" \
      --memory-budget-mb "${PIPELINE_MEMORY_BUDGET_MB}" \
      --auto-max-cpus "${PIPELINE_AUTO_MAX_CPUS}" \
      --auto-max-genome-parallelism "${PIPELINE_AUTO_MAX_GENOME_PARALLELISM}" \
      --auto-min-cpus-per-genome "${PIPELINE_AUTO_MIN_CPUS_PER_GENOME}" \
      --auto-memory-percent "${PIPELINE_AUTO_MEMORY_PERCENT}" \
      --auto-memory-per-genome-mb "${PIPELINE_AUTO_MEMORY_PER_GENOME_MB}" \
      --auto-max-anno-cpus "${PIPELINE_AUTO_MAX_ANNO_CPUS}" \
      --auto-max-funbgcex-workers "${PIPELINE_AUTO_MAX_FUNBGCEX_WORKERS}" \
      --auto-max-antismash-record-parallelism "${PIPELINE_AUTO_MAX_ANTISMASH_RECORD_PARALLELISM}"
  )" || die "Failed to build the annotation resource plan"
  IFS=$'\t' read -r \
    CPUS GENOME_PARALLELISM PER_GENOME_CPU_BUDGET ANNO_CPUS WORKERS \
    ANTISMASH_RECORD_PARALLELISM ANTISMASH_SHARD_CPUS ANTISMASH_LEGACY_CPUS \
    RESOURCE_EFFECTIVE_CPUS RESOURCE_EFFECTIVE_MEMORY_MB RESOURCE_MEMORY_BUDGET_MB \
    annotation_slots funbgcex_slots antismash_shard_slots antismash_legacy_slots \
    <<< "${plan_fields}"
  if [[ "${annotation_slots}" -gt "${CPUS}" || "${funbgcex_slots}" -gt "${CPUS}" || "${antismash_shard_slots}" -gt "${CPUS}" || "${antismash_legacy_slots}" -gt "${CPUS}" ]]; then
    die "Resource plan invariant failed: a stage can exceed CPUS=${CPUS}"
  fi

  log "RESOURCE_PLAN_FROZEN mode=${PIPELINE_RESOURCE_MODE} requested_cpus=${requested_cpus} effective_cpus=${RESOURCE_EFFECTIVE_CPUS} effective_memory_mb=${RESOURCE_EFFECTIVE_MEMORY_MB} memory_budget_mb=${RESOURCE_MEMORY_BUDGET_MB} genomes=${total_genomes} cpus=${CPUS} genome_parallelism=${GENOME_PARALLELISM} per_genome_cpu_budget=${PER_GENOME_CPU_BUDGET} anno_cpus=${ANNO_CPUS} funbgcex_workers=${WORKERS} antismash_record_parallelism=${ANTISMASH_RECORD_PARALLELISM} antismash_shard_cpus=${ANTISMASH_SHARD_CPUS} antismash_legacy_cpus=${ANTISMASH_LEGACY_CPUS}"
  log "RESOURCE_PLAN_BOUNDS annotation_slots=${annotation_slots} funbgcex_slots=${funbgcex_slots} antismash_shard_slots=${antismash_shard_slots} antismash_legacy_slots=${antismash_legacy_slots} job_cpus=${CPUS}"
}

running_genome_job_count() {
  jobs -rp | wc -l | tr -d '[:space:]'
}

wait_for_genome_job() {
  local rc=0
  set +e
  wait -n
  rc=$?
  set -e
  [[ "${rc}" -eq 0 || "${rc}" -eq 127 ]]
}

wait_for_antismash_shard_job() {
  local rc=0
  set +e
  wait -n
  rc=$?
  set -e
  # Bash can report 127 when all remaining children finish before a later
  # wait -n observes them. Manifest-row validation below still verifies every shard.
  [[ "${rc}" -eq 0 || "${rc}" -eq 127 ]]
}

progress_bar() {
  local percent="${1:-0}"
  local width="${2:-20}"
  local filled empty
  if ! [[ "${percent}" =~ ^[0-9]+$ ]]; then percent=0; fi
  if [[ "${percent}" -lt 0 ]]; then percent=0; fi
  if [[ "${percent}" -gt 100 ]]; then percent=100; fi
  filled=$((percent * width / 100))
  empty=$((width - filled))
  printf '['
  printf '%*s' "${filled}" '' | tr ' ' '#'
  printf '%*s' "${empty}" '' | tr ' ' '-'
  printf ']'
}

genome_stage_progress() {
  local genome_id="${1:-genome}"
  local stage="${2:-annotation}"
  local percent="${3:-0}"
  local message="${4:-Working}"
  message="$(tool_activity_limit_line "${message}")"
  message="${message//\"/ }"
  log "GENOME_PROGRESS genome=${genome_id} stage=${stage} percent=${percent} bar=$(progress_bar "${percent}") message=\"${message}\""
}

genome_annotation_decision() {
  local genome_id="${1:-genome}"
  local required="${2:-no}"
  local method="${3:-existing_cds}"
  local message="${4:-Annotation route selected}"
  message="$(tool_activity_limit_line "${message}")"
  message="${message//\"/ }"
  log "GENOME_ANNOTATION_DECISION genome=${genome_id} required=${required} method=${method} message=\"${message}\""
}

antismash_record_progress() {
  local genome_id="${1:-genome}"
  local record_id="${2:-record}"
  local ordinal="${3:-1}"
  local total_records="${4:-1}"
  local percent="${5:-0}"
  local message="${6:-Working}"
  record_id="$(tool_activity_clean_line "${record_id}")"
  record_id="$(safe_antismash_record_id "${record_id}")"
  message="$(tool_activity_limit_line "${message}")"
  message="${message//\"/ }"
  log "ANTISMASH_RECORD_PROGRESS genome=${genome_id} record=${record_id} ordinal=${ordinal}/${total_records} percent=${percent} bar=$(progress_bar "${percent}") message=\"${message}\""
}

tool_activity_clean_line() {
  local value="${1:-}"
  value="${value//$'\r'/}"
  value="${value//$'\t'/ }"
  printf '%s' "${value}" | LC_ALL=C tr -cd '\11\12\15\40-\176'
}

tool_activity_limit_line() {
  local value=""
  value="$(tool_activity_clean_line "${1:-}")"
  local limit="${TOOL_ACTIVITY_RAW_LIMIT:-1200}"
  if [[ "${#value}" -gt "${limit}" ]]; then
    value="${value:0:${limit}}..."
  fi
  printf '%s\n' "${value}"
}

tool_activity_display_name() {
  case "${1:-}" in
    plantismash) printf '%s\n' "plantiSMASH" ;;
    antismash) printf '%s\n' "antiSMASH" ;;
    funannotate) printf '%s\n' "funannotate" ;;
    funbgcex) printf '%s\n' "FunBGCeX" ;;
    *) printf '%s\n' "${1:-tool}" ;;
  esac
}

tool_activity_public_message() {
  local tool="${1:-}"
  local line="${2:-}"
  local lower=""
  local error_scan=""
  lower="$(printf '%s' "${line}" | tr '[:upper:]' '[:lower:]')"
  # Progress reporters commonly include neutral counters such as
  # "0 failed". Remove those counters before classifying an error so the
  # public activity stream does not announce a failure for healthy work.
  error_scan="${lower//0 failed/}"
  error_scan="${error_scan//0 errors/}"
  error_scan="${error_scan//0 error/}"
  case "${tool}" in
    plantismash)
      if [[ "${lower}" == plant_phase* ]]; then
        case "${lower}" in
          *phase=merging*) printf '%s\n' "Merging plantiSMASH record outputs" ;;
          *phase=validating*) printf '%s\n' "Validating plantiSMASH genome outputs" ;;
          *phase=exporting*) printf '%s\n' "Exporting plantiSMASH native reports" ;;
          *) return 1 ;;
        esac
        return 0
      fi
      if [[ "${lower}" =~ ^plant_shard.*completed=([0-9]+)/([0-9]+) ]]; then
        local completed="${BASH_REMATCH[1]}" total="${BASH_REMATCH[2]}"
        if [[ "${lower}" =~ state=(failed|invalid|cancelled) ]]; then
          printf '%s\n' "plantiSMASH record shard failed or cancelled; ${completed}/${total} complete"
        else
          printf '%s\n' "plantiSMASH record shards: ${completed}/${total} complete; genome processing continues"
        fi
        return 0
      fi
      if [[ "${lower}" == plant_shard* ]]; then
        if [[ "${lower}" == *state=failed* || "${lower}" == *state=invalid* || "${lower}" == *state=cancelled* ]]; then printf '%s\n' "plantiSMASH record shard failed or cancelled";
        elif [[ "${lower}" == *state=complete* ]]; then printf '%s\n' "plantiSMASH record shard complete";
        else printf '%s\n' "Running plantiSMASH record shards"; fi
        return 0
      fi
      ;;
    antismash)
      # Matplotlib falls back to a temporary cache after this specific warning.
      # Raw stderr remains retained; exit status and output validation are authoritative.
      if [[ "${lower}" == *matplotlib* && ( "${lower}" == *"mkdir -p failed for path"* || "${lower}" == *"created a temporary"* ) ]]; then
        printf '%s\n' "antiSMASH reported a recoverable Matplotlib cache warning"; return 0
      fi
      if [[ "${error_scan}" =~ (error|failed|exception|traceback) ]]; then printf '%s\n' "antiSMASH reported an error"; return 0; fi
      if [[ "${lower}" =~ running[[:space:]]+whole-genome[[:space:]]+pfam[[:space:]]+search ]]; then printf '%s\n' "Running whole-genome PFAM search"; return 0; fi
      if [[ "${lower}" =~ (database|databases|schema|download) ]]; then printf '%s\n' "Checking antiSMASH databases"; return 0; fi
      if [[ "${lower}" =~ (domain|hmmer|hmm|pfam|blast|diamond|smcog) ]]; then printf '%s\n' "Scanning protein domains"; return 0; fi
      if [[ "${lower}" =~ (cluster|region|detect|detection|rule|rules) ]]; then printf '%s\n' "Detecting biosynthetic regions"; return 0; fi
      if [[ "${lower}" =~ (html|json|write|writing|output|result) ]]; then printf '%s\n' "Writing antiSMASH outputs"; return 0; fi
      if [[ "${lower}" =~ (warn|warning) ]]; then printf '%s\n' "antiSMASH reported a warning"; return 0; fi
      if [[ "${error_scan}" =~ (error|failed|exception|traceback) ]]; then printf '%s\n' "antiSMASH reported an error"; return 0; fi
      ;;
    funannotate)
      if [[ "${lower}" =~ (sort|clean|prepare|assembly|contig|fasta) ]]; then printf '%s\n' "Preparing assembly"; return 0; fi
      if [[ "${lower}" =~ (busco|augustus|train|training|validated|model) ]]; then printf '%s\n' "Training gene models"; return 0; fi
      if [[ "${lower}" =~ (predict|gene|genemark|snap|glimmer|codingquarry|exonerate|protein) ]]; then printf '%s\n' "Predicting genes"; return 0; fi
      if [[ "${lower}" =~ (gff|gbk|tbl|annotation|write|writing|output|result) ]]; then printf '%s\n' "Writing annotation outputs"; return 0; fi
      if [[ "${lower}" =~ (warn|warning) ]]; then printf '%s\n' "funannotate reported a warning"; return 0; fi
      if [[ "${error_scan}" =~ (error|failed|exception|traceback) ]]; then printf '%s\n' "funannotate reported an error"; return 0; fi
      ;;
  esac
  return 1
}

tool_activity_emit_progress() {
  local genome="${1:-genome}"
  local tool="${2:-tool}"
  local phase="${3:-run}"
  local message=""
  message="$(tool_activity_limit_line "${4:-Running}")"
  message="${message//\"/ }"
  log "TOOL_PROGRESS genome=${genome} tool=${tool} phase=${phase} message=\"${message}\""
}
tool_activity_emit_heartbeat() {
  local genome="${1:-genome}"
  local tool="${2:-tool}"
  local phase="${3:-run}"
  local elapsed="${4:-0}"
  log "TOOL_HEARTBEAT genome=${genome} tool=${tool} phase=${phase} elapsed=${elapsed}s"
}

tool_activity_stream() {
  local genome="${1:-genome}"
  local tool="${2:-tool}"
  local stream="${3:-stdout}"
  local dest="${4:-/dev/null}"
  local phase="${5:-run}"
  local line=""
  local raw=""
  local public_message=""
  local last_public_message=""
  local raw_line_count=0
  local central_raw_count=0
  local central_raw_limit="${TOOL_ACTIVITY_CENTRAL_RAW_LIMIT:-24}"
  if ! [[ "${central_raw_limit}" =~ ^[0-9]+$ ]]; then
    central_raw_limit=24
  fi
  while IFS= read -r line; do
    raw="$(tool_activity_limit_line "${line}")"
    # Keep exact tool text privately; central/public presentation remains bounded.
    printf '%s\n' "${line}" >> "${dest}"
    raw_line_count=$((raw_line_count + 1))
    if [[ "${tool}" == plantismash && "${raw}" =~ ^PLANT_SHARD[[:space:]]ordinal=([0-9]+)[[:space:]]state=([a-z]+)[[:space:]]completed=([0-9]+)/([0-9]+)$ ]]; then
      log "PLANT_RECORD_PROGRESS genome=${genome} record=${BASH_REMATCH[1]} ordinal=${BASH_REMATCH[1]}/${BASH_REMATCH[4]} state=${BASH_REMATCH[2]}"
    fi
    if [[ "${central_raw_count}" -lt "${central_raw_limit}" ]]; then
      log "TOOL_RAW genome=${genome} tool=${tool} stream=${stream} ${raw}"
      central_raw_count=$((central_raw_count + 1))
    fi
    if public_message="$(tool_activity_public_message "${tool}" "${raw}")"; then
      if [[ -n "${public_message}" && "${public_message}" != "${last_public_message}" ]]; then
        tool_activity_emit_progress "${genome}" "${tool}" "${phase}" "${public_message}"
        last_public_message="${public_message}"
      fi
    fi
  done
  if [[ "${raw_line_count}" -gt "${central_raw_count}" ]]; then
    log "TOOL_RAW_SUMMARY genome=${genome} tool=${tool} stream=${stream} total=${raw_line_count} central_emitted=${central_raw_count} private_retained=${raw_line_count}"
  fi
}

tool_activity_heartbeat_loop() {
  local genome="${1:-genome}"
  local tool="${2:-tool}"
  local phase="${3:-run}"
  local marker="${4:-}"
  local start=""
  local now=""
  local elapsed="0"
  start="$(date +%s)"
  while [[ -n "${marker}" && -f "${marker}" ]]; do
    sleep "${TOOL_ACTIVITY_HEARTBEAT_SECONDS:-45}"
    [[ -f "${marker}" ]] || break
    now="$(date +%s)"
    elapsed=$((now - start))
    tool_activity_emit_heartbeat "${genome}" "${tool}" "${phase}" "${elapsed}"
  done
}

run_tool_with_activity() {
  local genome="${1:-genome}"
  local tool="${2:-tool}"
  local phase="${3:-run}"
  local stdout_log="${4:-/dev/null}"
  local stderr_log="${5:-/dev/null}"
  shift 5
  local marker="${WORK_ROOT}/tmp/${genome}.${tool}.${phase}.activity"
  local heartbeat_pid=""
  local rc=0
  : >> "${stdout_log}"
  if [[ "${stderr_log}" != "${stdout_log}" ]]; then : >> "${stderr_log}"; fi
  : > "${marker}"
  tool_activity_emit_progress "${genome}" "${tool}" "${phase}" "Started $(tool_activity_display_name "${tool}")"
  tool_activity_heartbeat_loop "${genome}" "${tool}" "${phase}" "${marker}" &
  heartbeat_pid="$!"
  set +e
  "$@" > >(tool_activity_stream "${genome}" "${tool}" stdout "${stdout_log}" "${phase}")        2> >(tool_activity_stream "${genome}" "${tool}" stderr "${stderr_log}" "${phase}")
  rc=$?
  set -e
  rm -f "${marker}" 2>/dev/null || true
  if [[ -n "${heartbeat_pid}" ]]; then
    kill "${heartbeat_pid}" 2>/dev/null || true
    wait "${heartbeat_pid}" 2>/dev/null || true
  fi
  if [[ "${rc}" -eq 0 ]]; then
    log "TOOL_EXECUTION genome=${genome} tool=${tool} state=complete exit_code=0"
    tool_activity_emit_progress "${genome}" "${tool}" "${phase}" "$(tool_activity_display_name "${tool}") finished"
  else
    log "TOOL_EXECUTION genome=${genome} tool=${tool} state=failed exit_code=${rc}"
    tool_activity_emit_progress "${genome}" "${tool}" "${phase}" "$(tool_activity_display_name "${tool}") reported an error"
  fi
  return "${rc}"
}

resolve_python_cmd() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    have "${PYTHON_BIN}" || die "PYTHON_BIN not found in PATH: ${PYTHON_BIN}"
    printf '%s\n' "${PYTHON_BIN}"
    return 0
  fi
  if have "${VENV_PY}"; then
    printf '%s\n' "${VENV_PY}"
    return 0
  fi
  if have python3; then
    printf '%s\n' "python3"
    return 0
  fi
  if have python; then
    printf '%s\n' "python"
    return 0
  fi
  die "No usable Python interpreter found. Install python3 or set PYTHON_BIN."
}

ANNOTATION_RUNTIME_ARGV=()
annotation_runtime_argv() {
  local argv_file=""
  argv_file="$(mktemp "${WORK_ROOT}/tmp/annotation_runtime_argv.XXXXXX")" \
    || die "Could not allocate annotation runtime argv file"
  if ! "${VENV_PY}" "${ANNOTATION_RUNTIME_HELPER}" "$@" > "${argv_file}"; then
    rm -f "${argv_file}" 2>/dev/null || true
    die "Could not construct annotation runtime argv for $1"
  fi
  mapfile -d '' -t ANNOTATION_RUNTIME_ARGV < "${argv_file}"
  rm -f "${argv_file}" 2>/dev/null || true
  [[ "${#ANNOTATION_RUNTIME_ARGV[@]}" -gt 0 ]] \
    || die "Annotation runtime helper returned an empty argv for $1"
}

###############################################################################
# Tracked GFF3-to-GenBank converter
###############################################################################
CONVERT_PY="${CONVERT_PY:-${PROJECT_DIR}/bin/gff3_to_gbk_with_translations.py}"
GENBANK_TRANSLATION_CHECKER="${GENBANK_TRANSLATION_CHECKER:-${PROJECT_DIR}/bin/check_genbank_translations.py}"

###############################################################################
# Input discovery/resolution
###############################################################################
GENOME_MAPPING_FILE="${GENOME_MAPPING_FILE:-${GENOME_ROOT}/accessions_fungusID_taxonomyID.txt}"
VENV_PY="${VENV_PY:-python3}"
ANNOTATION_INPUT_HELPER="${ANNOTATION_INPUT_HELPER:-${SCRIPT_DIR:-.}/bin/annotation_input.py}"
declare -A DEFAULT_PREDICTION_BY_TAXON=()
declare -A DEFAULT_DETECTOR_BY_TAXON=()
declare -A ROUTE_TAXON_BY_GENOME=()
declare -A ROUTE_ROOT_BY_GENOME=()
declare -A ROUTE_PREDICTION_BY_GENOME=()
declare -A ROUTE_DETECTOR_BY_GENOME=()
declare -A ROUTE_SOURCE_BY_GENOME=()
declare -A ROUTE_STATUS_BY_GENOME=()
ROUTE_MANIFEST_ACTIVE=0
HAS_FUNGAL_ROUTES=0
HAS_BACTERIAL_ROUTES=0
HAS_PLANT_ROUTES=0

load_taxon_routes() {
  local kind genome_id taxon_group root prediction_method detector_profile taxon_source route_status
  local route_output="" profile_defaults=""
  route_output="$(
    "${VENV_PY}" "${ANNOTATION_INPUT_HELPER}" routes \
      --manifest "${GENOME_TAXON_MANIFEST}" \
      --fungi-root "${FUNGI_GENOME_ROOT}" \
      --bacteria-root "${BACTERIA_GENOME_ROOT}" \
      --plants-root "${PLANTS_GENOME_ROOT:-${FUNGI_GENOME_ROOT%/*}/plants}"
  )" || die "Failed to load canonical taxon manifest: ${GENOME_TAXON_MANIFEST}"
  profile_defaults="$(
    "${VENV_PY}" "${ANNOTATION_INPUT_HELPER}" profile-defaults
  )" || die "Failed to load scientific profile defaults"
  while IFS=$'\t' read -r taxon_group prediction_method detector_profile; do
    DEFAULT_PREDICTION_BY_TAXON["${taxon_group}"]="${prediction_method}"
    DEFAULT_DETECTOR_BY_TAXON["${taxon_group}"]="${detector_profile}"
  done <<< "${profile_defaults}"
  while IFS=$'\034' read -r \
      kind genome_id taxon_group root prediction_method detector_profile \
      taxon_source route_status; do
    if [[ "${kind}" == "meta" ]]; then
      ROUTE_MANIFEST_ACTIVE="${genome_id}"
      HAS_FUNGAL_ROUTES="${taxon_group}"
      HAS_BACTERIAL_ROUTES="${root}"
      continue
    fi
    [[ "${kind}" == "route" ]] || continue
    [[ "${taxon_group}" == "plants" ]] && HAS_PLANT_ROUTES=1
    ROUTE_TAXON_BY_GENOME["${genome_id}"]="${taxon_group}"
    ROUTE_ROOT_BY_GENOME["${genome_id}"]="${root}"
    ROUTE_PREDICTION_BY_GENOME["${genome_id}"]="${prediction_method}"
    ROUTE_DETECTOR_BY_GENOME["${genome_id}"]="${detector_profile}"
    ROUTE_SOURCE_BY_GENOME["${genome_id}"]="${taxon_source}"
    ROUTE_STATUS_BY_GENOME["${genome_id}"]="${route_status}"
  done <<< "${route_output//$'\t'/$'\034'}"
}

persist_taxon_routes() {
  # Downstream readers use the result-local route manifest. Preserve the
  # validated external CLI manifest there before any native work starts.
  local canonical_routes="${RESULTS_ROOT}/summary_tables/genome_taxon_manifest.tsv"
  if [[ "${ROUTE_MANIFEST_ACTIVE}" == "1" ]] && \
     [[ "$(realpath -m "${GENOME_TAXON_MANIFEST}")" != "$(realpath -m "${canonical_routes}")" ]]; then
    mkdir -p "$(dirname "${canonical_routes}")"
    [[ ! -L "${canonical_routes}" ]] || die "Canonical taxon manifest must not be a symbolic link"
    if [[ -e "${canonical_routes}" ]]; then
      cmp -s "${GENOME_TAXON_MANIFEST}" "${canonical_routes}" || \
        die "Existing result taxon manifest differs from supplied routes; use a fresh results directory"
    else
      local route_copy
      route_copy="$(mktemp "${canonical_routes}.tmp.XXXXXX")"
      cp "${GENOME_TAXON_MANIFEST}" "${route_copy}"
      mv -n "${route_copy}" "${canonical_routes}"
      rm -f "${route_copy}"
      cmp -s "${GENOME_TAXON_MANIFEST}" "${canonical_routes}" || die "Concurrent taxon manifest change"
    fi
    GENOME_TAXON_MANIFEST="${canonical_routes}"
  fi
}

route_taxon_for_genome() {
  printf '%s\n' "${ROUTE_TAXON_BY_GENOME[$1]:-fungi}"
}

route_root_for_genome() {
  printf '%s\n' "${ROUTE_ROOT_BY_GENOME[$1]:-${FUNGI_GENOME_ROOT}}"
}

route_prediction_for_genome() {
  local genome_id="$1"
  local taxon_group=""
  taxon_group="$(route_taxon_for_genome "${genome_id}")"
  printf '%s\n' "${ROUTE_PREDICTION_BY_GENOME[${genome_id}]:-${DEFAULT_PREDICTION_BY_TAXON[${taxon_group}]}}"
}

route_detector_for_genome() {
  local genome_id="$1"
  local taxon_group=""
  taxon_group="$(route_taxon_for_genome "${genome_id}")"
  printf '%s\n' "${ROUTE_DETECTOR_BY_GENOME[${genome_id}]:-${DEFAULT_DETECTOR_BY_TAXON[${taxon_group}]}}"
}

route_source_for_genome() {
  printf '%s\n' "${ROUTE_SOURCE_BY_GENOME[$1]:-legacy_default}"
}

route_status_for_genome() {
  printf '%s\n' "${ROUTE_STATUS_BY_GENOME[$1]:-routed}"
}

mapping_file_for_taxon() {
  local taxon_group="$1"
  if [[ "${taxon_group}" == "plants" ]]; then
    printf '%s\n' "${PLANTS_GENOME_ROOT}/accessions_plantsID_taxonomyID.txt"
  elif [[ "${taxon_group}" == "bacteria" ]]; then
    printf '%s\n' "${BACTERIA_GENOME_ROOT}/accessions_bacteriaID_taxonomyID.txt"
  else
    printf '%s\n' "${FUNGI_GENOME_ROOT}/accessions_fungusID_taxonomyID.txt"
  fi
}

genome_stem_has_file() {
  "${VENV_PY}" "${ANNOTATION_INPUT_HELPER}" has-input --root "${2:-${GENOME_ROOT}}" --stem "$1"
}

mapped_canonical_stem() {
  "${VENV_PY}" "${ANNOTATION_INPUT_HELPER}" mapped-canonical --mapping-file "${GENOME_MAPPING_FILE}" --stem "$1"
}

source "${SCRIPT_DIR}/annotation_funannotate.sh"

source "${SCRIPT_DIR}/annotation_braker3.sh"

source "${SCRIPT_DIR}/annotation_prepare.sh"

should_skip_discovered_stem() {
  local stem="$1"
  local canonical=""
  canonical="$(
    "${VENV_PY}" "${ANNOTATION_INPUT_HELPER}" materialized-alias \
      --mapping-file "${GENOME_MAPPING_FILE}" \
      --fungi-root "${FUNGI_GENOME_ROOT}" \
      --stem "${stem}"
  )" || return 1
  warn "skipping accession alias genome stem: ${stem} maps to existing ${canonical}"
}

discover_stems() {
  if [[ "${ROUTE_MANIFEST_ACTIVE}" -eq 1 ]]; then
    printf '%s\n' "${!ROUTE_TAXON_BY_GENOME[@]}" | LC_ALL=C sort
    return 0
  fi
  "${VENV_PY}" "${ANNOTATION_INPUT_HELPER}" discover \
    --fungi-root "${FUNGI_GENOME_ROOT}" \
    --mapping-file "${GENOME_MAPPING_FILE}"
}

resolve_fasta_for_stem() {
  "${VENV_PY}" "${ANNOTATION_INPUT_HELPER}" resolve --kind fasta --root "${2:-${GENOME_ROOT}}" --stem "$1"
}

resolve_genbank_for_stem() {
  "${VENV_PY}" "${ANNOTATION_INPUT_HELPER}" resolve --kind genbank --root "${2:-${GENOME_ROOT}}" --stem "$1"
}



runtime_preparation_hint() {
  warn "Runtime acquisition is disabled during canonical jobs."
  warn "Prepare local assets with: docker compose run --rm --no-deps worker prepare-runtime"
  warn "Verify them with: docker compose run --rm --no-deps worker check-runtime"
  warn "External executors must pre-provision the configured site-managed runtime."
}

ensure_prepared_sif() {
  local label="$1"
  local sif="$2"
  local uri="$3"

  if [[ "${ENGINE}" == "docker" ]]; then
    ensure_docker_image "${label}" "$(docker_image_from_uri "${uri}")"
    return $?
  fi

  if [[ -s "${sif}" ]]; then
    log "${label} SIF present: ${sif}"
    return 0
  fi

  warn "${label} SIF missing: ${sif}"
  warn "${label} configured image source: ${uri}"
  runtime_preparation_hint
  return 1
}

source "${SCRIPT_DIR}/detection_funbgcex.sh"

repository_helper_python_exec() {
  # The Docker worker is built from the pinned antiSMASH image and already
  # carries Biopython plus this repository. A sibling FunBGCeX container sees
  # the named /data volume but cannot see the worker-only /clusterweave path,
  # so preparation helpers use the prepared application Python when available.
  # This also applies to a nonroot SIF worker; a plant-only route never bootstraps
  # the fungal detector. Standalone HPC users retain the prepared SIF fallback.
  local helper_python
  helper_python="$(resolve_python_cmd)"
  if [[ "${ENGINE}" == "docker" ]] || "${helper_python}" -c 'import Bio' >/dev/null 2>&1; then
    "${helper_python}" "$@"
  else
    if [[ -z "${FUNBGCEX_RUNTIME:-}" ]]; then
      ensure_funbgcex_runtime
    fi
    funbgcex_python_exec "$@"
  fi
}

antismash_input_python_exec() {
  repository_helper_python_exec "$@"
}

ensure_primary_tooling() {
  if [[ "${HAS_FUNGAL_ROUTES}" == "0" && "${HAS_BACTERIAL_ROUTES}" == "0" && "${HAS_PLANT_ROUTES}" == "1" ]]; then
    return 0
  fi
  if [[ "${ENGINE}" == "docker" ]]; then
    if have antismash; then
      log "antiSMASH available on worker PATH."
    else
      ensure_docker_image "antiSMASH" "${ANTISMASH_DOCKER_IMAGE}" \
        || die "antiSMASH is required but unavailable after runtime preparation. Provide ANTISMASH_DOCKER_IMAGE."
    fi
  else
    ensure_prepared_sif "antiSMASH" "${ANTISMASH_SIF}" "${ANTISMASH_IMAGE_URI}" \
      || die "antiSMASH is required but unavailable after runtime preparation. Provide ANTISMASH_SIF."
  fi
  if [[ "${HAS_FUNGAL_ROUTES}" -eq 1 ]]; then
    ensure_funbgcex_runtime \
      || die "FunBGCeX is required for fungal routes but unavailable after runtime preparation."
  else
    log "Skipping FunBGCeX runtime check: no fungal routes are present."
  fi
}

source "${SCRIPT_DIR}/detection_plantismash.sh"

source "${SCRIPT_DIR}/detection_antismash.sh"

###############################################################################
# Per-genome logging sync + manifest
###############################################################################
sync_logs_genome() {
  local genome_id="$1"
  mkdir -p "${RESULTS_ROOT}/logs"
  rsync -a "${WORK_ROOT}/logs/${genome_id}."* "${RESULTS_ROOT}/logs/" >/dev/null 2>&1 || true
}

MANIFEST="${RESULTS_ROOT}/summary_tables/run_manifest.tsv"
mkdir -p "$(dirname "${MANIFEST}")"
printf "genome_id\tfasta\tgbk_used\tgbk_status\tantismash_status\tfunbgcex_status\ttaxon_group\tprediction_method\tdetector_profile\tfunbgcex_applicability\n" > "${MANIFEST}"

###############################################################################
# CLI
###############################################################################
usage() {
  cat <<EOF
Usage: $0 [-f] [-t THREADS] [-c CPUS] [-w WORKERS] [-p GENOME_PARALLELISM] [-g genome1,genome2,...]
  -f            Force re-run even if outputs exist (sets FORCE=1; clears staged + outputs per genome)
  -t THREADS    Threads (alias; recorded). If CPUS not set, CPUS=THREADS.
  -c CPUS       antiSMASH cpus (default: ${CPUS})
  -w WORKERS    funbgcex workers per genome (default: ${WORKERS})
  -p N          Concurrent genomes to process in annotation stage (default: ${GENOME_PARALLELISM})
  -g LIST       Comma-separated stems to process. If omitted, auto-discover in GENOME_ROOT.
  -h            Help

Annotation env vars:
  ANNOTATION_FALLBACK_ORDER=... Comma order (default: ${ANNOTATION_FALLBACK_ORDER})
  BRAKER3_ENABLED=0|1          Enable braker3 fallback when listed in order (default: ${BRAKER3_ENABLED})
  BRAKER_SIF=...                BRAKER3 container path (default: ${BRAKER_SIF})
  FUNANNOTATE_SIF=...           funannotate container path (default: ${FUNANNOTATE_SIF})
  BRAKER_SPECIES_PREFIX=...     Prefix for BRAKER species names (default: ${BRAKER_SPECIES_PREFIX})
  FUNANNOTATE_ORGANISM_NAME=... Species label or auto from taxonomy mapping (default: ${FUNANNOTATE_ORGANISM_NAME})
  FUNANNOTATE_BUSCO_DB=...      BUSCO lineage or auto from taxonomy mapping (default: ${FUNANNOTATE_BUSCO_DB})
  FUNANNOTATE_BUSCO_SEED_SPECIES=... Optional AUGUSTUS seed from `funannotate species` (default: unset)
  FUNANNOTATE_BUSCO_DB_DEFAULT=... Conservative auto fallback (default: dikarya)
  FUNANNOTATE_BUSCO_DB_NO_TAXONOMY=... Optional broad fallback when mapping lacks taxonomy; auto-lineage is ignored
  FUNANNOTATE_RETRY_WITHOUT_PROTEIN_EVIDENCE=0|1 Retry predict without default UniProt protein-to-genome mapping if p2g fails (default: ${FUNANNOTATE_RETRY_WITHOUT_PROTEIN_EVIDENCE})
  PLANTS_GENOME_ROOT=...        Translated plant GenBank root; requires explicit plants routes
  PLANTISMASH_SIF=...           Prepared accepted plantiSMASH SIF (no job-time acquisition)
  PLANTISMASH_ENGINE=...        apptainer or singularity for the plant runtime
  GENOME_MAPPING_FILE=...        Mapping file written by genome prep (default: ${GENOME_MAPPING_FILE})
  BRAKER_BAM=...                Optional RNA-seq BAM for BRAKER3
  BRAKER_PROT_SEQ=...           Optional protein FASTA for BRAKER3

Annotation threading:
  ANNO_CPUS=...                 Threads for BRAKER3/funannotate per genome (default: ${ANNO_CPUS})
  GENOME_PARALLELISM=...        Concurrent genomes for annotation fan-out/regroup (default: ${GENOME_PARALLELISM})
  ANTISMASH_RECORD_PARALLELISM=... Concurrent antiSMASH record shards per genome (default: ${ANTISMASH_RECORD_PARALLELISM})
  ANTISMASH_SHARD_CPUS=...      CPUs per record shard (bounded to the per-genome CPU lane)
  ANTISMASH_LEGACY_CPUS=...     CPUs for the legacy single-run path (bounded to the per-genome CPU lane)
  ANTISMASH_RETAIN_SHARD_WORK=0|1 Retain full raw shard HTML/data for debugging (default: 0; compact after success)
  Funannotate is never split by GenBank record; it scales via whole-genome fan-out and its native --cpus.

Resource planning:
  PIPELINE_RESOURCE_MODE=conservative|auto Opt in to cgroup-aware automatic planning (manual is an alias; default: conservative)
  PIPELINE_MEMORY_BUDGET_MB=... Optional hard memory ceiling considered by auto mode
  PIPELINE_AUTO_MAX_CPUS=...    Auto-mode job CPU ceiling (default: ${PIPELINE_AUTO_MAX_CPUS})
  PIPELINE_AUTO_MAX_GENOME_PARALLELISM=... Auto-mode whole-genome fan-out ceiling (default: ${PIPELINE_AUTO_MAX_GENOME_PARALLELISM})
  PIPELINE_AUTO_MEMORY_PER_GENOME_MB=... Conservative memory reservation per active genome (default: ${PIPELINE_AUTO_MEMORY_PER_GENOME_MB})
  PIPELINE_AUTO_MAX_ANNO_CPUS=... Max native BRAKER3/funannotate CPUs per genome (default: ${PIPELINE_AUTO_MAX_ANNO_CPUS})
  CLUSTERWEAVE_TOOL_DOCKER_CPUS=... Optional hard --cpus limit on every Docker tool child
  CLUSTERWEAVE_TOOL_DOCKER_MEMORY=... Optional hard --memory limit on every Docker tool child
  CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT=... Optional hard --pids-limit on every Docker tool child

Runtime preparation compatibility:
  Prepare/check runtimes explicitly before jobs with the worker prepare-runtime/check-runtime commands.
  AUTO_PULL_IMAGES=ask|always|never Accepted compatibility input; jobs never pull (default: ${AUTO_PULL_IMAGES})
  ANTISMASH_IMAGE_URI=...       Source URI for antiSMASH image (default: ${ANTISMASH_IMAGE_URI})
  FUNBGCEX_IMAGE_URI=...        Optional source URI for FunBGCeX image (default: unset)
  AUTO_BUILD_FUNBGCEX_SIF=0|1   Accepted compatibility input; jobs never build (default: ${AUTO_BUILD_FUNBGCEX_SIF})
  FUNBGCEX_DEF=...              Singularity definition used for the local FunBGCeX build
  FUNBGCEX_DOCKERFILE=...       Dockerfile used for the local FunBGCeX build fallback path
  FUNBGCEX_BUILD_SCRIPT=...     Helper script used to build the local FunBGCeX SIF
  BRAKER_IMAGE_URI=...          Source URI for BRAKER3 image (default: ${BRAKER_IMAGE_URI})
  FUNANNOTATE_IMAGE_URI=...     Baked funannotate image URI for Docker mode (default: ${FUNANNOTATE_IMAGE_URI})
  FUNANNOTATE_BASE_IMAGE_URI=... Upstream base used by the one-time bake (default: ${FUNANNOTATE_BASE_IMAGE_URI})
  AUTO_BUILD_FUNANNOTATE_SIF=0|1 Accepted compatibility input; jobs never build (default: ${AUTO_BUILD_FUNANNOTATE_SIF})
  AUTO_BUILD_FUNANNOTATE_DOCKER=0|1 Accepted compatibility input; jobs never build (default: ${AUTO_BUILD_FUNANNOTATE_DOCKER})
  FUNANNOTATE_BUILD_SCRIPT=...  Helper script used to bake funannotate DBs into the local runtime
  FUNBGCEX_BOOTSTRAP=0|1        Accepted compatibility input; jobs never create a venv (default: ${FUNBGCEX_BOOTSTRAP})
  FUNBGCEX_VERSION=...          FunBGCeX version for the advanced host bootstrap path (default: ${FUNBGCEX_VERSION})
EOF
}

GENOMES=""
CPUS_SET_BY_FLAG=0
THREADS_SET_BY_FLAG=0
while getopts "fht:c:w:p:g:" opt; do
  case "${opt}" in
    f) FORCE=1 ;;
    t) THREADS="${OPTARG}"; THREADS_SET_BY_FLAG=1 ;;
    c) CPUS="${OPTARG}"; CPUS_SET_BY_FLAG=1; CPUS_REQUEST_EXPLICIT=1 ;;
    w) WORKERS="${OPTARG}" ;;
    p) GENOME_PARALLELISM="${OPTARG}" ;;
    g) GENOMES="${OPTARG}" ;;
    h) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done
if [[ "${CPUS_SET_BY_FLAG}" -eq 0 && "${THREADS_SET_BY_FLAG}" -eq 1 ]]; then
  CPUS="${THREADS}"
  CPUS_REQUEST_EXPLICIT=1
fi
case "${PIPELINE_RESOURCE_MODE}" in
  manual|conservative) PIPELINE_RESOURCE_MODE="conservative" ;;
  auto) ;;
  *) die "PIPELINE_RESOURCE_MODE must be conservative/manual or auto; got '${PIPELINE_RESOURCE_MODE}'" ;;
esac
CPUS="$(positive_int_or_default "${CPUS}" 6)"
THREADS="$(positive_int_or_default "${THREADS}" "${CPUS}")"
WORKERS="$(positive_int_or_default "${WORKERS}" 2)"
ANNO_CPUS="$(positive_int_or_default "${ANNO_CPUS}" 6)"
GENOME_PARALLELISM="$(positive_int_or_default "${GENOME_PARALLELISM}" 1)"
ANTISMASH_RECORD_PARALLELISM="$(positive_int_or_default "${ANTISMASH_RECORD_PARALLELISM}" 1)"
ANTISMASH_SHARD_CPUS_REQUESTED="${ANTISMASH_SHARD_CPUS}"
ANTISMASH_LEGACY_CPUS_REQUESTED="${ANTISMASH_LEGACY_CPUS}"
CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS="$(positive_int_or_default "${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}" 1)"
export OMP_NUM_THREADS="${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
export OPENBLAS_NUM_THREADS="${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
export MKL_NUM_THREADS="${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
export NUMEXPR_NUM_THREADS="${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
export VECLIB_MAXIMUM_THREADS="${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
export BLIS_NUM_THREADS="${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
case "${ANTISMASH_RETAIN_SHARD_WORK}" in
  1) ;;
  *) ANTISMASH_RETAIN_SHARD_WORK=0 ;;
esac

###############################################################################
# Preconditions
###############################################################################
[[ -d "${PROJECT_DIR}" ]] || die "PROJECT_DIR not found: ${PROJECT_DIR}"
[[ -d "${FUNGI_GENOME_ROOT}" ]] || die "FUNGI_GENOME_ROOT not found: ${FUNGI_GENOME_ROOT}"
[[ -d "${BACTERIA_GENOME_ROOT}" ]] || die "BACTERIA_GENOME_ROOT not found: ${BACTERIA_GENOME_ROOT}"
[[ -s "${ANTISMASH_SHARD_COMPACTOR}" ]] || die "antiSMASH shard compactor not found: ${ANTISMASH_SHARD_COMPACTOR}"
[[ -s "${ANTISMASH_INPUT_PREPARER}" ]] || die "antiSMASH input preparer not found: ${ANTISMASH_INPUT_PREPARER}"
[[ -s "${ANNOTATION_GENBANK_HELPER}" ]] || die "annotation GenBank helper not found: ${ANNOTATION_GENBANK_HELPER}"
[[ -s "${ANNOTATION_RUNTIME_HELPER}" ]] || die "annotation runtime helper not found: ${ANNOTATION_RUNTIME_HELPER}"
[[ -s "${BACTERIAL_GENBANK_SANITIZER}" ]] || die "bacterial GenBank sanitizer not found: ${BACTERIAL_GENBANK_SANITIZER}"
[[ -s "${ANNOTATION_INPUT_HELPER}" ]] || die "annotation input helper not found: ${ANNOTATION_INPUT_HELPER}"
[[ -s "${GENBANK_TRANSLATION_CHECKER}" ]] || die "GenBank translation checker not found: ${GENBANK_TRANSLATION_CHECKER}"

load_taxon_routes
persist_taxon_routes
ensure_primary_tooling

log "Run started: PID $$"
log "ENGINE=${ENGINE}"
log "PROJECT_DIR=${PROJECT_DIR}"
log "FUNGI_GENOME_ROOT=${FUNGI_GENOME_ROOT}"
log "BACTERIA_GENOME_ROOT=${BACTERIA_GENOME_ROOT}"
log "GENOME_TAXON_MANIFEST=${GENOME_TAXON_MANIFEST} active=${ROUTE_MANIFEST_ACTIVE}"
log "RESULTS_ROOT=${RESULTS_ROOT}"
log "BIND_ARGS=${BIND_ARGS[*]}"
log "ANTISMASH_SIF=${ANTISMASH_SIF}"
log "FUNBGCEX_SIF=${FUNBGCEX_SIF}"
log "FUNBGCEX_DEF=${FUNBGCEX_DEF}"
log "FUNBGCEX_DOCKERFILE=${FUNBGCEX_DOCKERFILE}"
log "FUNBGCEX_BUILD_SCRIPT=${FUNBGCEX_BUILD_SCRIPT}"
log "ANTISMASH_IMAGE_URI=${ANTISMASH_IMAGE_URI}"
log "FUNBGCEX_IMAGE_URI=${FUNBGCEX_IMAGE_URI:-unset}"
log "FUNBGCEX_RUNTIME=${FUNBGCEX_RUNTIME}"
log "AUTO_BUILD_FUNBGCEX_SIF=${AUTO_BUILD_FUNBGCEX_SIF} FUNBGCEX_BOOTSTRAP=${FUNBGCEX_BOOTSTRAP} FUNBGCEX_VERSION=${FUNBGCEX_VERSION}"
log "BRAKER_SIF=${BRAKER_SIF} FUNANNOTATE_SIF=${FUNANNOTATE_SIF}"
log "FUNANNOTATE_IMAGE_URI=${FUNANNOTATE_IMAGE_URI} FUNANNOTATE_BASE_IMAGE_URI=${FUNANNOTATE_BASE_IMAGE_URI}"
log "FUNANNOTATE_BUILD_SCRIPT=${FUNANNOTATE_BUILD_SCRIPT} AUTO_BUILD_FUNANNOTATE_SIF=${AUTO_BUILD_FUNANNOTATE_SIF} AUTO_BUILD_FUNANNOTATE_DOCKER=${AUTO_BUILD_FUNANNOTATE_DOCKER}"
log "RESOURCE_REQUEST mode=${PIPELINE_RESOURCE_MODE} cpus=${CPUS} cpus_explicit=${CPUS_REQUEST_EXPLICIT} genome_parallelism=${GENOME_PARALLELISM} anno_cpus=${ANNO_CPUS} funbgcex_workers=${WORKERS} antismash_record_parallelism=${ANTISMASH_RECORD_PARALLELISM} antismash_shard_cpus=${ANTISMASH_SHARD_CPUS_REQUESTED:-auto} antismash_legacy_cpus=${ANTISMASH_LEGACY_CPUS_REQUESTED:-auto}"
log "RESOURCE_DOCKER_LIMITS cpus=${CLUSTERWEAVE_TOOL_DOCKER_CPUS:-unset} memory=${CLUSTERWEAVE_TOOL_DOCKER_MEMORY:-unset} pids=${CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT:-unset} numeric_library_threads=${CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS}"
log "AUTO_PULL_IMAGES=${AUTO_PULL_IMAGES} ANTISMASH_RETAIN_SHARD_WORK=${ANTISMASH_RETAIN_SHARD_WORK}"
log "ANNOTATION_FALLBACK_ORDER=${ANNOTATION_FALLBACK_ORDER}"
log "BRAKER3_ENABLED=${BRAKER3_ENABLED}"
log "FORCE=${FORCE} THREADS=${THREADS}"
if [[ "${HAS_FUNGAL_ROUTES}" -eq 1 ]]; then
  log "Converter python: ${VENV_PY}"
  log "Converter script: ${CONVERT_PY}"
fi
log "WORK_ROOT=${WORK_ROOT}"

ANT_FLAGS_ARRAY=()
log "Detecting supported antiSMASH flags..."
if [[ "${HAS_FUNGAL_ROUTES}" == "1" || "${HAS_BACTERIAL_ROUTES}" == "1" ]]; then
  mapfile -t ANT_FLAGS_ARRAY < <(antismash_supported_flags fungi none)
fi
if [[ ${#ANT_FLAGS_ARRAY[@]} -eq 0 ]]; then
  log "antiSMASH flags enabled: none"
else
  log "antiSMASH flags enabled: ${ANT_FLAGS_ARRAY[*]}"
fi

###############################################################################
# Determine genomes to process
###############################################################################
if [[ -z "${GENOMES}" ]]; then
  log "No genomes specified with -g; discovering from the canonical taxon manifest or fungal compatibility root"
  mapfile -t GEN_ARR < <(discover_stems)
  [[ ${#GEN_ARR[@]} -gt 0 ]] || die "No routed genome inputs found"
else
  IFS=',' read -r -a GEN_ARR <<< "${GENOMES}"
fi
if [[ "${ROUTE_MANIFEST_ACTIVE}" -eq 1 ]]; then
  for genome_id in "${GEN_ARR[@]}"; do
    [[ -n "${ROUTE_TAXON_BY_GENOME[${genome_id}]+set}" ]] \
      || die "Requested genome is absent from immutable taxon manifest: ${genome_id}"
  done
fi
log "Genomes to process ($((${#GEN_ARR[@]}))): $(join_by ', ' "${GEN_ARR[@]}")"
taxon_summary_fungi=0
taxon_summary_bacteria=0
taxon_summary_unresolved=0
for genome_id in "${GEN_ARR[@]}"; do
  case "$(route_taxon_for_genome "${genome_id}")" in
    fungi) taxon_summary_fungi=$((taxon_summary_fungi + 1)) ;;
    bacteria) taxon_summary_bacteria=$((taxon_summary_bacteria + 1)) ;;
    *) taxon_summary_unresolved=$((taxon_summary_unresolved + 1)) ;;
  esac
done
log "TAXON_SUMMARY scope=${ANALYSIS_SCOPE} fungi=${taxon_summary_fungi} bacteria=${taxon_summary_bacteria} unresolved=${taxon_summary_unresolved}"

prepare_annotation_tooling "${GEN_ARR[@]}"
freeze_resource_plan "${#GEN_ARR[@]}"

###############################################################################
# Main loop
###############################################################################
total=0; dropped=0; processed=0
MANIFEST_ROW_DIR="${WORK_ROOT}/tmp/manifest_rows"
if [[ -d "${MANIFEST_ROW_DIR}" ]]; then
  mv "${MANIFEST_ROW_DIR}" "${MANIFEST_ROW_DIR}.previous.$(date -u +%Y%m%dT%H%M%S).$$"
fi
mkdir -p "${MANIFEST_ROW_DIR}"
MANIFEST_ROW_FILES=()

write_genome_manifest_row() {
  local row_file="$1"
  shift
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$@" > "${row_file}.tmp"
  mv "${row_file}.tmp" "${row_file}"
}

compute_genome() {
  local genome_id="$1"
  local ordinal="$2"
  local row_file="$3"
  local total_genomes="$4"
  local GENLOG fasta gb_src staged_gbk ant_out fbx_out ant_err ant_stdout fbx_err fbx_stdout
  local gbk_used gbk_status antismash_status funbgcex_status ant_done fbx_done
  local per_tmp ant_filtered_input ant_input antismash_input_sanitized ant_sanitize_summary
  local antismash_duplicate_cds_dropped antismash_invalid_non_cds_dropped antismash_codon_start_removed
  local fbx_input antismash_record_ids_file antismash_record_count antismash_record_ids_stable antismash_shard_root antismash_run_mode antismash_run_ok
  local taxon_group taxon_source route_status prediction_method detector_profile funbgcex_applicability genome_input_root
  local GENOME_ROOT GENOME_MAPPING_FILE
  local -a antismash_record_ids=()
  local -a ANT_FLAGS_ARRAY=()
  taxon_group="$(route_taxon_for_genome "${genome_id}")"
  taxon_source="$(route_source_for_genome "${genome_id}")"
  route_status="$(route_status_for_genome "${genome_id}")"
  genome_input_root="$(route_root_for_genome "${genome_id}")"
  prediction_method="$(route_prediction_for_genome "${genome_id}")"
  detector_profile="$(route_detector_for_genome "${genome_id}")"
  GENOME_ROOT="${genome_input_root}"
  GENOME_MAPPING_FILE="$(mapping_file_for_taxon "${taxon_group}")"
  if [[ "${taxon_group}" == "plants" ]]; then
    prediction_method="existing_cds"
    detector_profile="plantismash"
    funbgcex_applicability="not_applicable_taxon"
  elif [[ "${taxon_group}" == "bacteria" ]]; then
    prediction_method="prodigal"
    detector_profile="antismash"
    funbgcex_applicability="not_applicable_taxon"
    mapfile -t ANT_FLAGS_ARRAY < <(antismash_supported_flags bacteria prodigal)
  else
    funbgcex_applicability="applicable"
    mapfile -t ANT_FLAGS_ARRAY < <(antismash_supported_flags fungi none)
  fi
  log "===================================================================="
  log "[${ordinal}/${total_genomes}] genome=${genome_id} taxon=${taxon_group} prediction=${prediction_method}"
  log "TAXON_ROUTE genome=${genome_id} taxon=${taxon_group} source=${taxon_source} status=${route_status} message=\"prediction=${prediction_method} detector=${detector_profile}\""

  GENLOG="${WORK_ROOT}/logs/${genome_id}.log"
  : > "${GENLOG}"
  genome_stage_progress "${genome_id}" "annotation" 0 "Preparing genome ${ordinal}/${total_genomes}"

  fasta=""
  if ! fasta="$(resolve_fasta_for_stem "${genome_id}")"; then
    if [[ "${taxon_group}" == "fungi" ]]; then
      warn "${genome_id}: no FASTA found; cannot run annotation fallback tools. Will only proceed if an annotated GBK exists."
    fi
  fi

  gb_src=""
  if gb_src="$(resolve_genbank_for_stem "${genome_id}")"; then :; else gb_src=""; fi

  staged_gbk="${RESULTS_ROOT}/input_gbks/${genome_id}.gbk"
  ant_out="${RESULTS_ROOT}/antismash/${genome_id}"
  fbx_out="${RESULTS_ROOT}/funbgcex/${genome_id}"

  ant_err="${WORK_ROOT}/logs/${genome_id}.antismash.stderr.log"
  ant_stdout="${WORK_ROOT}/logs/${genome_id}.antismash.stdout.log"
  fbx_err="${WORK_ROOT}/logs/${genome_id}.funbgcex.stderr.log"
  fbx_stdout="${WORK_ROOT}/logs/${genome_id}.funbgcex.stdout.log"

  if [[ "${FORCE}" == "1" ]]; then
    rm -f "${staged_gbk}" 2>/dev/null || true
    rm -rf "${ant_out}" 2>/dev/null || true
    rm -rf "${fbx_out}" 2>/dev/null || true
    rm -rf "${RESULTS_ROOT}/braker3/${genome_id}" 2>/dev/null || true
    rm -rf "${RESULTS_ROOT}/funannotate/${genome_id}" 2>/dev/null || true

    # Fresh per-genome work cache cleanup under /tmp
    rm -rf "${WORK_ROOT}/tmp/${genome_id}" 2>/dev/null || true
    rm -f "${WORK_ROOT}/logs/${genome_id}."* 2>/dev/null || true

  fi

  per_tmp="${WORK_ROOT}/tmp/${genome_id}"
  mkdir -p "${per_tmp}"

  if [[ "${taxon_group}" == "plants" ]]; then
    run_plantismash_genome "${genome_id}" "${gb_src}" "${fasta}" "${staged_gbk}" "${row_file}"
    return $?
  fi

  prepare_genome_genbank "${genome_id}" "${taxon_group}" "${genome_input_root}" \
    "${fasta}" "${gb_src}" "${staged_gbk}" "${per_tmp}" "${GENLOG}"

  antismash_status="skipped"
  if [[ "${taxon_group}" == "bacteria" ]]; then
    funbgcex_status="not_applicable_taxon"
  else
    funbgcex_status="skipped"
  fi

  if [[ -z "${gbk_used}" ]]; then
    warn "${genome_id}: DROPPED (gbk_status=${gbk_status})" | tee -a "${GENLOG}"
    genome_stage_progress "${genome_id}" "annotation" 100 "Dropped: ${gbk_status}"
    write_genome_manifest_row "${row_file}" \
      "${genome_id}" "${fasta}" "" "${gbk_status}" "${antismash_status}" "${funbgcex_status}" \
      "${taxon_group}" "${prediction_method}" "${detector_profile}" "${funbgcex_applicability}"
    sync_logs_genome "${genome_id}"
    return 0
  fi

  ant_done=0; fbx_done=0
  if antismash_done "${ant_out}"; then ant_done=1; fi
  if [[ "${taxon_group}" == "fungi" ]] && funbgcex_done "${fbx_out}"; then fbx_done=1; fi

  if [[ -s "${gbk_used}" && "${ant_done}" -eq 1 ]] \
      && { [[ "${taxon_group}" == "bacteria" ]] || [[ "${fbx_done}" -eq 1 ]]; }; then
    antismash_status="skipped_done"
    if [[ "${taxon_group}" == "fungi" ]]; then
      funbgcex_status="skipped_done"
    fi
    log "${genome_id}: outputs already present in RESULTS_ROOT; skipping genome" | tee -a "${GENLOG}"
    genome_stage_progress "${genome_id}" "annotation" 100 "Outputs already complete"
    write_genome_manifest_row "${row_file}" \
      "${genome_id}" "${fasta}" "${gbk_used}" "${gbk_status}" "${antismash_status}" "${funbgcex_status}" \
      "${taxon_group}" "${prediction_method}" "${detector_profile}" "${funbgcex_applicability}"
    sync_logs_genome "${genome_id}"
    return 0
  fi

  if [[ "${taxon_group}" == "fungi" ]]; then
    log "${genome_id}: DIAG gbk_used summary" | tee -a "${GENLOG}"
    gbk_diag_summary "${gbk_used}" "gbk_used" | tee -a "${GENLOG}"

    ant_filtered_input="${per_tmp}/${genome_id}.antismash.filtered.gbk"
    ant_input="${per_tmp}/${genome_id}.antismash.gbk"
    antismash_input_sanitized=0
    log "${genome_id}: filtering GBK to drop gene-less records for antiSMASH" | tee -a "${GENLOG}"
    filter_gbk_drop_gene_less_records "${gbk_used}" "${ant_filtered_input}" | tee -a "${GENLOG}"

    log "${genome_id}: sanitizing antiSMASH-only GenBank features" | tee -a "${GENLOG}"
    ant_sanitize_summary="$(sanitize_antismash_duplicate_cds_locations "${ant_filtered_input}" "${ant_input}" "${genome_id}")" || {
      warn "${genome_id}: antiSMASH input sanitizer failed; using gene-less-filtered GBK unchanged" | tee -a "${GENLOG}"
      cp -f "${ant_filtered_input}" "${ant_input}"
      ant_sanitize_summary="${genome_id}: antismash_input_duplicate_cds_locations sanitizer_failed=1 dropped_duplicate_cds=0"
    }
    printf '%s\n' "${ant_sanitize_summary}" | tee -a "${GENLOG}"
    antismash_duplicate_cds_dropped="$(printf '%s\n' "${ant_sanitize_summary}" | sed -nE 's/.*dropped_duplicate_cds[^0-9]*([0-9]+).*/\1/p' | head -n1)"
    antismash_invalid_non_cds_dropped="$(printf '%s\n' "${ant_sanitize_summary}" | sed -nE 's/.*dropped_invalid_non_cds_compound_features[^0-9]*([0-9]+).*/\1/p' | head -n1)"
    antismash_codon_start_removed="$(printf '%s\n' "${ant_sanitize_summary}" | sed -nE 's/.*removed_unsafe_codon_start_qualifiers[^0-9]*([0-9]+).*/\1/p' | head -n1)"
    if [[ "${antismash_duplicate_cds_dropped:-0}" -gt 0 \
        || "${antismash_invalid_non_cds_dropped:-0}" -gt 0 \
        || "${antismash_codon_start_removed:-0}" -gt 0 ]]; then
      antismash_input_sanitized=1
    fi

    log "${genome_id}: DIAG ant_input summary" | tee -a "${GENLOG}"
    gbk_diag_summary "${ant_input}" "ant_input" | tee -a "${GENLOG}"

    fbx_input="${per_tmp}/${genome_id}.funbgcex.gbk"
    cp -f "${ant_filtered_input}" "${fbx_input}"
  fi

  # ---------------- antiSMASH ----------------
  if [[ "${ant_done}" -eq 1 ]]; then
    antismash_status="skipped_done"
    log "${genome_id}: antiSMASH already done -> ${ant_out}" | tee -a "${GENLOG}"
    genome_stage_progress "${genome_id}" "antismash" 70 "antiSMASH already complete"
  else
    rm -rf "${ant_out}" 2>/dev/null || true
    mkdir -p "${ant_out}"

    log "${genome_id}: running antiSMASH (outdir=${ant_out})" | tee -a "${GENLOG}"
    genome_stage_progress "${genome_id}" "antismash" 35 "Running antiSMASH"
    : > "${ant_stdout}"
    : > "${ant_err}"

    antismash_record_ids=()
    antismash_record_ids_stable=0
    if [[ "${taxon_group}" == "bacteria" ]]; then
      mapfile -t antismash_record_ids < "${antismash_record_ids_file}"
      if antismash_record_ids_are_stable "${antismash_record_ids_file}" 2>> "${ant_err}"; then
        antismash_record_ids_stable=1
      else
        warn "${genome_id}: bacterial sanitizer emitted an unstable antiSMASH record ID; using legacy single-run mode" | tee -a "${GENLOG}"
      fi
    else
      antismash_record_ids_file="${per_tmp}/antismash_record_ids.txt"
      if list_genbank_record_ids "${ant_input}" "${ANTISMASH_MIN_RECORD_BP}" > "${antismash_record_ids_file}" 2>> "${ant_err}"; then
        mapfile -t antismash_record_ids < "${antismash_record_ids_file}"
        if antismash_record_ids_are_stable "${antismash_record_ids_file}" 2>> "${ant_err}"; then
          antismash_record_ids_stable=1
        else
          antismash_unstable_record_display="$(tool_activity_clean_line "${ANTISMASH_UNSTABLE_RECORD_ID}")"
          antismash_unstable_record_display="${antismash_unstable_record_display//\"/ }"
          antismash_unstable_safe_display="$(tool_activity_clean_line "${ANTISMASH_UNSTABLE_SAFE_ID}")"
          antismash_unstable_safe_display="${antismash_unstable_safe_display//\"/ }"
          warn "ANTISMASH_RECORD_SHARD_FALLBACK genome=${genome_id} reason=record_id_not_output_basename_stable record=\"${antismash_unstable_record_display}\" output_basename=\"${antismash_unstable_safe_display}\" message=\"Using legacy single-run mode to preserve record identity\"" | tee -a "${GENLOG}"
        fi
      else
        warn "${genome_id}: could not list antiSMASH record IDs; using legacy single-run mode" | tee -a "${GENLOG}"
        : > "${antismash_record_ids_file}"
      fi
    fi
    antismash_record_count="${#antismash_record_ids[@]}"
    antismash_shard_root="${per_tmp}/antismash_shards"
    antismash_run_mode="legacy"
    # One slot runs the same record shards sequentially; only scheduling changes.
    if [[ "${antismash_record_count}" -gt 1 && "${antismash_record_ids_stable}" -eq 1 ]]; then
      antismash_run_mode="sharded"
    fi

    antismash_run_ok=0
    if [[ "${antismash_run_mode}" == "sharded" ]]; then
      log "${genome_id}: antiSMASH record sharding enabled records=${antismash_record_count} parallelism=${ANTISMASH_RECORD_PARALLELISM} shard_cpus=${ANTISMASH_SHARD_CPUS} shard_root=${antismash_shard_root}" | tee -a "${GENLOG}"
      if run_antismash_sharded \
          "${genome_id}" "${ant_input}" "${ant_out}" "${antismash_record_ids_file}" \
          "${antismash_shard_root}" "${ant_stdout}" "${ant_err}"; then
        antismash_run_ok=1
      fi
    else
      log "${genome_id}: antiSMASH legacy single-run mode records=${antismash_record_count} record_parallelism=${ANTISMASH_RECORD_PARALLELISM} legacy_cpus=${ANTISMASH_LEGACY_CPUS}" | tee -a "${GENLOG}"
      if CLUSTERWEAVE_CHILD_DOCKER_CPUS="${ANTISMASH_LEGACY_CPUS}" run_tool_with_activity "${genome_id}" "antismash" "detect" "${ant_stdout}" "${ant_err}" antismash_exec antismash \
          "${ant_input}" \
          --minlength "${ANTISMASH_MIN_RECORD_BP}" \
          --output-dir "${ant_out}" \
          --cpus "${ANTISMASH_LEGACY_CPUS}" \
          "${ANT_FLAGS_ARRAY[@]}"; then
        antismash_run_ok=1
      fi
    fi

    if [[ "${antismash_run_ok}" -eq 1 ]] && mark_antismash_done "${ant_out}"; then
      if [[ "${antismash_input_sanitized:-0}" -eq 1 ]]; then
        antismash_status="ran_ok_sanitized"
      else
        antismash_status="ran_ok"
      fi
      log "${genome_id}: antiSMASH OK" | tee -a "${GENLOG}"
      genome_stage_progress "${genome_id}" "antismash" 70 "antiSMASH complete"
    else
      antismash_status="failed"
      warn "${genome_id}: antiSMASH FAILED (see ${ant_err})" | tee -a "${GENLOG}"
      antismash_failure_message="$(antismash_public_failure_message "${ant_err}")"
      genome_stage_progress "${genome_id}" "antismash" 70 "${antismash_failure_message}"
    fi
  fi

  # ---------------- FunBGCeX ----------------
  if [[ "${taxon_group}" == "bacteria" ]]; then
    funbgcex_status="not_applicable_taxon"
    log "${genome_id}: FunBGCeX not applicable to bacterial route; skipping." | tee -a "${GENLOG}"
    case "${antismash_status}" in
      ran_ok|ran_ok_sanitized|skipped_done)
        genome_stage_progress "${genome_id}" "antismash" 100 "BGC detection complete"
        ;;
      failed)
        # Bacteria have no downstream FunBGCeX stage that could provide a
        # terminal marker. Keep the lane terminal without replacing the
        # actual antiSMASH failure with a misleading success message.
        antismash_failure_message="$(antismash_public_failure_message "${ant_err}")"
        genome_stage_progress "${genome_id}" "antismash" 100 "${antismash_failure_message}"
        ;;
      *)
        warn "${genome_id}: antiSMASH ended with unexpected status=${antismash_status}" | tee -a "${GENLOG}"
        genome_stage_progress "${genome_id}" "antismash" 100 "antiSMASH failed"
        ;;
    esac
  else
    run_funbgcex_detection "${genome_id}" "${fbx_done}" "${fbx_input}" "${fbx_out}" \
      "${per_tmp}" "${fbx_stdout}" "${fbx_err}" "${GENLOG}" funbgcex_status
  fi

  write_genome_manifest_row "${row_file}" \
    "${genome_id}" "${fasta}" "${gbk_used}" "${gbk_status}" "${antismash_status}" "${funbgcex_status}" \
    "${taxon_group}" "${prediction_method}" "${detector_profile}" "${funbgcex_applicability}"

  if [[ "${antismash_status}" == "failed" || "${funbgcex_status}" == "failed" ]]; then
    genome_stage_progress "${genome_id}" "annotation" 100 "Genome workflow complete with warning"
  else
    genome_stage_progress "${genome_id}" "annotation" 100 "Genome workflow complete"
  fi
  sync_logs_genome "${genome_id}"
  return 0

}

# Freeze dependency content once per annotation stage. File stamps below are
# mutation guards; they are never used as cache identity.
ACCESSION_CONTEXT="${WORK_ROOT}/tmp/accession-cache-context.json"
rm -f "${ACCESSION_CONTEXT}"
if [[ -n "${CLUSTERWEAVE_ACCESSION_CACHE_ROOT:-}" && "${ENGINE}" == "docker" \
    && "${FORCE}" != "1" && "${CLUSTERWEAVE_ACCESSION_CACHE_FORCE_MISS:-0}" != "1" ]]; then
  cache_settings=()
  for setting in ENGINE VENV_PY CPUS THREADS WORKERS ANNO_CPUS GENOME_PARALLELISM \
      ANTISMASH_RECORD_PARALLELISM ANTISMASH_SHARD_CPUS ANTISMASH_LEGACY_CPUS \
      ANTISMASH_RETAIN_SHARD_WORK ANTISMASH_MIN_RECORD_BP ANTISMASH_MAX_RECORD_BP \
      ANNOTATION_FALLBACK_ORDER BRAKER3_ENABLED BRAKER_SPECIES_PREFIX \
      FUNANNOTATE_ORGANISM_NAME FUNANNOTATE_BUSCO_DB FUNANNOTATE_BUSCO_SEED_SPECIES \
      FUNANNOTATE_BUSCO_DB_DEFAULT FUNANNOTATE_BUSCO_DB_FUNGI FUNANNOTATE_BUSCO_DB_DIKARYA \
      FUNANNOTATE_BUSCO_DB_MUCOROMYCOTA FUNANNOTATE_BUSCO_DB_MUCORALES \
      FUNANNOTATE_BUSCO_DB_MICROSPORIDIA FUNANNOTATE_BUSCO_DB_ASCOMYCOTA \
      FUNANNOTATE_BUSCO_DB_BASIDIOMYCOTA FUNANNOTATE_BUSCO_DB_NO_TAXONOMY \
      FUNANNOTATE_RETRY_WITHOUT_PROTEIN_EVIDENCE FUNANNOTATE_MIN_TRAINING_MODELS_FALLBACK \
      FUNANNOTATE_DB BRAKER_BAM BRAKER_PROT_SEQ CLUSTERWEAVE_TOOL_DOCKER_CPUS \
      CLUSTERWEAVE_TOOL_DOCKER_MEMORY CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT \
      CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS OMP_NUM_THREADS OPENBLAS_NUM_THREADS \
      MKL_NUM_THREADS NUMEXPR_NUM_THREADS VECLIB_MAXIMUM_THREADS BLIS_NUM_THREADS \
      LANG LC_ALL TZ PYTHONHASHSEED SOURCE_DATE_EPOCH ANTISMASH_DB_DIR HAS_FUNGAL_ROUTES \
      FUNGAL_ANNOTATION_FALLBACK_NEEDED FUNBGCEX_RUNTIME FUNBGCEX_DOCKER_IMAGE \
      FUNANNOTATE_IMAGE_URI ANTISMASH_DOCKER_IMAGE; do
    cache_settings+=(--setting "${setting}" "${!setting-}")
  done
  # Custom execution helpers remain eligible for ordinary computation only.
  if [[ "${ANNOTATION_GENBANK_HELPER}" == "${SCRIPT_DIR}/bin/annotation_genbank.py" \
      && "${BACTERIAL_GENBANK_SANITIZER}" == "${SCRIPT_DIR}/bin/sanitize_bacterial_genbank.py" \
      && "${ANNOTATION_RUNTIME_HELPER}" == "${SCRIPT_DIR}/bin/annotation_runtime.py" \
      && "${ANNOTATION_INPUT_HELPER}" == "${SCRIPT_DIR}/bin/annotation_input.py" \
      && "${ANTISMASH_SHARD_COMPACTOR}" == "${SCRIPT_DIR}/bin/compact_antismash_shard.py" \
      && "${ANTISMASH_WEB_RESULTS_PREPARER}" == "${SCRIPT_DIR}/bin/prepare_antismash_web_results.py" \
      && "${ANTISMASH_INPUT_PREPARER}" == "${SCRIPT_DIR}/bin/prepare_antismash_input.py" ]] \
      && [[ "${CONVERT_PY}" == "${SCRIPT_DIR}/bin/gff3_to_gbk_with_translations.py" ]] \
      && "$(resolve_python_cmd)" "${SCRIPT_DIR}/bin/cached_accession.py" context \
          --output "${ACCESSION_CONTEXT}" "${cache_settings[@]}"; then
    # Execute sibling tools by the exact immutable IDs recorded in the context.
    while IFS=$'\t' read -r tool digest; do
      case "${tool}" in
        funbgcex) FUNBGCEX_DOCKER_IMAGE="sha256:${digest}" ;;
        funannotate) FUNANNOTATE_IMAGE_URI="docker://sha256:${digest}" ;;
        antismash) ANTISMASH_DOCKER_IMAGE="sha256:${digest}" ;;
      esac
    done < <("$(resolve_python_cmd)" -c 'import json,sys; print("\n".join(k+"\t"+v for k,v in json.load(open(sys.argv[1]))["images"].items()))' "${ACCESSION_CONTEXT}")
  fi
fi

process_genome() (
  # A subshell owns this key's claim through computation and atomic population.
  local genome_id="$1" row_file="$3" cache_claim="" cache_fd cache_rc=0
  local taxon="$(route_taxon_for_genome "$1")"
  local input_root="$(route_root_for_genome "$1")"
  if [[ "${taxon}" == "plants" ]]; then
    compute_genome "$@"
    return $?
  fi
  local state="${WORK_ROOT}/tmp/${genome_id}.accession-cache-state.json"
  local provenance="${RESULTS_ROOT}/reproducibility/accession_cache/${genome_id}.detection.json"
  local -a adapter=("$(resolve_python_cmd)" "${SCRIPT_DIR}/bin/cached_accession.py")
  local -a args=(--genome-id "${genome_id}" --taxon "${taxon}" \
    --route-manifest "${GENOME_TAXON_MANIFEST}" --acquired-root "${input_root}" \
    --mapping "$(mapping_file_for_taxon "${taxon}")" --results "${RESULTS_ROOT}" \
    --work "${WORK_ROOT}" --row "${row_file}" --provenance "${provenance}" \
    --context "${ACCESSION_CONTEXT}" --state "${state}")
  if [[ -n "${CLUSTERWEAVE_ACCESSION_CACHE_ROOT:-}" ]]; then
    cache_claim="$(FORCE="${FORCE}" "${adapter[@]}" prepare "${args[@]}")" || cache_claim=""
  fi
  if [[ -n "${cache_claim}" ]]; then
    if ! have flock; then cache_claim=""; fi
  fi
  if [[ -n "${cache_claim}" ]]; then
    exec {cache_fd}<>"${cache_claim}"
    local attempts=0
    until flock -x -w 1 "${cache_fd}"; do
      [[ -z "${CLUSTERWEAVE_CANCEL_FILE:-}" || ! -e "${CLUSTERWEAVE_CANCEL_FILE}" ]] || return 1
      attempts=$((attempts + 1))
      if [[ "${attempts}" -ge 3600 ]]; then cache_claim=""; break; fi
    done
    if [[ -n "${cache_claim}" ]] && FORCE="${FORCE}" "${adapter[@]}" restore "${args[@]}"; then
      log "ACCESSION_CACHE genome=${genome_id} stage=annotation_detection outcome=hit"
      genome_stage_progress "${genome_id}" "annotation" 100 "Reused verified annotation and BGC detection"
      return 0
    fi
  fi
  compute_genome "$@"
  cache_rc=$?
  if [[ "${cache_rc}" -eq 0 && -n "${cache_claim}" ]]; then
    FORCE="${FORCE}" "${adapter[@]}" publish "${args[@]}" || true
  fi
  return "${cache_rc}"
)

# Each subshell retains an exit receipt even when a helper exits before writing
# its scientific row. Unknown failures remain ineligible for continuation.
finish_genome_task() {
  local rc="$1" genome="$2" row="$3"
  trap - EXIT
  if [[ ! -s "${row}" ]]; then
    write_genome_manifest_row "${row}" "${genome}" "" "" "unclassified_failure" \
      "blocked" "blocked" "$(route_taxon_for_genome "${genome}")" \
      "$(route_prediction_for_genome "${genome}")" "$(route_detector_for_genome "${genome}")" "unknown"
    rc=1
  fi
  printf '%s\n' "${rc}" > "${row}.exit.tmp"
  mv "${row}.exit.tmp" "${row}.exit"
  sync_logs_genome "${genome}"
  exit "${rc}"
}
run_genome_task() (
  trap 'finish_genome_task "$?" "$1" "$3"' EXIT
  process_genome "$@"
)
idx=0
genome_job_failure=0
genome_pids=()
for genome_id in "${GEN_ARR[@]}"; do
  idx=$((idx + 1))
  row_file="${MANIFEST_ROW_DIR}/$(printf '%06d' "${idx}").tsv"
  MANIFEST_ROW_FILES+=("${row_file}")
  run_genome_task "${genome_id}" "${idx}" "${row_file}" "${#GEN_ARR[@]}" &
  genome_pids+=("$!")
  while [[ "$(running_genome_job_count)" -ge "${GENOME_PARALLELISM}" ]]; do
    if ! wait_for_genome_job; then genome_job_failure=1; fi
  done
done
# wait -n may observe only a subset of already exited children. Explicit waits
# bind every scheduled genome, including failures that finished between polls.
for genome_pid in "${genome_pids[@]}"; do
  if ! wait "${genome_pid}"; then genome_job_failure=1; fi
done

if [[ "${HAS_PLANT_ROUTES}" == "1" ]]; then
  repository_helper_python_exec "${SCRIPT_DIR}/bin/plantismash_runtime.py" collect --results "${RESULTS_ROOT}" || genome_job_failure=1
fi

detector_failure=0
for row_file in "${MANIFEST_ROW_FILES[@]}"; do
  [[ -s "${row_file}" ]] || die "Missing per-genome manifest row: ${row_file}"
  cat "${row_file}" >> "${MANIFEST}"
  row_line="$(<"${row_file}")"
  IFS=$'\034' read -r \
    row_genome row_fasta row_gbk row_gbk_status row_antismash row_funbgcex \
    row_taxon row_prediction row_detector row_funbgcex_applicability \
    <<< "${row_line//$'\t'/$'\034'}" || true
  if [[ "${row_antismash}" == "failed" || "${row_funbgcex}" == "failed" ]]; then
    detector_failure=1
  fi
  total=$((total + 1))
  if [[ -n "${row_gbk:-}" ]]; then
    processed=$((processed + 1))
  else
    dropped=$((dropped + 1))
  fi
done
rsync -a "${MANIFEST}" "${RESULTS_ROOT}/summary_tables/" >/dev/null 2>&1 || true

if [[ -d "${RESULTS_ROOT}/reproducibility/genome_attempts" ]]; then
  mv "${RESULTS_ROOT}/reproducibility/genome_attempts" "${RESULTS_ROOT}/reproducibility/genome_attempts.previous.$(date -u +%Y%m%dT%H%M%S).$$"
fi
mkdir -p "${RESULTS_ROOT}/reproducibility/genome_attempts"
cp "${MANIFEST_ROW_DIR}"/*.tsv "${MANIFEST_ROW_DIR}"/*.exit "${RESULTS_ROOT}/reproducibility/genome_attempts/"
rsync -a "${WORK_ROOT}/logs/" "${RESULTS_ROOT}/logs/" >/dev/null 2>&1 || true

if [[ "${genome_job_failure}" -ne 0 || "${detector_failure}" -ne 0 ]]; then
  die "Required BGC detection failed; partial outputs and run manifest retained. See ${WORK_ROOT}/logs"
fi

log "Complete."
log "summary_tables: ${RESULTS_ROOT}/summary_tables"
log "manifest: ${MANIFEST}"
log "total=${total} processed=${processed} dropped=${dropped}"
rsync -a "${WORK_ROOT}/logs/" "${RESULTS_ROOT}/logs/" >/dev/null 2>&1 || true
log "Logs synced to: ${RESULTS_ROOT}/logs"
