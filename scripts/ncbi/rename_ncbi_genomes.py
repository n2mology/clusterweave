import csv
import glob
import json
import os
import re
import subprocess
import sys

root = sys.argv[1]
outp = sys.argv[2]
datasets_cmd = sys.argv[3] if len(sys.argv) >= 4 else ""
taxon_group = sys.argv[4].strip().lower() if len(sys.argv) >= 5 else "fungi"
route_manifest = sys.argv[5] if len(sys.argv) >= 6 else ""
taxonomy_cache = {}
route_by_accession = {}


def accession_keys(value):
    text = str(value or "").strip().upper()
    if not text:
        return []
    keys = [text]
    if text.startswith(("GCA_", "GCF_")):
        keys.append(text.split(".", 1)[0])
    return keys


if route_manifest and os.path.isfile(route_manifest):
    with open(route_manifest, newline="", encoding="utf-8-sig") as handle:
        for route in csv.DictReader(handle, delimiter="\t"):
            if str(route.get("taxon_group") or "").strip().lower() != taxon_group:
                continue
            accession = route.get("source_accession") or route.get("input_key") or ""
            for key in accession_keys(accession):
                existing = route_by_accession.get(key)
                if existing and existing.get("genome_id") != route.get("genome_id"):
                    raise RuntimeError(f"Contradictory immutable routes for accession {accession}")
                route_by_accession[key] = route

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

def genome_id_from(org, strain, isolate):
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
    route = next((route_by_accession[key] for key in accession_keys(acc) if key in route_by_accession), None)
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

    if route:
        fid = sanitize(str(route.get("genome_id") or ""))
        if not fid:
            raise RuntimeError(f"Immutable route for {acc} has no safe genome_id")
        taxid = clean_tsv(route.get("taxid")) or taxid
        org = clean_tsv(route.get("organism_name")) or org
    else:
        fid = genome_id_from(org, strain, isolate)
    rows.append((acc, fid, taxid, genome_size_mb, clean_tsv(org), lineage_ids, lineage_names))

seen_ids = {}
for acc, fid, *_ in rows:
    previous = seen_ids.get(fid.casefold())
    if previous and previous != acc:
        raise RuntimeError(
            f"Genome ID collision after taxonomy rename: {previous} and {acc} both map to {fid}"
        )
    seen_ids[fid.casefold()] = acc

with open(outp, "w", encoding="utf-8") as out:
    for acc, fid, taxid, genome_size_mb, org, lineage_ids, lineage_names in rows:
        out.write(f"{acc}\t{fid}\t{taxid}\t{genome_size_mb}\t{org}\t{lineage_ids}\t{lineage_names}\n")
