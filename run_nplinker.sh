#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

###############################################################################
# run_nplinker.sh
# - Runs NPLinker for a configured target strain
# - Uses an explicitly prepared Docker or Singularity/Apptainer runtime
# - Exports a ranked TSV table of predicted links
###############################################################################

###############################################################################
# Env-backed project paths
###############################################################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
PROJECTS_ROOT="${PROJECTS_ROOT:-${PROJECT_DIR}}"
DATA_ROOT="${DATA_ROOT:-${PROJECTS_ROOT}/data}"
TOOLS_ROOT="${TOOLS_ROOT:-${PROJECTS_ROOT}/software}"
RESULTS_BASE="${RESULTS_BASE:-${DATA_ROOT}/results}"
RESULTS_ROOT="${RESULTS_ROOT:-${RESULTS_BASE}/${PROJECT_NAME}}"
SOFTWARE_ROOT="${SOFTWARE_ROOT:-${TOOLS_ROOT}/nplinker}"

###############################################################################
# Tunables
###############################################################################
ENGINE="${ENGINE:-}"
FORCE="${FORCE:-0}"
CPUS="${CPUS:-6}"
CLUSTERWEAVE_RUNTIME_MODE="${CLUSTERWEAVE_RUNTIME_MODE:-hpc-singularity}"
NPLINKER_DOCKER_MEMORY="${NPLINKER_DOCKER_MEMORY:-${CLUSTERWEAVE_TOOL_DOCKER_MEMORY:-}}"
NPLINKER_DOCKER_PIDS_LIMIT="${NPLINKER_DOCKER_PIDS_LIMIT:-${CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT:-}}"

# Run mode:
#   auto  -> try PODP first (if PODP_ID exists), else require local inputs
#   podp  -> enforce PODP mode
#   local -> enforce local mode
RUN_MODE="${RUN_MODE:-local}"

# Target dataset/strain
PODP_ID="${PODP_ID:-}"
TARGET_STRAIN="${TARGET_STRAIN:-}"

# MassIVE credentials (used by some private workflows/services)
MASSIVE_DATASET_ID="${MASSIVE_DATASET_ID:-}"
MASSIVE_USERNAME="${MASSIVE_USERNAME:-}"
MASSIVE_PASSWORD="${MASSIVE_PASSWORD:-}"

# Container + environment
SIF_PATH="${SIF_PATH:-${SOFTWARE_ROOT}/nplinker_python3.11.sif}"
SIF_SOURCE="${SIF_SOURCE:-docker://python:3.11-slim}"
NPLINKER_USE_DOCKER_IMAGE="${NPLINKER_USE_DOCKER_IMAGE:-0}"
NPLINKER_DOCKER_IMAGE="${NPLINKER_DOCKER_IMAGE:-python:3.11-slim}"
NPLINKER_DOCKER_DATA_VOLUME="${NPLINKER_DOCKER_DATA_VOLUME:-${DOCKER_DATA_VOLUME:-}}"
VENV_DIR="${VENV_DIR:-${SOFTWARE_ROOT}/venv}"
PIP_CACHE="${PIP_CACHE:-${SOFTWARE_ROOT}/pip_cache}"
AUTO_PULL_NPLINKER_SIF="${AUTO_PULL_NPLINKER_SIF:-1}"

# NPLinker run layout
# Use native Linux storage by default to avoid false 0GB warnings on /mnt/c mounts.
NPLINKER_USE_NATIVE="${NPLINKER_USE_NATIVE:-1}"   # 1=yes (/tmp), 0=no (Windows path)
WINDOWS_NPLINKER_ROOT="${WINDOWS_NPLINKER_ROOT:-${RESULTS_ROOT}/nplinker}"
NATIVE_NPLINKER_ROOT="${NATIVE_NPLINKER_ROOT:-/tmp/$(basename "${RESULTS_ROOT}")_nplinker}"
if [[ "${NPLINKER_USE_NATIVE}" == "1" ]]; then
  NPLINKER_ROOT="${NPLINKER_ROOT:-${NATIVE_NPLINKER_ROOT}}"
else
  NPLINKER_ROOT="${NPLINKER_ROOT:-${WINDOWS_NPLINKER_ROOT}}"
fi
RUN_DIR="${RUN_DIR:-${NPLINKER_ROOT}/runs/${TARGET_STRAIN}}"
MIRROR_RUN_DIR="${MIRROR_RUN_DIR:-${WINDOWS_NPLINKER_ROOT}/runs/${TARGET_STRAIN}}"
WORK_ROOT="${WORK_ROOT:-/tmp/$(basename "${RESULTS_ROOT}")_nplinker_work}"
LOGDIR="${LOGDIR:-${RESULTS_ROOT}/logs}"
LOGFILE="${LOGFILE:-${LOGDIR}/run_nplinker.$(date +%Y%m%d_%H%M%S).log}"

# Output table
OUT_TABLE="${OUT_TABLE:-${RUN_DIR}/output/links_${TARGET_STRAIN}.tsv}"
MIRROR_OUT_TABLE="${MIRROR_OUT_TABLE:-${MIRROR_RUN_DIR}/output/links_${TARGET_STRAIN}.tsv}"
SUMMARY_TABLE="${SUMMARY_TABLE:-${RUN_DIR}/output/summary_${TARGET_STRAIN}.tsv}"
MIRROR_SUMMARY_TABLE="${MIRROR_SUMMARY_TABLE:-${MIRROR_RUN_DIR}/output/summary_${TARGET_STRAIN}.tsv}"

# Local mode inputs (required if RUN_MODE=local, or if auto falls back to local)
LOCAL_ANTISMASH_ROOT="${LOCAL_ANTISMASH_ROOT:-${RESULTS_ROOT}/antismash/${TARGET_STRAIN}}"
LOCAL_GNPS_DIR="${LOCAL_GNPS_DIR:-}"
LOCAL_STRAIN_MAPPING="${LOCAL_STRAIN_MAPPING:-}"
LOCAL_BIGSCAPE_ROOT="${LOCAL_BIGSCAPE_ROOT:-${RESULTS_ROOT}/big_scape}"
USE_LOCAL_GENOMICS_ONLY="${USE_LOCAL_GENOMICS_ONLY:-1}"

# Dependency bootstrap behavior
NPLINKER_INSTALL_DEPS="${NPLINKER_INSTALL_DEPS:-0}"
NPLINKER_VERSION="${NPLINKER_VERSION:-2.0.0}"
NPLINKER_BOOTSTRAP_ENV="${NPLINKER_BOOTSTRAP_ENV:-1}"
NPLINKER_HTTP_TIMEOUT="${NPLINKER_HTTP_TIMEOUT:-180}"
NPLINKER_LOAD_RETRIES="${NPLINKER_LOAD_RETRIES:-3}"
NPLINKER_RETRY_SLEEP="${NPLINKER_RETRY_SLEEP:-20}"
GNPS_VERSION="${GNPS_VERSION:-2}"
FILTER_TARGET_ONLY="${FILTER_TARGET_ONLY:-0}"
# Target-only runs are strict unless an operator explicitly requests legacy fallback.
ALLOW_FILTER_FALLBACK="${ALLOW_FILTER_FALLBACK:-0}"
METCALF_STANDARDISED="${METCALF_STANDARDISED:-1}"
EXPORT_PREFER_LOCAL="${EXPORT_PREFER_LOCAL:-1}"
SUMMARY_EXCLUDE_MIBIG_ONLY="${SUMMARY_EXCLUDE_MIBIG_ONLY:-1}"

###############################################################################
# Helpers
###############################################################################
ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "[$(ts)] [INFO] $*" | tee -a "${LOGFILE}"; }
warn(){ echo "[$(ts)] [WARN] $*" | tee -a "${LOGFILE}" >&2; }
err(){ echo "[$(ts)] [ERROR] $*" | tee -a "${LOGFILE}" >&2; }
die(){ err "$*"; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
runtime_preparation_hint() {
  warn "Runtime acquisition is disabled during canonical jobs."
  warn "Prepare local assets with: docker compose run --rm --no-deps worker prepare-runtime"
  warn "Verify them with: docker compose run --rm --no-deps worker check-runtime"
  warn "External executors must pre-provision the configured site-managed runtime."
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

normalize_positive_integer CPUS 1
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
NPLINKER_DOCKER_CPUS="$(bounded_docker_cpu_limit "${CPUS}" "${CLUSTERWEAVE_TOOL_DOCKER_CPUS:-}")"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
sync_results_back() {
  if [[ "${RUN_DIR}" == "${MIRROR_RUN_DIR}" ]]; then
    return 0
  fi
  mkdir -p "${MIRROR_RUN_DIR}"
  log "Syncing NPLinker run directory back to Windows path: ${MIRROR_RUN_DIR}"
  if have rsync; then
    rsync -a "${RUN_DIR}/" "${MIRROR_RUN_DIR}/"
  else
    cp -a "${RUN_DIR}/." "${MIRROR_RUN_DIR}/"
  fi
}

resolve_local_antismash_root() {
  if [[ -d "${LOCAL_ANTISMASH_ROOT}" ]]; then
    return 0
  fi

  local -a discovered_roots=()
  mapfile -d '' -t discovered_roots < <(
    find "${RESULTS_ROOT}/antismash" -maxdepth 1 -mindepth 1 -type d -print0 2>/dev/null \
      | sort -z
  )
  die "LOCAL_ANTISMASH_ROOT does not match TARGET_STRAIN='${TARGET_STRAIN}'; exact target root is required (discovered ${#discovered_roots[@]} other genome result root(s))"
}

get_podp_genome_ids() {
  [[ -n "${PODP_ID}" ]] || return 0
  cexec python -c "import json,urllib.request; u='https://pairedomicsdata.bioinformatics.nl/api/projects/${PODP_ID}'; d=json.load(urllib.request.urlopen(u, timeout=60)); gs=d.get('genomes',[]); out=[]; 
if isinstance(gs, dict):
  out.extend([str(k) for k in gs.keys() if k]);
elif isinstance(gs, list):
  for rec in gs:
    gid=rec.get('genome_ID',{}) if isinstance(rec,dict) else {}
    if isinstance(gid,dict):
      v=gid.get('RefSeq_accession') or gid.get('GenBank_accession') or gid.get('JGI_Genome_ID') or gid.get('IMG_Genome_ID')
      if v: out.append(str(v))
for x in out: print(x)" 2>/dev/null || true
}

target_taxon_provenance_json() {
  local manifest="${GENOME_TAXON_MANIFEST:-${RESULTS_ROOT}/summary_tables/genome_taxon_manifest.tsv}"
  python3 - "${manifest}" "${TARGET_STRAIN}" <<'PY'
import csv
import json
from pathlib import Path
import sys

manifest = Path(sys.argv[1])
target_genome_id = sys.argv[2].strip()
provenance = {
    "target_genome_id": target_genome_id,
    "taxon_group": "",
    "prediction_method": "",
    "source": "genome_taxon_manifest.tsv",
}

if manifest.is_file():
    with manifest.open(newline="", encoding="utf-8") as handle:
        rows = [
            row
            for row in csv.DictReader(handle, delimiter="\t")
            if (row.get("genome_id") or "").strip() == target_genome_id
        ]
    if len(rows) > 1:
        raise SystemExit(
            f"duplicate exact target rows in genome taxon manifest: {target_genome_id}"
        )
    if rows:
        taxon_group = (rows[0].get("taxon_group") or "").strip().lower()
        prediction_method = (rows[0].get("prediction_method") or "").strip().lower()
        if taxon_group in {"fungi", "bacteria"}:
            provenance["taxon_group"] = taxon_group
        if prediction_method in {"funannotate", "existing_cds", "prodigal"}:
            provenance["prediction_method"] = prediction_method

print(json.dumps(provenance, separators=(",", ":"), sort_keys=True))
PY
}

write_genome_status_for_local_antismash() {
  local status_file="${RUN_DIR}/downloads/genome_status.json"
  local clusterweave_provenance
  mkdir -p "${RUN_DIR}/downloads"

  mapfile -t _podp_ids < <(get_podp_genome_ids)
  if [[ "${#_podp_ids[@]}" -eq 0 ]]; then
    return 0
  fi
  clusterweave_provenance="$(target_taxon_provenance_json)"

  {
    printf '{"genome_status": ['
    local first=1
    for gid in "${_podp_ids[@]}"; do
      [[ -n "${gid}" ]] || continue
      if [[ "${first}" -eq 0 ]]; then
        printf ', '
      fi
      first=0
      # We intentionally resolve to TARGET_STRAIN because local seeded antiSMASH
      # is staged under antismash/TARGET_STRAIN and genome_bgc_mappings uses that key.
      printf '{"original_id": "%s", "resolved_refseq_id": "%s", "resolve_attempted": true, "bgc_path": "%s"}' \
        "${gid}" "${TARGET_STRAIN}" "${RUN_DIR}/antismash/${TARGET_STRAIN}"
    done
    printf '], "version": "1.0", "clusterweave_provenance": %s}\n' \
      "${clusterweave_provenance}"
  } > "${status_file}"

  log "Wrote local genome status mapping for seeded antiSMASH: ${status_file}"
}

seed_antismash_for_podp() {
  resolve_local_antismash_root
  [[ -d "${LOCAL_ANTISMASH_ROOT}" ]] || return 0

  local -a stage_dirs
  stage_dirs=("${RUN_DIR}/antismash/${TARGET_STRAIN}")

  mapfile -t _podp_ids < <(get_podp_genome_ids)
  for gid in "${_podp_ids[@]}"; do
    [[ -n "${gid}" ]] || continue
    stage_dirs+=("${RUN_DIR}/antismash/${gid}")
  done

  local seeded_dirs=0
  for stage_root in "${stage_dirs[@]}"; do
    mkdir -p "${stage_root}"
    find "${LOCAL_ANTISMASH_ROOT}" -maxdepth 1 -type f -name "*region*.gbk" -print0 \
      | xargs -0 -I{} cp -f "{}" "${stage_root}/"
    if [[ -n "$(find "${stage_root}" -maxdepth 1 -type f -name '*region*.gbk' -print -quit 2>/dev/null || true)" ]]; then
      seeded_dirs=$((seeded_dirs + 1))
    fi
  done

  if [[ "${seeded_dirs}" -gt 0 ]]; then
    log "Seeded antiSMASH data for PODP run from local results: ${LOCAL_ANTISMASH_ROOT} (dirs seeded=${seeded_dirs})"
    write_genome_status_for_local_antismash
  fi
}

seed_bigscape_for_run() {
  local stage_dir="${RUN_DIR}/bigscape"
  mkdir -p "${stage_dir}"

  if [[ -s "${stage_dir}/data_sqlite.db" ]] || compgen -G "${stage_dir}/mix_clustering_c*.tsv" >/dev/null; then
    return 0
  fi

  if [[ ! -d "${LOCAL_BIGSCAPE_ROOT}" ]]; then
    if [[ "${USE_LOCAL_GENOMICS_ONLY}" == "1" ]]; then
      die "LOCAL_BIGSCAPE_ROOT not found: ${LOCAL_BIGSCAPE_ROOT} (USE_LOCAL_GENOMICS_ONLY=1)"
    fi
    warn "LOCAL_BIGSCAPE_ROOT not found: ${LOCAL_BIGSCAPE_ROOT}; NPLinker may run BiG-SCAPE."
    return 0
  fi

  if [[ -s "${LOCAL_BIGSCAPE_ROOT}/data_sqlite.db" ]]; then
    cp -f "${LOCAL_BIGSCAPE_ROOT}/data_sqlite.db" "${stage_dir}/data_sqlite.db"
  elif [[ -s "${LOCAL_BIGSCAPE_ROOT}/big_scape.db" ]]; then
    cp -f "${LOCAL_BIGSCAPE_ROOT}/big_scape.db" "${stage_dir}/data_sqlite.db"
  else
    local mix_file=""
    mix_file="$(find "${LOCAL_BIGSCAPE_ROOT}" -type f -name 'mix_clustering_c*.tsv' | head -n 1 || true)"
    if [[ -n "${mix_file}" ]]; then
      cp -f "${mix_file}" "${stage_dir}/$(basename "${mix_file}")"
    fi
  fi

  if [[ -s "${stage_dir}/data_sqlite.db" ]] || compgen -G "${stage_dir}/mix_clustering_c*.tsv" >/dev/null; then
    log "Seeded BiG-SCAPE data for run from local results: ${LOCAL_BIGSCAPE_ROOT}"
  elif [[ "${USE_LOCAL_GENOMICS_ONLY}" == "1" ]]; then
    die "Could not seed BiG-SCAPE data from ${LOCAL_BIGSCAPE_ROOT} (USE_LOCAL_GENOMICS_ONLY=1)"
  fi
}

###############################################################################
# Detect container engine
###############################################################################
if [[ -z "${ENGINE}" ]]; then
  if [[ "${NPLINKER_USE_DOCKER_IMAGE}" == "1" ]] && have docker; then ENGINE="docker"
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

[[ -n "${TARGET_STRAIN}" ]] || die "TARGET_STRAIN must be set before running NPLinker"

###############################################################################
# Directories
###############################################################################
mkdir -p "${LOGDIR}" "${NPLINKER_ROOT}" "${WINDOWS_NPLINKER_ROOT}" "${RUN_DIR}" "${WORK_ROOT}"

log "ENGINE=${ENGINE}"
log "RUN_MODE=${RUN_MODE}"
log "NPLINKER_DOCKER_IMAGE=${NPLINKER_DOCKER_IMAGE}"
log "NPLINKER_USE_NATIVE=${NPLINKER_USE_NATIVE}"
log "PODP_ID=${PODP_ID}"
log "TARGET_STRAIN=${TARGET_STRAIN}"
log "GNPS_VERSION=${GNPS_VERSION}"
log "USE_LOCAL_GENOMICS_ONLY=${USE_LOCAL_GENOMICS_ONLY}"
log "FILTER_TARGET_ONLY=${FILTER_TARGET_ONLY}"
log "ALLOW_FILTER_FALLBACK=${ALLOW_FILTER_FALLBACK}"
log "METCALF_STANDARDISED=${METCALF_STANDARDISED}"
log "EXPORT_PREFER_LOCAL=${EXPORT_PREFER_LOCAL}"
log "SUMMARY_EXCLUDE_MIBIG_ONLY=${SUMMARY_EXCLUDE_MIBIG_ONLY}"
log "RUN_DIR=${RUN_DIR}"
log "MIRROR_RUN_DIR=${MIRROR_RUN_DIR}"
log "LOGFILE=${LOGFILE}"

###############################################################################
# Verify explicitly prepared container runtime
###############################################################################
if [[ "${ENGINE}" == "docker" ]]; then
  if docker image inspect "${NPLINKER_DOCKER_IMAGE}" >/dev/null 2>&1; then
    log "NPLinker Docker base image already present: ${NPLINKER_DOCKER_IMAGE}"
  else
    warn "NPLinker Docker image missing: ${NPLINKER_DOCKER_IMAGE}"
    warn "AUTO_PULL_NPLINKER_SIF=${AUTO_PULL_NPLINKER_SIF} is accepted for compatibility; canonical jobs do not pull images."
    runtime_preparation_hint
    exit 1
  fi
elif [[ ! -s "${SIF_PATH}" ]]; then
  warn "NPLinker base image missing: ${SIF_PATH}"
  warn "Configured image source: ${SIF_SOURCE}"
  warn "AUTO_PULL_NPLINKER_SIF=${AUTO_PULL_NPLINKER_SIF} is accepted for compatibility; canonical jobs do not pull images."
  runtime_preparation_hint
  exit 1
else
  log "Container SIF already present: ${SIF_PATH}"
fi

###############################################################################
# Runtime bindings
###############################################################################
BIND_ARGS=(
  --bind "${PROJECT_DIR}:${PROJECT_DIR}"
  --bind "${RESULTS_ROOT}:${RESULTS_ROOT}"
  --bind "${SOFTWARE_ROOT}:${SOFTWARE_ROOT}"
  --bind "${RUN_DIR}:${RUN_DIR}"
  --bind "${WORK_ROOT}:${WORK_ROOT}"
  --bind "/tmp:/tmp"
)

docker_run_args() {
  local -a args=(
    --rm -i --user 0:0 --entrypoint ""
    --cpus "${NPLINKER_DOCKER_CPUS}"
    -e OMP_NUM_THREADS=1
    -e OPENBLAS_NUM_THREADS=1
    -e MKL_NUM_THREADS=1
    -e NUMEXPR_NUM_THREADS=1
  )
  if [[ -n "${NPLINKER_DOCKER_MEMORY}" ]]; then
    args+=(--memory "${NPLINKER_DOCKER_MEMORY}")
  fi
  if [[ -n "${NPLINKER_DOCKER_PIDS_LIMIT}" ]]; then
    args+=(--pids-limit "${NPLINKER_DOCKER_PIDS_LIMIT}")
  fi
  if [[ -n "${CLUSTERWEAVE_JOB_ID:-}" ]]; then
    args+=(--label "clusterweave.job_id=${CLUSTERWEAVE_JOB_ID}" --label "clusterweave.project=${PROJECT_NAME:-}")
  fi
  if [[ -n "${NPLINKER_DOCKER_DATA_VOLUME}" ]]; then
    args+=(-v "${NPLINKER_DOCKER_DATA_VOLUME}:/data")
  else
    args+=(
      -v "${PROJECT_DIR}:${PROJECT_DIR}"
      -v "${RESULTS_ROOT}:${RESULTS_ROOT}"
      -v "${SOFTWARE_ROOT}:${SOFTWARE_ROOT}"
      -v "${RUN_DIR}:${RUN_DIR}"
      -v "${WORK_ROOT}:${WORK_ROOT}"
      -v "/tmp:/tmp"
    )
  fi
  printf '%s\0' "${args[@]}"
}

cexec() {
  if [[ "${ENGINE}" == "docker" ]]; then
    local -a args=()
    mapfile -d '' -t args < <(docker_run_args)
    docker run "${args[@]}" "${NPLINKER_DOCKER_IMAGE}" "$@"
  else
    "${ENGINE}" exec "${BIND_ARGS[@]}" "${SIF_PATH}" "$@"
  fi
}

###############################################################################
# Runner/exporter script (host-side, executed inside container)
###############################################################################
TRACKED_RUNNER_PY="${PROJECT_DIR}/bin/nplinker_run_and_export.py"
[[ -s "${TRACKED_RUNNER_PY}" ]] || die "Tracked NPLinker runner missing: ${TRACKED_RUNNER_PY}"
if [[ "${ENGINE}" == "docker" && -n "${NPLINKER_DOCKER_DATA_VOLUME}" ]]; then
  RUNNER_PY="${RUNNER_PY:-${RUN_DIR}/nplinker_run_and_export.py}"
else
  RUNNER_PY="${RUNNER_PY:-${TRACKED_RUNNER_PY}}"
fi
if [[ "${RUNNER_PY}" != "${TRACKED_RUNNER_PY}" ]]; then
  mkdir -p "$(dirname "${RUNNER_PY}")"
  cp -f "${TRACKED_RUNNER_PY}" "${RUNNER_PY}"
fi
chmod +x "${RUNNER_PY}"

###############################################################################
# Helpers to select NPLinker mode and generate config
###############################################################################
podp_project_exists() {
  local project_id="$1"
  [[ -n "${project_id}" ]] || return 1
  cexec python -c "import urllib.request,sys; u='https://pairedomicsdata.bioinformatics.nl/api/projects/${project_id}'; r=urllib.request.urlopen(u, timeout=25); sys.exit(0 if int(getattr(r,'status',200))==200 else 1)" >/dev/null 2>&1
}

prepare_local_layout() {
  resolve_local_antismash_root
  [[ -d "${LOCAL_ANTISMASH_ROOT}" ]] || die "LOCAL_ANTISMASH_ROOT not found: ${LOCAL_ANTISMASH_ROOT}"
  [[ -n "${LOCAL_GNPS_DIR}" ]] || die "LOCAL_GNPS_DIR must be set for local mode"
  [[ -d "${LOCAL_GNPS_DIR}" ]] || die "LOCAL_GNPS_DIR not found: ${LOCAL_GNPS_DIR}"
  [[ -n "${LOCAL_STRAIN_MAPPING}" ]] || die "LOCAL_STRAIN_MAPPING must be set for local mode"
  [[ -s "${LOCAL_STRAIN_MAPPING}" ]] || die "LOCAL_STRAIN_MAPPING not found: ${LOCAL_STRAIN_MAPPING}"

  mkdir -p "${RUN_DIR}/antismash/${TARGET_STRAIN}" "${RUN_DIR}/gnps"

  # Stage antiSMASH region GBKs under the expected NPLinker folder structure.
  find "${LOCAL_ANTISMASH_ROOT}" -maxdepth 1 -type f -name "*region*.gbk" -print0 \
    | xargs -0 -I{} cp -f "{}" "${RUN_DIR}/antismash/${TARGET_STRAIN}/"
  [[ -n "$(find "${RUN_DIR}/antismash/${TARGET_STRAIN}" -maxdepth 1 -type f -name '*region*.gbk' -print -quit)" ]] \
    || die "No region GBKs found in ${LOCAL_ANTISMASH_ROOT}"

  cp -rf "${LOCAL_GNPS_DIR}/." "${RUN_DIR}/gnps/"
  cp -f "${LOCAL_STRAIN_MAPPING}" "${RUN_DIR}/strain_mappings.json"
}

ACTIVE_MODE=""
case "${RUN_MODE}" in
  podp)
    if podp_project_exists "${PODP_ID}"; then
      ACTIVE_MODE="podp"
      seed_antismash_for_podp
      if [[ -z "$(find "${RUN_DIR}/antismash" -type f -name '*region*.gbk' -print -quit 2>/dev/null || true)" ]] && [[ "${USE_LOCAL_GENOMICS_ONLY}" == "1" ]]; then
        die "No staged antiSMASH region GBKs found under ${RUN_DIR}/antismash (USE_LOCAL_GENOMICS_ONLY=1)"
      fi
      seed_bigscape_for_run
    else
      die "RUN_MODE=podp but PODP_ID=${PODP_ID} was not found at pairedomicsdata.bioinformatics.nl. If this is a MassIVE ID, use RUN_MODE=local with local GNPS + strain_mappings.json."
    fi
    ;;
  local)
    ACTIVE_MODE="local"
    prepare_local_layout
    seed_bigscape_for_run
    ;;
  auto)
    if podp_project_exists "${PODP_ID}"; then
      ACTIVE_MODE="podp"
      seed_antismash_for_podp
      if [[ -z "$(find "${RUN_DIR}/antismash" -type f -name '*region*.gbk' -print -quit 2>/dev/null || true)" ]] && [[ "${USE_LOCAL_GENOMICS_ONLY}" == "1" ]]; then
        die "No staged antiSMASH region GBKs found under ${RUN_DIR}/antismash (USE_LOCAL_GENOMICS_ONLY=1)"
      fi
      seed_bigscape_for_run
      log "Found PODP project for PODP_ID=${PODP_ID}; using mode=podp"
    else
      ACTIVE_MODE="local"
      warn "PODP project not found for ID=${PODP_ID}; falling back to mode=local"
      prepare_local_layout
      seed_bigscape_for_run
    fi
    ;;
  *)
    die "Invalid RUN_MODE=${RUN_MODE}. Use one of: auto, podp, local"
    ;;
esac

log "ACTIVE_MODE=${ACTIVE_MODE}"

###############################################################################
# nplinker.toml
###############################################################################
CONFIG_FILE="${RUN_DIR}/nplinker.toml"
if [[ "${ACTIVE_MODE}" == "podp" ]]; then
cat > "${CONFIG_FILE}" <<EOF
root_dir = "${RUN_DIR}"
mode = "podp"
podp_id = "${PODP_ID}"

[log]
level = "INFO"
use_console = true

[mibig]
to_use = true
version = "3.1"

[bigscape]
version = "2"
cutoff = "0.30"
parameters = "--mibig_version 3.1 --include_singletons --gcf_cutoffs 0.30"

[gnps]
version = "${GNPS_VERSION}"

[scoring]
methods = ["metcalf"]
EOF
else
cat > "${CONFIG_FILE}" <<EOF
root_dir = "${RUN_DIR}"
mode = "local"

[log]
level = "INFO"
use_console = true

[mibig]
to_use = true
version = "3.1"

[bigscape]
version = "2"
cutoff = "0.30"
parameters = "--mibig_version 3.1 --include_singletons --gcf_cutoffs 0.30"

[gnps]
version = "${GNPS_VERSION}"

[scoring]
methods = ["metcalf"]
EOF
fi

###############################################################################
# Clean outputs if requested
###############################################################################
if [[ "${FORCE}" == "1" ]]; then
  log "FORCE=1: removing previous NPLinker output dir"
  rm -rf "${RUN_DIR}/output"
fi

###############################################################################
# Verify explicitly prepared NPLinker environment
###############################################################################
if [[ ! -f "${VENV_DIR}/bin/activate" ]]; then
  warn "NPLinker environment missing: ${VENV_DIR}"
  warn "NPLINKER_BOOTSTRAP_ENV=${NPLINKER_BOOTSTRAP_ENV} and NPLINKER_INSTALL_DEPS=${NPLINKER_INSTALL_DEPS} are accepted compatibility inputs; canonical jobs do not create or install environments."
  runtime_preparation_hint
  exit 1
fi
log "Using prepared NPLinker environment: ${VENV_DIR}"

###############################################################################
# Run + export table
###############################################################################
log "Running NPLinker and exporting ranked links table"
cexec bash -lc "
set -euo pipefail
source '${VENV_DIR}/bin/activate'
export MASSIVE_DATASET_ID='${MASSIVE_DATASET_ID}'
export MASSIVE_USERNAME='${MASSIVE_USERNAME}'
export MASSIVE_PASSWORD='${MASSIVE_PASSWORD}'
export NPLINKER_CONFIG='${CONFIG_FILE}'
export OUT_TABLE='${OUT_TABLE}'
export SUMMARY_TABLE='${SUMMARY_TABLE}'
export TARGET_STRAIN='${TARGET_STRAIN}'
export NPLINKER_METHODS='metcalf'
export MAX_LINKS='5000'
export NPLINKER_HTTP_TIMEOUT='${NPLINKER_HTTP_TIMEOUT}'
export NPLINKER_LOAD_RETRIES='${NPLINKER_LOAD_RETRIES}'
export NPLINKER_RETRY_SLEEP='${NPLINKER_RETRY_SLEEP}'
export FILTER_TARGET_ONLY='${FILTER_TARGET_ONLY}'
export ALLOW_FILTER_FALLBACK='${ALLOW_FILTER_FALLBACK}'
export METCALF_STANDARDISED='${METCALF_STANDARDISED}'
export EXPORT_PREFER_LOCAL='${EXPORT_PREFER_LOCAL}'
export SUMMARY_EXCLUDE_MIBIG_ONLY='${SUMMARY_EXCLUDE_MIBIG_ONLY}'
python '${RUNNER_PY}'
" 2>&1 | tee -a "${LOGFILE}" || {
  warn "NPLinker run failed."
  warn "Troubleshooting:"
  warn "  1) If using PODP mode, ensure PODP_ID is a valid Paired Omics project ID and not only an MSV ID."
  warn "  2) For local mode, set LOCAL_GNPS_DIR and LOCAL_STRAIN_MAPPING."
  warn "  3) Verify the prepared runtime with the worker check-runtime command."
  die "NPLinker execution did not complete."
}

if [[ -s "${OUT_TABLE}" ]]; then
  sync_results_back
  if [[ -s "${MIRROR_OUT_TABLE}" ]]; then
    log "Done. Raw links table: ${MIRROR_OUT_TABLE}"
  else
    log "Done. Raw links table: ${OUT_TABLE}"
  fi
  if [[ -s "${MIRROR_SUMMARY_TABLE}" ]]; then
    log "Done. Summary table: ${MIRROR_SUMMARY_TABLE}"
  elif [[ -s "${SUMMARY_TABLE}" ]]; then
    log "Done. Summary table: ${SUMMARY_TABLE}"
  fi
else
  die "Run completed but output table missing: ${OUT_TABLE}"
fi
