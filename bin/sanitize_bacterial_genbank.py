#!/usr/bin/env python3
"""Build deterministic feature-free bacterial GenBank input for antiSMASH."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Iterable


DNA_ALPHABET = set("ACGTURYSWKMBDHVN-.")


@dataclass(frozen=True)
class SequenceRecord:
    original_id: str
    sequence: str
    topology: str
    ordinal: int


def safe_token(value: str, fallback: str = "record", limit: int = 120) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("._-")[:limit]
    if not text:
        text = fallback
    if text.startswith("-"):
        text = f"{fallback}_{text.lstrip('-')}"
    return text


def clean_tsv_text(value: str, limit: int = 500) -> str:
    return re.sub(r"[\t\r\n]+", " ", str(value or "")).strip()[:limit]


def validate_sequence(sequence: str, record_id: str) -> str:
    normalized = re.sub(r"\s+", "", sequence).upper()
    invalid = sorted(set(normalized) - DNA_ALPHABET)
    if invalid:
        display = "".join(invalid[:8])
        raise ValueError(f"record {record_id!r} contains unsupported nucleotide characters: {display}")
    if not normalized:
        raise ValueError(f"record {record_id!r} has no nucleotide sequence")
    return normalized


def parse_fasta(path: Path) -> list[SequenceRecord]:
    records: list[SequenceRecord] = []
    current_id = ""
    chunks: list[str] = []

    def flush() -> None:
        nonlocal current_id, chunks
        if not current_id:
            return
        records.append(
            SequenceRecord(
                original_id=current_id,
                sequence=validate_sequence("".join(chunks), current_id),
                topology="linear",
                ordinal=len(records) + 1,
            )
        )
        current_id = ""
        chunks = []

    with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                flush()
                current_id = line[1:].strip().split()[0] if line[1:].strip() else ""
                if not current_id:
                    raise ValueError("FASTA record header is empty")
                continue
            if not current_id:
                raise ValueError("FASTA sequence data appears before the first header")
            chunks.append(line)
    flush()
    if not records:
        raise ValueError("FASTA input contains no records")
    return records


def _genbank_record(block: list[str], ordinal: int) -> SequenceRecord:
    locus_id = ""
    accession = ""
    version = ""
    topology = "linear"
    in_origin = False
    sequence_parts: list[str] = []
    for line in block:
        if line.startswith("LOCUS"):
            fields = line.split()
            if len(fields) >= 2:
                locus_id = fields[1]
            if any(field.lower() == "circular" for field in fields):
                topology = "circular"
            elif any(field.lower() == "linear" for field in fields):
                topology = "linear"
        elif line.startswith("ACCESSION"):
            fields = line.split()
            if len(fields) >= 2:
                accession = fields[1]
        elif line.startswith("VERSION"):
            fields = line.split()
            if len(fields) >= 2:
                version = fields[1]
        elif line.startswith("ORIGIN"):
            in_origin = True
        elif line.startswith("//"):
            in_origin = False
        elif in_origin:
            sequence_parts.append("".join(re.findall(r"[A-Za-z.-]+", line)))
    original_id = version or accession or locus_id or f"record_{ordinal}"
    return SequenceRecord(
        original_id=original_id,
        sequence=validate_sequence("".join(sequence_parts), original_id),
        topology=topology,
        ordinal=ordinal,
    )


def parse_genbank(path: Path) -> list[SequenceRecord]:
    records: list[SequenceRecord] = []
    block: list[str] = []
    with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            if line.startswith("LOCUS") and block:
                raise ValueError("GenBank record is missing a // terminator")
            if line.startswith("LOCUS") or block:
                block.append(line)
            if line.startswith("//") and block:
                records.append(_genbank_record(block, len(records) + 1))
                block = []
    if block:
        raise ValueError("GenBank record is missing a // terminator")
    if not records:
        raise ValueError("GenBank input contains no complete records")
    return records


def parse_input(path: Path) -> tuple[str, list[SequenceRecord]]:
    first = ""
    with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
        for raw in handle:
            if raw.strip():
                first = raw.lstrip()
                break
    if first.startswith(">"):
        return "fasta", parse_fasta(path)
    if first.startswith("LOCUS"):
        return "genbank", parse_genbank(path)
    raise ValueError("input is neither FASTA nor GenBank")


def format_origin(sequence: str) -> list[str]:
    lines = ["ORIGIN"]
    clean = sequence.lower()
    for offset in range(0, len(clean), 60):
        chunk = clean[offset : offset + 60]
        groups = " ".join(chunk[index : index + 10] for index in range(0, len(chunk), 10))
        lines.append(f"{offset + 1:>9} {groups}")
    return lines


def format_record(record_id: str, sequence: str, topology: str) -> str:
    lines = [
        f"LOCUS       {record_id:<20} {len(sequence):>11} bp    DNA     {topology:<8} BCT 01-JAN-1980",
        f"DEFINITION  ClusterWeave sanitized bacterial assembly record {record_id}.",
        f"ACCESSION   {record_id}",
        f"VERSION     {record_id}",
        "KEYWORDS    .",
        "SOURCE      .",
        "  ORGANISM  .",
        "FEATURES             Location/Qualifiers",
        *format_origin(sequence),
        "//",
    ]
    return "\n".join(lines) + "\n"


def write_tsv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def sanitize(
    input_path: Path,
    output_path: Path,
    record_map_path: Path,
    record_ids_path: Path,
    genome_id: str,
    min_record_bp: int,
    max_record_bp: int,
) -> dict[str, int | str]:
    input_format, records = parse_input(input_path)
    safe_genome = safe_token(genome_id, "genome", 56)
    used_ids: set[str] = set()
    map_rows: list[dict[str, object]] = []
    eligible: list[tuple[str, SequenceRecord]] = []
    oversized = 0

    for record in records:
        base = safe_token(record.original_id, f"record_{record.ordinal}", 56)
        sanitized_id = safe_token(f"{safe_genome}__{base}", f"{safe_genome}__record", 120)
        suffix = 1
        candidate = sanitized_id
        while candidate.casefold() in used_ids:
            suffix += 1
            candidate = safe_token(f"{sanitized_id}_{suffix}", "record", 120)
        sanitized_id = candidate
        used_ids.add(sanitized_id.casefold())

        length = len(record.sequence)
        status = "eligible"
        reason = ""
        if length < min_record_bp:
            status = "excluded_below_minimum"
            reason = f"length below minimum {min_record_bp} bp"
        elif length > max_record_bp:
            status = "rejected_above_maximum"
            reason = f"length above maximum {max_record_bp} bp"
            oversized += 1
        else:
            eligible.append((sanitized_id, record))
        map_rows.append(
            {
                "input_order": record.ordinal,
                "original_record_id": clean_tsv_text(record.original_id),
                "sanitized_record_id": sanitized_id,
                "sequence_length_bp": length,
                "topology": record.topology,
                "status": status,
                "reason": reason,
            }
        )

    write_tsv(
        record_map_path,
        [
            "input_order",
            "original_record_id",
            "sanitized_record_id",
            "sequence_length_bp",
            "topology",
            "status",
            "reason",
        ],
        map_rows,
    )
    record_ids_path.parent.mkdir(parents=True, exist_ok=True)
    ids_tmp = record_ids_path.with_name(f".{record_ids_path.name}.tmp")
    ids_tmp.write_text("".join(f"{record_id}\n" for record_id, _ in eligible), encoding="utf-8")
    ids_tmp.replace(record_ids_path)

    if oversized:
        raise ValueError(f"{oversized} record(s) exceed the configured maximum size")
    if not eligible:
        raise ValueError("no bacterial records remain after bounded size filtering")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_tmp = output_path.with_name(f".{output_path.name}.tmp")
    with output_tmp.open("w", encoding="utf-8") as handle:
        for record_id, record in eligible:
            handle.write(format_record(record_id, record.sequence, record.topology))
    output_tmp.replace(output_path)
    return {
        "input_format": input_format,
        "records_total": len(records),
        "records_eligible": len(eligible),
        "records_excluded": len(records) - len(eligible),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--record-map", required=True, type=Path)
    parser.add_argument("--record-ids", required=True, type=Path)
    parser.add_argument("--genome-id", required=True)
    parser.add_argument("--min-record-bp", type=int, default=1000)
    parser.add_argument("--max-record-bp", type=int, default=50_000_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_record_bp < 1 or args.max_record_bp < args.min_record_bp:
        print("ERROR: invalid bacterial record size bounds", file=sys.stderr)
        return 2
    try:
        summary = sanitize(
            args.input,
            args.output,
            args.record_map,
            args.record_ids,
            args.genome_id,
            args.min_record_bp,
            args.max_record_bp,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: bacterial GenBank sanitization failed: {exc}", file=sys.stderr)
        return 2
    print(
        "BACTERIAL_SANITIZE "
        f"genome={safe_token(args.genome_id, 'genome')} "
        f"format={summary['input_format']} "
        f"records_total={summary['records_total']} "
        f"records_eligible={summary['records_eligible']} "
        f"records_excluded={summary['records_excluded']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
