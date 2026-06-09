#!/usr/bin/env python3
"""Export a target-genome priority shortlist from the project ranking table."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
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


def build_manual_review_bucket(row: dict[str, str]) -> str:
    tier = clean(row.get("priority_tier"))
    consensus = clean(row.get("consensus_support"))
    gcf_id = clean(row.get("gcf_id"))
    annotation_tier = clean(row.get("annotation_support_tier"))

    if (
        tier == "tier_1"
        and consensus == "antiSMASH+FunBGCeX"
        and gcf_id
        and annotation_tier in {"knowncluster_high", "knowncluster_moderate", "clustercompare_hint"}
    ):
        return "clinker_now"
    if tier == "tier_1":
        return "manual_table_now"
    if tier == "tier_2" and gcf_id:
        return "hold_for_context_review"
    return "defer"


def build_safe_claim_text(row: dict[str, str], genome: str) -> str:
    region = clean(row.get("antismash_region")) or clean(row.get("funbgcex_cluster")) or "unresolved region"
    gcf_id = clean(row.get("gcf_id"))
    class_name = clean(row.get("antismash_class")) or "unclassified"
    consensus = clean(row.get("consensus_support"))
    gcf_pattern = clean(row.get("gcf_ecology_pattern"))
    gcf_genomes = clean(row.get("gcf_genome_count"))
    annotation = clean(row.get("nearest_mibig_or_annotation_if_available"))

    claim_parts: list[str] = [f"{genome} {region} is a {class_name} candidate"]

    if gcf_id:
        gcf_text = f"in {gcf_id}"
        if gcf_genomes:
            gcf_text += f" detected in {gcf_genomes} genomes"
        if gcf_pattern:
            gcf_text += f" with a {gcf_pattern} ecology pattern"
        claim_parts.append(gcf_text)

    if consensus:
        claim_parts.append(f"with {consensus} support")

    sentence = " ".join(claim_parts).strip()
    if annotation:
        sentence += f". Annotation hints include {annotation}, but product identity is not assigned."
    else:
        sentence += ". Product identity is not assigned."
    return sentence


def write_markdown_summary(
    path: Path,
    selected_rows: list[dict[str, object]],
    genome: str,
    input_path: Path,
) -> None:
    bucket_counts = Counter(str(row["manual_review_bucket"]) for row in selected_rows)
    top_rows = [row for row in selected_rows if row["manual_review_bucket"] == "clinker_now"][:12]

    lines: list[str] = [
        f"# Priority Shortlist For {genome}",
        "",
        f"- Genome: `{genome}`",
        f"- Source ranking: `{input_path}`",
        f"- Shortlisted rows: `{len(selected_rows)}`",
        f"- `clinker_now`: `{bucket_counts.get('clinker_now', 0)}`",
        f"- `manual_table_now`: `{bucket_counts.get('manual_table_now', 0)}`",
        f"- `hold_for_context_review`: `{bucket_counts.get('hold_for_context_review', 0)}`",
        f"- `defer`: `{bucket_counts.get('defer', 0)}`",
        "",
        "## Top Manual Synteny Targets",
        "",
    ]

    if not top_rows:
        lines.extend(
            [
                "No `clinker_now` candidates were identified under the current rules.",
                "",
            ]
        )
    else:
        for row in top_rows:
            lines.extend(
                [
                    f"### Rank {row['rank']}: {row['antismash_region'] or row['funbgcex_cluster']}",
                    "",
                    f"- Class: `{row['antismash_class']}`",
                    f"- GCF: `{row['gcf_id']}`",
                    f"- Consensus: `{row['consensus_support']}`",
                    f"- Annotation tier: `{row['annotation_support_tier']}`",
                    f"- Follow-up: {row['recommended_followup']}",
                    f"- Safe interpretation: {row['safe_claim_text']}",
                    "",
                ]
            )

    lines.extend(
        [
            "## Notes",
            "",
            "- This shortlist is ranking-driven and is intended to reduce the manual review set.",
            "- It is not a product-assignment table.",
            "- NPLinker should be treated as exploratory and checked separately.",
            "",
        ]
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a target-genome priority shortlist from targeted_candidate_ranking.tsv."
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
        "--genome",
        default="",
        help="Genome ID to shortlist.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output TSV path. Defaults to the project summary directory.",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=None,
        help="Optional Markdown summary path. Defaults to the project summary directory.",
    )
    args = parser.parse_args()

    results_root = args.project_root / "data" / "results" / args.project_name
    summary_root = results_root / "summary"
    ranking_path = summary_root / "targeted_candidate_ranking.tsv"
    if not ranking_path.exists():
        raise FileNotFoundError(f"Ranking table not found: {ranking_path}")

    if not clean(args.genome):
        raise ValueError("--genome is required")

    output_path = args.output or (summary_root / "priority_shortlist.tsv")
    markdown_path = args.markdown_output or (summary_root / "priority_shortlist.md")

    rows = read_tsv_rows(ranking_path)
    filtered_rows = [row for row in rows if clean(row.get("genome")) == args.genome]
    if not filtered_rows:
        raise ValueError(f"No ranking rows found for genome: {args.genome}")

    filtered_rows = [
        row
        for row in filtered_rows
        if clean(row.get("priority_tier")) in {"tier_1", "tier_2"}
    ]
    filtered_rows.sort(key=lambda row: (to_int(row.get("rank")), -to_int(row.get("priority_score"))))

    selected_rows: list[dict[str, object]] = []
    for shortlist_rank, row in enumerate(filtered_rows, start=1):
        selected_rows.append(
            {
                "shortlist_rank": shortlist_rank,
                "manual_review_bucket": build_manual_review_bucket(row),
                "rank": clean(row.get("rank")),
                "priority_score": clean(row.get("priority_score")),
                "priority_tier": clean(row.get("priority_tier")),
                "genome": clean(row.get("genome")),
                "antismash_region": clean(row.get("antismash_region")),
                "funbgcex_cluster": clean(row.get("funbgcex_cluster")),
                "antismash_class": clean(row.get("antismash_class")),
                "gcf_id": clean(row.get("gcf_id")),
                "gcf_ecology_pattern": clean(row.get("gcf_ecology_pattern")),
                "gcf_genome_count": clean(row.get("gcf_genome_count")),
                "focus_ecology_label": clean(row.get("focus_ecology_label")),
                "gcf_focus_genome_count": clean(row.get("gcf_focus_genome_count")),
                "gcf_nonfocus_genome_count": clean(row.get("gcf_nonfocus_genome_count")),
                "consensus_support": clean(row.get("consensus_support")),
                "annotation_support_tier": clean(row.get("annotation_support_tier")),
                "nearest_mibig_or_annotation_if_available": clean(
                    row.get("nearest_mibig_or_annotation_if_available")
                ),
                "antismash_knowncluster_product": clean(row.get("antismash_knowncluster_product")),
                "funbgcex_putative_product": clean(row.get("funbgcex_putative_product")),
                "recommended_followup": clean(row.get("recommended_followup")),
                "ranking_rationale": clean(row.get("ranking_rationale")),
                "safe_claim_text": build_safe_claim_text(row, args.genome),
            }
        )

    fieldnames = [
        "shortlist_rank",
        "manual_review_bucket",
        "rank",
        "priority_score",
        "priority_tier",
        "genome",
        "antismash_region",
        "funbgcex_cluster",
        "antismash_class",
        "gcf_id",
        "gcf_ecology_pattern",
        "gcf_genome_count",
        "focus_ecology_label",
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
    ]
    write_tsv(output_path, fieldnames, selected_rows)
    write_markdown_summary(markdown_path, selected_rows, args.genome, ranking_path)

    print(f"Wrote shortlist TSV: {output_path}")
    print(f"Wrote shortlist Markdown: {markdown_path}")


if __name__ == "__main__":
    main()
