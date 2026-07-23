#!/usr/bin/env python3
"""Merge bounded ETE4 topology summaries into shortlisted cross-kingdom rows.

The resulting TSV remains private staging input for the public cross-kingdom
evidence builder. Only the existing public-safe scalar fields are added; tree
paths, Newick, alignments, commands, and raw sequences are never copied.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tempfile
from pathlib import Path


MAX_CANDIDATE_BYTES = 2 * 1024 * 1024
MAX_TOPOLOGY_BYTES = 2 * 1024 * 1024
HARD_MAX_CANDIDATES = 100
HARD_MAX_TOPOLOGY_ROWS = 100
MAX_FIELD_CHARS = 512
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+\-]{0,199}$")
SAFE_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+\-]{0,99}$")

REQUIRED_TOPOLOGY_FIELDS = {
    "gcf_id",
    "gene_family_id",
    "family_tree_id",
    "comparison_status",
    "topology_discordance",
    "topology_support",
    "topology_support_method",
    "tree_method",
    "alignment_method",
    "trimming_method",
    "model_selection",
    "model",
    "tree_sequence_count",
    "tree_taxon_count",
    "outgroup_status",
    "tree_tool_version",
    "alignment_tool_version",
}
PUBLIC_ADDITIONS = (
    "gene_family_id",
    "family_tree_id",
    "topology_discordance",
    "topology_comparison_status",
    "topology_support",
    "topology_support_method",
    "tree_method",
    "alignment_method",
    "trimming_method",
    "model_selection",
    "model",
    "tree_sequence_count",
    "tree_taxon_count",
    "outgroup_status",
    "tree_tool_version",
    "alignment_tool_version",
)
ALLOWED_TOPOLOGY_VALUES = {"supported", "not_supported", "insufficient_data"}
ALLOWED_COMPARISON_STATUSES = {
    "supported_domain_topology_discordance",
    "domain_topology_discordance_low_support",
    "concordant_domain_split",
    "insufficient_domain_replication",
}
PINNED_SCALAR_VALUES = {
    "topology_support_method": "IQ-TREE_2_ultrafast_bootstrap_ETE4_unrooted_domain_split",
    "tree_method": "IQ-TREE_2_maximum_likelihood",
    "alignment_method": "MAFFT_7.526",
    "trimming_method": "trimAl_automated1",
    "model_selection": "MFP",
    "outgroup_status": "unrooted_no_directional_inference",
    "tree_tool_version": "IQ-TREE_2.4.0",
    "alignment_tool_version": "MAFFT_7.526",
}


class MergeError(ValueError):
    """Raised when private topology staging data violates its safe schema."""


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def read_tsv(path: Path, *, max_bytes: int, max_rows: int) -> tuple[list[str], list[dict[str, str]]]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise MergeError(f"input TSV is unavailable: {path.name}") from exc
    if size > max_bytes:
        raise MergeError(f"input TSV exceeds its byte bound: {path.name}")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = [clean(field) for field in (reader.fieldnames or [])]
        if not fields or any(not field for field in fields) or len(fields) != len(set(fields)):
            raise MergeError(f"input TSV has invalid headers: {path.name}")
        rows: list[dict[str, str]] = []
        for index, raw in enumerate(reader, 1):
            if index > max_rows:
                raise MergeError(f"input TSV exceeds its row bound: {path.name}")
            row = {field: clean(raw.get(field)) for field in fields}
            if any(len(value) > MAX_FIELD_CHARS for value in row.values()):
                raise MergeError(f"input TSV contains an overlong scalar: {path.name}")
            rows.append(row)
    return fields, rows


def parse_nonnegative_int(value: str, field: str) -> int:
    if not value.isdigit():
        raise MergeError(f"topology field {field} must be a nonnegative integer")
    return int(value)


def parse_support(value: str) -> float | None:
    if not value:
        return None
    try:
        support = float(value)
    except ValueError as exc:
        raise MergeError("topology support must be numeric") from exc
    if not 0 <= support <= 100:
        raise MergeError("topology support must be between 0 and 100")
    return support


def validate_topology_row(row: dict[str, str]) -> tuple[int, float]:
    for field in ("gcf_id", "gene_family_id", "family_tree_id"):
        if not SAFE_ID_RE.fullmatch(row[field]):
            raise MergeError(f"topology field {field} is not a safe identifier")
    topology = row["topology_discordance"]
    if topology not in ALLOWED_TOPOLOGY_VALUES:
        raise MergeError("topology_discordance has an unsupported value")
    if row["comparison_status"] not in ALLOWED_COMPARISON_STATUSES:
        raise MergeError("comparison_status has an unsupported value")
    for field, expected in PINNED_SCALAR_VALUES.items():
        if row[field] != expected:
            raise MergeError(f"topology field {field} does not match the pinned method")
    if not SAFE_MODEL_RE.fullmatch(row["model"]):
        raise MergeError("topology field model is not a safe bounded IQ-TREE model identifier")
    support = parse_support(row["topology_support"])
    sequence_count = parse_nonnegative_int(row["tree_sequence_count"], "tree_sequence_count")
    taxon_count = parse_nonnegative_int(row["tree_taxon_count"], "tree_taxon_count")
    if sequence_count > 1_000 or taxon_count > 2:
        raise MergeError("topology sequence or taxon count exceeds its bound")
    for field in REQUIRED_TOPOLOGY_FIELDS - {
        "gcf_id",
        "gene_family_id",
        "family_tree_id",
        "topology_support",
        "tree_sequence_count",
        "tree_taxon_count",
    }:
        value = row[field]
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise MergeError(f"topology field {field} contains control characters")
        if "/" in value or "\\" in value or "://" in value:
            raise MergeError(f"topology field {field} contains a path or URL")
    rank = {"supported": 3, "not_supported": 2, "insufficient_data": 1}[topology]
    return rank, support if support is not None else -1.0


def merge(args: argparse.Namespace) -> int:
    if not args.explicit_request:
        raise MergeError("--explicit-request is required")
    if not 1 <= args.max_candidates <= HARD_MAX_CANDIDATES:
        raise MergeError("--max-candidates must be between 1 and 100")
    candidate_fields, candidates = read_tsv(
        args.candidates,
        max_bytes=MAX_CANDIDATE_BYTES,
        max_rows=args.max_candidates + 1,
    )
    if len(candidates) > args.max_candidates:
        raise MergeError("candidate TSV exceeds the explicit candidate bound")
    if "gcf_id" not in candidate_fields:
        raise MergeError("candidate TSV requires gcf_id")
    topology_fields, topology_rows = read_tsv(
        args.topology,
        max_bytes=MAX_TOPOLOGY_BYTES,
        max_rows=HARD_MAX_TOPOLOGY_ROWS,
    )
    missing = sorted(REQUIRED_TOPOLOGY_FIELDS.difference(topology_fields))
    if missing:
        raise MergeError(f"topology TSV requires column {missing[0]}")

    selected: dict[str, tuple[tuple[int, float, str, str], dict[str, str]]] = {}
    for row in topology_rows:
        rank, support = validate_topology_row(row)
        key = (rank, support, row["gene_family_id"], row["family_tree_id"])
        current = selected.get(row["gcf_id"])
        if current is None or key > current[0]:
            selected[row["gcf_id"]] = (key, row)

    output_fields = list(candidate_fields)
    for field in PUBLIC_ADDITIONS:
        if field not in output_fields:
            output_fields.append(field)
    merged_count = 0
    output_rows: list[dict[str, str]] = []
    for candidate in candidates:
        row = dict(candidate)
        selected_row = selected.get(row["gcf_id"])
        if selected_row is not None:
            topology = selected_row[1]
            additions = {
                "gene_family_id": topology["gene_family_id"],
                "family_tree_id": topology["family_tree_id"],
                "topology_discordance": topology["topology_discordance"],
                # The public builder treats these as aliases, so they must use
                # the same controlled token rather than a private status label.
                "topology_comparison_status": topology["topology_discordance"],
                "topology_support": topology["topology_support"],
                "topology_support_method": topology["topology_support_method"],
                "tree_method": topology["tree_method"],
                "alignment_method": topology["alignment_method"],
                "trimming_method": topology["trimming_method"],
                "model_selection": topology["model_selection"],
                "model": topology["model"],
                "tree_sequence_count": topology["tree_sequence_count"],
                "tree_taxon_count": topology["tree_taxon_count"],
                "outgroup_status": topology["outgroup_status"],
                "tree_tool_version": topology["tree_tool_version"],
                "alignment_tool_version": topology["alignment_tool_version"],
            }
            row.update(additions)
            merged_count += 1
        else:
            for field in PUBLIC_ADDITIONS:
                row.setdefault(field, "")
        output_rows.append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{args.output.name}.", dir=str(args.output.parent)
    )
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=output_fields, delimiter="\t", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(output_rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, args.output)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return merged_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explicit-request", action="store_true")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-candidates", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    try:
        count = merge(parse_args())
    except (OSError, UnicodeError, MergeError) as exc:
        message = re.sub(r"[^A-Za-z0-9_. -]+", "_", str(exc))[:180]
        print(f"TOPOLOGY_EVIDENCE_MERGE status=failed message={message}", file=sys.stderr)
        return 2
    print(f"TOPOLOGY_EVIDENCE_MERGE status=success candidates_enriched={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
