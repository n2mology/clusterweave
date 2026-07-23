#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

# Optional terminal follow-up for bounded cross-kingdom evidence.
#
# This wrapper never performs downloads or inference.  A caller must explicitly
# request it and provide a pre-shortlisted, public-safe cross-domain candidate
# TSV.  Logical failures are recorded privately and always return success so
# the completed core ClusterWeave workflow remains successful.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
DATA_ROOT="${DATA_ROOT:-${PROJECT_DIR}/data}"
RESULTS_BASE="${RESULTS_BASE:-${DATA_ROOT}/results}"
RESULTS_ROOT="${RESULTS_ROOT:-${RESULTS_BASE}/${PROJECT_NAME}}"
WORK_ROOT="${WORK_ROOT:-${RESULTS_ROOT}/tmp}"

fallback_value() {
  local canonical_name="$1"
  local legacy_name="$2"
  local default_value="$3"
  if [[ -n "${!canonical_name-}" ]]; then
    printf '%s\n' "${!canonical_name}"
  elif [[ -n "${!legacy_name-}" ]]; then
    printf '%s\n' "${!legacy_name}"
  else
    printf '%s\n' "${default_value}"
  fi
}

RUN_CROSS_KINGDOM_EVIDENCE="$(fallback_value RUN_CROSS_KINGDOM_EVIDENCE RUN_HGT_EVIDENCE 0)"
CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES="$(fallback_value CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES HGT_EVIDENCE_MAX_CANDIDATES 25)"
candidate_source="default"
if [[ -n "${CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV+x}" ]]; then
  CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV="${CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV}"
  candidate_source="canonical"
elif [[ -n "${CROSS_KINGDOM_EVIDENCE_CANDIDATES+x}" ]]; then
  CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV="${CROSS_KINGDOM_EVIDENCE_CANDIDATES}"
  candidate_source="canonical"
elif [[ -n "${HGT_EVIDENCE_CANDIDATES_TSV+x}" ]]; then
  CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV="${HGT_EVIDENCE_CANDIDATES_TSV}"
  candidate_source="legacy"
elif [[ -n "${HGT_EVIDENCE_CANDIDATES+x}" ]]; then
  CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV="${HGT_EVIDENCE_CANDIDATES}"
  candidate_source="legacy"
else
  CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV="${RESULTS_ROOT}/summary/cross_kingdom_candidates.tsv"
fi
auto_select_explicit=0
if [[ -n "${CROSS_KINGDOM_EVIDENCE_AUTO_SELECT+x}" || -n "${HGT_EVIDENCE_AUTO_SELECT+x}" ]]; then
  auto_select_explicit=1
fi
CROSS_KINGDOM_EVIDENCE_AUTO_SELECT="$(fallback_value CROSS_KINGDOM_EVIDENCE_AUTO_SELECT HGT_EVIDENCE_AUTO_SELECT "$([[ "${candidate_source}" == "default" ]] && printf 1 || printf 0)")"
legacy_default_candidates="${RESULTS_ROOT}/summary/putative_transfer_candidates.tsv"
if [[ "${candidate_source}" == "default" \
  && ! -s "${CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV}" \
  && -s "${legacy_default_candidates}" \
  && "${auto_select_explicit}" == "0" ]]; then
  CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV="${legacy_default_candidates}"
  CROSS_KINGDOM_EVIDENCE_AUTO_SELECT=0
fi
CROSS_KINGDOM_EVIDENCE_CROSSWALK_TSV="$(fallback_value CROSS_KINGDOM_EVIDENCE_CROSSWALK_TSV HGT_EVIDENCE_CROSSWALK_TSV "${RESULTS_ROOT}/summary/candidate_bgc_gcf_crosswalk.tsv")"
CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR="$(fallback_value CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR HGT_EVIDENCE_OUTPUT_DIR "${RESULTS_ROOT}/integrated_evidence")"
CROSS_KINGDOM_EVIDENCE_WORK_ROOT="$(fallback_value CROSS_KINGDOM_EVIDENCE_WORK_ROOT HGT_EVIDENCE_WORK_ROOT "${WORK_ROOT}/integrated_evidence")"
CROSS_KINGDOM_EVIDENCE_STAGING_DIR="$(fallback_value CROSS_KINGDOM_EVIDENCE_STAGING_DIR HGT_EVIDENCE_STAGING_DIR "${CROSS_KINGDOM_EVIDENCE_WORK_ROOT}/staged")"
CROSS_KINGDOM_EVIDENCE_PREVIOUS_DIR="$(fallback_value CROSS_KINGDOM_EVIDENCE_PREVIOUS_DIR HGT_EVIDENCE_PREVIOUS_DIR "${CROSS_KINGDOM_EVIDENCE_WORK_ROOT}/previous_public")"
CROSS_KINGDOM_EVIDENCE_LOG_ROOT="$(fallback_value CROSS_KINGDOM_EVIDENCE_LOG_ROOT HGT_EVIDENCE_LOG_ROOT "${RESULTS_ROOT}/logs")"
CROSS_KINGDOM_EVIDENCE_LOGFILE="$(fallback_value CROSS_KINGDOM_EVIDENCE_LOGFILE HGT_EVIDENCE_LOGFILE "${CROSS_KINGDOM_EVIDENCE_LOG_ROOT}/run_cross_kingdom_evidence.log")"
CROSS_KINGDOM_EVIDENCE_STATUS_MANIFEST="$(fallback_value CROSS_KINGDOM_EVIDENCE_STATUS_MANIFEST HGT_EVIDENCE_STATUS_MANIFEST "${CROSS_KINGDOM_EVIDENCE_LOG_ROOT}/cross_kingdom_evidence_run_manifest.json")"
CROSS_KINGDOM_EVIDENCE_BUILDER="$(fallback_value CROSS_KINGDOM_EVIDENCE_BUILDER HGT_EVIDENCE_BUILDER "${PROJECT_DIR}/bin/build_cross_kingdom_evidence.py")"
CROSS_KINGDOM_EVIDENCE_SELECTOR="$(fallback_value CROSS_KINGDOM_EVIDENCE_SELECTOR HGT_EVIDENCE_SELECTOR "${PROJECT_DIR}/bin/select_cross_kingdom_candidates.py")"
CROSS_KINGDOM_EVIDENCE_TOPOLOGY_TSV="$(fallback_value CROSS_KINGDOM_EVIDENCE_TOPOLOGY_TSV HGT_EVIDENCE_TOPOLOGY_TSV "${RESULTS_ROOT}/phylogeny/topology_comparison.tsv")"
CROSS_KINGDOM_EVIDENCE_TOPOLOGY_MERGER="$(fallback_value CROSS_KINGDOM_EVIDENCE_TOPOLOGY_MERGER HGT_EVIDENCE_TOPOLOGY_MERGER "${PROJECT_DIR}/bin/merge_topology_evidence.py")"
CROSS_KINGDOM_EVIDENCE_ENRICHED_CANDIDATES_TSV="$(fallback_value CROSS_KINGDOM_EVIDENCE_ENRICHED_CANDIDATES_TSV HGT_EVIDENCE_ENRICHED_CANDIDATES_TSV "${CROSS_KINGDOM_EVIDENCE_STAGING_DIR}/candidates_with_topology.tsv")"
CROSS_KINGDOM_EVIDENCE_CONTEXT_ENRICHER="$(fallback_value CROSS_KINGDOM_EVIDENCE_CONTEXT_ENRICHER HGT_EVIDENCE_CONTEXT_ENRICHER "${PROJECT_DIR}/bin/enrich_cross_kingdom_context.py")"
CROSS_KINGDOM_EVIDENCE_CONTEXT_CANDIDATES_TSV="$(fallback_value CROSS_KINGDOM_EVIDENCE_CONTEXT_CANDIDATES_TSV HGT_EVIDENCE_CONTEXT_CANDIDATES_TSV "${CROSS_KINGDOM_EVIDENCE_STAGING_DIR}/candidates_with_context.tsv")"
CROSS_KINGDOM_EVIDENCE_RANKING_TSV="$(fallback_value CROSS_KINGDOM_EVIDENCE_RANKING_TSV HGT_EVIDENCE_RANKING_TSV "${RESULTS_ROOT}/summary/targeted_candidate_ranking.tsv")"
CROSS_KINGDOM_EVIDENCE_TAXON_MANIFEST="$(fallback_value CROSS_KINGDOM_EVIDENCE_TAXON_MANIFEST HGT_EVIDENCE_TAXON_MANIFEST "${RESULTS_ROOT}/summary_tables/genome_taxon_manifest.tsv")"
CROSS_KINGDOM_EVIDENCE_ANTISMASH_ROOT="$(fallback_value CROSS_KINGDOM_EVIDENCE_ANTISMASH_ROOT HGT_EVIDENCE_ANTISMASH_ROOT "${RESULTS_ROOT}/antismash")"
CROSS_KINGDOM_EVIDENCE_CLINKER_ROOT="$(fallback_value CROSS_KINGDOM_EVIDENCE_CLINKER_ROOT HGT_EVIDENCE_CLINKER_ROOT "${RESULTS_ROOT}/clinker")"
CROSS_KINGDOM_EVIDENCE_GENOMES_ROOT="$(fallback_value CROSS_KINGDOM_EVIDENCE_GENOMES_ROOT HGT_EVIDENCE_GENOMES_ROOT "${DATA_ROOT}/genomes")"
PYTHON_BIN="${PYTHON_BIN:-python3}"

CROSS_KINGDOM_EVIDENCE_HARD_MAX_CANDIDATES=100
PUBLIC_OUTPUT_NAMES=(
  "cross_kingdom_evidence.tsv"
  "cross_kingdom_evidence.json"
  "cross_kingdom_evidence_cards.txt"
)
LEGACY_PUBLIC_OUTPUT_NAMES=(
  "putative_transfer_evidence.tsv"
  "putative_transfer_evidence.json"
  "putative_transfer_evidence_cards.txt"
)

progress() {
  local phase="$1"
  local message="$2"
  printf 'CROSS_KINGDOM_EVIDENCE_PROGRESS phase=%s percent=100 message="%s"\n' "${phase}" "${message}"
}

write_status_manifest() {
  local status="$1"
  local message="$2"
  local candidate_count="${3:-0}"
  local output_count="${4:-0}"
  mkdir -p "$(dirname "${CROSS_KINGDOM_EVIDENCE_STATUS_MANIFEST}")"
  EVIDENCE_STATUS="${status}" \
  EVIDENCE_MESSAGE="${message}" \
  EVIDENCE_CANDIDATE_COUNT="${candidate_count}" \
  EVIDENCE_OUTPUT_COUNT="${output_count}" \
  EVIDENCE_CANDIDATE_LIMIT="${CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES}" \
    "${PYTHON_BIN}" - "${CROSS_KINGDOM_EVIDENCE_STATUS_MANIFEST}" <<'PY'
import json
import os
from pathlib import Path
import tempfile
import sys

path = Path(sys.argv[1])
output_names = [
    "cross_kingdom_evidence.tsv",
    "cross_kingdom_evidence.json",
    "cross_kingdom_evidence_cards.txt",
]
output_count = int(os.environ.get("EVIDENCE_OUTPUT_COUNT", "0"))
payload = {
    "candidate_count": int(os.environ.get("EVIDENCE_CANDIDATE_COUNT", "0")),
    "candidate_limit": int(os.environ["EVIDENCE_CANDIDATE_LIMIT"]),
    "message": os.environ["EVIDENCE_MESSAGE"],
    "outputs": output_names if output_count == len(output_names) else [],
    "requested": True,
    "schema_version": "clusterweave-cross-kingdom-evidence-run-v1",
    "status": os.environ["EVIDENCE_STATUS"],
}
descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
try:
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_name, path)
finally:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
PY
}

record_nonfatal() {
  local status="$1"
  local message="$2"
  local phase="$3"
  if command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    write_status_manifest "${status}" "${message}" 0 0 || true
  fi
  progress "${phase}" "${message}"
  printf '[WARN] %s\n' "${message}" >&2
  exit 0
}

quarantine_previous_public_outputs() {
  mkdir -p "${CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR}" "${CROSS_KINGDOM_EVIDENCE_PREVIOUS_DIR}"
  local name
  for name in "${PUBLIC_OUTPUT_NAMES[@]}" "${LEGACY_PUBLIC_OUTPUT_NAMES[@]}"; do
    if [[ -f "${CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR}/${name}" ]]; then
      mv -f "${CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR}/${name}" "${CROSS_KINGDOM_EVIDENCE_PREVIOUS_DIR}/${name}"
    fi
  done
}

if [[ "${RUN_CROSS_KINGDOM_EVIDENCE}" != "1" ]]; then
  progress "not_requested" "Optional cross-kingdom evidence not requested"
  exit 0
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  progress "tool_unavailable" "Python runtime unavailable; optional evidence skipped"
  printf '[WARN] Python runtime unavailable; optional evidence skipped.\n' >&2
  exit 0
fi

if ! mkdir -p "${CROSS_KINGDOM_EVIDENCE_LOG_ROOT}" "${CROSS_KINGDOM_EVIDENCE_WORK_ROOT}" "${CROSS_KINGDOM_EVIDENCE_STAGING_DIR}"; then
  record_nonfatal "failed" "Optional evidence directories could not be initialized; core outputs remain valid" "failed"
fi
if ! : > "${CROSS_KINGDOM_EVIDENCE_LOGFILE}"; then
  record_nonfatal "failed" "Optional evidence private log could not be initialized; core outputs remain valid" "failed"
fi

if ! quarantine_previous_public_outputs; then
  record_nonfatal "failed" "Previous optional evidence could not be quarantined; core outputs remain valid" "failed"
fi

if ! staging_dir_physical="$(cd "${CROSS_KINGDOM_EVIDENCE_STAGING_DIR}" && pwd -P)" \
  || ! output_dir_physical="$(cd "${CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR}" && pwd -P)"; then
  record_nonfatal "failed" "Optional evidence directories could not be resolved; core outputs remain valid" "failed"
fi
if [[ "${staging_dir_physical}" == "${output_dir_physical}" ]]; then
  record_nonfatal \
    "failed" \
    "Optional evidence staging and publication directories must be distinct; core outputs remain valid" \
    "failed"
fi

if [[ ! "${CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES}" =~ ^[0-9]+$ ]] \
  || (( CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES < 1 )) \
  || (( CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES > CROSS_KINGDOM_EVIDENCE_HARD_MAX_CANDIDATES )); then
  record_nonfatal "failed" "Candidate limit must be between 1 and 100; core outputs remain valid" "failed"
fi

if [[ ! -f "${CROSS_KINGDOM_EVIDENCE_BUILDER}" ]]; then
  record_nonfatal "tool_unavailable" "Optional evidence builder is unavailable; core outputs remain valid" "tool_unavailable"
fi

if [[ "${CROSS_KINGDOM_EVIDENCE_AUTO_SELECT}" != "0" && "${CROSS_KINGDOM_EVIDENCE_AUTO_SELECT}" != "1" ]]; then
  record_nonfatal "failed" "Automatic candidate selection must be 0 or 1; core outputs remain valid" "failed"
fi

if [[ "${CROSS_KINGDOM_EVIDENCE_AUTO_SELECT}" == "1" ]]; then
  if [[ ! -f "${CROSS_KINGDOM_EVIDENCE_SELECTOR}" ]]; then
    record_nonfatal "tool_unavailable" "Optional evidence selector is unavailable; core outputs remain valid" "tool_unavailable"
  fi
  if [[ ! -s "${CROSS_KINGDOM_EVIDENCE_CROSSWALK_TSV}" ]]; then
    record_nonfatal "insufficient_data" "Canonical BGC/GCF crosswalk is unavailable; core outputs remain valid" "insufficient_data"
  fi
  progress "select" "Selecting bounded cross-domain GCF candidates"
  if ! "${PYTHON_BIN}" "${CROSS_KINGDOM_EVIDENCE_SELECTOR}" \
    --explicit-request \
    --crosswalk "${CROSS_KINGDOM_EVIDENCE_CROSSWALK_TSV}" \
    --output "${CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV}" \
    --max-candidates "${CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES}" \
    >> "${CROSS_KINGDOM_EVIDENCE_LOGFILE}" 2>&1; then
    record_nonfatal "failed" "Cross-domain candidate selection failed; core outputs remain valid" "failed"
  fi
fi

if [[ ! -s "${CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV}" ]]; then
  record_nonfatal "insufficient_data" "No eligible shortlisted cross-domain candidate TSV was supplied; core outputs remain valid" "insufficient_data"
fi

candidate_input_count="$(${PYTHON_BIN} - "${CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV}" "${CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES}" <<'PY'
import csv
from pathlib import Path
import stat
import sys

path = Path(sys.argv[1])
try:
    info = path.lstat()
except OSError:
    raise SystemExit(2)
if (
    stat.S_ISLNK(info.st_mode)
    or not stat.S_ISREG(info.st_mode)
    or info.st_size > 2 * 1024 * 1024
):
    raise SystemExit(2)
limit = int(sys.argv[2])
count = 0
with path.open("r", newline="", encoding="utf-8-sig") as handle:
    reader = csv.DictReader(handle, delimiter="\t")
    for _ in reader:
        count += 1
        if count > limit:
            raise SystemExit(2)
print(count)
PY
)" || record_nonfatal "failed" "Safe candidate TSV could not be counted; core outputs remain valid" "failed"
if (( candidate_input_count < 1 )); then
  record_nonfatal "insufficient_data" "No cross-domain GCF family was eligible; core outputs remain valid" "insufficient_data"
fi

builder_candidates_tsv="${CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV}"
rm -f -- "${CROSS_KINGDOM_EVIDENCE_CONTEXT_CANDIDATES_TSV}"
if [[ -f "${CROSS_KINGDOM_EVIDENCE_CONTEXT_ENRICHER}" ]]; then
  progress "context" "Deriving bounded synteny, reference, composition, mobile-element, and assembly context"
  if "${PYTHON_BIN}" "${CROSS_KINGDOM_EVIDENCE_CONTEXT_ENRICHER}" \
    --explicit-request \
    --candidates "${builder_candidates_tsv}" \
    --crosswalk "${CROSS_KINGDOM_EVIDENCE_CROSSWALK_TSV}" \
    --ranking "${CROSS_KINGDOM_EVIDENCE_RANKING_TSV}" \
    --taxon-manifest "${CROSS_KINGDOM_EVIDENCE_TAXON_MANIFEST}" \
    --antismash-root "${CROSS_KINGDOM_EVIDENCE_ANTISMASH_ROOT}" \
    --clinker-root "${CROSS_KINGDOM_EVIDENCE_CLINKER_ROOT}" \
    --genomes-root "${CROSS_KINGDOM_EVIDENCE_GENOMES_ROOT}" \
    --project-name "${PROJECT_NAME}" \
    --output "${CROSS_KINGDOM_EVIDENCE_CONTEXT_CANDIDATES_TSV}" \
    --max-candidates "${CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES}" \
    >> "${CROSS_KINGDOM_EVIDENCE_LOGFILE}" 2>&1; then
    builder_candidates_tsv="${CROSS_KINGDOM_EVIDENCE_CONTEXT_CANDIDATES_TSV}"
  else
    progress "context_unavailable" "Context artifacts were incomplete or invalid; continuing without automatic context"
    printf '[WARN] Optional context enrichment was rejected; continuing with the safe shortlisted candidates.\n' >> "${CROSS_KINGDOM_EVIDENCE_LOGFILE}"
  fi
else
  progress "context_unavailable" "Context enrichment helper unavailable; continuing without automatic context"
  printf '[WARN] Optional context enrichment helper is unavailable; continuing with the safe shortlisted candidates.\n' >> "${CROSS_KINGDOM_EVIDENCE_LOGFILE}"
fi
rm -f -- "${CROSS_KINGDOM_EVIDENCE_ENRICHED_CANDIDATES_TSV}"
if [[ -s "${CROSS_KINGDOM_EVIDENCE_TOPOLOGY_TSV}" ]]; then
  if [[ -f "${CROSS_KINGDOM_EVIDENCE_TOPOLOGY_MERGER}" ]]; then
    progress "topology" "Integrating bounded ETE4 topology summaries"
    if "${PYTHON_BIN}" "${CROSS_KINGDOM_EVIDENCE_TOPOLOGY_MERGER}" \
      --explicit-request \
      --candidates "${builder_candidates_tsv}" \
      --topology "${CROSS_KINGDOM_EVIDENCE_TOPOLOGY_TSV}" \
      --output "${CROSS_KINGDOM_EVIDENCE_ENRICHED_CANDIDATES_TSV}" \
      --max-candidates "${CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES}" \
      >> "${CROSS_KINGDOM_EVIDENCE_LOGFILE}" 2>&1; then
      builder_candidates_tsv="${CROSS_KINGDOM_EVIDENCE_ENRICHED_CANDIDATES_TSV}"
    else
      progress "topology_unavailable" "Topology summaries were invalid; continuing without them"
      printf '[WARN] Optional topology summaries were rejected; continuing with the safe shortlisted candidates.\n' >> "${CROSS_KINGDOM_EVIDENCE_LOGFILE}"
    fi
  else
    progress "topology_unavailable" "Topology merge helper unavailable; continuing without it"
    printf '[WARN] Optional topology merge helper is unavailable; continuing with the safe shortlisted candidates.\n' >> "${CROSS_KINGDOM_EVIDENCE_LOGFILE}"
  fi
fi

progress "build" "Building bounded cross-kingdom evidence"
if ! "${PYTHON_BIN}" "${CROSS_KINGDOM_EVIDENCE_BUILDER}" \
  --explicit-request \
  --candidates "${builder_candidates_tsv}" \
  --output-dir "${CROSS_KINGDOM_EVIDENCE_STAGING_DIR}" \
  --max-candidates "${CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES}" \
  >> "${CROSS_KINGDOM_EVIDENCE_LOGFILE}" 2>&1; then
  record_nonfatal "failed" "Candidate evidence validation or rendering failed; core outputs remain valid" "failed"
fi

for name in "${PUBLIC_OUTPUT_NAMES[@]}"; do
  if [[ ! -s "${CROSS_KINGDOM_EVIDENCE_STAGING_DIR}/${name}" ]]; then
    record_nonfatal "failed" "Optional evidence builder did not produce the complete bounded artifact set; core outputs remain valid" "failed"
  fi
done

candidate_count="$(${PYTHON_BIN} - "${CROSS_KINGDOM_EVIDENCE_STAGING_DIR}/cross_kingdom_evidence.json" <<'PY'
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
count = int(payload.get("candidate_count", 0))
if count < 1 or count > 100:
    raise SystemExit(2)
print(count)
PY
)" || record_nonfatal "failed" "Optional evidence JSON failed its bounded-count check; core outputs remain valid" "failed"

candidate_events="$(${PYTHON_BIN} - "${CROSS_KINGDOM_EVIDENCE_STAGING_DIR}/cross_kingdom_evidence.json" <<'PY'
import json
import re
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for record in payload.get("records", [])[:100]:
    source = record.get("input", {}) if isinstance(record, dict) else {}
    raw_id = source.get("candidate_id") or source.get("gcf_id") or record.get("evidence_id") or "candidate"
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", str(raw_id)).strip("._-")[:100] or "candidate"
    tier = str(record.get("confidence", "exploratory"))
    if tier not in {"exploratory", "supportive", "strong"}:
        tier = "exploratory"
    print(
        f'CROSS_KINGDOM_EVIDENCE candidate={candidate} status=success evidence_tier={tier} '
        'message="Computational context does not establish an evolutionary event, mechanism, or direction."'
    )
PY
)" || record_nonfatal "failed" "Optional evidence events failed validation; core outputs remain valid" "failed"
[[ -n "${candidate_events}" ]] && printf '%s\n' "${candidate_events}"

publication_failed=0
for name in "${PUBLIC_OUTPUT_NAMES[@]}"; do
  if ! mv -f "${CROSS_KINGDOM_EVIDENCE_STAGING_DIR}/${name}" "${CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR}/${name}"; then
    publication_failed=1
    break
  fi
done

if (( publication_failed != 0 )); then
  for name in "${PUBLIC_OUTPUT_NAMES[@]}"; do
    if [[ -f "${CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR}/${name}" ]]; then
      mv -f "${CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR}/${name}" "${CROSS_KINGDOM_EVIDENCE_STAGING_DIR}/${name}" 2>/dev/null || true
    fi
  done
  record_nonfatal "failed" "Optional evidence publication failed; core outputs remain valid" "failed"
fi

if ! write_status_manifest "success" "Bounded cross-kingdom evidence completed" "${candidate_count}" "${#PUBLIC_OUTPUT_NAMES[@]}"; then
  progress "failed" "Optional evidence status could not be recorded; core outputs remain valid"
  printf '[WARN] Optional evidence status could not be recorded; core outputs remain valid.\n' >&2
  exit 0
fi
progress "success" "Bounded cross-kingdom evidence completed"
exit 0
