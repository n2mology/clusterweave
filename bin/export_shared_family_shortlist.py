#!/usr/bin/env python3
"""Export BiG-SCAPE most-shared family summaries for a target genome."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
import sys

BIN_DIR = str(Path(__file__).resolve().parent)
if BIN_DIR not in sys.path:
    sys.path.insert(0, BIN_DIR)

from gcf_view import (
    GCF_PROVENANCE_FIELDS,
    canonical_gcf_category,
    canonical_gcf_threshold,
    clustering_view,
    materialized_gcf_provenance,
)


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "na", "n/a", "none", "-"}:
        return ""
    return text


def to_int(value: object) -> int:
    text = clean(value)
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def read_tsv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def ecology_group(primary_label: str) -> str:
    return clean(primary_label) or "UNLABELED"


def matches_focus_ecology(ecology_value: str, focus_label: str) -> bool:
    return bool(clean(focus_label)) and clean(ecology_value).casefold() == clean(focus_label).casefold()


def region_from_gbk(gbk: str) -> str:
    token = clean(gbk)
    if "__" in token:
        return token.split("__", 1)[1]
    return token


def join_sorted(values: set[str]) -> str:
    return ";".join(sorted(value for value in values if clean(value)))


def ecology_pattern(focus_count: int, other_count: int, focus_label: str) -> str:
    if focus_count and other_count:
        return "mixed"
    if not clean(focus_label):
        return "present"
    if focus_count:
        return "focus_only"
    if other_count:
        return "nonfocus_only"
    return "unlabeled"


def preferred_family_source(families_by_category: dict[str, set[str]]) -> tuple[str, list[str]]:
    if "mix" in families_by_category and families_by_category["mix"]:
        return "mix", sorted(families_by_category["mix"])

    preferred_order = [
        "NRPS.PKS.other.terpene",
        "NRPS.PKS.other",
        "NRPS.PKS.terpene",
        "PKS.other.terpene",
        "NRPS.PKS",
        "PKS.terpene",
        "NRPS.terpene",
        "NRPS.other",
        "PKS.other",
        "other.terpene",
        "NRPS",
        "PKS",
        "terpene",
        "RiPP",
        "other",
    ]
    for category in preferred_order:
        if category in families_by_category and families_by_category[category]:
            return category, sorted(families_by_category[category])

    candidates = [
        (len(families), category, sorted(families))
        for category, families in families_by_category.items()
        if families
    ]
    if not candidates:
        return "", []
    _, category, families = sorted(candidates)[0]
    return category, families


def build_safe_claim_text(row: dict[str, object], genome: str) -> str:
    region = clean(row.get("antismash_region")) or "unresolved region"
    cc = clean(row.get("bigscape_cc"))
    primary_families = clean(row.get("shared_cc_primary_families"))
    record_count = clean(row.get("shared_cc_record_count"))
    genome_count = clean(row.get("shared_cc_dataset_genome_count"))
    annotation = clean(row.get("nearest_mibig_or_annotation_if_available"))

    sentence = (
        f"{genome} {region} belongs to BiG-SCAPE CC {cc} "
        f"({primary_families}) with {record_count} clustered records"
    )
    if genome_count:
        sentence += f" across {genome_count} dataset genomes"
    sentence += "."
    if annotation:
        sentence += f" Annotation hints include {annotation}, but product identity is not assigned."
    else:
        sentence += " Product identity is not assigned."
    return sentence


def public_path_label(path: Path) -> str:
    parts = path.parts
    for index in range(len(parts) - 1):
        if parts[index : index + 2] == ("data", "results"):
            return Path(*parts[index:]).as_posix()
    return path.name


def write_markdown_summary(
    path: Path,
    shortlist_rows: list[dict[str, object]],
    genome: str,
    stage_limit: int,
    global_summary_path: Path,
) -> None:
    stage_rows = [row for row in shortlist_rows if clean(row.get("manual_review_bucket")) == "shared_family_now"]
    overlap_rows = [row for row in stage_rows if clean(row.get("priority_shortlist_bucket")) == "clinker_now"]
    novel_rows = [row for row in stage_rows if clean(row.get("priority_shortlist_bucket")) != "clinker_now"]

    lines = [
        f"# Most-Shared Family Shortlist For {genome}",
        "",
        f"- Genome: `{genome}`",
        f"- Source summary: `{public_path_label(global_summary_path)}`",
        f"- Target rows: `{len(shortlist_rows)}`",
        f"- `shared_family_now`: `{len(stage_rows)}`",
        f"- `shared_family_context`: `{len(shortlist_rows) - len(stage_rows)}`",
        f"- Overlap with confident `clinker_now`: `{len(overlap_rows)}`",
        f"- Shared-family-only additions: `{len(novel_rows)}`",
        "",
        f"Top `{stage_limit}` rows are marked `shared_family_now` for clinker staging.",
        "",
        "## Shared-Family-Only Additions",
        "",
    ]

    if novel_rows:
        for row in novel_rows[:10]:
            lines.extend(
                [
                    f"### Shared rank {row['shared_family_rank']}: {row['antismash_region']}",
                    "",
                    f"- BiG-SCAPE CC: `{row['bigscape_cc']}`",
                    f"- Primary families: `{row['shared_cc_primary_families']}`",
                    f"- Records: `{row['shared_cc_record_count']}`",
                    f"- Dataset genomes: `{row['shared_cc_dataset_genome_count']}`",
                    f"- Priority overlap: `{row['priority_shortlist_bucket'] or 'none'}`",
                    f"- Safe interpretation: {row['safe_claim_text']}",
                    "",
                ]
            )
    else:
        lines.extend(["No shared-family-only additions were identified.", ""])

    lines.extend(["## Overlap With Confident Track", ""])
    if overlap_rows:
        for row in overlap_rows[:10]:
            lines.extend(
                [
                    f"- `{row['antismash_region']}`: CC `{row['bigscape_cc']}`, "
                    f"families `{row['shared_cc_primary_families']}`, records `{row['shared_cc_record_count']}`",
                ]
            )
    else:
        lines.extend(["- No overlap rows were identified."])

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This shortlist captures prevalence across the dataset, not confidence of a product call.",
            "- Use it alongside, not instead of, the confidence-ranked priority shortlist.",
            "- Treat any annotation hint as similarity context only until the clinker/synteny review is complete.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export BiG-SCAPE most-shared connected-component summaries for a target genome."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root containing Code/ and data/.",
    )
    parser.add_argument(
        "--project-name",
        default="clusterweave",
        help="Project name used under data/results.",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=None,
        help=(
            "Explicit normalized metadata TSV. Defaults to the historical "
            "summary_tables/ecofun_metadata_normalized.tsv path."
        ),
    )
    parser.add_argument(
        "--genome",
        default="",
        help="Genome ID to shortlist.",
    )
    parser.add_argument(
        "--ecology-field",
        default="ecofun_primary",
        help="Metadata column used as the ecology label.",
    )
    parser.add_argument(
        "--focus-ecology-label",
        default="",
        help="Optional ecology label to prioritize. Defaults to the target genome's ecology label when available.",
    )
    parser.add_argument(
        "--gcf-category",
        default="mix",
        help="BiG-SCAPE category used for shortlist family logic (default: mix).",
    )
    parser.add_argument(
        "--gcf-threshold",
        default="0.3",
        help="BiG-SCAPE clustering threshold used for shortlist family logic (default: 0.3).",
    )
    parser.add_argument(
        "--stage-limit",
        type=int,
        default=12,
        help="Top shared-family rows to mark as shared_family_now.",
    )
    parser.add_argument(
        "--min-records",
        type=int,
        default=3,
        help="Minimum BiG-SCAPE record count to mark shared_family_now.",
    )
    args = parser.parse_args()
    args.gcf_category = canonical_gcf_category(args.gcf_category)
    args.gcf_threshold = canonical_gcf_threshold(args.gcf_threshold)
    if not clean(args.genome):
        raise ValueError("--genome is required")

    results_root = args.project_root / "data" / "results" / args.project_name
    summary_root = results_root / "summary"
    summary_tables_root = results_root / "summary_tables"
    bigscape_root = results_root / "big_scape" / "output_files"

    metadata_path = args.metadata or (summary_tables_root / "ecofun_metadata_normalized.tsv")
    ranking_path = summary_root / "targeted_candidate_ranking.tsv"
    priority_path = summary_root / "priority_shortlist.tsv"
    annotations_path = next(bigscape_root.rglob("record_annotations.tsv"), None)

    for path in [metadata_path, ranking_path, priority_path]:
        if not path.exists():
            raise FileNotFoundError(f"Required input not found: {path}")

    global_out = summary_root / "bigscape_most_shared_ccs.tsv"
    shortlist_out = summary_root / "shared_family_shortlist.tsv"
    shortlist_md_out = summary_root / "shared_family_shortlist.md"

    metadata_rows = read_tsv_rows(metadata_path)
    ranking_rows = read_tsv_rows(ranking_path)
    priority_rows = read_tsv_rows(priority_path)
    # Zero-region projects have no BiG-SCAPE annotation table. Emit the
    # existing header-only shared-family outputs instead of treating that
    # biological result as a technical failure.
    annotation_rows = read_tsv_rows(annotations_path) if annotations_path is not None else []

    ecology_by_genome: dict[str, str] = {}
    for row in metadata_rows:
        genome = clean(row.get("genome_id_current"))
        if genome:
            ecology_by_genome[genome] = ecology_group(clean(row.get(args.ecology_field)))

    for row in ranking_rows:
        genome = clean(row.get("genome"))
        if genome and genome not in ecology_by_genome:
            ecology_by_genome[genome] = ecology_group(clean(row.get("ecology_group")))

    focus_ecology_label = clean(args.focus_ecology_label) or clean(ecology_by_genome.get(args.genome))

    ranking_by_region: dict[tuple[str, str], dict[str, str]] = {}
    for row in ranking_rows:
        genome = clean(row.get("genome"))
        region = clean(row.get("antismash_region"))
        if genome and region:
            ranking_by_region[(genome, region)] = row

    priority_by_region: dict[str, dict[str, str]] = {}
    for row in priority_rows:
        if clean(row.get("genome")) == args.genome:
            region = clean(row.get("antismash_region"))
            if region:
                priority_by_region[region] = row

    annotation_by_record = {clean(row.get("Record")): row for row in annotation_rows if clean(row.get("Record"))}

    cc_stats: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "records": set(),
            "gbks": set(),
            "families_all": set(),
            "families_by_category": defaultdict(set),
            "categories": set(),
            "classes": set(),
            "organisms": set(),
            "dataset_genomes": set(),
            "focus_genomes": set(),
            "other_genomes": set(),
            "mibig_records": set(),
            "target_regions": set(),
            "target_records": set(),
        }
    )

    for cluster_path in sorted(bigscape_root.rglob("*_clustering_c*.tsv")):
        category_name, clustering_threshold = clustering_view(cluster_path)
        if (
            category_name,
            clustering_threshold,
        ) != (args.gcf_category, args.gcf_threshold):
            continue
        for row in read_tsv_rows(cluster_path):
            cc = clean(row.get("CC"))
            record = clean(row.get("Record"))
            gbk = clean(row.get("GBK"))
            family = clean(row.get("Family"))
            if not cc or not record:
                continue

            bucket = cc_stats[cc]
            bucket["records"].add(record)
            if gbk:
                bucket["gbks"].add(gbk)
            if family:
                bucket["families_all"].add(family)
                bucket["families_by_category"][category_name].add(family)
            bucket["categories"].add(category_name)

            annot_row = annotation_by_record.get(record, {})
            organism = clean(annot_row.get("Organism"))
            class_name = clean(annot_row.get("Class"))
            if organism:
                ecology_by_genome.setdefault(organism, ecology_group(""))
                bucket["organisms"].add(organism)
                bucket["dataset_genomes"].add(organism)
                if matches_focus_ecology(ecology_by_genome[organism], focus_ecology_label):
                    bucket["focus_genomes"].add(organism)
                else:
                    bucket["other_genomes"].add(organism)
            if class_name:
                bucket["classes"].add(class_name)
            if record.startswith("BGC"):
                bucket["mibig_records"].add(record)

            if organism == args.genome or gbk.startswith(f"{args.genome}__"):
                region = region_from_gbk(gbk)
                if region:
                    bucket["target_regions"].add(region)
                bucket["target_records"].add(record)

    global_rows: list[dict[str, object]] = []
    shortlist_rows: list[dict[str, object]] = []

    sorted_ccs = sorted(
        cc_stats.items(),
        key=lambda item: (
            -len(item[1]["records"]),
            -len(item[1]["dataset_genomes"]),
            -len(item[1]["target_regions"]),
            int(item[0]),
        ),
    )

    for cc_rank, (cc, info) in enumerate(sorted_ccs, start=1):
        primary_category, primary_families = preferred_family_source(info["families_by_category"])
        primary_family_text = ";".join(primary_families)
        all_family_text = join_sorted(info["families_all"])
        dataset_genome_count = len(info["dataset_genomes"])
        focus_count = len(info["focus_genomes"])
        other_count = len(info["other_genomes"])

        global_row = {
            "shared_rank": cc_rank,
            "cc": cc,
            "gcf_selected_category": args.gcf_category,
            "gcf_selected_threshold": args.gcf_threshold,
            "primary_family_source": primary_category,
            "primary_families": primary_family_text,
            "all_family_aliases": all_family_text,
            "record_count": len(info["records"]),
            "dataset_genome_count": dataset_genome_count,
            "focus_ecology_label": focus_ecology_label,
            "focus_genome_count": focus_count,
            "nonfocus_genome_count": other_count,
            "ecology_pattern": ecology_pattern(focus_count, other_count, focus_ecology_label),
            "categories": join_sorted(info["categories"]),
            "classes": join_sorted(info["classes"]),
            "mibig_record_count": len(info["mibig_records"]),
            "target_genome_present": "yes" if info["target_regions"] else "no",
            "target_region_count": len(info["target_regions"]),
            "target_regions": join_sorted(info["target_regions"]),
        }
        global_rows.append(global_row)

        if not info["target_regions"]:
            continue

        for region in sorted(info["target_regions"]):
            ranking_row = ranking_by_region.get((args.genome, region), {})
            priority_row = priority_by_region.get(region, {})
            gcf_provenance = materialized_gcf_provenance(
                ranking_row,
                fallback_selected_id=primary_family_text,
                fallback_category=args.gcf_category,
                fallback_threshold=args.gcf_threshold,
            )
            if not gcf_provenance["gcf_id"]:
                gcf_provenance["gcf_id"] = all_family_text or primary_family_text
            shortlist_rows.append(
                {
                    "shared_family_rank": 0,
                    "manual_review_bucket": "",
                    "selection_track": "most_shared_bigscape_cc",
                    "bigscape_cc": cc,
                    "shared_cc_primary_family_source": primary_category,
                    "shared_cc_primary_families": primary_family_text,
                    "shared_cc_all_family_aliases": all_family_text,
                    "shared_cc_record_count": len(info["records"]),
                    "shared_cc_dataset_genome_count": dataset_genome_count,
                    "focus_ecology_label": focus_ecology_label,
                    "shared_cc_focus_genome_count": focus_count,
                    "shared_cc_nonfocus_genome_count": other_count,
                    "shared_cc_ecology_pattern": ecology_pattern(focus_count, other_count, focus_ecology_label),
                    "shared_cc_categories": join_sorted(info["categories"]),
                    "shared_cc_classes": join_sorted(info["classes"]),
                    "shared_cc_target_region_count": len(info["target_regions"]),
                    "priority_shortlist_bucket": clean(priority_row.get("manual_review_bucket")),
                    "rank": clean(ranking_row.get("rank")),
                    "priority_score": clean(ranking_row.get("priority_score")),
                    "priority_tier": clean(ranking_row.get("priority_tier")),
                    "genome": args.genome,
                    "ecology_group": clean(ranking_row.get("ecology_group")) or ecology_by_genome.get(args.genome, "UNLABELED"),
                    "antismash_region": region,
                    "funbgcex_cluster": clean(ranking_row.get("funbgcex_cluster")),
                    "antismash_class": clean(ranking_row.get("antismash_class")) or join_sorted(info["classes"]),
                    **gcf_provenance,
                    "gcf_ecology_pattern": clean(ranking_row.get("gcf_ecology_pattern")),
                    "gcf_genome_count": clean(ranking_row.get("gcf_genome_count")),
                    "gcf_focus_genome_count": clean(ranking_row.get("gcf_focus_genome_count")),
                    "gcf_nonfocus_genome_count": clean(ranking_row.get("gcf_nonfocus_genome_count")),
                    "consensus_support": clean(ranking_row.get("consensus_support")),
                    "annotation_support_tier": clean(ranking_row.get("annotation_support_tier")),
                    "nearest_mibig_or_annotation_if_available": clean(
                        ranking_row.get("nearest_mibig_or_annotation_if_available")
                    ),
                    "antismash_knowncluster_product": clean(ranking_row.get("antismash_knowncluster_product")),
                    "funbgcex_putative_product": clean(ranking_row.get("funbgcex_putative_product")),
                    "recommended_followup": clean(ranking_row.get("recommended_followup"))
                    or "compare this broadly shared BiG-SCAPE family by clinker before making product-level claims",
                    "ranking_rationale": clean(ranking_row.get("ranking_rationale")),
                    "safe_claim_text": "",
                }
            )

    shortlist_rows.sort(
        key=lambda row: (
            -to_int(row.get("shared_cc_record_count")),
            -to_int(row.get("shared_cc_dataset_genome_count")),
            to_int(row.get("rank")) if clean(row.get("rank")) else 10**9,
            clean(row.get("antismash_region")),
        )
    )

    for idx, row in enumerate(shortlist_rows, start=1):
        row["shared_family_rank"] = idx
        row["manual_review_bucket"] = (
            "shared_family_now"
            if idx <= args.stage_limit and to_int(row.get("shared_cc_record_count")) >= args.min_records
            else "shared_family_context"
        )
        row["safe_claim_text"] = build_safe_claim_text(row, args.genome)

    write_tsv(
        global_out,
        [
            "shared_rank",
            "cc",
            "gcf_selected_category",
            "gcf_selected_threshold",
            "primary_family_source",
            "primary_families",
            "all_family_aliases",
            "record_count",
            "dataset_genome_count",
            "focus_ecology_label",
            "focus_genome_count",
            "nonfocus_genome_count",
            "ecology_pattern",
            "categories",
            "classes",
            "mibig_record_count",
            "target_genome_present",
            "target_region_count",
            "target_regions",
        ],
        global_rows,
    )

    write_tsv(
        shortlist_out,
        [
            "shared_family_rank",
            "manual_review_bucket",
            "selection_track",
            "bigscape_cc",
            "shared_cc_primary_family_source",
            "shared_cc_primary_families",
            "shared_cc_all_family_aliases",
            "shared_cc_record_count",
            "shared_cc_dataset_genome_count",
            "focus_ecology_label",
            "shared_cc_focus_genome_count",
            "shared_cc_nonfocus_genome_count",
            "shared_cc_ecology_pattern",
            "shared_cc_categories",
            "shared_cc_classes",
            "shared_cc_target_region_count",
            "priority_shortlist_bucket",
            "rank",
            "priority_score",
            "priority_tier",
            "genome",
            "ecology_group",
            "antismash_region",
            "funbgcex_cluster",
            "antismash_class",
            *GCF_PROVENANCE_FIELDS,
            "gcf_ecology_pattern",
            "gcf_genome_count",
            "gcf_focus_genome_count",
            "gcf_nonfocus_genome_count",
            "consensus_support",
            "annotation_support_tier",
            "nearest_mibig_or_annotation_if_available",
            "antismash_knowncluster_product",
            "funbgcex_putative_product",
            "recommended_followup",
            "ranking_rationale",
            "safe_claim_text",
        ],
        shortlist_rows,
    )

    write_markdown_summary(shortlist_md_out, shortlist_rows, args.genome, args.stage_limit, global_out)

    print(f"Wrote BiG-SCAPE shared CC summary: {global_out}")
    print(f"Wrote shared-family shortlist TSV: {shortlist_out}")
    print(f"Wrote shared-family shortlist Markdown: {shortlist_md_out}")


if __name__ == "__main__":
    main()
