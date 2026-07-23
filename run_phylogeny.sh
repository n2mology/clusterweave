#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

# Optional, bounded sequence-inference follow-up. The core taxonomy/BGC/GCF
# figure is rendered elsewhere and never depends on this runtime.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${SCRIPT_DIR}")}"
DATA_ROOT="${DATA_ROOT:-${SCRIPT_DIR}/data}"
RESULTS_ROOT="${RESULTS_ROOT:-${DATA_ROOT}/results/${PROJECT_NAME}}"
WORK_ROOT="${WORK_ROOT:-${RESULTS_ROOT}/tmp}"
PHYLOGENY_INPUT_ROOT="${PHYLOGENY_INPUT_ROOT:-${RESULTS_ROOT}/phylogeny_inputs}"
PHYLOGENY_FAMILY_MANIFEST="${PHYLOGENY_FAMILY_MANIFEST:-${PHYLOGENY_INPUT_ROOT}/families.tsv}"
PHYLOGENY_RESULTS_ROOT="${PHYLOGENY_RESULTS_ROOT:-${RESULTS_ROOT}/phylogeny}"
PHYLOGENY_WORK_ROOT="${PHYLOGENY_WORK_ROOT:-${WORK_ROOT}/phylogeny}"
PHYLOGENY_LOG_ROOT="${PHYLOGENY_LOG_ROOT:-${RESULTS_ROOT}/logs}"
PHYLOGENY_LOGFILE="${PHYLOGENY_LOGFILE:-${PHYLOGENY_LOG_ROOT}/run_phylogeny.$(date +%Y%m%d_%H%M%S).log}"
PHYLOGENY_MANIFEST_TSV="${PHYLOGENY_MANIFEST_TSV:-${PHYLOGENY_RESULTS_ROOT}/phylogeny_run_manifest.tsv}"
PHYLOGENY_MANIFEST_JSON="${PHYLOGENY_MANIFEST_JSON:-${PHYLOGENY_RESULTS_ROOT}/phylogeny_run_manifest.json}"
PHYLOGENY_SEQUENCE_MAP="${PHYLOGENY_SEQUENCE_MAP:-${PHYLOGENY_INPUT_ROOT}/sequence_taxon_map.tsv}"
PHYLOGENY_TOPOLOGY_RESULTS_TSV="${PHYLOGENY_TOPOLOGY_RESULTS_TSV:-${PHYLOGENY_RESULTS_ROOT}/topology_comparison.tsv}"

RUN_PHYLOGENY="${RUN_PHYLOGENY:-0}"
PHYLOGENY_REQUIRED="${PHYLOGENY_REQUIRED:-0}"
# RUN_PHYLOGENY=1 is itself the explicit preparation request.  Set this to 0
# only when an operator supplies a complete, bounded families.tsv override.
PHYLOGENY_AUTO_PREPARE="${PHYLOGENY_AUTO_PREPARE:-${RUN_PHYLOGENY}}"
PHYLOGENY_AUTO_SELECT_CANDIDATES="${PHYLOGENY_AUTO_SELECT_CANDIDATES:-1}"
PHYLOGENY_PREPARE_HELPER="${PHYLOGENY_PREPARE_HELPER:-${SCRIPT_DIR}/bin/prepare_phylogeny_families.py}"
PHYLOGENY_CANDIDATE_SELECTOR="${PHYLOGENY_CANDIDATE_SELECTOR:-${SCRIPT_DIR}/bin/select_cross_kingdom_candidates.py}"
PHYLOGENY_CANDIDATES_TSV="${PHYLOGENY_CANDIDATES_TSV:-${RESULTS_ROOT}/summary/cross_kingdom_candidates.tsv}"
PHYLOGENY_LEGACY_CANDIDATES_TSV="${PHYLOGENY_LEGACY_CANDIDATES_TSV:-${RESULTS_ROOT}/summary/putative_transfer_candidates.tsv}"
PHYLOGENY_CROSSWALK_TSV="${PHYLOGENY_CROSSWALK_TSV:-${RESULTS_ROOT}/summary/candidate_bgc_gcf_crosswalk.tsv}"
PHYLOGENY_ANTISMASH_ROOT="${PHYLOGENY_ANTISMASH_ROOT:-${RESULTS_ROOT}/antismash}"
PHYLOGENY_MAX_CANDIDATES="${PHYLOGENY_MAX_CANDIDATES:-25}"
PHYLOGENY_MAX_REGIONS_PER_CANDIDATE="${PHYLOGENY_MAX_REGIONS_PER_CANDIDATE:-100}"
PHYLOGENY_MAX_REGION_BYTES="${PHYLOGENY_MAX_REGION_BYTES:-26214400}"
PHYLOGENY_MAX_INPUT_BYTES="${PHYLOGENY_MAX_INPUT_BYTES:-262144000}"
PHYLOGENY_MAX_PREPARED_BYTES="${PHYLOGENY_MAX_PREPARED_BYTES:-50000000}"
PHYLOGENY_CPUS="${PHYLOGENY_CPUS:-1}"
PHYLOGENY_PARALLELISM="${PHYLOGENY_PARALLELISM:-1}"
PHYLOGENY_MAX_FAMILIES="${PHYLOGENY_MAX_FAMILIES:-10}"
PHYLOGENY_MAX_SEQUENCES_PER_FAMILY="${PHYLOGENY_MAX_SEQUENCES_PER_FAMILY:-250}"
PHYLOGENY_MAX_ALIGNMENT_BYTES="${PHYLOGENY_MAX_ALIGNMENT_BYTES:-50000000}"
PHYLOGENY_TIMEOUT_SECONDS="${PHYLOGENY_TIMEOUT_SECONDS:-7200}"
PHYLOGENY_RETAIN_SCRATCH="${PHYLOGENY_RETAIN_SCRATCH:-0}"
PHYLOGENY_RETAIN_ALIGNMENTS="${PHYLOGENY_RETAIN_ALIGNMENTS:-0}"
PHYLOGENY_MAX_LOG_BYTES="${PHYLOGENY_MAX_LOG_BYTES:-2000000}"
PHYLOGENY_MAX_RETAINED_SCRATCH_BYTES="${PHYLOGENY_MAX_RETAINED_SCRATCH_BYTES:-200000000}"
PHYLOGENY_DOCKER_IMAGE="${PHYLOGENY_DOCKER_IMAGE:-clusterweave-phylogeny:1.0.0}"
PHYLOGENY_DOCKER_DATA_VOLUME="${PHYLOGENY_DOCKER_DATA_VOLUME:-${DOCKER_DATA_VOLUME:-${CLUSTERWEAVE_DOCKER_DATA_VOLUME:-}}}"
PHYLOGENY_DOCKER_DATA_ROOT="${PHYLOGENY_DOCKER_DATA_ROOT:-/data}"
PHYLOGENY_SIF_PATH="${PHYLOGENY_SIF_PATH:-${SCRIPT_DIR}/software/phylogeny/clusterweave_phylogeny_1.0.0.sif}"
PHYLOGENY_RUNTIME="${PHYLOGENY_RUNTIME:-auto}"
CLUSTERWEAVE_JOB_ID="${CLUSTERWEAVE_JOB_ID:-}"
CLUSTERWEAVE_CANCEL_FILE="${CLUSTERWEAVE_CANCEL_FILE:-}"
CPUS="${CPUS:-1}"
CLUSTERWEAVE_CHILD_DOCKER_CPUS="${CLUSTERWEAVE_CHILD_DOCKER_CPUS:-${CPUS}}"
CLUSTERWEAVE_TOOL_DOCKER_CPUS="${CLUSTERWEAVE_TOOL_DOCKER_CPUS:-}"
CLUSTERWEAVE_CHILD_DOCKER_MEMORY="${CLUSTERWEAVE_CHILD_DOCKER_MEMORY:-${CLUSTERWEAVE_TOOL_DOCKER_MEMORY:-}}"
CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT="${CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT:-256}"

ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ printf '[%s] [INFO] %s\n' "$(ts)" "$*" | tee -a "${PHYLOGENY_LOGFILE}"; }
warn(){ printf '[%s] [WARN] %s\n' "$(ts)" "$*" | tee -a "${PHYLOGENY_LOGFILE}" >&2; }
die(){ printf '[%s] [ERROR] %s\n' "$(ts)" "$*" | tee -a "${PHYLOGENY_LOGFILE}" >&2; exit 1; }

positive_int() {
  local value="$1" fallback="$2"
  [[ "${value}" =~ ^[0-9]+$ && "${value}" -gt 0 ]] && printf '%s\n' "${value}" || printf '%s\n' "${fallback}"
}

bounded_cpu_limit() {
  local requested="$1" ceiling="${2:-}"
  local numeric_re='^[0-9]+([.][0-9]+)?$'
  if [[ "${ceiling}" =~ ${numeric_re} && "${ceiling}" != "0" && "${ceiling}" != "0.0" ]]; then
    awk -v requested="${requested}" -v ceiling="${ceiling}" \
      'BEGIN { print (requested + 0 <= ceiling + 0) ? requested : ceiling }'
  else
    printf '%s\n' "${requested}"
  fi
}

integer_thread_limit() {
  local limit="$1"
  awk -v limit="${limit}" 'BEGIN { value = int(limit + 0); print (value > 0 ? value : 1) }'
}

safe_id() {
  local value="$1"
  value="$(printf '%s' "${value}" | LC_ALL=C tr -c 'A-Za-z0-9._-' '_')"
  value="${value:0:100}"
  [[ -n "${value}" && "${value}" != "." && "${value}" != ".." ]] || value="family"
  printf '%s\n' "${value}"
}

resolve_python() {
  if command -v python3 >/dev/null 2>&1; then printf '%s\n' python3
  elif command -v python >/dev/null 2>&1; then printf '%s\n' python
  else return 1
  fi
}

mkdir -p "${PHYLOGENY_RESULTS_ROOT}" "${PHYLOGENY_WORK_ROOT}/logs" "${PHYLOGENY_LOG_ROOT}"
: > "${PHYLOGENY_LOGFILE}"
printf 'family_id\ttaxon_group\tgcf_id\tfamily_definition\tsequence_count\tstatus\talignment_method\ttrimming_policy\tmodel_selection\tselected_model\tsupport_method\tcpus\telapsed_seconds\ttree_file\ttopology_status\tmessage\n' > "${PHYLOGENY_MANIFEST_TSV}"

PHYLOGENY_CPUS="$(positive_int "${PHYLOGENY_CPUS}" 1)"
PHYLOGENY_PARALLELISM="$(positive_int "${PHYLOGENY_PARALLELISM}" 1)"
PHYLOGENY_MAX_FAMILIES="$(positive_int "${PHYLOGENY_MAX_FAMILIES}" 10)"
PHYLOGENY_MAX_SEQUENCES_PER_FAMILY="$(positive_int "${PHYLOGENY_MAX_SEQUENCES_PER_FAMILY}" 250)"
PHYLOGENY_MAX_CANDIDATES="$(positive_int "${PHYLOGENY_MAX_CANDIDATES}" 25)"
PHYLOGENY_MAX_REGIONS_PER_CANDIDATE="$(positive_int "${PHYLOGENY_MAX_REGIONS_PER_CANDIDATE}" 100)"
PHYLOGENY_MAX_REGION_BYTES="$(positive_int "${PHYLOGENY_MAX_REGION_BYTES}" 26214400)"
PHYLOGENY_MAX_INPUT_BYTES="$(positive_int "${PHYLOGENY_MAX_INPUT_BYTES}" 262144000)"
PHYLOGENY_MAX_PREPARED_BYTES="$(positive_int "${PHYLOGENY_MAX_PREPARED_BYTES}" 50000000)"
PHYLOGENY_MAX_ALIGNMENT_BYTES="$(positive_int "${PHYLOGENY_MAX_ALIGNMENT_BYTES}" 50000000)"
PHYLOGENY_TIMEOUT_SECONDS="$(positive_int "${PHYLOGENY_TIMEOUT_SECONDS}" 7200)"
PHYLOGENY_MAX_LOG_BYTES="$(positive_int "${PHYLOGENY_MAX_LOG_BYTES}" 2000000)"
PHYLOGENY_MAX_RETAINED_SCRATCH_BYTES="$(positive_int "${PHYLOGENY_MAX_RETAINED_SCRATCH_BYTES}" 200000000)"
CPUS="$(positive_int "${CPUS}" 1)"
[[ "${PHYLOGENY_MAX_CANDIDATES}" -le 100 ]] || PHYLOGENY_MAX_CANDIDATES=100
[[ "${PHYLOGENY_MAX_REGIONS_PER_CANDIDATE}" -le 500 ]] || PHYLOGENY_MAX_REGIONS_PER_CANDIDATE=500
[[ "${PHYLOGENY_MAX_REGION_BYTES}" -le 104857600 ]] || PHYLOGENY_MAX_REGION_BYTES=104857600
[[ "${PHYLOGENY_MAX_INPUT_BYTES}" -le 2147483648 ]] || PHYLOGENY_MAX_INPUT_BYTES=2147483648
[[ "${PHYLOGENY_MAX_PREPARED_BYTES}" -le 200000000 ]] || PHYLOGENY_MAX_PREPARED_BYTES=200000000
[[ "${PHYLOGENY_MAX_FAMILIES}" -le 100 ]] || PHYLOGENY_MAX_FAMILIES=100
[[ "${PHYLOGENY_MAX_SEQUENCES_PER_FAMILY}" -le 1000 ]] || PHYLOGENY_MAX_SEQUENCES_PER_FAMILY=1000
[[ "${PHYLOGENY_MAX_ALIGNMENT_BYTES}" -le 200000000 ]] || PHYLOGENY_MAX_ALIGNMENT_BYTES=200000000
[[ "${PHYLOGENY_TIMEOUT_SECONDS}" -le 86400 ]] || PHYLOGENY_TIMEOUT_SECONDS=86400
[[ "${PHYLOGENY_MAX_LOG_BYTES}" -le 10000000 ]] || PHYLOGENY_MAX_LOG_BYTES=10000000
[[ "${PHYLOGENY_MAX_RETAINED_SCRATCH_BYTES}" -le 1000000000 ]] || PHYLOGENY_MAX_RETAINED_SCRATCH_BYTES=1000000000
CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT="$(positive_int "${CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT}" 256)"
[[ "${CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT}" -le 4096 ]] || CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT=4096
if [[ "${PHYLOGENY_CPUS}" -gt "${CPUS}" ]]; then PHYLOGENY_CPUS="${CPUS}"; fi
DOCKER_CPU_LIMIT="$(bounded_cpu_limit "${PHYLOGENY_CPUS}" "${CLUSTERWEAVE_CHILD_DOCKER_CPUS}")"
DOCKER_CPU_LIMIT="$(bounded_cpu_limit "${DOCKER_CPU_LIMIT}" "${CLUSTERWEAVE_TOOL_DOCKER_CPUS}")"
PHYLOGENY_CPUS="$(integer_thread_limit "${DOCKER_CPU_LIMIT}")"
if [[ $((PHYLOGENY_CPUS * PHYLOGENY_PARALLELISM)) -gt "${CPUS}" ]]; then
  PHYLOGENY_PARALLELISM=$((CPUS / PHYLOGENY_CPUS))
  [[ "${PHYLOGENY_PARALLELISM}" -gt 0 ]] || PHYLOGENY_PARALLELISM=1
fi
# Families currently execute serially so manifest/resource claims reflect the
# actual number of simultaneous child containers rather than an aspirational
# operator value.  The resource planner may still reserve more conservatively.
if [[ "${PHYLOGENY_PARALLELISM}" -gt 1 ]]; then
  PHYLOGENY_PARALLELISM=1
  warn "PHYLOGENY_PARALLELISM normalized to 1 by the bounded serial runner"
fi
if [[ -z "${CLUSTERWEAVE_CHILD_DOCKER_MEMORY}" || "${CLUSTERWEAVE_CHILD_DOCKER_MEMORY}" =~ ^0+([A-Za-z]+)?$ ]]; then
  phylogeny_memory_base_mb="$(positive_int "${WORKER_MEMORY_PHYLOGENY_BASE_MB:-1024}" 1024)"
  phylogeny_memory_per_cpu_mb="$(positive_int "${WORKER_MEMORY_PER_PHYLOGENY_CPU_MB:-2048}" 2048)"
  [[ "${phylogeny_memory_base_mb}" -le 65536 ]] || phylogeny_memory_base_mb=65536
  [[ "${phylogeny_memory_per_cpu_mb}" -le 65536 ]] || phylogeny_memory_per_cpu_mb=65536
  phylogeny_memory_safety_factor="${WORKER_MEMORY_SAFETY_FACTOR:-1.25}"
  [[ "${phylogeny_memory_safety_factor}" =~ ^[0-9]+([.][0-9]+)?$ ]] || phylogeny_memory_safety_factor=1.25
  CLUSTERWEAVE_CHILD_DOCKER_MEMORY="$(awk -v base="${phylogeny_memory_base_mb}" -v per="${phylogeny_memory_per_cpu_mb}" -v cpus="${PHYLOGENY_CPUS}" -v factor="${phylogeny_memory_safety_factor}" 'BEGIN { if (factor < 1) factor=1; if (factor > 4) factor=4; value=int(((base + per * cpus) * factor) + 0.999); if (value > 262144) value=262144; print value "m" }')"
fi

RUN_STATUS="not_requested"
RUN_MESSAGE="Optional sequence phylogeny was not requested"
RUNTIME_KIND="none"
RUNTIME_IDENTITY=""
TOOL_VERSIONS=""
START_SECONDS="${SECONDS}"
ACTIVE_PROCESS_GROUP=""

write_json_manifest() {
  local py=""
  py="$(resolve_python)" || return 0
  CW_STATUS="${RUN_STATUS}" CW_MESSAGE="${RUN_MESSAGE}" CW_RUNTIME="${RUNTIME_KIND}" \
  CW_RUNTIME_IDENTITY="${RUNTIME_IDENTITY}" CW_TOOL_VERSIONS="${TOOL_VERSIONS}" \
  CW_CPUS="${PHYLOGENY_CPUS}" CW_PARALLELISM="${PHYLOGENY_PARALLELISM}" \
  CW_MAX_FAMILIES="${PHYLOGENY_MAX_FAMILIES}" CW_MAX_SEQUENCES="${PHYLOGENY_MAX_SEQUENCES_PER_FAMILY}" \
  CW_MAX_ALIGNMENT_BYTES="${PHYLOGENY_MAX_ALIGNMENT_BYTES}" CW_TIMEOUT_SECONDS="${PHYLOGENY_TIMEOUT_SECONDS}" \
  CW_MAX_RETAINED_SCRATCH_BYTES="${PHYLOGENY_MAX_RETAINED_SCRATCH_BYTES}" \
  CW_CHILD_MEMORY_LIMIT="${CLUSTERWEAVE_CHILD_DOCKER_MEMORY}" \
  CW_AUTO_PREPARE="${PHYLOGENY_AUTO_PREPARE}" CW_TOPOLOGY_TSV="${PHYLOGENY_TOPOLOGY_RESULTS_TSV}" \
  CW_ELAPSED="$((SECONDS - START_SECONDS))" \
  "${py}" - "${PHYLOGENY_MANIFEST_TSV}" "${PHYLOGENY_MANIFEST_JSON}" <<'PY'
import csv
import json
import os
import sys
from pathlib import Path

tsv_path = Path(sys.argv[1])
json_path = Path(sys.argv[2])
rows = []
if tsv_path.exists():
    with tsv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
payload = {
    "schema_version": 1,
    "status": os.environ.get("CW_STATUS", "failed"),
    "message": os.environ.get("CW_MESSAGE", "")[:300],
    "runtime": os.environ.get("CW_RUNTIME", "none"),
    "runtime_identity": os.environ.get("CW_RUNTIME_IDENTITY", "")[:300],
    "tool_versions": os.environ.get("CW_TOOL_VERSIONS", "")[:800],
    "cpus": int(os.environ.get("CW_CPUS", "1")),
    "parallelism": int(os.environ.get("CW_PARALLELISM", "1")),
    "max_families": int(os.environ.get("CW_MAX_FAMILIES", "10")),
    "max_sequences_per_family": int(os.environ.get("CW_MAX_SEQUENCES", "250")),
    "max_alignment_bytes": int(os.environ.get("CW_MAX_ALIGNMENT_BYTES", "50000000")),
    "timeout_seconds": int(os.environ.get("CW_TIMEOUT_SECONDS", "7200")),
    "max_retained_scratch_bytes": int(os.environ.get("CW_MAX_RETAINED_SCRATCH_BYTES", "200000000")),
    "child_memory_limit": os.environ.get("CW_CHILD_MEMORY_LIMIT", ""),
    "auto_prepare": os.environ.get("CW_AUTO_PREPARE", "0") == "1",
    "topology_comparison_count": 0,
    "elapsed_seconds": int(os.environ.get("CW_ELAPSED", "0")),
    "families": rows,
}
topology_path = Path(os.environ.get("CW_TOPOLOGY_TSV", ""))
if topology_path.is_file():
    try:
        with topology_path.open(newline="", encoding="utf-8") as handle:
            payload["topology_comparison_count"] = sum(
                1 for _ in csv.DictReader(handle, delimiter="\t")
            )
    except (OSError, UnicodeError, csv.Error):
        payload["topology_comparison_count"] = 0
json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

finish() {
  local exit_status=$?
  if [[ "${exit_status}" -ne 0 && "${RUN_PHYLOGENY}" == "1" && "${RUN_STATUS}" == "not_requested" ]]; then
    RUN_STATUS="failed"
    RUN_MESSAGE="Optional sequence phylogeny terminated unexpectedly"
  fi
  if [[ -f "${PHYLOGENY_LOGFILE}" && "$(stat -c %s "${PHYLOGENY_LOGFILE}" 2>/dev/null || printf '0')" -gt "${PHYLOGENY_MAX_LOG_BYTES}" ]]; then
    tail -c "${PHYLOGENY_MAX_LOG_BYTES}" "${PHYLOGENY_LOGFILE}" > "${PHYLOGENY_LOGFILE}.bounded" 2>/dev/null || true
    mv -f "${PHYLOGENY_LOGFILE}.bounded" "${PHYLOGENY_LOGFILE}" 2>/dev/null || true
  fi
  write_json_manifest || true
}
trap finish EXIT

cancelled() {
  [[ -n "${CLUSTERWEAVE_CANCEL_FILE}" && -e "${CLUSTERWEAVE_CANCEL_FILE}" ]]
}

on_signal() {
  RUN_STATUS="cancelled"
  RUN_MESSAGE="Optional sequence phylogeny was cancelled"
  if [[ -n "${ACTIVE_PROCESS_GROUP}" ]]; then
    kill -TERM -- "-${ACTIVE_PROCESS_GROUP}" 2>/dev/null || kill -TERM "${ACTIVE_PROCESS_GROUP}" 2>/dev/null || true
    sleep 1
    kill -KILL -- "-${ACTIVE_PROCESS_GROUP}" 2>/dev/null || kill -KILL "${ACTIVE_PROCESS_GROUP}" 2>/dev/null || true
  fi
  printf 'PHYLOGENY_PROGRESS phase=cancel ordinal=0/0 percent=100 message="Cancelled"\n'
  exit 130
}
trap on_signal INT TERM

remaining_stage_seconds() {
  local remaining=$((PHYLOGENY_TIMEOUT_SECONDS - (SECONDS - START_SECONDS)))
  [[ "${remaining}" -gt 0 ]] || remaining=0
  printf '%s\n' "${remaining}"
}

run_bounded_host_command() {
  local remaining
  remaining="$(remaining_stage_seconds)"
  [[ "${remaining}" -gt 0 ]] || return 124
  local timeout_args=(timeout --signal=TERM --kill-after=30 "${remaining}")
  if command -v setsid >/dev/null 2>&1; then
    setsid "${timeout_args[@]}" "$@" &
  else
    "${timeout_args[@]}" "$@" &
  fi
  ACTIVE_PROCESS_GROUP=$!
  while kill -0 "${ACTIVE_PROCESS_GROUP}" 2>/dev/null; do
    cancelled && on_signal
    sleep 1
  done
  local command_status=0
  wait "${ACTIVE_PROCESS_GROUP}" || command_status=$?
  ACTIVE_PROCESS_GROUP=""
  return "${command_status}"
}

if [[ "${RUN_PHYLOGENY}" != "1" ]]; then
  log "request status=not_requested"
  printf 'PHYLOGENY_PROGRESS phase=not_requested ordinal=0/0 percent=100 message="Optional sequence phylogeny not requested"\n'
  exit 0
fi
log "request status=requested required=${PHYLOGENY_REQUIRED} max_families=${PHYLOGENY_MAX_FAMILIES} max_sequences_per_family=${PHYLOGENY_MAX_SEQUENCES_PER_FAMILY}"

# Invalidate prior topology evidence before any requested-run preflight.  A
# missing runtime or failed rerun must never leave stale topology available to
# the terminal evidence stage.
rm -f -- "${PHYLOGENY_TOPOLOGY_RESULTS_TSV}"

detect_runtime() {
  case "${PHYLOGENY_RUNTIME}" in
    docker)
      command -v docker >/dev/null 2>&1 && timeout --signal=TERM --kill-after=5 10 docker image inspect "${PHYLOGENY_DOCKER_IMAGE}" >/dev/null 2>&1 || return 1
      RUNTIME_KIND="docker"
      ;;
    sif|apptainer|singularity)
      [[ -s "${PHYLOGENY_SIF_PATH}" ]] || return 1
      if command -v apptainer >/dev/null 2>&1; then RUNTIME_KIND="apptainer"
      elif command -v singularity >/dev/null 2>&1; then RUNTIME_KIND="singularity"
      else return 1
      fi
      ;;
    auto)
      if command -v docker >/dev/null 2>&1 && timeout --signal=TERM --kill-after=5 10 docker image inspect "${PHYLOGENY_DOCKER_IMAGE}" >/dev/null 2>&1; then
        RUNTIME_KIND="docker"
      elif [[ -s "${PHYLOGENY_SIF_PATH}" ]] && command -v apptainer >/dev/null 2>&1; then
        RUNTIME_KIND="apptainer"
      elif [[ -s "${PHYLOGENY_SIF_PATH}" ]] && command -v singularity >/dev/null 2>&1; then
        RUNTIME_KIND="singularity"
      else
        return 1
      fi
      ;;
    *) return 1 ;;
  esac
}

if ! detect_runtime; then
  RUN_STATUS="tool_unavailable"
  RUN_MESSAGE="Pinned optional phylogeny runtime is unavailable; run explicit setup/preflight"
  printf 'PHYLOGENY_PROGRESS phase=preflight ordinal=0/0 percent=100 message="Pinned runtime unavailable"\n'
  [[ "${PHYLOGENY_REQUIRED}" == "1" ]] && exit 1
  exit 0
fi

runtime_version() {
  local preflight_timeout="${PHYLOGENY_TIMEOUT_SECONDS}"
  [[ "${preflight_timeout}" -le 60 ]] || preflight_timeout=60
  if [[ "${RUNTIME_KIND}" == "docker" ]]; then
    timeout --signal=TERM --kill-after=10 "${preflight_timeout}" \
      docker run --rm --network none --cpus 1 --pids-limit 64 "${PHYLOGENY_DOCKER_IMAGE}" clusterweave-phylogeny-versions
  else
    timeout --signal=TERM --kill-after=10 "${preflight_timeout}" \
      "${RUNTIME_KIND}" exec --cleanenv --containall "${PHYLOGENY_SIF_PATH}" clusterweave-phylogeny-versions
  fi
}

if [[ "${RUNTIME_KIND}" == "docker" ]]; then
  RUNTIME_IDENTITY="$(timeout --signal=TERM --kill-after=5 10 docker image inspect --format '{{.Id}}' "${PHYLOGENY_DOCKER_IMAGE}" 2>/dev/null || true)"
else
  RUNTIME_IDENTITY="sha256:$(sha256sum "${PHYLOGENY_SIF_PATH}" | awk '{print $1}')"
fi
if ! TOOL_VERSIONS="$(runtime_version 2>&1 | tr '\n\t' '; ' | cut -c1-800)"; then
  RUN_STATUS="tool_unavailable"
  RUN_MESSAGE="Pinned optional phylogeny runtime failed its version preflight"
  printf 'PHYLOGENY_PROGRESS phase=preflight ordinal=0/0 percent=100 message="Pinned runtime version check failed"\n'
  [[ "${PHYLOGENY_REQUIRED}" == "1" ]] && exit 1
  exit 0
fi
log "Pinned runtime ready kind=${RUNTIME_KIND} identity=${RUNTIME_IDENTITY:-unavailable} cpus=${PHYLOGENY_CPUS} parallelism=${PHYLOGENY_PARALLELISM} memory=${CLUSTERWEAVE_CHILD_DOCKER_MEMORY} timeout_seconds=${PHYLOGENY_TIMEOUT_SECONDS}"

if [[ "${PHYLOGENY_AUTO_PREPARE}" != "0" && "${PHYLOGENY_AUTO_PREPARE}" != "1" ]]; then
  RUN_STATUS="failed"
  RUN_MESSAGE="PHYLOGENY_AUTO_PREPARE must be 0 or 1"
  printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=100 message="Invalid auto-prepare setting"\n'
  [[ "${PHYLOGENY_REQUIRED}" == "1" ]] && exit 1
  exit 0
fi
if [[ "${PHYLOGENY_AUTO_SELECT_CANDIDATES}" != "0" && "${PHYLOGENY_AUTO_SELECT_CANDIDATES}" != "1" ]]; then
  RUN_STATUS="failed"
  RUN_MESSAGE="PHYLOGENY_AUTO_SELECT_CANDIDATES must be 0 or 1"
  printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=100 message="Invalid candidate-selection setting"\n'
  [[ "${PHYLOGENY_REQUIRED}" == "1" ]] && exit 1
  exit 0
fi

if [[ "${PHYLOGENY_AUTO_PREPARE}" == "1" ]]; then
  prepare_python="$(resolve_python || true)"
  if [[ -z "${prepare_python}" || ! -f "${PHYLOGENY_PREPARE_HELPER}" ]]; then
    RUN_STATUS="tool_unavailable"
    RUN_MESSAGE="Bounded phylogeny family preparation helper is unavailable"
    printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=100 message="Family preparation helper unavailable"\n'
    [[ "${PHYLOGENY_REQUIRED}" == "1" ]] && exit 1
    exit 0
  fi
  if [[ ! -s "${PHYLOGENY_CANDIDATES_TSV}" && -s "${PHYLOGENY_LEGACY_CANDIDATES_TSV}" ]]; then
    PHYLOGENY_CANDIDATES_TSV="${PHYLOGENY_LEGACY_CANDIDATES_TSV}"
  fi
  if [[ ! -s "${PHYLOGENY_CANDIDATES_TSV}" && "${PHYLOGENY_AUTO_SELECT_CANDIDATES}" == "1" ]]; then
    if [[ ! -f "${PHYLOGENY_CANDIDATE_SELECTOR}" || ! -s "${PHYLOGENY_CROSSWALK_TSV}" ]]; then
      RUN_STATUS="insufficient_data"
      RUN_MESSAGE="Cross-domain candidate selection inputs are unavailable"
      printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=100 message="No bounded cross-domain candidates"\n'
      [[ "${PHYLOGENY_REQUIRED}" == "1" ]] && exit 1
      exit 0
    fi
    mkdir -p "$(dirname "${PHYLOGENY_CANDIDATES_TSV}")"
    printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=10 message="Selecting bounded cross-domain GCF candidates"\n'
    set +e
    run_bounded_host_command "${prepare_python}" "${PHYLOGENY_CANDIDATE_SELECTOR}" \
      --explicit-request \
      --crosswalk "${PHYLOGENY_CROSSWALK_TSV}" \
      --output "${PHYLOGENY_CANDIDATES_TSV}" \
      --max-candidates "${PHYLOGENY_MAX_CANDIDATES}" \
      >> "${PHYLOGENY_LOGFILE}" 2>&1
    prepare_status=$?
    set -e
    if [[ "${prepare_status}" -ne 0 ]]; then
      if [[ "${prepare_status}" -eq 124 || "${prepare_status}" -eq 137 ]]; then
        RUN_STATUS="timeout"
        RUN_MESSAGE="Bounded cross-domain candidate selection reached the stage timeout"
        printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=100 message="Candidate selection timed out"\n'
      else
        RUN_STATUS="failed"
        RUN_MESSAGE="Bounded cross-domain candidate selection failed"
        printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=100 message="Candidate selection failed"\n'
      fi
      [[ "${PHYLOGENY_REQUIRED}" == "1" ]] && exit 1
      exit 0
    fi
  fi
  if [[ ! -s "${PHYLOGENY_CANDIDATES_TSV}" || ! -s "${PHYLOGENY_CROSSWALK_TSV}" || ! -d "${PHYLOGENY_ANTISMASH_ROOT}" ]]; then
    RUN_STATUS="insufficient_data"
    RUN_MESSAGE="Shortlisted candidates, canonical crosswalk, or antiSMASH regions are unavailable"
    printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=100 message="Family preparation inputs unavailable"\n'
    [[ "${PHYLOGENY_REQUIRED}" == "1" ]] && exit 1
    exit 0
  fi
  printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=25 message="Preparing explicitly annotated protein families"\n'
  set +e
  run_bounded_host_command "${prepare_python}" "${PHYLOGENY_PREPARE_HELPER}" \
    --explicit-request \
    --candidates "${PHYLOGENY_CANDIDATES_TSV}" \
    --crosswalk "${PHYLOGENY_CROSSWALK_TSV}" \
    --antismash-root "${PHYLOGENY_ANTISMASH_ROOT}" \
    --output-root "${PHYLOGENY_INPUT_ROOT}" \
    --max-candidates "${PHYLOGENY_MAX_CANDIDATES}" \
    --max-families "${PHYLOGENY_MAX_FAMILIES}" \
    --max-sequences-per-family "${PHYLOGENY_MAX_SEQUENCES_PER_FAMILY}" \
    --max-regions-per-candidate "${PHYLOGENY_MAX_REGIONS_PER_CANDIDATE}" \
    --max-region-bytes "${PHYLOGENY_MAX_REGION_BYTES}" \
    --max-total-input-bytes "${PHYLOGENY_MAX_INPUT_BYTES}" \
    --max-total-output-bytes "${PHYLOGENY_MAX_PREPARED_BYTES}" \
    >> "${PHYLOGENY_LOGFILE}" 2>&1
  prepare_status=$?
  set -e
  if [[ "${prepare_status}" -ne 0 ]]; then
    if [[ "${prepare_status}" -eq 124 || "${prepare_status}" -eq 137 ]]; then
      RUN_STATUS="timeout"
      RUN_MESSAGE="Bounded annotated protein-family preparation reached the stage timeout"
      printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=100 message="Family preparation timed out"\n'
    else
      RUN_STATUS="failed"
      RUN_MESSAGE="Bounded annotated protein-family preparation failed"
      printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=100 message="Family preparation failed"\n'
    fi
    [[ "${PHYLOGENY_REQUIRED}" == "1" ]] && exit 1
    exit 0
  fi
  printf 'PHYLOGENY_PROGRESS phase=prepare ordinal=0/0 percent=50 message="Bounded family preparation complete"\n'
fi

if [[ ! -s "${PHYLOGENY_FAMILY_MANIFEST}" ]]; then
  RUN_STATUS="insufficient_data"
  RUN_MESSAGE="No bounded phylogeny family manifest was provided"
  printf 'PHYLOGENY_PROGRESS phase=eligibility ordinal=0/0 percent=100 message="No eligible family manifest"\n'
  [[ "${PHYLOGENY_REQUIRED}" == "1" ]] && exit 1
  exit 0
fi

input_root_real="$(realpath -m "${PHYLOGENY_INPUT_ROOT}")"
mapfile -t FAMILY_ROWS < <(tail -n +2 "${PHYLOGENY_FAMILY_MANIFEST}" | sed '/^[[:space:]]*$/d' | sort)
if [[ "${#FAMILY_ROWS[@]}" -eq 0 ]]; then
  RUN_STATUS="insufficient_data"
  RUN_MESSAGE="Family manifest contains no eligible rows"
  [[ "${PHYLOGENY_REQUIRED}" == "1" ]] && exit 1
  exit 0
fi

TOTAL="${#FAMILY_ROWS[@]}"
if [[ "${TOTAL}" -gt "${PHYLOGENY_MAX_FAMILIES}" ]]; then TOTAL="${PHYLOGENY_MAX_FAMILIES}"; fi
FAILURES=0
SUCCESSES=0
TOPOLOGY_FAILURES=0

run_family_runtime() {
  local family_work="$1" input_relative="$2" mapping_relative="${3:-}"
  local raw_family="${4:-}" tree_id="${5:-}" raw_gcf="${6:-}"
  local remaining_timeout="${7:-1}"
  local mapping_in_container=""
  [[ -n "${mapping_relative}" ]] && mapping_in_container="/inputs/${mapping_relative}"
  local timeout_args=(timeout --signal=TERM --kill-after=30 "${remaining_timeout}")
  local command='set -eu; mafft --thread "$1" --auto "$2" > aligned.faa; trimal -in aligned.faa -out trimmed.faa -automated1; iqtree2 -s trimmed.faa -nt "$1" -m MFP -B 1000 --prefix family; selected_model="$(awk -F ": " "/Best-fit model according to BIC:/{print \$2; exit}" family.iqtree)"; [ -n "$selected_model" ] || selected_model=undetermined; if [ -n "$3" ] && [ -n "$4" ] && [ -n "$5" ] && [ -n "$6" ] && command -v clusterweave-compare-gene-tree-taxonomy >/dev/null 2>&1; then clusterweave-compare-gene-tree-taxonomy --explicit-request --tree family.treefile --mapping "$3" --family-id "$4" --tree-id "$5" --gcf-id "$6" --selected-model "$selected_model" --output topology_comparison.tsv || printf "%s\n" "optional ETE4 topology comparison unavailable" >&2; fi'
  if [[ "${RUNTIME_KIND}" == "docker" ]]; then
    local docker_args=(run --rm --network none --cpus "${DOCKER_CPU_LIMIT}" --pids-limit "${CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT}")
    local runtime_uid_gid input_in_container work_in_container data_root_real
    runtime_uid_gid="$(stat -c '%u:%g' "${family_work}")"
    input_in_container="/inputs/${input_relative}"
    work_in_container="/work"
    [[ -n "${CLUSTERWEAVE_CHILD_DOCKER_MEMORY}" ]] && docker_args+=(--memory "${CLUSTERWEAVE_CHILD_DOCKER_MEMORY}")
    [[ -n "${CLUSTERWEAVE_JOB_ID}" ]] && docker_args+=(--label "clusterweave.job_id=${CLUSTERWEAVE_JOB_ID}" --label "clusterweave.stage=phylogeny")
    docker_args+=(--user "${runtime_uid_gid}")
    if [[ -n "${PHYLOGENY_DOCKER_DATA_VOLUME}" ]]; then
      data_root_real="$(realpath -m "${PHYLOGENY_DOCKER_DATA_ROOT}")"
      if [[ "${data_root_real}" == "/" || "${input_root_real}" != "${data_root_real}/"* || "${family_work}" != "${data_root_real}/"* ]]; then
        printf 'Named-volume phylogeny paths must stay below %s\n' "${data_root_real}" >&2
        return 2
      fi
      input_in_container="${input_root_real}/${input_relative}"
      [[ -n "${mapping_relative}" ]] && mapping_in_container="${input_root_real}/${mapping_relative}"
      work_in_container="${family_work}"
      docker_args+=(-v "${PHYLOGENY_DOCKER_DATA_VOLUME}:${data_root_real}:rw")
    else
      docker_args+=(-v "${input_root_real}:/inputs:ro" -v "${family_work}:/work:rw")
    fi
    docker_args+=(-w "${work_in_container}" "${PHYLOGENY_DOCKER_IMAGE}")
    if command -v setsid >/dev/null 2>&1; then
      exec setsid "${timeout_args[@]}" docker "${docker_args[@]}" sh -c "${command}" sh "${PHYLOGENY_CPUS}" "${input_in_container}" "${mapping_in_container}" "${raw_family}" "${tree_id}" "${raw_gcf}"
    fi
    exec "${timeout_args[@]}" docker "${docker_args[@]}" sh -c "${command}" sh "${PHYLOGENY_CPUS}" "${input_in_container}" "${mapping_in_container}" "${raw_family}" "${tree_id}" "${raw_gcf}"
  else
    if command -v setsid >/dev/null 2>&1; then
      exec setsid "${timeout_args[@]}" "${RUNTIME_KIND}" exec --cleanenv --containall \
        --bind "${input_root_real}:/inputs:ro,${family_work}:/work:rw" --pwd /work \
        "${PHYLOGENY_SIF_PATH}" sh -c "${command}" sh "${PHYLOGENY_CPUS}" "/inputs/${input_relative}" "${mapping_in_container}" "${raw_family}" "${tree_id}" "${raw_gcf}"
    fi
    exec "${timeout_args[@]}" "${RUNTIME_KIND}" exec --cleanenv --containall \
      --bind "${input_root_real}:/inputs:ro,${family_work}:/work:rw" --pwd /work \
      "${PHYLOGENY_SIF_PATH}" sh -c "${command}" sh "${PHYLOGENY_CPUS}" "/inputs/${input_relative}" "${mapping_in_container}" "${raw_family}" "${tree_id}" "${raw_gcf}"
  fi
}

truncate_private_log() {
  local path="$1" temporary="${1}.bounded"
  [[ -f "${path}" ]] || return 0
  if [[ "$(stat -c %s "${path}")" -gt "${PHYLOGENY_MAX_LOG_BYTES}" ]]; then
    tail -c "${PHYLOGENY_MAX_LOG_BYTES}" "${path}" > "${temporary}"
    mv -f "${temporary}" "${path}"
  fi
}

RETAINED_SCRATCH_BYTES=0
SCRATCH_REMOVED_OVER_LIMIT=0
retain_or_remove_family_work() {
  local path="$1" scratch_bytes=0
  SCRATCH_REMOVED_OVER_LIMIT=0
  [[ -d "${path}" ]] || return 0
  if [[ "${PHYLOGENY_RETAIN_SCRATCH}" == "1" ]]; then
    scratch_bytes="$(du -sb "${path}" 2>/dev/null | awk '{print $1}' || true)"
    scratch_bytes="$(positive_int "${scratch_bytes:-0}" 1)"
    if [[ $((RETAINED_SCRATCH_BYTES + scratch_bytes)) -le "${PHYLOGENY_MAX_RETAINED_SCRATCH_BYTES}" ]]; then
      RETAINED_SCRATCH_BYTES=$((RETAINED_SCRATCH_BYTES + scratch_bytes))
      return 0
    fi
    SCRATCH_REMOVED_OVER_LIMIT=1
  fi
  rm -rf -- "${path}"
}

for ((index=0; index<TOTAL; index++)); do
  cancelled && on_signal
  IFS=$'\t' read -r raw_family taxon_group raw_path raw_mapping raw_gcf raw_annotation _rest <<< "${FAMILY_ROWS[index]}"
  family_id="$(safe_id "${raw_family}")__$(printf '%s\t%s\t%s' "${raw_family}" "${taxon_group}" "${index}" | sha256sum | cut -c1-8)"
  taxon_group="$(printf '%s' "${taxon_group:-unresolved}" | tr '[:upper:]' '[:lower:]')"
  case "${taxon_group}" in fungi|bacteria|both) ;; *) taxon_group="unresolved" ;; esac
  input_file="$(realpath -m "${raw_path}")"
  mapping_file="$(realpath -m "${raw_mapping:-/nonexistent}")"
  mapping_relative=""
  if [[ "${mapping_file}" == "${input_root_real}/"* && -s "${mapping_file}" && "${raw_family}" =~ ^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,199}$ && "${raw_gcf:-}" =~ ^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,199}$ ]]; then
    mapping_relative="${mapping_file#${input_root_real}/}"
  fi
  status="failed"
  message=""
  selected_model="undetermined"
  topology_status="not_requested"
  sequence_count=0
  elapsed=0
  tree_file=""
  family_started="${SECONDS}"
  ordinal=$((index + 1))
  percent=$((ordinal * 100 / TOTAL))
  remaining_seconds=$((PHYLOGENY_TIMEOUT_SECONDS - (SECONDS - START_SECONDS)))
  printf 'PHYLOGENY_PROGRESS phase=family ordinal=%s/%s percent=%s message="Running bounded family inference"\n' "${ordinal}" "${TOTAL}" "${percent}"
  log "family=${family_id} ordinal=${ordinal}/${TOTAL} status=running"

  if [[ "${remaining_seconds}" -le 0 ]]; then
    status="timeout"; message="stage_elapsed_time_limit_reached"
  elif [[ "${input_file}" != "${input_root_real}/"* || ! -s "${input_file}" ]]; then
    status="failed"; message="input_outside_allowed_root_or_missing"
  elif [[ "$(stat -c %s "${input_file}")" -gt "${PHYLOGENY_MAX_ALIGNMENT_BYTES}" ]]; then
    status="insufficient_data"; message="input_exceeds_alignment_byte_limit"
  else
    sequence_count="$(grep -c '^>' "${input_file}" || true)"
    if [[ "${sequence_count}" -lt 3 ]]; then
      status="insufficient_data"; message="fewer_than_three_sequences"
    elif [[ "${sequence_count}" -gt "${PHYLOGENY_MAX_SEQUENCES_PER_FAMILY}" ]]; then
      status="insufficient_data"; message="sequence_count_exceeds_limit"
    else
      family_work="${PHYLOGENY_WORK_ROOT}/${family_id}"
      family_result="${PHYLOGENY_RESULTS_ROOT}/${family_id}"
      rm -rf "${family_work}"
      mkdir -p "${family_work}" "${family_result}"
      rm -f -- "${family_result}/${family_id}.topology.tsv"
      input_relative="${input_file#${input_root_real}/}"
      stdout_log="${PHYLOGENY_WORK_ROOT}/logs/${family_id}.stdout.log"
      stderr_log="${PHYLOGENY_WORK_ROOT}/logs/${family_id}.stderr.log"
      set +e
      run_family_runtime "${family_work}" "${input_relative}" "${mapping_relative}" "${raw_family}" "${family_id}" "${raw_gcf:-}" "${remaining_seconds}" >"${stdout_log}" 2>"${stderr_log}" &
      ACTIVE_PROCESS_GROUP=$!
      while kill -0 "${ACTIVE_PROCESS_GROUP}" 2>/dev/null; do
        cancelled && on_signal
        sleep 1
      done
      wait "${ACTIVE_PROCESS_GROUP}"
      runtime_status=$?
      ACTIVE_PROCESS_GROUP=""
      set -e
      truncate_private_log "${stdout_log}"
      truncate_private_log "${stderr_log}"
      if [[ "${runtime_status}" -eq 0 && -s "${family_work}/family.treefile" ]]; then
        selected_model="$(awk -F ': ' '/Best-fit model according to BIC:/{print $2; exit}' "${family_work}/family.iqtree" 2>/dev/null | LC_ALL=C tr -cd 'A-Za-z0-9_.:+-' | cut -c1-100)"
        [[ -n "${selected_model}" ]] || selected_model="undetermined"
        cp -f "${family_work}/family.treefile" "${family_result}/${family_id}.treefile"
        cp -f "${family_work}/family.iqtree" "${family_result}/${family_id}.iqtree" 2>/dev/null || true
        if [[ "${PHYLOGENY_RETAIN_ALIGNMENTS}" == "1" ]]; then
          cp -f "${family_work}/trimmed.faa" "${family_result}/${family_id}.trimmed.faa" 2>/dev/null || true
        fi
        if [[ -s "${family_work}/topology_comparison.tsv" ]]; then
          cp -f "${family_work}/topology_comparison.tsv" "${family_result}/${family_id}.topology.tsv"
          if [[ ! -s "${PHYLOGENY_TOPOLOGY_RESULTS_TSV}" ]]; then
            cp -f "${family_work}/topology_comparison.tsv" "${PHYLOGENY_TOPOLOGY_RESULTS_TSV}"
          else
            tail -n +2 "${family_work}/topology_comparison.tsv" >> "${PHYLOGENY_TOPOLOGY_RESULTS_TSV}"
          fi
          topology_status="$(awk -F '\t' 'NR == 1 { for (i = 1; i <= NF; i++) h[$i] = i; next } NR == 2 { print $(h["comparison_status"]); exit }' "${family_work}/topology_comparison.tsv")"
          topology_status="$(safe_id "${topology_status:-unavailable}")"
          printf 'TOPOLOGY_COMPARISON family=%s status=%s message="Computational context does not establish an evolutionary event, mechanism, or direction."\n' "${family_id}" "${topology_status}"
        elif [[ -n "${mapping_relative}" ]]; then
          topology_status="unavailable"
          TOPOLOGY_FAILURES=$((TOPOLOGY_FAILURES + 1))
          printf 'TOPOLOGY_COMPARISON family=%s status=unavailable message="Optional ETE4 comparison unavailable; tree retained"\n' "${family_id}"
        else
          topology_status="insufficient_data"
        fi
        tree_file="${family_id}/${family_id}.treefile"
        status="success"; message="bounded_family_inference_complete"
      elif [[ "${runtime_status}" -eq 124 || "${runtime_status}" -eq 137 ]]; then
        status="timeout"; message="family_inference_timeout"
      else
        status="failed"; message="mafft_trimal_or_iqtree_failed"
      fi
      retain_or_remove_family_work "${family_work}"
      if [[ "${status}" == "success" && "${SCRATCH_REMOVED_OVER_LIMIT}" == "1" ]]; then
        message="bounded_family_inference_complete_scratch_removed_over_limit"
      elif [[ "${SCRATCH_REMOVED_OVER_LIMIT}" == "1" ]]; then
        message="${message}_scratch_removed_over_limit"
      fi
    fi
  fi
  if [[ "${status}" == "success" ]]; then
    SUCCESSES=$((SUCCESSES + 1))
  elif [[ "${status}" == "failed" || "${status}" == "timeout" ]]; then
    FAILURES=$((FAILURES + 1))
  fi
  elapsed=$((SECONDS - family_started))
  safe_gcf="$(safe_id "${raw_gcf:-unavailable}")"
  safe_definition="$(safe_id "${raw_annotation:-unavailable}")"
  printf '%s\t%s\t%s\t%s\t%s\t%s\tMAFFT_7.526\ttrimAl_automated1\tMFP\t%s\t1000_ultrafast_bootstrap\t%s\t%s\t%s\t%s\t%s\n' \
    "${family_id}" "${taxon_group}" "${safe_gcf}" "${safe_definition}" "${sequence_count}" "${status}" "${selected_model}" "${PHYLOGENY_CPUS}" "${elapsed}" "${tree_file}" "${topology_status}" "${message}" >> "${PHYLOGENY_MANIFEST_TSV}"
  log "family=${family_id} status=${status} topology_status=${topology_status} sequences=${sequence_count} elapsed_seconds=${elapsed}"
done

if [[ "${SUCCESSES}" -gt 0 && "${FAILURES}" -eq 0 && "${TOPOLOGY_FAILURES}" -eq 0 ]]; then
  RUN_STATUS="success"
  RUN_MESSAGE="Bounded optional sequence phylogeny completed"
elif [[ "${SUCCESSES}" -gt 0 ]]; then
  RUN_STATUS="success_with_optional_failures"
  RUN_MESSAGE="Some optional families failed; successful trees were retained"
elif [[ "${FAILURES}" -gt 0 ]]; then
  RUN_STATUS="failed"
  RUN_MESSAGE="No optional family tree completed"
else
  RUN_STATUS="insufficient_data"
  RUN_MESSAGE="No family passed bounded eligibility checks"
fi

printf 'TREE_ARTIFACT kind=sequence_phylogeny basis=gene_family status=%s elapsed_s=%s\n' "${RUN_STATUS}" "$((SECONDS - START_SECONDS))"
if [[ "${PHYLOGENY_REQUIRED}" == "1" && "${RUN_STATUS}" != "success" ]]; then exit 1; fi
exit 0
