#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd -P)}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_ROOT}")}"
GENOME_ROOT="${GENOME_ROOT:-${PROJECT_ROOT}/Data/Genomes/Fungi/${PROJECT_NAME}}"
MAPPING_FILE="${MAPPING_FILE:-${GENOME_ROOT}/accessions_fungusID_taxonomyID.txt}"

die(){ echo "ERROR: $*" >&2; exit 1; }

resolve_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    command -v "${PYTHON_BIN}" >/dev/null 2>&1 || die "PYTHON_BIN not found in PATH: ${PYTHON_BIN}"
    printf '%s\n' "${PYTHON_BIN}"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
    return 0
  fi
  die "No Python interpreter found. Install python3 or set PYTHON_BIN."
}

[[ -d "${GENOME_ROOT}" ]] || die "GENOME_ROOT not found: ${GENOME_ROOT}"
mkdir -p "$(dirname "${MAPPING_FILE}")"
PYTHON_CMD="$(resolve_python)"

"${PYTHON_CMD}" - "${GENOME_ROOT}" "${MAPPING_FILE}" <<'PY'
import glob
import json
import os
import re
import sys

root = sys.argv[1]
outp = sys.argv[2]

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
                break
    except Exception:
        continue

    fid = fungus_id_from(org, strain, isolate)
    rows.append((acc, fid, taxid, genome_size_mb))

with open(outp, "w", encoding="utf-8") as out:
    for acc, fid, taxid, genome_size_mb in rows:
        out.write(f"{acc}\t{fid}\t{taxid}\t{genome_size_mb}\n")
PY

[[ -f "${MAPPING_FILE}" ]] || die "Failed to create mapping file: ${MAPPING_FILE}"

while IFS=$'\t' read -r acc fungus_id taxid genome_size_mb || [[ -n "${acc:-}" ]]; do
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
      if [[ -e "${sub_new}" && "${sub_old}" != "${sub_new}" ]]; then
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
