#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


GcfMembership = tuple[str, str, str]
DEFAULT_GCF_CATEGORY = "mix"
DEFAULT_GCF_THRESHOLD = "0.3"


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


def join_id_pairs(
    genome: str, antismash_region: str, taxon_group: str
) -> list[tuple[str, str]]:
    """Try current exact IDs before the pre-v1.0 bacterial prefix convention."""
    pairs = [(genome, antismash_region)]
    if taxon_group.casefold() != "bacteria":
        return pairs
    legacy_genome = (
        genome
        if genome.casefold().startswith("bacteria_")
        else f"bacteria_{genome}"
    )
    legacy_region = (
        antismash_region
        if antismash_region.casefold().startswith("bacteria_")
        else f"bacteria_{antismash_region}"
    )
    legacy_pair = (legacy_genome, legacy_region)
    if legacy_pair != pairs[0]:
        pairs.append(legacy_pair)
    return pairs


def canonical_gcf_category(value: object) -> str:
    return clean(value).casefold() or DEFAULT_GCF_CATEGORY


def canonical_gcf_threshold(value: object) -> str:
    text = clean(value).casefold()
    if text.startswith("c"):
        text = text[1:]
    if not text:
        return DEFAULT_GCF_THRESHOLD
    try:
        normalized = format(Decimal(text).normalize(), "f")
    except InvalidOperation:
        return text
    return (
        normalized.rstrip("0").rstrip(".") if "." in normalized else normalized
    )


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


def clustering_view(path: Path) -> tuple[str, str]:
    match = re.match(r"(.+)_clustering_c([^/]+)\.tsv$", path.name)
    if match:
        return (
            canonical_gcf_category(match.group(1)),
            canonical_gcf_threshold(match.group(2)),
        )
    return canonical_gcf_category(path.parent.name), DEFAULT_GCF_THRESHOLD


def serialize_gcf_memberships(memberships: Iterable[GcfMembership]) -> str:
    return ";".join(
        f"{category}@c{threshold}={family}"
        for category, threshold, family in sorted(
            set(memberships), key=lambda item: (item[0], item[1], item[2])
        )
    )


def membership_family_ids(
    memberships: Iterable[GcfMembership], category: str, threshold: str
) -> set[str]:
    selected_category = canonical_gcf_category(category)
    selected_threshold = canonical_gcf_threshold(threshold)
    return {
        family
        for member_category, member_threshold, family in memberships
        if member_category == selected_category
        and member_threshold == selected_threshold
    }


def parse_bigscape_cluster_memberships(
    bigscape_root: Path,
    selected_category: str = DEFAULT_GCF_CATEGORY,
    selected_threshold: str = DEFAULT_GCF_THRESHOLD,
) -> tuple[
    dict[str, set[GcfMembership]],
    dict[str, set[GcfMembership]],
    dict[str, dict[str, str]],
]:
    """Return lossless category/threshold memberships keyed by record and GBK."""
    selected_view = (
        canonical_gcf_category(selected_category),
        canonical_gcf_threshold(selected_threshold),
    )
    record_to_memberships: dict[str, set[GcfMembership]] = defaultdict(set)
    gbk_to_memberships: dict[str, set[GcfMembership]] = defaultdict(set)
    representative_rows: dict[str, dict[str, str]] = {}
    paths = sorted(
        bigscape_root.rglob("*_clustering_c*.tsv"),
        key=lambda path: (
            clustering_view(path) != selected_view,
            str(path).casefold(),
        ),
    )
    for path in paths:
        category, threshold = clustering_view(path)
        for row in read_tsv_rows(path):
            record = clean(row.get("Record"))
            gbk = clean(row.get("GBK"))
            family = clean(row.get("Family"))
            cc = clean(row.get("CC"))
            gcf_id = family if family else (f"CC_{cc}" if cc else "")
            membership = (category, threshold, gcf_id)
            representative = {
                **row,
                "_gcf_category": category,
                "_gcf_threshold": threshold,
            }
            if record and gcf_id:
                record_to_memberships[norm_key(record)].add(membership)
                representative_rows.setdefault(norm_key(record), representative)
            if gbk and gcf_id:
                gbk_to_memberships[norm_key(gbk)].add(membership)
                representative_rows.setdefault(norm_key(gbk), representative)
    return record_to_memberships, gbk_to_memberships, representative_rows


def parse_bigscape_clusters(
    bigscape_root: Path,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, str]]]:
    """Compatibility view returning the historical union of family identifiers."""
    record_memberships, gbk_memberships, representative_rows = (
        parse_bigscape_cluster_memberships(bigscape_root)
    )
    record_to_families = {
        key: {family for _, _, family in memberships}
        for key, memberships in record_memberships.items()
    }
    gbk_to_families = {
        key: {family for _, _, family in memberships}
        for key, memberships in gbk_memberships.items()
    }
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
    *,
    selected_category: str = DEFAULT_GCF_CATEGORY,
    selected_threshold: str = DEFAULT_GCF_THRESHOLD,
    selected_gcf_id: str = "",
    selected_status: str = "",
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
    notes.append(
        f"gcf_selected_category={canonical_gcf_category(selected_category)}"
    )
    notes.append(
        f"gcf_selected_threshold={canonical_gcf_threshold(selected_threshold)}"
    )
    notes.append(
        f"gcf_selected_status={selected_status or ('assigned' if selected_gcf_id else 'unassigned')}"
    )
    if selected_gcf_id:
        notes.append(f"gcf_selected_id_count={len(selected_gcf_id.split(';'))}")
    antismash_present = bool(clean(row.get("antismash_bgc_id")))
    funbgcex_present = bool(clean(row.get("funbgcex_bgc_id")))
    funbgcex_applicability = clean(row.get("funbgcex_applicability"))
    if not funbgcex_applicability:
        funbgcex_applicability = (
            "not_applicable_taxon"
            if clean(row.get("taxon_group")) == "bacteria"
            else "applicable"
        )
    if funbgcex_applicability == "not_applicable_taxon":
        notes.append("consensus=applicable-detectors-complete")
        notes.append("funbgcex=not_applicable_taxon")
    elif antismash_present and funbgcex_present:
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
        help="Project root containing data/results and Code directories.",
    )
    parser.add_argument(
        "--project-name",
        default="clusterweave",
        help="Project name used under data/results.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output TSV path. Defaults to data/results/<project-name>/summary/candidate_bgc_gcf_crosswalk.tsv",
    )
    parser.add_argument(
        "--selected-gcf-category",
        default=DEFAULT_GCF_CATEGORY,
        help="Canonical BiG-SCAPE category used by downstream GCF counts/arcs (default: mix).",
    )
    parser.add_argument(
        "--selected-gcf-threshold",
        default=DEFAULT_GCF_THRESHOLD,
        help="Canonical BiG-SCAPE clustering threshold used downstream (default: 0.3).",
    )
    args = parser.parse_args()
    selected_category = canonical_gcf_category(args.selected_gcf_category)
    selected_threshold = canonical_gcf_threshold(args.selected_gcf_threshold)

    projects_root = args.project_root
    data_root = projects_root / "data" / "results" / args.project_name
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

    record_to_memberships, gbk_to_memberships, representative_rows = (
        parse_bigscape_cluster_memberships(
            bigscape_root, selected_category, selected_threshold
        )
    )
    annotation_by_record: dict[str, dict[str, str]] = {}
    annotation_by_gbk: dict[str, dict[str, str]] = {}
    if record_annotations_path is not None:
        annotation_by_record, annotation_by_gbk = parse_annotations_table(record_annotations_path)

    output_rows: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()

    for row in read_csv_rows(comparison_csv):
        genome = clean(row.get("genome"))
        taxon_group = clean(row.get("taxon_group")) or "fungi"
        antismash_region = clean(row.get("antismash_bgc_id"))
        antismash_class = clean(row.get("antismash_bgc_class"))
        funbgcex_cluster = clean(row.get("funbgcex_bgc_id"))

        if not antismash_region and not funbgcex_cluster:
            continue

        join_pairs = join_id_pairs(genome, antismash_region, taxon_group)
        join_genome, join_region = join_pairs[0]
        gbk_key = (
            build_gbk_key(join_genome, join_region)
            if join_genome and join_region
            else ""
        )

        annot_row = {}
        join_mode = "none"
        for candidate_genome, candidate_region in join_pairs:
            candidate_gbk_key = (
                build_gbk_key(candidate_genome, candidate_region)
                if candidate_genome and candidate_region
                else ""
            )
            candidate_record_key = (
                build_record_key(candidate_gbk_key, candidate_region)
                if candidate_gbk_key
                else ""
            )
            if (
                candidate_record_key
                and norm_key(candidate_record_key) in annotation_by_record
            ):
                annot_row = annotation_by_record[norm_key(candidate_record_key)]
                join_genome, join_region = candidate_genome, candidate_region
                gbk_key = candidate_gbk_key
                join_mode = "exact_record"
                break
            if candidate_gbk_key and norm_key(candidate_gbk_key) in annotation_by_gbk:
                annot_row = annotation_by_gbk[norm_key(candidate_gbk_key)]
                join_genome, join_region = candidate_genome, candidate_region
                gbk_key = candidate_gbk_key
                join_mode = "exact_gbk"
                break

        if not annot_row:
            # Try partial matching when the exact record key is unavailable.
            for candidate_genome, candidate_region in join_pairs:
                candidate_gbk_key = (
                    build_gbk_key(candidate_genome, candidate_region)
                    if candidate_genome and candidate_region
                    else ""
                )
                if not candidate_gbk_key:
                    continue
                gbk_norm = norm_key(candidate_gbk_key)
                for key, candidate in annotation_by_gbk.items():
                    if key.startswith(gbk_norm) or gbk_norm.startswith(key):
                        annot_row = candidate
                        join_genome, join_region = candidate_genome, candidate_region
                        gbk_key = candidate_gbk_key
                        join_mode = "fuzzy_gbk"
                        break
                if annot_row:
                    break

        bigscape_record = clean(annot_row.get("Record")) if annot_row else ""
        memberships_from_record = (
            record_to_memberships.get(norm_key(bigscape_record), set())
            if bigscape_record
            else set()
        )
        memberships_from_gbk = (
            gbk_to_memberships.get(
                norm_key(clean(annot_row.get("GBK")))
                if annot_row
                else norm_key(gbk_key),
                set(),
            )
            if (annot_row or gbk_key)
            else set()
        )
        memberships = memberships_from_record | memberships_from_gbk
        gcf_id = join_family_ids({family for _, _, family in memberships})
        gcf_memberships = serialize_gcf_memberships(memberships)
        selected_gcf_id = join_family_ids(
            membership_family_ids(
                memberships, selected_category, selected_threshold
            )
        )
        family_count = len(gcf_id.split(";")) if gcf_id else 0

        # If the record annotation table was not found, fall back to the clustering row that matches the GBK key.
        if not bigscape_record and gbk_key:
            representative = representative_rows.get(norm_key(gbk_key))
            if representative:
                bigscape_record = clean(representative.get("Record"))
                if not gcf_id:
                    family = clean(representative.get("Family")) or (
                        f"CC_{clean(representative.get('CC'))}"
                        if clean(representative.get("CC"))
                        else ""
                    )
                    category = canonical_gcf_category(
                        representative.get("_gcf_category")
                    )
                    threshold = canonical_gcf_threshold(
                        representative.get("_gcf_threshold")
                    )
                    memberships = {(category, threshold, family)} if family else set()
                    gcf_id = join_family_ids({family} if family else set())
                    gcf_memberships = serialize_gcf_memberships(memberships)
                    selected_gcf_id = join_family_ids(
                        membership_family_ids(
                            memberships, selected_category, selected_threshold
                        )
                    )
                    family_count = len(gcf_id.split(";")) if gcf_id else 0
                    join_mode = "cluster_table_fallback"

        nearest_annotation = choose_nearest_annotation(row)
        if not nearest_annotation and annot_row:
            desc = clean(annot_row.get("Description"))
            if desc:
                nearest_annotation = desc

        if selected_gcf_id:
            selected_status = "assigned"
        elif antismash_region:
            selected_status = "unassigned"
        else:
            selected_status = "not_applicable_detector_only"
        notes = build_notes(
            row,
            bigscape_record,
            gcf_id,
            join_mode,
            family_count,
            selected_category=selected_category,
            selected_threshold=selected_threshold,
            selected_gcf_id=selected_gcf_id,
            selected_status=selected_status,
        )
        if annot_row and clean(annot_row.get("Organism")):
            notes = "; ".join([notes, f"bigscape_organism={clean(annot_row.get('Organism'))}"]) if notes else f"bigscape_organism={clean(annot_row.get('Organism'))}"

        candidate = {
            "genome": genome,
            "taxon_group": taxon_group,
            "prediction_method": clean(row.get("prediction_method")),
            "funbgcex_applicability": clean(row.get("funbgcex_applicability")) or (
                "not_applicable_taxon" if taxon_group == "bacteria" else "applicable"
            ),
            "antismash_region": antismash_region,
            "antismash_class": antismash_class,
            "bigscape_record": bigscape_record,
            "gcf_id": gcf_id,
            "gcf_memberships": gcf_memberships,
            "gcf_selected_category": selected_category,
            "gcf_selected_threshold": selected_threshold,
            "gcf_selected_id": selected_gcf_id,
            "gcf_selected_status": selected_status,
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
            candidate["gcf_memberships"],
            candidate["gcf_selected_id"],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        output_rows.append(candidate)

    output_rows.sort(key=lambda r: (norm_key(r["genome"]), norm_key(r["antismash_region"]), norm_key(r["funbgcex_cluster"]), norm_key(r["gcf_id"])))

    fields = [
        "genome",
        "taxon_group",
        "prediction_method",
        "funbgcex_applicability",
        "antismash_region",
        "antismash_class",
        "bigscape_record",
        "gcf_id",
        "gcf_memberships",
        "gcf_selected_category",
        "gcf_selected_threshold",
        "gcf_selected_id",
        "gcf_selected_status",
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
