#!/usr/bin/env python3
"""Render a publication-style BiG-SCAPE multipanel figure.

The figure combines a compact BGC/GCF count bar chart with the ClusterWeave
BiG-SCAPE network rendering. It writes a multi-panel SVG with optional PNG/PDF
export through cairosvg; the count chart can also be written as a standalone
debugging SVG when requested.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape

import render_bigscape_network as network


CHART_CLASSES = ["NRPS", "PKS", "terpene", "RiPP", "hybrid", "other"]
CHART_COLORS = {
    "NRPS": network.CLASS_COLORS["NRPS"],
    "PKS": network.CLASS_COLORS["PKS"],
    "terpene": network.CLASS_COLORS["terpene"],
    "RiPP": network.CLASS_COLORS["RiPP"],
    "hybrid": network.CLASS_COLORS["hybrid"],
    "other": network.CLASS_COLORS["other"],
}
CHART_ROWS_BY_TAXON = {
    "fungi": [("BGC", "funbgcex"), ("BGC", "antismash"), ("GCF", "antismash")],
    "bacteria": [("BGC", "antismash"), ("GCF", "antismash")],
}
DEFAULT_CANVAS_WIDTH = 2400
DEFAULT_MIN_HEIGHT = 0
FONT_SIZE_INCREMENT = 2
CHART_TOP_SPACE = 54.0
CHART_BOTTOM_SPACE = 42.0
CHART_PER_GENOME_HEIGHT = 92.0
CHART_GROUP_GAP = 12.0
CHART_MIN_HEIGHT = 330.0
CHART_BODY_LABEL_SIZE = 13
CHART_TOTAL_LABEL_SIZE = 11


def chart_rows_for_taxon(taxon_group: str) -> list[tuple[str, str]]:
    return list(CHART_ROWS_BY_TAXON[taxon_group])


def clean(value: object) -> str:
    return network.clean(value)


def display_tool_label(value: str) -> str:
    token = clean(value).casefold()
    if token == "antismash":
        return "antiSMASH"
    if token == "funbgcex":
        return "FunBGCeX"
    return clean(value)


def shorten(text: str, limit: int = 30) -> str:
    value = clean(text).replace("_", " ")
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def normalize_chart_class(value: str) -> str:
    text = re.sub(r"[_;/|.+-]+", " ", clean(value).lower())
    if not text:
        return "other"
    has_nrps = bool(re.search(r"\bnrps?\b|\bnrp\b|nrps-like", text))
    has_pks = bool(re.search(r"\bpks\b|t1pks|polyketide|nr-pks|hr-pks", text))
    has_ripp = "ripp" in text or "lanthipeptide" in text or "lassopeptide" in text
    has_terpene = "terpene" in text or bool(re.search(r"\btc\b|cyclase|synthase", text))
    major_hits = [
        label
        for label, present in [
            ("NRPS", has_nrps),
            ("PKS", has_pks),
            ("RiPP", has_ripp),
            ("terpene", has_terpene),
        ]
        if present
    ]
    if len(major_hits) > 1:
        return "hybrid"
    if major_hits:
        return major_hits[0]
    if "hybrid" in text:
        return "hybrid"
    return "other"


def read_summary_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def load_sample_display_labels(
    manifest_path: Path | None, taxon_group: str
) -> dict[str, str]:
    """Return display-only labels for historical NCBI routing identifiers.

    Releases before v1.0 prefixed NCBI-derived bacterial IDs with
    ``bacteria_``. User-supplied IDs may legitimately begin with the same
    text, so provenance from the canonical taxon manifest is required before
    that legacy prefix is hidden.
    """
    if manifest_path is None or not manifest_path.exists():
        return {}
    first = manifest_path.read_text(
        encoding="utf-8-sig", errors="ignore"
    ).splitlines()
    delimiter = "," if first and "," in first[0] and "\t" not in first[0] else "\t"
    labels: dict[str, str] = {}
    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle, delimiter=delimiter):
            genome_id = clean(row.get("genome_id") or row.get("genome"))
            row_taxon = clean(row.get("taxon_group")).casefold()
            taxon_source = clean(row.get("taxon_source")).casefold()
            if (
                taxon_group == "bacteria"
                and row_taxon == "bacteria"
                and taxon_source == "ncbi"
                and genome_id.startswith("bacteria_")
                and len(genome_id) > len("bacteria_")
            ):
                labels[genome_id] = genome_id[len("bacteria_") :]
    return labels


def count_matrix(
    summary_path: Path, taxon_group: str = "fungi"
) -> tuple[list[str], dict[tuple[str, str, str], dict[str, float]]]:
    rows = read_summary_rows(summary_path)
    chart_rows = chart_rows_for_taxon(taxon_group)
    genomes: list[str] = []
    matrix: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        row_taxon = clean(row.get("taxon_group")).casefold()
        if row_taxon and row_taxon != taxon_group:
            continue
        entity_type = clean(row.get("entity_type")).upper()
        tool = clean(row.get("tool")).casefold()
        if (entity_type, tool) not in chart_rows:
            continue
        genome = clean(row.get("genome"))
        if not genome:
            continue
        if genome not in genomes:
            genomes.append(genome)
        category = normalize_chart_class(clean(row.get("class_norm")))
        try:
            total = float(clean(row.get("total")) or 0)
        except ValueError:
            total = 0.0
        matrix[(genome, entity_type, tool)][category] += max(0.0, total)

    return genomes, matrix


def chart_height_for_genome_count(genome_count: int, row_count: int = 3) -> float:
    if genome_count <= 0:
        return CHART_MIN_HEIGHT
    per_genome_height = max(
        66.0, CHART_PER_GENOME_HEIGHT - max(0, 3 - row_count) * 14.0
    )
    plot_h = genome_count * per_genome_height + max(0, genome_count - 1) * CHART_GROUP_GAP
    return max(CHART_MIN_HEIGHT, CHART_TOP_SPACE + CHART_BOTTOM_SPACE + plot_h)


def chart_height_for_summary(summary_path: Path, taxon_group: str = "fungi") -> float:
    genomes, _ = count_matrix(summary_path, taxon_group)
    return chart_height_for_genome_count(
        len(genomes), len(chart_rows_for_taxon(taxon_group))
    )


def nice_tick_step(max_value: float, target_ticks: int = 5) -> float:
    if max_value <= 0:
        return 1.0
    raw = max_value / max(1, target_ticks)
    exponent = math.floor(math.log10(raw))
    fraction = raw / (10**exponent)
    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10
    return nice * (10**exponent)


def svg_text(
    x: float,
    y: float,
    text: str,
    size: int,
    weight: str = "400",
    anchor: str = "start",
    fill: str = "#222222",
    extra: str = "",
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial, Helvetica, sans-serif" '
        f'font-size="{max(4, size + FONT_SIZE_INCREMENT)}" font-weight="{weight}" text-anchor="{anchor}" '
        f'fill="{fill}"{extra}>{escape(text)}</text>'
    )


def chart_lines(
    summary_path: Path,
    x: float,
    y: float,
    width: float,
    height: float,
    warnings: list[str],
    taxon_group: str = "fungi",
    title_anchor: str = "middle",
    title_x: float | None = None,
    sample_display_labels: dict[str, str] | None = None,
) -> list[str]:
    genomes, matrix = count_matrix(summary_path, taxon_group)
    chart_rows = chart_rows_for_taxon(taxon_group)
    lines: list[str] = []
    lines.append(
        svg_text(
            title_x if title_x is not None else x + width / 2.0,
            y + 18,
            "BGC and GCF count by genome, tool, and class",
            18,
            "700",
            anchor=title_anchor,
        )
    )

    if not genomes:
        warnings.append(f"No BGC/GCF summary rows were found in: {summary_path}")
        lines.append(svg_text(x + 12, y + 74, "No BGC/GCF count data available", 10, "700"))
        return lines

    left = 122.0
    right = 28.0
    top = CHART_TOP_SPACE
    bottom = CHART_BOTTOM_SPACE
    plot_x = x + left
    plot_y = y + top
    plot_w = max(1.0, width - left - right)
    plot_h = max(1.0, height - top - bottom)
    axis_y = plot_y + plot_h

    bar_keys = [(genome, entity_type, tool) for genome in genomes for entity_type, tool in chart_rows]
    max_total = max(sum(matrix[key].get(category, 0.0) for category in CHART_CLASSES) for key in bar_keys)
    tick_step = nice_tick_step(max_total)
    x_max = max(tick_step, math.ceil(max_total / tick_step) * tick_step)
    tick_count = int(round(x_max / tick_step))

    lines.append(f'<line x1="{plot_x:.1f}" y1="{plot_y:.1f}" x2="{plot_x:.1f}" y2="{axis_y:.1f}" stroke="#222222" stroke-width="1"/>')
    lines.append(f'<line x1="{plot_x:.1f}" y1="{axis_y:.1f}" x2="{plot_x + plot_w:.1f}" y2="{axis_y:.1f}" stroke="#222222" stroke-width="1"/>')

    for tick in range(tick_count + 1):
        value = tick * tick_step
        tx = plot_x + (value / x_max) * plot_w
        lines.append(f'<line x1="{tx:.1f}" y1="{axis_y:.1f}" x2="{tx:.1f}" y2="{axis_y + 4:.1f}" stroke="#222222" stroke-width="0.8"/>')
        if tick > 0:
            lines.append(f'<line x1="{tx:.1f}" y1="{plot_y:.1f}" x2="{tx:.1f}" y2="{axis_y:.1f}" stroke="#E5E5E5" stroke-width="0.8"/>')
        lines.append(svg_text(tx, axis_y + 17, f"{int(value)}", CHART_BODY_LABEL_SIZE, "700", anchor="middle"))

    lines.append(svg_text(plot_x + plot_w / 2.0, axis_y + 34, "Count", CHART_BODY_LABEL_SIZE, "700", anchor="middle"))

    group_count = max(1, len(genomes))
    group_gap_y = CHART_GROUP_GAP if group_count > 1 else 0.0
    group_h = (plot_h - group_gap_y * max(0, group_count - 1)) / group_count
    row_gap = 6.0
    bar_h = min(16.0, max(10.0, (group_h - 32.0 - row_gap * (len(chart_rows) - 1)) / len(chart_rows)))
    row_block_h = len(chart_rows) * bar_h + (len(chart_rows) - 1) * row_gap
    label_baseline_offset = 14.0
    label_to_bar_gap = 14.0
    group_block_h = label_baseline_offset + label_to_bar_gap + row_block_h
    genome_label_size = CHART_BODY_LABEL_SIZE if len(genomes) <= 5 else 12

    for genome_index, genome in enumerate(genomes):
        group_y = plot_y + genome_index * (group_h + group_gap_y)
        block_y = group_y + max(0.0, (group_h - group_block_h) / 2.0)
        label_y = block_y + label_baseline_offset
        row_y = label_y + label_to_bar_gap
        display_genome = clean((sample_display_labels or {}).get(genome)) or genome
        lines.append(network.svg_sample_label(plot_x, label_y, display_genome, genome_label_size, "700", anchor="start"))
        if genome_index > 0:
            sep_y = group_y - group_gap_y / 2.0
            lines.append(f'<line x1="{plot_x:.1f}" y1="{sep_y:.1f}" x2="{plot_x + plot_w:.1f}" y2="{sep_y:.1f}" stroke="#B8B8B8" stroke-width="0.8" stroke-dasharray="2 3"/>')

        for row_index, (entity_type, tool) in enumerate(chart_rows):
            bar_y = row_y + row_index * (bar_h + row_gap)
            key = (genome, entity_type, tool)
            label = display_tool_label(tool) if entity_type == "BGC" else "GCF"
            lines.append(svg_text(plot_x - 10, bar_y + bar_h / 2.0 + 4.0, label, CHART_BODY_LABEL_SIZE, "700" if entity_type == "GCF" else "400", anchor="end"))
            stack_x = plot_x
            total = 0.0
            for category in CHART_CLASSES:
                value = matrix[key].get(category, 0.0)
                if value <= 0:
                    continue
                segment_w = (value / x_max) * plot_w
                lines.append(
                    f'<rect x="{stack_x:.1f}" y="{bar_y:.1f}" width="{segment_w:.1f}" height="{bar_h:.1f}" '
                    f'fill="{CHART_COLORS[category]}" stroke="#FFFFFF" stroke-width="0.7"/>'
                )
                stack_x += segment_w
                total += value
            total_label = f"{int(total)}"
            if total > 0:
                if stack_x + 22.0 < plot_x + plot_w:
                    lines.append(svg_text(stack_x + 5.0, bar_y + bar_h / 2.0 + 4.0, total_label, CHART_TOTAL_LABEL_SIZE, anchor="start"))
                else:
                    lines.append(svg_text(stack_x - 5.0, bar_y + bar_h / 2.0 + 4.0, total_label, CHART_TOTAL_LABEL_SIZE, "700", anchor="end", fill="#FFFFFF"))

    return lines


def write_count_chart_svg(
    path: Path,
    summary_path: Path,
    warnings: list[str],
    taxon_group: str = "fungi",
    sample_display_labels: dict[str, str] | None = None,
) -> None:
    width = 620
    height = int(chart_height_for_summary(summary_path, taxon_group) + 68.0)
    body = chart_lines(
        summary_path,
        34.0,
        34.0,
        540.0,
        height - 68.0,
        warnings,
        taxon_group,
        sample_display_labels=sample_display_labels,
    )
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#FFFFFF"/>',
        *body,
        "</svg>",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def normalized_region_key(value: object) -> str:
    name = Path(clean(value).replace("\\", "/")).name.casefold()
    name = re.sub(r"\.gbk_region_\d+$", "", name)
    return re.sub(r"\.gbk$", "", name)


def load_region_taxon_groups(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    first = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    delimiter = "," if first and "," in first[0] and "\t" not in first[0] else "\t"
    mapping: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle, delimiter=delimiter):
            key = normalized_region_key(
                row.get("staged_gbk") or row.get("bigscape_gbk") or row.get("GBK")
            )
            taxon = clean(row.get("taxon_group")).casefold()
            if not key or taxon not in CHART_ROWS_BY_TAXON:
                continue
            if key in mapping and mapping[key] != taxon:
                raise ValueError(
                    f"Conflicting taxon assignments for staged BiG-SCAPE GBK: {key}"
                )
            mapping[key] = taxon
    return mapping


def assign_complete_taxon_groups(
    nodes: dict[str, network.NodeRecord],
    annotation_table: Path | None,
    region_crosswalk: Path | None,
) -> list[str]:
    warnings: list[str] = []
    annotated, annotation_warnings = network.load_taxon_groups(annotation_table)
    warnings.extend(annotation_warnings)
    warnings.extend(network.assign_taxon_groups(nodes, annotated))
    region_taxa = load_region_taxon_groups(region_crosswalk)
    matched = 0
    for node in nodes.values():
        if node.is_mibig:
            continue
        taxon = region_taxa.get(normalized_region_key(node.gbk)) or region_taxa.get(
            normalized_region_key(node.record)
        )
        if not taxon:
            continue
        if node.taxon_group in CHART_ROWS_BY_TAXON and node.taxon_group != taxon:
            raise ValueError(
                f"Conflicting canonical taxon labels for BiG-SCAPE record: {node.record}"
            )
        node.taxon_group = taxon
        matched += 1
    if region_taxa:
        warnings.append(
            f"Assigned canonical taxa from staged-region crosswalk to {matched} dataset record(s)."
        )
    return warnings


def filter_nodes_for_taxon(
    nodes: dict[str, network.NodeRecord],
    edges: list[network.EdgeRecord],
    taxon_group: str,
) -> tuple[dict[str, network.NodeRecord], list[network.EdgeRecord], list[str]]:
    selected = {
        key
        for key, node in nodes.items()
        if not node.is_mibig and node.taxon_group == taxon_group
    }
    if not selected:
        raise ValueError(
            f"No {taxon_group} dataset records were available for the taxon-specific BiG-SCAPE multipanel"
        )
    unknown = sum(
        not node.is_mibig and node.taxon_group not in CHART_ROWS_BY_TAXON
        for node in nodes.values()
    )
    keep = selected | {key for key, node in nodes.items() if node.is_mibig}
    filtered_nodes = {key: node for key, node in nodes.items() if key in keep}
    filtered_edges = [
        edge
        for edge in edges
        if edge.source in filtered_nodes and edge.target in filtered_nodes
    ]
    filtered_nodes, filtered_edges, warnings = (
        network.filter_dataset_dependent_mibig_references(
            filtered_nodes, filtered_edges, include_mibig_only=False
        )
    )
    omitted = sum(
        not node.is_mibig and node.taxon_group != taxon_group
        for node in nodes.values()
    )
    if omitted:
        warnings.append(
            f"Omitted non-{taxon_group} dataset records from taxon-specific multipanel: {omitted}"
        )
    if unknown:
        warnings.append(
            f"Dataset records without canonical taxon assignment were omitted: {unknown}"
        )
    return filtered_nodes, filtered_edges, warnings


def prepare_network_data(args: argparse.Namespace) -> tuple[network.BigscapeInputs, dict[str, network.NodeRecord], list[network.EdgeRecord], list[str]]:
    results_root = args.project_root / "data" / "results" / args.project_name
    bigscape_root = args.bigscape_root or results_root / "big_scape" / "output_files"
    annotation_table = args.annotation_table
    if annotation_table is None:
        default_annotation_table = results_root / "summary" / "candidate_bgc_gcf_crosswalk.tsv"
        annotation_table = default_annotation_table if default_annotation_table.exists() else None
    region_crosswalk = args.region_crosswalk
    if region_crosswalk is None:
        default_crosswalk = results_root / "summary_tables" / "bigscape_region_crosswalk.tsv"
        region_crosswalk = default_crosswalk if default_crosswalk.exists() else None
    metadata_path = args.metadata
    if metadata_path is None:
        metadata_name = (
            "ecobac_metadata_normalized.tsv"
            if args.taxon_group == "bacteria"
            else "ecofun_metadata_normalized.tsv"
        )
        default_metadata = results_root / "summary_tables" / metadata_name
        metadata_path = default_metadata if default_metadata.exists() else None

    warnings: list[str] = []
    inputs = network.select_bigscape_inputs(bigscape_root, args.category, args.clustering_threshold)
    annotations = network.load_annotations(inputs.annotations_path)
    if not annotations:
        warnings.append("record_annotations.tsv was not found; BGC class, organism, and MiBIG context may be incomplete.")

    nodes, node_warnings = network.load_nodes(inputs.clustering_path, annotations)
    warnings.extend(node_warnings)
    mibig_annotated_records, mibig_annotation_warnings = network.load_mibig_annotation_records(annotation_table)
    warnings.extend(mibig_annotation_warnings)
    warnings.extend(network.mark_mibig_annotations(nodes, mibig_annotated_records))
    product_labels, product_warnings = network.load_product_labels(annotation_table)
    warnings.extend(product_warnings)
    warnings.extend(network.assign_product_labels(nodes, product_labels))
    warnings.extend(
        assign_complete_taxon_groups(nodes, annotation_table, region_crosswalk)
    )
    edges, edge_warnings = network.load_edges(inputs.network_path, set(nodes), args.distance_threshold, args.similarity_threshold)
    warnings.extend(edge_warnings)
    nodes, edges, taxon_scope_warnings = filter_nodes_for_taxon(
        nodes, edges, args.taxon_group
    )
    warnings.extend(taxon_scope_warnings)

    ecology_field = args.ecology_field or (
        "ecobac_primary" if args.taxon_group == "bacteria" else "ecofun_primary"
    )
    metadata, metadata_warnings, metadata_columns = network.load_metadata(metadata_path, ecology_field, args.metadata_id_column)
    warnings.extend(metadata_warnings)
    if metadata_path is None:
        warnings.append(f"No ecology metadata table was provided or found; all sample ecology borders use '{network.UNKNOWN}'.")
    elif metadata_columns:
        warnings.append(f"Using metadata columns: id={metadata_columns[0]}, ecology={metadata_columns[1] or network.UNKNOWN}.")
    warnings.extend(network.assign_metadata_and_labels(nodes, metadata))
    if not network.has_ecology_signal(nodes):
        warnings.append("No non-unknown ecology categories found; ecology borders were omitted from the SVG.")
    if not any(node.is_mibig or node.has_mibig_annotation for node in nodes.values()):
        warnings.append("No MiBIG reference or MiBIG-annotated nodes were detected in the selected network.")

    nodes, edges, filter_warnings = network.filter_graph(nodes, edges, args.max_nodes, args.max_components)
    warnings.extend(filter_warnings)
    return inputs, nodes, edges, warnings


def shift_singletons_to_min_height(
    layout: network.LayoutResult,
    nodes: dict[str, network.NodeRecord],
    edges: list[network.EdgeRecord],
    min_height: int,
) -> None:
    if layout.height >= min_height or "singletons" not in layout.section_y:
        layout.height = max(layout.height, min_height)
        return
    singleton_start = layout.section_y["singletons"]
    singleton_ids = {
        component[0]
        for component in network.graph_components(nodes, edges)
        if len(component) == 1 and component[0] in layout.positions
    }
    slack = min_height - layout.height
    for node_id in singleton_ids:
        x, y = layout.positions[node_id]
        layout.positions[node_id] = (x, y + slack)
    layout.section_y["singletons"] = singleton_start + slack
    layout.height = min_height


def parse_formats(text: str) -> set[str]:
    formats = {part.strip().lower() for part in clean(text).split(",") if part.strip()}
    valid = {"svg", "png", "pdf"}
    invalid = formats - valid
    if invalid:
        raise ValueError(f"Unknown multipanel output format(s): {', '.join(sorted(invalid))}")
    return formats or {"svg", "png"}


def manifest_path_text(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def update_manifest(output_dir: Path, paths: Iterable[Path]) -> None:
    manifest_path = output_dir / "figure_manifest.txt"
    existing: list[str] = []
    if manifest_path.exists():
        existing = [line.strip() for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not existing or existing[0] != "figure_path":
        existing = ["figure_path", *existing]
    seen = set(existing[1:])
    for path in paths:
        text = manifest_path_text(path)
        if text not in seen:
            existing.append(text)
            seen.add(text)
    manifest_path.write_text("\n".join(existing) + "\n", encoding="utf-8")


def render_multipanel(args: argparse.Namespace) -> int:
    results_root = args.project_root / "data" / "results" / args.project_name
    output_dir = args.output_dir or results_root / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.summary_table or results_root / "summary" / "all_tools_shared_unshared_summary.csv"
    taxon_manifest = args.taxon_manifest
    if taxon_manifest is None:
        default_taxon_manifest = (
            results_root / "summary_tables" / "genome_taxon_manifest.tsv"
        )
        taxon_manifest = (
            default_taxon_manifest if default_taxon_manifest.exists() else None
        )
    sample_display_labels = load_sample_display_labels(
        taxon_manifest, args.taxon_group
    )
    formats = parse_formats(args.formats)
    warnings: list[str] = []
    prefix = args.prefix or f"{args.taxon_group}_big_scape_multipanel"
    genomes, _ = count_matrix(summary_path, args.taxon_group)
    if not genomes:
        raise ValueError(
            f"No {args.taxon_group} BGC/GCF summary rows were available for the taxon-specific multipanel"
        )

    chart_svg_path = output_dir / "gcf_calls_by_tool_category.svg"
    written: list[Path] = []
    if not args.no_standalone_chart:
        write_count_chart_svg(
            chart_svg_path,
            summary_path,
            warnings,
            args.taxon_group,
            sample_display_labels,
        )
        written.append(chart_svg_path)

    inputs, nodes, edges, network_warnings = prepare_network_data(args)
    warnings.extend(network_warnings)

    chart_x = 46.0
    chart_y = 24.0
    chart_w = 520.0
    left_column_w = 560.0
    margin = 36.0
    gap = 34.0
    network_column_x = margin + left_column_w + gap
    reserved_top_left = (left_column_w, 100000.0)
    layout = network.build_layout(
        nodes,
        edges,
        args.canvas_width,
        args.layout_iterations,
        reserved_top_left=reserved_top_left,
        combine_connected_components=True,
        network_content_width=1710.0,
        top_margin=78.0,
    )
    shift_singletons_to_min_height(layout, nodes, edges, args.min_height)
    chart_h = chart_height_for_summary(summary_path, args.taxon_group)
    layout.height = max(layout.height, int(math.ceil(chart_y + chart_h + margin)))
    layout.legend_x = layout.section_right + 52.0
    layout.width = min(layout.width, int(math.ceil(layout.legend_x + 520.0 + margin)))

    body_lines = [
        svg_text(chart_x - 10, 42, "A", 22, "700"),
        svg_text(network_column_x - 44, 42, "B", 22, "700"),
        svg_text(
            network_column_x,
            42,
            f"Connected {'fungal' if args.taxon_group == 'fungi' else 'bacterial'} GCFs",
            18,
            "700",
        ),
        *chart_lines(
            summary_path,
            chart_x,
            chart_y,
            chart_w,
            chart_h,
            warnings,
            args.taxon_group,
            title_anchor="start",
            title_x=chart_x + 34.0,
            sample_display_labels=sample_display_labels,
        ),
    ]

    base = output_dir / prefix
    svg_path = base.with_suffix(".svg")
    taxon_label = "Fungal" if args.taxon_group == "fungi" else "Bacterial"
    genome_label = "genome" if len(genomes) == 1 else "genomes"
    network.render_svg(
        svg_path,
        nodes,
        edges,
        layout,
        inputs,
        pre_body_lines=body_lines,
        section_titles={"large": None, "medium_small": None},
        section_x=network_column_x,
        svg_title=f"{taxon_label} BGC and GCF multipanel",
        svg_description=(
            f"Two-panel summary for {len(genomes)} {taxon_label.lower()} {genome_label}. "
            "Panel A compares BGC and GCF counts by tool and broad biosynthetic class. "
            f"Panel B shows a BiG-SCAPE clustering network with {len(nodes)} nodes and "
            f"{len(edges)} similarity edges; node fill denotes broad BGC class, labels "
            "identify genomes, and MiBIG markers indicate reference context."
        ),
        sample_display_labels=sample_display_labels,
    )

    written.append(svg_path)
    if "png" in formats:
        png_path = base.with_suffix(".png")
        network.convert_svg_with_cairosvg(svg_path, png_path, "png", warnings)
        if png_path.exists():
            written.append(png_path)
    if "pdf" in formats:
        pdf_path = base.with_suffix(".pdf")
        network.convert_svg_with_cairosvg(svg_path, pdf_path, "pdf", warnings)
        if pdf_path.exists():
            written.append(pdf_path)

    warning_path = output_dir / f"{prefix}_warnings.txt"
    unique_warnings = list(dict.fromkeys(warnings))
    if not args.no_warnings_file:
        warning_path.write_text("\n".join(unique_warnings) + ("\n" if unique_warnings else ""), encoding="utf-8")
    if not args.no_manifest:
        update_manifest(output_dir, written)

    if not args.no_standalone_chart:
        print(f"Wrote BGC/GCF count SVG: {chart_svg_path}")
    print(f"Wrote BiG-SCAPE multipanel SVG: {svg_path}")
    if unique_warnings and not args.no_warnings_file:
        print(f"Wrote warnings: {warning_path}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a ClusterWeave BiG-SCAPE multipanel figure.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--project-name", default="clusterweave")
    parser.add_argument("--bigscape-root", type=Path, default=None, help="BiG-SCAPE root, output_files root, or c-threshold run directory.")
    parser.add_argument("--metadata", type=Path, default=None, help="Optional ecology metadata TSV/CSV.")
    parser.add_argument("--annotation-table", type=Path, default=None, help="Optional ClusterWeave summary table with MiBIG/BGC accession annotations.")
    parser.add_argument("--region-crosswalk", type=Path, default=None, help="Canonical staged-region crosswalk with taxon_group labels.")
    parser.add_argument("--summary-table", type=Path, default=None, help="Summary CSV with entity_type=BGC and entity_type=GCF rows.")
    parser.add_argument("--taxon-manifest", type=Path, default=None, help="Canonical genome taxon manifest used for provenance-aware display labels.")
    parser.add_argument("--taxon-group", choices=sorted(CHART_ROWS_BY_TAXON), required=True)
    parser.add_argument("--metadata-id-column", default="", help="Metadata ID column. Defaults to sample_id, fungal_id, genome_id_current, genome, or isolate.")
    parser.add_argument("--ecology-field", default="", help="Metadata ecology column. Defaults to ecofun_primary or ecobac_primary by taxon.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Defaults to data/results/<project-name>/figures.")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--category", default="mix", help="BiG-SCAPE category directory to render. Defaults to mix when present.")
    parser.add_argument("--clustering-threshold", default="0.3", help="BiG-SCAPE c-threshold label to select, for example 0.3.")
    parser.add_argument("--distance-threshold", type=float, default=None, help="Optional maximum BiG-SCAPE distance for displayed edges.")
    parser.add_argument("--similarity-threshold", type=float, default=None, help="Optional minimum displayed similarity, computed as 1 - distance.")
    parser.add_argument("--formats", default="svg,png", help="Comma-separated outputs: svg,png,pdf.")
    parser.add_argument("--max-nodes", type=int, default=0, help="Optional readability cap. 0 keeps all nodes.")
    parser.add_argument("--max-components", type=int, default=0, help="Optional readability cap. 0 keeps all components.")
    parser.add_argument("--include-mibig-only", action="store_true", help="Keep MiBIG references even when their family has no dataset records.")
    parser.add_argument("--canvas-width", type=int, default=DEFAULT_CANVAS_WIDTH)
    parser.add_argument("--min-height", type=int, default=DEFAULT_MIN_HEIGHT)
    parser.add_argument("--layout-iterations", type=int, default=80)
    parser.add_argument("--no-standalone-chart", action="store_true", help="Do not write gcf_calls_by_tool_category.svg.")
    parser.add_argument("--no-warnings-file", action="store_true", help="Do not write the auxiliary warnings text file.")
    parser.add_argument("--no-manifest", action="store_true", help="Do not update figure_manifest.txt.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return render_multipanel(args)


if __name__ == "__main__":
    raise SystemExit(main())
