#!/usr/bin/env python3
"""Post-process clinker HTML outputs for cleaner labels and legends."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "na", "n/a", "none", "-"}:
        return ""
    return text


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def js_bool(value: bool) -> str:
    return "true" if value else "false"


def read_tsv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def resolve_manifest_path(raw: str) -> Path:
    text = clean(raw)
    if not text:
        return Path()
    candidate = Path(text)
    if candidate.exists():
        return candidate

    wsl_match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", text)
    if wsl_match:
        drive = f"{wsl_match.group(1).upper()}:"
        remainder = wsl_match.group(2).replace("/", "\\")
        windows_candidate = Path(f"{drive}\\{remainder}")
        if windows_candidate.exists():
            return windows_candidate

    windows_match = re.match(r"^([a-zA-Z]):[\\/](.*)$", text)
    if windows_match:
        drive = windows_match.group(1).lower()
        remainder = windows_match.group(2).replace("\\", "/")
        wsl_candidate = Path(f"/mnt/{drive}/{remainder}")
        if wsl_candidate.exists():
            return wsl_candidate

    return candidate


def parse_html_payload(path: Path) -> tuple[str, dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    start_marker = "const data="
    end_marker = ";function serialise"
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker)
    payload = json.loads(text[start:end])
    return text[:start], payload, text[end:]


def write_html_payload(path: Path, prefix: str, payload: dict[str, object], suffix: str) -> None:
    text = prefix + json.dumps(payload) + suffix
    text = apply_html_defaults(text)
    path.write_text(text, encoding="utf-8")


def prettify_genome_name(raw: str) -> str:
    text = clean(raw)
    if not text:
        return ""
    text = text.replace("_sp._", " sp. ")
    text = text.replace("_sp_", " sp. ")
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_display_artifacts(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    text = re.sub(r"\s*\(Eurofung\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ;,")
    return text


def compact_reference_taxon(raw: str) -> str:
    text = prettify_genome_name(raw)
    if not text:
        return ""
    parts = text.split()
    if len(parts) >= 3 and parts[0] == "Candidatus":
        return " ".join(parts[:3])
    if len(parts) >= 2:
        return " ".join(parts[:2])
    return text


def parse_gbk_summary(path: Path) -> dict[str, str]:
    summary = {"source": "", "organism_display_name": "", "accession": ""}
    if not path.is_file():
        return summary
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for idx, line in enumerate(handle):
            if idx > 120:
                break
            if line.startswith("ACCESSION"):
                summary["accession"] = clean(line.split("ACCESSION", 1)[1])
            elif line.startswith("SOURCE"):
                summary["source"] = clean(line.split("SOURCE", 1)[1])
            elif "Organism Display Name ::" in line:
                summary["organism_display_name"] = clean(line.split("::", 1)[1]).replace(" v1.0", "")
    return summary


def friendly_cluster_name(row: dict[str, str]) -> str:
    if not row:
        return ""
    role = clean(row.get("role"))
    genome = clean(row.get("genome"))
    taxon_group = clean(row.get("taxon_group")).lower()
    taxon_source = clean(row.get("taxon_source")).lower()
    antismash_region = clean(row.get("antismash_region"))
    gbk_summary = parse_gbk_summary(resolve_manifest_path(clean(row.get("source_gbk_path"))))

    if role == "mibig_reference":
        organism = compact_reference_taxon(gbk_summary["source"]) or "MIBiG reference"
        accession = gbk_summary["accession"] or antismash_region or genome
        return clean(f"{organism} {accession}")

    organism = clean(row.get("organism_name"))
    if organism:
        return prettify_genome_name(organism)

    if gbk_summary["organism_display_name"]:
        return prettify_genome_name(gbk_summary["organism_display_name"])

    if gbk_summary["source"]:
        return prettify_genome_name(gbk_summary["source"])

    if (
        taxon_group == "bacteria"
        and taxon_source in {"ncbi", "ncbi_taxonomy"}
    ):
        genome = re.sub(r"^bacteria_", "", genome, flags=re.IGNORECASE)
    if genome:
        return prettify_genome_name(genome)
    return prettify_genome_name(antismash_region)


def friendly_scaffold_name(row: dict[str, str], fallback: str = "") -> str:
    scaffold = clean(row.get("scaffold_id"))
    if not scaffold:
        region = clean(row.get("antismash_region"))
        scaffold = re.sub(r"\.region\d+$", "", region, flags=re.IGNORECASE)
    scaffold = scaffold or clean(fallback)
    return prettify_genome_name(scaffold)


def order_key(row: dict[str, str]) -> int:
    try:
        return int(clean(row.get("order")) or 0)
    except ValueError:
        return 0


def simplify_text(value: str) -> str:
    text = strip_display_artifacts(value)
    if not text:
        return ""
    text = re.sub(r"^\s*(putative|probable|predicted)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"-like protein\b", " protein", text, flags=re.IGNORECASE)
    text = re.sub(r"\bdomain-containing protein\b", "domain protein", text, flags=re.IGNORECASE)
    text = re.sub(r"\bprotein protein\b", "protein", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ;,")
    return text


def simplify_identifier(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    text = re.sub(r"^(?:ncbi[_:]+)", "", text, flags=re.IGNORECASE)
    return text.rstrip(".")


def normalize_locus_name(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    return text.rstrip(".")


def is_generic_product(value: str) -> bool:
    text = simplify_text(value).lower()
    return text in {
        "",
        "hypothetical protein",
        "protein",
        "p450",
        "conserved hypothetical protein",
        "uncharacterized protein",
        "expressed protein",
    }


def simplify_gene_function(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    if ") " in text:
        text = text.split(") ", 1)[1]
    text = text.replace(":", " ")
    return simplify_text(text)


def simplify_domain(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    text = text.split("(", 1)[0]
    return simplify_text(text)


def simplify_note(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    if text.lower().startswith(("transcript_id=", "old_locus_tag=", "locus_tag=")):
        return ""
    if "GO_function:" in text:
        function_text = text.split("GO_function:", 1)[1]
        for chunk in function_text.split(";"):
            chunk = clean(chunk)
            chunk = re.sub(r"^GO:\d+\s*-\s*", "", chunk)
            chunk = re.sub(r"\[[^\]]+\]", "", chunk).strip(" -,")
            chunk = simplify_text(chunk)
            if chunk and not is_generic_product(chunk) and not chunk.lower().startswith("go:"):
                return chunk
    text = re.sub(r"GO:\d+\s*-\s*", "", text)
    text = re.sub(r"\[[^\]]+\]", "", text).strip(" -,")
    return simplify_text(text)


def truncate_label(value: str, max_len: int = 48) -> str:
    text = clean(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def gene_label_candidates(gene: dict[str, object]) -> list[tuple[int, str]]:
    names = gene.get("names", {}) or {}
    gene_name = simplify_text(names.get("gene", ""))
    product = simplify_text(names.get("product", ""))
    gene_function = simplify_gene_function(names.get("gene_functions", ""))
    domain = simplify_domain(names.get("sec_met_domain", ""))
    locus_tag = simplify_identifier(names.get("locus_tag", ""))
    protein_id = simplify_identifier(names.get("protein_id", ""))
    note = simplify_note(names.get("note", ""))

    candidates: list[tuple[int, str]] = []
    if not is_generic_product(product):
        if gene_name and gene_name.lower() not in product.lower():
            candidates.append((0, f"{gene_name} ({product})"))
        else:
            candidates.append((0, product))
    if gene_name and gene_name.lower() not in {"", "gene", "p450", "nrps", "pks"}:
        candidates.append((1, gene_name))
    if gene_function and not is_generic_product(gene_function):
        candidates.append((2, gene_function))
    if domain and not is_generic_product(domain):
        candidates.append((3, domain))
    if locus_tag:
        candidates.append((4, locus_tag))
    if protein_id:
        candidates.append((5, protein_id))
    if note and not is_generic_product(note):
        candidates.append((6, note))
    if not candidates and not is_generic_product(product):
        candidates.append((7, product))
    if not candidates:
        candidates.append((8, "hypothetical protein"))
    return candidates


def preferred_gene_label(gene: dict[str, object]) -> str:
    candidates = gene_label_candidates(gene)
    if not candidates:
        return "hypothetical protein"
    names = gene.get("names", {}) or {}
    symbol = clean(names.get("gene"))
    return truncate_label(symbol or candidates[0][1], 24)


def group_label_options(group: dict[str, object], gene_by_uid: dict[str, dict[str, object]]) -> list[str]:
    scored_candidates: list[tuple[int, int, str]] = []
    for uid in group.get("genes", []):
        gene_info = gene_by_uid.get(uid)
        if gene_info is None:
            continue
        role = clean(gene_info.get("role"))
        role_rank = 0 if role == "target" else (1 if role == "mibig_reference" else 2)
        for tier, label in gene_label_candidates(gene_info["gene"]):
            scored_candidates.append((tier, role_rank, truncate_label(label)))
    scored_candidates.sort(key=lambda item: (item[0], item[1], item[2].lower()))

    ordered: list[str] = []
    seen: set[str] = set()
    for _, _, label in scored_candidates:
        label = clean(label)
        if not label or label in seen:
            continue
        seen.add(label)
        ordered.append(label)
    return ordered


def choose_group_label(group: dict[str, object], gene_by_uid: dict[str, dict[str, object]], group_index: int) -> str:
    scored_candidates: list[tuple[int, int, str]] = []
    for uid in group.get("genes", []):
        gene_info = gene_by_uid.get(uid)
        if gene_info is None:
            continue
        role = clean(gene_info.get("role"))
        role_rank = 0 if role == "target" else (1 if role == "mibig_reference" else 2)
        for tier, label in gene_label_candidates(gene_info["gene"]):
            scored_candidates.append((tier, role_rank, label))

    if not scored_candidates:
        return f"group {group_index}"

    best_tier = min(item[0] for item in scored_candidates)
    tier_candidates = [item for item in scored_candidates if item[0] == best_tier]
    best_role = min(item[1] for item in tier_candidates)
    role_candidates = [item[2] for item in tier_candidates if item[1] == best_role]
    if not role_candidates:
        role_candidates = [item[2] for item in tier_candidates]

    counts = Counter(role_candidates)
    chosen = counts.most_common(1)[0][0]
    chosen = truncate_label(chosen)
    if is_generic_product(chosen):
        return f"{chosen} [G{group_index}]"
    return chosen


def ensure_unique_labels(
    groups: list[dict[str, object]],
    label_options_by_uid: dict[str, list[str]],
) -> None:
    used: set[str] = set()
    label_counts = Counter(clean(group.get("label")) for group in groups)
    for idx, group in enumerate(groups, start=1):
        base = clean(group.get("label")) or f"group {idx}"
        options: list[str] = []
        for candidate in [base, *label_options_by_uid.get(clean(group.get("uid")), [])]:
            candidate = clean(candidate)
            if candidate and candidate not in options:
                options.append(candidate)

        chosen = ""
        if label_counts[base] <= 1 and base not in used:
            chosen = base
        else:
            for option in options:
                if option not in used:
                    chosen = option
                    break

        if not chosen:
            suffix = 2
            chosen = base
            while chosen in used:
                chosen = f"{base} {suffix}"
                suffix += 1

        group["label"] = chosen
        used.add(chosen)


def iter_clusters(payload: dict[str, object]) -> Iterable[dict[str, object]]:
    return payload.get("clusters", [])


def normalize_gene_display_names(gene: dict[str, object]) -> None:
    names = gene.get("names")
    if not isinstance(names, dict):
        return
    for key in ["product", "gene_functions", "sec_met_domain"]:
        if key in names:
            names[key] = strip_display_artifacts(names.get(key, ""))
    for key in ["locus_tag", "protein_id"]:
        if key in names:
            names[key] = simplify_identifier(names.get(key, ""))
    if "note" in names:
        note = clean(names.get("note", ""))
        if note.lower().startswith("transcript_id="):
            names["note"] = ""
        else:
            names["note"] = strip_display_artifacts(note)


def replace_input_tag(text: str, input_id: str, transform) -> str:
    pattern = rf"<input\b[^>]*\bid=\"{re.escape(input_id)}\"[^>]*>"
    return re.sub(pattern, lambda match: transform(match.group(0)), text)


def set_tag_attribute(tag: str, attr: str, value: str) -> str:
    if re.search(rf'\b{re.escape(attr)}="[^"]*"', tag):
        return re.sub(rf'(\b{re.escape(attr)}=")[^"]*(")', rf"\g<1>{value}\2", tag)
    return tag[:-1] + f' {attr}="{value}">'


def set_checkbox_state(text: str, input_id: str, checked: bool) -> str:
    def transform(tag: str) -> str:
        tag = re.sub(r"\schecked(?=[\s>])", "", tag)
        if checked:
            tag = tag[:-1] + " checked>"
        return tag

    return replace_input_tag(text, input_id, transform)


def set_input_defaults(text: str, input_id: str, value: int) -> str:
    def transform(tag: str) -> str:
        tag = set_tag_attribute(tag, "value", str(value))
        tag = set_tag_attribute(tag, "default", str(value))
        return tag

    return replace_input_tag(text, input_id, transform)


def apply_html_defaults(text: str) -> str:
    scale_factor = env_int("CLINKER_SCALE_FACTOR", 12)
    vertical_spacing = env_int("CLINKER_VERTICAL_SPACING", 70)
    align_labels = env_bool("CLINKER_ALIGN_LABELS", True)
    hide_locus_coordinates = env_bool("CLINKER_HIDE_COORDINATES", True)
    show_gene_labels = env_bool("CLINKER_SHOW_GENE_LABELS", True)
    use_group_colour = env_bool("CLINKER_USE_GROUP_COLOUR", True)
    show_link_labels = env_bool("CLINKER_SHOW_LINK_LABELS", False)

    config_block = (
        ".config({\n"
        f"      plot: {{scaleFactor: {scale_factor}, transitionDuration: 0}},\n"
        "      cluster: {\n"
        "        lociFontSize: 11,\n"
        f"        spacing: {vertical_spacing},\n"
        f"        alignLabels: {js_bool(align_labels)},\n"
        f"        hideLocusCoordinates: {js_bool(hide_locus_coordinates)},\n"
        "      },\n"
        "      gene: {\n"
        "        label: {\n"
        f"          show: {js_bool(show_gene_labels)},\n"
        "          rotation: 45,\n"
        "          fontSize: 11,\n"
        "        },\n"
        "      },\n"
        "      legend: {fontSize: 11, entryHeight: 18, marginLeft: 60},\n"
        "      link: {\n"
        f"        groupColour: {js_bool(use_group_colour)},\n"
        "        label: {\n"
        f"          show: {js_bool(show_link_labels)},\n"
        "          fontSize: 11,\n"
        "        },\n"
        "      },\n"
        "    })\n\n"
        "  let plot"
    )
    text = re.sub(r"\.config\(\{.*?\n\s*\}\)\n\n  let plot", config_block, text, count=1, flags=re.S)

    for input_id, value in [
        ("input-scale-factor", scale_factor),
        ("input-cluster-spacing", vertical_spacing),
        ("input-label-rotation", 45),
        ("input-label-size", 11),
        ("input-locus-name-size", 11),
    ]:
        text = set_input_defaults(text, input_id, value)

    for input_id, checked in [
        ("input-cluster-align-labels", align_labels),
        ("input-cluster-hide-coords", hide_locus_coordinates),
        ("input-gene-labels", show_gene_labels),
        ("input-link-group-colour", use_group_colour),
        ("input-link-label-show", show_link_labels),
    ]:
        text = set_checkbox_state(text, input_id, checked)

    # Replace prior injected layout when reprocessing an existing portable panel.
    text = re.sub(r"<!-- clusterweave-layout-start -->.*?<!-- clusterweave-layout-end -->", "", text, flags=re.S)
    text = re.sub(r"\n  function layoutClusterWeaveLabels\(\) \{.*?  setTimeout\(layoutClusterWeaveLabels, 600\);\n", "\n", text, count=1, flags=re.S)
    layout = r'''
<!-- clusterweave-layout-start -->
  let clusterWeaveLayoutTimer;
  function scheduleClusterWeaveLayout() {
    clearTimeout(clusterWeaveLayoutTimer);
    clusterWeaveLayoutTimer = setTimeout(() => layoutClusterWeaveLabels(), 100);
  }
  function layoutClusterWeaveLabels() {
    const svg = document.querySelector("svg.clusterMap");
    if (!svg) return;
    const group = svg.querySelector("g.clusterMapG");
    group.setAttribute("transform", "translate(0,0)");
    // Preserve the native genomic scale and angled labels. Wide loci remain
    // scrollable/zoomable instead of being compressed into overlapping names.
    // Keep the legend to the right in the drawing and exported SVG. The
    // full canvas scrolls horizontally on narrow screens without rescaling loci.
    const legend = group.querySelector("g.legend");
    if (legend) {
      legend.style.display = "none";
      const drawing = group.getBBox();
      legend.style.display = "";
      const box = legend.getBBox();
      legend.setAttribute("transform", `translate(${drawing.x + drawing.width + 60 - box.x},${drawing.y - box.y})`);
    }
    const box = group.getBBox();
    const transform = d3.zoomIdentity.translate(24 - box.x, 24 - box.y);
    group.setAttribute("transform", transform);
    // Keep D3 navigation synchronized with the framed view.
    d3.select(svg).property("__zoom", transform);
    svg.setAttribute("width", Math.max(div.node().clientWidth, Math.ceil(box.width + 48)));
    svg.setAttribute("height", Math.max(div.node().clientHeight, Math.ceil(box.height + 48)));
  }
  scheduleClusterWeaveLayout();
  // Observe the viewport, not the scroll container whose scrollbar is changed
  // by this layout. This avoids self-triggered resize/fit oscillation.
  window.addEventListener("resize", () => {
    scheduleClusterWeaveLayout();
  });
<!-- clusterweave-layout-end -->
'''
    # HTML comment delimiters are valid JavaScript line comments in classic scripts.
    text = text.replace('  d3.select("#btn-save-svg")', layout + '\n  d3.select("#btn-save-svg")', 1)
    if 'layoutClusterWeaveLabels();\n\t\t\tconst blob' not in text:
        text = text.replace('const blob = serialise(svg)', 'layoutClusterWeaveLabels();\n\t\t\tconst blob = serialise(svg)', 1)
    text = text.replace('    plot.call(chart)\n  }', '    plot.call(chart)\n    setTimeout(layoutClusterWeaveLabels, 600);\n  }', 1)
    text = text.replace('setTimeout(layoutClusterWeaveLabels, 600);', 'scheduleClusterWeaveLayout();')
    # Export bounds need signed offsets and padding, including positive origins.
    text = text.replace('node.setAttribute("width", bbox.width);', 'node.setAttribute("width", bbox.width + 48);')
    text = text.replace('node.setAttribute("height", bbox.height);', 'node.setAttribute("height", bbox.height + 48);')
    text = text.replace('translate(${Math.abs(bbox.x)}, ${Math.abs(bbox.y)})', 'translate(${24 - bbox.x}, ${24 - bbox.y})')
    text = re.sub(r"\n#plot \{width: calc\(100vw - 370px\);.*?</style>", "</style>", text, count=1, flags=re.S)
    text = re.sub(r"/\* clusterweave-layout \*/.*?/\* end-clusterweave-layout \*/", "", text, flags=re.S)
    css = """/* clusterweave-layout */
div#plot {width: calc(100vw - 370px); height: 100vh; overflow: auto; scrollbar-gutter: stable;}
#plot .wrapper-svg {width: 100%; height: 100%;}
#div-floater {box-sizing: border-box; right: 12px; width: 340px;}
@media(max-width: 800px) {
  div#plot {width: 100vw; height: 68vh;}
  #div-floater {width: 100%; right: 0; top: 70vh; max-height: 30vh;}
}
/* end-clusterweave-layout */
"""
    text = text.replace('</style>', css + '</style>', 1)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Improve clinker HTML labels and legend names.")
    parser.add_argument("--html", type=Path, required=True, help="panel.html path")
    parser.add_argument("--manifest", type=Path, required=True, help="panel_manifest.tsv path")
    args = parser.parse_args()

    manifest_rows = read_tsv_rows(args.manifest)
    ordered_rows = sorted(manifest_rows, key=order_key)
    # A repeated organism is useful as the cluster heading; repeating the same
    # organism again in brackets adds no identity. Distinct genomes sharing a
    # display name still receive their original genome qualifier.
    genomes_by_name = defaultdict(set)
    scaffold_counts = Counter(friendly_scaffold_name(row) for row in manifest_rows)
    for row in manifest_rows:
        genomes_by_name[friendly_cluster_name(row)].add(clean(row.get("genome")))
    row_by_stem = {
        Path(clean(row.get("staged_gbk_path"))).stem: row
        for row in manifest_rows
        if clean(row.get("staged_gbk_path"))
    }

    prefix, payload, suffix = parse_html_payload(args.html)

    gene_by_uid: dict[str, dict[str, object]] = {}
    label_options_by_uid: dict[str, list[str]] = {}
    for cluster_index, cluster in enumerate(iter_clusters(payload)):
        cluster_name = clean(cluster.get("name"))
        manifest_row = row_by_stem.get(cluster_name)
        if manifest_row is None and cluster_index < len(ordered_rows):
            manifest_row = ordered_rows[cluster_index]
        if manifest_row is None:
            manifest_row = {}
        friendly_name = friendly_cluster_name(manifest_row)
        if friendly_name and len(genomes_by_name[friendly_name]) > 1:
            friendly_name += " [" + clean(manifest_row.get("genome")) + "]"
        if friendly_name:
            cluster["name"] = friendly_name
            cluster["label"] = friendly_name
        for locus in cluster.get("loci", []):
            locus_name = friendly_scaffold_name(
                manifest_row, normalize_locus_name(locus.get("name", ""))
            )
            if locus_name and scaffold_counts[locus_name] > 1:
                # Multiple regions on the same scaffold must remain distinct.
                region = clean(manifest_row.get("antismash_region"))
                region_suffix = re.search(r"\.(?:region|cluster)[0-9]+$", region, re.IGNORECASE)
                if region_suffix and not locus_name.endswith(region_suffix.group()):
                    locus_name += region_suffix.group()
            if locus_name:
                locus["name"] = locus_name
            for gene in locus.get("genes", []):
                normalize_gene_display_names(gene)
                gene["label"] = preferred_gene_label(gene)
                gene_by_uid[gene["uid"]] = {
                    "gene": gene,
                    "role": clean(manifest_row.get("role")),
                    "cluster_name": friendly_name or cluster_name,
                }

    for link in payload.get("links", []):
        for endpoint in ["query", "target"]:
            gene = link.get(endpoint)
            if isinstance(gene, dict):
                normalize_gene_display_names(gene)
                gene["label"] = preferred_gene_label(gene)

    for idx, group in enumerate(payload.get("groups", []), start=1):
        group["label"] = choose_group_label(group, gene_by_uid, idx)
        label_options_by_uid[clean(group.get("uid"))] = group_label_options(group, gene_by_uid)
    ensure_unique_labels(payload.get("groups", []), label_options_by_uid)

    # Retained panel manifests carry exact identities/provenance. Remove the
    # old generated presentation from both fresh and reprocessed exports.
    prefix = re.sub(r'<section id="clusterweave-panel-provenance"[\s\S]*?</section>', '', prefix)
    write_html_payload(args.html, prefix, payload, suffix)
    print(f"Updated clinker HTML labels: {args.html}")


if __name__ == "__main__":
    main()
