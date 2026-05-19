#!/usr/bin/env python3
"""Render antiSMASH/FunBGCeX BGC scaffold overlap figures."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

import render_bigscape_multipanel as multipanel
import render_bigscape_network as network


CLASS_ORDER = multipanel.CHART_CLASSES
CLASS_COLORS = multipanel.CHART_COLORS
TOOL_KEYS = ("antismash", "funbgcex")
TOOL_ORDER = set(TOOL_KEYS)
TOOL_LABELS = {"antismash": "antiSMASH", "funbgcex": "FunBGCeX"}
STATUS_COLORS = {
    "shared": "#4A4A4A",
    "antismash_only": "#2F7FB8",
    "funbgcex_only": "#E58A1F",
}
FONT_FAMILY = "Arial, Helvetica, sans-serif"


def clean(value: object) -> str:
    return network.clean(value)


def parse_formats(text: str) -> set[str]:
    formats = {part.strip().lower() for part in clean(text).split(",") if part.strip()}
    valid = {"svg", "png"}
    invalid = formats - valid
    if invalid:
        raise ValueError(f"Unknown BGC overlap output format(s): {', '.join(sorted(invalid))}")
    return formats or {"svg", "png"}


def svg_text(
    x: float,
    y: float,
    text: str,
    size: int | float,
    weight: str = "400",
    anchor: str = "start",
    fill: str = "#222222",
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT_FAMILY}" '
        f'font-size="{float(size):g}" font-weight="{weight}" text-anchor="{anchor}" fill="{fill}">'
        f"{escape(text)}</text>"
    )


def svg_sample_label(x: float, y: float, sample_id: str, size: int | float, weight: str = "700") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT_FAMILY}" '
        f'font-size="{float(size):g}" font-weight="{weight}" text-anchor="start" fill="#222222">'
        f"{network.svg_sample_name_tspans(sample_id)}</text>"
    )


def read_summary(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def parse_count(value: object) -> float:
    try:
        return max(0.0, float(clean(value) or 0))
    except ValueError:
        return 0.0


def overlap_counts(summary_path: Path) -> tuple[list[str], dict[str, dict[str, dict[str, float]]]]:
    rows = read_summary(summary_path)
    genomes: list[str] = []
    shared_by_tool: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    unshared_by_tool: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    for row in rows:
        if clean(row.get("entity_type")).upper() != "BGC":
            continue
        tool = clean(row.get("tool")).casefold()
        if tool not in TOOL_ORDER:
            continue
        genome = clean(row.get("genome"))
        if not genome:
            continue
        if genome not in genomes:
            genomes.append(genome)
        category = multipanel.normalize_chart_class(clean(row.get("class_norm")))
        shared_by_tool[genome][tool][category] += parse_count(row.get("shared_count"))
        unshared_by_tool[genome][tool][category] += parse_count(row.get("unshared_count"))

    matrix: dict[str, dict[str, dict[str, float]]] = {}
    for genome in genomes:
        shared: dict[str, float] = defaultdict(float)
        antismash_only: dict[str, float] = defaultdict(float)
        funbgcex_only: dict[str, float] = defaultdict(float)
        unshared: dict[str, float] = defaultdict(float)
        for category in CLASS_ORDER:
            # Shared calls are represented once per tool in the summary; count the overlap once.
            shared[category] = max(shared_by_tool[genome][tool].get(category, 0.0) for tool in TOOL_KEYS)
            antismash_only[category] = unshared_by_tool[genome]["antismash"].get(category, 0.0)
            funbgcex_only[category] = unshared_by_tool[genome]["funbgcex"].get(category, 0.0)
            unshared[category] = antismash_only[category] + funbgcex_only[category]
        matrix[genome] = {
            "shared": {category: shared.get(category, 0.0) for category in CLASS_ORDER},
            "antismash_only": {category: antismash_only.get(category, 0.0) for category in CLASS_ORDER},
            "funbgcex_only": {category: funbgcex_only.get(category, 0.0) for category in CLASS_ORDER},
            "unshared": {category: unshared.get(category, 0.0) for category in CLASS_ORDER},
        }
    return genomes, matrix


def percent_label(value: float, total: float) -> str:
    if total <= 0:
        return "0%"
    return f"{round(value / total * 100):.0f}%"


def count_label(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 1e-6:
        return str(int(rounded))
    return f"{value:g}"


def tool_only_label(tool_key: str) -> str:
    base = TOOL_LABELS.get(tool_key.replace("_only", ""), tool_key)
    if tool_key.endswith("_only"):
        return f"{base}-only"
    return base


def rect(
    x: float,
    y: float,
    width: float,
    height: float,
    fill: str,
    stroke: str = "#FFFFFF",
    extra: str = "",
) -> str:
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(0.0, width):.1f}" height="{height:.1f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1"{extra}/>'
    )


def polar_point(cx: float, cy: float, radius: float, angle_degrees: float) -> tuple[float, float]:
    radians = math.radians(angle_degrees - 90.0)
    return cx + radius * math.cos(radians), cy + radius * math.sin(radians)


def pie_slice_path(cx: float, cy: float, radius: float, start_angle: float, end_angle: float) -> str:
    start_x, start_y = polar_point(cx, cy, radius, start_angle)
    end_x, end_y = polar_point(cx, cy, radius, end_angle)
    large_arc = 1 if end_angle - start_angle > 180.0 else 0
    return (
        f"M {cx:.1f} {cy:.1f} L {start_x:.1f} {start_y:.1f} "
        f"A {radius:.1f} {radius:.1f} 0 {large_arc} 1 {end_x:.1f} {end_y:.1f} Z"
    )


def svg_label_text(
    x: float,
    y: float,
    text: str,
    size: int | float = 10,
    fill: str = "#111111",
    anchor: str = "middle",
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT_FAMILY}" '
        f'font-size="{float(size):g}" font-weight="700" text-anchor="{anchor}" '
        f'fill="{fill}">{escape(text)}</text>'
    )


def readable_text_color(fill: str) -> str:
    value = fill.lstrip("#")
    if len(value) != 6:
        return "#111111"
    try:
        red = int(value[0:2], 16)
        green = int(value[2:4], 16)
        blue = int(value[4:6], 16)
    except ValueError:
        return "#111111"
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255.0
    return "#111111" if luminance >= 0.58 else "#FFFFFF"


def agreement_pie(
    cx: float,
    cy: float,
    radius: float,
    shared_total: float,
    antismash_total: float,
    funbgcex_total: float,
) -> tuple[list[str], dict[str, dict[str, float]]]:
    union_total = shared_total + antismash_total + funbgcex_total
    lines: list[str] = [
        f'<g data-chart="agreement-pie" data-total="{escape(count_label(union_total))}" '
        f'data-center-x="{cx:.1f}" data-center-y="{cy:.1f}" data-radius="{radius:.1f}">'
    ]
    geometry: dict[str, dict[str, float]] = {}
    if union_total <= 0:
        lines.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius:.1f}" fill="#F4F4F4" '
            f'stroke="#D0D0D0" stroke-width="1"/>'
        )
        lines.append(svg_text(cx, cy + 5.0, "No BGC calls", 12, "700", "middle", "#777777"))
        lines.append("</g>")
        return lines, geometry

    start_angle = 150.0
    for key, value, label, text_fill in [
        ("shared", shared_total, "Shared", "#FFFFFF"),
        ("antismash_only", antismash_total, "antiSMASH-only", "#FFFFFF"),
        ("funbgcex_only", funbgcex_total, "FunBGCeX-only", "#111111"),
    ]:
        if value <= 0:
            continue
        span = 360.0 * value / union_total
        end_angle = start_angle + span
        mid_angle = start_angle + span / 2.0
        explode = radius * 0.28 if key.endswith("_only") else 0.0
        slice_cx, slice_cy = polar_point(cx, cy, explode, mid_angle) if explode else (cx, cy)
        percent = percent_label(value, union_total)
        bgc_unit = "BGC" if abs(value - 1.0) < 1e-6 else "BGCs"
        attrs = (
            f'data-segment="{key}" data-value="{escape(count_label(value))}" '
            f'data-percent="{escape(percent)}" data-exploded="{str(bool(explode)).lower()}"'
        )
        title = f"{label}: {count_label(value)} {bgc_unit}; {percent} of genome union"
        if span >= 359.99:
            lines.append(
                f'<circle cx="{slice_cx:.1f}" cy="{slice_cy:.1f}" r="{radius:.1f}" '
                f'fill="{STATUS_COLORS[key]}" stroke="#FFFFFF" stroke-width="1.2" {attrs}>'
                f'<title>{escape(title)}</title></circle>'
            )
        else:
            lines.append(
                f'<path d="{pie_slice_path(slice_cx, slice_cy, radius, start_angle, end_angle)}" '
                f'fill="{STATUS_COLORS[key]}" stroke="#FFFFFF" stroke-width="1.2" {attrs}>'
                f'<title>{escape(title)}</title></path>'
            )
        if span >= 24.0:
            label_x, label_y = polar_point(slice_cx, slice_cy, radius * 0.58, mid_angle)
            label_size = 17 if key == "shared" else 14
            lines.append(svg_label_text(label_x, label_y + 4.8, percent, label_size, text_fill))
        if key == "shared":
            radial_x, _ = polar_point(slice_cx, slice_cy, radius * 1.08, mid_angle)
            shared_label_x = min(max(radial_x, cx - radius * 0.66), cx + radius * 0.66)
            lines.append(
                svg_text(
                    shared_label_x,
                    cy - radius - 11.0,
                    f"Shared (n = {count_label(value)})",
                    12,
                    "700",
                    "middle",
                    "#4A4A4A",
                )
            )
        geometry[key] = {
            "cx": slice_cx,
            "cy": slice_cy,
            "radius": radius,
            "start_angle": start_angle,
            "end_angle": end_angle,
            "mid_angle": mid_angle,
            "value": value,
        }
        start_angle = end_angle

    lines.append("</g>")
    return lines, geometry


def slice_connector_point(slice_geometry: dict[str, float]) -> tuple[float, float]:
    radius = slice_geometry["radius"] + 5.0
    return polar_point(slice_geometry["cx"], slice_geometry["cy"], radius, slice_geometry["mid_angle"])


def slice_to_bar_connectors(
    slice_geometry: dict[str, float],
    chart_x: float,
    chart_y: float,
    chart_height: float,
    color: str,
) -> list[str]:
    mid_x, mid_y = slice_connector_point(slice_geometry)
    target_x = chart_x - 12.0
    target_mid_y = chart_y + chart_height / 2.0
    bend_x = mid_x + (target_x - mid_x) * 0.68
    bend_y = target_mid_y
    incoming_dx = bend_x - mid_x
    incoming_dy = bend_y - mid_y
    incoming_distance = math.hypot(incoming_dx, incoming_dy)
    outgoing_distance = max(0.0, target_x - bend_x)
    curve_radius = max(0.0, min(18.0, incoming_distance * 0.35, outgoing_distance * 0.45))
    if curve_radius > 0.0 and incoming_distance > 0.0 and outgoing_distance > 0.0:
        curve_start_x = bend_x - incoming_dx / incoming_distance * curve_radius
        curve_start_y = bend_y - incoming_dy / incoming_distance * curve_radius
        curve_end_x = bend_x + curve_radius
        curve_end_y = bend_y
        path_d = (
            f"M {mid_x:.1f} {mid_y:.1f} L {curve_start_x:.1f} {curve_start_y:.1f} "
            f"Q {bend_x:.1f} {bend_y:.1f} {curve_end_x:.1f} {curve_end_y:.1f} "
            f"L {target_x:.1f} {target_mid_y:.1f}"
        )
    else:
        path_d = (
            f"M {mid_x:.1f} {mid_y:.1f} L {bend_x:.1f} {bend_y:.1f} "
            f"L {target_x:.1f} {target_mid_y:.1f}"
        )
    return [
        (
            f'<path d="{path_d}" '
            f'fill="none" stroke="{color}" stroke-width="1.5" stroke-opacity="0.74" '
            f'stroke-dasharray="4 4" stroke-linecap="round" data-connector="slice-to-bar" '
            f'data-curve="curved-bend" data-bend-x="{bend_x:.1f}" data-bend-y="{bend_y:.1f}"/>'
        ),
    ]


def nonzero_class_items(counts: dict[str, float]) -> list[tuple[str, float]]:
    return [(category, counts.get(category, 0.0)) for category in CLASS_ORDER if counts.get(category, 0.0) > 0]


def class_horizontal_chart_height(row_count: int) -> float:
    row_h = 16.0
    row_gap = 6.0
    axis_space = 6.0
    top_space = 8.0
    rows_h = max(1, row_count) * row_h + max(0, row_count - 1) * row_gap
    return top_space + rows_h + axis_space


def percent_axis_label(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 1e-6:
        return f"{int(rounded)}%"
    return f"{value:g}%"


def count_axis_max(value: float) -> float:
    if value <= 0:
        return 1.0
    tick_step = multipanel.nice_tick_step(value, target_ticks=4)
    return max(tick_step, math.ceil(value / tick_step) * tick_step)


def class_horizontal_bar_chart(
    x: float,
    y: float,
    width: float,
    counts: dict[str, float],
    denominator: float,
    tool_key: str,
    x_max_count: float,
) -> tuple[list[str], float, float]:
    total = sum(counts.get(category, 0.0) for category in CLASS_ORDER)
    lines: list[str] = []
    if denominator <= 0 or total <= 0:
        return lines, 0.0, 0.0
    items = nonzero_class_items(counts)
    if not items:
        return lines, 0.0, 0.0
    total_label = percent_label(total, denominator)
    chart_h = class_horizontal_chart_height(len(items))
    top_space = 8.0
    row_h = 16.0
    row_gap = 6.0
    label_w = 72.0
    right = 4.0
    plot_x = x + label_w
    plot_y = y + top_space
    plot_w = max(1.0, width - label_w - right)
    x_max_count = max(1.0, x_max_count)
    lines.append(
        f'<g data-chart="class-horizontal-bars" data-orientation="horizontal" data-tool="{tool_key}" '
        f'data-total="{escape(count_label(total))}" data-total-percent="{escape(total_label)}" '
        f'data-x-axis="raw-count" data-scale-max="{escape(count_label(x_max_count))}">'
    )
    lines.append(svg_text(plot_x, y - 10.0, f"{tool_only_label(tool_key)} (n = {count_label(total)})", 12, "700", fill=STATUS_COLORS[tool_key]))

    for index, (category, value) in enumerate(items):
        bar_y = plot_y + index * (row_h + row_gap)
        value_label = count_label(value)
        union_percent = percent_label(value, denominator)
        tool_percent = percent_label(value, total)
        bar_w = max(0.0, plot_w * value / x_max_count)
        fill = CLASS_COLORS.get(category, CLASS_COLORS["other"])
        bgc_unit = "BGC" if abs(value - 1.0) < 1e-6 else "BGCs"
        title = (
            f"{tool_only_label(tool_key)} {category}: "
            f"{value_label} {bgc_unit}; {union_percent} of genome union"
        )
        attrs = (
            f'data-tool="{tool_key}" data-class="{escape(category)}" '
            f'data-value="{escape(value_label)}" data-percent="{escape(union_percent)}" '
            f'data-tool-percent="{escape(tool_percent)}"'
        )
        lines.append(svg_text(plot_x - 8.0, bar_y + row_h / 2.0 + 4.0, category, 10, "700", "end"))
        lines.append(
            f'<rect x="{plot_x:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" height="{row_h:.1f}" '
            f'fill="{fill}" stroke="#FFFFFF" stroke-width="0.8" {attrs}>'
            f'<title>{escape(title)}</title></rect>'
        )
        lines.append(svg_label_text(plot_x + bar_w + 5.0, bar_y + row_h / 2.0 + 3.7, union_percent, 9, "#111111", "start"))
    lines.append("</g>")
    return lines, total, chart_h


def tool_chart_height(counts: dict[str, float]) -> float:
    if sum(counts.get(category, 0.0) for category in CLASS_ORDER) <= 0:
        return 0.0
    items = nonzero_class_items(counts)
    if not items:
        return 0.0
    return class_horizontal_chart_height(len(items))


def tool_chart_center_offsets(
    shared_total: float,
    antismash_total: float,
    funbgcex_total: float,
    antismash_chart_h: float,
    funbgcex_chart_h: float,
    agreement_cx: float,
    agreement_radius: float,
) -> dict[str, float]:
    _, probe_geometry = agreement_pie(
        agreement_cx,
        0.0,
        agreement_radius,
        shared_total,
        antismash_total,
        funbgcex_total,
    )
    desired_centers: dict[str, float] = {}
    chart_heights = {
        "antismash_only": antismash_chart_h,
        "funbgcex_only": funbgcex_chart_h,
    }
    for key, chart_h in chart_heights.items():
        if chart_h <= 0 or key not in probe_geometry:
            continue
        _, connector_y = slice_connector_point(probe_geometry[key])
        chart_nudge = -16.0 if key == "antismash_only" else 16.0
        desired_centers[key] = connector_y + chart_nudge

    min_gap = 30.0
    if "antismash_only" in desired_centers and "funbgcex_only" in desired_centers:
        minimum_fun_center = (
            desired_centers["antismash_only"]
            + antismash_chart_h / 2.0
            + funbgcex_chart_h / 2.0
            + min_gap
        )
        if desired_centers["funbgcex_only"] < minimum_fun_center:
            midpoint = (desired_centers["antismash_only"] + desired_centers["funbgcex_only"]) / 2.0
            half = (antismash_chart_h + funbgcex_chart_h) / 4.0 + min_gap / 2.0
            desired_centers["antismash_only"] = midpoint - half
            desired_centers["funbgcex_only"] = midpoint + half
    return desired_centers


def bgc_overlap_row_layouts(
    genomes: list[str],
    matrix: dict[str, dict[str, dict[str, float]]],
    agreement_cx: float,
    agreement_radius: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for genome in genomes:
        shared_counts = matrix[genome]["shared"]
        antismash_counts = matrix[genome]["antismash_only"]
        funbgcex_counts = matrix[genome]["funbgcex_only"]
        shared_total = sum(shared_counts.values())
        antismash_total = sum(antismash_counts.values())
        funbgcex_total = sum(funbgcex_counts.values())
        antismash_chart_h = tool_chart_height(antismash_counts)
        funbgcex_chart_h = tool_chart_height(funbgcex_counts)
        chart_center_offsets = tool_chart_center_offsets(
            shared_total,
            antismash_total,
            funbgcex_total,
            antismash_chart_h,
            funbgcex_chart_h,
            agreement_cx,
            agreement_radius,
        )

        above_center = agreement_radius + 32.0
        below_center = agreement_radius + 12.0
        for key, chart_h in {
            "antismash_only": antismash_chart_h,
            "funbgcex_only": funbgcex_chart_h,
        }.items():
            if chart_h <= 0 or key not in chart_center_offsets:
                continue
            offset = chart_center_offsets[key]
            above_center = max(above_center, chart_h / 2.0 - offset + 10.0)
            below_center = max(below_center, offset + chart_h / 2.0 + 10.0)

        rows.append(
            {
                "genome": genome,
                "shared_counts": shared_counts,
                "antismash_counts": antismash_counts,
                "funbgcex_counts": funbgcex_counts,
                "shared_total": shared_total,
                "antismash_total": antismash_total,
                "funbgcex_total": funbgcex_total,
                "antismash_chart_h": antismash_chart_h,
                "funbgcex_chart_h": funbgcex_chart_h,
                "chart_center_offsets": chart_center_offsets,
                "height": math.ceil(max(236.0, above_center + below_center)),
                "center_offset": above_center,
            }
        )
    return rows


def render_svg(path: Path, summary_path: Path) -> None:
    genomes, matrix = overlap_counts(summary_path)
    top = 76.0
    bottom = 42.0
    row_gap = 28.0
    label_x = 44.0
    agreement_cx = 420.0
    detail_x = 680.0
    detail_w = 216.0
    width = int(detail_x + detail_w + 78.0)
    agreement_radius = 100.0
    row_layouts = bgc_overlap_row_layouts(genomes, matrix, agreement_cx, agreement_radius)
    content_h = sum(float(row["height"]) for row in row_layouts) + row_gap * max(0, len(row_layouts) - 1)
    height = int(max(220.0, top + content_h + bottom))

    global_max_class_count = 1.0
    for genome in genomes:
        if genome not in matrix:
            continue
        for key in ("antismash_only", "funbgcex_only"):
            for value in matrix[genome][key].values():
                global_max_class_count = max(global_max_class_count, value)
    x_max_count = count_axis_max(global_max_class_count)

    lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#FFFFFF"/>',
        svg_text(label_x, 42.0, "BGC scaffold overlap between antiSMASH and FunBGCeX", 20, "700"),
    ]

    if not genomes:
        lines.append(svg_text(label_x, 112.0, "No BGC overlap data available", 14, "700"))
    row_top = top
    for index, row in enumerate(row_layouts):
        genome = str(row["genome"])
        center_y = row_top + float(row["center_offset"])
        if index > 0:
            sep_y = row_top - row_gap / 2.0
            lines.append(f'<line x1="{label_x:.1f}" y1="{sep_y:.1f}" x2="{width - 44:.1f}" y2="{sep_y:.1f}" stroke="#D2D2D2" stroke-width="0.9" stroke-dasharray="2 3"/>')
        lines.append(svg_sample_label(label_x, center_y + 5.0, genome, 15))

        shared_counts = row["shared_counts"]
        antismash_counts = row["antismash_counts"]
        funbgcex_counts = row["funbgcex_counts"]
        shared_total = float(row["shared_total"])
        antismash_total = float(row["antismash_total"])
        funbgcex_total = float(row["funbgcex_total"])
        union_total = shared_total + antismash_total + funbgcex_total

        pie_lines, pie_geometry = agreement_pie(
            agreement_cx,
            center_y,
            agreement_radius,
            shared_total,
            antismash_total,
            funbgcex_total,
        )
        lines.extend(pie_lines)

        antismash_chart_h = float(row["antismash_chart_h"])
        funbgcex_chart_h = float(row["funbgcex_chart_h"])
        chart_center_offsets = row["chart_center_offsets"]
        detail_rows = []
        if "antismash_only" in chart_center_offsets:
            chart_y = center_y + float(chart_center_offsets["antismash_only"]) - antismash_chart_h / 2.0
            detail_rows.append(("antismash_only", antismash_counts, chart_y))
        if "funbgcex_only" in chart_center_offsets:
            chart_y = center_y + float(chart_center_offsets["funbgcex_only"]) - funbgcex_chart_h / 2.0
            detail_rows.append(("funbgcex_only", funbgcex_counts, chart_y))
        for key, counts, chart_y in detail_rows:
            if key not in pie_geometry:
                continue
            chart_lines, total, chart_h = class_horizontal_bar_chart(
                detail_x,
                chart_y,
                detail_w,
                counts,
                union_total,
                key,
                x_max_count,
            )
            if total <= 0:
                continue
            lines.extend(slice_to_bar_connectors(pie_geometry[key], detail_x, chart_y, chart_h, STATUS_COLORS[key]))
            lines.extend(chart_lines)
        row_top += float(row["height"]) + row_gap

    lines.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render shared/unshared BGC overlap figures.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--project-name", default="clusterweave")
    parser.add_argument("--summary-table", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None, help="Defaults to Data/Results/<project-name>/figures.")
    parser.add_argument("--prefix", default="bgc_overlap")
    parser.add_argument("--formats", default="svg,png", help="Comma-separated outputs: svg,png.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    results_root = args.project_root / "Data" / "Results" / args.project_name
    summary_path = args.summary_table or results_root / "summary" / "all_tools_shared_unshared_summary.csv"
    output_dir = args.output_dir or results_root / "figures"
    formats = parse_formats(args.formats)

    base = output_dir / args.prefix
    svg_path = base.with_suffix(".svg")
    render_svg(svg_path, summary_path)
    print(f"Wrote BGC overlap SVG: {svg_path}")
    if "png" in formats:
        warnings: list[str] = []
        png_path = base.with_suffix(".png")
        network.convert_svg_with_cairosvg(svg_path, png_path, "png", warnings)
        if png_path.exists():
            print(f"Wrote BGC overlap PNG: {png_path}")
        for warning in warnings:
            print(warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
