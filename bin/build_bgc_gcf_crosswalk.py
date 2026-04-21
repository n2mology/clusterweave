#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable


def norm_key(value: str | None) -> str:
    """Normalize names so underscore / punctuation differences do not break joins."""
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text in {"", "-", "na", "n/a", "none"}:
        return ""
    return text


def read_tsv_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle, delimiter="\t")


def read_csv_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def build_gbk_key(genome: str, antismash_region: str) -> str:
    return f"{genome}__{antismash_region}"


def build_record_key(gbk_key: str, antismash_region: str) -> str:
    match = re.search(r"region0*([0-9]+)$", antismash_region)
    region_no = match.group(1) if match else "1"
    return f"{gbk_key}.gbk_region_{int(region_no)}"


def parse_annotations_table(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    by_record: dict[str, dict[str, str]] = {}
    by_gbk: dict[str, dict[str, str]] = {}
    if not path.exists():
        return by_record, by_gbk
    for row in read_tsv_rows(path):
        record = clean(row.get("Record"))
        gbk = clean(row.get("GBK"))
        if record:
            by_record[norm_key(record)] = row
        if gbk:
            by_gbk[norm_key(gbk)] = row
    return by_record, by_gbk


def parse_bigscape_clusters(bigscape_root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, str]]]:
    """Return record->families, gbk->families, and one representative annotation row per record."""
    record_to_families: dict[str, set[str]] = defaultdict(set)
    gbk_to_families: dict[str, set[str]] = defaultdict(set)
    representative_rows: dict[str, dict[str, str]] = {}
    for path in bigscape_root.rglob("*_clustering_c0.3.tsv"):
        for row in read_tsv_rows(path):
            record = clean(row.get("Record"))
            gbk = clean(row.get("GBK"))
            family = clean(row.get("Family"))
            cc = clean(row.get("CC"))
            gcf_id = family if family else (f"CC_{cc}" if cc else "")
            if record and gcf_id:
                record_to_families[norm_key(record)].add(gcf_id)
                representative_rows.setdefault(norm_key(record), row)
            if gbk and gcf_id:
                gbk_to_families[norm_key(gbk)].add(gcf_id)
                representative_rows.setdefault(norm_key(gbk), row)
    return record_to_families, gbk_to_families, representative_rows


def join_family_ids(*family_sets: set[str]) -> str:
    families: set[str] = set()
    for s in family_sets:
        families.update(s)
    if not families:
        return ""
    return ";".join(sorted(families))


def choose_nearest_annotation(row: dict[str, str]) -> str:
    known_acc = clean(row.get("antismash_knowncluster_accession"))
    known_product = clean(row.get("antismash_knowncluster_product"))
    cluster_compare_products = clean(row.get("antismash_clustercompare_compounds"))
    cluster_compare_score = clean(row.get("antismash_clustercompare_similarity_score"))
    funbgc_similar = clean(row.get("funbgcex_similar_bgc"))
    funbgc_product = clean(row.get("funbgcex_putative_product"))
    funbgc_score = clean(row.get("funbgcex_similarity_score"))

    parts: list[str] = []
    if known_acc:
        if known_product:
            parts.append(f"{known_acc} | {known_product}")
        else:
            parts.append(known_acc)
    elif known_product:
        parts.append(known_product)

    if cluster_compare_products:
        if cluster_compare_score:
            parts.append(f"clustercompare {cluster_compare_score}: {cluster_compare_products}")
        else:
            parts.append(f"clustercompare: {cluster_compare_products}")

    if funbgc_similar or funbgc_product:
        label = funbgc_similar if funbgc_similar else "FunBGCeX"
        if funbgc_product:
            if funbgc_score:
                parts.append(f"{label} {funbgc_score}: {funbgc_product}")
            else:
                parts.append(f"{label}: {funbgc_product}")
        else:
            parts.append(label)

    return "; ".join(parts)


def build_notes(
    row: dict[str, str],
    bigscape_record: str,
    gcf_id: str,
    record_join_mode: str,
    family_count: int,
) -> str:
    notes: list[str] = []
    overlap_bp = clean(row.get("overlap_bp"))
    if overlap_bp:
        notes.append(f"overlap_bp={overlap_bp}")
    if bigscape_record:
        notes.append(f"bigscape_record={bigscape_record}")
    if gcf_id:
        notes.append(f"gcf_join={record_join_mode}")
        notes.append(f"gcf_id_count={family_count}")
    antismash_present = bool(clean(row.get("antismash_bgc_id")))
    funbgcex_present = bool(clean(row.get("funbgcex_bgc_id")))
    if antismash_present and funbgcex_present:
        notes.append("consensus=antiSMASH+FunBGCeX")
    elif antismash_present:
        notes.append("consensus=antiSMASH-only")
    elif funbgcex_present:
        notes.append("consensus=FunBGCeX-only")
    if clean(row.get("same_putative_product_exact")) == "yes" or clean(row.get("same_putative_product_keyword")) == "yes":
        notes.append("same_putative_product=yes")
    return "; ".join(notes)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a BGC/GCF crosswalk TSV from the active ClusterWeave project outputs."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root containing Data/Results and Code directories.",
    )
    parser.add_argument(
        "--project-name",
        default="clusterweave",
        help="Project name used under Data/Results.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output TSV path. Defaults to Data/Results/<project-name>/summary/candidate_bgc_gcf_crosswalk.tsv",
    )
    args = parser.parse_args()

    projects_root = args.project_root
    data_root = projects_root / "Data" / "Results" / args.project_name
    comparison_csv = data_root / "summary" / "all_tools_bgc_comparison.csv"
    bigscape_root = data_root / "big_scape" / "output_files"
    record_annotations_path = next(bigscape_root.rglob("record_annotations.tsv"), None)

    if not comparison_csv.exists():
        raise FileNotFoundError(f"Comparison table not found: {comparison_csv}")
    if not bigscape_root.exists():
        raise FileNotFoundError(f"Big-SCAPE output directory not found: {bigscape_root}")

    out_path = args.output
    if out_path is None:
        out_path = data_root / "summary" / "candidate_bgc_gcf_crosswalk.tsv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    record_to_families, gbk_to_families, representative_rows = parse_bigscape_clusters(bigscape_root)
    annotation_by_record: dict[str, dict[str, str]] = {}
    annotation_by_gbk: dict[str, dict[str, str]] = {}
    if record_annotations_path is not None:
        annotation_by_record, annotation_by_gbk = parse_annotations_table(record_annotations_path)

    output_rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for row in read_csv_rows(comparison_csv):
        genome = clean(row.get("genome"))
        antismash_region = clean(row.get("antismash_bgc_id"))
        antismash_class = clean(row.get("antismash_bgc_class"))
        funbgcex_cluster = clean(row.get("funbgcex_bgc_id"))

        if not antismash_region and not funbgcex_cluster:
            continue

        gbk_key = build_gbk_key(genome, antismash_region) if genome and antismash_region else ""
        record_key = build_record_key(gbk_key, antismash_region) if gbk_key else ""

        annot_row = {}
        join_mode = "none"
        if record_key and norm_key(record_key) in annotation_by_record:
            annot_row = annotation_by_record[norm_key(record_key)]
            join_mode = "exact_record"
        elif gbk_key and norm_key(gbk_key) in annotation_by_gbk:
            annot_row = annotation_by_gbk[norm_key(gbk_key)]
            join_mode = "exact_gbk"
        else:
            # Try partial matching when the exact record key is unavailable.
            if gbk_key:
                gbk_norm = norm_key(gbk_key)
                for key, candidate in annotation_by_gbk.items():
                    if key.startswith(gbk_norm) or gbk_norm.startswith(key):
                        annot_row = candidate
                        join_mode = "fuzzy_gbk"
                        break

        bigscape_record = clean(annot_row.get("Record")) if annot_row else ""
        family_from_record = record_to_families.get(norm_key(bigscape_record), set()) if bigscape_record else set()
        family_from_gbk = gbk_to_families.get(norm_key(clean(annot_row.get("GBK"))) if annot_row else norm_key(gbk_key), set()) if (annot_row or gbk_key) else set()
        gcf_id = join_family_ids(family_from_record, family_from_gbk)
        family_count = len(gcf_id.split(";")) if gcf_id else 0

        # If the record annotation table was not found, fall back to the clustering row that matches the GBK key.
        if not bigscape_record and gbk_key:
            representative = representative_rows.get(norm_key(gbk_key))
            if representative:
                bigscape_record = clean(representative.get("Record"))
                if not gcf_id:
                    gcf_id = clean(representative.get("Family")) or (f"CC_{clean(representative.get('CC'))}" if clean(representative.get("CC")) else "")
                    family_count = len(gcf_id.split(";")) if gcf_id else 0
                    join_mode = "cluster_table_fallback"

        nearest_annotation = choose_nearest_annotation(row)
        if not nearest_annotation and annot_row:
            desc = clean(annot_row.get("Description"))
            if desc:
                nearest_annotation = desc

        notes = build_notes(row, bigscape_record, gcf_id, join_mode, family_count)
        if annot_row and clean(annot_row.get("Organism")):
            notes = "; ".join([notes, f"bigscape_organism={clean(annot_row.get('Organism'))}"]) if notes else f"bigscape_organism={clean(annot_row.get('Organism'))}"

        candidate = {
            "genome": genome,
            "antismash_region": antismash_region,
            "antismash_class": antismash_class,
            "bigscape_record": bigscape_record,
            "gcf_id": gcf_id,
            "nearest_mibig_or_annotation_if_available": nearest_annotation,
            "funbgcex_cluster": funbgcex_cluster,
            "notes": notes,
        }

        dedupe_key = (
            candidate["genome"],
            candidate["antismash_region"],
            candidate["funbgcex_cluster"],
            candidate["bigscape_record"],
            candidate["gcf_id"],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        output_rows.append(candidate)

    output_rows.sort(key=lambda r: (norm_key(r["genome"]), norm_key(r["antismash_region"]), norm_key(r["funbgcex_cluster"]), norm_key(r["gcf_id"])))

    fields = [
        "genome",
        "antismash_region",
        "antismash_class",
        "bigscape_record",
        "gcf_id",
        "nearest_mibig_or_annotation_if_available",
        "funbgcex_cluster",
        "notes",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Wrote {len(output_rows)} crosswalk rows to {out_path}")


if __name__ == "__main__":
    main()
