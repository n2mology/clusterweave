#!/usr/bin/env python3
"""Render the core taxonomy/BGC/GCF context tree and lossless bundle.

This renderer intentionally performs no sequence inference.  Its topology is
assembled only from saved taxonomy lineage fields; unresolved declarations are
shown as polytomies.  MAFFT, IQ-TREE, ETE, and marker databases are not needed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from itertools import combinations
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape, quoteattr

import render_bigscape_network as bigscape_network


RENDERER_VERSION = "3.1.0"
DEFAULT_GCF_CATEGORY = "mix"
DEFAULT_GCF_THRESHOLD = "0.3"
ONTOLOGY_VERSION = "clusterweave-bgc-broad-v1"
DOMAIN_ORDER = {"fungi": 0, "bacteria": 1}
BGC_ORDER = ["NRPS", "PKS", "terpene", "RiPP", "hybrid", "other"]
BGC_COLORS = {
    category: bigscape_network.CLASS_COLORS[category] for category in BGC_ORDER
}
INK = "#222222"
MUTED = "#444444"
TREE = "#8B8B8B"
TREE_NODE = "#333333"
GRID = "#E5E5E5"
SEPARATOR = "#B8B8B8"
BOUNDARY = "#DADADA"
UPPER_TRIANGLE = "#F6F6F6"
PRIVATE = "#DADADA"
WITHIN = "#1F77B4"
CROSS = "#444444"
TREE_FILENAMES = {
    "svg": "clusterweave_taxon_tree.svg",
    "png": "clusterweave_taxon_tree.png",
    "newick": "clusterweave_taxon_tree.nwk",
    "profiles": "clusterweave_taxon_tree_leaf_profiles.tsv",
    "edges": "clusterweave_gcf_network_edges.tsv",
    "graphml": "clusterweave_taxon_tree.graphml",
    "manifest": "clusterweave_tree_manifest.json",
    "methods": "clusterweave_tree_methods.json",
    "bundle": "clusterweave_tree_bundle.zip",
}
MAX_SVG_LEAF_LABEL_CHARS = 48


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def read_rows(path: Path | None, delimiter: str = "\t") -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def split_values(value: object) -> list[str]:
    text = clean(value)
    if not text:
        return []
    for delimiter in ("|", ";", ","):
        if delimiter in text:
            return [part.strip() for part in text.split(delimiter) if part.strip()]
    return [text]


def split_gcf_ids(value: object) -> set[str]:
    return {part.strip() for part in clean(value).split(";") if part.strip()}


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


def split_gcf_memberships(value: object) -> set[tuple[str, str, str]]:
    """Parse category/threshold/family membership tokens from the crosswalk."""
    memberships: set[tuple[str, str, str]] = set()
    for token in clean(value).split(";"):
        if "=" not in token:
            continue
        view, family = token.split("=", 1)
        if "@c" not in view or not family.strip():
            continue
        category, threshold = view.rsplit("@c", 1)
        memberships.add(
            (
                canonical_gcf_category(category),
                canonical_gcf_threshold(threshold),
                family.strip(),
            )
        )
    return memberships


def selected_gcf_ids(
    row: dict[str, str], category: str, threshold: str
) -> set[str]:
    """Return only the requested BiG-SCAPE view, with legacy fallback."""
    wanted = (
        canonical_gcf_category(category),
        canonical_gcf_threshold(threshold),
    )
    has_selected_schema = all(
        key in row
        for key in (
            "gcf_selected_category",
            "gcf_selected_threshold",
            "gcf_selected_id",
        )
    )
    if has_selected_schema:
        declared = (
            canonical_gcf_category(row.get("gcf_selected_category")),
            canonical_gcf_threshold(row.get("gcf_selected_threshold")),
        )
        if declared == wanted:
            return split_gcf_ids(row.get("gcf_selected_id"))
    if "gcf_memberships" in row:
        return {
            family
            for member_category, member_threshold, family
            in split_gcf_memberships(row.get("gcf_memberships"))
            if (member_category, member_threshold) == wanted
        }
    if has_selected_schema:
        return set()
    return split_gcf_ids(row.get("gcf_id"))


def normalized_taxon(value: object) -> str:
    taxon = clean(value).lower()
    return taxon if taxon in DOMAIN_ORDER else "fungi"


def broad_class(value: object) -> str:
    token = clean(value).lower()
    hits: list[str] = []
    if "nrps" in token or "nrp" in token:
        hits.append("NRPS")
    if "pks" in token or "polyketide" in token:
        hits.append("PKS")
    if "terpene" in token:
        hits.append("terpene")
    if "ripp" in token or "lanthi" in token or "lasso" in token:
        hits.append("RiPP")
    if len(set(hits)) > 1 or "hybrid" in token:
        return "hybrid"
    return hits[0] if hits else "other"


def safe_genome_id(row: dict[str, str]) -> str:
    return clean(row.get("genome_id")) or clean(row.get("genome")) or clean(row.get("input_key"))


def profile_genome_id(
    row: dict[str, str], known_genome_ids: set[str]
) -> str:
    """Resolve exact IDs first, with read compatibility for pre-v1.0 jobs."""
    genome_id = safe_genome_id(row)
    if genome_id in known_genome_ids:
        return genome_id
    if (
        normalized_taxon(row.get("taxon_group")) == "bacteria"
        and genome_id
        and not genome_id.casefold().startswith("bacteria_")
    ):
        canonical = f"bacteria_{genome_id}"
        if canonical in known_genome_ids:
            return canonical
    return genome_id


def taxonomy_lineage(row: dict[str, str]) -> tuple[str, ...]:
    explicit = split_values(row.get("lineage_names") or row.get("lineage"))
    if explicit:
        return tuple(dict.fromkeys(explicit))
    ranked = [
        clean(row.get(rank))
        for rank in ("domain", "kingdom", "phylum", "class", "order", "family", "genus", "species")
    ]
    return tuple(value for value in ranked if value)


def taxonomy_lineage_ids(
    row: dict[str, str], names: tuple[str, ...]
) -> tuple[str, ...]:
    ids = tuple(split_values(row.get("lineage_ids")))
    return ids if len(ids) == len(names) else tuple("" for _ in names)


def combined_broad_class(values: Iterable[str]) -> str:
    classes = {broad_class(value) for value in values if clean(value)}
    informative = classes - {"other"}
    if "hybrid" in informative or len(informative) > 1:
        return "hybrid"
    if informative:
        return next(category for category in BGC_ORDER if category in informative)
    return "other"


def dominant_gcf_class(counts: Counter[str]) -> str:
    if not counts:
        return "other"
    return min(
        BGC_ORDER,
        key=lambda category: (-counts.get(category, 0), BGC_ORDER.index(category)),
    )


def safe_label(row: dict[str, str], genome_id: str) -> str:
    """Build a concise visible label without repeating the internal genome ID."""

    organism = re.sub(r"\s+", " ", clean(row.get("organism_name"))).strip()
    genome_label = re.sub(r"[_\s]+", " ", genome_id).strip()
    if (
        normalized_taxon(row.get("taxon_group")) == "bacteria"
        and clean(row.get("taxon_source")).casefold() == "ncbi"
        and genome_label.casefold().startswith("bacteria ")
    ):
        genome_label = genome_label.split(" ", 1)[1].strip()
    if not organism:
        return genome_label or genome_id
    if organism.casefold() == genome_label.casefold():
        return organism

    organism_words = organism.split()
    genome_words = genome_label.split()
    if (
        len(genome_words) > len(organism_words)
        and [word.casefold() for word in genome_words[: len(organism_words)]]
        == [word.casefold() for word in organism_words]
    ):
        suffix = " ".join(genome_words[len(organism_words) :]).strip()
        if suffix and suffix.casefold() not in organism.casefold():
            return f"{organism} {suffix}"
    return organism


@dataclass
class Leaf:
    genome_id: str
    taxon_group: str
    taxon_source: str
    taxid: str
    organism_name: str
    display_label: str
    lineage: tuple[str, ...]
    lineage_ids: tuple[str, ...]
    unresolved: bool
    prediction_method: str
    detector_profile: str
    bgc_counts: Counter[str] = field(default_factory=Counter)
    gcf_ids: set[str] = field(default_factory=set)
    gcf_unassigned_rows: int = 0
    gcf_not_applicable_rows: int = 0
    gcf_counts: Counter[str] = field(default_factory=Counter)
    y: float = 0.0


@dataclass
class TreeNode:
    name: str
    depth: int
    leaf_id: str = ""
    taxid: str = ""
    children: dict[str, "TreeNode"] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0


def load_leaves(manifest: Path, taxonomy: Path | None) -> list[Leaf]:
    manifest_rows = read_rows(manifest)
    taxonomy_by_id = {safe_genome_id(row): row for row in read_rows(taxonomy) if safe_genome_id(row)}
    leaves: list[Leaf] = []
    seen: set[str] = set()
    for route in manifest_rows:
        genome_id = safe_genome_id(route)
        if not genome_id or genome_id in seen:
            continue
        seen.add(genome_id)
        merged = dict(route)
        merged.update({key: value for key, value in taxonomy_by_id.get(genome_id, {}).items() if clean(value)})
        lineage = taxonomy_lineage(merged)
        lineage_ids = taxonomy_lineage_ids(merged, lineage)
        source = clean(merged.get("taxon_source")) or "legacy_default"
        unresolved = not lineage
        leaves.append(
            Leaf(
                genome_id=genome_id,
                taxon_group=normalized_taxon(merged.get("taxon_group")),
                taxon_source=source,
                taxid=clean(merged.get("taxid") or merged.get("tax_id")),
                organism_name=clean(merged.get("organism_name")),
                display_label=safe_label(merged, genome_id),
                lineage=lineage,
                lineage_ids=lineage_ids,
                unresolved=unresolved,
                prediction_method=clean(merged.get("prediction_method")),
                detector_profile=clean(merged.get("detector_profile")),
            )
        )
    leaves.sort(
        key=lambda leaf: (
            DOMAIN_ORDER[leaf.taxon_group],
            tuple(value.casefold() for value in leaf.lineage),
            leaf.genome_id.casefold(),
        )
    )
    if not leaves:
        raise ValueError(f"No routed genomes found in canonical manifest: {manifest}")
    return leaves


def add_profiles(
    leaves: list[Leaf],
    exact_products: Path | None,
    crosswalk: Path | None,
    gcf_category: str = DEFAULT_GCF_CATEGORY,
    gcf_threshold: str = DEFAULT_GCF_THRESHOLD,
) -> tuple[dict[str, set[str]], list[dict[str, object]]]:
    by_id = {leaf.genome_id: leaf for leaf in leaves}
    known_genome_ids = set(by_id)
    raw_classes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in read_rows(exact_products):
        genome = profile_genome_id(row, known_genome_ids)
        bgc_id = clean(row.get("bgc_id"))
        if genome not in by_id or not bgc_id:
            continue
        raw_classes[(genome, bgc_id)].add(
            clean(row.get("broad_display_class") or row.get("exact_product_type"))
        )
    bgc_classes = {
        key: combined_broad_class(values) for key, values in raw_classes.items()
    }
    for (genome, _), category in bgc_classes.items():
        by_id[genome].bgc_counts[category] += 1

    family_genomes: dict[str, set[str]] = defaultdict(set)
    family_classes: dict[str, Counter[str]] = defaultdict(Counter)
    for row in read_rows(crosswalk):
        genome = profile_genome_id(row, known_genome_ids)
        if genome not in by_id:
            continue
        families = selected_gcf_ids(row, gcf_category, gcf_threshold)
        if not families:
            status = clean(row.get("gcf_selected_status")).casefold()
            if status == "not_applicable_detector_only":
                by_id[genome].gcf_not_applicable_rows += 1
            else:
                by_id[genome].gcf_unassigned_rows += 1
        by_id[genome].gcf_ids.update(families)
        region = clean(row.get("antismash_region") or row.get("bgc_id"))
        category = bgc_classes.get((genome, region)) or broad_class(
            row.get("antismash_class")
        )
        for family in families:
            family_genomes[family].add(genome)
            family_classes[family][category] += 1

    family_class = {
        family: dominant_gcf_class(counts)
        for family, counts in family_classes.items()
    }

    for leaf in leaves:
        for family in sorted(leaf.gcf_ids):
            members = family_genomes[family]
            taxa = {by_id[genome].taxon_group for genome in members}
            if len(taxa) > 1:
                category = "shared_across_taxon"
            elif len(members) > 1:
                category = "shared_within_taxon"
            else:
                category = "private_singleton"
            leaf.gcf_counts[category] += 1

    edges: list[dict[str, object]] = []
    for left, right in combinations(leaves, 2):
        shared = sorted(left.gcf_ids.intersection(right.gcf_ids))
        if not shared:
            continue
        class_counts = Counter(family_class.get(family, "other") for family in shared)
        edges.append(
            {
                "source": left.genome_id,
                "target": right.genome_id,
                "source_taxon": left.taxon_group,
                "target_taxon": right.taxon_group,
                "cross_taxon": "yes" if left.taxon_group != right.taxon_group else "no",
                "shared_gcf_count": len(shared),
                "gcf_category": canonical_gcf_category(gcf_category),
                "gcf_threshold": canonical_gcf_threshold(gcf_threshold),
                "shared_gcf_ids": ";".join(shared),
                "shared_gcf_classes": ";".join(
                    f'{family}={family_class.get(family, "other")}'
                    for family in shared
                ),
                "gcf_class_counts": ";".join(
                    f"{category}:{class_counts[category]}"
                    for category in BGC_ORDER
                    if class_counts[category]
                ),
            }
        )
    edges.sort(key=lambda row: (-int(row["shared_gcf_count"]), str(row["source"]), str(row["target"])))
    return family_genomes, edges


def build_tree(leaves: list[Leaf]) -> TreeNode:
    root = TreeNode("ClusterWeave taxonomy panels", 0)
    for leaf in leaves:
        panel_label = (
            "Fungal genomes" if leaf.taxon_group == "fungi" else "Bacterial genomes"
        )
        domain = root.children.setdefault(
            f"domain:{leaf.taxon_group}", TreeNode(panel_label, 1)
        )
        node = domain
        for depth, lineage_name in enumerate(leaf.lineage, start=2):
            index = depth - 2
            taxid = leaf.lineage_ids[index] if index < len(leaf.lineage_ids) else ""
            key = f"taxid:{taxid}" if taxid else f"taxon:{lineage_name.casefold()}"
            node = node.children.setdefault(
                key, TreeNode(lineage_name, depth, taxid=taxid)
            )
        leaf_key = f"leaf:{leaf.genome_id}"
        node.children[leaf_key] = TreeNode(
            leaf.genome_id,
            node.depth + 1,
            leaf_id=leaf.genome_id,
            taxid=leaf.taxid,
        )
    return root


def all_nodes(root: TreeNode) -> Iterable[TreeNode]:
    yield root
    for key in sorted(root.children):
        yield from all_nodes(root.children[key])


def newick_name(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def to_newick(node: TreeNode) -> str:
    label = node.leaf_id or node.name
    if node.children:
        children = ",".join(to_newick(node.children[key]) for key in sorted(node.children))
        return f"({children}){newick_name(label)}"
    return newick_name(label)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def graphml_text(
    leaves: list[Leaf],
    edges: list[dict[str, object]],
    gcf_category: str = DEFAULT_GCF_CATEGORY,
    gcf_threshold: str = DEFAULT_GCF_THRESHOLD,
) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '<key id="selected_category" for="graph" attr.name="gcf_selected_category" attr.type="string"/>',
        '<key id="selected_threshold" for="graph" attr.name="gcf_selected_threshold" attr.type="string"/>',
        '<key id="taxon" for="node" attr.name="taxon_group" attr.type="string"/>',
        '<key id="organism" for="node" attr.name="organism_name" attr.type="string"/>',
        '<key id="taxid" for="node" attr.name="ncbi_taxid" attr.type="string"/>',
        '<key id="lineage" for="node" attr.name="ncbi_lineage" attr.type="string"/>',
        '<key id="bgc_total" for="node" attr.name="bgc_total" attr.type="int"/>',
        '<key id="gcf_total" for="node" attr.name="gcf_total" attr.type="int"/>',
        '<key id="gcf_unassigned" for="node" attr.name="gcf_unassigned_rows" attr.type="int"/>',
        '<key id="gcf_not_applicable" for="node" attr.name="gcf_not_applicable_rows" attr.type="int"/>',
        '<key id="edge_category" for="edge" attr.name="gcf_category" attr.type="string"/>',
        '<key id="edge_threshold" for="edge" attr.name="gcf_threshold" attr.type="string"/>',
        '<key id="shared_count" for="edge" attr.name="shared_gcf_count" attr.type="int"/>',
        '<key id="shared_ids" for="edge" attr.name="shared_gcf_ids" attr.type="string"/>',
        '<key id="shared_classes" for="edge" attr.name="shared_gcf_classes" attr.type="string"/>',
        '<key id="class_counts" for="edge" attr.name="gcf_class_counts" attr.type="string"/>',
        '<key id="cross_taxon" for="edge" attr.name="cross_taxon" attr.type="boolean"/>',
        '<key id="visible" for="edge" attr.name="visible_in_svg" attr.type="boolean"/>',
        '<graph id="clusterweave_taxon_gcf_context" edgedefault="undirected">',
        f'<data key="selected_category">{escape(canonical_gcf_category(gcf_category))}</data>',
        f'<data key="selected_threshold">{escape(canonical_gcf_threshold(gcf_threshold))}</data>',
    ]
    for leaf in leaves:
        lines.extend(
            [
                f'<node id={quoteattr(leaf.genome_id)}>',
                f'<data key="taxon">{escape(leaf.taxon_group)}</data>',
                f'<data key="organism">{escape(leaf.organism_name)}</data>',
                f'<data key="taxid">{escape(leaf.taxid)}</data>',
                f'<data key="lineage">{escape("|".join(leaf.lineage))}</data>',
                f'<data key="bgc_total">{sum(leaf.bgc_counts.values())}</data>',
                f'<data key="gcf_total">{sum(leaf.gcf_counts.values())}</data>',
                f'<data key="gcf_unassigned">{leaf.gcf_unassigned_rows}</data>',
                f'<data key="gcf_not_applicable">{leaf.gcf_not_applicable_rows}</data>',
                '</node>',
            ]
        )
    for index, edge in enumerate(edges, start=1):
        lines.extend(
            [
                f'<edge id="e{index}" source={quoteattr(str(edge["source"]))} target={quoteattr(str(edge["target"]))}>',
                f'<data key="edge_category">{escape(str(edge.get("gcf_category", canonical_gcf_category(gcf_category))))}</data>',
                f'<data key="edge_threshold">{escape(str(edge.get("gcf_threshold", canonical_gcf_threshold(gcf_threshold))))}</data>',
                f'<data key="shared_count">{int(edge["shared_gcf_count"])}</data>',
                f'<data key="shared_ids">{escape(str(edge["shared_gcf_ids"]))}</data>',
                f'<data key="shared_classes">{escape(str(edge.get("shared_gcf_classes", "")))}</data>',
                f'<data key="class_counts">{escape(str(edge.get("gcf_class_counts", "")))}</data>',
                f'<data key="cross_taxon">{str(edge["cross_taxon"] == "yes").lower()}</data>',
                f'<data key="visible">{str(bool(edge.get("visible_in_svg"))).lower()}</data>',
                '</edge>',
            ]
        )
    lines.extend(['</graph>', '</graphml>'])
    return "\n".join(lines) + "\n"


def svg_text(x: float, y: float, value: str, size: int = 14, *, weight: int = 400,
             anchor: str = "start", fill: str = "#18241e", extra: str = "") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial, Helvetica, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="{fill}"{extra}>'
        f'{escape(value)}</text>'
    )


def bounded_svg_leaf_label(leaf: Leaf, display_label: str | None = None) -> str:
    suffix = " *" if leaf.unresolved else ""
    limit = max(1, MAX_SVG_LEAF_LABEL_CHARS - len(suffix))
    visible = display_label if display_label is not None else leaf.display_label
    if len(visible) > limit:
        visible = visible[: max(1, limit - 1)].rstrip() + "…"
    return visible + suffix


def select_visible_edges(
    edges: list[dict[str, object]], max_visible_arcs: int
) -> list[dict[str, object]]:
    """Select strongest edges while reserving a mixed-job cross-taxon lane."""

    limit = max(0, max_visible_arcs)
    if limit == 0:
        return []
    cross_taxon = [edge for edge in edges if edge.get("cross_taxon") == "yes"]
    if not cross_taxon:
        return edges[:limit]

    reserved_count = min(len(cross_taxon), max(1, limit // 4))
    selected_ids = {id(edge) for edge in cross_taxon[:reserved_count]}
    for edge in edges:
        if len(selected_ids) >= limit:
            break
        selected_ids.add(id(edge))
    return [edge for edge in edges if id(edge) in selected_ids][:limit]


def parsed_class_counts(edge: dict[str, object]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for token in clean(edge.get("gcf_class_counts")).split(";"):
        if ":" not in token:
            continue
        category, value = token.rsplit(":", 1)
        try:
            counts[category] += max(0, int(value))
        except ValueError:
            continue
    if not counts:
        counts["other"] = int(edge.get("shared_gcf_count") or 0)
    return counts


def compact_display(value: str) -> str:
    """Apply the approved figure's bounded display-name compaction."""

    replacements = {
        "Streptomyces avermitilis MA-4680 = NBRC 14893": "Streptomyces avermitilis MA-4680",
        "Streptomyces griseus subsp. griseus NBRC 13350": "Streptomyces griseus NBRC 13350",
        "Bacillus subtilis subsp. subtilis str. 168": "Bacillus subtilis 168",
        "Fusobacterium nucleatum subsp. nucleatum ATCC 25586": "Fusobacterium nucleatum ATCC 25586",
        "Escherichia coli str. K-12 substr. MG1655": "Escherichia coli K-12 MG1655",
        "Treponema pallidum subsp. pallidum str. Nichols": "Treponema pallidum Nichols",
        "Deinococcus radiodurans R1 = ATCC 13939 = DSM 20539": "Deinococcus radiodurans R1 / ATCC 13939",
    }
    return replacements.get(value, value)


def short_name(value: str) -> str:
    compact = compact_display(value)
    tokens = compact.split()
    if len(tokens) < 2:
        return compact
    label = f"{tokens[0][0]}. {tokens[1]}"
    if len(tokens) > 2:
        tail = tokens[-1]
        if len(tail) <= 10 and any(character.isdigit() for character in tail):
            label += f" {tail}"
    return label


def split_species_label(value: str) -> tuple[str, str]:
    tokens = value.split()
    if len(tokens) < 2:
        return value, ""
    return " ".join(tokens[:2]), " ".join(tokens[2:])


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    token = value.lstrip("#")
    return tuple(int(token[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def interpolate_color(low: str, high: str, fraction: float) -> str:
    fraction = max(0.0, min(1.0, fraction))
    start = hex_to_rgb(low)
    end = hex_to_rgb(high)
    channels = (
        max(0, min(255, round(start[index] + (end[index] - start[index]) * fraction)))
        for index in range(3)
    )
    return "#" + "".join(f"{channel:02X}" for channel in channels)


def nice_ceiling(value: int) -> int:
    if value <= 0:
        return 1
    exponent = 10 ** math.floor(math.log10(value))
    for multiplier in (1, 2, 2.5, 5, 10):
        candidate = multiplier * exponent
        if candidate >= value:
            return int(candidate)
    return int(10 * exponent)


def layout_ranked_tree(
    root: TreeNode,
    leaves: list[Leaf],
    row_positions: dict[str, float],
) -> dict[int, int]:
    """Place the saved lineage trie on the approved D/K/P/C/O/F/G/S grid."""

    leaf_by_id = {leaf.genome_id: leaf for leaf in leaves}
    descendant_counts: dict[int, int] = {}

    def place(node: TreeNode) -> tuple[float, int]:
        if node.leaf_id:
            node.x = 465.0
            node.y = row_positions[node.leaf_id]
            leaf_by_id[node.leaf_id].y = node.y
            descendant_counts[id(node)] = 1
            return node.y, 1
        if node.depth <= 1:
            node.x = 105.0
        else:
            node.x = 105.0 + min(7, node.depth - 2) * 45.0
        placed = [place(node.children[key]) for key in sorted(node.children)]
        ys = [y for y, count in placed if count]
        node.y = (min(ys) + max(ys)) / 2.0 if ys else 0.0
        count = sum(count for _, count in placed)
        descendant_counts[id(node)] = count
        return node.y, count

    place(root)
    return descendant_counts


def render_svg(
    root: TreeNode,
    leaves: list[Leaf],
    edges: list[dict[str, object]],
    max_visible_arcs: int,
    gcf_category: str = DEFAULT_GCF_CATEGORY,
    gcf_threshold: str = DEFAULT_GCF_THRESHOLD,
) -> str:
    width = 2200
    panel_b_x, panel_b_w = 1328.0, 842.0
    domain_order = [
        domain
        for domain in ("fungi", "bacteria")
        if any(leaf.taxon_group == domain for leaf in leaves)
    ]
    grouped = {
        domain: [leaf for leaf in leaves if leaf.taxon_group == domain]
        for domain in domain_order
    }

    row_step = 25.8 if len(leaves) >= 35 else 30.0
    content_top = 116.0
    group_gap = 12.0
    group_layout: dict[str, dict[str, float]] = {}
    row_positions: dict[str, float] = {}
    cursor_y = content_top
    index_by_id: dict[str, int] = {}
    for index, leaf in enumerate(leaves, start=1):
        index_by_id[leaf.genome_id] = index
    for domain in domain_order:
        members = grouped[domain]
        group_top = cursor_y
        rows_start = group_top + 32.0
        for offset, leaf in enumerate(members):
            row_positions[leaf.genome_id] = rows_start + offset * row_step
        last_y = row_positions[members[-1].genome_id]
        group_bottom = last_y + 14.0
        group_layout[domain] = {
            "top": group_top,
            "bottom": group_bottom,
            "rows_start": rows_start,
        }
        cursor_y = group_bottom + group_gap
    panel_a_content_bottom = cursor_y + 2.0
    descendant_counts = layout_ranked_tree(root, leaves, row_positions)

    visible = select_visible_edges(edges, max_visible_arcs)
    selected_ids = {id(edge) for edge in visible}
    for edge in edges:
        edge["visible_in_svg"] = id(edge) in selected_ids

    by_id = {leaf.genome_id: leaf for leaf in leaves}
    pairs: list[dict[str, object]] = []
    for edge in visible:
        left = by_id[str(edge["source"])]
        right = by_id[str(edge["target"])]
        if right.genome_id < left.genome_id:
            left, right = right, left
        shared = int(edge["shared_gcf_count"])
        denominator = len(left.gcf_ids) + len(right.gcf_ids) - shared
        pairs.append(
            {
                "left": left,
                "right": right,
                "shared": shared,
                "jaccard": shared / denominator if denominator > 0 else 0.0,
                "classes": parsed_class_counts(edge),
            }
        )
    pairs.sort(
        key=lambda pair: (
            -float(pair["jaccard"]),
            -int(pair["shared"]),
            pair["left"].genome_id,  # type: ignore[union-attr]
            pair["right"].genome_id,  # type: ignore[union-attr]
        )
    )

    n_genomes = len(leaves)
    cell = min(24.0, 600.0 / max(1, n_genomes))
    matrix_size = cell * n_genomes
    matrix_y = 158.0
    matrix_x = panel_b_x + 25.0 + (panel_b_w - 50.0 - matrix_size) / 2.0
    matrix_bottom = matrix_y + matrix_size
    table_pairs = pairs[:10]
    table_y = matrix_bottom + 48.0
    table_bottom = table_y + 80.0 + max(1, len(table_pairs)) * 28.0
    panel_bottom = max(panel_a_content_bottom, table_bottom) + 8.0
    footer_y = panel_bottom + 16.0
    footer_h = 58.0
    height = int(math.ceil(footer_y + footer_h + 16.0))
    height_mm = 300.0 * height / width

    bgc_x, bgc_w = 875.0, 230.0
    gcf_x, gcf_w = 1148.0, 92.0
    bgc_axis_max = nice_ceiling(
        max((sum(leaf.bgc_counts.values()) for leaf in leaves), default=1)
    )
    max_jaccard = max((float(pair["jaccard"]) for pair in pairs), default=0.0)
    legend_max = max(0.05, math.ceil(max_jaccard * 20.0) / 20.0)
    display_mode = "mixed" if len(domain_order) > 1 else domain_order[0]
    mode_label = {
        "mixed": "Mixed input",
        "fungi": "Fungal input",
        "bacteria": "Bacterial input",
    }[display_mode]
    context_text = f"{mode_label} · {len(leaves)} genomes"

    lines: list[str] = []
    add = lines.append
    add(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="300mm" height="{height_mm:.2f}mm" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">'
    )
    add('<title id="title">ClusterWeave BGC and GCF context</title>')
    add(
        '<desc id="desc">Compact rank-aligned taxonomy with absolute BGC bars, '
        'proportional GCF status bars, a lower-triangular Jaccard matrix, and a '
        'ranked link table with fixed-width class-composition bars. The layout adapts '
        'to mixed, fungal-only, or bacterial-only inputs.</desc>'
    )
    add('<defs>')
    add(
        '<linearGradient id="jaccardGradient" x1="0%" y1="0%" x2="100%" y2="0%">'
        '<stop offset="0%" stop-color="#F2F2F2"/><stop offset="50%" stop-color="#A8BFFF"/>'
        '<stop offset="100%" stop-color="#1F77B4"/></linearGradient>'
    )
    add(
        '<pattern id="crossHatch" patternUnits="userSpaceOnUse" width="7" height="7" patternTransform="rotate(45)">'
        '<rect width="7" height="7" fill="#FFFFFF"/>'
        f'<line x1="0" y1="0" x2="0" y2="7" stroke="{CROSS}" stroke-width="1.4"/>'
        '</pattern>'
    )
    add('</defs>')
    add(
        '<style>'
        '.taxonomy-edge{fill:none;stroke:#8B8B8B;stroke-width:1.0;}'
        '.taxonomy-rank-label{font-family:Arial,Helvetica,sans-serif;font-size:11.4px;font-weight:700;fill:#444444;paint-order:stroke;stroke:#FFFFFF;stroke-width:2.5px;stroke-linejoin:round;}'
        '.row-guide{stroke:#B8B8B8;stroke-width:.65;stroke-dasharray:2 3;}'
        '.matrix-grid{stroke:#E5E5E5;stroke-width:.8;}'
        '</style>'
    )
    add(f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>')

    add(svg_text(36, 42, "A", 24, weight=700, fill=INK))
    add(svg_text(80, 42, "Taxonomy + genome profiles", 20, weight=700, fill=INK))
    add(svg_text(panel_b_x + 10, 42, "B", 24, weight=700, fill=INK))
    add(svg_text(panel_b_x + 54, 42, "Pairwise GCF sharing", 20, weight=700, fill=INK))
    add(svg_text(width - 40, 42, context_text, 13, fill=MUTED, anchor="end"))
    add(
        f'<line x1="{panel_b_x - 14:.2f}" y1="68" x2="{panel_b_x - 14:.2f}" '
        f'y2="{panel_bottom:.2f}" stroke="#DDDDDD" stroke-width="1"/>'
    )

    add('<g id="panel-a" aria-label="Taxonomy and genome profiles">')
    add(svg_text(58, 74, "Taxonomy", 15, weight=700, fill=INK))
    add(svg_text(505, 74, "Genome", 15, weight=700, fill=INK))
    add(svg_text(bgc_x, 74, "BGCs", 15, weight=700, fill=INK))
    add(
        f'<text x="{gcf_x + gcf_w / 2.0:.2f}" y="74" '
        'font-family="Arial, Helvetica, sans-serif" font-size="13" '
        f'font-weight="700" fill="{INK}" text-anchor="middle">'
        '<title>Per genome: unique GCFs also found in at least one other submitted genome, divided by all unique GCFs assigned to that genome.</title>'
        'Shared · % of genome GCFs.</text>'
    )

    rank_abbrev = [
        ("D", "Domain"),
        ("K", "Kingdom or clade"),
        ("P", "Phylum"),
        ("C", "Class"),
        ("O", "Order"),
        ("F", "Family"),
        ("G", "Genus"),
        ("S", "Species"),
    ]
    rank_x = [105.0 + index * 45.0 for index in range(8)]
    for x, (short, full) in zip(rank_x, rank_abbrev):
        add(
            f'<text x="{x:.2f}" y="106" font-family="Arial, Helvetica, sans-serif" '
            f'font-size="11" font-weight="700" fill="{MUTED}" text-anchor="middle">'
            f'<title>{escape(full)}</title>{short}</text>'
        )
        add(
            f'<line x1="{x:.2f}" y1="112" x2="{x:.2f}" y2="{panel_bottom:.2f}" '
            f'stroke="{GRID}" stroke-width="0.8"/>'
        )

    for tick in (0, bgc_axis_max / 2.0, bgc_axis_max):
        x = bgc_x + bgc_w * tick / bgc_axis_max
        add(
            f'<line x1="{x:.2f}" y1="112" x2="{x:.2f}" y2="{panel_bottom:.2f}" '
            f'stroke="{GRID}" stroke-width="0.8"/>'
        )
        label = str(int(tick)) if float(tick).is_integer() else f"{tick:g}"
        add(svg_text(x, 106, label, 11, weight=700, fill=MUTED, anchor="middle"))
    add(svg_text(gcf_x, 106, "0", 11, weight=700, fill=MUTED, anchor="middle"))
    add(svg_text(gcf_x + gcf_w, 106, "100%", 11, weight=700, fill=MUTED, anchor="middle"))

    domain_meta = {"fungi": "Fungi", "bacteria": "Bacteria"}
    for domain in domain_order:
        members = grouped[domain]
        top = group_layout[domain]["top"]
        first = index_by_id[members[0].genome_id]
        last = index_by_id[members[-1].genome_id]
        add(svg_text(58, top + 16.0, f"{domain_meta[domain]} · {first:02d}-{last:02d}", 13, weight=700, fill=INK))
        add(
            f'<line x1="170" y1="{top + 11.0:.2f}" x2="1295" y2="{top + 11.0:.2f}" '
            f'stroke="{SEPARATOR}" stroke-width="0.8" stroke-dasharray="2 3"/>'
        )

    for leaf in leaves:
        y = row_positions[leaf.genome_id]
        add(
            f'<line class="row-guide" x1="466" y1="{y + row_step / 2.0:.2f}" '
            f'x2="1295" y2="{y + row_step / 2.0:.2f}"/>'
        )

    add('<g id="taxonomy-tree" aria-label="Rank-aligned NCBI taxonomy">')
    for domain_node in root.children.values():
        title = domain_node.name + (
            f" — NCBI taxid {domain_node.taxid}" if domain_node.taxid else ""
        )
        add(
            f'<path class="taxonomy-edge" d="M 60.00 {domain_node.y:.2f} '
            f'H 105.00 V {domain_node.y:.2f}"><title>{escape(title)}</title></path>'
        )
    for parent in all_nodes(root):
        if parent.depth <= 1:
            continue
        for key in sorted(parent.children):
            child = parent.children[key]
            title = child.name + (
                f" — NCBI taxid {child.taxid}" if child.taxid else ""
            )
            add(
                f'<path class="taxonomy-edge" d="M {parent.x:.2f} {parent.y:.2f} '
                f'H {child.x:.2f} V {child.y:.2f}"><title>{escape(title)}</title></path>'
            )
    for domain_node in root.children.values():
        for child in domain_node.children.values():
            if child.leaf_id:
                add(
                    f'<path class="taxonomy-edge" d="M 105.00 {child.y:.2f} H 465.00">'
                    f'<title>{escape(child.name)} — unresolved taxonomy</title></path>'
                )
    for node in all_nodes(root):
        if node.depth < 2 or node.leaf_id:
            continue
        title = node.name + (f" — NCBI taxid {node.taxid}" if node.taxid else "")
        add(
            f'<circle class="taxonomy-node" cx="{node.x:.2f}" cy="{node.y:.2f}" r="2.1" '
            f'fill="{TREE_NODE}"><title>{escape(title)}</title></circle>'
        )
    for node in all_nodes(root):
        if node.depth < 2 or node.leaf_id:
            continue
        title = node.name + (f" — NCBI taxid {node.taxid}" if node.taxid else "")
        rank_index = min(7, node.depth - 2)
        count = descendant_counts.get(id(node), 0)
        if rank_index == 2 or (rank_index == 6 and count >= 2):
            add(
                f'<text class="taxonomy-rank-label" x="{node.x + 4:.2f}" y="{node.y - 4.5:.2f}">'
                f'<title>{escape(title)}; {count} selected genome(s)</title>'
                f'{escape(node.name)}</text>'
            )
    add('</g>')

    add('<g id="genome-profiles">')
    for leaf in leaves:
        y = row_positions[leaf.genome_id]
        visible = bounded_svg_leaf_label(leaf, compact_display(leaf.display_label))
        scientific, suffix = split_species_label(visible)
        font_size = 14.0 if len(visible) <= 42 else 13.2
        resolution = "unresolved taxonomy" if leaf.unresolved else "saved taxonomy lineage"
        add(f'<circle cx="465" cy="{y:.2f}" r="2.5" fill="{TREE_NODE}"/>')
        add(
            f'<circle cx="487.5" cy="{y:.2f}" r="8.5" fill="#FFFFFF" '
            f'stroke="{TREE_NODE}" stroke-width="1.1"/>'
        )
        add(svg_text(487.5, y + 3.5, f"{index_by_id[leaf.genome_id]:02d}", 9.5, weight=800, fill="#111111", anchor="middle"))
        add(
            f'<text class="leaf-label" x="505" y="{y + 4.6:.2f}" '
            f'font-family="Arial, Helvetica, sans-serif" font-size="{font_size}" '
            f'font-weight="700" fill="{INK}">'
            f'<title>{escape(leaf.display_label)} — internal genome ID: {escape(leaf.genome_id)} — {resolution}</title>'
            f'<tspan font-style="italic">{escape(scientific)}</tspan>'
            + (f'<tspan>&#160;{escape(suffix)}</tspan>' if suffix else "")
            + '</text>'
        )

        total_bgc = sum(leaf.bgc_counts.values())
        bar_y = y - 6.5
        cursor = bgc_x
        add(
            f'<g class="bgc-profile" data-genome="{escape(leaf.genome_id)}" '
            f'data-bgc-count="{total_bgc}" data-x="{bgc_x:.1f}" data-width="{bgc_w:.1f}">'
        )
        for category in BGC_ORDER:
            count = leaf.bgc_counts.get(category, 0)
            if count <= 0:
                continue
            segment_width = bgc_w * count / bgc_axis_max
            add(
                f'<rect x="{cursor:.2f}" y="{bar_y:.2f}" width="{segment_width:.2f}" height="13" '
                f'fill="{BGC_COLORS[category]}" stroke="#FFFFFF" stroke-width="0.7">'
                f'<title>{escape(leaf.display_label)} — {category}: {count} of {total_bgc} BGCs</title></rect>'
            )
            cursor += segment_width
        add('</g>')
        add(svg_text(bgc_x + bgc_w + 9, y + 4.2, str(total_bgc), 13, fill=INK))

        total_gcf = sum(leaf.gcf_counts.values())
        within = leaf.gcf_counts.get("shared_within_taxon", 0)
        cross = leaf.gcf_counts.get("shared_across_taxon", 0)
        private = leaf.gcf_counts.get("private_singleton", 0)
        add(
            f'<g class="gcf-profile" data-genome="{escape(leaf.genome_id)}" '
            f'data-gcf-count="{total_gcf}" data-x="{gcf_x:.1f}" data-width="{gcf_w:.1f}">'
        )
        if total_gcf <= 0:
            add(
                f'<title>{escape(leaf.display_label)} — N/A: no GCFs were assigned in the selected '
                'BiG-SCAPE view, so the shared-GCF percentage has no denominator.</title>'
            )
            add(
                f'<rect class="gcf-status-na" x="{gcf_x:.2f}" y="{bar_y:.2f}" '
                f'width="{gcf_w:.2f}" height="13" fill="#FFFFFF" '
                f'stroke="{SEPARATOR}" stroke-width="0.8" stroke-dasharray="2 2">'
                f'<title>{escape(leaf.display_label)} — no GCFs are assigned in the selected view; '
                'the shared percentage is undefined.</title></rect>'
            )
        else:
            add(
                f'<title>{escape(leaf.display_label)} — shared-GCF percentage: {within + cross} unique '
                'GCFs found in this genome and at least one other submitted genome, divided by all '
                f'{total_gcf} unique GCFs assigned to this genome.</title>'
            )
            statuses = [
                ("same-domain shared", within, WITHIN),
                ("cross-domain shared", cross, "url(#crossHatch)"),
                ("dataset singleton", private, PRIVATE),
            ]
            cursor = gcf_x
            for label, count, fill in statuses:
                if count <= 0:
                    continue
                segment_width = gcf_w * count / total_gcf
                percentage = 100.0 * count / total_gcf
                add(
                    f'<rect x="{cursor:.2f}" y="{bar_y:.2f}" width="{segment_width:.2f}" height="13" '
                    f'fill="{fill}" stroke="#FFFFFF" stroke-width="0.7">'
                    f'<title>{escape(leaf.display_label)} — {label}: {count} unique GCFs '
                    f'({percentage:.1f}% of this genome&apos;s {total_gcf} unique GCFs); '
                    'dataset-relative to the submitted genomes.</title></rect>'
                )
                cursor += segment_width
        add('</g>')
        if total_gcf <= 0:
            add(
                f'<text x="{gcf_x + gcf_w + 9:.2f}" y="{y + 4.2:.2f}" '
                'font-family="Arial, Helvetica, sans-serif" font-size="13" '
                f'font-weight="400" fill="{MUTED}">'
                f'<title>{escape(leaf.display_label)} — N/A because no GCFs are assigned in the selected view.</title>'
                'N/A</text>'
            )
        else:
            shared_percent = 100.0 * (within + cross) / total_gcf
            add(
                f'<text x="{gcf_x + gcf_w + 9:.2f}" y="{y + 4.2:.2f}" '
                'font-family="Arial, Helvetica, sans-serif" font-size="13" '
                f'font-weight="400" fill="{INK}">'
                f'<title>{within + cross} of {total_gcf} unique GCFs are also found in at least one other submitted genome; this percentage is dataset-relative.</title>'
                f'{shared_percent:.1f}%</text>'
            )
    add('</g>')
    add('</g>')

    add('<g id="panel-b" aria-label="Pairwise GCF sharing">')
    gradient_width = min(220.0, matrix_size * 0.42)
    add(
        f'<text x="{matrix_x:.2f}" y="76" font-family="Arial, Helvetica, sans-serif" '
        f'font-size="13" font-weight="700" fill="{INK}">'
        '<title>GCFs present in both genomes divided by the nonredundant union of GCFs present in either genome.</title>'
        'GCF overlap · Jaccard %</text>'
    )
    add(
        f'<rect x="{matrix_x:.2f}" y="90" width="{gradient_width:.2f}" height="10" '
        f'fill="url(#jaccardGradient)" stroke="{SEPARATOR}" stroke-width="0.8"/>'
    )
    add(svg_text(matrix_x, 120, "0%", 10.5, weight=700, fill=MUTED, anchor="middle"))
    add(svg_text(matrix_x + gradient_width, 120, f"{legend_max * 100:.0f}%", 10.5, weight=700, fill=MUTED, anchor="middle"))

    spans: list[tuple[str, int, int]] = []
    offset = 0
    for domain in domain_order:
        count = len(grouped[domain])
        spans.append((domain, offset, count))
        offset += count
    for domain, start, count in spans:
        x = matrix_x + start * cell
        span_width = count * cell
        add(svg_text(x + span_width / 2.0, matrix_y - 22.0, domain_meta[domain], 12, weight=700, fill=INK, anchor="middle"))
        add(
            f'<line x1="{x:.2f}" y1="{matrix_y - 17:.2f}" x2="{x + span_width:.2f}" '
            f'y2="{matrix_y - 17:.2f}" stroke="{SEPARATOR}" stroke-width="0.8"/>'
        )

    add(
        f'<rect x="{matrix_x:.2f}" y="{matrix_y:.2f}" width="{matrix_size:.2f}" '
        f'height="{matrix_size:.2f}" fill="#FFFFFF" stroke="{INK}" stroke-width="1"/>'
    )
    for row in range(n_genomes):
        for column in range(n_genomes):
            fill = (
                UPPER_TRIANGLE
                if column > row
                else "#F2F2F2"
                if row == column
                else "#FFFFFF"
                if leaves[row].taxon_group == leaves[column].taxon_group
                else "#FAFAFA"
            )
            add(
                f'<rect x="{matrix_x + column * cell:.2f}" y="{matrix_y + row * cell:.2f}" '
                f'width="{cell:.2f}" height="{cell:.2f}" fill="{fill}"/>'
            )

    boundary_indices = {0, n_genomes - 1}
    for _, start, count in spans:
        boundary_indices.update((start, start + count - 1))
    label_indices = {
        index
        for index in range(n_genomes)
        if index in boundary_indices or (index + 1) % 5 == 0
    }
    for index in sorted(label_indices):
        x = matrix_x + (index + 0.5) * cell
        y = matrix_y + (index + 0.5) * cell
        add(svg_text(x, matrix_y - 6.0, f"{index + 1:02d}", 9.5, weight=700, fill=INK, anchor="middle"))
        add(svg_text(matrix_x - 17.0, y + 3.2, f"{index + 1:02d}", 9.5, weight=700, fill=INK, anchor="end"))
    for index in range(0, n_genomes + 1, 5):
        x = matrix_x + index * cell
        y = matrix_y + index * cell
        add(f'<line class="matrix-grid" x1="{x:.2f}" y1="{matrix_y:.2f}" x2="{x:.2f}" y2="{matrix_y + matrix_size:.2f}"/>')
        add(f'<line class="matrix-grid" x1="{matrix_x:.2f}" y1="{y:.2f}" x2="{matrix_x + matrix_size:.2f}" y2="{y:.2f}"/>')
    if len(spans) > 1:
        separator = spans[0][2] * cell
        add(f'<line x1="{matrix_x + separator:.2f}" y1="{matrix_y:.2f}" x2="{matrix_x + separator:.2f}" y2="{matrix_y + matrix_size:.2f}" stroke="{TREE}" stroke-width="1.2"/>')
        add(f'<line x1="{matrix_x:.2f}" y1="{matrix_y + separator:.2f}" x2="{matrix_x + matrix_size:.2f}" y2="{matrix_y + separator:.2f}" stroke="{TREE}" stroke-width="1.2"/>')

    for pair in pairs:
        left = pair["left"]
        right = pair["right"]
        assert isinstance(left, Leaf) and isinstance(right, Leaf)
        row = max(index_by_id[left.genome_id] - 1, index_by_id[right.genome_id] - 1)
        column = min(index_by_id[left.genome_id] - 1, index_by_id[right.genome_id] - 1)
        x = matrix_x + column * cell
        y = matrix_y + row * cell
        jaccard = float(pair["jaccard"])
        color = interpolate_color("#E8EDF8", WITHIN, math.sqrt(jaccard / legend_max if legend_max else 0.0))
        classes = pair["classes"]
        assert isinstance(classes, Counter)
        shared = int(pair["shared"])
        class_text = ", ".join(
            f"{category} {classes[category]} ({100.0 * classes[category] / shared:.1f}%)"
            for category in BGC_ORDER
            if classes[category]
        )
        add(
            f'<rect class="gcf-pair" x="{x + 0.75:.2f}" y="{y + 0.75:.2f}" '
            f'width="{cell - 1.5:.2f}" height="{cell - 1.5:.2f}" fill="{color}" '
            f'stroke="#FFFFFF" stroke-width="1"><title>{escape(left.display_label)} ↔ '
            f'{escape(right.display_label)} — GCF overlap {jaccard * 100.0:.1f}% (Jaccard); '
            f'{shared} shared GCFs; Jaccard is shared GCFs divided by the nonredundant union of GCFs '
            'in either genome; shared GCFs by representative BGC class: '
            f'{escape(class_text)}</title></rect>'
        )

    if len(spans) == 2 and not any(
        pair["left"].taxon_group != pair["right"].taxon_group  # type: ignore[union-attr]
        for pair in pairs
    ):
        first_count, second_count = spans[0][2], spans[1][2]
        cross_x = matrix_x
        cross_y = matrix_y + first_count * cell
        cross_width = first_count * cell
        cross_height = second_count * cell
        add(svg_text(cross_x + cross_width / 2.0, cross_y + cross_height / 2.0 + 5.0, "No cross-domain links", 15, weight=700, fill=MUTED, anchor="middle"))

    add(svg_text(panel_b_x + 22.0, table_y, "Links", 16, weight=700, fill=INK))
    header_y = table_y + 34.0
    table_x = panel_b_x + 18.0
    table_width = panel_b_w - 36.0
    pair_index_x = table_x + 14.0
    pair_label_x = table_x + 70.0
    shared_x = table_x + 480.0
    overlap_x = table_x + 568.0
    bar_x = table_x + 600.0
    bar_right = table_x + table_width - 10.0
    bar_width = bar_right - bar_x
    add(svg_text(pair_index_x, header_y, "Pair", 13, weight=700, fill=INK))
    add(svg_text(shared_x, header_y, "Shared", 13, weight=700, fill=INK, anchor="end"))
    add(svg_text(overlap_x, header_y, "Overlap", 13, weight=700, fill=INK, anchor="end"))
    add(svg_text(bar_x, header_y, "Shared GCFs by BGC class", 13, weight=700, fill=INK))
    axis_y = header_y + 18.0
    add(f'<line x1="{bar_x:.2f}" y1="{axis_y:.2f}" x2="{bar_right:.2f}" y2="{axis_y:.2f}" stroke="{SEPARATOR}" stroke-width="0.8"/>')
    for fraction in (0.0, 0.5, 1.0):
        tick_x = bar_x + bar_width * fraction
        add(f'<line x1="{tick_x:.2f}" y1="{axis_y - 3.0:.2f}" x2="{tick_x:.2f}" y2="{axis_y + 3.0:.2f}" stroke="{SEPARATOR}" stroke-width="0.8"/>')
    add(svg_text(bar_x, header_y + 32.0, "0", 9.5, weight=700, fill=MUTED))
    add(svg_text(bar_x + bar_width / 2.0, header_y + 32.0, "50", 9.5, weight=700, fill=MUTED, anchor="middle"))
    add(svg_text(bar_right, header_y + 32.0, "100%", 9.5, weight=700, fill=MUTED, anchor="end"))
    add(f'<line x1="{table_x:.2f}" y1="{header_y + 40:.2f}" x2="{table_x + table_width:.2f}" y2="{header_y + 40:.2f}" stroke="{SEPARATOR}" stroke-width="0.8"/>')
    if not table_pairs:
        add(svg_text(table_x + 14, header_y + 62.0, "No shared GCF links", 13.2, fill=MUTED))
    else:
        for rank, pair in enumerate(table_pairs):
            y = header_y + 60.0 + rank * 28.0
            left = pair["left"]
            right = pair["right"]
            assert isinstance(left, Leaf) and isinstance(right, Leaf)
            pair_index = f"{index_by_id[left.genome_id]:02d}-{index_by_id[right.genome_id]:02d}"
            label = f"{short_name(left.display_label)} ↔ {short_name(right.display_label)}"
            full_label = f"{left.display_label} ↔ {right.display_label}"
            add(svg_text(pair_index_x, y, pair_index, 13, weight=700, fill=INK))
            add(svg_text(pair_label_x, y, label, 12.6, fill=INK))
            add(svg_text(shared_x, y, str(pair["shared"]), 13, fill=INK, anchor="end"))
            add(svg_text(overlap_x, y, f'{float(pair["jaccard"]) * 100.0:.1f}%', 13, fill=INK, anchor="end"))
            add(f'<rect x="{bar_x:.2f}" y="{y - 8.0:.2f}" width="{bar_width:.2f}" height="10" fill="#F7F7F7"/>')
            cursor = bar_x
            classes = pair["classes"]
            assert isinstance(classes, Counter)
            for category in BGC_ORDER:
                count = classes.get(category, 0)
                if count <= 0:
                    continue
                shared = int(pair["shared"])
                segment_width = bar_width * count / shared
                percentage = 100.0 * count / shared
                add(
                    f'<rect x="{cursor:.2f}" y="{y - 8.0:.2f}" width="{segment_width:.2f}" '
                    f'height="10" fill="{BGC_COLORS[category]}" stroke="#FFFFFF" stroke-width="0.7">'
                    f'<title>{escape(full_label)} — {category}: {count} shared GCFs '
                    f'({percentage:.1f}% of {shared}); each shared GCF is assigned its representative broad BGC class.</title></rect>'
                )
                cursor += segment_width
            add(f'<rect x="{bar_x:.2f}" y="{y - 8.0:.2f}" width="{bar_width:.2f}" height="10" fill="none" stroke="{BOUNDARY}" stroke-width="0.7"/>')
            if rank < len(table_pairs) - 1:
                add(f'<line x1="{table_x:.2f}" y1="{y + 10:.2f}" x2="{table_x + table_width:.2f}" y2="{y + 10:.2f}" stroke="{GRID}" stroke-width="0.7"/>')
    add('</g>')

    add(f'<rect x="30" y="{footer_y:.2f}" width="2140" height="{footer_h}" fill="none" stroke="{BOUNDARY}" stroke-width="1.2"/>')
    legend_y = footer_y + 36.0
    add(svg_text(50, legend_y, "BGC class", 16, weight=700, fill=INK))
    x = 142.0
    item_widths = {
        "NRPS": 82.0,
        "PKS": 76.0,
        "terpene": 104.0,
        "RiPP": 76.0,
        "hybrid": 92.0,
        "other": 82.0,
    }
    for category in BGC_ORDER:
        add(f'<circle cx="{x + 7:.2f}" cy="{legend_y - 5.5:.2f}" r="7" fill="{BGC_COLORS[category]}" stroke="{TREE_NODE}" stroke-width="1.1"/>')
        add(svg_text(x + 22, legend_y, category, 13, fill=INK))
        x += item_widths[category]

    x = 730.0
    add(svg_text(x, legend_y, "GCF status", 16, weight=700, fill=INK))
    x += 100.0
    statuses = [
        (PRIVATE, "singleton", None, 105.0),
        (WITHIN, "same-domain", None, 145.0),
    ]
    if display_mode == "mixed":
        statuses.append((CROSS, "cross-domain", "url(#crossHatch)", 145.0))
    for color, label, pattern, item_width in statuses:
        add(
            f'<rect x="{x:.2f}" y="{legend_y - 13:.2f}" width="15" height="15" '
            f'fill="{pattern or color}" stroke="{TREE_NODE}" stroke-width="0.8"/>'
        )
        add(svg_text(x + 22, legend_y, label, 13, fill=INK))
        x += item_width
    add(svg_text(1915, legend_y, "Unique pairs below diagonal", 13, fill=MUTED, anchor="end"))
    add(svg_text(2145, legend_y, "Rank-aligned; not a phylogram", 13, fill=MUTED, anchor="end"))
    add('</svg>')
    return "\n".join(lines) + "\n"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_zip(path: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(files, key=lambda item: item.name):
            info = zipfile.ZipInfo(source.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())


def render(args: argparse.Namespace) -> dict[str, Path]:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {key: output_dir / filename for key, filename in TREE_FILENAMES.items()}
    leaves = load_leaves(args.manifest, args.taxonomy)
    gcf_category = canonical_gcf_category(
        getattr(args, "gcf_category", DEFAULT_GCF_CATEGORY)
    )
    gcf_threshold = canonical_gcf_threshold(
        getattr(args, "gcf_threshold", DEFAULT_GCF_THRESHOLD)
    )
    family_genomes, edges = add_profiles(
        leaves,
        args.exact_products,
        args.crosswalk,
        gcf_category,
        gcf_threshold,
    )
    root = build_tree(leaves)

    paths["newick"].write_text(to_newick(root) + ";\n", encoding="utf-8")
    visible_limit = max(0, args.max_visible_arcs)
    svg = render_svg(
        root, leaves, edges, visible_limit, gcf_category, gcf_threshold
    )
    paths["svg"].write_text(svg, encoding="utf-8")
    paths["png"].unlink(missing_ok=True)
    if args.png:
        try:
            import cairosvg  # type: ignore
        except ImportError:
            pass
        else:
            cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(paths["png"]))

    profile_rows: list[dict[str, object]] = []
    for leaf in leaves:
        profile_rows.append(
            {
                "genome_id": leaf.genome_id,
                "display_label": leaf.display_label,
                "taxon_group": leaf.taxon_group,
                "taxon_source": leaf.taxon_source,
                "taxid": leaf.taxid,
                "organism_name": leaf.organism_name,
                "lineage": "|".join(leaf.lineage),
                "lineage_ids": "|".join(leaf.lineage_ids),
                "taxonomy_resolution": "unresolved_polytomy" if leaf.unresolved else "saved_lineage",
                "prediction_method": leaf.prediction_method,
                "detector_profile": leaf.detector_profile,
                "bgc_total": sum(leaf.bgc_counts.values()),
                **{f"bgc_{category.lower()}": leaf.bgc_counts.get(category, 0) for category in BGC_ORDER},
                "gcf_selected_category": gcf_category,
                "gcf_selected_threshold": gcf_threshold,
                "gcf_total": sum(leaf.gcf_counts.values()),
                "gcf_unassigned_rows": leaf.gcf_unassigned_rows,
                "gcf_not_applicable_rows": leaf.gcf_not_applicable_rows,
                "gcf_shared_within_taxon": leaf.gcf_counts.get("shared_within_taxon", 0),
                "gcf_shared_across_taxon": leaf.gcf_counts.get("shared_across_taxon", 0),
                "gcf_private_singleton": leaf.gcf_counts.get("private_singleton", 0),
                "gcf_ids": ";".join(sorted(leaf.gcf_ids)),
            }
        )
    profile_fields = [
        "genome_id", "display_label", "taxon_group", "taxon_source", "taxid",
        "organism_name", "lineage", "lineage_ids", "taxonomy_resolution", "prediction_method",
        "detector_profile", "bgc_total", *[f"bgc_{category.lower()}" for category in BGC_ORDER],
        "gcf_selected_category", "gcf_selected_threshold", "gcf_total",
        "gcf_unassigned_rows", "gcf_not_applicable_rows",
        "gcf_shared_within_taxon", "gcf_shared_across_taxon", "gcf_private_singleton", "gcf_ids",
    ]
    write_tsv(paths["profiles"], profile_fields, profile_rows)
    edge_fields = [
        "source", "target", "source_taxon", "target_taxon", "cross_taxon",
        "gcf_category", "gcf_threshold", "shared_gcf_count",
        "shared_gcf_ids", "shared_gcf_classes",
        "gcf_class_counts", "visible_in_svg",
    ]
    write_tsv(paths["edges"], edge_fields, edges)
    paths["graphml"].write_text(
        graphml_text(leaves, edges, gcf_category, gcf_threshold),
        encoding="utf-8",
    )

    methods = {
        "schema_version": 2,
        "renderer": "render_phylo_taxon_profile.py",
        "renderer_version": RENDERER_VERSION,
        "basis": "saved_ranked_taxonomy",
        "topology_method": "separate deterministic ranked lineage tries with unresolved domain polytomies",
        "branch_lengths": "not_inferred",
        "leaf_sort": "taxon_group, saved lineage, stable genome_id",
        "bgc_display_ontology": ONTOLOGY_VERSION,
        "bgc_marker_scaling": "absolute stacked horizontal bar on a shared BGC-count axis",
        "bgc_class_palette": "shared ClusterWeave BiG-SCAPE multipanel class palette",
        "gcf_selected_category": gcf_category,
        "gcf_selected_threshold": gcf_threshold,
        "gcf_membership_basis": (
            "only selected category/threshold memberships contribute to GCF "
            "counts and pairwise sharing views"
        ),
        "gcf_unassigned_interpretation": (
            "eligible crosswalk rows without a selected-view GCF; excluded "
            "from private/singleton counts"
        ),
        "gcf_not_applicable_interpretation": (
            "detector-only rows not eligible for BiG-SCAPE membership"
        ),
        "gcf_marker_encoding": (
            "proportional status bar: shared within taxon, shared Cross-Kingdom, private singleton"
        ),
        "gcf_arc_encoding": (
            "legacy metadata key: lower-triangular genome-pair Jaccard matrix "
            "plus a ranked link table with stacked broad BGC-class bars"
        ),
        "gcf_arc_selection": (
            "strongest shared-family count, then stable genome pair; mixed jobs "
            "reserve a bounded cross-taxon lane"
        ),
        "visual_layout": (
            "approved rank-aligned two-panel profile with absolute BGC bars, "
            "proportional GCF bars, Jaccard matrix, and ranked pair table"
        ),
        "max_visible_arcs": visible_limit,
        "all_edges_exported": True,
        "cross_domain_interpretation": "shared Cross-Kingdom computational GCF context; no evolutionary event, mechanism, or direction established",
        "sequence_inference": "not_performed",
    }
    paths["methods"].write_text(json.dumps(methods, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    artifact_paths = [paths[key] for key in ("svg", "newick", "profiles", "edges", "graphml", "methods")]
    if paths["png"].exists():
        artifact_paths.append(paths["png"])
    manifest = {
        "schema_version": 2,
        "status": "success",
        "basis": "saved_ranked_taxonomy",
        "leaf_count": len(leaves),
        "edge_count": len(edges),
        "visible_arc_count": sum(bool(edge.get("visible_in_svg")) for edge in edges),
        "visible_pair_count": sum(bool(edge.get("visible_in_svg")) for edge in edges),
        "unresolved_leaf_count": sum(leaf.unresolved for leaf in leaves),
        "taxon_counts": dict(Counter(leaf.taxon_group for leaf in leaves)),
        "gcf_selected_category": gcf_category,
        "gcf_selected_threshold": gcf_threshold,
        "gcf_assigned_family_count": len(family_genomes),
        "gcf_unassigned_row_count": sum(
            leaf.gcf_unassigned_rows for leaf in leaves
        ),
        "gcf_not_applicable_row_count": sum(
            leaf.gcf_not_applicable_rows for leaf in leaves
        ),
        "renderer_version": RENDERER_VERSION,
        "artifacts": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path), "status": "success"}
            for path in sorted(artifact_paths, key=lambda item: item.name)
        ],
    }
    paths["manifest"].write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bundle_files = [*artifact_paths, paths["manifest"]]
    deterministic_zip(paths["bundle"], bundle_files)
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, default=None)
    parser.add_argument("--exact-products", type=Path, default=None)
    parser.add_argument("--crosswalk", type=Path, default=None)
    parser.add_argument(
        "--gcf-category",
        default=DEFAULT_GCF_CATEGORY,
        help="BiG-SCAPE category used for tree GCF counts/arcs (default: mix).",
    )
    parser.add_argument(
        "--gcf-threshold",
        default=DEFAULT_GCF_THRESHOLD,
        help="BiG-SCAPE clustering threshold used for tree GCF counts/arcs (default: 0.3).",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--max-visible-arcs",
        type=int,
        default=80,
        help="Maximum pairwise GCF links rendered (legacy option name; default: 80).",
    )
    parser.add_argument("--png", action="store_true")
    args = parser.parse_args()
    args.max_visible_arcs = max(0, min(500, args.max_visible_arcs))
    args.gcf_category = canonical_gcf_category(args.gcf_category)
    args.gcf_threshold = canonical_gcf_threshold(args.gcf_threshold)
    return args


if __name__ == "__main__":
    produced = render(parse_args())
    print(f"TREE_ARTIFACT kind=taxonomy_context basis=taxonomy status=success file={produced['svg'].name}")
