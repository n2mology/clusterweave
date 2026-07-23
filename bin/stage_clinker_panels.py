#!/usr/bin/env python3
"""Stage reviewer-priority BGC panels for clinker."""

from __future__ import annotations

import argparse
import csv
import re
import shlex
import shutil
from collections import defaultdict
from pathlib import Path
import sys

BIN_DIR = str(Path(__file__).resolve().parent)
if BIN_DIR not in sys.path:
    sys.path.insert(0, BIN_DIR)

from gcf_view import (
    GCF_PROVENANCE_FIELDS,
    has_selected_gcf_schema,
    materialized_gcf_provenance,
    selected_gcf_id,
    selected_gcf_ids,
    selected_gcf_view,
    selected_views_compatible,
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


def sanitize_token(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", clean(value))
    return text.strip("._-") or "item"


def slugify_label(value: str) -> str:
    text = clean(value).lower()
    text = text.replace("&", " and ")
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "item"


def split_gcf_ids(value: str) -> list[str]:
    return [part.strip() for part in clean(value).split(";") if part.strip()]


def ecology_display(row: dict[str, str]) -> str:
    primary = clean(row.get("ecofun_primary"))
    secondary = clean(row.get("ecofun_secondary"))
    broad = clean(row.get("ecology_group"))

    parts: list[str] = []
    for value in [primary, secondary]:
        if value and value not in parts:
            parts.append(value)
    detail = "/".join(parts)
    if detail:
        if (
            broad
            and broad not in {"Other", detail}
            and not detail.startswith(f"{broad}/")
            and not detail.endswith(f"/{broad}")
        ):
            return f"{detail} [{broad}]"
        return detail
    return broad or "NA"


def first_product_candidate(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    text = text.split(";", 1)[0].strip()
    if "|" in text:
        left, right = text.split("|", 1)
        if re.fullmatch(r"(?:BGC|FBGC|FPROT)\d+(?:\.\d+)?", clean(left), flags=re.IGNORECASE):
            text = clean(right)
    text = re.sub(
        r"^(?:clustercompare|FBGC\d+|FPROT\d+)\s+[0-9.eE+-]+\s*:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if " | " in text:
        text = text.split(" | ", 1)[0].strip()
    return clean(text)


def expected_putative_product(target_row: dict[str, str]) -> str:
    for key in [
        "antismash_knowncluster_product",
        "funbgcex_putative_product",
        "nearest_mibig_or_annotation_if_available",
    ]:
        candidate = first_product_candidate(clean(target_row.get(key)))
        if candidate:
            return candidate
    antismash_class = clean(target_row.get("antismash_class"))
    if antismash_class:
        return f"unassigned {antismash_class}"
    antismash_region = clean(target_row.get("antismash_region"))
    if antismash_region:
        return antismash_region
    return "unassigned_bgc"


def load_genome_metadata(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    metadata: dict[str, dict[str, str]] = {}
    for row in read_tsv_rows(path):
        genome = clean(row.get("genome_id")) or clean(row.get("genome"))
        if not genome:
            continue
        taxon_group = clean(row.get("taxon_group")).lower()
        if taxon_group not in {"fungi", "bacteria"}:
            taxon_group = "fungi"
        metadata[genome] = {
            "organism_name": clean(row.get("organism_name")),
            "taxon_group": taxon_group,
            "taxon_source": clean(row.get("taxon_source")),
        }
    return metadata


def load_genus_by_genome(path: Path) -> dict[str, str]:
    genera: dict[str, str] = {}
    for genome, row in load_genome_metadata(path).items():
        organism = clean(row.get("organism_name"))
        genus = organism.replace("_", " ").split(None, 1)[0] if organism else ""
        if genus:
            genera[genome] = genus
    return genera


def load_original_record_ids(path: Path) -> dict[tuple[str, str], str]:
    original_ids: dict[tuple[str, str], str] = {}
    if not path.is_dir():
        return original_ids
    suffix = ".record_map.tsv"
    for map_path in sorted(path.glob(f"*{suffix}")):
        genome = map_path.name.removesuffix(suffix)
        for row in read_tsv_rows(map_path):
            sanitized = clean(row.get("sanitized_record_id"))
            original = clean(row.get("original_record_id"))
            if genome and sanitized and original:
                original_ids[(genome, sanitized)] = original
    return original_ids


def panel_scaffold_id(
    row: dict[str, str], original_ids: dict[tuple[str, str], str]
) -> str:
    genome = clean(row.get("genome"))
    region = clean(row.get("antismash_region"))
    record = re.sub(r"\.region\d+$", "", region, flags=re.IGNORECASE)
    return original_ids.get((genome, record), record)


def panel_genome_metadata(
    row: dict[str, str], metadata_by_genome: dict[str, dict[str, str]]
) -> dict[str, str]:
    genome = clean(row.get("genome"))
    canonical = metadata_by_genome.get(genome, {})
    taxon_group = clean(row.get("taxon_group") or canonical.get("taxon_group")).lower()
    if taxon_group not in {"fungi", "bacteria"}:
        # Historical jobs without a routing manifest retain the fungal default.
        taxon_group = "fungi"
    return {
        "organism_name": clean(row.get("organism_name") or canonical.get("organism_name")),
        "taxon_group": taxon_group,
        "taxon_source": clean(row.get("taxon_source") or canonical.get("taxon_source")),
    }


def resolve_panel_path(project_root: Path, raw_path: str) -> Path:
    path = Path(clean(raw_path))
    if not path:
        return path
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


def extract_mibig_accessions(*values: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        for match in re.findall(r"(BGC\d+(?:\.\d+)?)", clean(value)):
            if match not in seen:
                seen.add(match)
                out.append(match)
    return out


def find_mibig_file(mibig_root: Path | None, accession: str) -> Path | None:
    if mibig_root is None or not mibig_root.exists() or not accession:
        return None

    versionless = accession.split(".", 1)[0]
    patterns = [
        f"{accession}.gbk",
        f"{versionless}.gbk",
        f"{accession}*.gbk",
        f"{versionless}*.gbk",
    ]
    for pattern in patterns:
        matches = sorted(mibig_root.rglob(pattern))
        if matches:
            return matches[0]
    return None


def mibig_root_has_gbks(mibig_root: Path | None) -> bool:
    if mibig_root is None or not mibig_root.exists():
        return False
    return any(mibig_root.rglob("*.gbk")) or any(mibig_root.rglob("*.gb"))


def default_mibig_root(project_root: Path) -> Path | None:
    software_root = project_root / "software"
    bigscape_softdir = software_root / "big_scape"
    res_dir = bigscape_softdir / "resources"
    mibig_cache = res_dir / "mibig_cache"
    if mibig_root_has_gbks(mibig_cache):
        return mibig_cache
    return None


def region_gbk_path(antismash_root: Path, genome: str, antismash_region: str) -> Path:
    return antismash_root / genome / f"{antismash_region}.gbk"


def shortlist_bucket_column(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "manual_review_bucket"
    if "manual_review_bucket" in rows[0]:
        return "manual_review_bucket"
    if "review_bucket" in rows[0]:
        return "review_bucket"
    raise KeyError("Shortlist file missing manual_review_bucket/review_bucket column")


def dedupe_candidates(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        category, threshold = selected_gcf_view(row)
        key = (
            clean(row.get("genome")),
            clean(row.get("antismash_region")),
            f"{category}@c{threshold}={selected_gcf_id(row)}",
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def ranking_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    index: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (clean(row.get("genome")), clean(row.get("antismash_region")))
        if not key[0] or not key[1]:
            continue
        index[key] = row
    return index


def target_region_key(row: dict[str, str]) -> tuple[str, str]:
    return (clean(row.get("genome")), clean(row.get("antismash_region")))


def is_dataset_atlas_target(row: dict[str, str]) -> bool:
    return clean(row.get("selection_track")) == "dataset_family_atlas" or bool(clean(row.get("atlas_rank")))


def target_selection_sort_key(row: dict[str, str]) -> tuple[object, ...]:
    return (
        to_int(
            row.get("shortlist_rank")
            or row.get("target_rank")
            or row.get("shared_family_rank")
            or row.get("atlas_rank")
            or row.get("rank")
        ),
        -to_int(row.get("priority_score")),
        clean(row.get("genome")),
        clean(row.get("antismash_region")),
    )


def select_candidate_targets(
    shortlist_rows: list[dict[str, str]],
    bucket_column: str,
    bucket: str,
    genome: str,
) -> list[dict[str, str]]:
    if clean(genome):
        candidates = [
            row
            for row in shortlist_rows
            if clean(row.get("genome")) == genome and clean(row.get(bucket_column)) == bucket
        ]
    else:
        candidates = [
            row
            for row in shortlist_rows
            if clean(row.get(bucket_column)) == bucket
            and clean(row.get("genome"))
            and clean(row.get("antismash_region"))
        ]
    return sorted(candidates, key=target_selection_sort_key)


def enrich_target_row(target_row: dict[str, str], ranking_row: dict[str, str] | None) -> dict[str, str]:
    if ranking_row is None:
        return dict(target_row)
    merged = dict(ranking_row)
    merged.update(target_row)
    return merged


def candidate_sort_key(
    candidate: dict[str, str],
    target_genus: str,
    target_ecology: str,
    genus_by_genome: dict[str, str] | None = None,
) -> tuple[object, ...]:
    candidate_genome = clean(candidate.get("genome"))
    candidate_genus = clean((genus_by_genome or {}).get(candidate_genome))
    same_canonical_genus = bool(
        target_genus
        and candidate_genus
        and candidate_genus.casefold() == target_genus.casefold()
    )
    candidate_ecology = clean(candidate.get("ecology_group"))
    priority_tier = clean(candidate.get("priority_tier"))
    priority_order = {"tier_1": 0, "tier_2": 1, "tier_3": 2, "tier_4": 3}
    return (
        0 if same_canonical_genus else 1,
        0 if candidate_ecology == target_ecology else 1,
        priority_order.get(priority_tier, 9),
        -to_int(candidate.get("priority_score")),
        candidate_genome,
        clean(candidate.get("antismash_region")),
    )


def choose_comparators(
    target_row: dict[str, str],
    ranking_rows: list[dict[str, str]],
    antismash_root: Path,
    max_same_ecology: int,
    max_other_ecology: int,
    max_comparators: int,
    genus_by_genome: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    target_genome = clean(target_row.get("genome"))
    target_ecology = clean(target_row.get("ecology_group")) or "UNLABELED"
    target_genus = clean((genus_by_genome or {}).get(target_genome))
    target_region = clean(target_row.get("antismash_region"))
    target_gcf_set = set(selected_gcf_ids(target_row))
    legacy_target = not has_selected_gcf_schema(target_row)
    target_cc_alias_set = (
        set(split_gcf_ids(clean(target_row.get("shared_cc_all_family_aliases"))))
        if legacy_target
        else set()
    )
    cc_alias_only_set = target_cc_alias_set.difference(target_gcf_set)

    exact_matches: list[dict[str, str]] = []
    cc_alias_matches: list[dict[str, str]] = []
    target_family_matches: list[dict[str, str]] = []
    for row in ranking_rows:
        genome = clean(row.get("genome"))
        antismash_region = clean(row.get("antismash_region"))
        gcf_id = selected_gcf_id(row)
        # Region basenames are only unique within one genome. Exclude the
        # target by its canonical composite key; a same-named region in a
        # different genome is a valid comparator and must not disappear.
        if (
            not genome
            or not antismash_region
            or (genome == target_genome and antismash_region == target_region)
        ):
            continue
        candidate_path = region_gbk_path(antismash_root, genome, antismash_region)
        if not candidate_path.exists():
            continue

        candidate_gcf_set = set(selected_gcf_ids(row))
        if (
            not target_gcf_set
            or not candidate_gcf_set
            or not selected_views_compatible(target_row, row)
        ):
            continue
        if candidate_gcf_set == target_gcf_set:
            row = dict(row)
            row["match_type"] = "exact_gcf"
            exact_matches.append(row)
        elif (
            legacy_target
            and not has_selected_gcf_schema(row)
            and cc_alias_only_set.intersection(candidate_gcf_set)
        ):
            row = dict(row)
            row["match_type"] = "shared_cc_alias"
            cc_alias_matches.append(row)
        elif target_gcf_set.intersection(candidate_gcf_set):
            row = dict(row)
            row["match_type"] = "shared_target_family"
            target_family_matches.append(row)

    exact_matches = dedupe_candidates(sorted(exact_matches, key=lambda row: candidate_sort_key(row, target_genus, target_ecology, genus_by_genome)))
    cc_alias_matches = dedupe_candidates(sorted(cc_alias_matches, key=lambda row: candidate_sort_key(row, target_genus, target_ecology, genus_by_genome)))
    target_family_matches = dedupe_candidates(sorted(target_family_matches, key=lambda row: candidate_sort_key(row, target_genus, target_ecology, genus_by_genome)))

    selected: list[dict[str, str]] = []
    selected_genomes: set[str] = set()

    def take_from_pool(pool: list[dict[str, str]], same_ecology_only: bool | None, limit: int) -> None:
        for row in pool:
            if len(selected) >= max_comparators or limit <= 0:
                return
            genome = clean(row.get("genome"))
            ecology = clean(row.get("ecology_group"))
            if genome in selected_genomes:
                continue
            if same_ecology_only is True and ecology != target_ecology:
                continue
            if same_ecology_only is False and ecology == target_ecology:
                continue
            selected.append(row)
            selected_genomes.add(genome)
            limit -= 1

    take_from_pool(exact_matches, True, max_same_ecology)
    take_from_pool(exact_matches, False, max_other_ecology)
    take_from_pool(exact_matches, None, max_comparators - len(selected))
    if len(selected) < max_comparators:
        take_from_pool(cc_alias_matches, True, max_same_ecology)
    if len(selected) < max_comparators:
        take_from_pool(cc_alias_matches, False, max_other_ecology)
    if len(selected) < max_comparators:
        take_from_pool(cc_alias_matches, None, max_comparators - len(selected))
    if len(selected) < max_comparators:
        take_from_pool(target_family_matches, True, max_same_ecology)
    if len(selected) < max_comparators:
        take_from_pool(target_family_matches, False, max_other_ecology)
    if len(selected) < max_comparators:
        take_from_pool(target_family_matches, None, max_comparators - len(selected))
    return selected[:max_comparators]


def panel_family_slug(target_row: dict[str, str]) -> str:
    """Return a stable, human-interpretable selected-GCF discriminator."""

    family = "_".join(selected_gcf_ids(target_row))
    if not family:
        return ""
    category, threshold = selected_gcf_view(target_row)
    parts = ["gcf"]
    if category:
        parts.append(category)
    if threshold:
        parts.append(f"c{threshold}")
    parts.append(family)
    return slugify_label("_".join(parts))


def panel_display_label(target_row: dict[str, str], panel_id: str) -> str:
    """Return the lossless compound label, qualified only when needed."""

    product = expected_putative_product(target_row)
    if "__gcf_" not in panel_id:
        return product
    family = selected_gcf_id(target_row)
    category, threshold = selected_gcf_view(target_row)
    view = f"c{threshold}" if threshold else ""
    qualifier = " ".join(part for part in [category.upper(), view, family] if part)
    return f"{product} [{qualifier}]" if qualifier else product


def panel_dir_name(target_row: dict[str, str], used_names: set[str]) -> str:
    base_name = slugify_label(expected_putative_product(target_row))
    antismash_region = slugify_label(clean(target_row.get("antismash_region")))
    if not base_name:
        base_name = antismash_region or "unassigned_bgc"

    candidate = base_name
    if candidate in used_names:
        # A shared compound annotation does not imply a shared GCF. Qualify
        # slug collisions with selected-family identity instead of an opaque
        # antiSMASH region ID. The manifest retains the raw compound, target,
        # and complete selected/all-view GCF provenance.
        family_suffix = panel_family_slug(target_row)
        collision_base = (
            f"{base_name}__{family_suffix}"
            if family_suffix
            else f"{base_name}__panel"
        )
        candidate = collision_base
    else:
        collision_base = base_name
    counter = 2
    while candidate in used_names:
        candidate = f"{collision_base}_{counter}"
        counter += 1
    used_names.add(candidate)
    return candidate


def load_existing_panel_dirs(
    project_root: Path,
    manifest_paths: list[Path],
) -> dict[tuple[str, str], Path]:
    mapping: dict[tuple[str, str], Path] = {}
    for manifest_path in manifest_paths:
        if not manifest_path.exists():
            continue
        for row in read_tsv_rows(manifest_path):
            target_genome = clean(row.get("target_genome"))
            target_region = clean(row.get("target_region"))
            panel_dir = clean(row.get("panel_dir"))
            if not target_genome or not target_region or not panel_dir:
                continue
            mapping.setdefault(
                (target_genome, target_region),
                resolve_panel_path(project_root, panel_dir),
            )
    return mapping


def migrate_existing_panel(existing_dir: Path | None, panel_dir: Path) -> None:
    if existing_dir is None or not existing_dir.exists():
        return
    if existing_dir.resolve() == panel_dir.resolve():
        return

    panel_dir.parent.mkdir(parents=True, exist_ok=True)
    panel_dir.mkdir(parents=True, exist_ok=True)

    for name in ["panel.html", "alignments.tsv"]:
        src = existing_dir / name
        dst = panel_dir / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)


def expected_active_panel_dirs(project_root: Path, output_root: Path, panel_rows: list[dict[str, object]]) -> set[Path]:
    active_dirs: set[Path] = set()
    for row in panel_rows:
        panel_dir = clean(row.get("panel_dir"))
        if not panel_dir:
            continue
        active_dirs.add(resolve_panel_path(project_root, panel_dir))
    return active_dirs


def prune_stale_panel_dirs(panels_root: Path, active_dirs: set[Path]) -> None:
    if not panels_root.exists():
        return
    generated_dirs = sorted(
        {path.parent for path in panels_root.rglob("panel_manifest.tsv")},
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for panel_dir in generated_dirs:
        resolved = panel_dir.resolve()
        if resolved in active_dirs or not (panel_dir / "run_panel.sh").exists():
            continue
        try:
            shutil.rmtree(panel_dir)
        except PermissionError:
            continue


def build_panel_markdown(
    panel_dir: Path,
    target_row: dict[str, str],
    manifest_rows: list[dict[str, object]],
    mibig_accessions: list[str],
) -> None:
    lines = [
        f"# Clinker panel for {clean(target_row.get('antismash_region'))}",
        "",
        f"- target genome: `{clean(target_row.get('genome'))}`",
        f"- target rank: `{clean(target_row.get('shortlist_rank')) or clean(target_row.get('target_rank')) or clean(target_row.get('shared_family_rank')) or clean(target_row.get('atlas_rank'))}`",
        f"- review bucket: `{clean(target_row.get('manual_review_bucket')) or clean(target_row.get('review_bucket'))}`",
        f"- selection track: `{clean(target_row.get('selection_track')) or 'priority_confidence'}`",
        f"- expected putative product: `{expected_putative_product(target_row)}`",
        f"- selected GCF: `{selected_gcf_id(target_row)}`",
        f"- selected GCF view: `{selected_gcf_view(target_row)[0] or 'legacy'}@c{selected_gcf_view(target_row)[1] or 'legacy'}`",
        f"- all-view GCF compatibility union: `{clean(target_row.get('gcf_id'))}`",
        f"- lossless GCF memberships: `{clean(target_row.get('gcf_memberships'))}`",
        f"- class: `{clean(target_row.get('antismash_class'))}`",
        f"- reference annotation: `{clean(target_row.get('nearest_mibig_or_annotation_if_available')) or clean(target_row.get('reference_annotation'))}`",
        f"- recommended follow-up: {clean(target_row.get('recommended_followup')) or clean(target_row.get('comparator_strategy'))}",
        "",
        "## Staged inputs",
        "",
    ]
    if clean(target_row.get("bigscape_cc")):
        lines[7:7] = [
            f"- BiG-SCAPE CC: `{clean(target_row.get('bigscape_cc'))}`",
            f"- shared-family record count: `{clean(target_row.get('shared_cc_record_count'))}`",
            f"- shared-family primary families: `{clean(target_row.get('shared_cc_primary_families'))}`",
        ]
    for row in manifest_rows:
        lines.append(
            f"- `{row['order']}` `{row['role']}` `{row['genome']}` `{row['antismash_region']}` "
            f"({row.get('ecology_display') or row['ecology_group'] or 'NA'}, {row['match_type'] or 'target'})"
        )
    if mibig_accessions:
        lines.extend(["", f"- requested MIBiG accessions: `{';'.join(mibig_accessions)}`"])
    panel_dir.joinpath("panel_notes.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run_panel_script(
    panel_dir: Path,
    staged_files: list[Path],
    project_root: Path,
    repo_root: Path,
) -> None:
    input_lines = [f"CLINKER_INPUTS+=('{path.as_posix()}')" for path in staged_files]
    project_root_literal = shlex.quote(project_root.resolve().as_posix())
    repo_root_literal = shlex.quote(repo_root.resolve().as_posix())
    script_text = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "IFS=$' \\n\\t'",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd -P)\"",
            "cd \"${SCRIPT_DIR}\"",
            f"PROJECT_ROOT={project_root_literal}",
            f"REPO_ROOT={repo_root_literal}",
            "POSTPROCESS_PY=\"${PROJECT_ROOT}/bin/postprocess_clinker_html.py\"",
            "POSTPROCESS_FALLBACK_PY=\"${REPO_ROOT}/bin/postprocess_clinker_html.py\"",
            "POSTPROCESS_MANIFEST=\"${SCRIPT_DIR}/panel_manifest.tsv\"",
            "POSTPROCESS_HTML=\"${SCRIPT_DIR}/panel.html\"",
            "",
            "CLINKER_INPUTS=()",
            *input_lines,
            "",
            "resolve_postprocess_py() {",
            "  if [[ -f \"${POSTPROCESS_PY}\" ]]; then",
            "    return 0",
            "  fi",
            "  local candidate",
            "  for candidate in \"${POSTPROCESS_FALLBACK_PY}\" \"${CLUSTERWEAVE_ROOT:-}/bin/postprocess_clinker_html.py\"; do",
            "    if [[ -n \"${candidate}\" && -f \"${candidate}\" ]]; then",
            "      POSTPROCESS_PY=\"${candidate}\"",
            "      return 0",
            "    fi",
            "  done",
            "  return 1",
            "}",
            "",
            "run_postprocess() {",
            "  if [[ ! -f \"${POSTPROCESS_MANIFEST}\" || ! -f \"${POSTPROCESS_HTML}\" ]]; then",
            "    echo \"Skipping clinker HTML post-processing: missing panel manifest or HTML for ${SCRIPT_DIR}\" >&2",
            "    return 0",
            "  fi",
            "  if ! resolve_postprocess_py; then",
            "    echo \"Skipping clinker HTML post-processing: helper not found under ${PROJECT_ROOT}/bin or ${REPO_ROOT}/bin\" >&2",
            "    return 0",
            "  fi",
            "  local helper_python=\"${PYTHON_BIN:-}\"",
            "  if [[ -z \"${helper_python}\" ]]; then",
            "    if command -v python3 >/dev/null 2>&1; then",
            "      helper_python=\"$(command -v python3)\"",
            "    elif command -v python >/dev/null 2>&1; then",
            "      helper_python=\"$(command -v python)\"",
            "    fi",
            "  fi",
            "  if [[ -z \"${helper_python}\" ]]; then",
            "    echo \"Skipping clinker HTML post-processing: no python interpreter found\" >&2",
            "    return 0",
            "  fi",
            "  \"${helper_python}\" \"${POSTPROCESS_PY}\" --html \"${POSTPROCESS_HTML}\" --manifest \"${POSTPROCESS_MANIFEST}\" \\",
            "    || echo \"Warning: clinker HTML post-processing failed for ${SCRIPT_DIR}\" >&2",
            "}",
            "",
            "if command -v clinker >/dev/null 2>&1 && [[ \"${PREFER_CLINKER_CONTAINER:-0}\" != \"1\" ]]; then",
            "  clinker \"${CLINKER_INPUTS[@]}\" -p \"${SCRIPT_DIR}/panel.html\" -o \"${SCRIPT_DIR}/alignments.tsv\" -f -ufo",
            "  run_postprocess",
            "  exit 0",
            "fi",
            "",
            "if [[ -n \"${CLINKER_ENGINE:-}\" && -n \"${CLINKER_SIF_PATH:-}\" && -f \"${CLINKER_SIF_PATH}\" ]]; then",
            "  \"${CLINKER_ENGINE}\" exec --bind \"${SCRIPT_DIR}:${SCRIPT_DIR}\" \"${CLINKER_SIF_PATH}\" \\",
            "    clinker \"${CLINKER_INPUTS[@]}\" -p \"${SCRIPT_DIR}/panel.html\" -o \"${SCRIPT_DIR}/alignments.tsv\" -f -ufo",
            "  run_postprocess",
            "  exit 0",
            "fi",
            "",
            "if [[ -n \"${CLINKER_DOCKER_IMAGE:-}\" ]]; then",
            "  CLINKER_DOCKER_CPUS=\"${CLINKER_DOCKER_CPUS:-1}\"",
            "  if [[ ! \"${CLINKER_DOCKER_CPUS}\" =~ ^[0-9]+([.][0-9]+)?$ || \"${CLINKER_DOCKER_CPUS}\" == \"0\" || \"${CLINKER_DOCKER_CPUS}\" == \"0.0\" ]]; then",
            "    echo \"Warning: CLINKER_DOCKER_CPUS=${CLINKER_DOCKER_CPUS} is not a positive CPU number; using 1\" >&2",
            "    CLINKER_DOCKER_CPUS=1",
            "  fi",
            "  DOCKER_ARGS=(--rm -i --user 0:0 --entrypoint \"\" --cpus \"${CLINKER_DOCKER_CPUS}\")",
            "  DOCKER_ARGS+=(-e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e NUMEXPR_NUM_THREADS=1)",
            "  if [[ -n \"${CLINKER_DOCKER_MEMORY:-}\" ]]; then",
            "    DOCKER_ARGS+=(--memory \"${CLINKER_DOCKER_MEMORY}\")",
            "  fi",
            "  if [[ -n \"${CLINKER_DOCKER_PIDS_LIMIT:-}\" ]]; then",
            "    DOCKER_ARGS+=(--pids-limit \"${CLINKER_DOCKER_PIDS_LIMIT}\")",
            "  fi",
            "  if [[ -n \"${CLUSTERWEAVE_JOB_ID:-}\" ]]; then",
            "    DOCKER_ARGS+=(--label \"clusterweave.job_id=${CLUSTERWEAVE_JOB_ID}\" --label \"clusterweave.project=${PROJECT_NAME:-}\")",
            "  fi",
            "  DOCKER_ARGS+=(--workdir \"${SCRIPT_DIR}\")",
            "  if [[ -n \"${CLINKER_DOCKER_DATA_VOLUME:-}\" ]]; then",
            "    DOCKER_ARGS+=(-v \"${CLINKER_DOCKER_DATA_VOLUME}:/data\")",
            "  else",
            "    DOCKER_ARGS+=(-v \"${SCRIPT_DIR}:${SCRIPT_DIR}\")",
            "  fi",
            "  docker run \"${DOCKER_ARGS[@]}\" \"${CLINKER_DOCKER_IMAGE}\" \\",
            "    clinker \"${CLINKER_INPUTS[@]}\" -p \"${SCRIPT_DIR}/panel.html\" -o \"${SCRIPT_DIR}/alignments.tsv\" -f -ufo",
            "  run_postprocess",
            "  exit 0",
            "fi",
            "",
            "echo \"No usable clinker backend found for ${SCRIPT_DIR}\" >&2",
            "echo \"Expected local clinker, CLINKER_ENGINE + CLINKER_SIF_PATH, or CLINKER_DOCKER_IMAGE from run_clinker.sh\" >&2",
            "exit 1",
            "",
        ]
    )
    panel_dir.joinpath("run_panel.sh").write_text(script_text, encoding="utf-8")


def write_master_run_script(output_root: Path, panel_dirs: list[Path], master_script_name: str) -> None:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "IFS=$' \\n\\t'",
        "",
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd -P)\"",
        "",
    ]
    if not panel_dirs:
        lines.append("echo \"No clinker panels were staged.\"")
    else:
        for panel_dir in panel_dirs:
            rel = panel_dir.relative_to(output_root).as_posix()
            lines.append(f"bash \"${{SCRIPT_DIR}}/{rel}/run_panel.sh\"")
    output_root.joinpath(master_script_name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage clinker panels from shortlist tables.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root containing Code/ and data/.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="ClusterWeave repository root containing bin/postprocess_clinker_html.py.",
    )
    parser.add_argument(
        "--project-name",
        default="clusterweave",
        help="Project name used under data/results.",
    )
    parser.add_argument(
        "--genome",
        default="",
        help="Optional genome to stage. Leave unset for dataset-wide atlas staging.",
    )
    parser.add_argument(
        "--shortlist",
        type=Path,
        default=None,
        help="Shortlist TSV. Defaults to summary/priority_shortlist.tsv.",
    )
    parser.add_argument(
        "--ranking",
        type=Path,
        default=None,
        help="Ranking TSV used to select comparators. Defaults to summary/targeted_candidate_ranking.tsv.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Output root for staged clinker panels. Defaults to data/results/<project>/clinker.",
    )
    parser.add_argument(
        "--bucket",
        default="clinker_now",
        help="Shortlist bucket to stage. Defaults to clinker_now.",
    )
    parser.add_argument(
        "--panels-subdir",
        default="panels",
        help="Panel subdirectory under output-root. Defaults to panels.",
    )
    parser.add_argument(
        "--manifest-name",
        default="panels_manifest.tsv",
        help="Manifest filename written under output-root.",
    )
    parser.add_argument(
        "--master-script-name",
        default="run_all_clinker_panels.sh",
        help="Master run-script filename written under output-root.",
    )
    parser.add_argument(
        "--existing-manifest",
        type=Path,
        action="append",
        default=[],
        help="Optional existing panel manifest(s) to mine for prior panel.html/alignments.tsv outputs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of target rows to stage.",
    )
    parser.add_argument(
        "--max-same-ecology",
        type=int,
        default=2,
        help="Maximum same-ecology comparators per panel.",
    )
    parser.add_argument(
        "--max-other-ecology",
        type=int,
        default=1,
        help="Maximum other-ecology comparators per panel.",
    )
    parser.add_argument(
        "--max-comparators",
        type=int,
        default=3,
        help="Maximum comparator regions per panel.",
    )
    parser.add_argument(
        "--mibig-root",
        type=Path,
        default=None,
        help="Optional local directory of MIBiG GenBank files.",
    )
    args = parser.parse_args()

    results_root = args.project_root / "data" / "results" / args.project_name
    summary_root = results_root / "summary"
    antismash_root = results_root / "antismash"
    output_root = args.output_root or (results_root / "clinker")
    output_root.mkdir(parents=True, exist_ok=True)
    panels_root = output_root / Path(args.panels_subdir)
    manifest_path = output_root / args.manifest_name
    mibig_root = args.mibig_root or default_mibig_root(args.project_root)

    shortlist_path = args.shortlist or (summary_root / "priority_shortlist.tsv")
    ranking_path = args.ranking or (summary_root / "targeted_candidate_ranking.tsv")
    if not shortlist_path.exists():
        raise FileNotFoundError(f"Shortlist TSV not found: {shortlist_path}")
    if not ranking_path.exists():
        raise FileNotFoundError(f"Ranking TSV not found: {ranking_path}")

    shortlist_rows = read_tsv_rows(shortlist_path)
    ranking_rows = read_tsv_rows(ranking_path)
    taxon_manifest_path = results_root / "summary_tables" / "genome_taxon_manifest.tsv"
    genome_metadata = load_genome_metadata(taxon_manifest_path)
    genus_by_genome = load_genus_by_genome(taxon_manifest_path)
    original_record_ids = load_original_record_ids(
        results_root / "summary_tables" / "bacterial_record_maps"
    )
    ranking_by_target = ranking_index(ranking_rows)
    bucket_column = shortlist_bucket_column(shortlist_rows)
    existing_manifest_paths = [manifest_path, *args.existing_manifest]
    existing_panel_dirs = load_existing_panel_dirs(args.project_root, existing_manifest_paths)

    candidate_targets = select_candidate_targets(shortlist_rows, bucket_column, args.bucket, args.genome)

    panel_rows: list[dict[str, object]] = []
    panel_dirs: list[Path] = []
    used_panel_names: dict[tuple[str, str], set[str]] = defaultdict(set)
    seen_target_keys: set[tuple[str, str]] = set()
    covered_atlas_region_keys: set[tuple[str, str]] = set()
    attempted_targets = 0

    for target_row in candidate_targets:
        raw_target_key = target_region_key(target_row)
        if raw_target_key[0] and raw_target_key[1] and raw_target_key in seen_target_keys:
            continue
        if raw_target_key[0] and raw_target_key[1]:
            seen_target_keys.add(raw_target_key)

        antismash_region = clean(target_row.get("antismash_region"))
        target_key = (clean(target_row.get("genome")), antismash_region)
        target_row = enrich_target_row(target_row, ranking_by_target.get(target_key))
        enriched_target_key = target_region_key(target_row)
        atlas_target = not clean(args.genome) and is_dataset_atlas_target(target_row)
        if (
            atlas_target
            and enriched_target_key[0]
            and enriched_target_key[1]
            and enriched_target_key in covered_atlas_region_keys
        ):
            continue
        if attempted_targets >= args.limit:
            break
        attempted_targets += 1

        shortlist_rank = to_int(
            target_row.get("shortlist_rank")
            or target_row.get("target_rank")
            or target_row.get("shared_family_rank")
            or target_row.get("atlas_rank")
            or target_row.get("rank")
        )
        target_genome = clean(target_row.get("genome"))
        target_metadata = panel_genome_metadata(target_row, genome_metadata)
        target_taxon = target_metadata["taxon_group"]
        panel_id = panel_dir_name(
            target_row, used_panel_names[(target_taxon, target_genome)]
        )
        panel_dir = (
            panels_root
            / target_taxon
            / sanitize_token(target_genome)
            / panel_id
        )
        compound_label = expected_putative_product(target_row)
        display_label = panel_display_label(target_row, panel_id)
        migrate_existing_panel(
            existing_panel_dirs.get((target_genome, antismash_region)),
            panel_dir,
        )
        inputs_dir = panel_dir / "inputs"
        panel_dir.mkdir(parents=True, exist_ok=True)
        inputs_dir.mkdir(parents=True, exist_ok=True)

        target_gbk = region_gbk_path(antismash_root, target_genome, antismash_region)
        if not target_gbk.exists():
            panel_rows.append(
                {
                    "panel_id": panel_id,
                    "panel_label": display_label,
                    "compound_label": compound_label,
                    "target_rank": shortlist_rank,
                    "target_genome": target_genome,
                    "target_taxon": target_taxon,
                    "target_organism": target_metadata["organism_name"],
                    "target_region": antismash_region,
                    **materialized_gcf_provenance(target_row),
                    "status": "missing_target_gbk",
                    "panel_dir": str(panel_dir),
                    "run_script": str(panel_dir / "run_panel.sh"),
                    "staged_input_count": 0,
                    "comparator_count": 0,
                    "mibig_count": 0,
                    "comparator_genomes": "",
                    "mibig_accessions": "",
                }
            )
            continue

        comparators = choose_comparators(
            target_row,
            ranking_rows,
            antismash_root,
            max_same_ecology=args.max_same_ecology,
            max_other_ecology=args.max_other_ecology,
            max_comparators=args.max_comparators,
            genus_by_genome=genus_by_genome,
        )
        if atlas_target:
            if enriched_target_key[0] and enriched_target_key[1]:
                covered_atlas_region_keys.add(enriched_target_key)
            for comparator in comparators:
                comparator_key = target_region_key(comparator)
                if comparator_key[0] and comparator_key[1]:
                    covered_atlas_region_keys.add(comparator_key)

        mibig_accessions = extract_mibig_accessions(
            clean(target_row.get("nearest_mibig_or_annotation_if_available")),
            clean(target_row.get("reference_annotation")),
        )
        mibig_files: list[tuple[str, Path]] = []
        for accession in mibig_accessions[:2]:
            mibig_file = find_mibig_file(mibig_root, accession)
            if mibig_file is not None:
                mibig_files.append((accession, mibig_file))

        manifest_rows: list[dict[str, object]] = []
        staged_files: list[Path] = []

        target_stage = inputs_dir / f"01_target_{sanitize_token(target_genome)}__{sanitize_token(antismash_region)}.gbk"
        shutil.copy2(target_gbk, target_stage)
        staged_files.append(target_stage.relative_to(panel_dir))
        manifest_rows.append(
            {
                "order": 1,
                "role": "target",
                "genome": target_genome,
                **target_metadata,
                "ecofun_primary": clean(target_row.get("ecofun_primary")),
                "ecofun_secondary": clean(target_row.get("ecofun_secondary")),
                "ecology_group": clean(target_row.get("ecology_group")) or "UNLABELED",
                "ecology_display": ecology_display(target_row),
                "antismash_region": antismash_region,
                "scaffold_id": panel_scaffold_id(target_row, original_record_ids),
                **materialized_gcf_provenance(target_row),
                "match_type": "target",
                "source_gbk_path": str(target_gbk),
                "staged_gbk_path": str(target_stage),
            }
        )

        order = 2
        comparator_genomes: list[str] = []
        for comparator in comparators:
            comparator_genome = clean(comparator.get("genome"))
            comparator_region = clean(comparator.get("antismash_region"))
            comparator_gbk = region_gbk_path(antismash_root, comparator_genome, comparator_region)
            staged_path = inputs_dir / (
                f"{order:02d}_compare_{sanitize_token(comparator_genome)}__{sanitize_token(comparator_region)}.gbk"
            )
            shutil.copy2(comparator_gbk, staged_path)
            staged_files.append(staged_path.relative_to(panel_dir))
            comparator_metadata = panel_genome_metadata(comparator, genome_metadata)
            manifest_rows.append(
                {
                    "order": order,
                    "role": "comparator",
                    "genome": comparator_genome,
                    **comparator_metadata,
                    "ecofun_primary": clean(comparator.get("ecofun_primary")),
                    "ecofun_secondary": clean(comparator.get("ecofun_secondary")),
                    "ecology_group": clean(comparator.get("ecology_group")),
                    "ecology_display": ecology_display(comparator),
                    "antismash_region": comparator_region,
                    "scaffold_id": panel_scaffold_id(comparator, original_record_ids),
                    **materialized_gcf_provenance(comparator),
                    "match_type": clean(comparator.get("match_type")),
                    "source_gbk_path": str(comparator_gbk),
                    "staged_gbk_path": str(staged_path),
                }
            )
            comparator_genomes.append(comparator_genome)
            order += 1

        for accession, mibig_file in mibig_files:
            staged_path = inputs_dir / f"{order:02d}_mibig_{sanitize_token(accession)}.gbk"
            shutil.copy2(mibig_file, staged_path)
            staged_files.append(staged_path.relative_to(panel_dir))
            manifest_rows.append(
                {
                    "order": order,
                    "role": "mibig_reference",
                    "genome": accession,
                    "organism_name": "",
                    "taxon_group": "",
                    "taxon_source": "mibig",
                    "ecofun_primary": "",
                    "ecofun_secondary": "",
                    "ecology_group": "",
                    "ecology_display": "",
                    "antismash_region": accession,
                    "scaffold_id": accession,
                    **materialized_gcf_provenance(target_row),
                    "match_type": "mibig_reference",
                    "source_gbk_path": str(mibig_file),
                    "staged_gbk_path": str(staged_path),
                }
            )
            order += 1

        write_tsv(
            panel_dir / "panel_manifest.tsv",
            [
                "order",
                "role",
                "genome",
                "organism_name",
                "taxon_group",
                "taxon_source",
                "ecofun_primary",
                "ecofun_secondary",
                "ecology_group",
                "ecology_display",
                "antismash_region",
                "scaffold_id",
                *GCF_PROVENANCE_FIELDS,
                "match_type",
                "source_gbk_path",
                "staged_gbk_path",
            ],
            manifest_rows,
        )
        build_panel_markdown(panel_dir, target_row, manifest_rows, mibig_accessions)
        write_run_panel_script(panel_dir, staged_files, args.project_root, args.repo_root)
        panel_dirs.append(panel_dir)
        panel_rows.append(
            {
                "panel_id": panel_id,
                "panel_label": display_label,
                "compound_label": compound_label,
                "target_rank": shortlist_rank,
                "target_genome": target_genome,
                    "target_taxon": target_taxon,
                    "target_organism": target_metadata["organism_name"],
                "target_region": antismash_region,
                **materialized_gcf_provenance(target_row),
                "status": "staged",
                "panel_dir": str(panel_dir),
                "run_script": str(panel_dir / "run_panel.sh"),
                "staged_input_count": len(manifest_rows),
                "comparator_count": len(comparators),
                "mibig_count": len(mibig_files),
                "comparator_genomes": ";".join(comparator_genomes),
                "mibig_accessions": ";".join(mibig_accessions),
            }
        )

    write_tsv(
        manifest_path,
        [
            "panel_id",
            "panel_label",
            "compound_label",
            "target_rank",
            "target_genome",
            "target_taxon",
            "target_organism",
            "target_region",
            *GCF_PROVENANCE_FIELDS,
            "status",
            "panel_dir",
            "run_script",
            "staged_input_count",
            "comparator_count",
            "mibig_count",
            "comparator_genomes",
            "mibig_accessions",
        ],
        panel_rows,
    )
    prune_stale_panel_dirs(panels_root, expected_active_panel_dirs(args.project_root, output_root, panel_rows))
    write_master_run_script(output_root, panel_dirs, args.master_script_name)

    print(f"Staged {len(panel_dirs)} clinker panels under {output_root}")
    print(f"Wrote panel manifest: {manifest_path}")
    print(f"Wrote master run script: {output_root / args.master_script_name}")
    if mibig_root is not None:
        print(f"Using MiBIG root: {mibig_root}")
    else:
        print("Using MiBIG root: none detected")


if __name__ == "__main__":
    main()
