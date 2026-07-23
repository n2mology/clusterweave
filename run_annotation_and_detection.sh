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
  "${ENGINE}" exec "${BIND_ARGS[@]}" "${image}" "$@"
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
  if annotation_prompt_pull "${label}"; then
    log "Pulling ${label} Docker image: ${image}"
    docker pull "${image}" >> "${PIPELOG}" 2>&1 && return 0
    warn "Failed to pull ${label} Docker image: ${image}"
  fi
  return 1
}

antismash_exec() {
  if [[ "${ENGINE}" == "docker" ]]; then
    if have antismash; then
      ANTISMASH_DB_DIR="${ANTISMASH_DB_DIR}" "$@"
    else
      docker_exec "${ANTISMASH_DOCKER_IMAGE}" "$@"
    fi
  else
    sing_exec "${ANTISMASH_SIF}" "$@"
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
  local spec="${1:-}"
  local total=0
  local part=""
  local first=0
  local last=0
  local IFS=','
  local -a parts=()
  read -r -a parts <<< "${spec}"
  for part in "${parts[@]}"; do
    if [[ "${part}" =~ ^([0-9]+)-([0-9]+)$ ]]; then
      first="${BASH_REMATCH[1]}"
      last="${BASH_REMATCH[2]}"
      if [[ "${last}" -ge "${first}" ]]; then
        total=$((total + last - first + 1))
      fi
    elif [[ "${part}" =~ ^[0-9]+$ ]]; then
      total=$((total + 1))
    fi
  done
  printf '%s\n' "${total}"
}

detect_online_cpus() {
  local candidate=""

  if have nproc; then
    # GNU nproc treats OpenMP limits as CPU availability hints.  ClusterWeave
    # intentionally caps numeric libraries (normally to one thread), but that
    # child-library policy must not collapse the job-level resource planner.
    candidate="$(
      unset OMP_NUM_THREADS OMP_THREAD_LIMIT
      nproc 2>/dev/null || true
    )"
  elif have getconf; then
    candidate="$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)"
  fi

  printf '%s\n' "${candidate}"
}

detect_effective_cpus() {
  local cgroup_root="${1:-/sys/fs/cgroup}"
  local effective=0
  local candidate=0
  local quota=""
  local period=""
  local cpuset=""
  local path=""

  candidate="$(detect_online_cpus)"
  if [[ "${candidate}" =~ ^[0-9]+$ && "${candidate}" -ge 1 ]]; then
    effective="${candidate}"
  fi

  for path in "${cgroup_root}/cpuset.cpus.effective" "${cgroup_root}/cpuset/cpuset.cpus"; do
    [[ -r "${path}" ]] || continue
    cpuset="$(<"${path}")"
    candidate="$(count_cpuset_cpus "${cpuset}")"
    if [[ "${candidate}" -ge 1 && ("${effective}" -eq 0 || "${candidate}" -lt "${effective}") ]]; then
      effective="${candidate}"
    fi
    break
  done

  if [[ -r "${cgroup_root}/cpu.max" ]]; then
    read -r quota period < "${cgroup_root}/cpu.max" || true
    if [[ "${quota}" =~ ^[0-9]+$ && "${period}" =~ ^[0-9]+$ && "${period}" -ge 1 ]]; then
      candidate=$((quota / period))
      if [[ "${candidate}" -lt 1 ]]; then candidate=1; fi
      if [[ "${effective}" -eq 0 || "${candidate}" -lt "${effective}" ]]; then
        effective="${candidate}"
      fi
    fi
  elif [[ -r "${cgroup_root}/cpu/cpu.cfs_quota_us" && -r "${cgroup_root}/cpu/cpu.cfs_period_us" ]]; then
    quota="$(<"${cgroup_root}/cpu/cpu.cfs_quota_us")"
    period="$(<"${cgroup_root}/cpu/cpu.cfs_period_us")"
    if [[ "${quota}" =~ ^[0-9]+$ && "${quota}" -ge 1 && "${period}" =~ ^[0-9]+$ && "${period}" -ge 1 ]]; then
      candidate=$((quota / period))
      if [[ "${candidate}" -lt 1 ]]; then candidate=1; fi
      if [[ "${effective}" -eq 0 || "${candidate}" -lt "${effective}" ]]; then
        effective="${candidate}"
      fi
    fi
  fi

  if [[ "${effective}" -lt 1 ]]; then effective=1; fi
  printf '%s\n' "${effective}"
}

detect_effective_memory_mb() {
  local effective=0
  local candidate=0
  local limit=""
  local current=""
  local remaining=0
  local host_available=""

  if [[ -r /proc/meminfo ]]; then
    host_available="$(awk '/^MemAvailable:/ {printf "%d\n", $2 / 1024; exit}' /proc/meminfo)"
    if [[ "${host_available}" =~ ^[0-9]+$ && "${host_available}" -ge 1 ]]; then
      effective="${host_available}"
    fi
  fi

  if [[ -r /sys/fs/cgroup/memory.max ]]; then
    limit="$(</sys/fs/cgroup/memory.max)"
    current="$(</sys/fs/cgroup/memory.current)"
    if [[ "${limit}" =~ ^[0-9]+$ && "${limit}" -lt 1152921504606846976 && "${current}" =~ ^[0-9]+$ ]]; then
      remaining=$((limit - current))
      candidate=$((remaining / 1048576))
      if [[ "${candidate}" -lt 1 ]]; then candidate=1; fi
      if [[ "${effective}" -eq 0 || "${candidate}" -lt "${effective}" ]]; then
        effective="${candidate}"
      fi
    fi
  elif [[ -r /sys/fs/cgroup/memory/memory.limit_in_bytes ]]; then
    limit="$(</sys/fs/cgroup/memory/memory.limit_in_bytes)"
    current="$(</sys/fs/cgroup/memory/memory.usage_in_bytes)"
    if [[ "${limit}" =~ ^[0-9]+$ && "${limit}" -lt 1152921504606846976 && "${current}" =~ ^[0-9]+$ ]]; then
      remaining=$((limit - current))
      candidate=$((remaining / 1048576))
      if [[ "${candidate}" -lt 1 ]]; then candidate=1; fi
      if [[ "${effective}" -eq 0 || "${candidate}" -lt "${effective}" ]]; then
        effective="${candidate}"
      fi
    fi
  fi

  printf '%s\n' "${effective}"
}

freeze_resource_plan() {
  local total_genomes=""
  local requested_cpus="${CPUS}"
  local desired_genome_parallelism="${GENOME_PARALLELISM}"
  local cpu_genome_limit=1
  local memory_genome_limit=1
  local usable_memory_mb=0
  local auto_max_cpus=1
  local auto_max_genomes=1
  local auto_min_cpus_per_genome=1
  local auto_memory_percent=70
  local auto_memory_per_genome_mb=8192
  local auto_max_anno_cpus=1
  local auto_max_funbgcex_workers=1
  local auto_max_record_parallelism=1
  local max_shard_cpus=1
  local annotation_slots=0
  local funbgcex_slots=0
  local antismash_shard_slots=0
  local antismash_legacy_slots=0

  total_genomes="$(positive_int_or_default "${1:-}" 1)"
  RESOURCE_EFFECTIVE_CPUS="$(detect_effective_cpus)"
  RESOURCE_EFFECTIVE_MEMORY_MB="$(detect_effective_memory_mb)"
  RESOURCE_MEMORY_BUDGET_MB=0

  if [[ "${PIPELINE_RESOURCE_MODE}" == "auto" ]]; then
    auto_max_cpus="$(positive_int_or_default "${PIPELINE_AUTO_MAX_CPUS}" 32)"
    if [[ "${CPUS_REQUEST_EXPLICIT}" -eq 0 ]]; then
      CPUS="${RESOURCE_EFFECTIVE_CPUS}"
    fi
    CPUS="$(minimum_int "$(positive_int_or_default "${CPUS}" 1)" "${RESOURCE_EFFECTIVE_CPUS}" "${auto_max_cpus}")"

    auto_max_genomes="$(positive_int_or_default "${PIPELINE_AUTO_MAX_GENOME_PARALLELISM}" 4)"
    auto_min_cpus_per_genome="$(positive_int_or_default "${PIPELINE_AUTO_MIN_CPUS_PER_GENOME}" 2)"
    auto_memory_percent="$(positive_int_or_default "${PIPELINE_AUTO_MEMORY_PERCENT}" 70)"
    if [[ "${auto_memory_percent}" -gt 100 ]]; then auto_memory_percent=100; fi
    auto_memory_per_genome_mb="$(positive_int_or_default "${PIPELINE_AUTO_MEMORY_PER_GENOME_MB}" 8192)"

    RESOURCE_MEMORY_BUDGET_MB="${RESOURCE_EFFECTIVE_MEMORY_MB}"
    if [[ "${PIPELINE_MEMORY_BUDGET_MB}" =~ ^[0-9]+$ && "${PIPELINE_MEMORY_BUDGET_MB}" -ge 1 ]]; then
      if [[ "${RESOURCE_MEMORY_BUDGET_MB}" -ge 1 ]]; then
        RESOURCE_MEMORY_BUDGET_MB="$(minimum_int "${RESOURCE_MEMORY_BUDGET_MB}" "${PIPELINE_MEMORY_BUDGET_MB}")"
      else
        RESOURCE_MEMORY_BUDGET_MB="${PIPELINE_MEMORY_BUDGET_MB}"
      fi
    fi
    if [[ "${RESOURCE_MEMORY_BUDGET_MB}" -ge 1 ]]; then
      usable_memory_mb=$((RESOURCE_MEMORY_BUDGET_MB * auto_memory_percent / 100))
    fi

    cpu_genome_limit=$((CPUS / auto_min_cpus_per_genome))
    if [[ "${cpu_genome_limit}" -lt 1 ]]; then cpu_genome_limit=1; fi
    memory_genome_limit="${auto_max_genomes}"
    if [[ "${usable_memory_mb}" -ge 1 ]]; then
      memory_genome_limit=$((usable_memory_mb / auto_memory_per_genome_mb))
      if [[ "${memory_genome_limit}" -lt 1 ]]; then memory_genome_limit=1; fi
    fi
    desired_genome_parallelism="$(minimum_int "${total_genomes}" "${auto_max_genomes}" "${cpu_genome_limit}" "${memory_genome_limit}")"
  else
    CPUS="$(positive_int_or_default "${CPUS}" 6)"
    if [[ "${CPUS_REQUEST_EXPLICIT}" -eq 0 ]]; then
      CPUS="$(minimum_int "${CPUS}" "${RESOURCE_EFFECTIVE_CPUS}")"
    fi
  fi

  GENOME_PARALLELISM="$(minimum_int "$(positive_int_or_default "${desired_genome_parallelism}" 1)" "${total_genomes}" "${CPUS}")"
  PER_GENOME_CPU_BUDGET=$((CPUS / GENOME_PARALLELISM))
  if [[ "${PER_GENOME_CPU_BUDGET}" -lt 1 ]]; then PER_GENOME_CPU_BUDGET=1; fi

  if [[ "${PIPELINE_RESOURCE_MODE}" == "auto" ]]; then
    auto_max_anno_cpus="$(positive_int_or_default "${PIPELINE_AUTO_MAX_ANNO_CPUS}" 8)"
    auto_max_funbgcex_workers="$(positive_int_or_default "${PIPELINE_AUTO_MAX_FUNBGCEX_WORKERS}" 2)"
    auto_max_record_parallelism="$(positive_int_or_default "${PIPELINE_AUTO_MAX_ANTISMASH_RECORD_PARALLELISM}" 3)"
    ANNO_CPUS="$(minimum_int "${auto_max_anno_cpus}" "${PER_GENOME_CPU_BUDGET}")"
    WORKERS="$(minimum_int "${auto_max_funbgcex_workers}" "${PER_GENOME_CPU_BUDGET}")"
    ANTISMASH_RECORD_PARALLELISM="$(minimum_int "${auto_max_record_parallelism}" "${PER_GENOME_CPU_BUDGET}")"
  else
    ANNO_CPUS="$(minimum_int "$(positive_int_or_default "${ANNO_CPUS}" 1)" "${PER_GENOME_CPU_BUDGET}")"
    WORKERS="$(minimum_int "$(positive_int_or_default "${WORKERS}" 1)" "${PER_GENOME_CPU_BUDGET}")"
    ANTISMASH_RECORD_PARALLELISM="$(minimum_int "$(positive_int_or_default "${ANTISMASH_RECORD_PARALLELISM}" 1)" "${PER_GENOME_CPU_BUDGET}")"
  fi

  ANTISMASH_SHARD_CPUS_DEFAULT=$((PER_GENOME_CPU_BUDGET / ANTISMASH_RECORD_PARALLELISM))
  if [[ "${ANTISMASH_SHARD_CPUS_DEFAULT}" -lt 1 ]]; then ANTISMASH_SHARD_CPUS_DEFAULT=1; fi
  max_shard_cpus="${ANTISMASH_SHARD_CPUS_DEFAULT}"
  if [[ "${PIPELINE_RESOURCE_MODE}" == "auto" || -z "${ANTISMASH_SHARD_CPUS_REQUESTED}" ]]; then
    ANTISMASH_SHARD_CPUS="${max_shard_cpus}"
  else
    ANTISMASH_SHARD_CPUS="$(minimum_int "$(positive_int_or_default "${ANTISMASH_SHARD_CPUS_REQUESTED}" "${max_shard_cpus}")" "${max_shard_cpus}")"
  fi
  if [[ "${PIPELINE_RESOURCE_MODE}" == "auto" || -z "${ANTISMASH_LEGACY_CPUS_REQUESTED}" ]]; then
    ANTISMASH_LEGACY_CPUS="${PER_GENOME_CPU_BUDGET}"
  else
    ANTISMASH_LEGACY_CPUS="$(minimum_int "$(positive_int_or_default "${ANTISMASH_LEGACY_CPUS_REQUESTED}" "${PER_GENOME_CPU_BUDGET}")" "${PER_GENOME_CPU_BUDGET}")"
  fi

  annotation_slots=$((GENOME_PARALLELISM * ANNO_CPUS))
  funbgcex_slots=$((GENOME_PARALLELISM * WORKERS))
  antismash_shard_slots=$((GENOME_PARALLELISM * ANTISMASH_RECORD_PARALLELISM * ANTISMASH_SHARD_CPUS))
  antismash_legacy_slots=$((GENOME_PARALLELISM * ANTISMASH_LEGACY_CPUS))
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
    antismash)
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
    printf '%s\n' "${raw}" >> "${dest}"
    raw_line_count=$((raw_line_count + 1))
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
    tool_activity_emit_progress "${genome}" "${tool}" "${phase}" "$(tool_activity_display_name "${tool}") finished"
  else
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

###############################################################################
# Converter bootstrap (pure stdlib python; no pip/venv dependency)
###############################################################################
CONVERT_PY="${CONVERT_PY:-${PROJECT_DIR}/bin/gff3_to_gbk_with_translations.py}"
GENBANK_TRANSLATION_CHECKER="${GENBANK_TRANSLATION_CHECKER:-${PROJECT_DIR}/bin/check_genbank_translations.py}"
VENV_PY="${VENV_PY:-python3}"

setup_converter() {
  if [[ -s "${CONVERT_PY}" ]]; then
    log "Using existing converter: ${CONVERT_PY}"
    return 0
  fi

  mkdir -p "$(dirname "${CONVERT_PY}")"

  command -v "${VENV_PY}" >/dev/null 2>&1 || die "Python interpreter not found for converter: ${VENV_PY}"

  log "Writing converter: ${CONVERT_PY}"
  cat > "${CONVERT_PY}" <<'PY'
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import argparse
import re

CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}

COMPLEMENT = str.maketrans("ACGTRYMKBDHVNacgtrymkbdhvn", "TGCAYRKMVHDBNtgcayrkmvhdbn")
ATTR_RE = re.compile(r'([^=;]+)=([^;]+)')


def normalize_seqid(value: str) -> str:
    return value.split()[0]


def parse_attrs(attr_str: str) -> dict[str, str]:
    attrs = {}
    for match in ATTR_RE.finditer(attr_str.strip()):
        attrs[match.group(1)] = match.group(2)
    return attrs


def parse_fasta(path: Path) -> dict[str, dict[str, str]]:
    records = {}
    current_id = None
    current_desc = ""
    parts: list[str] = []
    with path.open() as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current_id is not None:
                    records[current_id] = {
                        "id": current_id,
                        "description": current_desc,
                        "seq": "".join(parts).upper(),
                    }
                header = line[1:].strip()
                tokens = header.split(None, 1)
                current_id = tokens[0]
                current_desc = header
                parts = []
            else:
                parts.append(line)
    if current_id is not None:
        records[current_id] = {
            "id": current_id,
            "description": current_desc,
            "seq": "".join(parts).upper(),
        }
    return records


def reverse_complement(seq: str) -> str:
    return seq.translate(COMPLEMENT)[::-1]


def translate_cds(seq: str) -> str:
    protein = []
    usable = len(seq) - (len(seq) % 3)
    for idx in range(0, usable, 3):
        codon = seq[idx:idx + 3]
        protein.append(CODON_TABLE.get(codon, "X"))
    return "".join(protein)


def format_location(parts: list[dict[str, int]], strand: str) -> str:
    ordered = sorted(parts, key=lambda item: item["start"])
    spans = [f"{item['start']}..{item['end']}" for item in ordered]
    loc = spans[0] if len(spans) == 1 else f"join({','.join(spans)})"
    return f"complement({loc})" if strand == "-" else loc


def wrap_qualifier(prefix: str, value: str) -> list[str]:
    width = 80
    lines = []
    current = f'{prefix}"{value}"'
    prefix_to_use = "                     "
    while len(prefix_to_use) + len(current) > width:
        take = width - len(prefix_to_use)
        lines.append(prefix_to_use + current[:take])
        current = current[take:]
    lines.append(prefix_to_use + current)
    return lines


def format_origin(seq: str) -> list[str]:
    lines = ["ORIGIN"]
    for offset in range(0, len(seq), 60):
        chunk = seq[offset:offset + 60].lower()
        groups = [chunk[i:i + 10] for i in range(0, len(chunk), 10)]
        lines.append(f"{offset + 1:>9} {' '.join(groups)}")
    lines.append("//")
    return lines


def gff_to_gbk_with_translations(fasta: Path, gff3: Path, out_gbk: Path) -> tuple[int, int]:
    seqs = parse_fasta(fasta)
    if not seqs:
        raise RuntimeError(f"No contigs read from FASTA: {fasta}")
    seqs_norm = {normalize_seqid(key): value for key, value in seqs.items()}

    cds_by_parent: dict[str, list[dict[str, object]]] = defaultdict(list)
    with gff3.open() as handle:
        for raw_line in handle:
            if not raw_line.strip() or raw_line.startswith("#"):
                continue
            parts = raw_line.rstrip("\n").split("\t")
            if len(parts) != 9:
                continue
            seqid, source, feature_type, start, end, score, strand, phase, attrs = parts
            if feature_type != "CDS":
                continue
            parsed = parse_attrs(attrs)
            parent = parsed.get("Parent") or parsed.get("transcript_id") or parsed.get("ID")
            if not parent:
                parent = f"{seqid}:{start}-{end}:{strand}"
            seqid_norm = normalize_seqid(seqid)
            # Gene IDs can repeat across contigs (e.g., g1.t1), so key by contig+parent.
            parent_key = f"{seqid_norm}::{parent}"
            cds_by_parent[parent_key].append({
                "seqid": seqid_norm,
                "parent": parent,
                "start": int(start),
                "end": int(end),
                "strand": strand if strand in {"+", "-"} else "+",
                "phase": phase,
            })

    if not cds_by_parent:
        raise RuntimeError(f"No CDS features found in GFF3: {gff3}")

    cds_count = 0
    tr_count = 0
    out_lines: list[str] = []
    today = datetime.utcnow().strftime("%d-%b-%Y").upper()

    for seqid_norm, record in seqs_norm.items():
        seq = record["seq"]
        matching = []
        for _parent_key, cds_list in cds_by_parent.items():
            contig_parts = [item for item in cds_list if item["seqid"] == seqid_norm]
            if not contig_parts:
                continue
            parent = str(contig_parts[0].get("parent", "unknown"))
            strand = str(contig_parts[0]["strand"])
            ordered_for_seq = sorted(contig_parts, key=lambda item: int(item["start"]), reverse=(strand == "-"))
            pieces = [seq[int(item["start"]) - 1:int(item["end"])] for item in ordered_for_seq]
            cds_seq = "".join(pieces)
            if strand == "-":
                cds_seq = reverse_complement(cds_seq)
            phase = contig_parts[0]["phase"]
            try:
                phase_int = int(phase) if phase not in {"", "."} else 0
            except ValueError:
                phase_int = 0
            if phase_int in (1, 2):
                cds_seq = cds_seq[phase_int:]
            protein = translate_cds(cds_seq)
            matching.append({
                "parent": parent,
                "strand": strand,
                "parts": [{"start": int(item["start"]), "end": int(item["end"])} for item in contig_parts],
                "protein": protein,
            })

        if not matching:
            continue

        locus = record["id"][:16]
        out_lines.append(f"LOCUS       {locus:<16}{len(seq):>11} bp    DNA              UNK {today}")
        out_lines.append(f"DEFINITION  {record['description'] or record['id']}")
        out_lines.append(f"ACCESSION   {record['id']}")
        out_lines.append(f"VERSION     {record['id']}")
        out_lines.append("KEYWORDS    .")
        out_lines.append("SOURCE      .")
        out_lines.append("  ORGANISM  .")
        out_lines.append("            .")
        out_lines.append("FEATURES             Location/Qualifiers")
        out_lines.append(f"     source          1..{len(seq)}")
        for feature in sorted(matching, key=lambda item: min(part['start'] for part in item['parts'])):
            out_lines.append(f"     CDS             {format_location(feature['parts'], feature['strand'])}")
            out_lines.extend(wrap_qualifier('/locus_tag=', str(feature['parent'])))
            out_lines.extend(wrap_qualifier('/product=', 'predicted_protein'))
            out_lines.extend(wrap_qualifier('/translation=', str(feature['protein'])))
            cds_count += 1
            tr_count += 1
        out_lines.extend(format_origin(seq))

    out_gbk.parent.mkdir(parents=True, exist_ok=True)
    out_gbk.write_text("\n".join(out_lines) + "\n")
    return cds_count, tr_count


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fasta", required=True)
    ap.add_argument("--gff3", required=True)
    ap.add_argument("--out_gbk", required=True)
    args = ap.parse_args()
    cds, tr = gff_to_gbk_with_translations(Path(args.fasta), Path(args.gff3), Path(args.out_gbk))
    print(f"WROTE {args.out_gbk}")
    print(f"CDS features: {cds}")
    print(f"/translation=: {tr}")
PY
  chmod +x "${CONVERT_PY}" || true

  [[ -f "${CONVERT_PY}" ]] || die "Converter script missing after setup"
}

###############################################################################
# Input discovery/resolution
###############################################################################
GENOME_MAPPING_FILE="${GENOME_MAPPING_FILE:-${GENOME_ROOT}/accessions_fungusID_taxonomyID.txt}"
declare -A ROUTE_TAXON_BY_GENOME=()
declare -A ROUTE_ROOT_BY_GENOME=()
declare -A ROUTE_PREDICTION_BY_GENOME=()
declare -A ROUTE_DETECTOR_BY_GENOME=()
declare -A ROUTE_SOURCE_BY_GENOME=()
declare -A ROUTE_STATUS_BY_GENOME=()
ROUTE_MANIFEST_ACTIVE=0
HAS_FUNGAL_ROUTES=0
HAS_BACTERIAL_ROUTES=0

load_taxon_routes() {
  local input_key genome_id taxon_group taxon_source taxid organism_name source_accession
  local prediction_method detector_profile input_path_key route_status route_reason
  local route_line=""
  [[ -s "${GENOME_TAXON_MANIFEST}" ]] || {
    HAS_FUNGAL_ROUTES=1
    return 0
  }
  while IFS= read -r route_line || [[ -n "${route_line}" ]]; do
    IFS=$'\034' read -r \
        input_key genome_id taxon_group taxon_source taxid organism_name source_accession \
        prediction_method detector_profile input_path_key route_status route_reason \
        <<< "${route_line//$'\t'/$'\034'}"
    [[ "${input_key}" == "input_key" ]] && continue
    [[ -n "${genome_id}" ]] || continue
    case "${route_status,,}" in
      failed|invalid|rejected|unresolved|unsupported) continue ;;
    esac
    case "${taxon_group,,}" in
      fungi)
        taxon_group="fungi"
        HAS_FUNGAL_ROUTES=1
        ;;
      bacteria)
        taxon_group="bacteria"
        HAS_BACTERIAL_ROUTES=1
        ;;
      *)
        die "Invalid taxon_group='${taxon_group}' for genome ${genome_id} in ${GENOME_TAXON_MANIFEST}"
        ;;
    esac
    [[ -z "${ROUTE_TAXON_BY_GENOME[${genome_id}]+set}" ]] \
      || die "Duplicate genome_id in canonical taxon manifest: ${genome_id}"
    ROUTE_TAXON_BY_GENOME["${genome_id}"]="${taxon_group}"
    if [[ "${taxon_group}" == "bacteria" ]]; then
      ROUTE_ROOT_BY_GENOME["${genome_id}"]="${BACTERIA_GENOME_ROOT}"
      ROUTE_PREDICTION_BY_GENOME["${genome_id}"]="${prediction_method:-prodigal}"
      ROUTE_DETECTOR_BY_GENOME["${genome_id}"]="${detector_profile:-antismash}"
    else
      ROUTE_ROOT_BY_GENOME["${genome_id}"]="${FUNGI_GENOME_ROOT}"
      ROUTE_PREDICTION_BY_GENOME["${genome_id}"]="${prediction_method:-funannotate}"
      ROUTE_DETECTOR_BY_GENOME["${genome_id}"]="${detector_profile:-antismash+funbgcex}"
    fi
    ROUTE_SOURCE_BY_GENOME["${genome_id}"]="${taxon_source:-legacy_default}"
    ROUTE_STATUS_BY_GENOME["${genome_id}"]="${route_status:-routed}"
    ROUTE_MANIFEST_ACTIVE=1
  done < "${GENOME_TAXON_MANIFEST}"
  if [[ "${ROUTE_MANIFEST_ACTIVE}" -eq 0 ]]; then
    HAS_FUNGAL_ROUTES=1
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
  printf '%s\n' "${ROUTE_PREDICTION_BY_GENOME[${genome_id}]:-$([[ "${taxon_group}" == "bacteria" ]] && printf prodigal || printf funannotate)}"
}

route_detector_for_genome() {
  local genome_id="$1"
  local taxon_group=""
  taxon_group="$(route_taxon_for_genome "${genome_id}")"
  printf '%s\n' "${ROUTE_DETECTOR_BY_GENOME[${genome_id}]:-$([[ "${taxon_group}" == "bacteria" ]] && printf antismash || printf antismash+funbgcex)}"
}

route_source_for_genome() {
  printf '%s\n' "${ROUTE_SOURCE_BY_GENOME[$1]:-legacy_default}"
}

route_status_for_genome() {
  printf '%s\n' "${ROUTE_STATUS_BY_GENOME[$1]:-routed}"
}

mapping_file_for_taxon() {
  local taxon_group="$1"
  if [[ "${taxon_group}" == "bacteria" ]]; then
    printf '%s\n' "${BACTERIA_GENOME_ROOT}/accessions_bacteriaID_taxonomyID.txt"
  else
    printf '%s\n' "${FUNGI_GENOME_ROOT}/accessions_fungusID_taxonomyID.txt"
  fi
}

genome_stem_has_file() {
  local stem="$1"
  local root="${2:-${GENOME_ROOT}}"
  local ext
  for ext in fna fa fsa fasta gb gbk gbff; do
    [[ -s "${root}/${stem}.${ext}" ]] && return 0
  done
  return 1
}

mapped_canonical_stem() {
  local stem="$1"
  [[ -f "${GENOME_MAPPING_FILE}" ]] || return 1
  awk -F '\t' -v stem="${stem}" '$1 == stem && $2 != "" && $2 != stem { print $2; exit }' "${GENOME_MAPPING_FILE}"
}

funannotate_trim() {
  printf '%s\n' "${1:-}" | awk '{$1=$1; print}'
}

funannotate_lower() {
  printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]'
}

funannotate_env_value() {
  local key="$1"
  local default="${2:-}"
  local value="${!key:-}"
  value="$(funannotate_trim "${value}")"
  [[ -n "${value}" ]] || value="${default}"
  printf '%s\n' "${value}"
}

funannotate_busco_env_value() {
  local key="$1"
  local default="${2:-}"
  local value=""
  value="$(funannotate_env_value "${key}" "${default}")"
  case "$(funannotate_lower "${value}")" in
    auto-lineage|auto_lineage|auto-lineage-euk|auto-lineage-prok)
      value="${default}"
      ;;
  esac
  printf '%s\n' "${value}"
}

funannotate_is_auto_busco() {
  case "$(funannotate_lower "${1:-}")" in
    ""|auto|taxonomy|lineage|from-taxonomy) return 0 ;;
    *) return 1 ;;
  esac
}

funannotate_is_auto_organism() {
  case "$(funannotate_lower "${1:-}")" in
    ""|"{}"|none|null|auto|taxonomy|lineage|from-taxonomy|fungal_sp|"fungal sp") return 0 ;;
    *) return 1 ;;
  esac
}

funannotate_species_from_text() {
  local value="${1:-}"
  local first=""
  local second=""
  value="${value//_/ }"
  value="$(funannotate_trim "${value}")"
  if [[ -z "${value}" ]]; then
    printf '%s\n' "Fungal sp"
    return 0
  fi
  read -r first second _ <<< "${value}"
  if [[ -n "${second}" ]]; then
    printf '%s %s\n' "${first}" "${second%.}"
  else
    printf '%s sp\n' "${first}"
  fi
}

funannotate_mapping_row() {
  local genome_id="$1"
  [[ -s "${GENOME_MAPPING_FILE}" ]] || return 1
  awk -F '\t' -v target="${genome_id}" '
    BEGIN { t = tolower(target) }
    tolower($1) == "accession" { next }
    {
      accession = tolower($1)
      genome = tolower($2)
      split(accession, accession_parts, /\./)
      accession_base = accession_parts[1]
      if (t == genome || t == accession || (t != "" && t == accession_base)) {
        print
        exit
      }
    }
  ' "${GENOME_MAPPING_FILE}"
}

funannotate_lineage_has_id() {
  local blob="${1:-}"
  local taxid="$2"
  local normalized=""
  normalized="${blob//[^0-9]/,}"
  [[ ",${normalized}," == *",${taxid},"* ]]
}

resolve_funannotate_policy() {
  local genome_id="$1"
  local row=""
  local map_accession=""
  local map_genome_id=""
  local map_taxid=""
  local map_size=""
  local map_organism=""
  local map_lineage_ids=""
  local map_lineage_names=""
  local lineage_blob=""
  local db_setting=""
  local default_db=""
  local fungi_db=""
  local dikarya_db=""
  local mucoromycota_db=""

  FUNANNOTATE_RESOLVED_BUSCO_DB="${FUNANNOTATE_BUSCO_DB}"
  FUNANNOTATE_RESOLVED_SPECIES="${FUNANNOTATE_ORGANISM_NAME}"
  FUNANNOTATE_RESOLVED_SOURCE="explicit"

  row="$(funannotate_mapping_row "${genome_id}" || true)"
  if [[ -n "${row}" ]]; then
    IFS=$'\t' read -r map_accession map_genome_id map_taxid map_size map_organism map_lineage_ids map_lineage_names <<< "${row}"
    lineage_blob="${map_lineage_ids},${map_taxid}"
  fi

  if funannotate_is_auto_organism "${FUNANNOTATE_ORGANISM_NAME}"; then
    if [[ -n "${map_organism}" ]]; then
      FUNANNOTATE_RESOLVED_SPECIES="$(funannotate_species_from_text "${map_organism}")"
    else
      FUNANNOTATE_RESOLVED_SPECIES="$(funannotate_species_from_text "${genome_id}")"
    fi
  else
    FUNANNOTATE_RESOLVED_SPECIES="${FUNANNOTATE_ORGANISM_NAME%.}"
  fi

  db_setting="$(funannotate_env_value FUNANNOTATE_BUSCO_DB auto)"
  if ! funannotate_is_auto_busco "${db_setting}"; then
    FUNANNOTATE_RESOLVED_BUSCO_DB="${db_setting}"
    FUNANNOTATE_RESOLVED_SOURCE="explicit"
  elif [[ -n "${row}" ]]; then
    default_db="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_DEFAULT dikarya)"
    fungi_db="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_FUNGI fungi)"
    dikarya_db="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_DIKARYA dikarya)"
    if funannotate_lineage_has_id "${lineage_blob}" "4827"; then
      mucoromycota_db="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_MUCOROMYCOTA "${fungi_db}")"
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_MUCORALES "${mucoromycota_db}")"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:mucorales"
    elif funannotate_lineage_has_id "${lineage_blob}" "1913637"; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_MUCOROMYCOTA "${fungi_db}")"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:mucoromycota"
    elif funannotate_lineage_has_id "${lineage_blob}" "6029"; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_MICROSPORIDIA microsporidia)"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:microsporidia"
    elif funannotate_lineage_has_id "${lineage_blob}" "4890"; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_ASCOMYCOTA ascomycota)"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:ascomycota"
    elif funannotate_lineage_has_id "${lineage_blob}" "5204"; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_BASIDIOMYCOTA basidiomycota)"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:basidiomycota"
    elif funannotate_lineage_has_id "${lineage_blob}" "451864"; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="${dikarya_db}"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:dikarya"
    elif funannotate_lineage_has_id "${lineage_blob}" "4751" || [[ -n "${map_taxid}" ]]; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="${fungi_db}"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:fungi"
    else
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_NO_TAXONOMY "${default_db}")"
      FUNANNOTATE_RESOLVED_SOURCE="fallback:no-taxonomy"
    fi
  else
    default_db="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_DEFAULT dikarya)"
    FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_NO_TAXONOMY "${default_db}")"
    FUNANNOTATE_RESOLVED_SOURCE="fallback:no-taxonomy"
  fi

  FUNANNOTATE_RESOLVED_BUSCO_DB="$(printf '%s' "${FUNANNOTATE_RESOLVED_BUSCO_DB}" | tr -d '[:space:]')"
  case "${FUNANNOTATE_RESOLVED_BUSCO_DB}" in
    ""|"{}"|none|null|auto|taxonomy|lineage|from-taxonomy|auto-lineage|auto_lineage|auto-lineage-euk|auto-lineage-prok)
      FUNANNOTATE_RESOLVED_BUSCO_DB="dikarya"
      ;;
  esac

  case "${FUNANNOTATE_RESOLVED_SPECIES}" in
    ""|"{}"|none|null|auto|taxonomy|lineage|from-taxonomy|Fungal_sp|"Fungal sp")
      FUNANNOTATE_RESOLVED_SPECIES="Fungal_sp"
      ;;
  esac
}

funannotate_busco_db_available() {
  local db="$1"
  local fun_cmd="${2:-funannotate}"
  local use_docker="${3:-0}"
  local use_sif="${4:-0}"
  local db_root="${FUNANNOTATE_DB:-/opt/databases}"

  case "${db}" in
    ""|"{}"|none|null|auto|taxonomy|lineage|from-taxonomy|auto-lineage|auto_lineage|auto-lineage-euk|auto-lineage-prok)
      return 1
      ;;
  esac

  if [[ "${use_docker}" -eq 1 ]]; then
    CLUSTERWEAVE_CHILD_DOCKER_CPUS=1 docker_exec "$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")" sh -lc \
      'db="$1"; base="${FUNANNOTATE_DB:-/opt/databases}"; test -d "${base}/${db}/hmms" && find "${base}/${db}/hmms" -type f -print -quit | grep -q .' \
      sh "${db}" >/dev/null 2>&1
    return $?
  fi

  if [[ "${use_sif}" -eq 1 ]]; then
    sing_exec "${FUNANNOTATE_SIF}" sh -lc \
      'db="$1"; base="${FUNANNOTATE_DB:-/opt/databases}"; test -d "${base}/${db}/hmms" && find "${base}/${db}/hmms" -type f -print -quit | grep -q .' \
      sh "${db}" >/dev/null 2>&1
    return $?
  fi

  [[ -d "${db_root}/${db}/hmms" ]] || return 1
  find "${db_root}/${db}/hmms" -type f -print -quit 2>/dev/null | grep -q .
}

validate_funannotate_busco_db() {
  local db="$1"
  local source="$2"
  local genome_id="$3"
  local fun_cmd="$4"
  local use_docker="$5"
  local use_sif="$6"
  local fallback_db

  if funannotate_busco_db_available "${db}" "${fun_cmd}" "${use_docker}" "${use_sif}"; then
    printf '%s\n' "${db}"
    return 0
  fi

  if [[ "${source}" == "explicit" ]]; then
    warn "${genome_id}: explicit FUNANNOTATE_BUSCO_DB='${db}' is not installed in the active funannotate runtime"
    return 1
  fi

  fallback_db="$(printf '%s' "${FUNANNOTATE_BUSCO_DB_DEFAULT:-dikarya}" | tr -d '[:space:]')"
  case "${fallback_db}" in
    ""|"{}"|none|null|auto|taxonomy|lineage|from-taxonomy|auto-lineage|auto_lineage|auto-lineage-euk|auto-lineage-prok)
      fallback_db="dikarya"
      ;;
  esac

  if [[ "${db}" != "${fallback_db}" ]] && funannotate_busco_db_available "${fallback_db}" "${fun_cmd}" "${use_docker}" "${use_sif}"; then
    warn "${genome_id}: auto-selected BUSCO db '${db}' for ${source} is not installed in the active funannotate runtime; falling back to broad '${fallback_db}'"
    printf '%s\n' "${fallback_db}"
    return 0
  fi

  warn "${genome_id}: selected BUSCO db '${db}' and fallback '${fallback_db}' are not installed in the active funannotate runtime"
  return 1
}


funannotate_predict_failed_in_p2g() {
  local fun_log="$1"
  [[ -s "${fun_log}" ]] || return 1
  grep -Eiq \
    'CMD ERROR:[[:space:]]*diamond blastx|funannotate-p2g\.py.*(error|failed|exception|traceback)|p2g\.diamond.*(error|failed|missing|no such file)|protein_alignments\.gff3.*(error|failed|missing|no such file)|(error|failed|exception|traceback|missing|no such file).*(funannotate-p2g\.py|p2g\.diamond|protein_alignments\.gff3)' \
    "${fun_log}"
}

funannotate_predict_failure_status() {
  local fun_log="$1"
  local not_enough_line=""
  local validated_line=""
  local training_models=""
  local required_models=""
  local validated_buscos=""
  [[ -s "${fun_log}" ]] || return 1

  not_enough_line="$(grep -E "Not enough gene models [0-9,]+ to train Augustus \([0-9,]+ required\)" "${fun_log}" | tail -n1 || true)"
  [[ -n "${not_enough_line}" ]] || return 1

  training_models="$(printf '%s\n' "${not_enough_line}" | sed -E 's/.*Not enough gene models ([0-9,]+) to train Augustus \(([0-9,]+) required\).*/\1/' | tr -d ',')"
  required_models="$(printf '%s\n' "${not_enough_line}" | sed -E 's/.*Not enough gene models ([0-9,]+) to train Augustus \(([0-9,]+) required\).*/\2/' | tr -d ',')"
  validated_line="$(grep -Eo "[0-9,]+ BUSCO predictions validated" "${fun_log}" | tail -n1 || true)"
  if [[ -n "${validated_line}" ]]; then
    validated_buscos="$(printf '%s\n' "${validated_line}" | sed -E 's/ .*//' | tr -d ',')"
  fi

  if [[ -n "${validated_buscos}" && "${validated_buscos}" == "${training_models}" ]]; then
    printf 'funannotate_busco_training_insufficient\tvalidated_busco_models=%s required_training_models=%s\n' "${validated_buscos}" "${required_models}"
  else
    printf 'funannotate_training_models_insufficient\ttraining_models=%s required_training_models=%s\n' "${training_models}" "${required_models}"
  fi
}

funannotate_normalize_min_training_models_fallback() {
  local value="${1:-150}"
  case "${value}" in
    ''|*[!0-9]*) value=150 ;;
    *)
      value="$(printf '%s\n' "${value}" | sed -E 's/^0+//')"
      [[ -n "${value}" ]] || value=0
      if [[ "${#value}" -gt 3 ]]; then
        value=200
      fi
      ;;
  esac
  if (( value < 100 )); then
    value=100
  elif (( value >= 200 )); then
    value=199
  fi
  printf '%s\n' "${value}"
}

funannotate_busco_training_fallback_threshold() {
  local fun_log="$1"
  local parsed=""
  local status=""
  local detail=""
  local validated_models=""
  local required_models=""
  local fallback_floor=""

  parsed="$(funannotate_predict_failure_status "${fun_log}" || true)"
  [[ -n "${parsed}" ]] || return 1
  IFS=$'\t' read -r status detail <<< "${parsed}"
  [[ "${status}" == "funannotate_busco_training_insufficient" ]] || return 1

  validated_models="$(printf '%s\n' "${detail}" | grep -Eo 'validated_busco_models=[0-9]+' | tail -n1 | cut -d= -f2 || true)"
  required_models="$(printf '%s\n' "${detail}" | grep -Eo 'required_training_models=[0-9]+' | tail -n1 | cut -d= -f2 || true)"
  [[ "${validated_models}" =~ ^[0-9]+$ && "${required_models}" =~ ^[0-9]+$ ]] || return 1

  fallback_floor="$(funannotate_normalize_min_training_models_fallback "${FUNANNOTATE_MIN_TRAINING_MODELS_FALLBACK:-150}")"
  (( validated_models >= fallback_floor && required_models > fallback_floor )) || return 1
  printf '%s\n' "${fallback_floor}"
}

funannotate_record_predict_failure() {
  local genome_id="$1"
  local fun_log="$2"
  local busco_db="$3"
  local source="$4"
  local parsed=""
  local status=""
  local detail=""
  FUNANNOTATE_LAST_FAILURE_STATUS=""
  FUNANNOTATE_LAST_FAILURE_DETAIL=""

  if parsed="$(funannotate_predict_failure_status "${fun_log}")"; then
    IFS=$'\t' read -r status detail <<< "${parsed}"
    FUNANNOTATE_LAST_FAILURE_STATUS="${status}"
    FUNANNOTATE_LAST_FAILURE_DETAIL="${detail} busco_db=${busco_db} policy=${source}"
    warn "${genome_id}: funannotate could not train AUGUSTUS; ${FUNANNOTATE_LAST_FAILURE_DETAIL}"
  fi
}

should_skip_discovered_stem() {
  local stem="$1"
  local canonical
  canonical="$(mapped_canonical_stem "${stem}" || true)"
  [[ -n "${canonical}" ]] || return 1
  genome_stem_has_file "${canonical}" || return 1
  warn "skipping accession alias genome stem: ${stem} maps to existing ${canonical}"
  return 0
}

discover_stems() {
  if [[ "${ROUTE_MANIFEST_ACTIVE}" -eq 1 ]]; then
    printf '%s\n' "${!ROUTE_TAXON_BY_GENOME[@]}" | LC_ALL=C sort
    return 0
  fi
  find "${FUNGI_GENOME_ROOT}" -maxdepth 1 -type f \
    \( -iname "*.fa" -o -iname "*.fna" -o -iname "*.fsa" -o -iname "*.fasta" -o -iname "*.gb" -o -iname "*.gbk" -o -iname "*.gbff" \) \
    -printf "%f\n" 2>/dev/null \
  | sed -E 's/\.(fa|fna|fsa|fasta|gb|gbk|gbff)$//' \
  | sort -u \
  | while IFS= read -r stem; do
      should_skip_discovered_stem "${stem}" && continue
      printf '%s\n' "${stem}"
    done
}

resolve_fasta_for_stem() {
  local stem="$1"
  local root="${2:-${GENOME_ROOT}}"
  local cands=( "${root}/${stem}.fna" "${root}/${stem}.fa" "${root}/${stem}.fsa" "${root}/${stem}.fasta" )
  local f
  for f in "${cands[@]}"; do [[ -s "${f}" ]] && { echo "${f}"; return 0; }; done
  return 1
}

resolve_genbank_for_stem() {
  local stem="$1"
  local root="${2:-${GENOME_ROOT}}"
  local cands=( "${root}/${stem}.gbk" "${root}/${stem}.gb" "${root}/${stem}.gbff" )
  local f
  for f in "${cands[@]}"; do [[ -s "${f}" ]] && { echo "${f}"; return 0; }; done
  return 1
}

###############################################################################
# GBK checks
###############################################################################
gbk_has_cds_and_translation() {
  local gbk="$1"
  [[ -s "${gbk}" ]] || return 1
  [[ -s "${GENBANK_TRANSLATION_CHECKER}" ]] || return 1
  "${VENV_PY}" "${GENBANK_TRANSLATION_CHECKER}" "${gbk}" >/dev/null 2>&1
}

gbk_has_cds() {
  local gbk="$1"
  [[ -s "${gbk}" ]] || return 1
  awk '
    /^LOCUS[[:space:]]/ { loci++ }
    /^[[:space:]]+CDS[[:space:]]/ { cds=1 }
    /^\/\/[[:space:]\r]*$/ { terminators++ }
    NF { last=$0 }
    END {
      sub(/\r$/, "", last)
      exit !(cds && loci > 0 && terminators == loci && last ~ /^\/\/[[:space:]]*$/)
    }
  ' "${gbk}"
}

backfill_gbk_translations_from_existing_cds() {
  local in_gbk="$1"
  local out_gbk="$2"

  # Use the configured FunBGCeX runtime for Biopython-backed GBK repair.
  funbgcex_python_exec - "$in_gbk" "$out_gbk" <<'PY'
import sys
from Bio import SeqIO

inp, outp = sys.argv[1], sys.argv[2]
out_records = []

for rec in SeqIO.parse(inp, "genbank"):
    rec.annotations.setdefault("molecule_type", "DNA")
    for feat in rec.features:
        if feat.type != "CDS":
            continue
        quals = feat.qualifiers or {}
        tx = quals.get("translation", [])
        if any(str(t).strip() for t in tx):
            continue

        cds_seq = feat.extract(rec.seq)

        codon_start = 1
        try:
            codon_start = int((quals.get("codon_start", ["1"]) or ["1"])[0])
        except Exception:
            codon_start = 1
        if codon_start in (2, 3):
            cds_seq = cds_seq[codon_start - 1:]

        table = 1
        try:
            table = int((quals.get("transl_table", ["1"]) or ["1"])[0])
        except Exception:
            table = 1

        prot = str(cds_seq.translate(table=table, to_stop=False)).rstrip("*").strip()
        if prot:
            quals["translation"] = [prot]
            feat.qualifiers = quals

    out_records.append(rec)

with open(outp, "w") as h:
    SeqIO.write(out_records, h, "genbank")
PY
}

normalize_gbk_record_headers() {
  local in_gbk="$1"
  local out_gbk="$2"

  funbgcex_python_exec - "$in_gbk" "$out_gbk" <<'PY'
import re
import sys
from Bio import SeqIO

inp, outp = sys.argv[1], sys.argv[2]
records = list(SeqIO.parse(inp, "genbank"))
version_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*?)(\.\d+)?$")
changed = 0

for rec in records:
    raw_id = ((rec.id or "").split() or [""])[0].strip()
    raw_name = (rec.name or "").strip()
    accessions = [str(acc).strip() for acc in (rec.annotations.get("accessions") or []) if str(acc).strip()]

    base_id = ""
    for candidate in [raw_id, raw_name, *(accessions or [])]:
        if not candidate:
            continue
        match = version_re.match(candidate.rstrip("."))
        if match:
            base_id = match.group(1)
            break
        base_id = candidate.rstrip(".")
        break

    if base_id:
        desired_name = base_id[:16].rstrip(".")
        if desired_name and rec.name != desired_name:
            rec.name = desired_name
            changed += 1

        normalized_accs = [base_id]
        if accessions != normalized_accs:
            rec.annotations["accessions"] = normalized_accs
            changed += 1

SeqIO.write(records, outp, "genbank")
print(f"normalized_records={len(records)} changed_fields={changed}")
PY
}

normalize_gbk_record_headers_in_place() {
  local gbk="$1"
  local tmp="${gbk}.headers_norm"
  [[ -s "${gbk}" ]] || return 1
  if normalize_gbk_record_headers "${gbk}" "${tmp}" >/dev/null 2>&1; then
    mv -f "${tmp}" "${gbk}"
    return 0
  fi
  rm -f "${tmp}" 2>/dev/null || true
  return 1
}



annotation_prompt_pull() {
  local label="$1"
  case "${AUTO_PULL_IMAGES}" in
    always) return 0 ;;
    never)  return 1 ;;
    ask)
      if [[ -t 0 ]]; then
        read -r -p "Pull missing ${label} image now? [y/N] " ans
        [[ "${ans}" =~ ^[Yy]$ ]] && return 0 || return 1
      fi
      return 1
      ;;
    *)
      warn "AUTO_PULL_IMAGES must be ask|always|never; got '${AUTO_PULL_IMAGES}'. Using 'ask'."
      if [[ -t 0 ]]; then
        read -r -p "Pull missing ${label} image now? [y/N] " ans
        [[ "${ans}" =~ ^[Yy]$ ]] && return 0 || return 1
      fi
      return 1
      ;;
  esac
}

ensure_sif_or_prompt_pull() {
  local label="$1"
  local sif="$2"
  local uri="$3"

  if [[ "${ENGINE}" == "docker" ]]; then
    ensure_docker_image "${label}" "$(docker_image_from_uri "${uri}")"
    return $?
  fi

  if [[ -f "${sif}" ]]; then
    log "${label} SIF present: ${sif}"
    return 0
  fi

  warn "${label} SIF missing: ${sif}"
  warn "${label} image source: ${uri}"

  if annotation_prompt_pull "${label}"; then
    mkdir -p "$(dirname "${sif}")"
    log "Pulling ${label} image -> ${sif}"
    if "${ENGINE}" pull --force "${sif}" "${uri}" >> "${PIPELOG}" 2>&1; then
      log "Pulled ${label} SIF: ${sif}"
      return 0
    fi
    warn "Failed to pull ${label} image automatically."
  fi

  warn "To install manually:"
  warn "  ${ENGINE} pull \"${sif}\" \"${uri}\""
  return 1
}

funbgcex_host_deps_ok() {
  local dep=""
  local missing=()
  for dep in hmmscan hmmfetch hmmpress diamond; do
    if ! have "${dep}"; then
      missing+=("${dep}")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    warn "Host FunBGCeX mode requires external binaries on PATH: $(join_by ', ' "${missing[@]}")"
    return 1
  fi
  return 0
}

configure_funbgcex_host_runtime() {
  local cmd="$1"
  local py="$2"

  [[ -x "${cmd}" ]] || die "FunBGCeX command not executable: ${cmd}"
  if [[ "${py}" == */* ]]; then
    [[ -x "${py}" ]] || die "FunBGCeX python not executable: ${py}"
  else
    have "${py}" || die "FunBGCeX python not found in PATH: ${py}"
  fi
  funbgcex_host_deps_ok || die "Install HMMER and DIAMOND on the host, or use the repo-local FunBGCeX SIF build path."
  "${py}" -c "import Bio" >/dev/null 2>&1 || die "FunBGCeX python is missing Biopython support: ${py}"

  FUNBGCEX_RUNTIME="host"
  FUNBGCEX_CMD="${cmd}"
  FUNBGCEX_PYTHON_CMD="${py}"
  log "FunBGCeX runtime configured from host/venv: ${FUNBGCEX_CMD}"
}

bootstrap_funbgcex_venv() {
  local py
  py="$(resolve_python_cmd)"
  mkdir -p "${FUNBGCEX_PIP_CACHE}" "$(dirname "${FUNBGCEX_VENV_DIR}")"

  if [[ -x "${FUNBGCEX_VENV_DIR}/bin/funbgcex" && -x "${FUNBGCEX_VENV_DIR}/bin/python" ]]; then
    configure_funbgcex_host_runtime "${FUNBGCEX_VENV_DIR}/bin/funbgcex" "${FUNBGCEX_VENV_DIR}/bin/python"
    return 0
  fi

  log "Bootstrapping FunBGCeX environment in ${FUNBGCEX_VENV_DIR}"
  "${py}" -m venv "${FUNBGCEX_VENV_DIR}" >> "${PIPELOG}" 2>&1 || die "Failed to create FunBGCeX venv: ${FUNBGCEX_VENV_DIR}"
  "${FUNBGCEX_VENV_DIR}/bin/python" -m pip install --cache-dir "${FUNBGCEX_PIP_CACHE}" -U pip setuptools wheel >> "${PIPELOG}" 2>&1 \
    || die "Failed to upgrade pip/setuptools/wheel in ${FUNBGCEX_VENV_DIR}"
  "${FUNBGCEX_VENV_DIR}/bin/python" -m pip install --cache-dir "${FUNBGCEX_PIP_CACHE}" "funbgcex==${FUNBGCEX_VERSION}" biopython >> "${PIPELOG}" 2>&1 \
    || die "Failed to install funbgcex==${FUNBGCEX_VERSION} into ${FUNBGCEX_VENV_DIR}"

  configure_funbgcex_host_runtime "${FUNBGCEX_VENV_DIR}/bin/funbgcex" "${FUNBGCEX_VENV_DIR}/bin/python"
}

ensure_funbgcex_build_recipe() {
  [[ -s "${FUNBGCEX_DEF}" ]] || die "FunBGCeX definition file not found: ${FUNBGCEX_DEF}"
  [[ -s "${FUNBGCEX_BUILD_SCRIPT}" ]] || die "FunBGCeX build helper not found: ${FUNBGCEX_BUILD_SCRIPT}"
}

build_funbgcex_sif() {
  if [[ -s "${FUNBGCEX_SIF}" ]]; then
    log "FunBGCeX SIF present: ${FUNBGCEX_SIF}"
    return 0
  fi

  [[ "${AUTO_BUILD_FUNBGCEX_SIF}" == "1" ]] || return 1

  ensure_funbgcex_build_recipe
  mkdir -p "$(dirname "${FUNBGCEX_SIF}")"

  log "Building repo-local FunBGCeX SIF at ${FUNBGCEX_SIF}"
  log "FunBGCeX build recipe: ${FUNBGCEX_DEF}"
  if ENGINE="${ENGINE}" \
     SIF_OUT="${FUNBGCEX_SIF}" \
     DEF="${FUNBGCEX_DEF}" \
     DOCKERFILE="${FUNBGCEX_DOCKERFILE}" \
     bash "${FUNBGCEX_BUILD_SCRIPT}" >> "${PIPELOG}" 2>&1; then
    [[ -s "${FUNBGCEX_SIF}" ]] || die "FunBGCeX build reported success but SIF is missing: ${FUNBGCEX_SIF}"
    log "Built FunBGCeX SIF: ${FUNBGCEX_SIF}"
    return 0
  fi

  warn "Automatic FunBGCeX SIF build failed."
  warn "To retry manually:"
  warn "  ENGINE=${ENGINE} SIF_OUT=\"${FUNBGCEX_SIF}\" DEF=\"${FUNBGCEX_DEF}\" bash \"${FUNBGCEX_BUILD_SCRIPT}\""
  return 1
}

build_funbgcex_docker_image() {
  [[ "${AUTO_BUILD_FUNBGCEX_DOCKER}" == "1" ]] || return 1
  [[ -s "${FUNBGCEX_DOCKERFILE}" ]] || return 1

  log "Building repo-local FunBGCeX Docker image: ${FUNBGCEX_DOCKER_IMAGE}"
  docker build -t "${FUNBGCEX_DOCKER_IMAGE}" -f "${FUNBGCEX_DOCKERFILE}" "$(dirname "${FUNBGCEX_DOCKERFILE}")" >> "${PIPELOG}" 2>&1
}

ensure_funbgcex_runtime() {
  local cmd_path=""
  local py=""

  if [[ "${ENGINE}" == "docker" || "${FUNBGCEX_USE_DOCKER_IMAGE}" == "1" ]]; then
    if docker image inspect "${FUNBGCEX_DOCKER_IMAGE}" >/dev/null 2>&1; then
      log "FunBGCeX Docker image present: ${FUNBGCEX_DOCKER_IMAGE}"
      FUNBGCEX_RUNTIME="docker"
      FUNBGCEX_CMD="run_funbgcex"
      FUNBGCEX_PYTHON_CMD="python3"
      log "FunBGCeX runtime configured from Docker image: ${FUNBGCEX_DOCKER_IMAGE}"
      return 0
    fi
    if build_funbgcex_docker_image || ensure_docker_image "FunBGCeX" "${FUNBGCEX_DOCKER_IMAGE}"; then
      FUNBGCEX_RUNTIME="docker"
      FUNBGCEX_CMD="run_funbgcex"
      FUNBGCEX_PYTHON_CMD="python3"
      log "FunBGCeX runtime configured from Docker image: ${FUNBGCEX_DOCKER_IMAGE}"
      return 0
    fi
    warn "FunBGCeX Docker image is unavailable: ${FUNBGCEX_DOCKER_IMAGE}"
    [[ "${ENGINE}" == "docker" ]] && return 1
  fi

  if [[ -s "${FUNBGCEX_SIF}" ]]; then
    FUNBGCEX_RUNTIME="sif"
    FUNBGCEX_CMD="funbgcex"
    FUNBGCEX_PYTHON_CMD="python3"
    log "FunBGCeX SIF present: ${FUNBGCEX_SIF}"
    return 0
  fi

  if build_funbgcex_sif; then
    FUNBGCEX_RUNTIME="sif"
    FUNBGCEX_CMD="funbgcex"
    FUNBGCEX_PYTHON_CMD="python3"
    return 0
  fi

  if [[ -n "${FUNBGCEX_IMAGE_URI}" ]] && ensure_sif_or_prompt_pull "FunBGCeX" "${FUNBGCEX_SIF}" "${FUNBGCEX_IMAGE_URI}"; then
    FUNBGCEX_RUNTIME="sif"
    FUNBGCEX_CMD="funbgcex"
    FUNBGCEX_PYTHON_CMD="python3"
    return 0
  fi

  if [[ -x "${FUNBGCEX_VENV_DIR}/bin/funbgcex" && -x "${FUNBGCEX_VENV_DIR}/bin/python" ]]; then
    if funbgcex_host_deps_ok; then
      configure_funbgcex_host_runtime "${FUNBGCEX_VENV_DIR}/bin/funbgcex" "${FUNBGCEX_VENV_DIR}/bin/python"
      return 0
    fi
    warn "Ignoring existing FunBGCeX venv because host dependencies are incomplete."
  fi

  if have funbgcex; then
    cmd_path="$(command -v funbgcex)"
    py="$(resolve_python_cmd)"
    if funbgcex_host_deps_ok && "${py}" -c "import Bio" >/dev/null 2>&1; then
      configure_funbgcex_host_runtime "${cmd_path}" "${py}"
      return 0
    fi
    warn "Host funbgcex found at ${cmd_path}, but its dependencies are incomplete; continuing to other runtime options."
  fi

  if [[ "${FUNBGCEX_BOOTSTRAP}" == "1" ]]; then
    bootstrap_funbgcex_venv
    return 0
  fi

  warn "FunBGCeX SIF missing: ${FUNBGCEX_SIF}"
  warn "Automatic repo-local SIF build is controlled by AUTO_BUILD_FUNBGCEX_SIF=${AUTO_BUILD_FUNBGCEX_SIF}."
  [[ -n "${FUNBGCEX_IMAGE_URI}" ]] && warn "Optional FunBGCeX image source: ${FUNBGCEX_IMAGE_URI}"
  warn "Check your container builder, or provide FUNBGCEX_SIF manually."
  return 1
}

funbgcex_python_exec() {
  case "${FUNBGCEX_RUNTIME}" in
    sif) sing_exec "${FUNBGCEX_SIF}" "${FUNBGCEX_PYTHON_CMD}" "$@" ;;
    docker) CLUSTERWEAVE_CHILD_DOCKER_CPUS=1 docker_exec "${FUNBGCEX_DOCKER_IMAGE}" "${FUNBGCEX_PYTHON_CMD}" "$@" ;;
    host) "${FUNBGCEX_PYTHON_CMD}" "$@" ;;
    *) die "FunBGCeX runtime not configured before python exec" ;;
  esac
}

antismash_input_python_exec() {
  # The Docker worker is built from the pinned antiSMASH image and already
  # carries Biopython plus this repository. A sibling FunBGCeX container sees
  # the named /data volume but cannot see the worker-only /clusterweave path,
  # so preparation helpers must run in the worker process in Docker mode.
  if [[ "${ENGINE}" == "docker" ]]; then
    "$(resolve_python_cmd)" "$@"
  else
    funbgcex_python_exec "$@"
  fi
}

run_funbgcex_cli() {
  local gbk_dir="$1"
  local out_dir="$2"

  case "${FUNBGCEX_RUNTIME}" in
    sif)
      sing_exec "${FUNBGCEX_SIF}" bash -lc "
        set -euo pipefail
        export CUDA_VISIBLE_DEVICES=''
        export TF_CPP_MIN_LOG_LEVEL=2
        funbgcex '${gbk_dir}' '${out_dir}' --workers '${WORKERS}'
      "
      ;;
    docker)
      CLUSTERWEAVE_CHILD_DOCKER_CPUS="${WORKERS}" docker_exec "${FUNBGCEX_DOCKER_IMAGE}" run_funbgcex "${gbk_dir}" "${out_dir}" "${WORKERS}"
      ;;
    host)
      CUDA_VISIBLE_DEVICES="" TF_CPP_MIN_LOG_LEVEL=2 "${FUNBGCEX_CMD}" "${gbk_dir}" "${out_dir}" --workers "${WORKERS}"
      ;;
    *)
      die "FunBGCeX runtime not configured before CLI execution"
      ;;
  esac
}

ensure_funannotate_build_recipe() {
  [[ -s "${FUNANNOTATE_BUILD_SCRIPT}" ]] || die "funannotate build helper not found: ${FUNANNOTATE_BUILD_SCRIPT}"
}

ensure_funannotate_docker_runtime() {
  local image=""
  image="$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")"
  [[ -n "${image}" ]] || return 1

  if docker image inspect "${image}" >/dev/null 2>&1; then
    log "funannotate Docker image present: ${image}"
    return 0
  fi

  if [[ "${AUTO_BUILD_FUNANNOTATE_DOCKER}" == "1" ]]; then
    ensure_funannotate_build_recipe
    log "Building repo-local funannotate Docker image: ${image}"
    if IMAGE_TAG="${image}"        FUNANNOTATE_BASE_IMAGE="$(docker_image_from_uri "${FUNANNOTATE_BASE_IMAGE_URI}")"        bash "${FUNANNOTATE_BUILD_SCRIPT}" docker >> "${PIPELOG}" 2>&1; then
      docker image inspect "${image}" >/dev/null 2>&1 || die "funannotate Docker build reported success but image is missing: ${image}"
      log "Built funannotate Docker image: ${image}"
      return 0
    fi
    warn "Automatic funannotate Docker image build failed."
    warn "To retry manually: IMAGE_TAG="${image}" FUNANNOTATE_BASE_IMAGE="$(docker_image_from_uri "${FUNANNOTATE_BASE_IMAGE_URI}")" bash "${FUNANNOTATE_BUILD_SCRIPT}" docker"
  fi

  ensure_docker_image "funannotate" "${image}"
}

ensure_funannotate_sif_runtime() {
  if [[ -s "${FUNANNOTATE_SIF}" ]]; then
    log "funannotate SIF present: ${FUNANNOTATE_SIF}"
    return 0
  fi

  if [[ "${AUTO_BUILD_FUNANNOTATE_SIF}" == "1" ]]; then
    ensure_funannotate_build_recipe
    mkdir -p "$(dirname "${FUNANNOTATE_SIF}")"
    log "Building repo-local funannotate SIF at ${FUNANNOTATE_SIF}"
    if ENGINE="${ENGINE}"        SIF_OUT="${FUNANNOTATE_SIF}"        FUNANNOTATE_BASE_IMAGE="$(docker_image_from_uri "${FUNANNOTATE_BASE_IMAGE_URI}")"        bash "${FUNANNOTATE_BUILD_SCRIPT}" sif >> "${PIPELOG}" 2>&1; then
      [[ -s "${FUNANNOTATE_SIF}" ]] || die "funannotate SIF build reported success but SIF is missing: ${FUNANNOTATE_SIF}"
      log "Built funannotate SIF: ${FUNANNOTATE_SIF}"
      return 0
    fi
    warn "Automatic funannotate SIF build failed."
    warn "To retry manually: ENGINE=${ENGINE} SIF_OUT="${FUNANNOTATE_SIF}" FUNANNOTATE_BASE_IMAGE="$(docker_image_from_uri "${FUNANNOTATE_BASE_IMAGE_URI}")" bash "${FUNANNOTATE_BUILD_SCRIPT}" sif"
  fi

  warn "funannotate SIF missing: ${FUNANNOTATE_SIF}"
  warn "Automatic repo-local SIF build is controlled by AUTO_BUILD_FUNANNOTATE_SIF=${AUTO_BUILD_FUNANNOTATE_SIF}."
  warn "Provide a baked FUNANNOTATE_SIF or build it with ${FUNANNOTATE_BUILD_SCRIPT}."
  return 1
}

ensure_primary_tooling() {
  if [[ "${ENGINE}" == "docker" ]]; then
    if have antismash; then
      log "antiSMASH available on worker PATH."
    else
      ensure_docker_image "antiSMASH" "${ANTISMASH_DOCKER_IMAGE}" \
        || die "antiSMASH is required but unavailable. Install it in the worker or provide ANTISMASH_DOCKER_IMAGE."
    fi
  else
    ensure_sif_or_prompt_pull "antiSMASH" "${ANTISMASH_SIF}" "${ANTISMASH_IMAGE_URI}" \
      || die "antiSMASH is required but unavailable. Provide ANTISMASH_SIF or allow pulling from ${ANTISMASH_IMAGE_URI}."
  fi
  if [[ "${HAS_FUNGAL_ROUTES}" -eq 1 ]]; then
    ensure_funbgcex_runtime \
      || die "FunBGCeX is required for fungal routes but unavailable. Provide FUNBGCEX_SIF manually or fix the repo-local SIF build path."
  else
    log "Skipping FunBGCeX runtime bootstrap: no fungal routes are present."
  fi
}

ensure_annotation_tooling() {
  local braker_ok=0
  local fun_ok=0
  local need_braker=0
  local need_fun=0
  local method
  local old_ifs="$IFS"
  local methods=()

  IFS=','
  read -r -a methods <<< "${ANNOTATION_FALLBACK_ORDER}"
  IFS="$old_ifs"

  for method in "${methods[@]}"; do
    method="$(echo "${method}" | tr -d '[:space:]')"
    case "${method}" in
      braker3)
        if [[ "${BRAKER3_ENABLED}" == "1" ]]; then
          need_braker=1
        else
          warn "BRAKER3 appears in ANNOTATION_FALLBACK_ORDER but BRAKER3_ENABLED=0; BRAKER3 will be skipped."
        fi
        ;;
      funannotate) need_fun=1 ;;
      none|skip|off) ;;
      "") ;;
      *) warn "Unknown annotation fallback method in ANNOTATION_FALLBACK_ORDER: ${method}" ;;
    esac
  done

  if [[ "${need_braker}" -eq 1 ]]; then
    if command -v braker.pl >/dev/null 2>&1; then
      braker_ok=1
      log "BRAKER3 available on host PATH (braker.pl)."
    elif [[ "${ENGINE}" == "docker" ]] && ensure_docker_image "BRAKER3" "$(docker_image_from_uri "${BRAKER_IMAGE_URI}")"; then
      braker_ok=1
    elif [[ "${ENGINE}" != "docker" ]] && ensure_sif_or_prompt_pull "BRAKER3" "${BRAKER_SIF}" "${BRAKER_IMAGE_URI}"; then
      braker_ok=1
    fi
  fi

  if [[ "${need_fun}" -eq 1 ]]; then
    if command -v funannotate >/dev/null 2>&1; then
      fun_ok=1
      log "funannotate available on host PATH."
    elif [[ "${ENGINE}" == "docker" ]] && ensure_funannotate_docker_runtime; then
      fun_ok=1
    elif [[ "${ENGINE}" != "docker" ]] && ensure_funannotate_sif_runtime; then
      fun_ok=1
    fi
  fi

  if [[ "${need_braker}" -eq 1 && "${braker_ok}" -eq 0 ]]; then
    die "BRAKER3 is required by ANNOTATION_FALLBACK_ORDER but unavailable. Enable image/tooling or remove braker3 from order."
  fi
  if [[ "${need_fun}" -eq 1 && "${fun_ok}" -eq 0 ]]; then
    die "funannotate is required by ANNOTATION_FALLBACK_ORDER but unavailable. Install funannotate or provide FUNANNOTATE_SIF."
  fi
  if [[ "${need_braker}" -eq 0 && "${need_fun}" -eq 0 ]]; then
    warn "No annotation fallback methods configured. Annotated GenBank inputs can still run; FASTA-only inputs may be dropped."
  fi
}

run_braker3_to_gbk() {
  local genome_id="$1"
  local fasta="$2"
  local out_gbk="$3"
  [[ -s "${fasta}" ]] || return 1

  local braker_out="${RESULTS_ROOT}/braker3/${genome_id}"
  local braker_log="${WORK_ROOT}/logs/${genome_id}.braker3.log"
  local braker_species="${BRAKER_SPECIES_PREFIX}_${genome_id}"
  local gff3=""
  local tmp_out="${out_gbk}.tmp"
  local ev_args=()

  if [[ -z "${BRAKER_BAM}" && -z "${BRAKER_PROT_SEQ}" ]]; then
    warn "${genome_id}: BRAKER3 requires evidence (--bam or --prot_seq). Set BRAKER_BAM or BRAKER_PROT_SEQ; skipping BRAKER3."
    return 3
  fi
  if [[ -n "${BRAKER_BAM}" ]]; then
    ev_args=(--bam "${BRAKER_BAM}")
  else
    ev_args=(--prot_seq "${BRAKER_PROT_SEQ}")
  fi

  : > "${braker_log}"
  mkdir -p "${braker_out}"
  rm -f "${tmp_out}" 2>/dev/null || true
  log "${genome_id}: trying BRAKER3 annotation (outdir=${braker_out})"

  if [[ "${ENGINE}" == "docker" ]]; then
    if ! CLUSTERWEAVE_CHILD_DOCKER_CPUS="${ANNO_CPUS}" docker_exec "$(docker_image_from_uri "${BRAKER_IMAGE_URI}")" braker.pl --genome "${fasta}" "${ev_args[@]}" --workingdir "${braker_out}" --species "${braker_species}" --fungus --gff3 --threads "${ANNO_CPUS}" >> "${braker_log}" 2>&1; then
      warn "${genome_id}: BRAKER3 failed (see ${braker_log})"
      return 2
    fi
  elif [[ -f "${BRAKER_SIF}" ]]; then
    if ! sing_exec "${BRAKER_SIF}" braker.pl --genome "${fasta}" "${ev_args[@]}" --workingdir "${braker_out}" --species "${braker_species}" --fungus --gff3 --threads "${ANNO_CPUS}" >> "${braker_log}" 2>&1; then
      warn "${genome_id}: BRAKER3 failed (see ${braker_log})"
      return 2
    fi
  elif command -v braker.pl >/dev/null 2>&1; then
    if ! braker.pl --genome "${fasta}" "${ev_args[@]}" --workingdir "${braker_out}" --species "${braker_species}" --fungus --gff3 --threads "${ANNO_CPUS}" >> "${braker_log}" 2>&1; then
      warn "${genome_id}: BRAKER3 failed (see ${braker_log})"
      return 2
    fi
  else
    warn "${genome_id}: BRAKER3 unavailable (missing BRAKER_SIF and braker.pl); skipping BRAKER3"
    return 3
  fi

  gff3="$(find "${braker_out}" -type f \( -name 'braker.gff3' -o -name '*.gff3' \) | head -n1)"
  if [[ -z "${gff3}" || ! -s "${gff3}" ]]; then
    warn "${genome_id}: BRAKER3 produced no GFF3 (see ${braker_log})"
    return 4
  fi

  if ! "${VENV_PY}" "${CONVERT_PY}" --fasta "${fasta}" --gff3 "${gff3}" --out_gbk "${tmp_out}" >> "${braker_log}" 2>&1; then
    warn "${genome_id}: BRAKER3 GFF3->GBK conversion failed (see ${braker_log})"
    return 5
  fi

  if [[ -s "${tmp_out}" ]] && gbk_has_cds_and_translation "${tmp_out}"; then
    mv -f "${tmp_out}" "${out_gbk}"
    log "${genome_id}: BRAKER3 produced staged GBK with CDS+translations"
    return 0
  fi

  warn "${genome_id}: BRAKER3 output GBK lacks CDS/translations"
  return 6
}

remap_gbk_ids_from_fasta_hashes() {
  local original_fasta="$1"
  local renamed_fasta="$2"
  local in_gbk="$3"
  local out_gbk="$4"
  local map_tsv="$5"
  funbgcex_python_exec - "$original_fasta" "$renamed_fasta" "$in_gbk" "$out_gbk" "$map_tsv" <<'PY'
import hashlib
import sys
from collections import defaultdict
from Bio import SeqIO

orig_fa, ren_fa, in_gbk, out_gbk, map_tsv = sys.argv[1:]

def hash_to_ids(path):
    out = defaultdict(list)
    for rec in SeqIO.parse(path, "fasta"):
        sid = (rec.id or "").split()[0]
        if not sid:
            continue
        h = hashlib.md5(str(rec.seq).upper().encode("utf-8")).hexdigest()
        out[h].append(sid)
    return out

orig = hash_to_ids(orig_fa)
ren = hash_to_ids(ren_fa)

ren_to_orig = {}
for h, ren_ids in ren.items():
    if len(ren_ids) != 1:
        continue
    orig_ids = orig.get(h, [])
    if len(orig_ids) != 1:
        continue
    ren_to_orig[ren_ids[0]] = orig_ids[0]

with open(map_tsv, "w", encoding="utf-8") as oh:
    oh.write("renamed_id\toriginal_id\n")
    for rid in sorted(ren_to_orig):
        oh.write(f"{rid}\t{ren_to_orig[rid]}\n")

records = list(SeqIO.parse(in_gbk, "genbank"))
remapped = 0
for rec in records:
    old = (rec.id or "").split()[0]
    new = ren_to_orig.get(old)
    if not new or new == old:
        continue
    rec.id = new
    rec.name = new[:16]
    if rec.description == old:
        rec.description = new
    elif rec.description.startswith(old + " "):
        rec.description = new + rec.description[len(old):]
    rec.annotations["accessions"] = [new]
    remapped += 1

SeqIO.write(records, out_gbk, "genbank")
print(f"map_entries={len(ren_to_orig)} total_records={len(records)} remapped_records={remapped}")
PY
}
run_funannotate_predict_to_gbk() {
  local genome_id="$1"
  local fasta="$2"
  local out_gbk="$3"
  [[ -s "${fasta}" ]] || return 1

  local fun_out="${RESULTS_ROOT}/funannotate/${genome_id}"
  local fun_run="${WORK_ROOT}/tmp/${genome_id}/funannotate_run"
  local fun_tmp="${WORK_ROOT}/tmp/${genome_id}/funannotate_tmp"
  local fun_log="${WORK_ROOT}/logs/${genome_id}.funannotate.log"
  local tmp_out="${out_gbk}.tmp"
  local remap_out="${out_gbk}.remap"
  local pred_gbk=""
  local pred_gff3=""
  local prep_dir="${WORK_ROOT}/tmp/${genome_id}/funannotate_prep"
  local sorted_fa="${prep_dir}/${genome_id}.sorted.fna"
  local cleaned_fa="${prep_dir}/${genome_id}.clean.fna"
  local predict_fa="${cleaned_fa}"
  local id_map_tsv="${WORK_ROOT}/tmp/${genome_id}/funannotate_id_map.tsv"
  local safe_name="${genome_id//_/}"
  resolve_funannotate_policy "${genome_id}"
  local species_name="${FUNANNOTATE_RESOLVED_SPECIES%.}"
  local busco_db="${FUNANNOTATE_RESOLVED_BUSCO_DB}"
  local busco_seed_species="${FUNANNOTATE_BUSCO_SEED_SPECIES}"
  local fun_predict_extra=()
  busco_db="$(printf '%s' "${busco_db}" | tr -d '[:space:]')"
  if [[ -z "${busco_db}" || "${busco_db}" == "{}" || "${busco_db}" == "none" || "${busco_db}" == "null" ]]; then
    warn "${genome_id}: invalid FUNANNOTATE_BUSCO_DB='${busco_db}'; using dikarya"
    busco_db="dikarya"
  fi
  busco_seed_species="$(printf '%s' "${busco_seed_species}" | tr -d '[:space:]')"
  if [[ -n "${busco_seed_species}" ]]; then
    case "${busco_seed_species}" in
      "{}"|none|null)
        warn "${genome_id}: ignoring invalid FUNANNOTATE_BUSCO_SEED_SPECIES='${busco_seed_species}'"
        ;;
      *)
        fun_predict_extra+=(--busco_seed_species "${busco_seed_species}")
        log "${genome_id}: using BUSCO seed species override: ${busco_seed_species}"
        ;;
    esac
  fi
  if [[ "${species_name}" == "Fungal_sp" || "${species_name}" == "Fungal sp" ]]; then
    local gnorm="${genome_id//[^A-Za-z0-9_]/_}"
    local g1="${gnorm%%_*}"
    local rest="${gnorm#*_}"
    local g2="${rest%%_*}"
    if [[ -n "${g1}" && -n "${g2}" ]]; then
      species_name="${g1} ${g2}"
    fi
  fi
  : > "${fun_log}"
  mkdir -p "${fun_out}" "${prep_dir}" "${fun_tmp}"
  rm -rf "${fun_run}" 2>/dev/null || true
  mkdir -p "${fun_run}"
  rm -f "${tmp_out}" "${remap_out}" "${sorted_fa}" "${cleaned_fa}" "${id_map_tsv}" 2>/dev/null || true

  local fun_cmd="funannotate"
  local use_sif=0
  local use_docker=0

  if [[ "${ENGINE}" == "docker" ]]; then
    use_docker=1
  elif [[ -f "${FUNANNOTATE_SIF}" ]]; then
    use_sif=1
    if sing_exec "${FUNANNOTATE_SIF}" test -x "/venv/bin/funannotate" >/dev/null 2>&1; then
      fun_cmd="/venv/bin/funannotate"
    fi
  elif ! command -v funannotate >/dev/null 2>&1; then
    warn "${genome_id}: funannotate unavailable (missing FUNANNOTATE_SIF and funannotate binary); skipping funannotate"
    return 3
  fi

  if ! busco_db="$(validate_funannotate_busco_db "${busco_db}" "${FUNANNOTATE_RESOLVED_SOURCE}" "${genome_id}" "${fun_cmd}" "${use_docker}" "${use_sif}")"; then
    warn "${genome_id}: no installed funannotate BUSCO database available for predict"
    return 2
  fi
  log "${genome_id}: funannotate policy ${FUNANNOTATE_RESOLVED_SOURCE}: species='${species_name}' busco_db='${busco_db}'"

  log "${genome_id}: running funannotate prepare workflow (sort + clean)"
  tool_activity_emit_progress "${genome_id}" "funannotate" "prepare" "Preparing assembly"
  if [[ "${use_docker}" -eq 1 ]]; then
    if ! CLUSTERWEAVE_CHILD_DOCKER_CPUS="${ANNO_CPUS}" docker_exec "$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")" "${fun_cmd}" sort -i "${fasta}" -o "${sorted_fa}" --minlen 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate sort failed (see ${fun_log})"
      return 2
    fi
    if ! CLUSTERWEAVE_CHILD_DOCKER_CPUS="${ANNO_CPUS}" docker_exec "$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")" "${fun_cmd}" clean -i "${sorted_fa}" -o "${cleaned_fa}" -m 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate clean failed; using sorted FASTA for predict"
      cp -f "${sorted_fa}" "${cleaned_fa}"
    fi
  elif [[ "${use_sif}" -eq 1 ]]; then
    if ! sing_exec "${FUNANNOTATE_SIF}" "${fun_cmd}" sort -i "${fasta}" -o "${sorted_fa}" --minlen 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate sort failed (see ${fun_log})"
      return 2
    fi
    if ! sing_exec "${FUNANNOTATE_SIF}" "${fun_cmd}" clean -i "${sorted_fa}" -o "${cleaned_fa}" -m 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate clean failed; using sorted FASTA for predict"
      cp -f "${sorted_fa}" "${cleaned_fa}"
    fi
  else
    if ! "${fun_cmd}" sort -i "${fasta}" -o "${sorted_fa}" --minlen 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate sort failed (see ${fun_log})"
      return 2
    fi
    if ! "${fun_cmd}" clean -i "${sorted_fa}" -o "${cleaned_fa}" -m 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate clean failed; using sorted FASTA for predict"
      cp -f "${sorted_fa}" "${cleaned_fa}"
    fi
  fi

  [[ -s "${predict_fa}" ]] || { warn "${genome_id}: prepared FASTA missing for funannotate predict"; return 2; }

  local no_protein_alignments="${WORK_ROOT}/tmp/${genome_id}/funannotate_no_protein_alignments.gff3"
  funannotate_predict_attempt() {
    local attempt_label="$1"
    shift
    local attempt_extra=("$@")
    rm -rf "${fun_run}" 2>/dev/null || true
    mkdir -p "${fun_run}"
    log "${genome_id}: trying funannotate predict (${attempt_label}, outdir=${fun_run})"
    tool_activity_emit_progress "${genome_id}" "funannotate" "predict" "Predicting genes"
    if [[ "${use_docker}" -eq 1 ]]; then
      CLUSTERWEAVE_CHILD_DOCKER_CPUS="${ANNO_CPUS}" run_tool_with_activity "${genome_id}" "funannotate" "predict" "${fun_log}" "${fun_log}" docker_exec "$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")" "${fun_cmd}" predict -i "${predict_fa}" -o "${fun_run}" --species "${species_name}" --organism fungus --busco_db "${busco_db}" "${fun_predict_extra[@]}" "${attempt_extra[@]}" --cpus "${ANNO_CPUS}" --name "${safe_name}_" --tmpdir "${fun_tmp}" --force
    elif [[ "${use_sif}" -eq 1 ]]; then
      run_tool_with_activity "${genome_id}" "funannotate" "predict" "${fun_log}" "${fun_log}" sing_exec "${FUNANNOTATE_SIF}" "${fun_cmd}" predict -i "${predict_fa}" -o "${fun_run}" --species "${species_name}" --organism fungus --busco_db "${busco_db}" "${fun_predict_extra[@]}" "${attempt_extra[@]}" --cpus "${ANNO_CPUS}" --name "${safe_name}_" --tmpdir "${fun_tmp}" --force
    else
      run_tool_with_activity "${genome_id}" "funannotate" "predict" "${fun_log}" "${fun_log}" "${fun_cmd}" predict -i "${predict_fa}" -o "${fun_run}" --species "${species_name}" --organism fungus --busco_db "${busco_db}" "${fun_predict_extra[@]}" "${attempt_extra[@]}" --cpus "${ANNO_CPUS}" --name "${safe_name}_" --tmpdir "${fun_tmp}" --force
    fi
  }

  local predict_succeeded=0
  local training_fallback_floor=""
  local -a training_retry_args=()
  if funannotate_predict_attempt "standard"; then
    predict_succeeded=1
  else
    # Classify the structured AUGUSTUS/BUSCO failure before considering the
    # independent protein-to-genome retry. A bare protein_alignments.gff3 path
    # in normal funannotate output is not evidence of a p2g failure.
    if training_fallback_floor="$(funannotate_busco_training_fallback_threshold "${fun_log}")"; then
      training_retry_args=(--min_training_models "${training_fallback_floor}")
      warn "${genome_id}: validated BUSCO models meet the bounded fallback floor; retrying funannotate with --min_training_models ${training_fallback_floor}"
      if funannotate_predict_attempt "reduced-training-model-threshold" "${training_retry_args[@]}"; then
        predict_succeeded=1
      fi
    fi

    if [[ "${predict_succeeded}" -eq 0 && "${FUNANNOTATE_RETRY_WITHOUT_PROTEIN_EVIDENCE}" == "1" ]] && funannotate_predict_failed_in_p2g "${fun_log}"; then
      warn "${genome_id}: funannotate protein-to-genome evidence mapping failed; retrying without default UniProt protein-to-genome evidence"
      printf '%s\n' '##gff-version 3' > "${no_protein_alignments}"
      if [[ -n "${training_fallback_floor}" ]]; then
        if funannotate_predict_attempt "reduced-training-and-no-protein-evidence" "${training_retry_args[@]}" --protein_alignments "${no_protein_alignments}"; then
          predict_succeeded=1
        fi
      elif funannotate_predict_attempt "no-protein-evidence" --protein_alignments "${no_protein_alignments}"; then
        predict_succeeded=1
      fi
    fi
  fi

  if [[ "${predict_succeeded}" -eq 0 ]]; then
    rsync -a --delete "${fun_run}/" "${fun_out}/" >/dev/null 2>&1 || true
    funannotate_record_predict_failure "${genome_id}" "${fun_log}" "${busco_db}" "${FUNANNOTATE_RESOLVED_SOURCE}"
    if [[ -n "${training_fallback_floor}" && -n "${FUNANNOTATE_LAST_FAILURE_DETAIL}" ]]; then
      FUNANNOTATE_LAST_FAILURE_DETAIL="${FUNANNOTATE_LAST_FAILURE_DETAIL} fallback_min_training_models=${training_fallback_floor}"
    fi
    warn "${genome_id}: funannotate predict failed after eligible bounded retries (see ${fun_log})"
    return 2
  fi

  pred_gbk="$(find "${fun_run}" -type f -path '*/predict_results/*.gbk' | head -n1)"
  if [[ -n "${pred_gbk}" && -s "${pred_gbk}" ]] && gbk_has_cds_and_translation "${pred_gbk}"; then
    cp -f "${pred_gbk}" "${out_gbk}"
    if remap_gbk_ids_from_fasta_hashes "${fasta}" "${predict_fa}" "${out_gbk}" "${remap_out}" "${id_map_tsv}" >> "${fun_log}" 2>&1; then
      mv -f "${remap_out}" "${out_gbk}"
      log "${genome_id}: remapped final GBK record IDs to original FASTA IDs (map=${id_map_tsv})"
    else
      warn "${genome_id}: could not remap GBK record IDs to original FASTA IDs; keeping funannotate IDs"
    fi
    rsync -a --delete "${fun_run}/" "${fun_out}/" >/dev/null 2>&1 || true
    log "${genome_id}: funannotate produced GBK with CDS+translations"
    return 0
  fi

  pred_gff3="$(find "${fun_run}" -type f -path '*/predict_results/*.gff3' | head -n1)"
  if [[ -n "${pred_gff3}" && -s "${pred_gff3}" ]]; then
    if "${VENV_PY}" "${CONVERT_PY}" --fasta "${predict_fa}" --gff3 "${pred_gff3}" --out_gbk "${tmp_out}" >> "${fun_log}" 2>&1; then
      if [[ -s "${tmp_out}" ]] && gbk_has_cds_and_translation "${tmp_out}"; then
        mv -f "${tmp_out}" "${out_gbk}"
        if remap_gbk_ids_from_fasta_hashes "${fasta}" "${predict_fa}" "${out_gbk}" "${remap_out}" "${id_map_tsv}" >> "${fun_log}" 2>&1; then
          mv -f "${remap_out}" "${out_gbk}"
          log "${genome_id}: remapped converted GBK record IDs to original FASTA IDs (map=${id_map_tsv})"
        else
          warn "${genome_id}: could not remap converted GBK record IDs to original FASTA IDs; keeping funannotate IDs"
        fi
        rsync -a --delete "${fun_run}/" "${fun_out}/" >/dev/null 2>&1 || true
        log "${genome_id}: funannotate GFF3 converted to GBK with CDS+translations"
        return 0
      fi
    fi
  fi

  rsync -a --delete "${fun_run}/" "${fun_out}/" >/dev/null 2>&1 || true
  warn "${genome_id}: funannotate did not yield usable GBK with CDS+translations"
  return 4
}

annotate_genome_with_fallbacks() {
  local genome_id="$1"
  local fasta="$2"
  local out_gbk="$3"
  local method
  local order_csv="${ANNOTATION_FALLBACK_ORDER}"
  local old_ifs="$IFS"
  ANNOTATION_FALLBACK_METHOD=""
  ANNOTATION_FALLBACK_FAILURE_REASON=""
  ANNOTATION_FALLBACK_FAILURE_DETAIL=""
  IFS=','
  read -r -a methods <<< "${order_csv}"
  IFS="$old_ifs"

  for method in "${methods[@]}"; do
    method="$(echo "${method}" | tr -d '[:space:]')"
    case "${method}" in
      braker3)
        if [[ "${BRAKER3_ENABLED}" != "1" ]]; then
          warn "${genome_id}: BRAKER3 disabled (BRAKER3_ENABLED=0); skipping braker3 fallback."
          continue
        fi
        genome_annotation_decision "${genome_id}" "yes" "braker3" "BRAKER3 annotation required"
        if run_braker3_to_gbk "${genome_id}" "${fasta}" "${out_gbk}"; then
          ANNOTATION_FALLBACK_METHOD="braker3"
          return 0
        fi
        ;;
      funannotate)
        genome_annotation_decision "${genome_id}" "yes" "funannotate" "Funannotate annotation required"
        if run_funannotate_predict_to_gbk "${genome_id}" "${fasta}" "${out_gbk}"; then
          ANNOTATION_FALLBACK_METHOD="funannotate"
          return 0
        fi
        if [[ -n "${FUNANNOTATE_LAST_FAILURE_STATUS}" ]]; then
          ANNOTATION_FALLBACK_FAILURE_REASON="${FUNANNOTATE_LAST_FAILURE_STATUS}"
          ANNOTATION_FALLBACK_FAILURE_DETAIL="${FUNANNOTATE_LAST_FAILURE_DETAIL}"
        fi
        ;;
      "") ;;
      *)
        warn "${genome_id}: unknown annotation fallback method in ANNOTATION_FALLBACK_ORDER: ${method}"
        ;;
    esac
  done
  return 1
}

###############################################################################
# antiSMASH flag helper (unchanged from your script)
###############################################################################
ANTISMASH_FLAGS_CANDIDATES=(
  --verbose
  --fullhmmer
  --asf
  --clusterhmmer
  --tigrfam
  --cc-mibig
  --cb-general
  --cb-knownclusters
  --cb-subclusters
  --pfam2go
  --smcog-trees
  --tfbs
  --rre
  --allow-long-headers
)

antismash_supported_flags() {
  local taxon_group="${1:-fungi}"
  local genefinding_tool="${2:-none}"
  local help
  help="$(antismash_exec antismash --help-showall 2>&1 || true)"

  # antiSMASH 8.0.4 supports both arguments and they define the scientific
  # prediction route, so never silently omit them.
  local out=(--taxon "${taxon_group}" --genefinding-tool "${genefinding_tool}")
  local i=0
  while [[ $i -lt ${#ANTISMASH_FLAGS_CANDIDATES[@]} ]]; do
    local tok="${ANTISMASH_FLAGS_CANDIDATES[$i]}"
    if [[ "${tok}" == --* ]]; then
      if grep -Fq -- "${tok}" <<< "${help}"; then out+=("${tok}"); fi
    fi
    i=$((i+1))
  done

  printf "%s\n" "${out[@]}"
}

###############################################################################
# Done checks (RESULTS_ROOT canonical)
###############################################################################
antismash_done() {
  local outdir="$1"
  [[ -d "${outdir}" ]] || return 1
  [[ -f "${outdir}/.done" ]] || return 1
  [[ -s "${outdir}/index.html" ]] || return 1

  # The marker is written only after a successful process and assembled output.
  # Also require browseable antiSMASH state, not interrupted region GBKs alone.
  if [[ -n "$(find "${outdir}" -maxdepth 3 -type f \( -name "regions.js" -o -name "*.antismash.json" -o -name "overview*.js" \) -print -quit 2>/dev/null)" ]]; then
    return 0
  fi
  return 1
}

funbgcex_outputs_valid() {
  local outdir="$1"
  [[ -d "${outdir}" ]] || return 1
  [[ -n "$(find "${outdir}" -maxdepth 4 -type f \
    \( -name "allBGCs.csv" -o -name "allBGCs.html" -o -name "BGCs.csv" -o -name "results.html" \) \
    -size +0c -print -quit 2>/dev/null)" ]]
}

funbgcex_done() {
  local outdir="$1"
  [[ -f "${outdir}/.done" ]] || return 1
  funbgcex_outputs_valid "${outdir}"
}

###############################################################################
# GBK diagnostics/filtering (run via the configured FunBGCeX runtime)
###############################################################################
gbk_diag_summary() {
  local gbk="$1"
  local label="${2:-GBK}"
  funbgcex_python_exec - "$gbk" "$label" <<'PY'
import sys
from Bio import SeqIO
p, label = sys.argv[1], sys.argv[2]
nrec=0
cds=0
cds_tx=0
bad_tx=0
try:
    for rec in SeqIO.parse(p, "genbank"):
        nrec += 1
        for feat in rec.features:
            if feat.type != "CDS":
                continue
            cds += 1
            q = feat.qualifiers or {}
            txs = q.get("translation", [])
            if any(str(t).strip() for t in txs):
                cds_tx += 1
            else:
                bad_tx += 1
except Exception as e:
    print(f"{label}: PARSE_FAIL file={p} err={e}")
    sys.exit(0)
print(f"{label}: file={p}")
print(f"{label}: records={nrec} cds={cds} cds_with_nonempty_translation={cds_tx} cds_missing_or_empty_translation={bad_tx}")
PY
}

filter_gbk_drop_gene_less_records() {
  local in_gbk="$1"
  local out_gbk="$2"
  funbgcex_python_exec - "$in_gbk" "$out_gbk" <<'PY'
import sys
from Bio import SeqIO

inp, outp = sys.argv[1], sys.argv[2]
out_recs=[]
dropped=0
kept=0

for rec in SeqIO.parse(inp, "genbank"):
    has_cds = any(f.type == "CDS" for f in (rec.features or []))
    if not has_cds:
        dropped += 1
        continue
    rec.annotations.setdefault("molecule_type","DNA")
    out_recs.append(rec)
    kept += 1

SeqIO.write(out_recs, outp, "genbank")
print(f"kept_records={kept} dropped_records={dropped}")
PY
}


list_genbank_record_ids() {
  local gbk="$1"
  local min_record_bp="${2:-${ANTISMASH_MIN_RECORD_BP:-1000}}"
  funbgcex_python_exec - "${gbk}" "${min_record_bp}" <<'PY'
import sys
from Bio import SeqIO

path = sys.argv[1]
min_record_bp = int(sys.argv[2])
if min_record_bp < 1:
    raise RuntimeError(f"Invalid antiSMASH minimum record length: {min_record_bp}")
seen = set()
for record in SeqIO.parse(path, "genbank"):
    record_id = str(record.id or record.name or "").strip()
    if not record_id or "\t" in record_id or "\n" in record_id or "\r" in record_id:
        raise RuntimeError(f"Invalid GenBank record ID in {path}: {record_id!r}")
    if record_id in seen:
        raise RuntimeError(f"Duplicate GenBank record ID in {path}: {record_id}")
    seen.add(record_id)
    if len(record.seq) < min_record_bp:
        continue
    print(record_id)
PY
}


safe_antismash_record_id() {
  local record_id="${1:-record}"
  local safe_id=""
  safe_id="$(printf '%s' "${record_id}" | LC_ALL=C tr -c 'A-Za-z0-9._-' '_')"
  safe_id="${safe_id:0:120}"
  case "${safe_id}" in
    ""|.|..) safe_id="record" ;;
  esac
  if [[ "${safe_id}" == -* || "${safe_id}" == .* ]]; then
    safe_id="record_${safe_id}"
  fi
  printf '%s\n' "${safe_id}"
}


antismash_record_ids_are_stable() {
  local record_ids_file="$1"
  local record_id=""
  local safe_record_id=""

  ANTISMASH_UNSTABLE_RECORD_ID=""
  ANTISMASH_UNSTABLE_SAFE_ID=""
  while IFS= read -r record_id || [[ -n "${record_id}" ]]; do
    safe_record_id="$(safe_antismash_record_id "${record_id}")"
    if [[ "${safe_record_id}" != "${record_id}" ]]; then
      ANTISMASH_UNSTABLE_RECORD_ID="${record_id}"
      ANTISMASH_UNSTABLE_SAFE_ID="${safe_record_id}"
      return 1
    fi
  done < "${record_ids_file}"
}

antismash_public_failure_message() {
  local error_log="${1:-}"
  local record_id=""
  if [[ -s "${error_log}" ]] && grep -qi 'location contains overlapping exons' "${error_log}"; then
    record_id="$(sed -nE 's/^([A-Za-z0-9_.-]+): location contains overlapping exons.*$/\1/p' "${error_log}" | head -n1)"
    if [[ -n "${record_id}" ]]; then
      printf 'antiSMASH rejected record %s: overlapping exon coordinates in an annotated feature\n' "${record_id}"
    else
      printf 'antiSMASH rejected an annotated feature with overlapping exon coordinates\n'
    fi
  elif [[ -s "${error_log}" ]] && grep -Eqi 'no space left on device|disk quota exceeded' "${error_log}"; then
    printf 'antiSMASH could not write its results because storage was exhausted\n'
  elif [[ -s "${error_log}" ]] && grep -Eqi 'out of memory|cannot allocate memory|killed' "${error_log}"; then
    printf 'antiSMASH exceeded the available memory for this genome\n'
  elif [[ -s "${error_log}" ]] && grep -Eqi 'invalid.*(genbank|location|feature)|malformed.*(genbank|location|feature)' "${error_log}"; then
    printf 'antiSMASH rejected an invalid GenBank annotation feature\n'
  else
    printf 'antiSMASH exited before producing a valid result; verify the assembly annotations and retry\n'
  fi
}


sanitize_antismash_duplicate_cds_locations() {
  local in_gbk="$1"
  local out_gbk="$2"
  local genome_id="${3:-genome}"

  antismash_input_python_exec "${ANTISMASH_INPUT_PREPARER}" sanitize \
    "${in_gbk}" "${out_gbk}" --genome-id "${genome_id}"
}

run_antismash_record_shard() {
  local genome_id="$1"
  local ant_input="$2"
  local record_id="$3"
  local safe_record_id="$4"
  local ordinal="$5"
  local total_records="$6"
  local shard_dir="$7"
  local row_file="$8"
  local stdout_log="$9"
  local stderr_log="${10}"
  local started_at finished_at elapsed region_count status rc start_percent end_percent compactor_python

  mkdir -p "${shard_dir}"
  started_at="$(date +%s)"
  start_percent=$(((ordinal - 1) * 100 / total_records))
  end_percent=$((ordinal * 100 / total_records))
  antismash_record_progress "${genome_id}" "${record_id}" "${ordinal}" "${total_records}" "${start_percent}" "Starting antiSMASH record shard"

  rc=0
  status="ok"
  if CLUSTERWEAVE_CHILD_DOCKER_CPUS="${ANTISMASH_SHARD_CPUS}" run_tool_with_activity "${genome_id}" "antismash" "record_${ordinal}" "${stdout_log}" "${stderr_log}" antismash_exec antismash \
      "${ant_input}" \
      --minlength "${ANTISMASH_MIN_RECORD_BP}" \
      --output-dir "${shard_dir}" \
      --output-basename "${safe_record_id}" \
      --cpus "${ANTISMASH_SHARD_CPUS}" \
      "${ANT_FLAGS_ARRAY[@]}"; then
    compactor_python="$(resolve_python_cmd)"
    if "${compactor_python}" "${ANTISMASH_SHARD_COMPACTOR}" \
        --shard-dir "${shard_dir}" \
        --record-id "${record_id}" \
        --json-name "${safe_record_id}.json" \
        --retain "${ANTISMASH_RETAIN_SHARD_WORK}" \
        >> "${stdout_log}" 2>> "${stderr_log}"; then
      antismash_record_progress "${genome_id}" "${record_id}" "${ordinal}" "${total_records}" "${end_percent}" "antiSMASH record shard complete"
    else
      rc=$?
      status="failed"
      antismash_record_progress "${genome_id}" "${record_id}" "${ordinal}" "${total_records}" "${end_percent}" "antiSMASH record shard compaction failed"
    fi
  else
    rc=$?
    status="failed"
    antismash_record_progress "${genome_id}" "${record_id}" "${ordinal}" "${total_records}" "${end_percent}" "antiSMASH record shard failed"
  fi

  finished_at="$(date +%s)"
  elapsed=$((finished_at - started_at))
  region_count="$(find "${shard_dir}" -type f -name '*region*.gbk' -print 2>/dev/null | wc -l | tr -d '[:space:]')"
  region_count="${region_count:-0}"
  if ! printf '%s\t%s\t%s\t%s\t%s\n' \
      "${record_id}" "${shard_dir}" "${status}" "${elapsed}" "${region_count}" > "${row_file}"; then
    return 1
  fi
  return "${rc}"
}

merge_antismash_shard_jsons() {
  local output_json="$1"
  local python_cmd=""
  shift
  [[ "$#" -gt 0 ]] || return 1
  if declare -F resolve_python_cmd >/dev/null 2>&1; then
    python_cmd="$(resolve_python_cmd)" || return 1
  elif command -v python3 >/dev/null 2>&1; then
    python_cmd="python3"
  elif command -v python >/dev/null 2>&1; then
    python_cmd="python"
  else
    return 1
  fi
  "${python_cmd}" - "${output_json}" "$@" <<'PY'
import json
import os
import sys

output_path = sys.argv[1]
record_and_path_args = sys.argv[2:]
if len(record_and_path_args) % 2:
    raise RuntimeError("antiSMASH shard JSON merge requires record/path pairs")
merged = None
merged_records = []
merged_timings = {}

for offset in range(0, len(record_and_path_args), 2):
    expected_record_id = record_and_path_args[offset]
    input_path = record_and_path_args[offset + 1]
    with open(input_path, encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise RuntimeError(f"antiSMASH shard JSON is not an object: {input_path}")
    records = document.get("records")
    if not isinstance(records, list) or not records:
        raise RuntimeError(f"antiSMASH shard JSON has no records: {input_path}")
    matching_records = [
        record for record in records
        if isinstance(record, dict) and (
            str(record.get("id", "")) == expected_record_id
            or str(record.get("original_id", "")) == expected_record_id
        )
    ]
    if len(matching_records) != 1:
        analysed_records = [
            record for record in records
            if isinstance(record, dict) and (record.get("areas") or record.get("modules"))
        ]
        if len(analysed_records) == 1:
            matching_records = analysed_records
    if len(matching_records) != 1:
        raise RuntimeError(
            f"antiSMASH shard JSON did not contain exactly one target record "
            f"{expected_record_id!r}: {input_path}"
        )
    if merged is None:
        merged = document
    merged_records.append(matching_records[0])
    timings = document.get("timings", {})
    if not isinstance(timings, dict):
        raise RuntimeError(f"antiSMASH shard JSON timings is not an object: {input_path}")
    merged_timings.update(timings)

if merged is None:
    raise RuntimeError("No antiSMASH shard JSON documents were provided")
merged["records"] = merged_records
merged["timings"] = merged_timings
temporary_path = output_path + ".tmp"
with open(temporary_path, "w", encoding="utf-8") as handle:
    json.dump(merged, handle, ensure_ascii=False, separators=(",", ":"))
    handle.write("\n")
os.replace(temporary_path, output_path)
PY
}

render_antismash_shard_web_bundle() {
  local genome_id="$1"
  local canonical_json="$2"
  local ant_out="$3"
  local shard_root="$4"
  local aggregate_stdout="$5"
  local aggregate_stderr="$6"
  local render_json="${shard_root}/assembled_web_results.json"
  local render_dir="${shard_root}/assembled_web_bundle"
  local region_record_count=""
  local preparer_python=""

  preparer_python="$(resolve_python_cmd)"
  rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
  region_record_count="$(
    "${preparer_python}" "${ANTISMASH_WEB_RESULTS_PREPARER}" \
      "${canonical_json}" "${render_json}" 2>> "${aggregate_stderr}"
  )" || return 1
  [[ "${region_record_count}" =~ ^[0-9]+$ ]] || return 1
  if [[ "${region_record_count}" -eq 0 ]]; then
    return 2
  fi

  log "${genome_id}: rendering complete antiSMASH web bundle from ${region_record_count} region-bearing record(s)"
  if ! CLUSTERWEAVE_CHILD_DOCKER_CPUS="${ANTISMASH_SHARD_CPUS}" \
      antismash_exec antismash \
        --reuse-results "${render_json}" \
        --output-dir "${render_dir}" \
        --output-basename "${genome_id}" \
        --cpus "${ANTISMASH_SHARD_CPUS}" \
        >> "${aggregate_stdout}" 2>> "${aggregate_stderr}"; then
    rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
    return 1
  fi
  if [[ ! -s "${render_dir}/index.html" || ! -s "${render_dir}/regions.js" ]]; then
    rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
    return 1
  fi
  # Keep the already assembled canonical JSON and region GBKs byte-for-byte;
  # only genuinely missing web-bundle files are copied into the result root.
  cp -a -n "${render_dir}/." "${ant_out}/" || {
    rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
    return 1
  }
  # The sharded placeholder index is intentionally replaced by antiSMASH's
  # real landing page; canonical JSON and assembled region GBKs remain intact.
  cp -f "${render_dir}/index.html" "${ant_out}/index.html" || {
    rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
    return 1
  }
  rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
  [[ -s "${ant_out}/index.html" && -s "${ant_out}/regions.js" ]]
}

html_escape() {
  printf '%s' "${1:-}" | sed \
    -e 's/&/\&amp;/g' \
    -e 's/</\&lt;/g' \
    -e 's/>/\&gt;/g' \
    -e 's/"/\&quot;/g' \
    -e "s/'/\\&#39;/g"
}

write_antismash_shard_index() {
  local genome_id="$1"
  local ant_out="$2"
  local record_count="$3"
  local region_count="$4"
  local display_genome region_name display_region
  display_genome="$(html_escape "$(safe_antismash_record_id "${genome_id}")")"

  {
    printf '%s\n' '<!doctype html>'
    printf '%s\n' '<html lang="en"><head><meta charset="utf-8">'
    printf '<title>antiSMASH record shards - %s</title></head><body>\n' "${display_genome}"
    printf '<h1>antiSMASH results: %s</h1>\n' "${display_genome}"
    printf '<p>Completed %s record shard(s); assembled %s region file(s).</p>\n' "${record_count}" "${region_count}"
    printf '%s\n' '<p>Shard manifest: <code>shard_manifest.tsv</code></p>'
    printf '%s\n' '<h2>Region GenBank files</h2><ul>'
    while IFS= read -r region_name; do
      [[ -n "${region_name}" ]] || continue
      display_region="$(html_escape "${region_name}")"
      printf '<li><code>%s</code></li>\n' "${display_region}"
    done < <(find "${ant_out}" -maxdepth 1 -type f -name '*region*.gbk' -printf '%f\n' 2>/dev/null | LC_ALL=C sort)
    printf '%s\n' '</ul></body></html>'
  } > "${ant_out}/index.html"
}

cleanup_antismash_assembled_outputs() {
  local ant_out="$1"
  local canonical_json="$2"
  find "${ant_out}" -maxdepth 1 -type f -name '*region*.gbk' -delete 2>/dev/null || true
  rm -f \
    "${canonical_json}" \
    "${canonical_json}.tmp" \
    "${ant_out}/index.html" \
    "${ant_out}/.done" \
    2>/dev/null || true
}

run_antismash_sharded() {
  local genome_id="$1"
  local ant_input="$2"
  local ant_out="$3"
  local record_ids_file="$4"
  local shard_root="$5"
  local aggregate_stdout="$6"
  local aggregate_stderr="$7"
  local total_records active_jobs shard_failure assembled_count
  local index ordinal record_id base_safe safe_record_id suffix shard_input shard_dir row_file split_manifest
  local shard_stdout shard_stderr row_status row_elapsed row_regions row_record row_dir
  local region_file source_name destination_name destination collision expected_json canonical_json
  local -a record_ids=() safe_record_ids=() shard_inputs=() shard_dirs=() row_files=() stdout_logs=() stderr_logs=()
  local -a shard_json_args=() fallback_json_files=()
  local -A used_safe_record_ids=()

  mapfile -t record_ids < "${record_ids_file}"
  total_records="${#record_ids[@]}"
  canonical_json="${ant_out}/${genome_id}.antismash.json"
  if [[ "${total_records}" -le 1 ]]; then
    cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
    return 2
  fi

  rm -rf "${shard_root}" 2>/dev/null || true
  mkdir -p "${shard_root}/manifest_rows" "${shard_root}/record_inputs"
  : > "${aggregate_stdout}"
  : > "${aggregate_stderr}"

  for index in "${!record_ids[@]}"; do
    ordinal=$((index + 1))
    record_id="${record_ids[${index}]}"
    base_safe="$(safe_antismash_record_id "${record_id}")"
    safe_record_id="${base_safe}"
    suffix=1
    while [[ -n "${used_safe_record_ids[${safe_record_id}]+set}" ]]; do
      suffix=$((suffix + 1))
      safe_record_id="${base_safe}_${suffix}"
    done
    used_safe_record_ids["${safe_record_id}"]=1
    shard_dir="${shard_root}/$(printf '%06d' "${ordinal}")_${safe_record_id}"
    shard_input="${shard_root}/record_inputs/$(printf '%06d' "${ordinal}")_${safe_record_id}.gbk"
    row_file="${shard_root}/manifest_rows/$(printf '%06d' "${ordinal}").tsv"
    shard_stdout="${WORK_ROOT}/logs/${genome_id}.antismash.shard.$(printf '%06d' "${ordinal}").stdout.log"
    shard_stderr="${WORK_ROOT}/logs/${genome_id}.antismash.shard.$(printf '%06d' "${ordinal}").stderr.log"
    safe_record_ids+=("${safe_record_id}")
    shard_inputs+=("${shard_input}")
    shard_dirs+=("${shard_dir}")
    row_files+=("${row_file}")
    stdout_logs+=("${shard_stdout}")
    stderr_logs+=("${shard_stderr}")
  done

  split_manifest="${shard_root}/record_inputs.tsv"
  : > "${split_manifest}"
  for index in "${!record_ids[@]}"; do
    printf '%s\t%s\n' "${record_ids[${index}]}" "${shard_inputs[${index}]}" >> "${split_manifest}"
  done
  if ! antismash_input_python_exec "${ANTISMASH_INPUT_PREPARER}" split-records \
      "${ant_input}" "${split_manifest}" >> "${aggregate_stdout}" 2>> "${aggregate_stderr}"; then
    warn "${genome_id}: failed to isolate antiSMASH record inputs"
    return 1
  fi

  active_jobs=0
  shard_failure=0
  for index in "${!record_ids[@]}"; do
    ordinal=$((index + 1))
    run_antismash_record_shard \
      "${genome_id}" "${shard_inputs[${index}]}" "${record_ids[${index}]}" "${safe_record_ids[${index}]}" \
      "${ordinal}" "${total_records}" "${shard_dirs[${index}]}" "${row_files[${index}]}" \
      "${stdout_logs[${index}]}" "${stderr_logs[${index}]}" &
    active_jobs=$((active_jobs + 1))
    while [[ "${active_jobs}" -ge "${ANTISMASH_RECORD_PARALLELISM}" ]]; do
      if ! wait_for_antismash_shard_job; then shard_failure=1; fi
      active_jobs=$((active_jobs - 1))
    done
  done
  while [[ "${active_jobs}" -gt 0 ]]; do
    if ! wait_for_antismash_shard_job; then shard_failure=1; fi
    active_jobs=$((active_jobs - 1))
  done

  for index in "${!record_ids[@]}"; do
    printf '\n===== record %s (%s) =====\n' "$((index + 1))" "${record_ids[${index}]}" >> "${aggregate_stdout}"
    if [[ -f "${stdout_logs[${index}]}" ]]; then
      cat "${stdout_logs[${index}]}" >> "${aggregate_stdout}" || true
    fi
    printf '\n===== record %s (%s) =====\n' "$((index + 1))" "${record_ids[${index}]}" >> "${aggregate_stderr}"
    if [[ -f "${stderr_logs[${index}]}" ]]; then
      cat "${stderr_logs[${index}]}" >> "${aggregate_stderr}" || true
    fi
  done

  if ! printf 'record_id\tshard_dir\tstatus\telapsed_seconds\tregion_count\n' > "${ant_out}/shard_manifest.tsv"; then
    cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
    return 1
  fi
  for index in "${!record_ids[@]}"; do
    if [[ ! -s "${row_files[${index}]}" ]]; then
      shard_failure=1
      printf '%s\t%s\t%s\t%s\t%s\n' \
        "${record_ids[${index}]}" "${shard_dirs[${index}]}" "failed" "0" "0" > "${row_files[${index}]}"
    fi
    if ! cat "${row_files[${index}]}" >> "${ant_out}/shard_manifest.tsv"; then
      cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
      return 1
    fi
  done

  assembled_count=0
  for index in "${!record_ids[@]}"; do
    row_record=""
    row_dir=""
    row_status="failed"
    row_elapsed="0"
    row_regions="0"
    IFS=$'\t' read -r row_record row_dir row_status row_elapsed row_regions < "${row_files[${index}]}" || true
    if [[ "${row_status}" != "ok" ]]; then
      shard_failure=1
      continue
    fi
    expected_json="${shard_dirs[${index}]}/${safe_record_ids[${index}]}.json"
    if [[ ! -s "${expected_json}" ]]; then
      fallback_json_files=()
      mapfile -d '' -t fallback_json_files < <(
        find "${shard_dirs[${index}]}" -maxdepth 1 -type f -name '*.antismash.json' -print0 2>/dev/null
      )
      if [[ "${#fallback_json_files[@]}" -eq 1 && -s "${fallback_json_files[0]}" ]]; then
        expected_json="${fallback_json_files[0]}"
      else
        warn "${genome_id}: missing expected antiSMASH shard JSON for record=${record_ids[${index}]} shard=${shard_dirs[${index}]}"
        shard_failure=1
        continue
      fi
    fi
    shard_json_args+=("${record_ids[${index}]}" "${expected_json}")
    while IFS= read -r -d '' region_file; do
      source_name="${region_file##*/}"
      destination_name="${source_name}"
      case "${destination_name}" in
        "${safe_record_ids[${index}]}".*) ;;
        *) destination_name="${safe_record_ids[${index}]}.${destination_name}" ;;
      esac
      destination="${ant_out}/${destination_name}"
      if [[ -e "${destination}" ]]; then
        if cmp -s "${region_file}" "${destination}"; then
          log "${genome_id}: deduplicated assembled antiSMASH region ${destination_name}"
          continue
        fi
        warn "${genome_id}: conflicting antiSMASH region collision at ${destination}"
        shard_failure=1
        continue
      fi
      if cp -f "${region_file}" "${destination}"; then
        assembled_count=$((assembled_count + 1))
      else
        shard_failure=1
      fi
    done < <(find "${shard_dirs[${index}]}" -type f -name '*region*.gbk' -print0 2>/dev/null)
  done

  if [[ "${shard_failure}" -eq 0 ]]; then
    if ! merge_antismash_shard_jsons "${canonical_json}" "${shard_json_args[@]}" 2>> "${aggregate_stderr}"; then
      warn "${genome_id}: failed to merge antiSMASH shard JSON into ${canonical_json}"
      shard_failure=1
    fi
  fi
  if [[ "${shard_failure}" -ne 0 ]]; then
    cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
    return 1
  fi
  if [[ "${assembled_count}" -gt 0 ]]; then
    if ! render_antismash_shard_web_bundle \
        "${genome_id}" "${canonical_json}" "${ant_out}" "${shard_root}" \
        "${aggregate_stdout}" "${aggregate_stderr}"; then
      warn "${genome_id}: failed to render the complete antiSMASH web bundle"
      cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
      return 1
    fi
  elif ! write_antismash_shard_index "${genome_id}" "${ant_out}" "${total_records}" "${assembled_count}"; then
    cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
    return 1
  fi
  if ! touch "${ant_out}/.done"; then
    cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
    return 1
  fi
}

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

Image bootstrap:
  AUTO_PULL_IMAGES=ask|always|never (default: ${AUTO_PULL_IMAGES})
  ANTISMASH_IMAGE_URI=...       Source URI for antiSMASH image (default: ${ANTISMASH_IMAGE_URI})
  FUNBGCEX_IMAGE_URI=...        Optional source URI for FunBGCeX image (default: unset)
  AUTO_BUILD_FUNBGCEX_SIF=0|1   Auto-build a repo-local FunBGCeX SIF if needed (default: ${AUTO_BUILD_FUNBGCEX_SIF})
  FUNBGCEX_DEF=...              Singularity definition used for the local FunBGCeX build
  FUNBGCEX_DOCKERFILE=...       Dockerfile used for the local FunBGCeX build fallback path
  FUNBGCEX_BUILD_SCRIPT=...     Helper script used to build the local FunBGCeX SIF
  BRAKER_IMAGE_URI=...          Source URI for BRAKER3 image (default: ${BRAKER_IMAGE_URI})
  FUNANNOTATE_IMAGE_URI=...     Baked funannotate image URI for Docker mode (default: ${FUNANNOTATE_IMAGE_URI})
  FUNANNOTATE_BASE_IMAGE_URI=... Upstream base used by the one-time bake (default: ${FUNANNOTATE_BASE_IMAGE_URI})
  AUTO_BUILD_FUNANNOTATE_SIF=0|1 Auto-build a repo-local funannotate SIF if needed (default: ${AUTO_BUILD_FUNANNOTATE_SIF})
  AUTO_BUILD_FUNANNOTATE_DOCKER=0|1 Auto-build a repo-local funannotate Docker image if needed (default: ${AUTO_BUILD_FUNANNOTATE_DOCKER})
  FUNANNOTATE_BUILD_SCRIPT=...  Helper script used to bake funannotate DBs into the local runtime
  FUNBGCEX_BOOTSTRAP=0|1        Advanced fallback: auto-create a local FunBGCeX venv if needed (default: ${FUNBGCEX_BOOTSTRAP})
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
[[ -s "${BACTERIAL_GENBANK_SANITIZER}" ]] || die "bacterial GenBank sanitizer not found: ${BACTERIAL_GENBANK_SANITIZER}"
[[ -s "${GENBANK_TRANSLATION_CHECKER}" ]] || die "GenBank translation checker not found: ${GENBANK_TRANSLATION_CHECKER}"

load_taxon_routes
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

log "Detecting supported antiSMASH flags..."
mapfile -t ANT_FLAGS_ARRAY < <(antismash_supported_flags fungi none)
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

fungal_annotation_fallback_needed() {
  local candidate root staged source_gbk source_fasta
  for candidate in "$@"; do
    [[ "$(route_taxon_for_genome "${candidate}")" == "fungi" ]] || continue
    root="$(route_root_for_genome "${candidate}")"
    staged="${RESULTS_ROOT}/input_gbks/${candidate}.gbk"
    if [[ "${FORCE}" != "1" && -s "${staged}" ]] && gbk_has_cds_and_translation "${staged}"; then
      continue
    fi
    source_gbk=""
    if source_gbk="$(resolve_genbank_for_stem "${candidate}" "${root}")" \
        && gbk_has_cds_and_translation "${source_gbk}"; then
      continue
    fi
    source_fasta=""
    if source_fasta="$(resolve_fasta_for_stem "${candidate}" "${root}")" && [[ -s "${source_fasta}" ]]; then
      return 0
    fi
  done
  return 1
}

FUNGAL_ANNOTATION_FALLBACK_NEEDED=0
if [[ "${HAS_FUNGAL_ROUTES}" -eq 1 ]] \
    && fungal_annotation_fallback_needed "${GEN_ARR[@]}"; then
  FUNGAL_ANNOTATION_FALLBACK_NEEDED=1
  log "Fungal input inspection selected an annotation fallback; bootstrapping configured annotation tooling."
  setup_converter
  ensure_annotation_tooling
elif [[ "${HAS_FUNGAL_ROUTES}" -eq 1 ]]; then
  log "Skipping fungal annotation runtime bootstrap: every reusable fungal GenBank already has complete non-empty CDS translations, or no fallback-capable FASTA is present."
else
  log "Skipping fungal annotation runtime bootstrap: no fungal routes are present."
fi
freeze_resource_plan "${#GEN_ARR[@]}"

###############################################################################
# Main loop
###############################################################################
total=0; dropped=0; processed=0
MANIFEST_ROW_DIR="${WORK_ROOT}/tmp/manifest_rows"
mkdir -p "${MANIFEST_ROW_DIR}"
rm -f "${MANIFEST_ROW_DIR}"/*.tsv 2>/dev/null || true
MANIFEST_ROW_FILES=()

write_genome_manifest_row() {
  local row_file="$1"
  shift
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$@" > "${row_file}"
}

process_genome() {
  local genome_id="$1"
  local ordinal="$2"
  local row_file="$3"
  local total_genomes="$4"
  local GENLOG fasta gb_src staged_gbk ant_out fbx_out ant_err ant_stdout fbx_err fbx_stdout
  local gbk_used gbk_status fallback_method antismash_status funbgcex_status ant_done fbx_done
  local per_tmp ant_filtered_input ant_input antismash_input_sanitized ant_sanitize_summary antismash_duplicate_cds_dropped
  local fbx_input gbk_dir antismash_record_ids_file antismash_record_count antismash_record_ids_stable antismash_shard_root antismash_run_mode antismash_run_ok
  local taxon_group taxon_source route_status prediction_method detector_profile funbgcex_applicability genome_input_root
  local bacteria_source bacterial_record_map bacterial_sanitize_summary python_cmd
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
  if [[ "${taxon_group}" == "bacteria" ]]; then
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
  genome_stage_progress "${genome_id}" "annotation" 0 "Queued genome ${ordinal}/${total_genomes}"

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

  gbk_used=""
  gbk_status="missing"
  per_tmp="${WORK_ROOT}/tmp/${genome_id}"
  mkdir -p "${per_tmp}"

  if [[ "${taxon_group}" == "bacteria" ]]; then
    ant_input="${per_tmp}/${genome_id}.bacteria.antismash.gbk"
    antismash_record_ids_file="${per_tmp}/antismash_record_ids.txt"
    bacterial_record_map="${RESULTS_ROOT}/summary_tables/bacterial_record_maps/${genome_id}.record_map.tsv"
    bacteria_source=""
    if [[ -n "${gb_src}" && -s "${gb_src}" ]]; then
      bacteria_source="${gb_src}"
    elif [[ -n "${fasta}" && -s "${fasta}" ]]; then
      bacteria_source="${fasta}"
    fi
    if [[ -z "${bacteria_source}" ]]; then
      gbk_status="no_bacterial_sequence_input"
    else
      python_cmd="$(resolve_python_cmd)" || true
      if [[ -n "${python_cmd}" ]] && bacterial_sanitize_summary="$(
          "${python_cmd}" "${BACTERIAL_GENBANK_SANITIZER}" \
            --input "${bacteria_source}" \
            --output "${ant_input}" \
            --record-map "${bacterial_record_map}" \
            --record-ids "${antismash_record_ids_file}" \
            --genome-id "${genome_id}" \
            --min-record-bp "${ANTISMASH_MIN_RECORD_BP}" \
            --max-record-bp "${ANTISMASH_MAX_RECORD_BP}" 2>> "${GENLOG}"
        )"; then
        printf '%s\n' "${bacterial_sanitize_summary}" | tee -a "${GENLOG}"
        gbk_used="${ant_input}"
        gbk_status="bacterial_sequence_sanitized"
        antismash_input_sanitized=1
        genome_stage_progress "${genome_id}" "annotation" 25 "Feature-free bacterial GenBank ready"
      else
        gbk_status="bacterial_sanitizer_failed"
      fi
    fi
  else

  # 1) Reuse staged GBK if present
  if [[ -s "${staged_gbk}" ]] && gbk_has_cds_and_translation "${staged_gbk}"; then
    normalize_gbk_record_headers_in_place "${staged_gbk}" || true
    gbk_used="${staged_gbk}"
    gbk_status="staged_ok"
    prediction_method="existing_cds"
    log "${genome_id}: using staged GBK: ${staged_gbk}" | tee -a "${GENLOG}"
    genome_annotation_decision "${genome_id}" "no" "existing_cds" "Complete CDS translations already available"
    genome_stage_progress "${genome_id}" "annotation" 20 "Staged GenBank ready"
  fi

  # 2) If no staged GBK, try original annotated GenBank, else annotation fallback chain
  if [[ -z "${gbk_used}" ]]; then
    if [[ -n "${gb_src}" && -s "${gb_src}" ]]; then
      if gbk_has_cds_and_translation "${gb_src}"; then
        cp -f "${gb_src}" "${staged_gbk}"
        normalize_gbk_record_headers_in_place "${staged_gbk}" || true
        gbk_used="${staged_gbk}"
        gbk_status="original_ok"
        prediction_method="existing_cds"
        log "${genome_id}: staged original GBK (has CDS+translation): ${gb_src}" | tee -a "${GENLOG}"
        genome_annotation_decision "${genome_id}" "no" "existing_cds" "Complete CDS translations already available"
      else
        gbk_status="original_missing_translations"
        log "${genome_id}: original GBK lacks usable CDS translations; using annotation workflow (${ANNOTATION_FALLBACK_ORDER})" | tee -a "${GENLOG}"
      fi
    else
      gbk_status="missing_genbank"
      log "${genome_id}: no original GBK detected; will try fallback annotation chain (${ANNOTATION_FALLBACK_ORDER}) if FASTA available" | tee -a "${GENLOG}"
    fi

    if [[ -z "${gbk_used}" ]]; then
      if [[ -n "${fasta}" && -s "${fasta}" ]]; then
        fallback_method=""
        genome_stage_progress "${genome_id}" "annotation" 10 "Running annotation fallback"
        if annotate_genome_with_fallbacks "${genome_id}" "${fasta}" "${staged_gbk}"; then
          fallback_method="${ANNOTATION_FALLBACK_METHOD:-annotation}"
          prediction_method="${fallback_method}"
          normalize_gbk_record_headers_in_place "${staged_gbk}" || true
          if gbk_has_cds_and_translation "${staged_gbk}"; then
            gbk_used="${staged_gbk}"
            gbk_status="${fallback_method}_fixed"
            genome_stage_progress "${genome_id}" "annotation" 25 "Annotation fallback produced GenBank"
          else
            gbk_status="${fallback_method}_no_translations"
            rm -f "${staged_gbk}" 2>/dev/null || true
          fi
        else
          gbk_status="${ANNOTATION_FALLBACK_FAILURE_REASON:-annotation_fallbacks_failed}"
          if [[ -n "${ANNOTATION_FALLBACK_FAILURE_DETAIL}" ]]; then
            log "${genome_id}: annotation fallback detail: ${ANNOTATION_FALLBACK_FAILURE_DETAIL}" | tee -a "${GENLOG}"
          fi
        fi
      else
        gbk_status="no_fasta_for_annotation"
      fi
    fi
  fi
  fi

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
    antismash_duplicate_cds_dropped="$(printf '%s\n' "${ant_sanitize_summary}" | sed -nE 's/.*dropped_duplicate_cds=([0-9]+).*/\1/p' | head -n1)"
    antismash_invalid_non_cds_dropped="$(printf '%s\n' "${ant_sanitize_summary}" | sed -nE 's/.*dropped_invalid_non_cds_compound_features[^0-9]*([0-9]+).*/\1/p' | head -n1)"
    if [[ "${antismash_duplicate_cds_dropped:-0}" -gt 0 || "${antismash_invalid_non_cds_dropped:-0}" -gt 0 ]]; then
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
    if [[ "${ANTISMASH_RECORD_PARALLELISM}" -gt 1 && "${antismash_record_count}" -gt 1 && "${antismash_record_ids_stable}" -eq 1 ]]; then
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

    if [[ "${antismash_run_ok}" -eq 1 ]] && touch "${ant_out}/.done" && antismash_done "${ant_out}"; then
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
  elif [[ "${fbx_done}" -eq 1 ]]; then
    funbgcex_status="skipped_done"
    log "${genome_id}: FunBGCeX already done -> ${fbx_out}" | tee -a "${GENLOG}"
    genome_stage_progress "${genome_id}" "funbgcex" 100 "FunBGCeX already complete"
  else
    rm -rf "${fbx_out}" 2>/dev/null || true
    mkdir -p "${fbx_out}"

    gbk_dir="${per_tmp}/funbgcex_in"
    rm -rf "${gbk_dir}" 2>/dev/null || true
    mkdir -p "${gbk_dir}"
    cp -f "${fbx_input}" "${gbk_dir}/"

    log "${genome_id}: running FunBGCeX (outdir=${fbx_out})" | tee -a "${GENLOG}"
    genome_stage_progress "${genome_id}" "funbgcex" 80 "Running FunBGCeX"
    if run_funbgcex_cli "${gbk_dir}" "${fbx_out}" >"${fbx_stdout}" 2>"${fbx_err}" \
        && funbgcex_outputs_valid "${fbx_out}" \
        && touch "${fbx_out}/.done"; then
      funbgcex_status="ran_ok"
      log "${genome_id}: FunBGCeX OK" | tee -a "${GENLOG}"
      genome_stage_progress "${genome_id}" "funbgcex" 100 "FunBGCeX complete"
    else
      funbgcex_status="failed"
      warn "${genome_id}: FunBGCeX FAILED (see ${fbx_err})" | tee -a "${GENLOG}"
      genome_stage_progress "${genome_id}" "funbgcex" 100 "FunBGCeX failed"
    fi
  fi

  write_genome_manifest_row "${row_file}" \
    "${genome_id}" "${fasta}" "${gbk_used}" "${gbk_status}" "${antismash_status}" "${funbgcex_status}" \
    "${taxon_group}" "${prediction_method}" "${detector_profile}" "${funbgcex_applicability}"

  sync_logs_genome "${genome_id}"
  return 0

}

idx=0
genome_job_failure=0
for genome_id in "${GEN_ARR[@]}"; do
  idx=$((idx + 1))
  row_file="${MANIFEST_ROW_DIR}/$(printf '%06d' "${idx}").tsv"
  MANIFEST_ROW_FILES+=("${row_file}")
  if [[ "${GENOME_PARALLELISM}" -gt 1 ]]; then
    process_genome "${genome_id}" "${idx}" "${row_file}" "${#GEN_ARR[@]}" &
    while [[ "$(running_genome_job_count)" -ge "${GENOME_PARALLELISM}" ]]; do
      if ! wait_for_genome_job; then genome_job_failure=1; fi
    done
  else
    if ! process_genome "${genome_id}" "${idx}" "${row_file}" "${#GEN_ARR[@]}"; then
      genome_job_failure=1
    fi
  fi
done

while [[ "$(running_genome_job_count)" -gt 0 ]]; do
  if ! wait_for_genome_job; then genome_job_failure=1; fi
done

if [[ "${genome_job_failure}" -ne 0 ]]; then
  die "One or more per-genome annotation jobs failed before manifest regroup; see ${WORK_ROOT}/logs"
fi

for row_file in "${MANIFEST_ROW_FILES[@]}"; do
  [[ -s "${row_file}" ]] || die "Missing per-genome manifest row: ${row_file}"
  cat "${row_file}" >> "${MANIFEST}"
  row_line="$(<"${row_file}")"
  IFS=$'\034' read -r \
    row_genome row_fasta row_gbk row_gbk_status row_antismash row_funbgcex \
    row_taxon row_prediction row_detector row_funbgcex_applicability \
    <<< "${row_line//$'\t'/$'\034'}" || true
  total=$((total + 1))
  if [[ -n "${row_gbk:-}" ]]; then
    processed=$((processed + 1))
  else
    dropped=$((dropped + 1))
  fi
done
rsync -a "${MANIFEST}" "${RESULTS_ROOT}/summary_tables/" >/dev/null 2>&1 || true

log "Complete."
log "summary_tables: ${RESULTS_ROOT}/summary_tables"
log "manifest: ${MANIFEST}"
log "total=${total} processed=${processed} dropped=${dropped}"
rsync -a "${WORK_ROOT}/logs/" "${RESULTS_ROOT}/logs/" >/dev/null 2>&1 || true
log "Logs synced to: ${RESULTS_ROOT}/logs"
