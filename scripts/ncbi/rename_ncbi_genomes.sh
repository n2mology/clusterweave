#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd -P)}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_ROOT}")}"
GENOME_ROOT="${GENOME_ROOT:-${PROJECT_ROOT}/data/genomes/fungi/${PROJECT_NAME}}"
MAPPING_FILE="${MAPPING_FILE:-${GENOME_ROOT}/accessions_fungusID_taxonomyID.txt}"
NCBI_CLI_ROOT="${NCBI_CLI_ROOT:-${PROJECT_ROOT}/software/ncbi_cli}"

die(){ echo "ERROR: $*" >&2; exit 1; }

is_windowsapps_alias() {
  local candidate_path="${1:-}"
  [[ -n "${candidate_path}" ]] || return 1
  case "${candidate_path}" in
    *"/Appdata/Local/Microsoft/WindowsApps/"*|*"\\AppData\\Local\\Microsoft\\WindowsApps\\"*)
      return 0
      ;;
  esac
  return 1
}

usable_python() {
  local candidate="${1:-}"
  [[ -n "${candidate}" ]] || return 1
  command -v "${candidate}" >/dev/null 2>&1 || return 1
  local resolved
  resolved="$(command -v "${candidate}" 2>/dev/null || true)"
  is_windowsapps_alias "${resolved}" && return 1
  "${candidate}" -c "import sys; print(sys.executable)" >/dev/null 2>&1 || return 1
  return 0
}

resolve_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    usable_python "${PYTHON_BIN}" || die "PYTHON_BIN is not a usable Python interpreter: ${PYTHON_BIN}"
    printf '%s\n' "${PYTHON_BIN}"
    return 0
  fi
  if usable_python python3; then
    printf '%s\n' "python3"
    return 0
  fi
  if usable_python python; then
    printf '%s\n' "python"
    return 0
  fi
  die "No usable Python interpreter found. Install python3 or set PYTHON_BIN to a real interpreter."
}

detect_datasets() {
  if [[ -n "${DATASETS_CMD:-}" ]]; then
    command -v "${DATASETS_CMD}" >/dev/null 2>&1 && printf '%s\n' "${DATASETS_CMD}" && return 0
    [[ -x "${DATASETS_CMD}" ]] && printf '%s\n' "${DATASETS_CMD}" && return 0
    return 1
  fi
  if command -v datasets >/dev/null 2>&1; then
    printf '%s\n' "datasets"
    return 0
  fi
  if [[ -x "${NCBI_CLI_ROOT}/datasets" ]]; then
    printf '%s\n' "${NCBI_CLI_ROOT}/datasets"
    return 0
  fi
  if [[ -f "${NCBI_CLI_ROOT}/datasets.exe" ]]; then
    printf '%s\n' "${NCBI_CLI_ROOT}/datasets.exe"
    return 0
  fi
  return 1
}

[[ -d "${GENOME_ROOT}" ]] || die "GENOME_ROOT not found: ${GENOME_ROOT}"
mkdir -p "$(dirname "${MAPPING_FILE}")"
PYTHON_CMD="$(resolve_python)"
DATASETS_CMD_RESOLVED="$(detect_datasets || true)"

"${PYTHON_CMD}" - "${GENOME_ROOT}" "${MAPPING_FILE}" "${DATASETS_CMD_RESOLVED}" <<'PY'
import glob
import json
import os
import re
import subprocess
import sys

root = sys.argv[1]
outp = sys.argv[2]
datasets_cmd = sys.argv[3] if len(sys.argv) >= 4 else ""
taxonomy_cache = {}

def deep_find_first(obj, key_substr):
    target = key_substr.lower()
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if target in str(k).lower():
                    if isinstance(v, str) and v.strip():
                        return v.strip()
                    if isinstance(v, (int, float)):
                        return str(v)
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            for v in cur:
                if isinstance(v, (dict, list)):
                    stack.append(v)
    return ""

def parse_bp(value):
    if value in ("", None):
        return 0
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return 0

def fasta_size_mb(acc_dir):
    candidates = glob.glob(os.path.join(acc_dir, "ncbi_dataset", "data", "**", "*.fna"), recursive=True)
    if not candidates:
        return ""
    total_bp = 0
    try:
        with open(candidates[0], "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if not line or line.startswith(">"):
                    continue
                total_bp += len(line.strip())
    except OSError:
        return ""
    if total_bp <= 0:
        return ""
    return f"{total_bp / 1_000_000:.2f}"

def derive_genome_size_mb(rec, acc_dir):
    stats = rec.get("assemblyStats", {}) or {}
    for key in ["totalSequenceLength", "totalUngappedLength", "atgcCount"]:
        total_bp = parse_bp(stats.get(key) or deep_find_first(rec, key))
        if total_bp > 0:
            return f"{total_bp / 1_000_000:.2f}"
    return fasta_size_mb(acc_dir)

def clean_tsv(value):
    return re.sub(r"[\t\r\n]+", " ", str(value or "")).strip()


def taxonomy_summary(taxid):
    taxid = str(taxid or "").strip()
    if not taxid or not datasets_cmd:
        return {}
    if taxid in taxonomy_cache:
        return taxonomy_cache[taxid]
    try:
        proc = subprocess.run(
            [datasets_cmd, "summary", "taxonomy", "taxon", taxid],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
        payload = json.loads(proc.stdout or "{}")
        reports = payload.get("reports") if isinstance(payload, dict) else None
        taxonomy = reports[0].get("taxonomy") if isinstance(reports, list) and reports and isinstance(reports[0], dict) else {}
        if not isinstance(taxonomy, dict):
            taxonomy = {}
    except Exception:
        taxonomy = {}
    taxonomy_cache[taxid] = taxonomy
    return taxonomy


def taxonomy_lineage_fields(taxid):
    taxonomy = taxonomy_summary(taxid)
    if not taxonomy:
        return "", ""
    ids = []
    for value in taxonomy.get("parents") or []:
        try:
            ids.append(str(int(value)))
        except (TypeError, ValueError):
            continue
    current = taxonomy.get("tax_id") or taxid
    try:
        current = str(int(current))
    except (TypeError, ValueError):
        current = str(current or "").strip()
    if current and current not in ids:
        ids.append(current)

    names = []
    classification = taxonomy.get("classification") or {}
    if isinstance(classification, dict):
        ordered = ["domain", "kingdom", "phylum", "class", "order", "family", "genus", "species"]
        for rank in ordered:
            item = classification.get(rank)
            if isinstance(item, dict):
                name = clean_tsv(item.get("name"))
                if name and name not in names:
                    names.append(name)
    current_name = taxonomy.get("current_scientific_name") or {}
    if isinstance(current_name, dict):
        name = clean_tsv(current_name.get("name"))
        if name and name not in names:
            names.append(name)
    return ",".join(ids), "|".join(names)


def try_infraspecific(rec):
    strain = ""
    isolate = ""
    orgobj = rec.get("organism", {}) or {}
    infra = orgobj.get("infraspecificNames") or rec.get("infraspecificNames") or []
    if isinstance(infra, dict):
        infra = [infra]
    for item in infra:
        if not isinstance(item, dict):
            continue
        cls = (item.get("class") or item.get("nameClass") or item.get("type") or "").lower()
        name = (item.get("name") or item.get("value") or item.get("text") or "").strip()
        if cls == "strain" and name and not strain:
            strain = name
        if cls == "isolate" and name and not isolate:
            isolate = name
    return strain, isolate

def regex_from_orgname(orgname):
    strain = ""
    isolate = ""
    if not orgname:
        return strain, isolate
    m = re.search(r'\bstrain\b[:\s]+([A-Za-z0-9._-]+)', orgname, flags=re.I)
    if m:
        strain = m.group(1)
    m = re.search(r'\bisolate\b[:\s]+([A-Za-z0-9._-]+)', orgname, flags=re.I)
    if m:
        isolate = m.group(1)
    return strain, isolate

def sanitize(value):
    value = value.strip().replace(" ", "_")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value

def fungus_id_from(org, strain, isolate):
    org = (org or "").strip()
    parts = org.split()
    genus = parts[0] if len(parts) >= 1 else "UnknownGenus"
    species = parts[1] if len(parts) >= 2 else "sp"
    tag = strain or isolate or ""
    base = f"{genus}_{species}"
    if tag:
        base = f"{base}_{tag}"
    return sanitize(base)

def find_report(acc_dir):
    candidates = [
        os.path.join(acc_dir, "ncbi_dataset", "data", "assembly_data_report.jsonl"),
    ]
    candidates += glob.glob(os.path.join(acc_dir, "ncbi_dataset", "data", "**", "assembly_data_report.jsonl"), recursive=True)
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""

rows = []
for name in sorted(os.listdir(root)):
    acc_dir = os.path.join(root, name)
    if not os.path.isdir(acc_dir):
        continue
    acc = os.path.basename(acc_dir)
    report = find_report(acc_dir)
    if not report:
        continue

    org = ""
    taxid = ""
    strain = ""
    isolate = ""
    genome_size_mb = ""
    lineage_ids = ""
    lineage_names = ""
    try:
        with open(report, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                orgobj = rec.get("organism", {}) or {}
                org = (orgobj.get("organismName") or rec.get("organismName") or "").strip()
                taxid_val = orgobj.get("taxId") or rec.get("taxId") or ""
                taxid = str(taxid_val) if taxid_val != "" else ""
                s1, i1 = try_infraspecific(rec)
                s2, i2 = regex_from_orgname(org)
                s3 = deep_find_first(rec, "strain")
                i3 = deep_find_first(rec, "isolate")
                strain = s1 or s2 or s3 or ""
                isolate = i1 or i2 or i3 or ""
                genome_size_mb = derive_genome_size_mb(rec, acc_dir)
                lineage_ids, lineage_names = taxonomy_lineage_fields(taxid)
                break
    except Exception:
        continue

    fid = fungus_id_from(org, strain, isolate)
    rows.append((acc, fid, taxid, genome_size_mb, clean_tsv(org), lineage_ids, lineage_names))

with open(outp, "w", encoding="utf-8") as out:
    for acc, fid, taxid, genome_size_mb, org, lineage_ids, lineage_names in rows:
        out.write(f"{acc}\t{fid}\t{taxid}\t{genome_size_mb}\t{org}\t{lineage_ids}\t{lineage_names}\n")
PY

[[ -f "${MAPPING_FILE}" ]] || die "Failed to create mapping file: ${MAPPING_FILE}"

while IFS=$'\t' read -r acc fungus_id taxid genome_size_mb _mapping_rest || [[ -n "${acc:-}" ]]; do
  [[ -z "${acc:-}" || -z "${fungus_id:-}" ]] && continue

  old_dir="${GENOME_ROOT}/${acc}"
  new_dir="${GENOME_ROOT}/${fungus_id}"
  [[ -d "${old_dir}" ]] || continue

  if [[ -e "${new_dir}" && "${old_dir}" != "${new_dir}" ]]; then
    echo "WARN: target exists, skipping outer rename: ${new_dir}" >&2
    continue
  fi

  data_dir="${old_dir}/ncbi_dataset/data"
  if [[ -d "${data_dir}" ]]; then
    sub_old=""
    if [[ -d "${data_dir}/${acc}" ]]; then
      sub_old="${data_dir}/${acc}"
    else
      sub_old="$(find "${data_dir}" -mindepth 1 -maxdepth 1 -type d -name "${acc}*" 2>/dev/null | head -n 1 || true)"
    fi

    if [[ -n "${sub_old}" && -d "${sub_old}" ]]; then
      sub_new="${data_dir}/${fungus_id}"
      if [[ "${sub_old}" == "${sub_new}" ]]; then
        :
      elif [[ -e "${sub_new}" ]]; then
        echo "WARN: target exists, skipping subfolder rename: ${sub_new}" >&2
      else
        mv -f "${sub_old}" "${sub_new}"
      fi

      work_sub="${sub_new}"
      if [[ ! -d "${work_sub}" ]]; then
        work_sub="${sub_old}"
      fi
      work_sub="$(cd "${work_sub}" && pwd -P)"

      while IFS= read -r -d '' f; do
        b="$(basename "$f")"
        d="$(dirname "$f")"
        nb="${b//$acc/$fungus_id}"
        [[ "${nb}" == "${b}" ]] && continue
        [[ -e "${d}/${nb}" ]] && continue
        mv -f "$f" "${d}/${nb}"
      done < <(find "${work_sub}" -maxdepth 1 -type f -name "*${acc}*" -print0 2>/dev/null)

      fna="$(find "${work_sub}" -maxdepth 1 -type f -iname "*.fna" 2>/dev/null | head -n 1 || true)"
      if [[ -n "${fna}" ]]; then
        d="$(dirname "${fna}")"
        target="${d}/${fungus_id}.fna"
        [[ "${fna}" != "${target}" && ! -e "${target}" ]] && mv -f "${fna}" "${target}"
      fi

      gff="$(find "${work_sub}" -maxdepth 1 -type f \( -iname "genomic.gff" -o -iname "genomic.gff3" \) 2>/dev/null | head -n 1 || true)"
      if [[ -n "${gff}" ]]; then
        d="$(dirname "${gff}")"
        ext="${gff##*.}"
        target="${d}/${fungus_id}.${ext}"
        [[ "${gff}" != "${target}" && ! -e "${target}" ]] && mv -f "${gff}" "${target}"
      fi

      gbff="$(find "${work_sub}" -maxdepth 1 -type f -iname "genomic.gbff" 2>/dev/null | head -n 1 || true)"
      if [[ -n "${gbff}" ]]; then
        d="$(dirname "${gbff}")"
        target="${d}/${fungus_id}.gbff"
        [[ "${gbff}" != "${target}" && ! -e "${target}" ]] && mv -f "${gbff}" "${target}"
      fi
    fi
  fi

  if [[ "${old_dir}" != "${new_dir}" ]]; then
    mv -f "${old_dir}" "${new_dir}"
  fi
done < "${MAPPING_FILE}"
