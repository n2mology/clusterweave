#!/usr/bin/env python3
"""Apply the annotation runner's canonical GenBank transformations."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
from pathlib import Path
import re

from Bio import SeqIO


def backfill_translations(source: Path, destination: Path) -> None:
    records = []
    for record in SeqIO.parse(source, "genbank"):
        record.annotations.setdefault("molecule_type", "DNA")
        for feature in record.features:
            if feature.type != "CDS":
                continue
            qualifiers = feature.qualifiers or {}
            translations = qualifiers.get("translation", [])
            if any(str(translation).strip() for translation in translations):
                continue

            cds_sequence = feature.extract(record.seq)
            try:
                codon_start = int(
                    (qualifiers.get("codon_start", ["1"]) or ["1"])[0]
                )
            except Exception:
                codon_start = 1
            if codon_start in (2, 3):
                cds_sequence = cds_sequence[codon_start - 1 :]

            try:
                translation_table = int(
                    (qualifiers.get("transl_table", ["1"]) or ["1"])[0]
                )
            except Exception:
                translation_table = 1

            protein = str(
                cds_sequence.translate(table=translation_table, to_stop=False)
            ).rstrip("*").strip()
            if protein:
                qualifiers["translation"] = [protein]
                feature.qualifiers = qualifiers
        records.append(record)

    with destination.open("w") as handle:
        SeqIO.write(records, handle, "genbank")


def normalize_headers(source: Path, destination: Path) -> tuple[int, int]:
    records = list(SeqIO.parse(source, "genbank"))
    version_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*?)(\.\d+)?$")
    changed = 0

    for record in records:
        raw_id = ((record.id or "").split() or [""])[0].strip()
        raw_name = (record.name or "").strip()
        accessions = [
            str(accession).strip()
            for accession in (record.annotations.get("accessions") or [])
            if str(accession).strip()
        ]

        base_id = ""
        for candidate in [raw_id, raw_name, *accessions]:
            if not candidate:
                continue
            match = version_re.match(candidate.rstrip("."))
            if match:
                base_id = match.group(1)
                break
            base_id = candidate.rstrip(".")
            break

        if base_id:
            desired_name = base_id[:16].rstrip(".")
            if desired_name and record.name != desired_name:
                record.name = desired_name
                changed += 1
            normalized_accessions = [base_id]
            if accessions != normalized_accessions:
                record.annotations["accessions"] = normalized_accessions
                changed += 1

    SeqIO.write(records, destination, "genbank")
    return len(records), changed


def _hash_to_ids(path: Path) -> dict[str, list[str]]:
    identifiers: dict[str, list[str]] = defaultdict(list)
    for record in SeqIO.parse(path, "fasta"):
        sequence_id = (record.id or "").split()[0]
        if not sequence_id:
            continue
        digest = hashlib.md5(str(record.seq).upper().encode("utf-8")).hexdigest()
        identifiers[digest].append(sequence_id)
    return identifiers


def remap_ids(
    original_fasta: Path,
    renamed_fasta: Path,
    source: Path,
    destination: Path,
    map_tsv: Path,
) -> tuple[int, int, int]:
    original = _hash_to_ids(original_fasta)
    renamed = _hash_to_ids(renamed_fasta)
    renamed_to_original = {}
    for digest, renamed_ids in renamed.items():
        if len(renamed_ids) != 1:
            continue
        original_ids = original.get(digest, [])
        if len(original_ids) != 1:
            continue
        renamed_to_original[renamed_ids[0]] = original_ids[0]

    with map_tsv.open("w", encoding="utf-8") as handle:
        handle.write("renamed_id\toriginal_id\n")
        for renamed_id in sorted(renamed_to_original):
            handle.write(f"{renamed_id}\t{renamed_to_original[renamed_id]}\n")

    records = list(SeqIO.parse(source, "genbank"))
    remapped = 0
    for record in records:
        old = (record.id or "").split()[0]
        new = renamed_to_original.get(old)
        if not new or new == old:
            continue
        record.id = new
        record.name = new[:16]
        if record.description == old:
            record.description = new
        elif record.description.startswith(old + " "):
            record.description = new + record.description[len(old) :]
        record.annotations["accessions"] = [new]
        remapped += 1

    SeqIO.write(records, destination, "genbank")
    return len(renamed_to_original), len(records), remapped


def diagnose(source: Path, label: str) -> None:
    record_count = 0
    cds_count = 0
    translated_cds = 0
    untranslated_cds = 0
    try:
        for record in SeqIO.parse(source, "genbank"):
            record_count += 1
            for feature in record.features:
                if feature.type != "CDS":
                    continue
                cds_count += 1
                qualifiers = feature.qualifiers or {}
                translations = qualifiers.get("translation", [])
                if any(str(translation).strip() for translation in translations):
                    translated_cds += 1
                else:
                    untranslated_cds += 1
    except Exception as exc:
        print(f"{label}: PARSE_FAIL file={source} err={exc}")
        return
    print(f"{label}: file={source}")
    print(
        f"{label}: records={record_count} cds={cds_count} "
        f"cds_with_nonempty_translation={translated_cds} "
        f"cds_missing_or_empty_translation={untranslated_cds}"
    )


def drop_gene_less_records(source: Path, destination: Path) -> tuple[int, int]:
    records = []
    dropped = 0
    for record in SeqIO.parse(source, "genbank"):
        if not any(feature.type == "CDS" for feature in (record.features or [])):
            dropped += 1
            continue
        record.annotations.setdefault("molecule_type", "DNA")
        records.append(record)
    SeqIO.write(records, destination, "genbank")
    return len(records), dropped


def list_record_ids(source: Path, minimum_record_bp: int) -> list[str]:
    if minimum_record_bp < 1:
        raise RuntimeError(
            f"Invalid antiSMASH minimum record length: {minimum_record_bp}"
        )
    identifiers = []
    seen = set()
    with source.open() as handle:
        for record in SeqIO.parse(handle, "genbank"):
            record_id = str(record.id or record.name or "").strip()
            if not record_id or any(character in record_id for character in "\t\n\r"):
                raise RuntimeError(
                    f"Invalid GenBank record ID in {source}: {record_id!r}"
                )
            if record_id in seen:
                raise RuntimeError(
                    f"Duplicate GenBank record ID in {source}: {record_id}"
                )
            seen.add(record_id)
            if len(record.seq) >= minimum_record_bp:
                identifiers.append(record_id)
    return identifiers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("backfill-translations", "normalize-headers", "drop-gene-less"):
        subparser = commands.add_parser(command)
        subparser.add_argument("source", type=Path)
        subparser.add_argument("destination", type=Path)
    remap = commands.add_parser("remap-ids")
    remap.add_argument("original_fasta", type=Path)
    remap.add_argument("renamed_fasta", type=Path)
    remap.add_argument("source", type=Path)
    remap.add_argument("destination", type=Path)
    remap.add_argument("map_tsv", type=Path)
    diagnose_parser = commands.add_parser("diagnose")
    diagnose_parser.add_argument("source", type=Path)
    diagnose_parser.add_argument("label")
    list_parser = commands.add_parser("list-record-ids")
    list_parser.add_argument("source", type=Path)
    list_parser.add_argument("minimum_record_bp", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "backfill-translations":
        backfill_translations(args.source, args.destination)
    elif args.command == "normalize-headers":
        records, changed = normalize_headers(args.source, args.destination)
        print(f"normalized_records={records} changed_fields={changed}")
    elif args.command == "remap-ids":
        map_entries, total_records, remapped_records = remap_ids(
            args.original_fasta,
            args.renamed_fasta,
            args.source,
            args.destination,
            args.map_tsv,
        )
        print(
            f"map_entries={map_entries} total_records={total_records} "
            f"remapped_records={remapped_records}"
        )
    elif args.command == "diagnose":
        diagnose(args.source, args.label)
    elif args.command == "drop-gene-less":
        kept, dropped = drop_gene_less_records(args.source, args.destination)
        print(f"kept_records={kept} dropped_records={dropped}")
    else:
        for record_id in list_record_ids(args.source, args.minimum_record_bp):
            print(record_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
