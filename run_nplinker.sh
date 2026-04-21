#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

###############################################################################
# run_nplinker.sh
# - Runs NPLinker for a configured target strain
# - Pulls/uses a Singularity/Apptainer image (same pattern as other project scripts)
# - Exports a ranked TSV table of predicted links
###############################################################################

###############################################################################
# Env-backed project paths
###############################################################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
PROJECTS_ROOT="${PROJECTS_ROOT:-${PROJECT_DIR}}"
DATA_ROOT="${DATA_ROOT:-${PROJECTS_ROOT}/Data}"
TOOLS_ROOT="${TOOLS_ROOT:-${PROJECTS_ROOT}/Software}"
RESULTS_BASE="${RESULTS_BASE:-${DATA_ROOT}/Results}"
RESULTS_ROOT="${RESULTS_ROOT:-${RESULTS_BASE}/${PROJECT_NAME}}"
SOFTWARE_ROOT="${SOFTWARE_ROOT:-${TOOLS_ROOT}/nplinker}"

###############################################################################
# Tunables
###############################################################################
ENGINE="${ENGINE:-}"
FORCE="${FORCE:-0}"
CPUS="${CPUS:-6}"

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
ALLOW_FILTER_FALLBACK="${ALLOW_FILTER_FALLBACK:-1}"
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

  local discovered=""
  discovered="$(find "${RESULTS_ROOT}/antismash" -maxdepth 1 -mindepth 1 -type d | head -n 1 || true)"
  if [[ -n "${discovered}" ]]; then
    warn "LOCAL_ANTISMASH_ROOT not found: ${LOCAL_ANTISMASH_ROOT}"
    warn "Using discovered antiSMASH directory: ${discovered}"
    LOCAL_ANTISMASH_ROOT="${discovered}"
  fi
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

write_genome_status_for_local_antismash() {
  local status_file="${RUN_DIR}/downloads/genome_status.json"
  mkdir -p "${RUN_DIR}/downloads"

  mapfile -t _podp_ids < <(get_podp_genome_ids)
  if [[ "${#_podp_ids[@]}" -eq 0 ]]; then
    return 0
  fi

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
    printf '], "version": "1.0"}\n'
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
  if have singularity; then ENGINE="singularity"
  elif have apptainer; then ENGINE="apptainer"
  else die "singularity/apptainer not found in PATH"
  fi
fi

[[ -n "${TARGET_STRAIN}" ]] || die "TARGET_STRAIN must be set before running NPLinker"

###############################################################################
# Directories
###############################################################################
mkdir -p "${LOGDIR}" "${SOFTWARE_ROOT}" "${PIP_CACHE}" "${NPLINKER_ROOT}" "${WINDOWS_NPLINKER_ROOT}" "${RUN_DIR}" "${WORK_ROOT}" "${PROJECT_DIR}/bin"

log "ENGINE=${ENGINE}"
log "RUN_MODE=${RUN_MODE}"
log "NPLINKER_USE_NATIVE=${NPLINKER_USE_NATIVE}"
log "PODP_ID=${PODP_ID}"
log "TARGET_STRAIN=${TARGET_STRAIN}"
log "GNPS_VERSION=${GNPS_VERSION}"
log "USE_LOCAL_GENOMICS_ONLY=${USE_LOCAL_GENOMICS_ONLY}"
log "FILTER_TARGET_ONLY=${FILTER_TARGET_ONLY}"
log "METCALF_STANDARDISED=${METCALF_STANDARDISED}"
log "EXPORT_PREFER_LOCAL=${EXPORT_PREFER_LOCAL}"
log "SUMMARY_EXCLUDE_MIBIG_ONLY=${SUMMARY_EXCLUDE_MIBIG_ONLY}"
log "RUN_DIR=${RUN_DIR}"
log "MIRROR_RUN_DIR=${MIRROR_RUN_DIR}"
log "LOGFILE=${LOGFILE}"

###############################################################################
# Pull container
###############################################################################
if [[ ! -s "${SIF_PATH}" ]]; then
  [[ "${AUTO_PULL_NPLINKER_SIF}" == "1" ]] || die "NPLinker base image missing: ${SIF_PATH}. Set AUTO_PULL_NPLINKER_SIF=1 to fetch it."
  log "Pulling NPLinker base image: ${SIF_SOURCE} -> ${SIF_PATH}"
  "${ENGINE}" pull "${SIF_PATH}" "${SIF_SOURCE}" 2>&1 | tee -a "${LOGFILE}" || die "Container pull failed"
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

cexec() {
  "${ENGINE}" exec "${BIND_ARGS[@]}" "${SIF_PATH}" "$@"
}

###############################################################################
# Runner/exporter script (host-side, executed inside container)
###############################################################################
RUNNER_PY="${PROJECT_DIR}/bin/nplinker_run_and_export.py"
if [[ ! -s "${RUNNER_PY}" ]]; then
cat > "${RUNNER_PY}" <<'PY'
#!/usr/bin/env python3
from __future__ import annotations

import csv
import os
import time
from pathlib import Path

import httpx
from nplinker import NPLinker


def _obj_id(obj):
    for attr in ("id", "name", "spectrum_id", "gcf_id", "bgc_id"):
        if hasattr(obj, attr):
            val = getattr(obj, attr)
            if val is not None:
                return str(val)
    return str(obj)


def _obj_type(obj):
    return obj.__class__.__name__


def _obj_strains(obj):
    out = []
    strains = getattr(obj, "strains", None)
    if strains:
        for s in strains:
            sid = getattr(s, "id", None)
            out.append(str(sid) if sid is not None else str(s))
    strain = getattr(obj, "strain", None)
    if strain is not None:
        sid = getattr(strain, "id", None)
        out.append(str(sid) if sid is not None else str(strain))
    seen = []
    for x in out:
        if x not in seen:
            seen.append(x)
    return ";".join(seen)


def _score_value(score_obj):
    if score_obj is None:
        return ""
    for attr in ("value", "score"):
        if hasattr(score_obj, attr):
            v = getattr(score_obj, attr)
            if v is not None:
                return v
    return score_obj


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_genomic(obj):
    return _obj_type(obj) == "GCF"


def _bgc_source(genomic_obj):
    strains = _obj_strains(genomic_obj)
    if "BGC" in strains:
        return "MiBIG"
    if strains:
        return strains
    return "Local"


def _is_mibig_only(genomic_obj):
    if hasattr(genomic_obj, "has_mibig_only"):
        try:
            return bool(genomic_obj.has_mibig_only())
        except Exception:
            return False
    strains = _obj_strains(genomic_obj)
    target = os.environ.get("TARGET_STRAIN", "").strip()
    return "BGC" in strains and (not target or target not in strains)


def _pretty_bgc_label(genomic_obj):
    genomic_id = _obj_id(genomic_obj)
    strains = _obj_strains(genomic_obj)
    aliases = [x.strip() for x in strains.split(";") if x.strip()]
    mibig_aliases = [x for x in aliases if x.startswith("BGC")]
    if mibig_aliases:
        return f"{mibig_aliases[0]} (MiBIG)"
    return f"GCF:{genomic_id}"


def _has_target(obj, target):
    target_l = target.lower()
    if target_l in _obj_id(obj).lower():
        return True
    strains = _obj_strains(obj).lower()
    if target_l and target_l in strains:
        return True
    return False


def main():
    config_file = Path(os.environ["NPLINKER_CONFIG"])
    out_table = Path(os.environ["OUT_TABLE"])
    summary_table = Path(os.environ["SUMMARY_TABLE"])
    target = os.environ.get("TARGET_STRAIN", "").strip()
    methods = [x.strip() for x in os.environ.get("NPLINKER_METHODS", "metcalf").split(",") if x.strip()]
    primary_method = methods[0] if methods else "metcalf"
    max_pairs = int(os.environ.get("MAX_LINKS", "5000"))
    http_timeout = float(os.environ.get("NPLINKER_HTTP_TIMEOUT", "180"))
    load_retries = int(os.environ.get("NPLINKER_LOAD_RETRIES", "3"))
    retry_sleep = int(os.environ.get("NPLINKER_RETRY_SLEEP", "20"))
    filter_target_only = os.environ.get("FILTER_TARGET_ONLY", "0").strip().lower() in {"1", "true", "yes", "on"}
    allow_filter_fallback = os.environ.get("ALLOW_FILTER_FALLBACK", "1").strip().lower() in {"1", "true", "yes", "on"}
    metcalf_standardised = os.environ.get("METCALF_STANDARDISED", "1").strip().lower() in {"1", "true", "yes", "on"}
    export_prefer_local = os.environ.get("EXPORT_PREFER_LOCAL", "1").strip().lower() in {"1", "true", "yes", "on"}
    summary_exclude_mibig_only = os.environ.get("SUMMARY_EXCLUDE_MIBIG_ONLY", "1").strip().lower() in {"1", "true", "yes", "on"}

    out_table.parent.mkdir(parents=True, exist_ok=True)
    summary_table.parent.mkdir(parents=True, exist_ok=True)

    # NPLinker internals call httpx.get() without an explicit timeout in some paths.
    # Patch the default timeout to reduce transient GNPS/PODP timeout failures.
    _orig_httpx_get = httpx.get
    def _patched_httpx_get(*args, **kwargs):
        if "timeout" not in kwargs or kwargs["timeout"] is None:
            kwargs["timeout"] = http_timeout
        return _orig_httpx_get(*args, **kwargs)
    httpx.get = _patched_httpx_get

    npl = NPLinker(str(config_file))
    last_exc = None
    for attempt in range(1, load_retries + 1):
        try:
            npl.load_data()
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < load_retries:
                print(f"[WARN] npl.load_data() failed on attempt {attempt}/{load_retries}: {type(exc).__name__}: {exc}")
                print(f"[WARN] sleeping {retry_sleep}s before retry")
                time.sleep(retry_sleep)
    if last_exc is not None:
        raise last_exc

    sources = npl.gcfs
    scoring_params = {}
    if primary_method == "metcalf":
        scoring_params["standardised"] = metcalf_standardised
    link_graph = npl.get_links(sources, primary_method, **scoring_params)
    if primary_method == "metcalf" and metcalf_standardised and len(link_graph.links) == 0:
        print("[WARN] standardised Metcalf produced 0 links; falling back to raw Metcalf")
        link_graph = npl.get_links(sources, primary_method, standardised=False)
    pairs = list(link_graph.links)

    rows_all = []
    rows_target = []
    for pair in pairs:
        if len(pair) < 2:
            continue
        left, right = pair[0], pair[1]
        is_target_pair = bool(target) and (_has_target(left, target) or _has_target(right, target))
        data = link_graph.get_link_data(left, right)
        row = {
            "left_type": _obj_type(left),
            "left_id": _obj_id(left),
            "left_strains": _obj_strains(left),
            "right_type": _obj_type(right),
            "right_id": _obj_id(right),
            "right_strains": _obj_strains(right),
            "_is_mibig_only": _is_mibig_only(right if _is_genomic(right) else left),
        }
        for method in methods:
            row[f"{method}_score"] = _score_value(data.get(method, None)) if hasattr(data, "get") else ""
        rows_all.append(row)
        if is_target_pair:
            rows_target.append(row)

    rows = rows_target if filter_target_only else rows_all
    if filter_target_only and len(rows) == 0 and allow_filter_fallback:
        print("[WARN] target-only filtering produced 0 links; falling back to unfiltered links")
        rows = rows_all

    score_key = f"{methods[0]}_score" if methods else "metcalf_score"
    if export_prefer_local:
        rows.sort(key=lambda r: (1 if r.get("_is_mibig_only") else 0, -_as_float(r.get(score_key, 0.0) or 0.0), str(r.get("right_id", "")), str(r.get("left_id", ""))))
    else:
        rows.sort(key=lambda r: _as_float(r.get(score_key, 0.0) or 0.0), reverse=True)
    if max_pairs > 0:
        rows = rows[:max_pairs]

    fields = [
        "left_type",
        "left_id",
        "left_strains",
        "right_type",
        "right_id",
        "right_strains",
    ] + [f"{m}_score" for m in methods]

    with out_table.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    summary_rows = []
    for pair in pairs:
        if len(pair) < 2:
            continue
        left, right = pair[0], pair[1]
        genomic_obj = left if _is_genomic(left) else right
        metabolomic_obj = right if _is_genomic(left) else left
        if summary_exclude_mibig_only and _is_mibig_only(genomic_obj):
            continue
        if target and not (_has_target(left, target) or _has_target(right, target)):
            if filter_target_only and not allow_filter_fallback:
                continue
        data = link_graph.get_link_data(left, right)
        metcalf_value = _score_value(data.get(primary_method, None)) if hasattr(data, "get") else ""
        summary_rows.append(
            {
                "Class": "",
                "SM": f"{_obj_type(metabolomic_obj)}:{_obj_id(metabolomic_obj)}",
                "BGC": _pretty_bgc_label(genomic_obj),
                "Metcalf score": metcalf_value,
                "BGC source": _bgc_source(genomic_obj),
                "Bioactivity": "",
                "Status": "putative",
            }
        )

    deduped_summary = {}
    for row in summary_rows:
        key = (row["SM"], row["BGC"])
        existing = deduped_summary.get(key)
        if existing is None or _as_float(row["Metcalf score"]) > _as_float(existing["Metcalf score"]):
            deduped_summary[key] = row

    summary_rows = list(deduped_summary.values())
    summary_rows.sort(key=lambda r: _as_float(r.get("Metcalf score", 0.0) or 0.0), reverse=True)
    if max_pairs > 0:
        summary_rows = summary_rows[:max_pairs]

    summary_fields = ["Class", "SM", "BGC", "Metcalf score", "BGC source", "Bioactivity", "Status"]
    with summary_table.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"Wrote {len(rows)} links to {out_table}")
    print(f"Wrote {len(summary_rows)} summary rows to {summary_table}")


if __name__ == "__main__":
    main()
PY
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
# Bootstrap NPLinker inside container env
###############################################################################
if [[ "${NPLINKER_BOOTSTRAP_ENV}" == "1" ]]; then
  log "Bootstrapping NPLinker environment in ${VENV_DIR}"
  cexec bash -lc "
  set -euo pipefail
  python -m venv '${VENV_DIR}'
  source '${VENV_DIR}/bin/activate'
  python -m pip install --cache-dir '${PIP_CACHE}' -U pip setuptools wheel
  python -m pip install --cache-dir '${PIP_CACHE}' 'nplinker==${NPLINKER_VERSION}'
  if [[ '${NPLINKER_INSTALL_DEPS}' == '1' ]] && command -v install-nplinker-deps >/dev/null 2>&1; then
    install-nplinker-deps || true
  fi
  "
else
  log "NPLinker bootstrap is disabled by default"
  [[ -f "${VENV_DIR}/bin/activate" ]] || die "NPLinker environment missing: ${VENV_DIR}. Set NPLINKER_BOOTSTRAP_ENV=1 to create it."
fi

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
python '${RUNNER_PY}'
" 2>&1 | tee -a "${LOGFILE}" || {
  warn "NPLinker run failed."
  warn "Troubleshooting:"
  warn "  1) If using PODP mode, ensure PODP_ID is a valid Paired Omics project ID and not only an MSV ID."
  warn "  2) For local mode, set LOCAL_GNPS_DIR and LOCAL_STRAIN_MAPPING."
  warn "  3) Optional deps installer is off by default; enable with NPLINKER_INSTALL_DEPS=1."
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
