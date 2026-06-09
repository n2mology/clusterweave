#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path

METADATA_FIELDS = [
    "accession",
    "genome_id_current",
    "taxonomy_id",
    "genome_size_mb",
    "genome_id_original_if_different",
    "ecofun_primary",
    "ecofun_secondary",
]

GENOME_EXTS = {".fasta", ".fa", ".fna", ".fsa", ".gb", ".gbk", ".gbff"}


def _normalize_name(text: str) -> str:
    """Normalize historical fungus labels to a stable matching key.

    We keep this deliberately conservative:
    - replace punctuation and whitespace with underscores
    - collapse repeated underscores
    - trim leading/trailing underscores
    - keep case-insensitive matching

    This handles the common dot/underscore/space differences between the
    original ecology colorstrip files and the current accession list.
    """
    text = text.strip().replace(" ", "_")
    text = re.sub(r"[.\-/:()+]+", "_", text)
    text = re.sub(r"__+", "_", text)
    text = text.strip("_")
    return text.lower()


def _parse_ecofun_colorstrip(path: Path) -> dict[str, str]:
    """Parse a simple iTOL colorstrip file into {normalized_name: label}."""
    labels: dict[str, str] = {}
    in_data = False
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line == "DATA":
                in_data = True
                continue
            if not in_data:
                continue
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            genome_name = parts[0].strip()
            ecofun_label = parts[2].strip()
            labels[_normalize_name(genome_name)] = ecofun_label
    return labels


def _parse_accessions(path: Path) -> list[dict[str, str]]:
    rows = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            if not row:
                continue
            if len(row) < 3:
                raise ValueError(f"Expected at least 3 tab-separated columns in {path}, got: {row!r}")
            accession, genome_id_current, taxonomy_id = row[0].strip(), row[1].strip(), row[2].strip()
            genome_size_mb = row[3].strip() if len(row) >= 4 else ""
            rows.append(
                {
                    "accession": accession,
                    "genome_id_current": genome_id_current,
                    "taxonomy_id": taxonomy_id,
                    "genome_size_mb": genome_size_mb,
                }
            )
    return rows


def _genome_file_stem(path: Path) -> str:
    if path.suffix.lower() in GENOME_EXTS:
        return path.stem
    if path.suffix.lower() == ".gz":
        uncompressed = Path(path.name[:-3])
        if uncompressed.suffix.lower() in GENOME_EXTS:
            return uncompressed.stem
    return ""


def _parse_genome_dir(path: Path) -> list[dict[str, str]]:
    rows = []
    seen = set()
    for candidate in sorted(path.iterdir(), key=lambda item: item.name.lower()):
        if not candidate.is_file():
            continue
        genome_id_current = _genome_file_stem(candidate)
        if not genome_id_current or genome_id_current in seen:
            continue
        seen.add(genome_id_current)
        rows.append(
            {
                "accession": "",
                "genome_id_current": genome_id_current,
                "taxonomy_id": "",
                "genome_size_mb": "",
            }
        )
    return rows


def _build_alias_map() -> dict[str, str]:
    """Map current genome names to the historical ecofun label when the names drifted."""
    return {
        _normalize_name("Chaetomium_sp._MPI-CAGE-AT-0009"): "Chaetomium_megalocarpum_MPI-CAGE-AT-0009",
        _normalize_name("Leptodontidium_sp._MPI-SDFR-AT-0119"): "Leptodontidium_orchidicola_MPI-SDFR-AT-0119",
        _normalize_name("Cadophora_sp._MPI-SDFR-AT-0126"): "Cadophora_sp_MPI-SDFR-AT-0126",
        _normalize_name("Cenococcum_geophilum_1.58"): "Cenoccoccum_geophilum_1_58",
        _normalize_name("Periconia_digitata_CNCM_I-4278"): "Periconia_digitata_CNCM_I-4278",
        _normalize_name("Cladophialophora_carrionii_CBS_160.54"): "Cladophialophora_carrionii_CBS_160_54",
    }


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    project_name = os.environ.get("PROJECT_NAME", project_root.name)
    legacy_default_root = project_root / "legacy_context"
    primary_default = Path(os.environ["ECOFUN_PRIMARY"]) if "ECOFUN_PRIMARY" in os.environ else legacy_default_root / "ecofun_primary_from_original.txt"
    secondary_default = Path(os.environ["ECOFUN_SECONDARY"]) if "ECOFUN_SECONDARY" in os.environ else legacy_default_root / "ecofun_secondary_from_original.txt"
    accessions_default = project_root / "data" / "genomes" / "fungi" / project_name / "accessions_fungusID_taxonomyID.txt"
    out_default = project_root / "data" / "results" / project_name / "summary_tables" / "ecofun_metadata_normalized.tsv"
    template_default = project_root / "data" / "results" / project_name / "summary_tables" / "ecofun_metadata_template.tsv"

    parser = argparse.ArgumentParser(
        description=(
            "Normalize ecology metadata into a TSV keyed by the current accession list. "
            "The script is conservative about name matching: generic punctuation cleanup first, then a "
            "small alias map for names that changed between the original project and the current codebase."
        )
    )
    parser.add_argument(
        "--primary",
        type=Path,
        default=primary_default,
        help="Path to the original primary ecofunction colorstrip.",
    )
    parser.add_argument(
        "--secondary",
        type=Path,
        default=secondary_default,
        help="Path to the original secondary ecofunction colorstrip.",
    )
    parser.add_argument(
        "--accessions",
        type=Path,
        default=accessions_default,
        help=(
            "Current accession mapping file with accession, current genome ID, and taxonomy ID. "
            "Optional when --genome-dir is provided for direct genome uploads."
        ),
    )
    parser.add_argument(
        "--genome-dir",
        type=Path,
        default=None,
        help="Directory of direct genome upload files to use for a blank metadata scaffold.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=out_default,
        help="Output TSV path.",
    )
    parser.add_argument(
        "--template-out",
        type=Path,
        default=template_default,
        help=(
            "Optional project-local header-only TSV scaffold for downstream grouping. "
            "The static repo template lives at config/metadata_template.tsv."
        ),
    )
    parser.add_argument(
        "--allow-missing-legacy",
        action="store_true",
        help=(
            "If set, proceed even when the legacy ecology colorstrip files are unavailable. "
            "The output TSV will still be written from the accession mapping, but ecology labels "
            "will remain blank until the user fills them in."
        ),
    )
    args = parser.parse_args()

    if args.accessions.exists():
        input_rows = _parse_accessions(args.accessions)
        input_label = f"accession mapping {args.accessions}"
    elif args.genome_dir and args.genome_dir.exists():
        input_rows = _parse_genome_dir(args.genome_dir)
        input_label = f"genome files in {args.genome_dir}"
        if not input_rows:
            parser.error(f"--genome-dir has no supported genome files: {args.genome_dir}")
    else:
        if args.genome_dir:
            parser.error(
                f"--accessions file not found: {args.accessions}; "
                f"--genome-dir not found: {args.genome_dir}"
            )
        parser.error(f"--accessions file not found: {args.accessions}")

    missing_legacy = []
    for label, path in [("primary", args.primary), ("secondary", args.secondary)]:
        if not path.exists():
            if args.allow_missing_legacy:
                missing_legacy.append((label, path))
            else:
                parser.error(
                    f"--{label} file not found: {path}. "
                    "Set the flag explicitly or use ECOFUN_PRIMARY / ECOFUN_SECONDARY for the legacy colorstrip files. "
                    "Use --allow-missing-legacy to generate a blank metadata scaffold instead."
                )

    primary = _parse_ecofun_colorstrip(args.primary) if args.primary.exists() else {}
    secondary = _parse_ecofun_colorstrip(args.secondary) if args.secondary.exists() else {}
    alias_map = _build_alias_map()

    rows = []
    unmatched_accessions = []

    # First pass: join current genomes to the original labels.
    for row in input_rows:
        current_name = row["genome_id_current"]
        current_norm = _normalize_name(current_name)
        original_name = ""

        primary_label = primary.get(current_norm, "")
        secondary_label = secondary.get(current_norm, "")

        if not primary_label and not secondary_label:
            alias_name = alias_map.get(current_norm, "")
            if alias_name:
                alias_norm = _normalize_name(alias_name)
                primary_label = primary.get(alias_norm, "")
                secondary_label = secondary.get(alias_norm, "")
                if primary_label or secondary_label:
                    original_name = alias_name

        if not primary_label and not secondary_label:
            unmatched_accessions.append(current_name)

        rows.append(
            {
                "accession": row["accession"],
                "genome_id_current": current_name,
                "taxonomy_id": row["taxonomy_id"],
                "genome_size_mb": row["genome_size_mb"],
                "genome_id_original_if_different": original_name,
                "ecofun_primary": primary_label,
                "ecofun_secondary": secondary_label,
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=METADATA_FIELDS,
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(rows)

    args.template_out.parent.mkdir(parents=True, exist_ok=True)
    with args.template_out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=METADATA_FIELDS,
            delimiter="\t",
        )
        writer.writeheader()

    print(f"Metadata input source: {input_label}")
    print(f"Wrote normalized ecology metadata to {args.out}")
    print(f"Wrote TSV template to {args.template_out}")
    print(f"Matched {sum(1 for r in rows if r['ecofun_primary'] or r['ecofun_secondary'])} of {len(rows)} current genomes")
    if missing_legacy:
        print("Warnings:")
        for label, path in missing_legacy:
            print(f"  - Missing legacy {label} colorstrip: {path}")
        print("  - Proceeded with blank ecology labels where no legacy mapping was available.")
    if unmatched_accessions:
        print("Unmatched current genomes:")
        for name in unmatched_accessions:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
