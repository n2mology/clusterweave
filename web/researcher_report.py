"""Portable methodology records containing only declared research metadata."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat

from tool_runtime import observe, safe_observation, TAG

REPORT_FILES = {"METHODS.md", "run_metadata.json", "resources.tsv", "CITATIONS.bib", "CITATION.cff"}
DIGEST = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
ACCESSION = re.compile(r"GC[AF]_[0-9]+\.[1-9][0-9]*\Z")
TOOLS = {
    "NCBI Datasets": ("datasets", "https://www.ncbi.nlm.nih.gov/datasets/", ""),
    "AUGUSTUS": ("augustus", "https://github.com/Gaius-Augustus/Augustus", ""),
    "BUSCO": ("busco", "https://gitlab.com/ezlab/busco", ""),
    "GeneMark": ("gmes_petap.pl", "https://github.com/gatech-genemark", ""),
    "SNAP": ("snap", "https://github.com/KorfLab/SNAP", ""),
    "DIAMOND": ("diamond", "https://github.com/bbuchfink/diamond", ""),
    "HMMER": ("hmmscan", "http://hmmer.org/", ""),
    "Exonerate": ("exonerate", "https://github.com/nathanweeks/exonerate", ""),
    "BLAST+": ("blastp", "https://blast.ncbi.nlm.nih.gov/", ""),
    "antiSMASH": ("antismash", "https://antismash.secondarymetabolites.org/", "10.1093/nar/gkaf334"),
    "BiG-SCAPE": ("bigscape", "https://github.com/medema-group/BiG-SCAPE", ""),
    "FunBGCeX": ("", "https://github.com/ydmatsd/funbgcex", ""),
    "funannotate": ("funannotate", "https://github.com/nextgenusfs/funannotate", ""),
    "BRAKER3": ("braker.pl", "https://github.com/Gaius-Augustus/BRAKER", ""),
    "Prodigal": ("prodigal", "https://github.com/hyattpd/Prodigal", ""),
    "clinker": ("clinker", "https://github.com/gamcil/clinker", ""),
    "MAFFT": ("mafft", "https://mafft.cbrc.jp/alignment/software/", ""),
    "FastTree": ("FastTree", "http://www.microbesonline.org/fasttree/", ""),
    "IQ-TREE": ("iqtree2", "https://iqtree.github.io/", ""),
    "R": ("Rscript", "https://www.r-project.org/", ""),
    "Python": ("python3", "https://www.python.org/", ""),
    "CairoSVG": ("", "https://cairosvg.org/", ""),
    "trimAl": ("trimal", "https://trimal.cgenomics.org/", ""),
    "ETE4": ("", "https://etetoolkit.org/", ""),
    "NPLinker": ("nplinker", "https://github.com/NPLinker/nplinker", ""),
}
CONFIGURATION = {"CPUS", "WORKERS", "ANNO_CPUS", "GENOME_PARALLELISM", "ENGINE", "ANTISMASH_TAXON",
    "ANTISMASH_RECORD_PARALLELISM", "ANTISMASH_RECORD_CPUS", "MIN_RECORD_BP", "MAX_RECORD_BP",
    "BRAKER3_ENABLED", "RUN_STAGE_ANNOTATION", "RUN_STAGE_BIGSCAPE", "RUN_STAGE_SUMMARY", "RUN_STAGE_CLINKER",
    "BIGSCAPE_CUTOFF", "BIGSCAPE_MODE", "BIGSCAPE_GCF_CUTOFF", "FUNBGCEX_MODE", "PHYLOGENY_METHOD"}
CONFIGURATION.update({"ANALYSIS_SCOPE", "ANNOTATION_FALLBACK_ORDER", "ANTISMASH_SHARD_CPUS", "ANTISMASH_LEGACY_CPUS",
    "RUN_CLINKER", "RUN_ECOLOGY_ANALYSIS", "RUN_PHYLOGENY", "RUN_CROSS_KINGDOM_EVIDENCE", "CLINKER_MODE",
    "ATLAS_MIN_RECORDS", "ATLAS_STAGE_LIMIT", "SHORTLIST_LIMIT", "SHARED_FAMILY_MIN_RECORDS", "SHARED_FAMILY_STAGE_LIMIT",
    "MAX_COMPARATORS", "MAX_OTHER_ECOLOGY", "MAX_SAME_ECOLOGY", "PHYLOGENY_CPUS", "PHYLOGENY_PARALLELISM",
    "PHYLOGENY_MAX_FAMILIES", "PHYLOGENY_MAX_SEQUENCES_PER_FAMILY", "PHYLOGENY_TIMEOUT_SECONDS", "GNPS_VERSION"})


def read_record(path, base, limit=65536):
    path.relative_to(base)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Report source cannot use links")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError("Report source exceeds its metadata envelope")
        raw = os.read(fd, limit + 1)
        after = os.fstat(fd)
        if len(raw) != info.st_size or (info.st_ino, info.st_mtime_ns, info.st_ctime_ns) != (after.st_ino, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Report source changed")
        return raw
    finally:
        os.close(fd)


def taxon_metadata(result):
    rows = {}
    conflicts = set()
    try:
        raw = read_record(result / "summary_tables/genome_taxon_manifest.tsv", result, 1024 * 1024).decode("utf-8-sig")
        for index, row in enumerate(csv.DictReader(io.StringIO(raw), delimiter="\t")):
            if index >= 4096:
                raise ValueError("Taxon metadata bound exceeded")
            label, group = row.get("genome_id", ""), row.get("taxon_group", "")
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,240}", label) and group in {"bacteria", "fungi"}:
                accession = row.get("source_accession", "")
                value = {"taxon_group": group, "accession": accession if ACCESSION.fullmatch(accession) else None}
                if label in conflicts or label in rows and rows[label] != value:
                    conflicts.add(label)
                    rows[label] = {"taxon_group": "unclassified", "accession": None}
                else:
                    rows[label] = value
    except (OSError, ValueError, UnicodeError, csv.Error):
        return {}
    return rows


def package_name(relative, taxa):
    parts = relative.split("/")
    if len(parts) >= 4 and parts[:2] == ["data", "results"]:
        parts = parts[3:]
    if len(parts) == 2 and parts[0] == "input_gbks":
        group = taxa.get(Path(parts[1]).stem, {}).get("taxon_group", "unclassified")
        return "/".join([parts[0], group, parts[1]])
    return "/".join(parts)


def probe_annotation_runtimes(env):
    """Observe selected annotation candidates; outcomes establish actual use later."""
    settings = dict(os.environ)
    settings.update(env)
    env = settings
    observations = []
    engine = env.get("ENGINE", "")
    if not engine:
        engine = "singularity" if shutil.which("singularity") else "apptainer"
    software = Path(env.get("SOFTWARE_ROOT", "software"))
    backend = "native" if engine == "docker" and shutil.which("antismash") else engine
    runtime = env.get("ANTISMASH_DOCKER_IMAGE", "antismash/standalone:8.0.4") if engine == "docker" else env.get("ANTISMASH_SIF", str(software / "antismash/antismash_standalone.sif"))
    for tool in ("antiSMASH", "Prodigal"):
        observations.append(observe(tool, backend, runtime))
    fungal = None
    if engine == "docker" or env.get("FUNBGCEX_USE_DOCKER_IMAGE") == "1":
        fungal = observe("FunBGCeX", "docker", env.get("FUNBGCEX_DOCKER_IMAGE", "clusterweave-funbgcex:latest"))
    if not fungal or not fungal.get("runtime_sha256"):
        sif = Path(env.get("FUNBGCEX_SIF", str(software / "funbgcex/funbgcex_bundle.sif")))
        venv = Path(env.get("FUNBGCEX_VENV_DIR", str(software / "funbgcex/venv")))
        if sif.is_file():
            fungal = observe("FunBGCeX", engine, str(sif))
        else:
            python = str(venv / "bin/python") if (venv / "bin/funbgcex").is_file() else env.get("PYTHON_BIN", "python3")
            fungal = observe("FunBGCeX", python=python)
    observations.append(fungal)
    for tool, image_key, image_default, sif_key, sif_default in (
            ("funannotate", "FUNANNOTATE_IMAGE_URI", "docker://clusterweave-funannotate:v1.8.17-busco", "FUNANNOTATE_SIF", "funannotate/funannotate_v1.8.17.sif"),
            ("BRAKER3", "BRAKER_IMAGE_URI", "docker://teambraker/braker3:latest", "BRAKER_SIF", "braker/braker3.sif")):
        if engine == "docker":
            observations.append(observe(tool, "docker", env.get(image_key, image_default).removeprefix("docker://")))
        else:
            sif = Path(env.get(sif_key, str(software / sif_default)))
            if sif.is_file():
                observations.append(observe(tool, engine, str(sif)))
            else:
                observations.append(observe(tool))
    return [record for record in observations if record]


def source_fingerprint(root):
    digest = hashlib.sha256()
    paths = set()
    for pattern in ("*.sh", "*.cff", "bin/*.py", "web/*.py", "scripts/**/*.py", "scripts/**/*.sh", "config/*.env"):
        paths.update(root.glob(pattern))
    # Worker orchestration lives separately from the scientific source tree.
    if root.as_posix() == "/clusterweave":
        paths.update(Path("/app").glob("*.py"))
    count = 0
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            continue
        if count >= 1024:
            return None
        name = ("orchestration/" + path.name) if path.parent == Path("/app") else path.relative_to(root).as_posix()
        digest.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
        count += 1
    return digest.hexdigest() if count else None


def input_fingerprints(roots):
    records = []
    for root in roots:
        if any(p.is_symlink() for p in (root, *root.parents)):
            continue
        for path in sorted(root.glob("*")):
            if path.suffix.lower() not in {".fna", ".fa", ".fasta", ".fsa", ".gb", ".gbk", ".gbff", ".gff", ".gff3"}:
                continue
            if path.is_symlink() or not path.is_file() or len(records) >= 4096:
                continue
            before = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
            after = path.stat()
            if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Input changed while recording research metadata")
            records.append({"genome_id": path.stem, "format": path.suffix.lower(), "bytes": after.st_size, "sha256": digest.hexdigest()})
    return records


def _safe_identity(value):
    if not isinstance(value, dict) or not ACCESSION.fullmatch(str(value.get("accession", ""))):
        return None
    result = {"accession": value["accession"]}
    contract = value.get("contract")
    if contract not in {"accession-detection-v2", "accession-detection-v3", "accession-snapshot-v2", "bacterial-genbank-v1", "fungal-existing-cds-v1"}:
        return None
    result["contract"] = contract
    route = value.get("route") or {}
    if route.get("taxon") in {"bacteria", "fungi"}:
        result["route"] = {"taxon": route["taxon"]}
    for key in ("genome_sha256", "source_sha256", "runtime_sha256"):
        if not DIGEST.fullmatch(str(value.get(key, ""))):
            return None
        result[key] = value[key]
    for key in ("tools", "containers", "databases", "models", "parameters"):
        section = value.get(key)
        if section == "not-used":
            result[key] = section
        elif isinstance(section, dict):
            result[key] = {k: v for k, v in section.items()
                           if re.fullmatch(r"[a-z0-9_]{1,64}", k) and (isinstance(v, str) and DIGEST.fullmatch(v)
                           or isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10**12)}
    return result


def _cache_records(result):
    records = []
    directory = result / "reproducibility/accession_cache"
    try:
        for index, path in enumerate(sorted(directory.glob("*.json"))):
            if index >= 256:
                break
            try:
                record = json.loads(read_record(path, result))
                identity = _safe_identity(record.get("identity"))
                if identity is None:
                    continue
                execution = record.get("producer_execution") or {}
                producer = {key: execution[key] for key in ("worker_image", "native_runtime_sha256", "producer_source_sha256")
                            if DIGEST.fullmatch(str(execution.get(key, "")))}
                if isinstance(execution.get("tool_versions"), list):
                    producer["tool_versions"] = [safe for raw in execution["tool_versions"][:16] if (safe := safe_observation(raw))]
                if isinstance(execution.get("scheduling"), dict):
                    producer["scheduling"] = _safe_scheduling(execution["scheduling"])
                records.append({"identity": identity, "outcome": "hit" if record.get("outcome") == "hit" else "miss",
                                "key": record.get("key") if DIGEST.fullmatch(str(record.get("key", ""))) else None,
                                "producer_execution": producer,
                                "materializer_scheduling": _safe_scheduling(record.get("materializer_scheduling")),
                                "population": record.get("population") if record.get("population") in {"published", "duplicate", "rejected", "not-attempted"} else "other"})
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    except OSError:
        pass
    return records


def _safe_scheduling(value):
    if not isinstance(value, dict):
        return {}
    fields = {"CPUS", "THREADS", "GENOME_PARALLELISM", "WORKERS", "ANNO_CPUS", "ANTISMASH_RECORD_PARALLELISM",
              "ANTISMASH_SHARD_CPUS", "ANTISMASH_LEGACY_CPUS", "CLUSTERWEAVE_TOOL_DOCKER_CPUS",
              "CLUSTERWEAVE_TOOL_DOCKER_MEMORY", "CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT"}
    return {k: v for k, v in value.items() if k in fields and isinstance(v, str)
            and len(v) <= 32 and (not v or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?[bkmgBKMG]?", v))}


def _citation(root):
    try:
        raw = read_record(root / "CITATION.cff", root).decode()
    except (OSError, ValueError, UnicodeError):
        return None, None
    fields = {}
    for key in ("version", "doi", "title"):
        match = re.search(r"^" + key + r":\s*([^\n]+)$", raw, re.M)
        fields[key] = match.group(1).strip('"\' ') if match else None
    return fields, raw


def external_artifacts(result):
    allowed = {"antismash_sif", "funbgcex_sif", "braker3_sif", "funannotate_sif", "funannotate_docker_image",
               "bigscape_sif", "pfam_hmm", "fasttree_binary", "mibig_cache",
               "clinker_sif", "nplinker_base_sif", "phylogeny_sif", "phylogeny_docker_image"}
    records = []
    try:
        raw = read_record(result / "reproducibility/external_artifacts.tsv", result, 1024 * 1024).decode()
        for index, row in enumerate(csv.DictReader(io.StringIO(raw), delimiter="\t")):
            if index >= 128:
                break
            artifact = row.get("artifact", "")
            if artifact not in allowed:
                continue
            record = {"artifact": artifact}
            for key in ("sha256", "resolved_digest"):
                if DIGEST.fullmatch(str(row.get(key, ""))): record[key] = row[key]
            tag = row.get("version_or_tag", "")
            if TAG.fullmatch(tag): record["recorded_version_or_tag"] = tag
            if len(record) > 1: records.append(record)
    except (OSError, ValueError, UnicodeError, csv.Error):
        pass
    return records


def has_output(result, directory, patterns):
    candidate = result / directory
    if not candidate.is_dir() or any(parent.is_symlink() for parent in (candidate, *candidate.parents)):
        return False
    return any(path.is_file() and not any(parent.is_symlink() for parent in (path, *path.parents))
               for pattern in patterns for path in candidate.rglob(pattern))


def _manifest_rows(result):
    try:
        return list(csv.DictReader(io.StringIO(read_record(result / "summary_tables/run_manifest.tsv", result, 1024 * 1024).decode()), delimiter="\t"))[:4096]
    except (OSError, ValueError, UnicodeError, csv.Error):
        return []


def _row_tools(row):
    tools = set()
    if row.get("antismash_status") in {"ran_ok", "ran_ok_sanitized", "skipped_done"}: tools.add("antiSMASH")
    if row.get("funbgcex_status") in {"ran_ok", "skipped_done"}: tools.add("FunBGCeX")
    predictor = {"prodigal": "Prodigal", "funannotate": "funannotate", "braker3": "BRAKER3"}.get(row.get("prediction_method"))
    if predictor: tools.add(predictor)
    return tools


def _producer_runtime(entry, tool):
    identity, producer = entry["identity"], entry["producer_execution"]
    images = identity.get("containers")
    key = {"antiSMASH": "antismash", "Prodigal": "antismash", "FunBGCeX": "funbgcex", "funannotate": "funannotate"}.get(tool)
    if isinstance(images, dict) and key in images:
        return images[key].removeprefix("sha256:")
    if (producer.get("native_runtime_sha256") == identity["runtime_sha256"] and
            producer.get("producer_source_sha256") == identity["source_sha256"]):
        return producer.get("worker_image", "").removeprefix("sha256:")
    return ""


def _safe_recovery(raw, entry):
    if not isinstance(raw, dict) or not entry.get("key") or raw.get("cache_key") != entry["key"]:
        return None
    record = safe_observation(raw)
    if not record or not record["version"]:
        return None
    if record["tool"] == "NCBI Datasets":
        expected = entry["identity"].get("tools", {}).get("datasets")
        valid = record["backend"] == "native" and record.get("executable_sha256") == expected
    else:
        expected = _producer_runtime(entry, record["tool"])
        valid = record["backend"] == "docker" and bool(expected) and record.get("runtime_sha256", "").removeprefix("sha256:") == expected
    if valid:
        return {**record, "cache_key": entry["key"], "version_observation": "verified original producer runtime"}
    return None


def collect_run_versions(result, work, env, state, log_lines=()):
    """Worker-only finalization: fixed local probes, without changing cached results.

    Older producer gaps can be filled only from their exact immutable runtime or
    an executable whose checksum matches the retrieval identity. No image pull,
    cache mutation, package rewrite or arbitrary command is involved.
    """
    from tool_runtime import annotation_dependencies
    rows = _manifest_rows(result)
    by_label = {row.get("genome_id"): row for row in rows}
    attempts = set()
    for line in log_lines:
        # Reruns can retain earlier log lines; only the current invocation counts.
        if line.endswith("=== Stage: Preparing ClusterWeave project layout ==="):
            attempts.clear()
        match = re.fullmatch(r'(?:\[[^\]\r\n]{1,64}\]\s*)*TOOL_PROGRESS genome=([A-Za-z0-9_.-]{1,240}) tool=funannotate phase=predict message="Started funannotate"', line)
        if match and match[1] in by_label:
            attempts.add(match[1])
    state["annotation_attempts"] = sorted(attempts)
    entries = _cache_records(result)
    entries_by_key = {entry["key"]: entry for entry in entries if entry["key"]}
    recovered = []
    probes = {}
    datasets = shutil.which("datasets") or str(Path(env.get("NCBI_CLI_ROOT", "software/ncbi_cli")) / "datasets")
    for path in sorted((result / "reproducibility/accession_cache").glob("*.json"))[:256]:
        try:
            raw = json.loads(read_record(path, result))
            # A complete original identity is bound to this cache key.
            key = hashlib.sha256(json.dumps(raw["identity"], sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
            entry = entries_by_key.get(key)
            if not entry or raw.get("key") != key:
                continue
            if entry["identity"]["contract"] == "accession-snapshot-v2":
                probe_key = ("NCBI Datasets", "native", datasets)
                if probe_key not in probes: probes[probe_key] = observe("NCBI Datasets", executable=datasets)
                observed = probes[probe_key]
                if observed and (safe := _safe_recovery({**observed, "cache_key": key}, entry)): recovered.append(safe)
                continue
            if entry["outcome"] != "hit" or not entry["identity"]["contract"].startswith("accession-detection-"):
                continue
            row = by_label.get(path.name.removesuffix(".detection.json"), {})
            recorded = entry["producer_execution"].get("tool_versions", [])
            for tool in sorted(_row_tools(row)):
                if any(r["tool"] == tool and r["version"] for r in recorded): continue
                runtime = _producer_runtime(entry, tool)
                if not runtime: continue
                probe_key = (tool, "docker", "sha256:" + runtime)
                if probe_key not in probes: probes[probe_key] = observe(*probe_key)
                observed = probes[probe_key]
                if observed and (safe := _safe_recovery({**observed, "cache_key": key}, entry)): recovered.append(safe)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    state["producer_version_recoveries"] = recovered
    dependencies = []
    for row in rows:
        parent = {"funannotate": "funannotate", "braker3": "BRAKER3"}.get(row.get("prediction_method"))
        if not parent: continue
        # A selected annotation runtime and its command log establish both use and identity.
        parents = [safe for raw in state.get("annotation_observations", [])
                   if (safe := safe_observation(raw)) and safe["tool"] == parent]
        for tool in sorted(annotation_dependencies(result, work, row.get("genome_id", ""), parent)):
            for selected in parents:
                runtime = selected.get("runtime_sha256", "")
                backend = selected["backend"]
                # SIF paths stay private in env; the selected file is rehashed by observe.
                if backend in {"singularity", "apptainer"}:
                    runtime = env.get("FUNANNOTATE_SIF" if parent == "funannotate" else "BRAKER_SIF", str(Path(env.get("SOFTWARE_ROOT", "software")) / ("funannotate/funannotate_v1.8.17.sif" if parent == "funannotate" else "braker/braker3.sif")))
                probe_key = (tool, backend, runtime)
                if probe_key not in probes: probes[probe_key] = observe(*probe_key)
                observed = probes[probe_key]
                if not observed or backend != "native" and observed.get("runtime_sha256") != selected.get("runtime_sha256"):
                    observed = safe_observation({"tool": tool, "backend": backend, "runtime_sha256": selected.get("runtime_sha256")})
                if observed:
                    dependencies.append({"parent": parent, "observation": observed})
    state["dependency_observations"] = dependencies
    state["retrieval_observations"] = []
    if any(re.search(r"NCBI_DOWNLOAD_SUMMARY\b.*\brequested=[1-9][0-9]*\b", line) for line in log_lines):
        probe_key = ("NCBI Datasets", "native", datasets)
        if probe_key not in probes: probes[probe_key] = observe("NCBI Datasets", executable=datasets)
        if probes[probe_key]: state["retrieval_observations"] = [probes[probe_key]]
    references = []
    mibig = None
    for line in log_lines:
        if "Stage 2/4: running" in line:
            mibig = None
            references = []
        match = re.search(r"MiBIG cache detected; enabling --mibig-version ([0-9]+(?:\.[0-9]+){1,3})\s*$", line)
        if match: mibig = match.group(1)
        if "running without MiBIG integration" in line: mibig = None
        if mibig and "Running BiG-SCAPE (inside container)" in line:
            references = [{"name": "MIBiG", "version": mibig, "evidence": "selected reference in BiG-SCAPE invocation", "url": "https://mibig.secondarymetabolites.org/"}]
    if has_output(result, "big_scape", ("index.html", "*_clustering_c*.tsv")):
        state["reference_observations"] = references


def build_report(result, *, state=None, root=None, status="unknown"):
    state = state or {}
    root = root or Path(__file__).resolve().parents[1]
    taxa = taxon_metadata(result)
    cache = _cache_records(result)
    tools = set()
    for entry in cache:
        recovery = [safe for raw in state.get("producer_version_recoveries", [])
                    if (safe := _safe_recovery(raw, entry))]
        if recovery:
            entry["version_recovery"] = recovery
    outcomes = []
    fresh_tools = set()
    reused_tools = set()
    existing_tools = set()
    failed_annotations = {}
    attempts = {label for label in state.get("annotation_attempts", [])
                if isinstance(label, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,240}", label)}
    producer_observations = []
    hit_labels = set()
    expected_producers = {}
    manifest_by_label = {r.get("genome_id"): r for r in _manifest_rows(result)}
    for path in (result / "reproducibility/accession_cache").glob("*.detection.json"):
        try:
            record = json.loads(read_record(path, result))
            if record.get("outcome") == "hit":
                label = path.name.removesuffix(".detection.json")
                hit_labels.add(label)
                if DIGEST.fullmatch(str(record.get("key", ""))):
                    expected_producers[record["key"]] = _row_tools(manifest_by_label.get(label, {}))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    for entry in cache:
        if entry["outcome"] == "hit" and entry["identity"]["contract"].startswith("accession-detection-"):
            producer_observations.extend(entry["producer_execution"].get("tool_versions", []))
            producer_observations.extend(entry.get("version_recovery", []))
            recorded = entry["producer_execution"].get("tool_versions", [])
            reused_tools.update(r["tool"] for r in recorded)
            if entry.get("key") in expected_producers:
                expected_producers[entry["key"]].update(r["tool"] for r in recorded)
        if entry["identity"]["contract"] == "accession-snapshot-v2":
            tools.add("NCBI Datasets")
            if entry["outcome"] == "miss": fresh_tools.add("NCBI Datasets")
            producer_observations.extend(entry.get("version_recovery", []))
            if entry["outcome"] == "hit":
                reused_tools.add("NCBI Datasets")
                if entry.get("key"): expected_producers[entry["key"]] = {"NCBI Datasets"}
    for name, directory, patterns in (
            ("antiSMASH", "antismash", ("index.html",)),
            ("BiG-SCAPE", "big_scape", ("index.html", "*_clustering_c*.tsv")),
            ("clinker", "clinker", ("panel.html",)),
            ("FunBGCeX", "funbgcex", ("index.html", "allBGCs.html", "allBGCs.csv", "BGCs.csv", "results.html"))):
        if has_output(result, directory, patterns):
            tools.add(name)
    try:
        rows = csv.DictReader(io.StringIO(read_record(result / "summary_tables/run_manifest.tsv", result, 1024 * 1024).decode()), delimiter="\t")
        for index, row in enumerate(rows):
            if index >= 4096:
                break
            if row.get("antismash_status") in {"ran_ok", "ran_ok_sanitized", "skipped_done"}: tools.add("antiSMASH")
            if row.get("funbgcex_status") in {"ran_ok", "skipped_done"}: tools.add("FunBGCeX")
            method = row.get("prediction_method")
            if method == "prodigal": tools.add("Prodigal")
            if method == "funannotate": tools.add("funannotate")
            if method == "braker3": tools.add("BRAKER3")
            row_tools = set()
            for tool, key in (("antiSMASH", "antismash_status"), ("FunBGCeX", "funbgcex_status")):
                if row.get(key) in {"ran_ok", "ran_ok_sanitized", "skipped_done"}:
                    row_tools.add(tool)
            predictor = {"prodigal": "Prodigal", "funannotate": "funannotate", "braker3": "BRAKER3"}.get(method)
            if predictor:
                row_tools.add(predictor)
            row_fresh = set()
            cached = row.get("genome_id") in hit_labels
            failed = False
            if cached:
                reused_tools.update(row_tools)
            else:
                if row.get("antismash_status", "").startswith("ran_ok"):
                    row_fresh.add("antiSMASH")
                    if predictor == "Prodigal": row_fresh.add(predictor)
                if row.get("funbgcex_status") == "ran_ok": row_fresh.add("FunBGCeX")
                if predictor and row.get("gbk_status") == method + "_fixed": row_fresh.add(predictor)
                attempted = predictor == "funannotate" and row.get("genome_id") in attempts
                failed = predictor == "funannotate" and row.get("gbk_status") != "funannotate_fixed" and (
                    attempted or row.get("gbk_status") in {"funannotate_busco_training_insufficient",
                        "funannotate_training_models_insufficient", "funannotate_no_translations"})
                if attempted: row_fresh.add(predictor)
                if failed: failed_annotations[predictor] = failed_annotations.get(predictor, 0) + 1
                fresh_tools.update(row_fresh)
                existing_tools.update(row_tools - row_fresh - ({predictor} if failed else set()))
            label = row.get("genome_id", "")
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,240}", label):
                outcome = {"genome_id": label}
                for key in ("taxon_group", "prediction_method", "detector_profile", "gbk_status", "antismash_status", "funbgcex_status"):
                    value = row.get(key, "")
                    if re.fullmatch(r"[A-Za-z0-9_+-]{1,64}", value): outcome[key] = value
                outcomes.append(outcome)
    except (OSError, ValueError, UnicodeError, csv.Error):
        pass
    fields, cff = _citation(root)
    artifacts = external_artifacts(result)
    observations = []
    executed_images = {}
    for entry in cache:
        if entry["outcome"] == "miss" and entry["identity"]["contract"].startswith("accession-detection-"):
            containers = entry["identity"].get("containers")
            if isinstance(containers, dict):
                for key, digest in containers.items(): executed_images.setdefault(key, set()).add(digest.removeprefix("sha256:"))
    for record in state.get("annotation_observations", []):
        safe = safe_observation(record)
        if safe and safe["tool"] in fresh_tools:
            key = {"antiSMASH": "antismash", "Prodigal": "antismash", "FunBGCeX": "funbgcex", "funannotate": "funannotate"}.get(safe["tool"])
            if key in executed_images and safe.get("runtime_sha256", "").removeprefix("sha256:") not in executed_images[key]:
                continue
            observations.append(safe)
    for path in sorted((result / "reproducibility/tool_observations").glob("*.json"))[:128]:
        try:
            raw = json.loads(read_record(path, result))
            record = safe_observation(raw)
            if record and state.get("observation_run") and raw.get("observation_run") == state["observation_run"]:
                observations.append(record)
        except (OSError, ValueError, TypeError):
            continue
    for raw in state.get("retrieval_observations", []):
        record = safe_observation(raw)
        if record and record["tool"] == "NCBI Datasets" and "NCBI Datasets" not in reused_tools:
            observations.append(record)
            tools.add("NCBI Datasets")
    # Optional preflight/configuration alone does not prove use.
    try:
        phylogeny = json.loads(read_record(result / "phylogeny/phylogeny_run_manifest.json", result, 1024 * 1024))
        if phylogeny.get("status") in {"success", "success_with_optional_failures"}:
            tools.update({"MAFFT", "trimAl", "IQ-TREE"})
            if phylogeny.get("topology_comparison_count", 0) > 0: tools.add("ETE4")
    except (OSError, ValueError, TypeError):
        pass
    if has_output(result, "nplinker", ("links_*.tsv",)):
        tools.add("NPLinker")
    if has_output(result, "figures", ("*.svg", "*.png", "*.pdf")):
        tools.update(record["tool"] for record in observations if record["tool"] in {"Python", "CairoSVG", "R"})
    # FastTree is configured by BiG-SCAPE but may not be invoked for every cohort.
    if has_output(result, "big_scape", ("*.newick",)):
        tools.add("FastTree")
    for raw in state.get("dependency_observations", []):
        if not isinstance(raw, dict) or raw.get("parent") not in fresh_tools: continue
        record = safe_observation(raw.get("observation"))
        if record:
            tools.add(record["tool"])
            fresh_tools.add(record["tool"])
            observations.append(record)
    for record in producer_observations:
        if record["tool"] in TOOLS:
            tools.add(record["tool"])
    references = []
    for record in state.get("reference_observations", []):
        if (isinstance(record, dict) and record.get("name") == "MIBiG" and
                re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", str(record.get("version", ""))) and "BiG-SCAPE" in tools):
            references.append({"name": "MIBiG", "version": record["version"], "evidence": "selected reference in BiG-SCAPE invocation", "url": "https://mibig.secondarymetabolites.org/"})
    tool_records = []
    artifact_names = {"antiSMASH": "antismash_sif", "FunBGCeX": "funbgcex_sif", "BiG-SCAPE": "bigscape_sif", "clinker": "clinker_sif", "funannotate": "funannotate_sif", "BRAKER3": "braker3_sif", "NPLinker": "nplinker_base_sif"}
    for name in sorted(tools):
        observed = [record for record in observations if record["tool"] == name]
        producer = [record for record in producer_observations if record["tool"] == name]
        producer_versions = {record["version"] for record in producer if record["version"]}
        versions = {record["version"] for record in observed + producer if record["version"]}
        version = ", ".join(sorted(versions)) or None
        mode = "analysis computed and reused from verified cache" if name in fresh_tools and name in reused_tools else "analysis reused from verified cache" if name in reused_tools else "current execution" if name in fresh_tools or observed else "output evidence; execution not recorded"
        if name in failed_annotations:
            if name not in fresh_tools and not observed and name not in reused_tools:
                mode = "original execution not recorded"
            mode += f"; annotation failed for {failed_annotations[name]} genome(s)"
        if name in existing_tools:
            mode = "existing outputs; original execution not recorded" if not observed and name not in reused_tools else mode + "; existing outputs"
        coverage = []
        for entry in cache:
            if name not in expected_producers.get(entry.get("key"), set()): continue
            evidence = entry["producer_execution"].get("tool_versions", []) + entry.get("version_recovery", [])
            recorded = sorted({r["version"] for r in evidence if r["tool"] == name and r["version"]})
            coverage.append({"cache_key": entry["key"], "versions": recorded, "status": "verified" if recorded else "unavailable"})
        tool_records.append({"name": name, "version": version, "verified_versions": sorted(versions), "producer_version_coverage": coverage,
            "version_observation": "verified original producer runtime" if any(r.get("cache_key") for r in producer) and version else "recorded producer runtime probe" if producer and not observed and version else "selected runtime version probe" if version else "not recorded",
            "use": mode, "runtime_observations": observed,
            "producer_version": next(iter(producer_versions)) if len(producer_versions) == 1 else None,
            "producer_runtime_observations": producer,
            "producer_version_scope": "Producer versions include recorded observations and explicit recovery from the original immutable runtime; unavailable historical evidence remains identified." if name in reused_tools else None,
            "configured_artifacts": [a for a in artifacts if a["artifact"] == artifact_names.get(name)],
            "url": TOOLS[name][1], "citation_doi": (TOOLS[name][2] or None) if name != "antiSMASH" or (version or "").startswith("8.") else None})
    inputs = []
    for path in sorted((result / "input_gbks").glob("*.gbk"))[:4096]:
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
        inputs.append({"genome_id": path.stem, **taxa.get(path.stem, {"taxon_group": "unclassified", "accession": None}),
                       "staged_genbank_sha256": digest.hexdigest(), "package_path": package_name("input_gbks/" + path.name, taxa)})
    resources = state.get("resources", [])
    metadata = {"schema": 1, "status": status, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "processing_started_at_utc": state.get("started_at_utc"), "processing_finished_at_utc": state.get("finished_at_utc"),
        "processing_wall_seconds_before_packaging": state.get("wall_seconds"),
        "project": {"title": "ClusterWeave", "release_record": fields if state.get("source_sha256") else None,
                    "citation_record": fields, "source_sha256": state.get("source_sha256"),
                    "controller_image_sha256": state.get("controller_image_sha256"),
                    "note": "The release citation alone does not identify modified source; use the captured source and producer hashes."},
        "configuration": state.get("configuration", {}), "inputs": inputs, "source_inputs": state.get("source_inputs", []), "analysis_outcomes": outcomes, "cache": cache,
        "observed_external_artifacts": artifacts,
        "external_artifact_scope": "Recorded software/reference inventory; presence alone does not establish use. Paths and source URIs are excluded.",
        "cache_record_scope": "Only recorded complete supported identities are listed. Missing or unsupported historical records do not establish a hit or a miss.",
        "tools": tool_records, "references": references,
        "resources": resources, "unmeasured_stages": state.get("unmeasured_stages", []),
        "resource_note": "Configured CPU limits are not consumption. Native CPU is wait4 accounting. Container CPU and combined memory are sampled observations; exact aggregate peak RAM is not collected. Canonical workflow resource rows combine its internal tools. Missing historical metrics and producer timings remain unavailable."}
    methods = ["# ClusterWeave methods and run information", "",
        "This record accompanies the result package. Review it when preparing a manuscript; it is not a scientific interpretation.", "",
        "## Software and citations", "", "ClusterWeave software record: https://doi.org/10.11578/PMI/dc.20260608.2. See CITATION.cff and CITATIONS.bib. Tool versions are verified against selected execution runtimes and recorded original producer identities. Explicit version recovery is documented in run_metadata.json.",
        f"Observed source SHA256: {state.get('source_sha256') or 'not recorded'}.", "",
        "| Tool represented in these outputs | Observed version | Evidence and use | Citation or software record |", "| --- | --- | --- | --- |"]
    for tool in metadata["tools"]:
        runtime_details = "; ".join(sorted({record["backend"] + ("; configured tag " + record["configured_tag"] if record.get("configured_tag") else "") for record in tool["runtime_observations"] + tool["producer_runtime_observations"]}))
        coverage = tool["producer_version_coverage"]
        coverage_note = f"producer versions verified for {sum(r['status'] == 'verified' for r in coverage)}/{len(coverage)} cache entries" if coverage else ""
        unavailable = "version evidence unavailable for current execution" if tool["name"] in fresh_tools else "historical version evidence unavailable"
        evidence = "; ".join(part for part in (tool["use"], coverage_note, tool["version_observation"] if tool["version"] else unavailable, runtime_details) if part)
        methods.append(f"| {tool['name']} | {tool['version'] or 'not recorded'} | {evidence} | {('https://doi.org/' + tool['citation_doi']) if tool['citation_doi'] else tool['url']} |")
    methods += ["", "Executable versions, configured image tags and immutable runtime hashes are recorded separately in run_metadata.json. Each cache recovery records its cache key and the matching original runtime or executable checksum."]
    if references:
        methods += ["", "## Reference datasets", "", "| Reference | Version used | Evidence |", "| --- | --- | --- |"]
        methods += [f"| {r['name']} | {r['version']} | {r['evidence']} |" for r in references]
    if outcomes:
        methods += ["", "## Recorded annotation and detection", "",
                    "| Genome | Taxon group | Gene annotation method | BGC detection profile | GenBank / annotation outcome | antiSMASH outcome | FunBGCeX outcome |",
                    "| --- | --- | --- | --- | --- | --- | --- |"]
        for outcome in outcomes:
            methods.append("| " + " | ".join(outcome.get(key, "not recorded") for key in ("genome_id", "taxon_group", "prediction_method", "detector_profile", "gbk_status", "antismash_status", "funbgcex_status")) + " |")
        methods += ["", "Annotation failure statuses identify genomes excluded from BGC detection. Skipped detection does not establish an absence of BGCs."]
    if metadata["configuration"]:
        methods += ["", "## Recorded configuration", "", "| Parameter | Value |", "| --- | --- |"]
        methods += [f"| {key} | {value} |" for key, value in sorted(metadata["configuration"].items())]
    methods += ["", "## Inputs and analysis", "", "Staged GenBank inputs are grouped by bacteria/fungi in this package; unclassified inputs are labelled explicitly. The runtime input_gbks layout remains flat. Input checksums and the recorded configuration are in run_metadata.json.", "",
        "Validated cached annotation and detection are analysis used by this job and are included in its methods and citations. Cache records retain the original computation, tool versions and producer identities. Execution records describe work computed during this run; downstream analyses retain their own provenance.", "",
        "## Time and resources", "", metadata["resource_note"], "",
        f"Processing start (UTC): {metadata['processing_started_at_utc'] or 'not recorded'}. Processing end before packaging (UTC): {metadata['processing_finished_at_utc'] or 'not recorded'}.",
        "See resources.tsv and the measurement methods in run_metadata.json. Null values mean not collected, not zero. Queue time and result-package compression are outside the processing measurements.", ""]
    bib = ["@software{clusterweave,", "  title = {ClusterWeave},", "  doi = {10.11578/PMI/dc.20260608.2},", "  url = {https://github.com/n2mology/clusterweave}", "}"]
    for tool in metadata["tools"]:
        key = re.sub(r"[^a-z0-9]", "", tool["name"].lower())
        bib += ["@software{" + key + ",", "  title = {" + tool["name"] + "},", "  url = {" + tool["url"] + "},",
                *( ["  doi = {" + tool["citation_doi"] + "},"] if tool["citation_doi"] else [] ),
                "  note = {Analysis version: " + (tool["version"] or "not recorded") + "; " + tool["use"] + "; " + tool["version_observation"] + "}", "}"]
    for reference in references:
        bib += ["@misc{mibig,", "  title = {MIBiG},", "  url = {" + reference["url"] + "},", "  note = {Reference version: " + reference["version"] + "}", "}"]
    columns = ["stage", "exit_code", "started_at_utc", "finished_at_utc", "wall_seconds", "native_cpu_seconds",
               "native_largest_process_peak_rss_bytes", "native_sampled_peak_sum_rss_bytes",
               "container_sampled_cpu_seconds", "sampled_peak_rss_plus_container_usage_bytes", "container_observation", "sampling_incomplete"]
    output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=columns, delimiter="\t", lineterminator="\n", extrasaction="ignore")
    writer.writeheader(); writer.writerows(resources)
    files = {"METHODS.md": "\n".join(methods).encode(), "run_metadata.json": (json.dumps(metadata, sort_keys=True, indent=2, allow_nan=False) + "\n").encode(),
             "CITATIONS.bib": ("\n".join(bib) + "\n").encode(), "resources.tsv": output.getvalue().encode()}
    if cff is not None: files["CITATION.cff"] = cff.encode()
    return files
