#!/usr/bin/env python3
"""Prepare isolated, antiSMASH-safe GenBank inputs.

The source GenBank remains unchanged.  Sanitization is limited to the copy
consumed by antiSMASH, and record splitting guarantees that each shard parses
only the record it was assigned.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import tempfile

from Bio import SeqIO
from Bio.SeqFeature import CompoundLocation


def location_key(location: object) -> str:
    if isinstance(location, CompoundLocation):
        operator = getattr(location, "operator", "join") or "join"
        return f"{operator}(" + ",".join(location_key(part) for part in location.parts) + ")"
    ref = getattr(location, "ref", None) or ""
    ref_db = getattr(location, "ref_db", None) or ""
    strand = getattr(location, "strand", None)
    return f"{ref}:{ref_db}:{int(location.start)}:{int(location.end)}:{strand}"


def has_translation(feature: object) -> bool:
    qualifiers = getattr(feature, "qualifiers", None) or {}
    return any(str(value).strip() for value in qualifiers.get("translation", []))


def qualifier_label(feature: object) -> str:
    qualifiers = getattr(feature, "qualifiers", None) or {}
    for key in ("locus_tag", "protein_id", "ID", "gene"):
        for value in qualifiers.get(key, []):
            text = str(value).strip()
            if text:
                return f"{key}:{text}"
    return "unlabeled"


def invalid_non_cds_compound(feature: object) -> bool:
    location = getattr(feature, "location", None)
    if getattr(feature, "type", "") == "CDS" or not isinstance(location, CompoundLocation):
        return False
    grouped: dict[tuple[str, str, object], list[tuple[int, int]]] = defaultdict(list)
    for part in location.parts:
        key = (
            str(getattr(part, "ref", None) or ""),
            str(getattr(part, "ref_db", None) or ""),
            getattr(part, "strand", None),
        )
        grouped[key].append((int(part.start), int(part.end)))
    for intervals in grouped.values():
        intervals.sort()
        previous_end = -1
        for start, end in intervals:
            if start < previous_end:
                return True
            previous_end = max(previous_end, end)
    return False


def sanitize(source: Path, destination: Path, genome_id: str) -> dict[str, object]:
    records = []
    total_cds = 0
    duplicate_groups: set[tuple[str, str]] = set()
    dropped_duplicate_cds = 0
    dropped_invalid_non_cds = 0
    examples: list[str] = []
    for record in SeqIO.parse(source, "genbank"):
        record.annotations.setdefault("molecule_type", "DNA")
        keep_by_key: dict[tuple[str, str], int] = {}
        dropped_indexes: set[int] = set()
        for index, feature in enumerate(record.features or []):
            if invalid_non_cds_compound(feature):
                dropped_indexes.add(index)
                dropped_invalid_non_cds += 1
                if len(examples) < 5:
                    examples.append(
                        f"record={record.id or record.name or 'record'} "
                        f"type={feature.type} label={qualifier_label(feature)}"
                    )
                continue
            if feature.type != "CDS":
                continue
            total_cds += 1
            key = (record.id or record.name or "record", location_key(feature.location))
            if key not in keep_by_key:
                keep_by_key[key] = index
                continue
            duplicate_groups.add(key)
            kept_index = keep_by_key[key]
            if not has_translation(record.features[kept_index]) and has_translation(feature):
                dropped_indexes.add(kept_index)
                keep_by_key[key] = index
            else:
                dropped_indexes.add(index)
            dropped_duplicate_cds += 1
        if dropped_indexes:
            record.features = [
                feature for index, feature in enumerate(record.features or [])
                if index not in dropped_indexes
            ]
        records.append(record)
    destination.parent.mkdir(parents=True, exist_ok=True)
    SeqIO.write(records, destination, "genbank")
    return {
        "genome": genome_id,
        "records": len(records),
        "cds": total_cds,
        "duplicate_location_groups": len(duplicate_groups),
        "dropped_duplicate_cds": dropped_duplicate_cds,
        "dropped_invalid_non_cds_compound_features": dropped_invalid_non_cds,
        "examples": examples,
    }


def split_records(source: Path, manifest: Path) -> int:
    requested: dict[str, Path] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record_id, separator, output = line.partition("\t")
        if not separator or not record_id or not output or record_id in requested:
            raise ValueError("invalid or duplicate record-split manifest row")
        requested[record_id] = Path(output)
    found: set[str] = set()
    for record in SeqIO.parse(source, "genbank"):
        record_id = str(record.id or record.name or "").strip()
        if record_id not in requested:
            continue
        if record_id in found:
            raise ValueError(f"duplicate requested GenBank record: {record_id}")
        destination = requested[record_id]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.name}.", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            SeqIO.write([record], handle, "genbank")
        temporary.replace(destination)
        found.add(record_id)
    missing = sorted(set(requested) - found)
    if missing:
        raise ValueError("requested GenBank records not found: " + ", ".join(missing))
    return len(found)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    sanitize_parser = subparsers.add_parser("sanitize")
    sanitize_parser.add_argument("source", type=Path)
    sanitize_parser.add_argument("destination", type=Path)
    sanitize_parser.add_argument("--genome-id", default="genome")
    split_parser = subparsers.add_parser("split-records")
    split_parser.add_argument("source", type=Path)
    split_parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "sanitize":
            print(json.dumps(sanitize(args.source, args.destination, args.genome_id), sort_keys=True))
        else:
            print(f"split_records={split_records(args.source, args.manifest)}")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"antiSMASH input preparation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
