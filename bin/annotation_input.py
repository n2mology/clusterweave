#!/usr/bin/env python3
"""Canonical taxon-manifest and annotation input discovery boundary."""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path
from typing import Iterable


FASTA_EXTENSIONS = ("fna", "fa", "fsa", "fasta")
GENBANK_EXTENSIONS = ("gbk", "gb", "gbff")
INPUT_EXTENSIONS = FASTA_EXTENSIONS + GENBANK_EXTENSIONS
SKIPPED_ROUTE_STATUSES = {
    "failed",
    "invalid",
    "rejected",
    "unresolved",
    "unsupported",
}


def _has_input(root: Path, stem: str) -> bool:
    return any(
        (root / f"{stem}.{extension}").is_file()
        and (root / f"{stem}.{extension}").stat().st_size > 0
        for extension in INPUT_EXTENSIONS
    )


def _mapped_canonical(mapping_file: Path, stem: str) -> str | None:
    if not mapping_file.is_file():
        return None
    with mapping_file.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) >= 2 and row[0] == stem and row[1] and row[1] != stem:
                return row[1]
    return None


def materialized_alias_target(
    mapping_file: Path, fungi_root: Path, stem: str
) -> str | None:
    canonical = _mapped_canonical(mapping_file, stem)
    if canonical and _has_input(fungi_root, canonical):
        return canonical
    return None


def discover_legacy_stems(fungi_root: Path, mapping_file: Path) -> list[str]:
    stems: set[str] = set()
    if fungi_root.is_dir():
        for entry in fungi_root.iterdir():
            if entry.is_symlink() or not entry.is_file():
                continue
            if entry.suffix[1:].lower() not in INPUT_EXTENSIONS:
                continue
            # Match the historical shell behavior: discovery accepts an
            # uppercase extension, but strips only the canonical lowercase
            # spelling.
            stem = re.sub(
                r"\.(fa|fna|fsa|fasta|gb|gbk|gbff)$", "", entry.name
            )
            stems.add(stem)

    discovered: list[str] = []
    for stem in sorted(stems, key=os.fsencode):
        canonical = materialized_alias_target(mapping_file, fungi_root, stem)
        if canonical:
            print(
                f"skipping accession alias genome stem: {stem} maps to existing "
                f"{canonical}",
                file=sys.stderr,
            )
            continue
        discovered.append(stem)
    return discovered


def _route_rows(
    manifest: Path, fungi_root: Path, bacteria_root: Path
) -> tuple[list[tuple[str, ...]], bool, bool]:
    routes: list[tuple[str, ...]] = []
    seen: set[str] = set()
    has_fungal = False
    has_bacterial = False

    with manifest.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            row = row + [""] * max(0, 12 - len(row))
            (
                input_key,
                genome_id,
                taxon_group,
                taxon_source,
                _taxid,
                _organism_name,
                _source_accession,
                prediction_method,
                detector_profile,
                _input_path_key,
                route_status,
                _route_reason,
            ) = row[:12]
            if input_key == "input_key" or not genome_id:
                continue
            if route_status.lower() in SKIPPED_ROUTE_STATUSES:
                continue

            taxon_group = taxon_group.lower()
            if taxon_group == "fungi":
                has_fungal = True
                root = fungi_root
                prediction_method = prediction_method or "funannotate"
                detector_profile = detector_profile or "antismash+funbgcex"
            elif taxon_group == "bacteria":
                has_bacterial = True
                root = bacteria_root
                prediction_method = prediction_method or "prodigal"
                detector_profile = detector_profile or "antismash"
            else:
                raise ValueError(
                    f"Invalid taxon_group='{taxon_group}' for genome {genome_id} "
                    f"in {manifest}"
                )

            if genome_id in seen:
                raise ValueError(
                    f"Duplicate genome_id in canonical taxon manifest: {genome_id}"
                )
            seen.add(genome_id)
            routes.append(
                (
                    genome_id,
                    taxon_group,
                    str(root),
                    prediction_method,
                    detector_profile,
                    taxon_source or "legacy_default",
                    route_status or "routed",
                )
            )
    return routes, has_fungal, has_bacterial


def emit_routes(manifest: Path, fungi_root: Path, bacteria_root: Path) -> None:
    if not manifest.is_file() or manifest.stat().st_size == 0:
        print("meta\t0\t1\t0")
        return

    routes, has_fungal, has_bacterial = _route_rows(
        manifest, fungi_root, bacteria_root
    )
    active = bool(routes)
    if not active:
        has_fungal = True
    print(
        "meta\t{}\t{}\t{}".format(
            int(active), int(has_fungal), int(has_bacterial)
        )
    )
    for route in routes:
        print("route\t" + "\t".join(route))


def resolve_input(root: Path, stem: str, extensions: Iterable[str]) -> Path | None:
    for extension in extensions:
        candidate = root / f"{stem}.{extension}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    routes = subparsers.add_parser("routes")
    routes.add_argument("--manifest", type=Path, required=True)
    routes.add_argument("--fungi-root", type=Path, required=True)
    routes.add_argument("--bacteria-root", type=Path, required=True)

    discover = subparsers.add_parser("discover")
    discover.add_argument("--fungi-root", type=Path, required=True)
    discover.add_argument("--mapping-file", type=Path, required=True)

    mapped = subparsers.add_parser("mapped-canonical")
    mapped.add_argument("--mapping-file", type=Path, required=True)
    mapped.add_argument("--stem", required=True)

    alias = subparsers.add_parser("materialized-alias")
    alias.add_argument("--mapping-file", type=Path, required=True)
    alias.add_argument("--fungi-root", type=Path, required=True)
    alias.add_argument("--stem", required=True)

    has_input = subparsers.add_parser("has-input")
    has_input.add_argument("--root", type=Path, required=True)
    has_input.add_argument("--stem", required=True)

    resolve = subparsers.add_parser("resolve")
    resolve.add_argument("--root", type=Path, required=True)
    resolve.add_argument("--stem", required=True)
    resolve.add_argument("--kind", choices=("fasta", "genbank"), required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "routes":
        emit_routes(args.manifest, args.fungi_root, args.bacteria_root)
    elif args.command == "discover":
        for stem in discover_legacy_stems(args.fungi_root, args.mapping_file):
            print(stem)
    elif args.command == "mapped-canonical":
        canonical = _mapped_canonical(args.mapping_file, args.stem)
        if canonical is None:
            return 1
        print(canonical)
    elif args.command == "materialized-alias":
        canonical = materialized_alias_target(
            args.mapping_file, args.fungi_root, args.stem
        )
        if canonical is None:
            return 1
        print(canonical)
    elif args.command == "has-input":
        return 0 if _has_input(args.root, args.stem) else 1
    elif args.command == "resolve":
        extensions = (
            FASTA_EXTENSIONS if args.kind == "fasta" else GENBANK_EXTENSIONS
        )
        resolved = resolve_input(args.root, args.stem, extensions)
        if resolved is None:
            return 1
        print(resolved)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(2) from exc
