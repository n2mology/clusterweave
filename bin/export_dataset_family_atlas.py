#!/usr/bin/env python3
"""Export a dataset-wide BiG-SCAPE family atlas for no-target clinker staging."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


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


def atlas_candidate_sort_key(row: dict[str, str]) -> tuple[object, ...]:
    return (
        to_int(row.get("rank")) if clean(row.get("rank")) else 10**9,
        -to_int(row.get("priority_score")),
        clean(row.get("genome")),
        clean(row.get("antismash_region")),
    )


def region_key_from_row(row: dict[str, object]) -> tuple[str, str]:
    return (clean(row.get("genome")), clean(row.get("antismash_region")))


def assign_atlas_review_buckets(
    shortlist_rows: list[dict[str, object]],
    candidate_regions_by_cc: dict[str, set[tuple[str, str]]],
    stage_limit: int,
    min_records: int,
) -> None:
    staged_count = 0
    covered_regions: set[tuple[str, str]] = set()

    for idx, row in enumerate(shortlist_rows, start=1):
        row["atlas_rank"] = idx
        representative_key = region_key_from_row(row)
        cc_regions = {
            key
            for key in candidate_regions_by_cc.get(clean(row.get("bigscape_cc")), set())
            if key[0] and key[1]
        }
        if representative_key[0] and representative_key[1]:
            cc_regions.add(representative_key)

        is_new_representative = not (
            representative_key[0] and representative_key[1] and representative_key in covered_regions
        )
        should_stage = (
            staged_count < stage_limit
            and to_int(row.get("shared_cc_record_count")) >= min_records
            and is_new_representative
        )
        row["manual_review_bucket"] = "atlas_now" if should_stage else "atlas_context"

        if should_stage:
            staged_count += 1
            covered_regions.update(cc_regions)


def build_safe_claim_text(row: dict[str, object]) -> str:
    genome = clean(row.get("genome")) or "unresolved genome"
    region = clean(row.get("antismash_region")) or "unresolved region"
    cc = clean(row.get("bigscape_cc"))
    primary_families = clean(row.get("shared_cc_primary_families"))
    record_count = clean(row.get("shared_cc_record_count"))
    genome_count = clean(row.get("shared_cc_dataset_genome_count"))
    annotation = clean(row.get("nearest_mibig_or_annotation_if_available"))

    sentence = (
        f"{genome} {region} represents BiG-SCAPE CC {cc} "
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
    if "data" in parts:
        return Path(*parts[parts.index("data") :]).as_posix()
    return path.name


def write_markdown_summary(
    path: Path,
    shortlist_rows: list[dict[str, object]],
    global_summary_path: Path,
    stage_limit: int,
) -> None:
    stage_rows = [row for row in shortlist_rows if clean(row.get("manual_review_bucket")) == "atlas_now"]
    context_rows = [row for row in shortlist_rows if clean(row.get("manual_review_bucket")) != "atlas_now"]

    lines = [
        "# Dataset-Wide Family Atlas",
        "",
        f"- Source summary: `{public_path_label(global_summary_path)}`",
        f"- Representative family rows: `{len(shortlist_rows)}`",
        f"- `atlas_now`: `{len(stage_rows)}`",
        f"- `atlas_context`: `{len(context_rows)}`",
        "",
        f"Up to `{stage_limit}` nonredundant rows are marked `atlas_now` for clinker staging.",
        "",
        "## Atlas-Now Families",
        "",
    ]

    if stage_rows:
        for row in stage_rows[:10]:
            lines.extend(
                [
                    f"### Atlas rank {row['atlas_rank']}: {row['genome']} {row['antismash_region']}",
                    "",
                    f"- BiG-SCAPE CC: `{row['bigscape_cc']}`",
                    f"- Primary families: `{row['shared_cc_primary_families']}`",
                    f"- Records: `{row['shared_cc_record_count']}`",
                    f"- Dataset genomes: `{row['shared_cc_dataset_genome_count']}`",
                    f"- Representative global rank: `{row['rank'] or 'NA'}`",
                    f"- Recommended follow-up: {row['recommended_followup']}",
                    f"- Safe interpretation: {row['safe_claim_text']}",
                    "",
                ]
            )
    else:
        lines.extend(["No atlas_now families were identified.", ""])

    lines.extend(
        [
            "## Notes",
            "",
            "- This atlas is dataset-wide and intentionally not tied to a single target genome.",
            "- Use it to identify broadly informative families before switching to target-specific clinker review.",
            "- Set `TARGET_GENOME` later when you want genome-specific priority and shared-family synteny panels.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a dataset-wide BiG-SCAPE family atlas for clinker staging."
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
        "--ecology-field",
        default="ecofun_primary",
        help="Metadata column used as the ecology label.",
    )
    parser.add_argument(
        "--focus-ecology-label",
        default="",
        help="Optional ecology label to annotate focus counts.",
    )
    parser.add_argument(
        "--stage-limit",
        type=int,
        default=12,
        help="Top atlas rows to mark as atlas_now.",
    )
    parser.add_argument(
        "--min-records",
        type=int,
        default=2,
        help="Minimum BiG-SCAPE record count to mark atlas_now.",
    )
    args = parser.parse_args()

    results_root = args.project_root / "data" / "results" / args.project_name
    summary_root = results_root / "summary"
    summary_tables_root = results_root / "summary_tables"
    bigscape_root = results_root / "big_scape" / "output_files"

    metadata_path = summary_tables_root / "ecofun_metadata_normalized.tsv"
    ranking_path = summary_root / "targeted_candidate_ranking.tsv"
    annotations_path = next(bigscape_root.rglob("record_annotations.tsv"), None)

    if annotations_path is None:
        raise FileNotFoundError(f"record_annotations.tsv not found under: {bigscape_root}")
    if not ranking_path.exists():
        raise FileNotFoundError(f"Required input not found: {ranking_path}")

    metadata_rows = read_tsv_rows(metadata_path) if metadata_path.exists() else []
    ranking_rows = read_tsv_rows(ranking_path)
    annotation_rows = read_tsv_rows(annotations_path)

    global_out = summary_root / "bigscape_family_atlas.tsv"
    shortlist_out = summary_root / "family_atlas_shortlist.tsv"
    shortlist_md_out = summary_root / "family_atlas_shortlist.md"

    ecology_by_genome: dict[str, str] = {}
    for row in metadata_rows:
        genome = clean(row.get("genome_id_current"))
        if genome:
            ecology_by_genome[genome] = ecology_group(clean(row.get(args.ecology_field)))
    for row in ranking_rows:
        genome = clean(row.get("genome"))
        if genome and genome not in ecology_by_genome:
            ecology_by_genome[genome] = ecology_group(clean(row.get("ecology_group")))

    focus_ecology_label = clean(args.focus_ecology_label)

    ranking_by_region: dict[tuple[str, str], dict[str, str]] = {}
    for row in ranking_rows:
        genome = clean(row.get("genome"))
        region = clean(row.get("antismash_region"))
        if genome and region:
            ranking_by_region[(genome, region)] = row

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
            "candidate_regions": set(),
        }
    )

    for cluster_path in sorted(bigscape_root.rglob("*_clustering_c0.3.tsv")):
        category_name = cluster_path.parent.name
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

            region = region_from_gbk(gbk)
            if organism and region and (organism, region) in ranking_by_region:
                bucket["candidate_regions"].add((organism, region))

    global_rows: list[dict[str, object]] = []
    shortlist_rows: list[dict[str, object]] = []
    candidate_regions_by_cc: dict[str, set[tuple[str, str]]] = {}

    sorted_ccs = sorted(
        cc_stats.items(),
        key=lambda item: (
            -len(item[1]["records"]),
            -len(item[1]["dataset_genomes"]),
            -len(item[1]["candidate_regions"]),
            int(item[0]),
        ),
    )

    for cc_rank, (cc, info) in enumerate(sorted_ccs, start=1):
        candidate_regions_by_cc[cc] = set(info["candidate_regions"])
        primary_category, primary_families = preferred_family_source(info["families_by_category"])
        primary_family_text = ";".join(primary_families)
        all_family_text = join_sorted(info["families_all"])
        dataset_genome_count = len(info["dataset_genomes"])
        focus_count = len(info["focus_genomes"])
        other_count = len(info["other_genomes"])

        representative_row: dict[str, str] | None = None
        candidate_rows = [ranking_by_region[key] for key in sorted(info["candidate_regions"]) if key in ranking_by_region]
        if candidate_rows:
            representative_row = sorted(candidate_rows, key=atlas_candidate_sort_key)[0]

        global_rows.append(
            {
                "atlas_rank": cc_rank,
                "cc": cc,
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
                "candidate_region_count": len(info["candidate_regions"]),
                "representative_genome": clean(representative_row.get("genome")) if representative_row else "",
                "representative_region": clean(representative_row.get("antismash_region")) if representative_row else "",
                "representative_global_rank": clean(representative_row.get("rank")) if representative_row else "",
                "representative_priority_score": clean(representative_row.get("priority_score")) if representative_row else "",
                "representative_annotation": clean(representative_row.get("nearest_mibig_or_annotation_if_available")) if representative_row else "",
            }
        )

        if representative_row is None:
            continue

        shortlist_rows.append(
            {
                "atlas_rank": 0,
                "manual_review_bucket": "",
                "selection_track": "dataset_family_atlas",
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
                "shared_cc_target_region_count": len(info["candidate_regions"]),
                "priority_shortlist_bucket": "",
                "rank": clean(representative_row.get("rank")),
                "priority_score": clean(representative_row.get("priority_score")),
                "priority_tier": clean(representative_row.get("priority_tier")),
                "genome": clean(representative_row.get("genome")),
                "ecology_group": clean(representative_row.get("ecology_group")) or ecology_by_genome.get(clean(representative_row.get("genome")), "UNLABELED"),
                "antismash_region": clean(representative_row.get("antismash_region")),
                "funbgcex_cluster": clean(representative_row.get("funbgcex_cluster")),
                "antismash_class": clean(representative_row.get("antismash_class")) or join_sorted(info["classes"]),
                "gcf_id": clean(representative_row.get("gcf_id")) or primary_family_text or all_family_text,
                "gcf_ecology_pattern": clean(representative_row.get("gcf_ecology_pattern")),
                "gcf_genome_count": clean(representative_row.get("gcf_genome_count")) or str(dataset_genome_count),
                "gcf_focus_genome_count": clean(representative_row.get("gcf_focus_genome_count")) or str(focus_count),
                "gcf_nonfocus_genome_count": clean(representative_row.get("gcf_nonfocus_genome_count")) or str(other_count),
                "consensus_support": clean(representative_row.get("consensus_support")),
                "annotation_support_tier": clean(representative_row.get("annotation_support_tier")),
                "nearest_mibig_or_annotation_if_available": clean(
                    representative_row.get("nearest_mibig_or_annotation_if_available")
                ),
                "antismash_knowncluster_product": clean(representative_row.get("antismash_knowncluster_product")),
                "funbgcex_putative_product": clean(representative_row.get("funbgcex_putative_product")),
                "recommended_followup": clean(representative_row.get("recommended_followup"))
                or "review this dataset-wide BiG-SCAPE family by clinker before narrowing to a target genome",
                "ranking_rationale": clean(representative_row.get("ranking_rationale")),
                "safe_claim_text": "",
            }
        )

    shortlist_rows.sort(
        key=lambda row: (
            -to_int(row.get("shared_cc_record_count")),
            -to_int(row.get("shared_cc_dataset_genome_count")),
            to_int(row.get("rank")) if clean(row.get("rank")) else 10**9,
            clean(row.get("genome")),
            clean(row.get("antismash_region")),
        )
    )

    assign_atlas_review_buckets(shortlist_rows, candidate_regions_by_cc, args.stage_limit, args.min_records)
    for row in shortlist_rows:
        row["safe_claim_text"] = build_safe_claim_text(row)

    write_tsv(
        global_out,
        [
            "atlas_rank",
            "cc",
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
            "candidate_region_count",
            "representative_genome",
            "representative_region",
            "representative_global_rank",
            "representative_priority_score",
            "representative_annotation",
        ],
        global_rows,
    )

    write_tsv(
        shortlist_out,
        [
            "atlas_rank",
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
            "gcf_id",
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

    write_markdown_summary(shortlist_md_out, shortlist_rows, global_out, args.stage_limit)

    print(f"Wrote dataset family atlas summary: {global_out}")
    print(f"Wrote family atlas shortlist TSV: {shortlist_out}")
    print(f"Wrote family atlas shortlist Markdown: {shortlist_md_out}")


if __name__ == "__main__":
    main()
