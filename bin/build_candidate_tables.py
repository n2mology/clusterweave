#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "na", "n/a", "none", "-"}:
        return ""
    return text


def norm_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean(value).lower())


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_tsv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def to_float(value: object) -> float:
    text = clean(value)
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def to_int(value: object) -> int:
    text = clean(value)
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def split_multi(value: str) -> list[str]:
    text = clean(value)
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def unique_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def ecology_group(primary_label: str) -> str:
    return clean(primary_label) or "UNLABELED"


def matches_focus_ecology(ecology_value: str, focus_label: str) -> bool:
    return bool(clean(focus_label)) and clean(ecology_value).casefold() == clean(focus_label).casefold()


def classes_from_terms(terms: list[str]) -> set[str]:
    out: set[str] = set()
    for raw in terms:
        token = re.sub(r"[^a-z0-9]+", " ", clean(raw).lower()).strip()
        if not token:
            continue
        if "nrps" in token:
            out.add("NRPS")
        if "pks" in token or "polyketide" in token:
            out.add("PKS")
        if "terpene" in token or " tc " in f" {token} ":
            out.add("terpene")
        if "ripp" in token:
            out.add("RiPP")
        if "indole" in token:
            out.add("indole")
        if "alkaloid" in token:
            out.add("alkaloid")
        if "saccharide" in token:
            out.add("saccharide")
    if not out and terms:
        out.add("other")
    return out


def parse_consensus(antismash_region: str, funbgcex_cluster: str) -> tuple[str, int]:
    has_antismash = bool(clean(antismash_region))
    has_funbgcex = bool(clean(funbgcex_cluster))
    if has_antismash and has_funbgcex:
        return "antiSMASH+FunBGCeX", 4
    if has_antismash:
        return "antiSMASH-only", 2
    return "FunBGCeX-only", 1


def gcf_ecology_pattern(focus_count: int, nonfocus_count: int, focus_label: str) -> str:
    if focus_count <= 0 and nonfocus_count <= 0:
        return "no_gcf"
    if not clean(focus_label):
        return "present"
    if focus_count > 0 and nonfocus_count <= 0:
        return "focus_only"
    if nonfocus_count > 0 and focus_count <= 0:
        return "nonfocus_only"
    return "mixed"


def annotation_support_label(
    knowncluster_similarity: float,
    clustercompare_similarity: float,
    funbgcex_similarity: float,
    nearest_annotation: str,
) -> str:
    if knowncluster_similarity >= 50.0:
        return "knowncluster_high"
    if knowncluster_similarity >= 20.0:
        return "knowncluster_moderate"
    if clustercompare_similarity >= 0.7:
        return "clustercompare_hint"
    if funbgcex_similarity >= 10.0:
        return "FunBGCeX_hint"
    if clean(nearest_annotation):
        return "annotation_text_only"
    return "no_annotation"


def build_recommended_followup(
    priority_tier: str,
    consensus_label: str,
    gcf_present: bool,
    class_logic_support: str,
) -> str:
    if priority_tier == "tier_1":
        return "prioritize targeted synteny/clinker and manual class-level metabolite review"
    if priority_tier == "tier_2" and gcf_present:
        return "review GCF context and schedule targeted synteny/clinker"
    if consensus_label == "antiSMASH+FunBGCeX" and class_logic_support == "yes":
        return "manual class-logic review, then targeted synteny if chemistry remains plausible"
    if gcf_present:
        return "manual GCF-context review before follow-up"
    return "keep as a low-confidence lead until stronger comparative support appears"


def pick_reference_annotation(row: dict[str, object]) -> str:
    for key in [
        "antismash_knowncluster_product",
        "antismash_clustercompare_compounds",
        "funbgcex_putative_product",
        "nearest_mibig_or_annotation_if_available",
    ]:
        value = clean(row.get(key))
        if value:
            return value
    return ""


def shorten_reference_label(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"[;/]+", text) if part.strip()]
    if len(parts) <= 1:
        return text
    if len(parts) == 2:
        return f"{parts[0]}-related annotation"
    return f"{parts[0]} and related annotations"


def build_reference_basis(row: dict[str, object]) -> str:
    if clean(row.get("antismash_knowncluster_product")) or clean(row.get("antismash_knowncluster_accession")):
        return "antiSMASH KnownClusterBlast"
    if clean(row.get("antismash_clustercompare_compounds")):
        return "antiSMASH ClusterCompare"
    if clean(row.get("funbgcex_putative_product")) or clean(row.get("funbgcex_similar_bgc")):
        return "FunBGCeX similarity"
    if clean(row.get("nearest_mibig_or_annotation_if_available")):
        return "merged annotation text"
    return "no specific reference"


def build_gcf_context_text(gcf_id: str, focus_count: int, nonfocus_count: int, focus_label: str) -> str:
    if not clean(gcf_id):
        return "no confident GCF assignment"
    pattern = gcf_ecology_pattern(focus_count, nonfocus_count, focus_label)
    if not clean(focus_label):
        return f"{gcf_id} is detected in {focus_count + nonfocus_count} genomes"
    if pattern == "focus_only":
        return f"{gcf_id} is restricted to {focus_label} ({focus_count} genomes)"
    if pattern == "nonfocus_only":
        return f"{gcf_id} is absent from {focus_label} and occurs in {nonfocus_count} other genomes"
    if pattern == "mixed":
        return f"{gcf_id} is mixed ({focus_count} {focus_label} / {nonfocus_count} non-{focus_label} genomes)"
    return f"{gcf_id} has limited ecology context"


def determine_review_bucket(row: dict[str, object]) -> str:
    priority_tier = clean(row.get("priority_tier"))
    gcf_id = clean(row.get("gcf_id"))
    class_logic_support = clean(row.get("class_logic_support"))
    annotation_support_tier = clean(row.get("annotation_support_tier"))
    if priority_tier == "tier_1" and gcf_id and annotation_support_tier in {
        "knowncluster_high",
        "knowncluster_moderate",
        "clustercompare_hint",
    }:
        return "synteny_first"
    if priority_tier in {"tier_1", "tier_2"} and (gcf_id or class_logic_support == "yes"):
        return "manual_review_then_synteny"
    if priority_tier == "tier_3":
        return "manual_review_only"
    return "deprioritize"


def build_safe_claim_text(row: dict[str, object], target_genome: str, focus_label: str) -> str:
    region_id = clean(row.get("antismash_region")) or clean(row.get("funbgcex_cluster")) or "unresolved region"
    bgc_class = clean(row.get("antismash_class")) or "unclassified"
    gcf_id = clean(row.get("gcf_id"))
    gcf_context = build_gcf_context_text(
        gcf_id,
        to_int(row.get("gcf_focus_genome_count")),
        to_int(row.get("gcf_nonfocus_genome_count")),
        focus_label,
    )
    reference_label = shorten_reference_label(pick_reference_annotation(row))
    if reference_label:
        return (
            f"{target_genome} {region_id} is a {bgc_class} BGC in {gcf_context}; "
            f"it is linked to reference-cluster annotations associated with {reference_label}, "
            "but product-level assignment should remain provisional pending targeted "
            "synteny and domain review."
        )
    return (
        f"{target_genome} {region_id} is a {bgc_class} BGC in {gcf_context}; "
        "it should be discussed at the class/GCF level unless stronger architecture "
        "or synteny evidence is added."
    )


def build_comparator_strategy(row: dict[str, object], focus_label: str) -> str:
    focus_count = to_int(row.get("gcf_focus_genome_count"))
    nonfocus_count = to_int(row.get("gcf_nonfocus_genome_count"))
    gcf_id = clean(row.get("gcf_id"))
    if not gcf_id:
        return "review local architecture first; no clear GCF comparator set"
    if not clean(focus_label):
        return "compare against same-GCF representatives before product-level discussion"
    if focus_count > 0 and nonfocus_count == 0:
        return f"compare first against same-GCF {focus_label} genomes, then optional MIBiG references"
    if focus_count > 0 and nonfocus_count > 0:
        return f"compare against same-GCF {focus_label} and non-{focus_label} representatives to test ecology specificity"
    return "compare against same-GCF representatives before product-level discussion"


def write_markdown_shortlist(
    path: Path,
    target_genome: str,
    shortlist_rows: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    synteny_rows = [row for row in shortlist_rows if clean(row.get("review_bucket")) == "synteny_first"]
    manual_rows = [row for row in shortlist_rows if clean(row.get("review_bucket")) == "manual_review_then_synteny"]
    hold_rows = [row for row in shortlist_rows if clean(row.get("review_bucket")) not in {"synteny_first", "manual_review_then_synteny"}]

    lines = [
        f"# Reviewer-safe shortlist for {target_genome}",
        "",
        f"- total candidate rows: {len(shortlist_rows)}",
        f"- synteny-first rows: {len(synteny_rows)}",
        f"- manual-review-then-synteny rows: {len(manual_rows)}",
        f"- hold/deprioritize rows: {len(hold_rows)}",
        "",
        "## Synteny-first shortlist",
        "",
    ]

    if synteny_rows:
        for row in synteny_rows[:12]:
            lines.extend(
                [
                    f"### {clean(row.get('target_rank'))}. {clean(row.get('antismash_region')) or clean(row.get('funbgcex_cluster'))}",
                    f"- class: {clean(row.get('antismash_class'))}",
                    f"- GCF context: {clean(row.get('gcf_context'))}",
                    f"- reference basis: {clean(row.get('reference_basis'))}",
                    f"- reference annotation: {clean(row.get('reference_annotation')) or 'none'}",
                    f"- region GBK: {clean(row.get('region_gbk_path')) or 'not found'}",
                    f"- recommended follow-up: {clean(row.get('recommended_followup'))}",
                    f"- safe claim: {clean(row.get('safe_claim_text'))}",
                    "",
                ]
            )
    else:
        lines.extend(["No synteny-first rows were identified.", ""])

    lines.extend(["## Manual review before synteny", ""])
    if manual_rows:
        for row in manual_rows[:12]:
            lines.extend(
                [
                    f"### {clean(row.get('target_rank'))}. {clean(row.get('antismash_region')) or clean(row.get('funbgcex_cluster'))}",
                    f"- class: {clean(row.get('antismash_class'))}",
                    f"- GCF context: {clean(row.get('gcf_context'))}",
                    f"- comparator strategy: {clean(row.get('comparator_strategy'))}",
                    f"- safe claim: {clean(row.get('safe_claim_text'))}",
                    "",
                ]
            )
    else:
        lines.extend(["No manual-review rows were identified.", ""])

    lines.extend(
        [
            "## Notes",
            "",
            "- Treat antiSMASH and FunBGCeX product labels as similarity clues, not product assignments.",
            "- Use the GCF context to decide whether a cluster is broadly shared, ecology-restricted, or too isolated for strong claims.",
            "- NPLinker can be revisited after the genomics shortlist is narrowed, but it is not the primary evidence layer here.",
            "",
        ]
    )

    path.write_text("\n".join(lines), encoding="utf-8")


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def fallback_metadata_row(genome: str) -> dict[str, str]:
    label = ecology_group("")
    return {
        "accession": "",
        "genome": genome,
        "ecofun_primary": label,
        "ecofun_secondary": "",
        "ecology_group": label,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build non-redundant downstream summaries for the active ClusterWeave project "
            "from the existing metadata, antiSMASH/FunBGCeX agreement tables, and "
            "BiG-SCAPE crosswalk outputs."
        )
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
        help="Project name used under data/results and Code/.",
    )
    parser.add_argument(
        "--target-genome",
        default="",
        help="Optional genome ID to prioritize for reviewer-facing shortlist outputs.",
    )
    parser.add_argument(
        "--ecology-field",
        default="ecofun_primary",
        help="Metadata column used as the ecology label for grouping and prioritization.",
    )
    parser.add_argument(
        "--focus-ecology-label",
        default="",
        help="Optional ecology label to prioritize. Defaults to the target genome's ecology label when available.",
    )
    args = parser.parse_args()

    results_root = args.project_root / "data" / "results" / args.project_name
    summary_root = results_root / "summary"
    summary_tables_root = results_root / "summary_tables"

    metadata_path = summary_tables_root / "ecofun_metadata_normalized.tsv"
    summary_path = summary_root / "all_tools_shared_unshared_summary.csv"
    crosswalk_path = summary_root / "candidate_bgc_gcf_crosswalk.tsv"
    comparison_path = summary_root / "all_tools_bgc_comparison.csv"

    dse_detail_out = summary_root / "ecology_group_gcf_by_genome.tsv"
    dse_summary_out = summary_root / "ecology_group_gcf_summary.tsv"
    gcf_context_out = summary_root / "gcf_ecology_distribution.tsv"
    candidate_ranking_out = summary_root / "targeted_candidate_ranking.tsv"
    target_shortlist_out = summary_root / "reviewer_shortlist.tsv"
    target_shortlist_md_out = summary_root / "reviewer_shortlist.md"

    for path in [metadata_path, summary_path, crosswalk_path, comparison_path]:
        if not path.exists():
            raise FileNotFoundError(f"Required input not found: {path}")

    metadata_rows = read_tsv_rows(metadata_path)
    summary_rows = read_csv_rows(summary_path)
    crosswalk_rows = read_tsv_rows(crosswalk_path)
    comparison_rows = read_csv_rows(comparison_path)

    metadata_by_genome: dict[str, dict[str, str]] = {}
    for row in metadata_rows:
        genome = clean(row.get("genome_id_current"))
        if not genome:
            continue
        primary_label = ecology_group(clean(row.get(args.ecology_field)))
        metadata_by_genome[genome] = {
            "accession": clean(row.get("accession")),
            "genome": genome,
            "ecofun_primary": clean(row.get("ecofun_primary")) or primary_label,
            "ecofun_secondary": clean(row.get("ecofun_secondary")),
            "ecology_group": ecology_group(primary_label),
        }

    for row_set in (summary_rows, crosswalk_rows, comparison_rows):
        for row in row_set:
            genome = clean(row.get("genome"))
            if genome and genome not in metadata_by_genome:
                metadata_by_genome[genome] = fallback_metadata_row(genome)

    focus_ecology_label = clean(args.focus_ecology_label)
    if not focus_ecology_label and clean(args.target_genome):
        focus_ecology_label = clean(metadata_by_genome.get(args.target_genome, {}).get("ecology_group"))

    gcf_summary_detail_rows: list[dict[str, object]] = []
    gcf_summary_aggregate: dict[tuple[str, str], dict[str, object]] = defaultdict(
        lambda: {
            "ecology_group": "",
            "class_norm": "",
            "genomes": set(),
            "shared_gcf_total": 0,
            "unshared_gcf_total": 0,
            "total_gcf": 0,
        }
    )
    gcf_summary_all_classes: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "ecology_group": "",
            "class_norm": "ALL_CLASSES",
            "genomes": set(),
            "shared_gcf_total": 0,
            "unshared_gcf_total": 0,
            "total_gcf": 0,
        }
    )
    genome_class_context: dict[tuple[str, str], dict[str, int]] = {}

    for row in summary_rows:
        genome = clean(row.get("genome"))
        tool = clean(row.get("tool"))
        entity_type = clean(row.get("entity_type"))
        class_norm = clean(row.get("class_norm")) or "UNCLASSIFIED"
        if tool != "antismash" or entity_type != "GCF":
            continue
        meta = metadata_by_genome.setdefault(genome, fallback_metadata_row(genome))

        shared_count = to_int(row.get("shared_count"))
        unshared_count = to_int(row.get("unshared_count"))
        total = to_int(row.get("total"))
        if total <= 0:
            continue
        ecology = meta["ecology_group"]

        detail_row = {
            "genome": genome,
            "accession": meta["accession"],
            "ecofun_primary": meta["ecofun_primary"],
            "ecofun_secondary": meta["ecofun_secondary"],
            "ecology_group": ecology,
            "class_norm": class_norm,
            "shared_gcf_count": shared_count,
            "unshared_gcf_count": unshared_count,
            "total_gcf_count": total,
        }
        gcf_summary_detail_rows.append(detail_row)
        genome_class_context[(genome, class_norm)] = {
            "shared": shared_count,
            "unshared": unshared_count,
            "total": total,
        }

        group_key = (ecology, class_norm)
        group_bucket = gcf_summary_aggregate[group_key]
        group_bucket["ecology_group"] = ecology
        group_bucket["class_norm"] = class_norm
        group_bucket["genomes"].add(genome)
        group_bucket["shared_gcf_total"] += shared_count
        group_bucket["unshared_gcf_total"] += unshared_count
        group_bucket["total_gcf"] += total

        all_bucket = gcf_summary_all_classes[ecology]
        all_bucket["ecology_group"] = ecology
        all_bucket["genomes"].add(genome)
        all_bucket["shared_gcf_total"] += shared_count
        all_bucket["unshared_gcf_total"] += unshared_count
        all_bucket["total_gcf"] += total

    gcf_summary_rows: list[dict[str, object]] = []
    for bucket in list(gcf_summary_aggregate.values()) + list(gcf_summary_all_classes.values()):
        genome_count = len(bucket["genomes"])
        if genome_count <= 0:
            continue
        total_gcf = int(bucket["total_gcf"])
        gcf_summary_rows.append(
            {
                "ecology_group": bucket["ecology_group"],
                "class_norm": bucket["class_norm"],
                "genome_count": genome_count,
                "shared_gcf_total": int(bucket["shared_gcf_total"]),
                "unshared_gcf_total": int(bucket["unshared_gcf_total"]),
                "total_gcf": total_gcf,
                "mean_shared_gcf_per_genome": f"{bucket['shared_gcf_total'] / genome_count:.3f}",
                "mean_unshared_gcf_per_genome": f"{bucket['unshared_gcf_total'] / genome_count:.3f}",
                "mean_total_gcf_per_genome": f"{total_gcf / genome_count:.3f}",
            }
        )

    comparison_lookup: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in comparison_rows:
        key = (
            clean(row.get("genome")),
            clean(row.get("antismash_bgc_id")),
            clean(row.get("funbgcex_bgc_id")),
        )
        comparison_lookup[key] = row

    gcf_stats: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "genomes": set(),
            "focus_genomes": set(),
            "other_genomes": set(),
            "classes": Counter(),
            "annotations": Counter(),
            "consensus": Counter(),
            "candidate_keys": set(),
        }
    )

    for row in crosswalk_rows:
        genome = clean(row.get("genome"))
        meta = metadata_by_genome.setdefault(genome, fallback_metadata_row(genome))
        gcf_id = clean(row.get("gcf_id"))
        if not gcf_id:
            continue

        consensus_label, _ = parse_consensus(
            clean(row.get("antismash_region")),
            clean(row.get("funbgcex_cluster")),
        )
        class_norm = clean(row.get("antismash_class")) or "UNCLASSIFIED"
        annotation = clean(row.get("nearest_mibig_or_annotation_if_available"))

        bucket = gcf_stats[gcf_id]
        bucket["genomes"].add(genome)
        if matches_focus_ecology(meta["ecology_group"], focus_ecology_label):
            bucket["focus_genomes"].add(genome)
        else:
            bucket["other_genomes"].add(genome)
        bucket["classes"][class_norm] += 1
        if annotation:
            bucket["annotations"][annotation] += 1
        bucket["consensus"][consensus_label] += 1
        bucket["candidate_keys"].add(
            (
                genome,
                clean(row.get("antismash_region")),
                clean(row.get("funbgcex_cluster")),
                gcf_id,
            )
        )

    gcf_context_rows: list[dict[str, object]] = []
    for gcf_id, bucket in gcf_stats.items():
        focus_count = len(bucket["focus_genomes"])
        other_count = len(bucket["other_genomes"])
        example_annotation = bucket["annotations"].most_common(1)[0][0] if bucket["annotations"] else ""
        top_class = bucket["classes"].most_common(1)[0][0] if bucket["classes"] else ""
        gcf_context_rows.append(
            {
                "gcf_id": gcf_id,
                "candidate_row_count": len(bucket["candidate_keys"]),
                "genome_count": len(bucket["genomes"]),
                "focus_ecology_label": focus_ecology_label,
                "focus_genome_count": focus_count,
                "nonfocus_genome_count": other_count,
                "ecology_pattern": gcf_ecology_pattern(focus_count, other_count, focus_ecology_label),
                "top_antismash_class": top_class,
                "example_annotation": example_annotation,
                "consensus_profile": "; ".join(
                    f"{label}:{count}" for label, count in bucket["consensus"].most_common()
                ),
                "genomes": ";".join(sorted(bucket["genomes"])),
            }
        )

    candidate_rows: list[dict[str, object]] = []
    for row in crosswalk_rows:
        genome = clean(row.get("genome"))
        meta = metadata_by_genome.setdefault(genome, fallback_metadata_row(genome))

        antismash_region = clean(row.get("antismash_region"))
        funbgcex_cluster = clean(row.get("funbgcex_cluster"))
        comparison = comparison_lookup.get((genome, antismash_region, funbgcex_cluster), {})

        antismash_class = clean(row.get("antismash_class")) or clean(comparison.get("antismash_bgc_class")) or "UNCLASSIFIED"
        gcf_id = clean(row.get("gcf_id"))
        gcf_components = split_multi(gcf_id)
        gcf_bucket = gcf_stats.get(gcf_id)
        gcf_genome_count = len(gcf_bucket["genomes"]) if gcf_bucket else 0
        gcf_focus_count = len(gcf_bucket["focus_genomes"]) if gcf_bucket else 0
        gcf_other_count = len(gcf_bucket["other_genomes"]) if gcf_bucket else 0
        gcf_pattern = gcf_ecology_pattern(gcf_focus_count, gcf_other_count, focus_ecology_label)

        consensus_label, consensus_points = parse_consensus(antismash_region, funbgcex_cluster)
        gcf_points = 0
        if gcf_id:
            gcf_points += 1
        if gcf_genome_count >= 2:
            gcf_points += 1
        if gcf_genome_count >= 4:
            gcf_points += 1

        ecology_points = 0
        if matches_focus_ecology(meta["ecology_group"], focus_ecology_label) and gcf_focus_count > 0:
            ecology_points += 1
            if gcf_other_count == 0 and gcf_focus_count >= 2:
                ecology_points += 1

        antismash_classes = classes_from_terms(split_multi(antismash_class))
        funbgcex_classes = classes_from_terms([clean(comparison.get("funbgcex_core_enzymes"))])
        class_logic_support = "yes" if antismash_classes and funbgcex_classes and antismash_classes.intersection(funbgcex_classes) else "no"
        class_logic_points = 1 if class_logic_support == "yes" else 0

        knowncluster_similarity = to_float(comparison.get("antismash_knowncluster_similarity_score"))
        clustercompare_similarity = to_float(comparison.get("antismash_clustercompare_similarity_score"))
        funbgcex_similarity = to_float(comparison.get("funbgcex_similarity_score"))
        nearest_annotation = clean(row.get("nearest_mibig_or_annotation_if_available"))
        annotation_points = 0
        annotation_reasons: list[str] = []
        if knowncluster_similarity >= 50.0:
            annotation_points += 2
            annotation_reasons.append("knowncluster>=50")
        elif knowncluster_similarity >= 20.0:
            annotation_points += 1
            annotation_reasons.append("knowncluster>=20")
        if clustercompare_similarity >= 0.7:
            annotation_points += 1
            annotation_reasons.append("clustercompare>=0.7")
        if funbgcex_similarity >= 10.0:
            annotation_points += 1
            annotation_reasons.append("FunBGCeX_similarity>=10")

        same_product_exact = clean(comparison.get("same_putative_product_exact")).lower() == "yes"
        same_product_keyword = clean(comparison.get("same_putative_product_keyword")).lower() == "yes"
        product_points = 1 if same_product_exact or same_product_keyword else 0
        product_support = "exact" if same_product_exact else ("keyword" if same_product_keyword else "no")

        priority_score = (
            consensus_points
            + gcf_points
            + ecology_points
            + class_logic_points
            + annotation_points
            + product_points
        )

        if priority_score >= 11 and consensus_label == "antiSMASH+FunBGCeX" and bool(gcf_id):
            priority_tier = "tier_1"
        elif priority_score >= 8:
            priority_tier = "tier_2"
        elif priority_score >= 5:
            priority_tier = "tier_3"
        else:
            priority_tier = "tier_4"

        genome_context = genome_class_context.get((genome, antismash_class), {"shared": 0, "unshared": 0, "total": 0})
        ranking_rationale = "; ".join(
            unique_preserve(
                [
                    f"consensus={consensus_label}",
                    f"gcf_pattern={gcf_pattern}",
                    f"ecology_group={meta['ecology_group']}",
                    f"focus_ecology_label={focus_ecology_label or 'none'}",
                    f"class_logic={'supported' if class_logic_support == 'yes' else 'limited'}",
                ]
                + annotation_reasons
                + ([f"product_support={product_support}"] if product_support != "no" else [])
            )
        )

        candidate_rows.append(
            {
                "rank": 0,
                "priority_score": priority_score,
                "priority_tier": priority_tier,
                "genome": genome,
                "accession": meta["accession"],
                "ecofun_primary": meta["ecofun_primary"],
                "ecofun_secondary": meta["ecofun_secondary"],
                "ecology_group": meta["ecology_group"],
                "antismash_region": antismash_region,
                "funbgcex_cluster": funbgcex_cluster,
                "antismash_class": antismash_class,
                "class_logic_support": class_logic_support,
                "overlap_bp": to_int(comparison.get("overlap_bp")),
                "gcf_id": gcf_id,
                "resolved_gcf_ids": ";".join(gcf_components),
                "gcf_family_count": len(gcf_components),
                "gcf_genome_count": gcf_genome_count,
                "focus_ecology_label": focus_ecology_label,
                "gcf_focus_genome_count": gcf_focus_count,
                "gcf_nonfocus_genome_count": gcf_other_count,
                "gcf_ecology_pattern": gcf_pattern,
                "genome_class_gcf_shared_count": genome_context["shared"],
                "genome_class_gcf_unshared_count": genome_context["unshared"],
                "genome_class_gcf_total": genome_context["total"],
                "consensus_support": consensus_label,
                "antismash_knowncluster_accession": clean(comparison.get("antismash_knowncluster_accession")),
                "antismash_knowncluster_product": clean(comparison.get("antismash_knowncluster_product")),
                "antismash_knowncluster_similarity_score": clean(comparison.get("antismash_knowncluster_similarity_score")),
                "antismash_clustercompare_compounds": clean(comparison.get("antismash_clustercompare_compounds")),
                "antismash_clustercompare_similarity_score": clean(comparison.get("antismash_clustercompare_similarity_score")),
                "antismash_clustercompare_organism": clean(comparison.get("antismash_clustercompare_organism")),
                "funbgcex_core_enzymes": clean(comparison.get("funbgcex_core_enzymes")),
                "funbgcex_similar_bgc": clean(comparison.get("funbgcex_similar_bgc")),
                "funbgcex_similarity_score": clean(comparison.get("funbgcex_similarity_score")),
                "funbgcex_putative_product": clean(comparison.get("funbgcex_putative_product")),
                "same_putative_product_support": product_support,
                "nearest_mibig_or_annotation_if_available": nearest_annotation,
                "annotation_support_tier": annotation_support_label(
                    knowncluster_similarity,
                    clustercompare_similarity,
                    funbgcex_similarity,
                    nearest_annotation,
                ),
                "notes": clean(row.get("notes")),
                "recommended_followup": build_recommended_followup(
                    priority_tier,
                    consensus_label,
                    bool(gcf_id),
                    class_logic_support,
                ),
                "ranking_rationale": ranking_rationale,
            }
        )

    ecology_sort = {focus_ecology_label: 0} if focus_ecology_label else {}
    candidate_rows.sort(
        key=lambda row: (
            -int(row["priority_score"]),
            ecology_sort.get(str(row["ecology_group"]), 9),
            -int(row["gcf_genome_count"]),
            -int(row["overlap_bp"]),
            norm_key(str(row["genome"])),
            norm_key(str(row["antismash_region"])),
            norm_key(str(row["funbgcex_cluster"])),
        )
    )
    for idx, row in enumerate(candidate_rows, start=1):
        row["rank"] = idx

    target_shortlist_rows: list[dict[str, object]] = []
    if clean(args.target_genome):
        target_antismash_root = results_root / "antismash" / args.target_genome
        for target_rank, row in enumerate(
            [candidate for candidate in candidate_rows if clean(candidate.get("genome")) == args.target_genome],
            start=1,
        ):
            antismash_region = clean(row.get("antismash_region"))
            region_gbk_path = target_antismash_root / f"{antismash_region}.gbk" if antismash_region else Path()
            reference_annotation = shorten_reference_label(pick_reference_annotation(row))
            shortlist_row = {
                "target_rank": target_rank,
                "global_rank": to_int(row.get("rank")),
                "priority_score": to_int(row.get("priority_score")),
                "priority_tier": clean(row.get("priority_tier")),
                "review_bucket": determine_review_bucket(row),
                "genome": clean(row.get("genome")),
                "antismash_region": antismash_region,
                "region_gbk_path": str(region_gbk_path) if antismash_region else "",
                "region_gbk_exists": "yes" if antismash_region and region_gbk_path.exists() else "no",
                "funbgcex_cluster": clean(row.get("funbgcex_cluster")),
                "antismash_class": clean(row.get("antismash_class")),
                "gcf_id": clean(row.get("gcf_id")),
                "gcf_context": build_gcf_context_text(
                    clean(row.get("gcf_id")),
                    to_int(row.get("gcf_focus_genome_count")),
                    to_int(row.get("gcf_nonfocus_genome_count")),
                    focus_ecology_label,
                ),
                "focus_ecology_label": focus_ecology_label,
                "gcf_focus_genome_count": to_int(row.get("gcf_focus_genome_count")),
                "gcf_nonfocus_genome_count": to_int(row.get("gcf_nonfocus_genome_count")),
                "consensus_support": clean(row.get("consensus_support")),
                "class_logic_support": clean(row.get("class_logic_support")),
                "reference_basis": build_reference_basis(row),
                "reference_annotation": reference_annotation,
                "same_putative_product_support": clean(row.get("same_putative_product_support")),
                "annotation_support_tier": clean(row.get("annotation_support_tier")),
                "recommended_followup": clean(row.get("recommended_followup")),
                "comparator_strategy": build_comparator_strategy(row, focus_ecology_label),
                "safe_claim_text": build_safe_claim_text(row, args.target_genome, focus_ecology_label),
                "ranking_rationale": clean(row.get("ranking_rationale")),
            }
            target_shortlist_rows.append(shortlist_row)

    gcf_summary_detail_rows.sort(
        key=lambda row: (
            ecology_sort.get(str(row["ecology_group"]), 9),
            norm_key(str(row["class_norm"])),
            norm_key(str(row["genome"])),
        )
    )
    gcf_summary_rows.sort(
        key=lambda row: (
            ecology_sort.get(str(row["ecology_group"]), 9),
            1 if str(row["class_norm"]) == "ALL_CLASSES" else 0,
            norm_key(str(row["class_norm"])),
        )
    )
    gcf_context_rows.sort(
        key=lambda row: (
            -int(row["genome_count"]),
            -int(row["candidate_row_count"]),
            norm_key(str(row["gcf_id"])),
        )
    )

    write_tsv(
        dse_detail_out,
        [
            "genome",
            "accession",
            "ecofun_primary",
            "ecofun_secondary",
            "ecology_group",
            "class_norm",
            "shared_gcf_count",
            "unshared_gcf_count",
            "total_gcf_count",
        ],
        gcf_summary_detail_rows,
    )
    write_tsv(
        dse_summary_out,
        [
            "ecology_group",
            "class_norm",
            "genome_count",
            "shared_gcf_total",
            "unshared_gcf_total",
            "total_gcf",
            "mean_shared_gcf_per_genome",
            "mean_unshared_gcf_per_genome",
            "mean_total_gcf_per_genome",
        ],
        gcf_summary_rows,
    )
    write_tsv(
        gcf_context_out,
        [
            "gcf_id",
            "candidate_row_count",
            "genome_count",
            "focus_ecology_label",
            "focus_genome_count",
            "nonfocus_genome_count",
            "ecology_pattern",
            "top_antismash_class",
            "example_annotation",
            "consensus_profile",
            "genomes",
        ],
        gcf_context_rows,
    )
    write_tsv(
        candidate_ranking_out,
        [
            "rank",
            "priority_score",
            "priority_tier",
            "genome",
            "accession",
            "ecofun_primary",
            "ecofun_secondary",
            "ecology_group",
            "antismash_region",
            "funbgcex_cluster",
            "antismash_class",
            "class_logic_support",
            "overlap_bp",
            "gcf_id",
            "resolved_gcf_ids",
            "gcf_family_count",
            "gcf_genome_count",
            "focus_ecology_label",
            "gcf_focus_genome_count",
            "gcf_nonfocus_genome_count",
            "gcf_ecology_pattern",
            "genome_class_gcf_shared_count",
            "genome_class_gcf_unshared_count",
            "genome_class_gcf_total",
            "consensus_support",
            "antismash_knowncluster_accession",
            "antismash_knowncluster_product",
            "antismash_knowncluster_similarity_score",
            "antismash_clustercompare_compounds",
            "antismash_clustercompare_similarity_score",
            "antismash_clustercompare_organism",
            "funbgcex_core_enzymes",
            "funbgcex_similar_bgc",
            "funbgcex_similarity_score",
            "funbgcex_putative_product",
            "same_putative_product_support",
            "nearest_mibig_or_annotation_if_available",
            "annotation_support_tier",
            "notes",
            "recommended_followup",
            "ranking_rationale",
        ],
        candidate_rows,
    )
    if target_shortlist_rows:
        write_tsv(
            target_shortlist_out,
            [
                "target_rank",
                "global_rank",
                "priority_score",
                "priority_tier",
                "review_bucket",
                "genome",
                "antismash_region",
                "region_gbk_path",
                "region_gbk_exists",
                "funbgcex_cluster",
                "antismash_class",
                "gcf_id",
                "gcf_context",
                "focus_ecology_label",
                "gcf_focus_genome_count",
                "gcf_nonfocus_genome_count",
                "consensus_support",
                "class_logic_support",
                "reference_basis",
                "reference_annotation",
                "same_putative_product_support",
                "annotation_support_tier",
                "recommended_followup",
                "comparator_strategy",
                "safe_claim_text",
                "ranking_rationale",
            ],
            target_shortlist_rows,
        )
        write_markdown_shortlist(
            target_shortlist_md_out,
            args.target_genome,
            target_shortlist_rows,
        )

    print(f"Wrote ecology-group per-genome GCF detail: {dse_detail_out}")
    print(f"Wrote ecology-group GCF summary:         {dse_summary_out}")
    print(f"Wrote GCF ecology distribution:         {gcf_context_out}")
    print(f"Wrote targeted candidate ranking:       {candidate_ranking_out}")
    if target_shortlist_rows:
        print(f"Wrote target reviewer shortlist:        {target_shortlist_out}")
        print(f"Wrote target reviewer shortlist note:   {target_shortlist_md_out}")
    else:
        print("Skipped target reviewer shortlist:      set --target-genome to enable it")


if __name__ == "__main__":
    main()
