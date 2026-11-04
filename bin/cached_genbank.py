#!/usr/bin/env python3
"""Prepare accession-local GenBank files with optional verified byte reuse."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import locale
import os
from pathlib import Path
import re
import sys
import sysconfig

from accession_cache import (ACCESSION, CONTRACTS, SCHEMA, Store, Unavailable,
                             canonical, identity_key, materialize, regular_bytes,
                             reject_symlink_parents, sha256)
import sanitize_bacterial_genbank as bacterial

ROOT = Path(__file__).resolve().parents[1]
for module_root in (Path("/app"), ROOT / "web"):
    if module_root.is_dir():
        sys.path.insert(0, str(module_root))
import genbank_readiness
from genbank_readiness import inspect_genbank_translation_stream  # noqa: E402

# Metadata copied from public records must still be free of execution context.
PRIVATE = re.compile(
    rb"(?:file://|(?<![A-Za-z0-9])/[A-Za-z0-9_.~-]+/|[A-Za-z]:\\"
    rb"|\b(?:[a-z]+[_-])?(?:token|secret|credentials?|api[_-]?key|job[_-]?id|password|authorization|bearer)\b"
    rb"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b)", re.I)


# NCBI yeast records cite this public homepage in their COMMENT metadata.
SGD_REFERENCE = re.compile(rb"https?://www\.yeastgenome\.org/(?=[\s\"<>]|$)")


def contains_private_context(data: bytes) -> bool:
    return bool(PRIVATE.search(SGD_REFERENCE.sub(b"SGD reference", data)))


def digest_paths(paths: dict[str, Path]) -> str:
    digest = hashlib.sha256()
    for name, path in sorted(paths.items()):
        reject_symlink_parents(path)
        digest.update(canonical([name, sha256(regular_bytes(path, allow_empty=True))]))
    if not paths:
        raise Unavailable("identity_empty")
    return digest.hexdigest()


def tree_paths(prefix: str, root: Path) -> dict[str, Path]:
    paths = {}
    def failed_walk(error):
        raise error
    for directory, names, files in os.walk(root, onerror=failed_walk):
        names[:] = sorted(n for n in names if n not in {"__pycache__", "site-packages", "dist-packages", "test", "tests"})
        if any((Path(directory) / name).is_symlink() for name in names):
            raise Unavailable("runtime_directory_link")
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix in {".py", ".so", ".zip"}:
                paths[prefix + "/" + path.relative_to(root).as_posix()] = path
    return paths


def runtime_digest(operation: str) -> str:
    # Hash installed code, not version labels, mtimes, image tags, or host paths.
    paths = {"python": Path(sys.executable).resolve()}
    paths.update(tree_paths("stdlib", Path(sysconfig.get_path("stdlib"))))
    if operation == "fungi":
        import Bio
        from Bio import SeqIO  # noqa: F401
        paths.update(tree_paths("Bio", Path(Bio.__file__).parent))
        if "numpy" in sys.modules:
            import numpy
            paths.update(tree_paths("numpy", Path(numpy.__file__).parent))
    # Include the interpreter's shared library and loaded native dependencies.
    libraries = set()
    for line in Path("/proc/self/maps").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 6 and fields[-1].startswith("/") and ".so" in fields[-1]:
            libraries.add(Path(fields[-1]).resolve())
    for index, path in enumerate(sorted(libraries, key=lambda p: (p.name, sha256(regular_bytes(p))))):
        paths[f"native/{index}/{path.name}"] = path
    return sha256(canonical({"files": digest_paths({name: path.resolve() for name, path in paths.items()}), "python": sys.version,
                             "byteorder": sys.byteorder, "platform": sys.platform,
                             "encoding": locale.getencoding(), "utf8_mode": sys.flags.utf8_mode}))


def public_accession(manifest: Path, genome_id: str, taxon: str) -> str:
    reject_symlink_parents(manifest)
    reader = csv.DictReader(io.StringIO(regular_bytes(manifest, 8 * 1024**2).decode()), delimiter="\t")
    fields = reader.fieldnames or []
    required = {"genome_id", "input_key", "source_accession", "taxon_source", "taxon_group", "route_status"}
    if len(fields) != len(set(fields)) or not required.issubset(fields):
        raise Unavailable("accession_route_schema")
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise Unavailable("accession_route_schema")
    matched = [row for row in rows if row.get("genome_id") == genome_id]
    if len(matched) != 1:
        raise Unavailable("accession_route")
    row = matched[0]
    accession = row.get("source_accession", "").strip().upper()
    if (not ACCESSION.fullmatch(accession) or row.get("input_key", "").strip().upper() != accession
            or row.get("taxon_group") != taxon or row.get("taxon_source") != "ncbi"
            or row.get("route_status") not in {"accepted", "routed", "resolved"}):
        raise Unavailable("accession_route")
    return accession


def make_identity(args) -> dict:
    accession = public_accession(args.route_manifest, args.genome_id,
                                 "bacteria" if args.operation == "bacteria" else "fungi")
    reject_symlink_parents(args.input)
    # Require the acquired file to belong to the routed accession input tree.
    reject_symlink_parents(args.acquired_root)
    if not args.input.resolve().is_relative_to(args.acquired_root.resolve()):
        raise Unavailable("acquired_input")
    source_paths = {name: ROOT / name for name in (
        "bin/accession_cache.py", "bin/cached_genbank.py", "bin/sanitize_bacterial_genbank.py",
        "bin/annotation_genbank.py", "web/genbank_readiness.py", "run_annotation_and_detection.sh")}
    source_paths["web/genbank_readiness.py"] = Path(genbank_readiness.__file__)
    source = digest_paths(source_paths)
    runtime = runtime_digest(args.operation)
    bacteria = args.operation == "bacteria"
    identity = {
        "schema": SCHEMA, "contract": "bacterial-genbank-v1" if bacteria else "fungal-existing-cds-v1",
        "accession": accession, "genome_sha256": sha256(regular_bytes(args.input)),
        "route": {"taxon": "bacteria" if bacteria else "fungi", "annotation": "sequence-only" if bacteria else "existing-cds"},
        "source_sha256": source, "runtime_sha256": runtime,
        "tools": {"python": runtime, "preparation": source},
        "containers": "not-used", "databases": "not-used", "models": "not-used",
        "parameters": {"genome_label_sha256": sha256(args.genome_id.encode()),
                       "min_record_bp": args.min_record_bp if bacteria else 0,
                       "max_record_bp": args.max_record_bp if bacteria else 0},
    }
    identity_key(identity)
    return identity


def validate_payload(payload: dict[str, bytes], operation: str, *, bounds: tuple[int, int] | None = None) -> None:
    contract = "bacterial-genbank-v1" if operation == "bacteria" else "fungal-existing-cds-v1"
    if set(payload) != CONTRACTS[contract] or any(contains_private_context(data) for data in payload.values()):
        raise Unavailable("payload_private_or_inventory")
    text = payload["prepared.gbk"].decode("utf-8")
    if operation == "fungi":
        if not inspect_genbank_translation_stream(io.StringIO(text)).usable_translated_cds:
            raise Unavailable("payload_cds")
        from Bio import SeqIO
        records = list(SeqIO.parse(io.StringIO(text), "genbank"))
        if not records or any(not len(record.seq) for record in records):
            raise Unavailable("payload_records")
    else:
        blocks = text.split("//\n")
        if blocks[-1] or len(blocks) < 2:
            raise Unavailable("payload_records")
        records = [bacterial._genbank_record(block.splitlines(), i + 1) for i, block in enumerate(blocks[:-1])]
        ids = payload["record_ids.txt"].decode("utf-8").splitlines()
        if ids != [record.original_id for record in records] or len(set(ids)) != len(ids):
            raise Unavailable("payload_ids")
        # Feature-free records must match the canonical writer byte for byte.
        if text != "".join(bacterial.format_record(r.original_id, r.sequence, r.topology) for r in records):
            raise Unavailable("payload_genbank")
        reader = csv.DictReader(io.StringIO(payload["record_map.tsv"].decode()), delimiter="\t")
        if reader.fieldnames != ["input_order", "original_record_id", "sanitized_record_id", "sequence_length_bp", "topology", "status", "reason"]:
            raise Unavailable("payload_map_schema")
        rows = list(reader)
        for index, row in enumerate(rows, 1):
            if (None in row or any(value is None for value in row.values())
                    or row["input_order"] != str(index) or not row["original_record_id"]
                    or row["status"] not in {"eligible", "excluded_below_minimum"}
                    or row["topology"] not in {"linear", "circular"}
                    or not row["sequence_length_bp"].isdigit() or int(row["sequence_length_bp"]) < 1):
                raise Unavailable("payload_map_rows")
            if bounds:
                size = int(row["sequence_length_bp"])
                eligible = bounds[0] <= size <= bounds[1]
                if (eligible != (row["status"] == "eligible") or size > bounds[1]
                        or row["reason"] != ("" if eligible else f"length below minimum {bounds[0]} bp")):
                    raise Unavailable("payload_map_bounds")
        expected = [row for row in rows if row.get("status") == "eligible"]
        if [row.get("sanitized_record_id") for row in expected] != ids:
            raise Unavailable("payload_map")
        if any(row.get("sequence_length_bp") != str(len(record.sequence))
               or row.get("topology") != record.topology for row, record in zip(expected, records)):
            raise Unavailable("payload_map")


def destinations(args) -> dict[str, Path]:
    result = {"prepared.gbk": args.output}
    if args.operation == "bacteria":
        result.update({"record_map.tsv": args.record_map, "record_ids.txt": args.record_ids})
    return result


def cancelled() -> bool:
    marker = os.environ.get("CLUSTERWEAVE_CANCEL_FILE", "")
    return bool(marker and Path(marker).exists())


def configured_store(root: str) -> Store:
    return Store(Path(root), max_bytes=int(os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_MAX_BYTES", 10 * 1024**3)),
                 max_entries=int(os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_MAX_ENTRIES", 256)),
                 max_age_seconds=int(os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_MAX_AGE_SECONDS", 30 * 86400)))


def print_bacterial_summary(args, summary: dict) -> None:
    print(f"BACTERIAL_SANITIZE genome={bacterial.safe_token(args.genome_id, 'genome')} "
          f"format={summary['input_format']} records_total={summary['records_total']} "
          f"records_eligible={summary['records_eligible']} records_excluded={summary['records_excluded']}")


def compute(args) -> None:
    if args.operation == "bacteria":
        summary = bacterial.sanitize(args.input, args.output, args.record_map, args.record_ids,
                                     args.genome_id, args.min_record_bp, args.max_record_bp)
        print_bacterial_summary(args, summary)
    else:
        from annotation_genbank import normalize_headers
        total, changed = normalize_headers(args.input, args.output)
        print(f"normalized_records={total} changed_fields={changed}")


def run(args) -> dict:
    provenance = {"schema": SCHEMA, "outcome": "miss", "reason": "disabled", "key": None,
                  "accession": None, "identity": None, "entry_manifest": None, "population": "skipped", "validation": "not-run"}
    if cancelled():
        raise InterruptedError("Preparation cancelled")
    root = os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_ROOT", "")
    forced = os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_FORCE_MISS", "0") == "1" or os.environ.get("FORCE", "0") == "1"
    identity = store = None
    validate = lambda payload: validate_payload(payload, args.operation, bounds=(args.min_record_bp, args.max_record_bp))
    if forced:
        provenance["reason"] = "forced"
    elif root:
        try:
            store = configured_store(root)
            # No store may be the input tree, a job destination, or their ancestor/descendant.
            cache_root = store.root.resolve()
            data_root = os.environ.get("DATA_DIR", "")
            if cache_root.is_relative_to(ROOT) or (data_root and cache_root.is_relative_to(Path(data_root).resolve())):
                raise Unavailable("storage_ownership")
            for path in (args.acquired_root, *[p.parent for p in destinations(args).values()]):
                resolved = path.resolve()
                if cache_root.is_relative_to(resolved) or resolved.is_relative_to(cache_root):
                    raise Unavailable("storage_overlap")
            identity = make_identity(args)
            provenance.update({"key": identity_key(identity), "accession": identity["accession"], "identity": identity})
            payload, reason, manifest = store.lookup(identity, validate)
            provenance["reason"] = reason
            if payload is not None:
                # Recheck identity before copying, including acquired bytes and installed code.
                if cancelled() or make_identity(args) != identity:
                    raise Unavailable("identity_changed")
                materialize(payload, destinations(args))
                if cancelled() or make_identity(args) != identity:
                    raise Unavailable("identity_changed")
                provenance.update({"outcome": "hit", "entry_manifest": manifest, "validation": "verified-hit"})
                if args.operation == "bacteria":
                    rows = list(csv.DictReader(io.StringIO(payload["record_map.tsv"].decode()), delimiter="\t"))
                    with args.input.open(encoding="utf-8-sig") as handle:
                        first = next(line.strip() for line in handle if line.strip())
                    eligible = sum(row["status"] == "eligible" for row in rows)
                    print_bacterial_summary(args, {"input_format": "fasta" if first.startswith(">") else "genbank",
                                                   "records_total": len(rows), "records_eligible": eligible,
                                                   "records_excluded": len(rows) - eligible})
                return provenance
        except Exception:
            provenance.update({"outcome": "miss", "entry_manifest": None, "validation": "not-run"})
            provenance["reason"] = "unavailable_or_ineligible"
            store = None
    # Normal failures propagate; cache failures never turn a failed preparation into success.
    if cancelled():
        raise InterruptedError("Preparation cancelled")
    compute(args)
    if store is not None and identity is not None:
        try:
            if make_identity(args) != identity:
                raise Unavailable("identity_changed")
            payload = {name: regular_bytes(path) for name, path in destinations(args).items()}
            def unchanged():
                return (not cancelled() and make_identity(args) == identity
                        and all(regular_bytes(path) == payload[name] for name, path in destinations(args).items()))
            provenance["population"] = store.publish(identity, payload, validate, can_publish=unchanged)
            provenance["validation"] = "verified-produced"
            if provenance["population"] in {"published", "duplicate"}:
                provenance["entry_manifest"] = {
                    "schema": SCHEMA, "key": identity_key(identity), "identity": identity,
                    "files": {name: {"bytes": len(data), "sha256": sha256(data)} for name, data in payload.items()},
                }
        except Exception:
            provenance["population"] = "validation_or_store_failure"
            provenance["validation"] = "rejected"
    return provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("bacteria", "fungi", "inspect", "delete"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--record-map", type=Path)
    parser.add_argument("--record-ids", type=Path)
    parser.add_argument("--genome-id")
    parser.add_argument("--route-manifest", type=Path)
    parser.add_argument("--acquired-root", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--min-record-bp", type=int, default=1000)
    parser.add_argument("--max-record-bp", type=int, default=50_000_000)
    parser.add_argument("--key")
    args = parser.parse_args(argv)
    if args.operation in {"inspect", "delete"}:
        root = os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_ROOT")
        if not root or (args.operation == "delete" and not args.key):
            parser.error("a separate cache root and, for deletion, an exact key are required")
        try:
            print(json.dumps(configured_store(root).inspect(delete=args.key if args.operation == "delete" else None), sort_keys=True))
        except (OSError, ValueError):
            print("ERROR: cache inspection unavailable", file=sys.stderr)
            return 2
        return 0
    if not all((args.input, args.output, args.genome_id, args.route_manifest, args.acquired_root)):
        parser.error("input, output, genome ID, route manifest, and acquired root are required")
    if args.operation == "bacteria" and not all((args.record_map, args.record_ids)):
        parser.error("bacterial preparation requires record map and record IDs")
    if not 1 <= args.min_record_bp <= args.max_record_bp:
        parser.error("invalid record size bounds")
    try:
        provenance = run(args)
    except (OSError, ValueError, ImportError) as exc:
        print(f"ERROR: GenBank preparation failed: {exc}", file=sys.stderr)
        return 2
    if args.provenance:
        try:
            materialize({"provenance": canonical(provenance)}, {"provenance": args.provenance})
        except (OSError, ValueError):
            print("WARNING: accession cache provenance unavailable", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
