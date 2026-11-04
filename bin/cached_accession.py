#!/usr/bin/env python3
"""Frozen public accession inputs and accession-local annotation/detection reuse."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

from accession_cache import (ACCESSION, DIGEST, SCHEMA, MAX_FILE_BYTES, Store,
                             Unavailable, canonical, identity_key, regular_bytes,
                             reject_symlink_parents, safe_directory, sha256)
from cached_genbank import public_accession, digest_paths, runtime_digest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_SNAPSHOT = "accession-snapshot-v2"
CONTRACT_DETECTION = "accession-detection-v3"
# Partitioning is scientific/output policy; concurrency only schedules its work.
PARTITION_SHA256 = sha256(canonical({"records": "stable-record-isolation-v1",
    "singleton": "whole-record-v1", "unstable_ids": "whole-genome-v1"}))
SCHEDULING_SETTINGS = frozenset({"CPUS", "THREADS", "GENOME_PARALLELISM", "WORKERS",
    "ANTISMASH_RECORD_PARALLELISM", "ANTISMASH_SHARD_CPUS", "ANTISMASH_LEGACY_CPUS",
    "CLUSTERWEAVE_TOOL_DOCKER_CPUS", "CLUSTERWEAVE_TOOL_DOCKER_MEMORY",
    "CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT"})
ALLOCATION_SETTINGS = SCHEDULING_SETTINGS | {"ANNO_CPUS"}
MAX_MEMBERS = 20000
PRIVATE_PATH = re.compile(rb"(?:file://|/data/(?:jobs|uploads)/|/home/|/tmp/)")
PORTABLE_PATH = re.compile(rb"__CW_(?:RESULTS|WORK|INPUT)__(?:/[A-Za-z0-9_.-]+)*")
METHODS = {"prodigal", "existing_cds", "funannotate", "braker3"}
NATIVE_ROOTS = tuple(Path(p) for p in (
    "/usr", "/opt", "/bin", "/sbin", "/lib", "/lib64", "/etc/alternatives",
    "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/fonts", "/etc/localtime", "/etc/timezone"))


def validate_identity(value):
    snapshot = value["contract"] in {CONTRACT_SNAPSHOT, "accession-snapshot-v1"}
    legacy = value["contract"].endswith("-v1")
    if value["route"] not in [{"taxon": t, "annotation": "retrieval" if snapshot else "per-genome"}
                              for t in ("bacteria", "fungi")]:
        raise Unavailable("identity_route")
    for name in ("tools", "containers", "databases", "models"):
        items = value[name]
        if items == "not-used" and name != "tools" and (snapshot or not legacy and name == "containers"):
            continue
        if not isinstance(items, dict) or not items or any(not isinstance(k, str) or
                not re.fullmatch(r"[a-z0-9_-]{1,64}", k) or not isinstance(v, str) or
                not DIGEST.fullmatch(v) for k, v in items.items()):
            raise Unavailable("identity_dependencies")
    if snapshot:
        if set(value["tools"]) != ({"datasets"} if legacy else {"datasets", "unzip"}) or any(value[n] != "not-used" for n in ("containers", "databases", "models")):
            raise Unavailable("identity_dependencies")
    elif legacy and (value["tools"] != {"pipeline": value["source_sha256"]} or
          not {"worker"} <= set(value["containers"]) <= {"worker", "antismash", "funbgcex", "funannotate"} or
          value["containers"]["worker"] != value["runtime_sha256"] or
          set(value["databases"]) != {"antismash"} or
          value["models"] != {"embedded": sha256(canonical(value["containers"]))}):
        raise Unavailable("identity_dependencies")
    elif not legacy:
        containers = value["containers"]
        images = {} if containers == "not-used" else containers
        if (value["tools"] != {"pipeline": value["source_sha256"], "native": value["runtime_sha256"]} or
                not set(images) <= {"antismash", "funbgcex", "funannotate"} or
                value["route"]["taxon"] == "fungi" and "funbgcex" not in images or
                set(value["databases"]) != {"antismash"} or
                value["models"] != {"embedded": sha256(canonical({"native": value["runtime_sha256"], "images": images}))}):
            raise Unavailable("identity_dependencies")
    params = value["parameters"]
    required = {"configuration_sha256", "genome_label_sha256"}
    if value["contract"] == CONTRACT_DETECTION:
        required.add("partition_sha256")
    if not isinstance(params, dict) or set(params) != required or any(
            not isinstance(v, str) or not DIGEST.fullmatch(v) for v in params.values()):
        raise Unavailable("identity_parameters")


def scheduling_record(settings):
    """Only declared resource values may enter portable producer provenance."""
    values = {k: v for k, v in settings.items() if k in ALLOCATION_SETTINGS}
    for key, value in values.items():
        pattern = r"[0-9]+(?:\.[0-9]+)?[bkmgBKMG]?" if key.endswith("MEMORY") else r"[0-9]+(?:\.[0-9]+)?"
        if not isinstance(value, str) or len(value) > 32 or value and not re.fullmatch(pattern, value):
            raise Unavailable("execution_provenance")
    return values


def hash_file(path, *, native=False):
    reject_symlink_parents(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not native and before.st_nlink != 1:
            raise Unavailable("dependency_type")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as handle:
            for block in iter(lambda: handle.read(8 * 1024**2), b""):
                digest.update(block)
        if stamp(before) != stamp(os.fstat(fd)):
            raise Unavailable("dependency_changed")
        return digest.hexdigest()
    finally:
        os.close(fd)


def stamp(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def inventory(root):
    reject_symlink_parents(root)
    if not root.is_dir():
        raise Unavailable("dependency_missing")
    paths = {}
    for directory, names, files in os.walk(root):
        if any((Path(directory) / n).is_symlink() for n in names):
            raise Unavailable("dependency_link")
        for name in files:
            p = Path(directory) / name
            reject_symlink_parents(p)
            if not p.is_file():
                raise Unavailable("dependency_type")
            paths[p.relative_to(root).as_posix()] = p
    if not paths:
        raise Unavailable("dependency_empty")
    return paths


def content_tree(root):
    return sha256(canonical({n: hash_file(p) for n, p in sorted(inventory(root).items())}))


def tree_stamp(root):
    return {n: stamp(p.stat()) for n, p in inventory(root).items()}


def source_digest():
    paths = {name: ROOT / name for name in (
        "bin/sanitize_bacterial_genbank.py", "bin/annotation_genbank.py", "bin/annotation_runtime.py",
        "bin/annotation_input.py", "bin/prepare_antismash_input.py", "bin/compact_antismash_shard.py",
        "bin/prepare_antismash_web_results.py", "bin/gff3_to_gbk_with_translations.py",
        "bin/cached_genbank.py", "web/resource_policy.py")}
    paths["runner"] = ROOT / "run_annotation_and_detection.sh"
    paths["readiness"] = Path(sys.modules["genbank_readiness"].__file__)
    return digest_paths(paths)


def native_inventory():
    paths = {}
    for root in NATIVE_ROOTS:
        if not root.exists() and not root.is_symlink():
            continue
        paths[root.as_posix()] = root
        if root.is_symlink() or not root.is_dir():
            continue
        for directory, names, files in os.walk(root):
            base = Path(directory)
            for name in list(names):
                path = base / name
                if name == "__pycache__":
                    names.remove(name)
                    if path.is_symlink():
                        raise Unavailable("external_native_bytecode")
                    # CPython's derived caches are not scientific source.
                    for cached in path.iterdir():
                        if cached.suffix == ".pyc":
                            import importlib.util
                            if not Path(importlib.util.source_from_cache(str(cached))).is_file():
                                raise Unavailable("native_bytecode_without_source")
                    continue
                paths[path.as_posix()] = path
                if path.is_symlink():
                    names.remove(name)
            for name in files:
                path = base / name
                if path.suffix in {".pyc", ".pyo"} and path.with_suffix(".py").is_file():
                    continue
                paths[path.as_posix()] = path
    if not paths:
        raise Unavailable("native_runtime_missing")
    return paths


def native_digest(*, content=False):
    digest = hashlib.sha256()
    for name, path in sorted(native_inventory().items()):
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            record = ["link", mode, os.readlink(path)]
            if not content:
                record += stamp(info)
        elif stat.S_ISDIR(info.st_mode):
            # Derived bytecode changes directory mtimes without changing code.
            record = ["directory", mode]
        elif stat.S_ISREG(info.st_mode):
            record = ["file", mode, hash_file(path, native=True)] if content else ["file", mode, *stamp(info)]
        else:
            raise Unavailable("native_runtime_file_type")
        digest.update(canonical([name, record]))
    return sha256(canonical({"files": digest.hexdigest(), "python": sys.version,
                             "byteorder": sys.byteorder, "platform": sys.platform}))


def store():
    root = Path(os.environ["CLUSTERWEAVE_ACCESSION_CACHE_ROOT"])
    reject_symlink_parents(root)
    safe_directory(root)
    for name in ("DATA_DIR", "DATA_ROOT", "RESULTS_ROOT", "GENOME_ROOT", "WORK_ROOT", "PROJECT_DIR"):
        if os.environ.get(name) and root.resolve().is_relative_to(Path(os.environ[name]).resolve()):
            raise Unavailable("cache_in_job_tree")
    if root.resolve().is_relative_to(ROOT):
        raise Unavailable("cache_in_source")
    return Store(root, max_bytes=int(os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_MAX_BYTES", 10 * 1024**3)),
                 max_entries=int(os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_MAX_ENTRIES", 256)),
                 max_age_seconds=int(os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_MAX_AGE_SECONDS", 30 * 86400)))


def cancelled():
    return bool(os.environ.get("CLUSTERWEAVE_CANCEL_FILE") and Path(os.environ["CLUSTERWEAVE_CANCEL_FILE"]).exists())


def forced():
    return os.environ.get("FORCE") == "1" or os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_FORCE_MISS") == "1"


def metadata_operation(operation):
    deadline = time.monotonic() + 120
    while True:
        if cancelled():
            raise Unavailable("cancelled")
        try:
            return operation()
        except Unavailable as exc:
            if str(exc) != "busy" or time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def claim_path(cache, key):
    directory = cache.root / "claims"
    directory.mkdir(mode=0o700, exist_ok=True)
    safe_directory(directory)
    # A bounded set of lock files avoids an inode leak after entry eviction.
    # Equal keys always share a claim; rare slot collisions only serialize work.
    path = directory / key[:2]
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise Unavailable("claim_type")
    finally:
        os.close(fd)
    return path


@contextmanager
def claim(cache, key):
    fd = os.open(claim_path(cache, key), os.O_RDWR | os.O_NOFOLLOW)
    try:
        deadline = time.monotonic() + 3600
        while True:
            if cancelled():
                raise Unavailable("cancelled")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise Unavailable("claim_timeout")
                time.sleep(1)
        yield
    finally:
        os.close(fd)


def pack(files):
    if not files or len(files) > MAX_MEMBERS or sum(map(len, files.values())) > MAX_FILE_BYTES:
        raise Unavailable("bundle_capacity")
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o600
            archive.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue(), mtime=0)


def unpack(data):
    files, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            name = member.name
            path = PurePosixPath(name)
            if (not member.isfile() or name != path.as_posix() or path.is_absolute() or
                    any(p in {"..", "."} for p in path.parts) or "\\" in name or
                    name in files or len(files) >= MAX_MEMBERS or member.size < 0):
                raise Unavailable("bundle_inventory")
            total += member.size
            if total > MAX_FILE_BYTES:
                raise Unavailable("bundle_capacity")
            files[name] = archive.extractfile(member).read(member.size + 1)
            if len(files[name]) != member.size:
                raise Unavailable("bundle_truncated")
    if not files:
        raise Unavailable("bundle_empty")
    return files


def portable(data, replacements, *, restore=False):
    # Generated paths are execution context. Public identifiers and sequences stay intact.
    if not restore and any(marker.encode() in data for marker in replacements.values()):
        raise Unavailable("reserved_path_marker")
    for original, neutral in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        left, right = (neutral, original) if restore else (original, neutral)
        data = data.replace(left.encode(), right.encode())
    return data


def validate_bundle(payload, identity):
    files = unpack(payload["bundle.tar"])
    snapshot = identity["contract"] in {CONTRACT_SNAPSHOT, "accession-snapshot-v1"}
    legacy = identity["contract"].endswith("-v1")
    for name, data in files.items():
        job_id = os.environ.get("CLUSTERWEAVE_JOB_ID", "")
        # Public libraries and biological records can contain UUIDs. Reject the
        # actual execution context instead of mistaking public IDs for secrets.
        def neutral_path(match):
            parts = match.group().split(b"/")[1:]
            if any(part in {b".", b".."} for part in parts):
                raise Unavailable("bundle_private_context")
            return b"__CW_PORTABLE_PATH__"
        # /tmp below a reserved job-root marker is a relative, remappable path,
        # not an unnormalized absolute path from the previous execution.
        inspected = PORTABLE_PATH.sub(neutral_path, data) if not snapshot else data
        if PRIVATE_PATH.search(inspected) or job_id and job_id.encode() in data:
            raise Unavailable("bundle_private_context")
        if snapshot:
            if not name.startswith("ncbi_dataset/data/"):
                raise Unavailable("snapshot_inventory")
        elif name not in {"outcome.json", "execution.json"} and name.split("/", 1)[0] not in {"input_gbks", "antismash", "funbgcex", "summary_tables"}:
            raise Unavailable("detection_inventory")
        if not snapshot and name not in {"outcome.json", "execution.json"}:
            parts = PurePosixPath(name).parts
            if parts[0] == "input_gbks":
                label = PurePosixPath(parts[-1]).stem
                if len(parts) != 2 or not name.endswith(".gbk"):
                    raise Unavailable("detection_inventory")
            elif parts[0] == "summary_tables":
                if (identity["route"]["taxon"] != "bacteria" or len(parts) != 3 or
                        parts[1] != "bacterial_record_maps" or not parts[-1].endswith(".record_map.tsv")):
                    raise Unavailable("detection_inventory")
                label = parts[-1].removesuffix(".record_map.tsv")
            else:
                if len(parts) < 3 or parts[0] == "funbgcex" and identity["route"]["taxon"] != "fungi":
                    raise Unavailable("detection_inventory")
                label = parts[1]
            if sha256(label.encode()) != identity["parameters"]["genome_label_sha256"]:
                raise Unavailable("detection_accession_label")
        if name.endswith((".gbk", ".gbff", ".gb")):
            from Bio import SeqIO
            records = list(SeqIO.parse(io.StringIO(data.decode()), "genbank"))
            if not records or any(not len(r.seq) for r in records):
                raise Unavailable("bundle_genbank")
    if snapshot:
        fasta = [d for n, d in files.items() if n.endswith(".fna")]
        reports = [d for n, d in files.items() if n.endswith("assembly_data_report.jsonl")]
        if not fasta or not reports or not all(d.startswith(b">") for d in fasta):
            raise Unavailable("snapshot_structure")
        records = [json.loads(line) for data in reports for line in data.splitlines() if line.strip()]
        if len(records) != 1 or records[0].get("accession") != identity["accession"]:
            raise Unavailable("snapshot_accession")
        return files
    outcome = json.loads(files["outcome.json"])
    if not legacy:
        execution = json.loads(files["execution.json"])
        expected = {"worker_image", "native_runtime_sha256", "producer_source_sha256"}
        if identity["contract"] == CONTRACT_DETECTION:
            expected.add("scheduling")
            scheduling = execution.get("scheduling")
            if not isinstance(scheduling, dict) or scheduling_record(scheduling) != scheduling:
                raise Unavailable("execution_provenance")
        if "tool_versions" in execution:
            expected.add("tool_versions")
            from tool_runtime import safe_observation
            versions = execution["tool_versions"]
            if (not isinstance(versions, list) or len(versions) > 16 or
                    any(safe_observation(record) != record for record in versions)):
                raise Unavailable("execution_provenance")
        if (set(execution) != expected or
                not isinstance(execution["worker_image"], str) or not DIGEST.fullmatch(execution["worker_image"]) or
                execution["native_runtime_sha256"] != identity["runtime_sha256"] or
                execution["producer_source_sha256"] != identity["source_sha256"]):
            raise Unavailable("execution_provenance")
    if set(outcome) != {"gbk_status", "prediction_method", "antismash_status", "funbgcex_status", "taxon_group", "detector_profile", "funbgcex_applicability"}:
        raise Unavailable("outcome_schema")
    if outcome["prediction_method"] not in METHODS or outcome["taxon_group"] != identity["route"]["taxon"]:
        raise Unavailable("outcome_route")
    if outcome["gbk_status"] not in {"bacterial_sequence_sanitized", "original_ok", "funannotate_fixed", "braker3_fixed"}:
        raise Unavailable("annotation_incomplete")
    if outcome["antismash_status"] not in {"ran_ok", "ran_ok_sanitized"}:
        raise Unavailable("detection_incomplete")
    bacterial = outcome["taxon_group"] == "bacteria"
    if outcome["funbgcex_status"] != ("not_applicable_taxon" if bacterial else "ran_ok"):
        raise Unavailable("detection_incomplete")
    if not any(n.startswith("input_gbks/") for n in files) or not any(n.startswith("antismash/") and n.endswith("/index.html") and d for n, d in files.items()):
        raise Unavailable("detection_incomplete")
    if not any(n.startswith("antismash/") and n.endswith(("regions.js", ".antismash.json", "overview.js")) for n in files):
        raise Unavailable("detection_incomplete")
    if not bacterial and not any(n.startswith("funbgcex/") and n.rsplit("/", 1)[-1] in {"allBGCs.csv", "allBGCs.html", "BGCs.csv", "results.html"} and d for n, d in files.items()):
        raise Unavailable("detection_incomplete")
    if not bacterial:
        from genbank_readiness import inspect_genbank_translation_stream
        annotated = [d for n, d in files.items() if n.startswith("input_gbks/")]
        if not annotated or not all(inspect_genbank_translation_stream(io.StringIO(d.decode())).usable_translated_cds for d in annotated):
            raise Unavailable("annotation_incomplete")
        if not legacy and outcome["prediction_method"] == "funannotate" and "funannotate" not in identity["containers"]:
            raise Unavailable("annotation_identity_missing")
    return files


def install(files, root, replacements=None):
    """Validate and stage the complete bundle before changing any job output."""
    reject_symlink_parents(root)
    root.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix=".accession-restore-", dir=root))
    installed = []
    try:
        for name, data in files.items():
            if name in {"outcome.json", "execution.json"}:
                continue
            target = root / name
            reject_symlink_parents(target)
            if target.exists():
                # Shared reuse never mixes a bundle with partial or edited job output.
                raise Unavailable("destination_exists")
            staged = pending / name
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(portable(data, replacements, restore=True) if replacements else data)
            staged.chmod(0o600)
        for name in files:
            if name in {"outcome.json", "execution.json"}:
                continue
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(pending / name, target)
            installed.append(target)
    except BaseException:
        for p in reversed(installed):
            p.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(pending)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink_parents(path)
    fd, name = tempfile.mkstemp(prefix=".cache-record-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical(value))
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def provenance(path, identity, outcome, reason, population="not-attempted", manifest=None):
    write_json(path, {"schema": SCHEMA, "identity": identity, "key": identity_key(identity) if identity else None,
                      "outcome": outcome, "reason": reason, "population": population, "entry_manifest": manifest})


def producer_tool_versions(identity, outcome, args=None):
    """Optional producer metadata never participates in a scientific cache key."""
    path = os.environ.get("CLUSTERWEAVE_ANNOTATION_OBSERVATIONS")
    if not path:
        return []
    try:
        from tool_runtime import safe_observation
        records = json.loads(regular_bytes(Path(path)))
        if not isinstance(records, list) or len(records) > 16:
            return []
        allowed = {"antiSMASH", "FunBGCeX"} if outcome["taxon_group"] == "fungi" else {"antiSMASH", "Prodigal"}
        if outcome.get("gbk_status") == "funannotate_fixed": allowed.add("funannotate")
        images = identity["containers"] if isinstance(identity["containers"], dict) else {}
        result = []
        for raw in records:
            record = safe_observation(raw)
            if not record or record["tool"] not in allowed:
                continue
            image_key = {"antiSMASH": "antismash", "FunBGCeX": "funbgcex", "funannotate": "funannotate", "Prodigal": "antismash"}.get(record["tool"])
            if record["backend"] == "docker":
                if record.get("runtime_sha256", "").removeprefix("sha256:") != images.get(image_key):
                    continue
            elif record["backend"] != "native" or image_key in images:
                continue
            result.append(record)
        if args is not None and "funannotate" in allowed:
            from tool_runtime import annotation_dependencies, observe
            for parent in [r for r in result if r["tool"] == "funannotate"]:
                for tool in sorted(annotation_dependencies(args.results, Path(os.environ.get("WORK_ROOT", "/unavailable")), args.genome_id, "funannotate")):
                    observed = observe(tool, parent["backend"], parent.get("runtime_sha256", ""))
                    if not observed or parent["backend"] != "native" and observed.get("runtime_sha256") != parent.get("runtime_sha256"):
                        observed = safe_observation({"tool": tool, "backend": parent["backend"], "runtime_sha256": parent.get("runtime_sha256")})
                    if observed: result.append(observed)
        return result[:16]
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        return []


def detection_provenance(args, state, outcome, reason, population="not-attempted", manifest=None, execution=None):
    identity = state["identity"]
    write_json(args.provenance, {"schema": SCHEMA, "identity": identity, "key": identity_key(identity),
        "outcome": outcome, "reason": reason, "population": population, "entry_manifest": manifest,
        "materialized_by_worker": state["context"]["worker_image"], "producer_execution": execution,
        "materializer_scheduling": scheduling_record(state["context"]["settings"])})


def snapshot_identity(args):
    accession = args.accession.upper()
    if not ACCESSION.fullmatch(accession):
        raise Unavailable("accession_version")
    public_accession(args.route_manifest, args.genome_id, args.taxon)  # authoritative route only
    if public_accession(args.route_manifest, args.genome_id, args.taxon) != accession:
        raise Unavailable("accession_route")
    binary = Path(shutil.which(args.datasets) or args.datasets).resolve()
    source = digest_paths({"download": ROOT / "scripts/ncbi/download_ncbi_genomes.sh"})
    # Load the same validation dependencies before every identity check.
    runtime = runtime_digest("fungi")
    return {"schema": SCHEMA, "contract": CONTRACT_SNAPSHOT, "accession": accession,
            "genome_sha256": sha256(accession.encode()), "route": {"taxon": args.taxon, "annotation": "retrieval"},
            "source_sha256": source, "runtime_sha256": runtime,
            "tools": {"datasets": hash_file(binary), "unzip": hash_file(Path(shutil.which("unzip") or "/unavailable"), native=True)},
            "containers": "not-used", "databases": "not-used", "models": "not-used",
            "parameters": {"configuration_sha256": sha256(canonical(["genome,gff3,gbff", "genome,gbff", "genome"])),
                           "genome_label_sha256": sha256(accession.encode())}}


def retrieve(args):
    """Hold the accession claim across the unchanged downloader and publication."""
    identity, cache, gate = None, None, None
    record = args.provenance
    try:
        if forced():
            raise Unavailable("forced")
        cache = store()
        identity = snapshot_identity(args)
        gate = claim(cache, identity_key(identity))
        gate.__enter__()
        payload, reason, manifest = metadata_operation(lambda: cache.lookup(identity, lambda p: validate_bundle(p, identity)))
        if payload:
            files = validate_bundle(payload, identity)
            install(files, args.destination)
            if cancelled() or snapshot_identity(args) != identity:
                shutil.rmtree(args.destination / "ncbi_dataset")
                raise Unavailable("identity_changed")
            provenance(record, identity, "hit", "verified", manifest=manifest)
            print(f"ACCESSION_CACHE genome={identity['accession']} stage=retrieval outcome=hit", flush=True)
            return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, Unavailable) else "cache_unavailable"
        if gate:
            gate.__exit__(None, None, None)
            gate = None
        cache = None
    try:
        result = subprocess.run(args.command, check=False)
        if result.returncode:
            provenance(record, identity, "miss", reason, "computation_failed")
            return result.returncode
        population, manifest = "not-attempted", None
        if cache and not cancelled():
            try:
                files = {n: regular_bytes(p, allow_empty=True) for n, p in inventory(args.destination).items()
                         if n.startswith("ncbi_dataset/data/")}
                payload = {"bundle.tar": pack(files)}
                population = metadata_operation(lambda: cache.publish(identity, payload, lambda p: validate_bundle(p, identity),
                    can_publish=lambda: not cancelled() and snapshot_identity(args) == identity))
                if population in {"published", "duplicate"}:
                    _, _, manifest = metadata_operation(lambda: cache.lookup(identity, lambda p: validate_bundle(p, identity)))
            except Exception as exc:
                population = "rejected:" + (str(exc) if isinstance(exc, Unavailable) else "cache_unavailable")
        provenance(record, identity, "miss", reason, population, manifest)
        return 0
    finally:
        if gate:
            gate.__exit__(None, None, None)


def image_id(reference):
    value = subprocess.check_output(["docker", "inspect", "--format", "{{.Image}}", reference], stderr=subprocess.DEVNULL, text=True).strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        # Image inspect uses .Id; container inspect uses .Image.
        raise Unavailable("runtime_identity")
    return value[7:]


def scientific_image(reference):
    value = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", reference.removeprefix("docker://")], stderr=subprocess.DEVNULL, text=True).strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise Unavailable("runtime_identity")
    return value[7:]


def native_runtime_supported():
    # Custom Python modules or executables outside the image need a separate
    # dependency contract. The prepared retrieval CLI does not affect detection.
    if any(os.environ.get(name) for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE", "LD_PRELOAD", "LD_LIBRARY_PATH", "BASH_ENV")):
        raise Unavailable("external_native_runtime")
    for directory in os.get_exec_path():
        path = Path(directory).resolve()
        if any(path.is_relative_to(root) for root in (Path("/usr"), Path("/bin"), Path("/sbin"))):
            continue
        if path.is_dir() and any(p.is_file() and os.access(p, os.X_OK) and p.name not in {"datasets", "dataformat"}
                                 for p in path.iterdir()):
            raise Unavailable("external_native_runtime")


def context(args):
    cache = store()
    settings = dict(args.setting)
    if settings["ENGINE"] != "docker":
        raise Unavailable("runtime_contract")
    native_runtime_supported()
    if (not Path(sys.executable).resolve().is_relative_to("/usr") or
            Path(shutil.which(settings["VENV_PY"]) or settings["VENV_PY"]).resolve() != Path(sys.executable).resolve()):
        raise Unavailable("native_interpreter_identity")
    if settings.get("BRAKER_BAM") or settings.get("BRAKER_PROT_SEQ") or settings.get("FUNANNOTATE_DB") not in {"", "/opt/databases"}:
        raise Unavailable("external_annotation_evidence")
    # This contract uses the immutable Docker worker and prepared sibling images.
    worker_image = image_id(os.environ["HOSTNAME"])
    images = {}
    if settings["HAS_FUNGAL_ROUTES"] == "1":
        if settings["FUNBGCEX_RUNTIME"] != "docker":
            raise Unavailable("runtime_contract")
        images["funbgcex"] = scientific_image(settings["FUNBGCEX_DOCKER_IMAGE"])
        if settings["FUNGAL_ANNOTATION_FALLBACK_NEEDED"] == "1":
            if shutil.which("funannotate") or settings["BRAKER3_ENABLED"] != "0":
                raise Unavailable("annotation_contract")
            images["funannotate"] = scientific_image(settings["FUNANNOTATE_IMAGE_URI"])
    if not shutil.which("antismash"):
        images["antismash"] = scientific_image(settings["ANTISMASH_DOCKER_IMAGE"])
    database = Path(settings["ANTISMASH_DB_DIR"])
    before = tree_stamp(database)
    digest = content_tree(database)
    after = tree_stamp(database)
    if before != after:
        raise Unavailable("database_changed")
    native_before = native_digest()
    native_runtime = native_digest(content=True)
    native_after = native_digest()
    if native_before != native_after:
        raise Unavailable("native_runtime_changed")
    record = {"source": source_digest(), "images": images, "database": digest,
              "database_stamp": after, "settings": settings, "worker_image": worker_image,
              "native_runtime": native_runtime, "native_stamp": native_after}
    write_json(args.output, record)


def inputs(args):
    files = {}
    for p in args.acquired_root.glob(args.genome_id + ".*"):
        if p.suffix.lower() in {".fna", ".fa", ".fasta", ".fsa", ".gb", ".gbk", ".gbff", ".gff", ".gff3"}:
            files[p.name] = p
    if not files:
        raise Unavailable("acquired_input")
    return files


def detection_identity(args, ctx):
    native_runtime_supported()
    accession = public_accession(args.route_manifest, args.genome_id, args.taxon)
    acquired = {n: hash_file(p) for n, p in sorted(inputs(args).items())}
    # Freeze only this accession's taxonomy/mapping, never its cohort or job paths.
    with args.route_manifest.open() as handle:
        row = next(r for r in csv.DictReader(handle, delimiter="\t") if r["genome_id"] == args.genome_id)
    row.pop("input_path_key", None)
    mapping = []
    if args.mapping.is_file():
        mapping = [r for r in args.mapping.read_text().splitlines() if r.split("\t", 1)[0] == accession]
    if (tree_stamp(Path(ctx["settings"]["ANTISMASH_DB_DIR"])) != ctx["database_stamp"] or
            source_digest() != ctx["source"] or native_digest() != ctx["native_stamp"]):
        raise Unavailable("dependency_changed")
    settings = {k: v for k, v in ctx["settings"].items() if k not in SCHEDULING_SETTINGS and k not in {
        "ANTISMASH_DB_DIR", "FUNBGCEX_DOCKER_IMAGE", "FUNANNOTATE_IMAGE_URI", "ANTISMASH_DOCKER_IMAGE",
        "HAS_FUNGAL_ROUTES", "FUNGAL_ANNOTATION_FALLBACK_NEEDED", "GENOME_PARALLELISM"}}
    images = dict(ctx["images"])
    if args.taxon == "bacteria":
        images = {k: v for k, v in images.items() if k == "antismash"}
        settings = {k: v for k, v in settings.items() if not k.startswith(("FUNANNOTATE_", "FUNBGCEX_", "BRAKER"))
                    and k not in {"WORKERS", "ANNO_CPUS", "ANNOTATION_FALLBACK_ORDER"}}
        mapping = []
    else:
        from genbank_readiness import inspect_genbank_translation_stream
        existing = any(inspect_genbank_translation_stream(io.StringIO(regular_bytes(p).decode())).usable_translated_cds
                       for p in inputs(args).values() if p.suffix in {".gb", ".gbk", ".gbff"})
        if existing:
            images.pop("funannotate", None)
            # No annotator is invoked for complete existing CDS annotations.
            settings.pop("ANNO_CPUS", None)
        elif "funannotate" not in images:
            raise Unavailable("annotation_identity_missing")
    return {"schema": SCHEMA, "contract": CONTRACT_DETECTION, "accession": accession,
            "genome_sha256": sha256(canonical(acquired)), "route": {"taxon": args.taxon, "annotation": "per-genome"},
            "source_sha256": ctx["source"], "runtime_sha256": ctx["native_runtime"],
            "tools": {"pipeline": ctx["source"], "native": ctx["native_runtime"]}, "containers": images or "not-used",
            "databases": {"antismash": ctx["database"]},
            "models": {"embedded": sha256(canonical({"native": ctx["native_runtime"], "images": images}))},
            "parameters": {"configuration_sha256": sha256(canonical([settings, row, mapping])),
                           "partition_sha256": PARTITION_SHA256,
                           "genome_label_sha256": sha256(args.genome_id.encode())}}


def replacements(args):
    return {str(args.results): "__CW_RESULTS__", str(args.work): "__CW_WORK__",
            str(args.acquired_root): "__CW_INPUT__"}


def prepare(args):
    if forced() or cancelled():
        raise Unavailable("forced_or_cancelled")
    if any((args.results / tool / args.genome_id).exists() for tool in ("antismash", "funbgcex")) or (
            args.results / "input_gbks" / (args.genome_id + ".gbk")).exists():
        raise Unavailable("existing_job_output")
    ctx = json.loads(regular_bytes(args.context, 1024**2))
    identity = detection_identity(args, ctx)
    cache = store()
    path = claim_path(cache, identity_key(identity))
    write_json(args.state, {"identity": identity, "context": ctx})
    print(path)


def unchanged(args, state):
    return not cancelled() and not forced() and detection_identity(args, state["context"]) == state["identity"]


def detection(args):
    state = json.loads(regular_bytes(args.state, 1024**2))
    identity, cache = state["identity"], store()
    validate = lambda p: validate_bundle(p, identity)
    if not unchanged(args, state):
        raise Unavailable("identity_changed")
    if args.action == "restore":
        payload, reason, manifest = metadata_operation(lambda: cache.lookup(identity, validate))
        if not payload:
            detection_provenance(args, state, "miss", reason)
            return 1
        files = validate(payload)
        install(files, args.results, replacements(args))
        try:
            if not unchanged(args, state):
                raise Unavailable("identity_changed")
            outcome = json.loads(files["outcome.json"])
            fasta = next((p for p in inputs(args).values() if p.suffix in {".fna", ".fa", ".fasta", ".fsa"}), "")
            row = [args.genome_id, str(fasta), str(args.results / "input_gbks" / (args.genome_id + ".gbk")),
                   outcome["gbk_status"], "skipped_done", "not_applicable_taxon" if args.taxon == "bacteria" else "skipped_done",
                   args.taxon, outcome["prediction_method"], outcome["detector_profile"], outcome["funbgcex_applicability"]]
            args.row.write_text("\t".join(row) + "\n")
            # Markers are freshly generated job state and are never shared.
            for tool in (["antismash"] if args.taxon == "bacteria" else ["antismash", "funbgcex"]):
                (args.results / tool / args.genome_id / ".done").touch()
            detection_provenance(args, state, "hit", "verified", manifest=manifest,
                                 execution=json.loads(files["execution.json"]))
        except BaseException:
            for n in files:
                if n not in {"outcome.json", "execution.json"}:
                    (args.results / n).unlink(missing_ok=True)
            for tool in ("antismash", "funbgcex"):
                (args.results / tool / args.genome_id / ".done").unlink(missing_ok=True)
            args.row.unlink(missing_ok=True)
            raise
        return 0
    row = args.row.read_text().rstrip("\n").split("\t")
    if len(row) != 10 or row[0] != args.genome_id:
        raise Unavailable("result_row")
    outcome = dict(zip(["gbk_status", "antismash_status", "funbgcex_status", "taxon_group", "prediction_method", "detector_profile", "funbgcex_applicability"], row[3:]))
    files = {"outcome.json": canonical(outcome), "execution.json": canonical({
        "worker_image": state["context"].get("producer_image", state["context"]["worker_image"]), "native_runtime_sha256": identity["runtime_sha256"],
        "producer_source_sha256": identity["source_sha256"],
        "scheduling": scheduling_record(state["context"]["settings"])})}
    versions = producer_tool_versions(identity, outcome, args)
    if versions:
        execution = json.loads(files["execution.json"])
        execution["tool_versions"] = versions
        files["execution.json"] = canonical(execution)
    for relative in ["input_gbks/" + args.genome_id + ".gbk", "antismash/" + args.genome_id] + (
            ["funbgcex/" + args.genome_id] if args.taxon == "fungi" else []):
        path = args.results / relative
        selected = inventory(path) if path.is_dir() else {path.name: path}
        for _, p in selected.items():
            if p.name == ".done" or p.suffix.lower() == ".log" or p.name in {"log.txt", "timings.json"}:
                continue
            data = regular_bytes(p, allow_empty=True)
            files[p.relative_to(args.results).as_posix()] = portable(data, replacements(args))
    if args.taxon == "bacteria":
        p = args.results / "summary_tables/bacterial_record_maps" / (args.genome_id + ".record_map.tsv")
        # This job-specific destination is reconstructed separately on restore.
        files[p.relative_to(args.results).as_posix()] = regular_bytes(p)
    payload = {"bundle.tar": pack(files)}
    population = metadata_operation(lambda: cache.publish(identity, payload, validate, can_publish=lambda: unchanged(args, state)))
    manifest = None
    if population in {"published", "duplicate"}:
        _, _, manifest = metadata_operation(lambda: cache.lookup(identity, validate))
    detection_provenance(args, state, "miss", "computed", population, manifest,
                         execution=json.loads(files["execution.json"]))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["retrieve", "context", "prepare", "restore", "publish"])
    for name in ("route-manifest", "destination", "provenance", "output", "context", "state", "acquired-root", "mapping", "results", "work", "row"):
        parser.add_argument("--" + name, type=Path)
    for name in ("accession", "genome-id", "taxon", "datasets"):
        parser.add_argument("--" + name)
    parser.add_argument("--setting", nargs=2, action="append", default=[])
    args, command = parser.parse_known_args()
    args.command = command[1:] if command[:1] == ["--"] else command
    try:
        if args.action == "retrieve":
            return retrieve(args)
        if args.action == "context":
            context(args)
        elif args.action == "prepare":
            prepare(args)
        else:
            return detection(args)
        return 0
    except Exception as exc:
        if args.provenance:
            identity = None
            if args.action in {"restore", "publish"} and args.state:
                try:
                    identity = json.loads(regular_bytes(args.state, 16 * 1024 * 1024))["identity"]
                    identity_key(identity)
                except Exception:
                    identity = None
            provenance(args.provenance, identity, "miss", str(exc) if isinstance(exc, Unavailable) else "cache_unavailable", "rejected")
        # Cache rejection is an ordinary miss; scientific computation stays in the runner.
        return 1


if __name__ == "__main__":
    sys.exit(main())
