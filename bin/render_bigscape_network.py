#!/usr/bin/env python3
"""Render a ClusterWeave-friendly BiG-SCAPE network figure.

The renderer consumes BiG-SCAPE v2 output tables already used elsewhere in
ClusterWeave:

- ``record_annotations.tsv`` for BGC class, organism, and MiBIG context
- ``*_clustering_c*.tsv`` for the BGC/GCF record universe
- ``*_c*.network`` for pairwise BiG-SCAPE distance edges

It writes a publication-friendly SVG plus Cytoscape-readable GraphML without
requiring networkx, matplotlib, or other heavyweight plotting dependencies.
"""

from __future__ import annotations

import argparse
import colorsys
import csv
import hashlib
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape


UNKNOWN = "unknown"
MIBIG_SAMPLE_ID = "MiBIG reference"
MIBIG_BLUE = "#1F77B4"
DEFAULT_CANVAS_WIDTH = 1200
PRODUCT_LABEL_FONT_SIZE = 13
PRODUCT_SCORE_FONT_SIZE = 11
FONT_SIZE_INCREMENT = 2


CLASS_COLORS = {
    "NRPS": "#56D8C1",
    "PKS": "#EC961C",
    "terpene": "#A743CC",
    "RiPP": "#5481E3",
    "hybrid": "#82775B",
    "saccharide": "#F7A389",
    "other": "#A8BFFF",
    UNKNOWN: "#BDBDBD",
}


CLASS_ORDER = ["NRPS", "PKS", "terpene", "RiPP", "hybrid", "saccharide", "other", UNKNOWN]
NONINFORMATIVE_ECOLOGY = {UNKNOWN, "unlabeled", "unlabelled", "none", "na", "n/a"}


@dataclass
class NodeRecord:
    record: str
    gbk: str = ""
    record_type: str = ""
    record_number: str = ""
    cc: str = ""
    family: str = ""
    raw_class: str = ""
    category: str = ""
    organism: str = ""
    taxonomy: str = ""
    description: str = ""
    sample_id: str = UNKNOWN
    label_number: str = ""
    bgc_class: str = UNKNOWN
    ecology_category: str = UNKNOWN
    is_mibig: bool = False
    has_mibig_annotation: bool = False
    putative_products: tuple[str, ...] = ()
    putative_product_scores: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    fill_color: str = CLASS_COLORS[UNKNOWN]
    border_color: str = "#7A7A7A"


@dataclass
class EdgeRecord:
    source: str
    target: str
    distance: float | None = None
    jaccard: str = ""
    adjacency: str = ""
    dss: str = ""
    weights: str = ""
    alignment_mode: str = ""
    extend_strategy: str = ""

    @property
    def similarity(self) -> float | None:
        if self.distance is None:
            return None
        return max(0.0, min(1.0, 1.0 - self.distance))


@dataclass(frozen=True)
class MibigAnnotationHit:
    accession: str
    score: float


@dataclass(frozen=True)
class ProductEvidence:
    label: str
    scores: tuple[tuple[str, str], ...] = ()


@dataclass
class BigscapeInputs:
    output_root: Path
    run_dir: Path
    category: str
    clustering_path: Path
    network_path: Path | None
    annotations_path: Path | None


@dataclass
class LayoutResult:
    positions: dict[str, tuple[float, float]]
    width: int
    height: int
    legend_x: float
    section_y: dict[str, float] = field(default_factory=dict)
    section_right: float = 0.0


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "-", "na", "n/a", "none", "null"}:
        return ""
    return text


def norm_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean(value).lower())


def natural_key(value: str) -> tuple[object, ...]:
    return tuple(int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value))


def threshold_label(value: str) -> str:
    text = clean(value) or "0.3"
    return text[1:] if text.startswith("c") else text


def read_table_rows(path: Path, delimiter: str = "\t") -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def write_tsv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_float(value: object) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def is_mibig_record(record: str, gbk: str = "") -> bool:
    return bool(re.match(r"^BGC\d+", clean(record)) or re.match(r"^BGC\d+", clean(gbk)))


def derive_sample_id(record: str, gbk: str, organism: str, is_mibig: bool) -> str:
    if is_mibig:
        return MIBIG_SAMPLE_ID
    for token in [gbk, record]:
        if "__" in clean(token):
            return clean(token).split("__", 1)[0]
    return clean(organism).replace(" ", "_") or UNKNOWN


def normalize_bgc_class(raw_class: str, category: str = "") -> str:
    """Condense raw antiSMASH/BiG-SCAPE labels into stable visual classes."""
    text = f"{clean(raw_class)} {clean(category)}".lower()
    if not text.strip():
        return UNKNOWN

    has_nrps = bool(re.search(r"\bnrps?\b|\bnrp\b|nrps-like", text))
    has_pks = bool(re.search(r"\bpks\b|t1pks|transatpks|polyketide|nr-pks|hr-pks", text))
    has_ripp = "ripp" in text or "lanthipeptide" in text or "lassopeptide" in text
    has_terpene = "terpene" in text or bool(re.search(r"\btc\b|cyclase|synthase", text))
    has_saccharide = "saccharide" in text or "glycoside" in text

    major_hits = [
        label
        for label, present in [
            ("NRPS", has_nrps),
            ("PKS", has_pks),
            ("RiPP", has_ripp),
            ("terpene", has_terpene),
            ("saccharide", has_saccharide),
        ]
        if present
    ]
    if len(major_hits) > 1:
        return "hybrid"
    if major_hits:
        return major_hits[0]
    return "other"


def stable_label_color(label: str) -> str:
    text = clean(label)
    if is_unknown_ecology(text):
        return "#8A8A8A"
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    hue = int(digest[:8], 16) / 0xFFFFFFFF
    red, green, blue = colorsys.hls_to_rgb(hue, 0.42, 0.62)
    return f"#{int(red * 255):02X}{int(green * 255):02X}{int(blue * 255):02X}"


def is_unknown_ecology(label: str) -> bool:
    return clean(label).casefold() in NONINFORMATIVE_ECOLOGY


def has_ecology_signal(nodes: dict[str, NodeRecord]) -> bool:
    return any(not node.is_mibig and not is_unknown_ecology(node.ecology_category) for node in nodes.values())


def resolve_bigscape_output_root(path: Path) -> Path:
    """Accept either the BiG-SCAPE root, output_files root, or run directory."""
    if (path / "output_files").is_dir():
        return path / "output_files"
    if path.name == "output_files" and path.is_dir():
        return path
    if (path / "record_annotations.tsv").is_file():
        return path.parent
    return path


def select_bigscape_inputs(bigscape_root: Path, category: str, clustering_threshold: str) -> BigscapeInputs:
    output_root = resolve_bigscape_output_root(bigscape_root)
    label = threshold_label(clustering_threshold)

    if (output_root / "record_annotations.tsv").is_file():
        run_dir = output_root
    else:
        preferred = sorted(output_root.glob(f"*_c{label}"), key=lambda p: natural_key(p.name))
        candidates = preferred or sorted(output_root.glob("*_c*"), key=lambda p: natural_key(p.name))
        if not candidates:
            raise FileNotFoundError(f"No BiG-SCAPE clustering run directories found under: {output_root}")
        run_dir = candidates[-1]

    clustering_files = sorted(run_dir.rglob(f"*_clustering_c{label}.tsv"), key=lambda p: natural_key(str(p)))
    if not clustering_files:
        clustering_files = sorted(run_dir.rglob("*_clustering_c*.tsv"), key=lambda p: natural_key(str(p)))
    if not clustering_files:
        raise FileNotFoundError(f"No BiG-SCAPE clustering TSV files found under: {run_dir}")

    requested = clean(category)
    selected: Path | None = None
    if requested:
        for path in clustering_files:
            if path.parent.name.casefold() == requested.casefold():
                selected = path
                break
    if selected is None:
        for path in clustering_files:
            if path.parent.name.casefold() == "mix":
                selected = path
                break
    if selected is None:
        selected = max(clustering_files, key=lambda p: p.stat().st_size)

    chosen_category = selected.parent.name
    network_candidates = sorted(selected.parent.glob(f"*_c{label}.network"), key=lambda p: natural_key(p.name))
    if not network_candidates:
        network_candidates = sorted(selected.parent.glob("*.network"), key=lambda p: natural_key(p.name))
    network_path = network_candidates[0] if network_candidates else None

    annotations_path = run_dir / "record_annotations.tsv"
    if not annotations_path.exists():
        annotations_path = next(iter(sorted(run_dir.rglob("record_annotations.tsv"))), None)

    return BigscapeInputs(
        output_root=output_root,
        run_dir=run_dir,
        category=chosen_category,
        clustering_path=selected,
        network_path=network_path,
        annotations_path=annotations_path,
    )


def load_annotations(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None or not path.exists():
        return {}
    annotations: dict[str, dict[str, str]] = {}
    for row in read_table_rows(path):
        record = clean(row.get("Record"))
        if record:
            annotations[record] = row
    return annotations


def load_nodes(clustering_path: Path, annotations: dict[str, dict[str, str]]) -> tuple[dict[str, NodeRecord], list[str]]:
    nodes: dict[str, NodeRecord] = {}
    warnings: list[str] = []

    for row in read_table_rows(clustering_path):
        record = clean(row.get("Record"))
        if not record:
            continue
        gbk = clean(row.get("GBK"))
        ann = annotations.get(record, {})
        raw_class = clean(ann.get("Class"))
        annotation_category = clean(ann.get("Category"))
        category = annotation_category or clustering_path.parent.name
        organism = clean(ann.get("Organism"))
        is_mibig = is_mibig_record(record, gbk)
        sample_id = derive_sample_id(record, gbk, organism, is_mibig)
        bgc_class = normalize_bgc_class(raw_class, annotation_category)

        if bgc_class == UNKNOWN:
            warnings.append(f"Missing BGC class for record: {record}")

        nodes[record] = NodeRecord(
            record=record,
            gbk=gbk,
            record_type=clean(row.get("Record_Type")),
            record_number=clean(row.get("Record_Number")),
            cc=clean(row.get("CC")),
            family=clean(row.get("Family")),
            raw_class=raw_class,
            category=category,
            organism=organism,
            taxonomy=clean(ann.get("Taxonomy")),
            description=clean(ann.get("Description")),
            sample_id=sample_id,
            bgc_class=bgc_class,
            ecology_category=UNKNOWN,
            is_mibig=is_mibig,
            has_mibig_annotation=False,
            fill_color=CLASS_COLORS.get(bgc_class, CLASS_COLORS["other"]),
        )

    if not nodes:
        raise ValueError(f"No nodes could be loaded from: {clustering_path}")
    return nodes, warnings


def text_has_mibig_accession(text: str) -> bool:
    return bool(re.search(r"\bBGC\d{6,}(?:\.\d+)?\b", clean(text)))


def normalize_product_label(label: str) -> str:
    text = clean(label)
    if not text:
        return ""
    text = re.sub(r"\bBGC\d{6,}(?:\.\d+)?\b\s*\|\s*", "", text)
    text = re.sub(r"^(clustercompare|knowncluster)\s+[0-9]*\.?[0-9]+\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^FBGC[0-9A-Za-z_.-]*\s+[0-9]*\.?[0-9]+\s*:\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ;,")
    if not text or text.casefold() in {"unknown", "none", "na", "n/a", "not assigned"}:
        return ""
    return text


def percent_score(value: object) -> str:
    """Render antiSMASH-style similarity scores as percentages for labels."""
    text = clean(value)
    if not text:
        return ""
    parsed = parse_float(text)
    if parsed is None:
        return text
    percent = parsed * 100.0 if abs(parsed) <= 1.0 else parsed
    return f"{percent:.0f}%"


def product_scores_from_segment(segment: str) -> tuple[tuple[str, str], ...]:
    text = clean(segment)
    scores: list[tuple[str, str]] = []
    cluster_match = re.search(r"\bclustercompare\s+([0-9]*\.?[0-9]+)", text, re.IGNORECASE)
    if cluster_match:
        scores.append(("ClusterCompare", percent_score(cluster_match.group(1))))

    known_match = re.search(r"\bknowncluster\s+([0-9]*\.?[0-9]+)", text, re.IGNORECASE)
    if known_match:
        scores.append(("antiSMASH", percent_score(known_match.group(1))))

    return tuple(score for score in scores if score[1])


def product_evidence_from_text(
    text: str,
    default_scores: tuple[tuple[str, str], ...] = (),
) -> list[ProductEvidence]:
    evidence: list[ProductEvidence] = []
    for segment in re.split(r";", clean(text)):
        segment = clean(segment)
        if not segment:
            continue
        if re.search(r"\bFBGC[0-9A-Za-z_.-]*\b", segment):
            continue
        scores = product_scores_from_segment(segment) or default_scores
        label = ""
        if "|" in segment:
            label = normalize_product_label(segment.split("|", 1)[1])
        elif ":" in segment and re.search(r"clustercompare|knowncluster", segment, re.IGNORECASE):
            label = normalize_product_label(segment.split(":", 1)[1])
        elif not re.search(r"\bBGC\d{6,}(?:\.\d+)?\b", segment):
            label = normalize_product_label(segment)
        if label:
            evidence.append(ProductEvidence(label=label, scores=scores))
    return evidence


def product_labels_from_text(text: str) -> list[str]:
    return [evidence.label for evidence in product_evidence_from_text(text)]


def merge_product_evidence(evidence: list[ProductEvidence]) -> tuple[ProductEvidence, ...]:
    deduped: list[ProductEvidence] = []
    seen: set[str] = set()
    display_by_key: dict[str, str] = {}
    scores_by_key: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for product in evidence:
        key = norm_key(product.label)
        if not key:
            continue
        if key not in seen:
            seen.add(key)
            display_by_key[key] = product.label
            deduped.append(product)
        for tool, score in product.scores:
            if score and score not in scores_by_key[key][tool]:
                scores_by_key[key][tool].append(score)

    merged: list[ProductEvidence] = []
    for product in deduped:
        key = norm_key(product.label)
        scores = tuple(
            (tool, score)
            for tool in sorted(scores_by_key[key], key=tool_sort_key)
            for score in scores_by_key[key][tool]
        )
        merged.append(ProductEvidence(label=display_by_key[key], scores=scores))
    return tuple(merged)


def extract_product_evidence(row: dict[str, str]) -> list[ProductEvidence]:
    evidence: list[ProductEvidence] = []
    knowncluster_score = percent_score(row.get("antismash_knowncluster_similarity_score"))
    for column in [
        "antismash_knowncluster_product",
        "representative_annotation",
        "nearest_mibig_or_annotation_if_available",
        "antismash_clustercompare_compounds",
    ]:
        value = clean(row.get(column))
        if value:
            default_scores = (("AS", knowncluster_score),) if column == "antismash_knowncluster_product" and knowncluster_score else ()
            evidence.extend(product_evidence_from_text(value, default_scores=default_scores))
    return list(merge_product_evidence(evidence))


def extract_product_labels(row: dict[str, str]) -> list[str]:
    return [evidence.label for evidence in extract_product_evidence(row)]


def tool_sort_key(tool: str) -> tuple[int, str]:
    order = {"antiSMASH": 0, "ClusterCompare": 1}
    return (order.get(tool, len(order)), tool)


def product_score_text(scores: dict[str, tuple[str, ...]] | tuple[tuple[str, str], ...], max_values: int = 2) -> str:
    grouped: dict[str, list[str]] = defaultdict(list)
    if isinstance(scores, dict):
        for tool, values in scores.items():
            for value in values:
                if value and value not in grouped[tool]:
                    grouped[tool].append(value)
    else:
        for tool, value in scores:
            if value and value not in grouped[tool]:
                grouped[tool].append(value)

    parts: list[str] = []
    for tool in sorted(grouped, key=tool_sort_key):
        values = grouped[tool][:max_values]
        suffix = "" if len(grouped[tool]) <= max_values else "+"
        parts.append(f"{' / '.join(values)}{suffix}")
    return " / ".join(parts)


def putative_product_scores_text(node: NodeRecord) -> str:
    parts: list[str] = []
    for label in node.putative_products:
        scores = node.putative_product_scores.get(label)
        if scores:
            parts.append(f"{label}: {product_score_text(scores, max_values=4)}")
    return "; ".join(parts)


def mibig_accessions(text: str) -> set[str]:
    return {
        match.group(0).split(".", 1)[0]
        for match in re.finditer(r"\bBGC\d{6,}(?:\.\d+)?\b", clean(text))
    }


def score_value(value: object, percent_scale: bool = False) -> float:
    parsed = parse_float(value)
    if parsed is None:
        return 0.0
    if percent_scale or parsed > 1.0:
        parsed = parsed / 100.0
    return max(0.0, min(1.0, parsed))


def parse_annotation_score(row: dict[str, str], annotation_text: str, accession: str) -> float:
    known_accession = clean(row.get("antismash_knowncluster_accession") or row.get("knowncluster_accession"))
    direct_accession = accession in mibig_accessions(known_accession) or re.search(
        rf"\b{re.escape(accession)}(?:\.\d+)?\b\s*\|",
        annotation_text,
    )
    known_score = score_value(row.get("antismash_knowncluster_similarity_score"), percent_scale=True)
    cluster_scores = [float(match.group(1)) for match in re.finditer(r"clustercompare\s+([0-9]*\.?[0-9]+)", annotation_text, re.IGNORECASE)]
    cluster_score = max([score_value(value) for value in cluster_scores] or [0.0])
    # Direct knowncluster accession is the main signal. ClusterCompare and
    # antiSMASH similarity scores break ties between same-accession family members.
    direct_bonus = 0.5 if direct_accession else 0.0
    return direct_bonus + known_score + (0.01 * cluster_score)


def load_mibig_annotation_records(annotation_table: Path | None) -> tuple[dict[str, list[MibigAnnotationHit]], list[str]]:
    """Return BiG-SCAPE records with MiBIG-style BGC accession annotations."""
    if annotation_table is None or not annotation_table.exists():
        return {}, []

    delimiter = "\t"
    first_line = annotation_table.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    if first_line and "," in first_line[0] and "\t" not in first_line[0]:
        delimiter = ","

    records: dict[str, list[MibigAnnotationHit]] = defaultdict(list)
    for row in read_table_rows(annotation_table, delimiter=delimiter):
        record = clean(row.get("bigscape_record")) or clean(row.get("Record"))
        if not record:
            continue
        annotation_text = " ".join(
            clean(row.get(column))
            for column in [
                "nearest_mibig_or_annotation_if_available",
                "antismash_knowncluster_accession",
                "knowncluster_accession",
                "mibig_accession",
            ]
        )
        for accession in sorted(mibig_accessions(annotation_text), key=natural_key):
            records[record].append(MibigAnnotationHit(accession=accession, score=parse_annotation_score(row, annotation_text, accession)))
    return records, []


def load_product_labels(annotation_table: Path | None) -> tuple[dict[str, tuple[ProductEvidence, ...]], list[str]]:
    """Return putative product labels and antiSMASH confidence scores keyed by BiG-SCAPE record."""
    if annotation_table is None or not annotation_table.exists():
        return {}, []

    delimiter = "\t"
    first_line = annotation_table.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    if first_line and "," in first_line[0] and "\t" not in first_line[0]:
        delimiter = ","

    products_by_record: dict[str, list[ProductEvidence]] = defaultdict(list)
    for row in read_table_rows(annotation_table, delimiter=delimiter):
        record = clean(row.get("bigscape_record")) or clean(row.get("Record"))
        if not record:
            continue
        products_by_record[record].extend(extract_product_evidence(row))

    compact: dict[str, tuple[ProductEvidence, ...]] = {}
    for record, products in products_by_record.items():
        merged = merge_product_evidence(products)
        if merged:
            compact[record] = merged
    return compact, []


def assign_product_labels(nodes: dict[str, NodeRecord], products_by_record: dict[str, tuple[ProductEvidence, ...]]) -> list[str]:
    missing = [record for record in products_by_record if record not in nodes]
    for record, products in products_by_record.items():
        if record in nodes:
            nodes[record].putative_products = tuple(product.label for product in products)
            nodes[record].putative_product_scores = {
                product.label: {
                    tool: tuple(value for candidate_tool, value in product.scores if candidate_tool == tool)
                    for tool in sorted({tool for tool, _ in product.scores}, key=tool_sort_key)
                }
                for product in products
                if product.scores
            }
    if missing:
        return [f"Product-labeled records not present in the selected BiG-SCAPE network: {len(missing)}"]
    return []


def mark_mibig_annotations(
    nodes: dict[str, NodeRecord],
    annotated_records: dict[str, list[MibigAnnotationHit]],
) -> list[str]:
    warnings: list[str] = []
    missing = [record for record in annotated_records if record not in nodes]
    grouped_hits: dict[tuple[str, tuple[str, ...]], list[tuple[float, str]]] = defaultdict(list)
    raw_hit_count = 0
    for record, hits in annotated_records.items():
        node = nodes.get(record)
        if node is None or node.is_mibig:
            continue
        family_key = tuple(sorted(node_family_keys(node))) or ("record-family:unknown",)
        for hit in hits:
            raw_hit_count += 1
            grouped_hits[(hit.accession, family_key)].append((hit.score, record))
    selected_records: set[str] = set()
    for hits in grouped_hits.values():
        _, record = sorted(hits, key=lambda item: (-item[0], natural_key(item[1])))[0]
        selected_records.add(record)
    for record in selected_records:
        nodes[record].has_mibig_annotation = True
    if raw_hit_count > len(selected_records):
        warnings.append(
            "Collapsed MiBIG accession markers to best dataset representative per accession/family: "
            f"{raw_hit_count} hits -> {len(selected_records)} marked nodes"
        )
    if missing:
        warnings.append(
            "MiBIG-annotated records not present in the selected BiG-SCAPE network: "
            f"{len(missing)}"
        )
    return warnings


def node_family_keys(node: NodeRecord) -> set[str]:
    keys = {f"family:{family}" for family in re.split(r"[;,]+", clean(node.family)) if clean(family)}
    if clean(node.cc):
        keys.add(f"cc:{node.cc}")
    return keys


def filter_dataset_dependent_mibig_references(
    nodes: dict[str, NodeRecord],
    edges: list[EdgeRecord],
    include_mibig_only: bool = False,
) -> tuple[dict[str, NodeRecord], list[EdgeRecord], list[str]]:
    """Drop MiBIG reference GBKs that do not map to a dataset-containing family."""
    if include_mibig_only:
        return nodes, edges, []

    dataset_family_keys: set[str] = set()
    for node in nodes.values():
        if not node.is_mibig:
            dataset_family_keys.update(node_family_keys(node))

    keep_mibig: set[str] = set()
    for node_id, node in nodes.items():
        if not node.is_mibig:
            continue
        if node_family_keys(node) & dataset_family_keys:
            keep_mibig.add(node_id)

    for edge in edges:
        source = nodes.get(edge.source)
        target = nodes.get(edge.target)
        if source is None or target is None:
            continue
        if source.is_mibig and not target.is_mibig:
            keep_mibig.add(edge.source)
        if target.is_mibig and not source.is_mibig:
            keep_mibig.add(edge.target)

    kept_nodes = {
        node_id: node
        for node_id, node in nodes.items()
        if not node.is_mibig or node_id in keep_mibig
    }
    kept_edges = [edge for edge in edges if edge.source in kept_nodes and edge.target in kept_nodes]
    omitted = len(nodes) - len(kept_nodes)
    warnings = []
    if omitted:
        warnings.append(f"Omitted MiBIG reference nodes outside dataset-dependent families: {omitted}")
    return kept_nodes, kept_edges, warnings


def load_edges(
    network_path: Path | None,
    node_ids: set[str],
    distance_threshold: float | None,
    similarity_threshold: float | None,
) -> tuple[list[EdgeRecord], list[str]]:
    warnings: list[str] = []
    if network_path is None or not network_path.exists():
        return [], ["No BiG-SCAPE network edge table found; rendering nodes without edges."]

    by_pair: dict[tuple[str, str], EdgeRecord] = {}
    for row in read_table_rows(network_path):
        source = clean(row.get("Record_a"))
        target = clean(row.get("Record_b"))
        if not source or not target or source == target:
            continue
        if source not in node_ids or target not in node_ids:
            continue
        distance = parse_float(row.get("distance"))
        if distance_threshold is not None and distance is not None and distance > distance_threshold:
            continue
        if similarity_threshold is not None and distance is not None and (1.0 - distance) < similarity_threshold:
            continue
        pair = tuple(sorted([source, target], key=natural_key))
        edge = EdgeRecord(
            source=pair[0],
            target=pair[1],
            distance=distance,
            jaccard=clean(row.get("jaccard")),
            adjacency=clean(row.get("adjacency")),
            dss=clean(row.get("dss")),
            weights=clean(row.get("weights")),
            alignment_mode=clean(row.get("alignment_mode")),
            extend_strategy=clean(row.get("extend_strategy")),
        )
        existing = by_pair.get(pair)
        if existing is None:
            by_pair[pair] = edge
        elif edge.distance is not None and (existing.distance is None or edge.distance < existing.distance):
            by_pair[pair] = edge

    return sorted(by_pair.values(), key=lambda e: (natural_key(e.source), natural_key(e.target))), warnings


def load_metadata(
    metadata_path: Path | None,
    ecology_field: str,
    metadata_id_column: str = "",
) -> tuple[dict[str, str], list[str], tuple[str, str] | None]:
    warnings: list[str] = []
    if metadata_path is None or not metadata_path.exists():
        return {}, warnings, None

    metadata_lines = metadata_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    if not metadata_lines:
        return {}, [f"Metadata table is empty: {metadata_path}"], None
    header_text = metadata_lines[0]
    delimiter = "\t" if "\t" in header_text else ","
    rows = read_table_rows(metadata_path, delimiter=delimiter)
    if not rows:
        return {}, [f"Metadata table is empty: {metadata_path}"], None

    headers = list(rows[0].keys())
    by_lower = {h.casefold(): h for h in headers}

    id_candidates = [
        metadata_id_column,
        "sample_id",
        "fungal_id",
        "genome_id_current",
        "genome",
        "isolate",
    ]
    ecology_candidates = [
        ecology_field,
        "ecology_category",
        "ecology_group",
        "ecofun_primary",
        "ecofun_secondary",
        "ecology",
        "sample_ecology",
    ]

    id_col = next((by_lower[c.casefold()] for c in id_candidates if clean(c) and c.casefold() in by_lower), "")
    eco_col = next((by_lower[c.casefold()] for c in ecology_candidates if clean(c) and c.casefold() in by_lower), "")
    if not id_col:
        return {}, [f"Metadata table has no recognized ID column: {metadata_path}"], None
    if not eco_col:
        warnings.append(f"Metadata table has no recognized ecology column: {metadata_path}")

    metadata: dict[str, str] = {}
    missing_category = 0
    fallback_category = 0
    fallback_cols = [
        by_lower[c.casefold()]
        for c in ecology_candidates
        if clean(c) and c.casefold() in by_lower and by_lower[c.casefold()] != eco_col
    ]
    for row in rows:
        sample_id = clean(row.get(id_col))
        if not sample_id:
            continue
        category = clean(row.get(eco_col)) if eco_col else ""
        if not category:
            for fallback_col in fallback_cols:
                category = clean(row.get(fallback_col))
                if category:
                    fallback_category += 1
                    break
        if not category:
            missing_category += 1
            category = UNKNOWN
        metadata[sample_id] = category

    if missing_category:
        warnings.append(f"Metadata rows with missing ecology category were assigned '{UNKNOWN}': {missing_category}")
    if fallback_category:
        warnings.append(f"Metadata rows used a fallback ecology column because the selected field was blank: {fallback_category}")
    return metadata, warnings, (id_col, eco_col or "")


def assign_metadata_and_labels(nodes: dict[str, NodeRecord], metadata: dict[str, str]) -> list[str]:
    warnings: list[str] = []
    metadata_norm = {norm_key(key): value for key, value in metadata.items()}
    used_metadata_keys: set[str] = set()
    missing_metadata_samples: set[str] = set()

    for node in nodes.values():
        if node.is_mibig:
            node.ecology_category = UNKNOWN
            continue
        ecology = metadata.get(node.sample_id)
        if ecology is None:
            ecology = metadata_norm.get(norm_key(node.sample_id))
        if ecology is None:
            missing_metadata_samples.add(node.sample_id)
            ecology = UNKNOWN
        else:
            used_metadata_keys.add(norm_key(node.sample_id))
        node.ecology_category = clean(ecology) or UNKNOWN

    unmatched = sorted(
        [sample_id for sample_id in metadata if norm_key(sample_id) not in used_metadata_keys],
        key=natural_key,
    )
    if missing_metadata_samples:
        sample_list = ", ".join(sorted(missing_metadata_samples, key=natural_key)[:10])
        suffix = "" if len(missing_metadata_samples) <= 10 else f" (+{len(missing_metadata_samples) - 10} more)"
        warnings.append(f"No ecology metadata matched these sample IDs; using '{UNKNOWN}': {sample_list}{suffix}")
    if unmatched:
        sample_list = ", ".join(unmatched[:10])
        suffix = "" if len(unmatched) <= 10 else f" (+{len(unmatched) - 10} more)"
        warnings.append(f"Metadata IDs not present in the BiG-SCAPE network: {sample_list}{suffix}")

    sample_ids = sorted({node.sample_id for node in nodes.values()}, key=lambda value: (value == MIBIG_SAMPLE_ID, natural_key(value)))
    label_by_sample = {sample_id: str(index) for index, sample_id in enumerate(sample_ids, start=1)}
    for node in nodes.values():
        node.label_number = label_by_sample[node.sample_id]
        node.border_color = stable_label_color(node.ecology_category)
    return warnings


def graph_components(nodes: dict[str, NodeRecord], edges: list[EdgeRecord]) -> list[list[str]]:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for edge in edges:
        if edge.source in adjacency and edge.target in adjacency:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)

    seen: set[str] = set()
    components: list[list[str]] = []
    for start in sorted(nodes, key=natural_key):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        comp: list[str] = []
        while stack:
            current = stack.pop()
            comp.append(current)
            for neighbor in sorted(adjacency[current], key=natural_key, reverse=True):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        components.append(sorted(comp, key=natural_key))
    edge_counts: dict[frozenset[str], int] = {}
    for comp in components:
        comp_set = frozenset(comp)
        edge_counts[comp_set] = sum(1 for edge in edges if edge.source in comp_set and edge.target in comp_set)

    return sorted(components, key=lambda comp: (-edge_counts[frozenset(comp)], -len(comp), natural_key(comp[0])))


def filter_graph(
    nodes: dict[str, NodeRecord],
    edges: list[EdgeRecord],
    max_nodes: int = 0,
    max_components: int = 0,
) -> tuple[dict[str, NodeRecord], list[EdgeRecord], list[str]]:
    warnings: list[str] = []
    components = graph_components(nodes, edges)

    if max_components > 0:
        kept_ids = {node_id for comp in components[:max_components] for node_id in comp}
        omitted = len(nodes) - len(kept_ids)
        nodes = {node_id: node for node_id, node in nodes.items() if node_id in kept_ids}
        edges = [edge for edge in edges if edge.source in nodes and edge.target in nodes]
        components = graph_components(nodes, edges)
        if omitted:
            warnings.append(f"Omitted {omitted} nodes after --max-components={max_components}.")

    if max_nodes > 0 and len(nodes) > max_nodes:
        kept_ids: set[str] = set()
        for comp in components:
            if len(kept_ids) + len(comp) <= max_nodes or not kept_ids:
                kept_ids.update(comp[: max(0, max_nodes - len(kept_ids))])
            if len(kept_ids) >= max_nodes:
                break
        omitted = len(nodes) - len(kept_ids)
        nodes = {node_id: node for node_id, node in nodes.items() if node_id in kept_ids}
        edges = [edge for edge in edges if edge.source in nodes and edge.target in nodes]
        if omitted:
            warnings.append(f"Omitted {omitted} nodes after --max-nodes={max_nodes}.")

    return nodes, edges, warnings


def component_edges(component: set[str], edges: list[EdgeRecord]) -> list[EdgeRecord]:
    return [edge for edge in edges if edge.source in component and edge.target in component]


def local_component_layout(component: list[str], edges: list[EdgeRecord], iterations: int) -> tuple[dict[str, tuple[float, float]], float, float]:
    """Deterministically lay out one connected component in a local box."""
    n = len(component)
    if n == 1:
        return {component[0]: (30.0, 30.0)}, 60.0, 60.0
    if n == 2:
        return {component[0]: (24.0, 24.0), component[1]: (24.0, 68.0)}, 48.0, 92.0

    cols = max(2, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / cols)
    width = max(150.0, cols * 58.0)
    height = max(120.0, rows * 58.0)
    radius = 0.38 * min(width, height)
    cx = width / 2.0
    cy = height / 2.0

    positions: dict[str, tuple[float, float]] = {}
    for index, node_id in enumerate(component):
        angle = (2.0 * math.pi * index / n) - math.pi / 2.0
        positions[node_id] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))

    if n <= 80 and edges:
        area = width * height
        k = math.sqrt(area / max(n, 1))
        edge_pairs = [(edge.source, edge.target, edge.similarity or 0.7) for edge in edges]
        for step in range(max(0, iterations)):
            disp = {node_id: [0.0, 0.0] for node_id in component}
            for i, v in enumerate(component):
                vx, vy = positions[v]
                for u in component[i + 1 :]:
                    ux, uy = positions[u]
                    dx = vx - ux
                    dy = vy - uy
                    dist = math.hypot(dx, dy) or 0.01
                    force = (k * k) / dist
                    fx = dx / dist * force
                    fy = dy / dist * force
                    disp[v][0] += fx
                    disp[v][1] += fy
                    disp[u][0] -= fx
                    disp[u][1] -= fy
            for source, target, similarity in edge_pairs:
                sx, sy = positions[source]
                tx, ty = positions[target]
                dx = sx - tx
                dy = sy - ty
                dist = math.hypot(dx, dy) or 0.01
                force = (dist * dist / k) * (0.5 + similarity)
                fx = dx / dist * force
                fy = dy / dist * force
                disp[source][0] -= fx
                disp[source][1] -= fy
                disp[target][0] += fx
                disp[target][1] += fy
            temperature = max(width, height) * 0.08 * (1.0 - step / max(iterations, 1))
            for node_id in component:
                dx, dy = disp[node_id]
                length = math.hypot(dx, dy) or 0.01
                x, y = positions[node_id]
                x += dx / length * min(length, temperature)
                y += dy / length * min(length, temperature)
                margin = 18.0
                positions[node_id] = (
                    min(width - margin, max(margin, x)),
                    min(height - margin, max(margin, y)),
                )

    min_x = min(x for x, _ in positions.values())
    max_x = max(x for x, _ in positions.values())
    min_y = min(y for _, y in positions.values())
    max_y = max(y for _, y in positions.values())
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    margin = 22.0
    normalized = {
        node_id: (
            margin + (x - min_x) / span_x * (width - 2 * margin),
            margin + (y - min_y) / span_y * (height - 2 * margin),
        )
        for node_id, (x, y) in positions.items()
    }
    return normalized, width, height


def build_layout(
    nodes: dict[str, NodeRecord],
    edges: list[EdgeRecord],
    canvas_width: int,
    layout_iterations: int,
    reserved_top_left: tuple[float, float] | None = None,
    combine_connected_components: bool = False,
    network_content_width: float | None = None,
    top_margin: float = 36.0,
) -> LayoutResult:
    margin = 36.0
    gap = 34.0
    row_gap = 56.0
    legend_width = 420.0
    network_width = max(480.0, canvas_width - legend_width - 3 * margin)
    pack_network_width = min(network_width, network_content_width) if network_content_width else network_width
    legend_x = margin + network_width + margin

    components = graph_components(nodes, edges)
    large = [comp for comp in components if len(comp) >= 6]
    medium_small = [comp for comp in components if 2 < len(comp) < 6]
    doubletons = [comp for comp in components if len(comp) == 2]
    singletons = [comp[0] for comp in components if len(comp) == 1]

    positions: dict[str, tuple[float, float]] = {}
    y = top_margin
    section_y: dict[str, float] = {}

    def row_left_for(y_cursor: float) -> float:
        if reserved_top_left is None:
            return margin
        reserved_width, reserved_height = reserved_top_left
        if y_cursor < margin + reserved_height:
            return margin + reserved_width + gap
        return margin

    def pack_layer(layer: list[list[str]], start_y: float, section_name: str) -> float:
        if not layer:
            return start_y
        section_y[section_name] = start_y
        row_top = start_y + 18.0
        row_height = 0.0
        y_cursor = row_top
        x = row_left_for(y_cursor)
        for comp in layer:
            comp_set = set(comp)
            local_edges = component_edges(comp_set, edges)
            local_pos, box_w, box_h = local_component_layout(comp, local_edges, layout_iterations)
            if x + box_w > margin + pack_network_width and x > margin:
                y_cursor += row_height + row_gap
                row_height = 0.0
                x = row_left_for(y_cursor)
            for node_id, (local_x, local_y) in local_pos.items():
                positions[node_id] = (x + local_x, y_cursor + local_y)
            x += box_w + gap
            row_height = max(row_height, box_h)
        return y_cursor + row_height + row_gap

    def pack_doubletons(layer: list[list[str]], start_y: float) -> float:
        if not layer:
            return start_y
        section_y["doubletons"] = start_y
        cell_w = 50.0
        cell_h = 84.0
        left = row_left_for(start_y)
        right = margin + pack_network_width
        cols = max(1, int(max(cell_w, right - left) // cell_w))
        for index, comp in enumerate(layer):
            col = index % cols
            row = index // cols
            x = left + col * cell_w + cell_w / 2.0
            y0 = start_y + 30.0 + row * cell_h
            positions[comp[0]] = (x, y0)
            positions[comp[1]] = (x, y0 + 42.0)
        rows = math.ceil(len(layer) / cols)
        return start_y + 116.0 + max(0, rows - 1) * cell_h

    if combine_connected_components:
        y = pack_layer(large + medium_small, y, "medium_small")
    else:
        y = pack_layer(large, y, "large")
        y = pack_layer(medium_small, y, "medium_small")
    y = pack_doubletons(doubletons, y)

    if singletons:
        section_y["singletons"] = y
        cell = 38.0
        left = row_left_for(y)
        right = margin + pack_network_width
        cols = max(1, int(max(cell, right - left) // cell))
        for index, node_id in enumerate(sorted(singletons, key=natural_key)):
            col = index % cols
            row = index // cols
            positions[node_id] = (left + col * cell + cell / 2.0, y + 30.0 + row * cell)
        rows = math.ceil(len(singletons) / cols)
        y += 58.0 + max(0, rows - 1) * cell

    sample_count = len({node.sample_id for node in nodes.values()})
    class_count = len({node.bgc_class for node in nodes.values()})
    ecology_count = (
        len({node.ecology_category for node in nodes.values() if not is_unknown_ecology(node.ecology_category)})
        if has_ecology_signal(nodes)
        else 0
    )
    marker_count = int(any(node.is_mibig for node in nodes.values())) + int(
        any(node.has_mibig_annotation and not node.is_mibig for node in nodes.values())
    )
    product_note_count = int(any(node.putative_product_scores for node in nodes.values()))
    legend_height = 205 + 22 * sample_count + 34 * class_count + 36 * ecology_count + 38 * marker_count + 20 * product_note_count
    canvas_height = int(max(y + margin, legend_height + margin))
    return LayoutResult(
        positions=positions,
        width=canvas_width,
        height=canvas_height,
        legend_x=legend_x,
        section_y=section_y,
        section_right=margin + pack_network_width,
    )


def svg_text(x: float, y: float, text: str, size: int = 11, weight: str = "400", anchor: str = "start") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial, Helvetica, sans-serif" '
        f'font-size="{display_font_size(size):g}" font-weight="{weight}" text-anchor="{anchor}" fill="#222222">'
        f"{escape(text)}</text>"
    )


def shorten(text: str, limit: int = 48) -> str:
    value = clean(text)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def display_font_size(size: int | float) -> float:
    return max(4.0, float(size) + FONT_SIZE_INCREMENT)


def sample_name_parts(sample_id: str) -> tuple[str, str]:
    display = re.sub(r"\s+", " ", clean(sample_id).replace("_", " ")).strip()
    if not display or display == MIBIG_SAMPLE_ID:
        return "", display
    words = display.split()
    if len(words) < 2 or not words[0].isalpha():
        return "", display

    italic_words = [words[0]]
    plain_words = words[1:]
    if words[1].isalpha() and words[1].casefold().rstrip(".") not in {"sp", "spp", "cf", "aff", "strain", "isolate"}:
        italic_words.append(words[1])
        plain_words = words[2:]
    return " ".join(italic_words), " ".join(plain_words)


def sample_display_text(sample_id: str) -> str:
    italic, plain = sample_name_parts(sample_id)
    return f"{italic} {plain}".strip() if italic else plain


def svg_sample_name_tspans(sample_id: str, suffix: str = "") -> str:
    italic, plain = sample_name_parts(sample_id)
    suffix_text = escape(suffix)
    if italic:
        plain_text = f" {plain}" if plain else ""
        return (
            f'<tspan font-style="italic">{escape(italic)}</tspan>'
            f"<tspan>{escape(plain_text)}{suffix_text}</tspan>"
        )
    return f"<tspan>{escape(plain)}{suffix_text}</tspan>"


def svg_sample_label(
    x: float,
    y: float,
    sample_id: str,
    size: int,
    weight: str = "400",
    anchor: str = "start",
    fill: str = "#222222",
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial, Helvetica, sans-serif" '
        f'font-size="{display_font_size(size):g}" font-weight="{weight}" text-anchor="{anchor}" fill="{fill}">'
        f"{svg_sample_name_tspans(sample_id)}</text>"
    )


def estimated_svg_text_width(text: str, size: int | float, weight: str = "400") -> float:
    font_size = display_font_size(size)
    weight_factor = 0.58 if str(weight) in {"700", "800", "bold"} else 0.53
    return len(clean(text)) * font_size * weight_factor


def bigscape_category_label(category: str) -> str:
    value = clean(category)
    if value.casefold() == "mix":
        return "all BGC classes (mix)"
    return value or UNKNOWN


def wrap_label_text(text: str, max_chars: int = 24, max_lines: int = 2) -> list[str]:
    words = clean(text).split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        kept[-1] = shorten(" ".join(lines[max_lines - 1 :]), max_chars)
        return kept
    return lines


def component_product_label_lines(component: list[str], nodes: dict[str, NodeRecord]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    display_by_key: dict[str, str] = {}
    scores_by_key: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for node_id in component:
        node = nodes[node_id]
        if node.is_mibig:
            continue
        for label in node.putative_products:
            key = norm_key(label)
            if not key:
                continue
            counts[key] += 1
            display_by_key.setdefault(key, label)
            for tool, values in node.putative_product_scores.get(label, {}).items():
                for value in values:
                    if value and value not in scores_by_key[key][tool]:
                        scores_by_key[key][tool].append(value)
    if not counts:
        return []
    ordered = sorted(
        counts,
        key=lambda key: (
            -counts[key],
            -sum(len(values) for values in scores_by_key[key].values()),
            natural_key(display_by_key[key]),
        ),
    )
    key = ordered[0]
    suffix = "" if len(ordered) == 1 else f" +{len(ordered) - 1}"
    product_lines = wrap_label_text(display_by_key[key] + suffix)
    score_text = product_score_text(scores_by_key[key], max_values=3) if scores_by_key[key] else ""
    return product_lines + ([score_text] if score_text else [])


def component_label_entries(
    nodes: dict[str, NodeRecord],
    edges: list[EdgeRecord],
    positions: dict[str, tuple[float, float]],
) -> list[tuple[float, float, list[str]]]:
    entries: list[tuple[float, float, list[str]]] = []
    for component in graph_components(nodes, edges):
        if len(component) <= 2:
            continue
        label_lines = component_product_label_lines(component, nodes)
        if not label_lines:
            continue
        xs = [positions[node_id][0] for node_id in component if node_id in positions]
        ys = [positions[node_id][1] for node_id in component if node_id in positions]
        if not xs or not ys:
            continue
        x = (min(xs) + max(xs)) / 2.0
        y = max(18.0, min(ys) - 44.0)
        entries.append((x, y, label_lines))
    return entries


def node_radius(node_count: int) -> float:
    return 12.0


def visible_node_radius(node: NodeRecord, base_radius: float, show_ecology: bool) -> float:
    if node.is_mibig:
        return base_radius + 6.0
    if show_ecology and not is_unknown_ecology(node.ecology_category):
        return base_radius + 2.5
    return base_radius


def trimmed_edge_endpoints(
    source_xy: tuple[float, float],
    target_xy: tuple[float, float],
    source_radius: float,
    target_radius: float,
    padding: float = 1.0,
) -> tuple[float, float, float, float] | None:
    x1, y1 = source_xy
    x2, y2 = target_xy
    dx = x2 - x1
    dy = y2 - y1
    distance = math.hypot(dx, dy)
    source_trim = source_radius + padding
    target_trim = target_radius + padding
    if distance <= source_trim + target_trim:
        return None
    ux = dx / distance
    uy = dy / distance
    return (
        x1 + ux * source_trim,
        y1 + uy * source_trim,
        x2 - ux * target_trim,
        y2 - uy * target_trim,
    )


def render_svg(
    path: Path,
    nodes: dict[str, NodeRecord],
    edges: list[EdgeRecord],
    layout: LayoutResult,
    inputs: BigscapeInputs,
    pre_body_lines: Iterable[str] | None = None,
    section_titles: dict[str, str | None] | None = None,
    section_x: float = 36.0,
) -> None:
    r = node_radius(len(nodes))
    show_ecology = has_ecology_signal(nodes)
    has_annotation_marker = any(node.has_mibig_annotation and not node.is_mibig for node in nodes.values())
    has_reference_marker = any(node.is_mibig for node in nodes.values())
    lines: list[str] = []

    if pre_body_lines:
        lines.extend(pre_body_lines)

    def section_title(key: str, default: str) -> str | None:
        if section_titles is not None and key in section_titles:
            return section_titles[key]
        return default

    large_title = section_title("large", "Large connected components")
    if "large" in layout.section_y and large_title:
        lines.append(svg_text(section_x, layout.section_y["large"] + 1, large_title, 12, "700"))
    medium_small_title = section_title("medium_small", "Connected GCFs")
    if "medium_small" in layout.section_y and medium_small_title:
        lines.append(svg_text(section_x, layout.section_y["medium_small"] + 1, medium_small_title, 12, "700"))
    doubleton_title = section_title("doubletons", "Doubletons")
    if "doubletons" in layout.section_y:
        y = layout.section_y["doubletons"] - 18
        section_right = layout.section_right or layout.legend_x - 44
        lines.append(f'<line x1="{section_x:.1f}" y1="{y:.1f}" x2="{section_right:.1f}" y2="{y:.1f}" stroke="#DDDDDD" stroke-width="1"/>')
        if doubleton_title:
            lines.append(svg_text(section_x, layout.section_y["doubletons"] + 1, doubleton_title, 12, "700"))
    singleton_title = section_title("singletons", "Singletons")
    if "singletons" in layout.section_y:
        y = layout.section_y["singletons"] - 18
        section_right = layout.section_right or layout.legend_x - 44
        lines.append(f'<line x1="{section_x:.1f}" y1="{y:.1f}" x2="{section_right:.1f}" y2="{y:.1f}" stroke="#DDDDDD" stroke-width="1"/>')
        if singleton_title:
            lines.append(svg_text(section_x, layout.section_y["singletons"] + 1, singleton_title, 12, "700"))

    for edge in edges:
        if edge.source not in layout.positions or edge.target not in layout.positions:
            continue
        trimmed = trimmed_edge_endpoints(
            layout.positions[edge.source],
            layout.positions[edge.target],
            visible_node_radius(nodes[edge.source], r, show_ecology),
            visible_node_radius(nodes[edge.target], r, show_ecology),
        )
        if trimmed is None:
            continue
        x1, y1, x2, y2 = trimmed
        similarity = edge.similarity if edge.similarity is not None else 0.55
        width = 0.8 + 2.0 * similarity
        lines.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="#8B8B8B" stroke-width="{width:.2f}" stroke-opacity="0.38"/>'
        )

    for x, y, label_lines in component_label_entries(nodes, edges, layout.positions):
        line_height = 14.0
        for index, line in enumerate(label_lines):
            size = PRODUCT_SCORE_FONT_SIZE if index == len(label_lines) - 1 and line.endswith("%") else PRODUCT_LABEL_FONT_SIZE
            weight = "400" if size == PRODUCT_SCORE_FONT_SIZE else "700"
            fill = "#444444" if size == PRODUCT_SCORE_FONT_SIZE else "#222222"
            lines.append(
                f'<text x="{x:.1f}" y="{y + 7.0 + index * line_height:.1f}" '
                f'font-family="Arial, Helvetica, sans-serif" font-size="{display_font_size(size):g}" font-weight="{weight}" '
                f'text-anchor="middle" fill="{fill}">{escape(line)}</text>'
            )

    for node_id in sorted(nodes, key=natural_key):
        node = nodes[node_id]
        if node_id not in layout.positions:
            continue
        x, y = layout.positions[node_id]
        if node.is_mibig:
            lines.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r + 6:.2f}" fill="none" '
                f'stroke="{MIBIG_BLUE}" stroke-width="3.0"/>'
            )
        if show_ecology and not node.is_mibig and not is_unknown_ecology(node.ecology_category):
            lines.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r + 2.5:.2f}" fill="none" '
                f'stroke="{node.border_color}" stroke-width="3.0"/>'
            )
        lines.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="{node.fill_color}" '
            f'stroke="#333333" stroke-width="1.1"/>'
        )
        if node.has_mibig_annotation and not node.is_mibig:
            dot_r = max(2.8, r * 0.34)
            lines.append(
                f'<circle cx="{x + r * 0.78:.2f}" cy="{y - r * 0.78:.2f}" r="{dot_r:.2f}" '
                f'fill="{MIBIG_BLUE}" stroke="#FFFFFF" stroke-width="1.0"/>'
            )
        base_font_size = 8 if len(node.label_number) > 2 or r < 8 else 9
        font_size = display_font_size(base_font_size)
        lines.append(
            f'<text x="{x:.2f}" y="{y + font_size / 2.7:.2f}" font-family="Arial, Helvetica, sans-serif" '
            f'font-size="{font_size:g}" font-weight="800" text-anchor="middle" fill="#111111">{escape(node.label_number)}</text>'
        )

    legend_x = layout.legend_x
    legend_padding = 18.0
    legend_box_x = legend_x - legend_padding
    legend_box_y = 4.0
    legend_start_index = len(lines)
    legend_text_widths: list[float] = [estimated_svg_text_width("BiG-SCAPE Network", 18, "700")]
    y = 42.0
    lines.append(svg_text(legend_x, y, "BiG-SCAPE Network", 18, "700"))
    y += 24
    if any(node.putative_product_scores for node in nodes.values()):
        legend_text_widths.append(estimated_svg_text_width("Product scores are antiSMASH ClusterCompare (%).", 11))
        lines.append(svg_text(legend_x, y, "Product scores are antiSMASH ClusterCompare (%).", 11))
        y += 28

    sample_counts: dict[str, int] = defaultdict(int)
    for node in nodes.values():
        sample_counts[node.sample_id] += 1
    samples = sorted(sample_counts, key=lambda value: int(next(n.label_number for n in nodes.values() if n.sample_id == value)))
    label_by_sample = {node.sample_id: node.label_number for node in nodes.values()}

    lines.append(svg_text(legend_x, y, "Node Labels", 14, "700"))
    legend_text_widths.append(estimated_svg_text_width("Node Labels", 14, "700"))
    y += 22
    for sample_id in samples:
        label = label_by_sample[sample_id]
        count = sample_counts[sample_id]
        legend_text_widths.append(estimated_svg_text_width(f"{label} = {sample_display_text(sample_id)} ({count})", 11, "800"))
        lines.append(
            f'<text x="{legend_x:.1f}" y="{y:.1f}" font-family="Arial, Helvetica, sans-serif" '
            f'font-size="{display_font_size(11):g}" font-weight="400" text-anchor="start" fill="#222222">'
            f'<tspan font-weight="800">{escape(label)}</tspan><tspan> = </tspan>'
            f'{svg_sample_name_tspans(sample_id, f" ({count})")}</text>'
        )
        y += 20
    y += 14

    lines.append(svg_text(legend_x, y, "BGC Class Fill", 14, "700"))
    legend_text_widths.append(estimated_svg_text_width("BGC Class Fill", 14, "700"))
    y += 28
    used_classes = sorted({node.bgc_class for node in nodes.values()}, key=lambda value: CLASS_ORDER.index(value) if value in CLASS_ORDER else len(CLASS_ORDER))
    for class_name in used_classes:
        color = CLASS_COLORS.get(class_name, CLASS_COLORS["other"])
        lines.append(f'<circle cx="{legend_x + 12:.1f}" cy="{y - 5:.1f}" r="12" fill="{color}" stroke="#333333" stroke-width="1.1"/>')
        legend_text_widths.append(32.0 + estimated_svg_text_width(class_name, 11))
        lines.append(svg_text(legend_x + 32, y, class_name, 11))
        y += 30
    y += 10

    if show_ecology:
        lines.append(svg_text(legend_x, y, "Ecology Border", 14, "700"))
        legend_text_widths.append(estimated_svg_text_width("Ecology Border", 14, "700"))
        y += 30
        used_ecology = sorted(
            {node.ecology_category for node in nodes.values() if not is_unknown_ecology(node.ecology_category)},
            key=natural_key,
        )
        for ecology in used_ecology:
            color = stable_label_color(ecology)
            lines.append(f'<circle cx="{legend_x + 14.5:.1f}" cy="{y - 5:.1f}" r="14.5" fill="none" stroke="{color}" stroke-width="3"/>')
            legend_text_widths.append(36.0 + estimated_svg_text_width(shorten(ecology, 45), 11))
            lines.append(svg_text(legend_x + 36, y, shorten(ecology, 45), 11))
            y += 32
        if any(is_unknown_ecology(node.ecology_category) for node in nodes.values()):
            lines.append(f'<circle cx="{legend_x + 14.5:.1f}" cy="{y - 5:.1f}" r="14.5" fill="none" stroke="#8A8A8A" stroke-width="1.2" stroke-dasharray="2 2"/>')
            legend_text_widths.append(36.0 + estimated_svg_text_width("unknown/unlabeled (no border)", 11))
            lines.append(svg_text(legend_x + 36, y, "unknown/unlabeled (no border)", 11))
            y += 32
        y += 10

    if has_reference_marker or has_annotation_marker:
        lines.append(svg_text(legend_x, y, "MiBIG Marker", 14, "700"))
        legend_text_widths.append(estimated_svg_text_width("MiBIG Marker", 14, "700"))
        y += 34
        if has_reference_marker:
            lines.append(f'<circle cx="{legend_x + 18:.1f}" cy="{y - 5:.1f}" r="18" fill="none" stroke="{MIBIG_BLUE}" stroke-width="3"/>')
            legend_text_widths.append(42.0 + estimated_svg_text_width("MiBIG reference GBK", 11))
            lines.append(svg_text(legend_x + 42, y, "MiBIG reference GBK", 11))
            y += 36
        if has_annotation_marker:
            lines.append(f'<circle cx="{legend_x + 18:.1f}" cy="{y - 5:.1f}" r="4.1" fill="{MIBIG_BLUE}" stroke="#FFFFFF" stroke-width="1"/>')
            legend_text_widths.append(42.0 + estimated_svg_text_width("representative dataset hit", 11))
            lines.append(svg_text(legend_x + 42, y, "representative dataset hit", 11))

    available_legend_w = max(360.0, layout.width - legend_box_x - legend_padding)
    legend_content_w = max(legend_text_widths) if legend_text_widths else 0.0
    legend_box_w = min(available_legend_w, max(360.0, legend_content_w + 2 * legend_padding))
    legend_box_h = max(120.0, y + 21.0 - legend_box_y)
    lines.insert(
        legend_start_index,
        f'<rect x="{legend_box_x:.1f}" y="{legend_box_y:.1f}" width="{legend_box_w:.1f}" '
        f'height="{legend_box_h:.1f}" fill="none" stroke="#DADADA" stroke-width="1.2"/>',
    )

    output_width = int(math.ceil(max(layout.section_right, legend_box_x + legend_box_w + legend_padding, 1.0)))
    document_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{output_width}" height="{layout.height}" viewBox="0 0 {output_width} {layout.height}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#FFFFFF"/>',
        *lines,
        "</svg>",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(document_lines) + "\n", encoding="utf-8")


def graphml_attr(value: object) -> str:
    if value is None:
        return ""
    return escape(str(value), {'"': "&quot;"})


def write_graphml(path: Path, nodes: dict[str, NodeRecord], edges: list[EdgeRecord], positions: dict[str, tuple[float, float]]) -> None:
    node_keys = {
        "label_number": "string",
        "sample_id": "string",
        "bgc_class": "string",
        "raw_class": "string",
        "ecology_category": "string",
        "is_mibig": "boolean",
        "has_mibig_annotation": "boolean",
        "putative_products": "string",
        "putative_product_scores": "string",
        "family": "string",
        "cc": "string",
        "gbk": "string",
        "organism": "string",
        "description": "string",
        "fill_color": "string",
        "border_color": "string",
        "x": "double",
        "y": "double",
    }
    edge_keys = {
        "distance": "double",
        "similarity": "double",
        "jaccard": "string",
        "adjacency": "string",
        "dss": "string",
        "weights": "string",
    }
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">']
    for key_id, attr_type in node_keys.items():
        lines.append(f'  <key id="{key_id}" for="node" attr.name="{key_id}" attr.type="{attr_type}"/>')
    for key_id, attr_type in edge_keys.items():
        lines.append(f'  <key id="{key_id}" for="edge" attr.name="{key_id}" attr.type="{attr_type}"/>')
    lines.append('  <graph id="ClusterWeave_BiG_SCAPE" edgedefault="undirected">')
    for node_id in sorted(nodes, key=natural_key):
        node = nodes[node_id]
        x, y = positions.get(node_id, (0.0, 0.0))
        values = {
            "label_number": node.label_number,
            "sample_id": node.sample_id,
            "bgc_class": node.bgc_class,
            "raw_class": node.raw_class,
            "ecology_category": node.ecology_category,
            "is_mibig": str(node.is_mibig).lower(),
            "has_mibig_annotation": str(node.has_mibig_annotation).lower(),
            "putative_products": "; ".join(node.putative_products),
            "putative_product_scores": putative_product_scores_text(node),
            "family": node.family,
            "cc": node.cc,
            "gbk": node.gbk,
            "organism": node.organism,
            "description": node.description,
            "fill_color": node.fill_color,
            "border_color": node.border_color,
            "x": f"{x:.3f}",
            "y": f"{y:.3f}",
        }
        lines.append(f'    <node id="{graphml_attr(node_id)}">')
        for key_id, value in values.items():
            lines.append(f'      <data key="{key_id}">{graphml_attr(value)}</data>')
        lines.append("    </node>")
    for idx, edge in enumerate(edges, start=1):
        values = {
            "distance": "" if edge.distance is None else f"{edge.distance:.6g}",
            "similarity": "" if edge.similarity is None else f"{edge.similarity:.6g}",
            "jaccard": edge.jaccard,
            "adjacency": edge.adjacency,
            "dss": edge.dss,
            "weights": edge.weights,
        }
        lines.append(f'    <edge id="e{idx}" source="{graphml_attr(edge.source)}" target="{graphml_attr(edge.target)}">')
        for key_id, value in values.items():
            if value != "":
                lines.append(f'      <data key="{key_id}">{graphml_attr(value)}</data>')
        lines.append("    </edge>")
    lines.append("  </graph>")
    lines.append("</graphml>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def node_attribute_rows(nodes: dict[str, NodeRecord], positions: dict[str, tuple[float, float]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for node_id in sorted(nodes, key=natural_key):
        node = nodes[node_id]
        x, y = positions.get(node_id, (0.0, 0.0))
        rows.append(
            {
                "bigscape_record": node.record,
                "label_number": node.label_number,
                "sample_id": node.sample_id,
                "bigscape_gbk": node.gbk,
                "cc": node.cc,
                "family": node.family,
                "bgc_class": node.bgc_class,
                "raw_class": node.raw_class,
                "category": node.category,
                "ecology_category": node.ecology_category,
                "is_mibig": str(node.is_mibig).lower(),
                "has_mibig_annotation": str(node.has_mibig_annotation).lower(),
                "putative_products": "; ".join(node.putative_products),
                "putative_product_scores": putative_product_scores_text(node),
                "organism": node.organism,
                "fill_color": node.fill_color,
                "border_color": node.border_color,
                "x": f"{x:.3f}",
                "y": f"{y:.3f}",
            }
        )
    return rows


def edge_attribute_rows(edges: list[EdgeRecord]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for edge in edges:
        rows.append(
            {
                "source_bigscape_record": edge.source,
                "target_bigscape_record": edge.target,
                "distance": "" if edge.distance is None else f"{edge.distance:.6g}",
                "similarity": "" if edge.similarity is None else f"{edge.similarity:.6g}",
                "jaccard": edge.jaccard,
                "adjacency": edge.adjacency,
                "dss": edge.dss,
                "weights": edge.weights,
            }
        )
    return rows


def fungal_legend_rows(nodes: dict[str, NodeRecord]) -> list[dict[str, object]]:
    counts: dict[str, int] = defaultdict(int)
    ecology: dict[str, str] = {}
    labels: dict[str, str] = {}
    for node in nodes.values():
        counts[node.sample_id] += 1
        ecology.setdefault(node.sample_id, node.ecology_category)
        labels[node.sample_id] = node.label_number
    return [
        {
            "label_number": labels[sample_id],
            "sample_id": sample_id,
            "ecology_category": ecology[sample_id],
            "node_count": counts[sample_id],
        }
        for sample_id in sorted(counts, key=lambda value: int(labels[value]))
    ]


def convert_svg_with_cairosvg(svg_path: Path, output_path: Path, fmt: str, warnings: list[str]) -> None:
    try:
        import cairosvg  # type: ignore
    except ImportError:
        warnings.append(f"Requested {fmt.upper()} output, but cairosvg is not installed; wrote SVG instead.")
        return
    if fmt == "png":
        cairosvg.svg2png(url=str(svg_path), write_to=str(output_path), dpi=180)
    elif fmt == "pdf":
        cairosvg.svg2pdf(url=str(svg_path), write_to=str(output_path))


def parse_formats(text: str) -> set[str]:
    formats = {part.strip().lower() for part in clean(text).split(",") if part.strip()}
    valid = {"svg", "png", "pdf", "graphml"}
    invalid = formats - valid
    if invalid:
        raise ValueError(f"Unknown output format(s): {', '.join(sorted(invalid))}")
    return formats or {"svg", "graphml"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a clean BiG-SCAPE network figure for ClusterWeave.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--project-name", default="clusterweave")
    parser.add_argument("--bigscape-root", type=Path, default=None, help="BiG-SCAPE root, output_files root, or c-threshold run directory.")
    parser.add_argument("--metadata", type=Path, default=None, help="Optional ecology metadata TSV/CSV.")
    parser.add_argument("--annotation-table", type=Path, default=None, help="Optional ClusterWeave summary table with MiBIG/BGC accession annotations.")
    parser.add_argument("--metadata-id-column", default="", help="Metadata ID column. Defaults to sample_id, fungal_id, genome_id_current, genome, or isolate.")
    parser.add_argument("--ecology-field", default="ecofun_primary", help="Metadata ecology column. Generic ecology_category is also recognized.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Defaults to data/results/<project-name>/figures.")
    parser.add_argument("--prefix", default="bigscape_network")
    parser.add_argument("--category", default="mix", help="BiG-SCAPE category directory to render. Defaults to mix when present.")
    parser.add_argument("--clustering-threshold", default="0.3", help="BiG-SCAPE c-threshold label to select, for example 0.3.")
    parser.add_argument("--distance-threshold", type=float, default=None, help="Optional maximum BiG-SCAPE distance for displayed edges.")
    parser.add_argument("--similarity-threshold", type=float, default=None, help="Optional minimum displayed similarity, computed as 1 - distance.")
    parser.add_argument("--formats", default="svg,graphml", help="Comma-separated outputs: svg,png,pdf,graphml.")
    parser.add_argument("--max-nodes", type=int, default=0, help="Optional readability cap. 0 keeps all nodes.")
    parser.add_argument("--max-components", type=int, default=0, help="Optional readability cap. 0 keeps all components.")
    parser.add_argument("--include-mibig-only", action="store_true", help="Keep MiBIG references even when their family has no dataset records.")
    parser.add_argument("--canvas-width", type=int, default=DEFAULT_CANVAS_WIDTH)
    parser.add_argument("--layout-iterations", type=int, default=80)
    parser.add_argument("--no-warnings-file", action="store_true", help="Do not write the auxiliary warnings text file.")
    parser.add_argument("--no-fungal-id-legend", action="store_true", help="Do not write the auxiliary fungal ID legend TSV.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    results_root = args.project_root / "data" / "results" / args.project_name
    bigscape_root = args.bigscape_root or results_root / "big_scape" / "output_files"
    annotation_table = args.annotation_table
    if annotation_table is None:
        default_annotation_table = results_root / "summary" / "candidate_bgc_gcf_crosswalk.tsv"
        annotation_table = default_annotation_table if default_annotation_table.exists() else None
    metadata_path = args.metadata
    if metadata_path is None:
        default_metadata = results_root / "summary_tables" / "ecofun_metadata_normalized.tsv"
        metadata_path = default_metadata if default_metadata.exists() else None
    output_dir = args.output_dir or results_root / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    formats = parse_formats(args.formats)
    inputs = select_bigscape_inputs(bigscape_root, args.category, args.clustering_threshold)
    annotations = load_annotations(inputs.annotations_path)
    if not annotations:
        warnings.append("record_annotations.tsv was not found; BGC class, organism, and MiBIG context may be incomplete.")

    nodes, node_warnings = load_nodes(inputs.clustering_path, annotations)
    warnings.extend(node_warnings)
    mibig_annotated_records, mibig_annotation_warnings = load_mibig_annotation_records(annotation_table)
    warnings.extend(mibig_annotation_warnings)
    warnings.extend(mark_mibig_annotations(nodes, mibig_annotated_records))
    product_labels, product_warnings = load_product_labels(annotation_table)
    warnings.extend(product_warnings)
    warnings.extend(assign_product_labels(nodes, product_labels))
    edges, edge_warnings = load_edges(inputs.network_path, set(nodes), args.distance_threshold, args.similarity_threshold)
    warnings.extend(edge_warnings)
    nodes, edges, mibig_scope_warnings = filter_dataset_dependent_mibig_references(
        nodes,
        edges,
        include_mibig_only=args.include_mibig_only,
    )
    warnings.extend(mibig_scope_warnings)

    metadata, metadata_warnings, metadata_columns = load_metadata(metadata_path, args.ecology_field, args.metadata_id_column)
    warnings.extend(metadata_warnings)
    if metadata_path is None:
        warnings.append(f"No ecology metadata table was provided or found; all sample ecology borders use '{UNKNOWN}'.")
    elif metadata_columns:
        warnings.append(f"Using metadata columns: id={metadata_columns[0]}, ecology={metadata_columns[1] or UNKNOWN}.")
    warnings.extend(assign_metadata_and_labels(nodes, metadata))
    if not has_ecology_signal(nodes):
        warnings.append("No non-unknown ecology categories found; ecology borders were omitted from the SVG.")

    if not any(node.is_mibig or node.has_mibig_annotation for node in nodes.values()):
        warnings.append("No MiBIG reference or MiBIG-annotated nodes were detected in the selected network.")

    nodes, edges, filter_warnings = filter_graph(nodes, edges, args.max_nodes, args.max_components)
    warnings.extend(filter_warnings)

    layout = build_layout(nodes, edges, args.canvas_width, args.layout_iterations)

    base = output_dir / args.prefix
    svg_path = base.with_suffix(".svg")
    needs_svg = bool(formats & {"svg", "png", "pdf"})
    if needs_svg:
        render_svg(svg_path, nodes, edges, layout, inputs)

    if "graphml" in formats:
        write_graphml(base.with_suffix(".graphml"), nodes, edges, layout.positions)

    if "png" in formats:
        convert_svg_with_cairosvg(svg_path, base.with_suffix(".png"), "png", warnings)
    if "pdf" in formats:
        convert_svg_with_cairosvg(svg_path, base.with_suffix(".pdf"), "pdf", warnings)

    write_tsv(
        output_dir / f"{args.prefix}_node_attributes.tsv",
        [
            "bigscape_record",
            "label_number",
            "sample_id",
            "bigscape_gbk",
            "cc",
            "family",
            "bgc_class",
            "raw_class",
            "category",
            "ecology_category",
            "is_mibig",
            "has_mibig_annotation",
            "putative_products",
            "putative_product_scores",
            "organism",
            "fill_color",
            "border_color",
            "x",
            "y",
        ],
        node_attribute_rows(nodes, layout.positions),
    )
    write_tsv(
        output_dir / f"{args.prefix}_edge_attributes.tsv",
        [
            "source_bigscape_record",
            "target_bigscape_record",
            "distance",
            "similarity",
            "jaccard",
            "adjacency",
            "dss",
            "weights",
        ],
        edge_attribute_rows(edges),
    )
    if not args.no_fungal_id_legend:
        write_tsv(
            output_dir / f"{args.prefix}_fungal_id_legend.tsv",
            ["label_number", "sample_id", "ecology_category", "node_count"],
            fungal_legend_rows(nodes),
        )

    warning_path = output_dir / f"{args.prefix}_warnings.txt"
    unique_warnings = list(dict.fromkeys(warnings))
    if not args.no_warnings_file:
        warning_path.write_text("\n".join(unique_warnings) + ("\n" if unique_warnings else ""), encoding="utf-8")

    if needs_svg:
        print(f"Wrote BiG-SCAPE network SVG: {svg_path}")
    if "graphml" in formats:
        print(f"Wrote Cytoscape GraphML: {base.with_suffix('.graphml')}")
    if unique_warnings and not args.no_warnings_file:
        print(f"Wrote warnings: {warning_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
