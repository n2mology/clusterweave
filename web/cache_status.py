"""Bounded cache metadata projections for operators and individual job owners."""
from __future__ import annotations

from collections import OrderedDict
import csv
import hashlib
import io
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import threading
import time

try:
    from accession_catalog import ACCESSION, CONTRACTS, DIGEST, MAX_ROWS
except ImportError:  # pragma: no cover - package-style imports
    from .accession_catalog import ACCESSION, CONTRACTS, DIGEST, MAX_ROWS

MAX_RECORDS = 256
MAX_JOBS = 1024
MAX_BYTES = 65536
REASONS = {
    "verified", "absent", "quarantined", "forced", "disabled", "computed", "cancelled",
    "unavailable_or_ineligible", "identity_changed", "forced_or_cancelled", "existing_job_output",
    "runtime_contract", "accession_route", "accession_ambiguous", "external_native_runtime",
    "external_annotation_evidence", "annotation_contract", "annotation_identity_missing",
    "dependency_changed", "database_changed", "native_runtime_changed", "storage_ownership",
    "storage_overlap", "capacity", "busy", "claim_timeout", "bundle_private_context",
    "payload_private_or_inventory", "detection_incomplete", "annotation_incomplete",
}
POPULATIONS = {"published", "duplicate", "not-attempted", "skipped", "rejected", "capacity",
               "cancelled_or_changed", "conflicting_outputs", "validation_or_store_failure"}


def read_bytes(path: Path, base: Path, limit=MAX_BYTES):
    path.relative_to(base)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("metadata_link")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise ValueError("metadata_size_or_type")
        with os.fdopen(fd, "rb", closefd=False) as f:
            raw = f.read(limit + 1)
        after = os.fstat(fd)
        if (len(raw) != before.st_size or len(raw) > limit
                or (before.st_ino, before.st_mtime_ns, before.st_ctime_ns, before.st_size) !=
                (after.st_ino, after.st_mtime_ns, after.st_ctime_ns, after.st_size)):
            raise ValueError("metadata_changed")
        return raw
    finally:
        os.close(fd)


def result_root(job, base):
    rel = PurePosixPath(str(job.get("result_root") or ""))
    if str(rel) != "." and not rel.is_absolute() and ".." not in rel.parts:
        path = base.joinpath(*rel.parts)
        if path.is_dir() and not any(p.is_symlink() for p in (path, *path.parents)):
            return path
    # Older records may omit the result pointer. Never follow arbitrary paths.
    directory = base / "data/results"
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        return None
    candidates = list(itertools.islice(directory.glob("*"), 2))
    if len(candidates) == 1 and candidates[0].is_dir() and not any(
            p.is_symlink() for p in (candidates[0], *candidates[0].parents)):
        return candidates[0]
    return None


def cache_records(result, base):
    directory = result / "reproducibility/accession_cache"
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("metadata_link")
    count = 0
    for path in directory.glob("*.json"):
        count += 1
        if count > MAX_RECORDS:
            raise ValueError("metadata_record_limit")
        raw = read_bytes(path, base)
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise ValueError("metadata_record_schema")
        record["_catalog_label"] = None
        record["_catalog_stage"] = None
        for suffix, stage in ((".detection.json", "detection"), (".retrieval.json", "retrieval"),
                              (".bacteria.json", "preparation"), (".fungi.json", "preparation")):
            if path.name.endswith(suffix):
                record["_catalog_label"] = path.name.removesuffix(suffix)
                record["_catalog_stage"] = stage
        yield record


def route_accessions(result, base):
    try:
        text = read_bytes(result / "summary_tables/genome_taxon_manifest.tsv", base, 1024 * 1024).decode()
    except FileNotFoundError:
        return {}
    result = {}
    for row in itertools.islice(csv.DictReader(io.StringIO(text), delimiter="\t"), MAX_RECORDS):
        accession = row.get("source_accession", "")
        if (ACCESSION.fullmatch(accession) and row.get("input_key") == accession and row.get("taxon_source") == "ncbi"
                and row.get("taxon_group") in {"bacteria", "fungi"}
                and row.get("route_status") in {"accepted", "routed", "resolved"}):
            result[row.get("genome_id")] = accession
    return result


def owner_provenance(job, base):
    result = result_root(job, base)
    records = []
    complete = True
    if result is not None:
        try:
            accessions = route_accessions(result, base)
            for r in cache_records(result, base):
                identity = r.get("identity") or {}
                if not isinstance(identity, dict):
                    continue
                contract = identity.get("contract")
                contract = contract if isinstance(contract, str) and contract in CONTRACTS else None
                stage = CONTRACTS.get(contract) or r.get("_catalog_stage")
                if stage is None:
                    continue
                accession = identity.get("accession") or accessions.get(r.get("_catalog_label"))
                if not isinstance(accession, str) or len(accession) > 64 or not ACCESSION.fullmatch(accession):
                    continue
                population = r.get("population", "not-attempted")
                if isinstance(population, str) and population.startswith("rejected:"):
                    population = "rejected"
                if population not in POPULATIONS:
                    population = "unknown"
                reason = r.get("reason")
                reason = reason if isinstance(reason, str) and reason in REASONS else "unavailable_or_ineligible"
                records.append({"accession": accession, "stage": stage, "contract": contract,
                                "identity_recorded": bool(identity),
                                "outcome": "hit" if r.get("outcome") == "hit" else "miss",
                                "reason": reason, "population": population})
        except (OSError, ValueError, TypeError):
            complete = False
    records.sort(key=lambda r: (r["accession"], r["stage"], r["contract"] or ""))
    return {"schema": 1, "scope": "this_job", "records_complete": complete, "records": records,
            "status": "recorded" if records else "not_recorded"}


def job_inventory(jobs, job_directory):
    """Record public accession membership without retaining job identities."""
    legacy, active, failures = set(), set(), set()
    complete = True
    for index, job in enumerate(jobs):
        if index >= MAX_JOBS or len(legacy) + len(active) + len(failures) >= MAX_ROWS:
            complete = False
            break
        try:
            if job.get("_catalog_incomplete"):
                complete = False
                continue
            base = job_directory(str(job["id"]))
            result = result_root(job, base)
            if result is None:
                continue
            records = list(cache_records(result, base))
            recorded = set()
            for r in records:
                identity = r.get("identity") or {}
                if not isinstance(identity, dict):
                    continue
                accession = identity.get("accession")
                contract = identity.get("contract")
                if not isinstance(accession, str) or not ACCESSION.fullmatch(accession) or contract not in CONTRACTS:
                    continue
                stage = CONTRACTS[contract]
                if stage == "detection":
                    recorded.add(accession)
                key = r.get("key")
                if (isinstance(key, str)
                        and DIGEST.fullmatch(key)
                        and hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"),
                                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest() == key):
                    if job.get("status") == "running" and r.get("outcome") == "miss" and r.get("population") == "not-attempted":
                        active.add((key, accession, stage))
                    elif r.get("population") in {"rejected", "validation_or_store_failure", "capacity", "conflicting_outputs"}:
                        code = r.get("reason") if r.get("population") == "rejected" else r.get("population")
                        code = code if isinstance(code, str) and (code in REASONS or code in {"capacity", "conflicting_outputs"}) else "population_unclassified"
                        failures.add((key, accession, stage, code))
            if job.get("status") != "success":
                continue
            route = result / "summary_tables/genome_taxon_manifest.tsv"
            try:
                text = read_bytes(route, base, 1024 * 1024).decode()
            except FileNotFoundError:
                continue
            for number, row in enumerate(csv.DictReader(io.StringIO(text), delimiter="\t")):
                if number >= MAX_RECORDS:
                    complete = False
                    break
                accession = row.get("source_accession", "")
                if (ACCESSION.fullmatch(accession) and row.get("input_key") == accession
                        and row.get("taxon_source") == "ncbi" and row.get("taxon_group") in {"bacteria", "fungi"}
                        and row.get("route_status") in {"accepted", "routed", "resolved"}
                        and accession not in recorded):
                    legacy.add((accession, "detection"))
        except (OSError, ValueError, TypeError, KeyError):
            complete = False
    return legacy, active, failures, complete


def catalog_jobs(data_dir):
    """Read bounded summaries rather than full result inventories or logs."""
    directory = data_dir / "jobs"
    if not directory.is_dir() or directory.is_symlink():
        return
    for base in itertools.islice(directory.iterdir(), MAX_JOBS + 1):
        if base.is_symlink() or not base.is_dir():
            yield {"_catalog_incomplete": True}
            continue
        summary = base / "job_summary.v1.json"
        source = summary if summary.is_file() else base / "job.json"
        try:
            job = json.loads(read_bytes(source, directory))
            if not isinstance(job, dict) or job.get("id") != base.name:
                raise ValueError("job_summary")
            yield job
        except (OSError, ValueError, TypeError):
            yield {"_catalog_incomplete": True}


def refresh_catalog(jobs, job_directory):
    root = os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_ROOT")
    if not root:
        return
    sys.path.insert(0, str(Path(os.environ.get("CLUSTERWEAVE_ROOT", Path(__file__).resolve().parents[1])) / "bin"))
    from accession_cache import Store
    legacy, active, failures, complete = job_inventory(jobs, job_directory)
    store = Store(Path(root), max_bytes=int(os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_MAX_BYTES", 10 * 1024**3)),
                  max_entries=int(os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_MAX_ENTRIES", 256)),
                  max_age_seconds=int(os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_MAX_AGE_SECONDS", 30 * 86400)))
    store.reconcile_catalog(legacy=legacy, active=active, failures=failures, complete=complete)


class RequestBudget:
    """Bound metadata requests after authentication, without storing tokens."""
    def __init__(self, *, limit=30, window=60, capacity=1024):
        self.limit, self.window, self.capacity = limit, window, capacity
        self.lock = threading.Lock()
        self.principals = OrderedDict()
        self.slots = threading.BoundedSemaphore(2)

    def take(self, principal):
        now = time.monotonic()
        with self.lock:
            started, count = self.principals.get(principal, (now, 0))
            if now - started >= self.window:
                started, count = now, 0
            if count >= self.limit:
                return False
            self.principals[principal] = (started, count + 1)
            self.principals.move_to_end(principal)
            while len(self.principals) > self.capacity:
                self.principals.popitem(last=False)
        return True
