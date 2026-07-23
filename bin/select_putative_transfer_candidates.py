#!/usr/bin/env python3
"""Select a bounded cross-domain GCF shortlist from the canonical crosswalk.

The selector is intentionally conservative: it groups unique genomes by GCF,
retains only families with both fungal and bacterial members, and carries only
public-safe, unambiguous evidence fields already accepted by the terminal
evidence builder.  Cross-domain membership is context and is never promoted to
an evidence signal here.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import io
import os
from pathlib import Path
import re
import tempfile
from typing import Sequence

from build_putative_transfer_evidence import (
    ALLOWED_INPUT_FIELDS,
    EvidenceInputError,
    safe_identifier,
    validate_public_value,
)


DEFAULT_MAX_CANDIDATES = 25
HARD_MAX_CANDIDATES = 100
MAX_CROSSWALK_BYTES = 64 * 1024 * 1024
MAX_CROSSWALK_ROWS = 500_000
SAFE_GCF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+\-]{0,127}$")

CORE_OUTPUT_FIELDS = (
    "candidate_id",
    "gcf_id",
    "cross_domain_gcf",
    "taxon_groups",
    "fungal_member_count",
    "bacterial_member_count",
    "member_count",
)

# These are the only optional fields copied from an enriched canonical
# crosswalk.  Values must be public-safe and identical across all rows in the
# selected family; conflicting or unsafe values are left blank.
CARRY_FIELDS = (
    "synteny_support",
    "synteny_gene_order_matches",
    "synteny_matched_genes",
    "synteny_gene_count",
    "synteny_total_genes",
    "synteny_gene_order_fraction",
    "characterized_reference_support",
    "characterized_reference_id",
    "characterized_reference_similarity",
    "characterized_reference_similarity_percent",
    "characterized_reference_method",
    "family_tree_id",
    "topology_discordance",
    "topology_discordance_supported",
    "topology_comparison_status",
    "topology_support",
    "topology_support_method",
    "support_method",
    "tree_method",
    "alignment_method",
    "trimming_method",
    "model",
    "tree_sequence_count",
    "tree_taxon_count",
    "outgroup_status",
    "tree_tool_version",
    "alignment_tool_version",
    "mobile_element_context",
    "mobile_element_support",
    "composition_outlier",
    "composition_support",
    "contamination_check",
    "contamination_status",
    "assembly_check",
    "assembly_context_check",
    "assembly_status",
    "paralogy_check",
    "paralogy_status",
    "sampling_check",
    "sampling_status",
    "incomplete_sampling",
    "conserved_enzyme_risk",
    "conserved_enzyme_family",
    "long_branch_attraction_risk",
    "long_branch_risk",
)
IDENTIFIER_CARRY_FIELDS = frozenset({"characterized_reference_id", "family_tree_id"})

if not set(CORE_OUTPUT_FIELDS).issubset(ALLOWED_INPUT_FIELDS):
    raise RuntimeError("selector core schema is not accepted by the evidence builder")
if not set(CARRY_FIELDS).issubset(ALLOWED_INPUT_FIELDS):
    raise RuntimeError("selector carry schema is not accepted by the evidence builder")


class SelectorInputError(ValueError):
    """Raised for malformed or unbounded canonical crosswalk inputs."""


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def split_gcf_ids(value: object) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for part in clean(value).split(";"):
        family = part.strip()
        if not family or family in seen:
            continue
        seen.add(family)
        if not SAFE_GCF_RE.fullmatch(family):
            continue
        values.append(family)
    return values


def normalized_taxon(value: object) -> str:
    token = clean(value).casefold()
    return token if token in {"fungi", "bacteria"} else ""


def safe_carry_value(field: str, value: str, row_number: int) -> bool:
    try:
        validate_public_value(field, value, row_number)
        if field in IDENTIFIER_CARRY_FIELDS:
            safe_identifier(value, field)
    except EvidenceInputError:
        return False
    return True


def read_crosswalk(
    path: Path,
) -> tuple[
    dict[str, dict[str, set[str]]],
    dict[str, dict[str, set[str]]],
    set[str],
    set[str],
]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SelectorInputError("canonical crosswalk is unavailable") from exc
    if size > MAX_CROSSWALK_BYTES:
        raise SelectorInputError(f"canonical crosswalk exceeds {MAX_CROSSWALK_BYTES} bytes")

    members: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"fungi": set(), "bacteria": set()}
    )
    carried_values: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    unsafe_or_conflicting: set[str] = set()
    source_carry_fields: set[str] = set()
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            headers = [str(name or "").strip() for name in (reader.fieldnames or [])]
            if not headers or any(not name for name in headers):
                raise SelectorInputError("canonical crosswalk requires non-empty TSV headers")
            if len(headers) != len(set(headers)):
                raise SelectorInputError("canonical crosswalk contains duplicate headers")
            genome_field = "genome" if "genome" in headers else "genome_id" if "genome_id" in headers else ""
            for required in ("taxon_group", "gcf_id"):
                if required not in headers:
                    raise SelectorInputError(f"canonical crosswalk requires {required}")
            if not genome_field:
                raise SelectorInputError("canonical crosswalk requires genome or genome_id")
            source_carry_fields = set(headers).intersection(CARRY_FIELDS)

            for row_number, row in enumerate(reader, start=2):
                if row_number - 1 > MAX_CROSSWALK_ROWS:
                    raise SelectorInputError(
                        f"canonical crosswalk exceeds {MAX_CROSSWALK_ROWS} data rows"
                    )
                if None in row:
                    raise SelectorInputError(f"row {row_number}: more values than declared columns")
                genome = clean(row.get(genome_field))
                taxon = normalized_taxon(row.get("taxon_group"))
                families = split_gcf_ids(row.get("gcf_id"))
                if not genome or not taxon or not families:
                    continue
                for family in families:
                    members[family][taxon].add(genome)
                    for field in source_carry_fields:
                        value = clean(row.get(field))
                        if not value:
                            continue
                        if not safe_carry_value(field, value, row_number):
                            unsafe_or_conflicting.add(f"{family}\0{field}")
                            continue
                        carried_values[family][field].add(value)
    except UnicodeError as exc:
        raise SelectorInputError("canonical crosswalk must be valid UTF-8") from exc
    except csv.Error as exc:
        raise SelectorInputError("canonical crosswalk is malformed") from exc
    return members, carried_values, unsafe_or_conflicting, source_carry_fields


def candidate_rows(
    members: dict[str, dict[str, set[str]]],
    carried_values: dict[str, dict[str, set[str]]],
    unsafe_or_conflicting: set[str],
    source_carry_fields: set[str],
    max_candidates: int,
) -> tuple[list[str], list[dict[str, str]], int]:
    eligible: list[tuple[str, set[str], set[str]]] = []
    for family, by_taxon in members.items():
        fungi = set(by_taxon.get("fungi", set()))
        bacteria = set(by_taxon.get("bacteria", set()))
        if not fungi or not bacteria:
            continue
        if fungi.intersection(bacteria):
            # A supposedly stable genome ID cannot safely establish two domains.
            continue
        eligible.append((family, fungi, bacteria))
    eligible.sort(
        key=lambda item: (
            -(len(item[1]) + len(item[2])),
            item[0].casefold(),
            item[0],
        )
    )

    optional_fields = [field for field in CARRY_FIELDS if field in source_carry_fields]
    fields = [*CORE_OUTPUT_FIELDS, *optional_fields]
    rows: list[dict[str, str]] = []
    for family, fungi, bacteria in eligible[:max_candidates]:
        row = {
            "candidate_id": family,
            "gcf_id": family,
            "cross_domain_gcf": "yes",
            "taxon_groups": "fungi;bacteria",
            "fungal_member_count": str(len(fungi)),
            "bacterial_member_count": str(len(bacteria)),
            "member_count": str(len(fungi) + len(bacteria)),
        }
        for field in optional_fields:
            values = carried_values.get(family, {}).get(field, set())
            key = f"{family}\0{field}"
            row[field] = next(iter(values)) if len(values) == 1 and key not in unsafe_or_conflicting else ""
        rows.append(row)
    return fields, rows, len(eligible)


def render_tsv(fields: list[str], rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=fields,
        delimiter="\t",
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def select_candidates(crosswalk: Path, output: Path, max_candidates: int) -> tuple[int, int]:
    if not 1 <= max_candidates <= HARD_MAX_CANDIDATES:
        raise SelectorInputError(f"--max-candidates must be between 1 and {HARD_MAX_CANDIDATES}")
    members, carried_values, unsafe_or_conflicting, source_fields = read_crosswalk(crosswalk)
    fields, rows, eligible_count = candidate_rows(
        members,
        carried_values,
        unsafe_or_conflicting,
        source_fields,
        max_candidates,
    )
    atomic_write_text(output, render_tsv(fields, rows))
    return len(rows), eligible_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Select bounded fungi+bacteria GCF candidates from a canonical crosswalk."
    )
    parser.add_argument(
        "--explicit-request",
        action="store_true",
        help="Confirm that optional cross-kingdom evidence was explicitly requested.",
    )
    parser.add_argument("--crosswalk", type=Path, required=True, help="Canonical BGC/GCF crosswalk TSV.")
    parser.add_argument("--output", type=Path, required=True, help="Private safe candidate TSV for the evidence builder.")
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=DEFAULT_MAX_CANDIDATES,
        help=f"Maximum selected families (default {DEFAULT_MAX_CANDIDATES}, hard maximum {HARD_MAX_CANDIDATES}).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.explicit_request:
        parser.error("--explicit-request is required; optional evidence selection is never implicit")
    try:
        selected_count, eligible_count = select_candidates(
            args.crosswalk,
            args.output,
            args.max_candidates,
        )
    except (SelectorInputError, OSError) as exc:
        parser.error(str(exc))
    print(
        "SELECTED_CROSS_DOMAIN_CANDIDATES "
        f"count={selected_count} eligible={eligible_count} limit={args.max_candidates}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
