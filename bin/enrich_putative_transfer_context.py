#!/usr/bin/env python3
"""Derive bounded context for explicitly requested cross-kingdom profiles.

The helper consumes only existing ClusterWeave result artifacts.  It performs
no downloads or inference, does not change core rankings, and emits bounded
public-safe scalar summaries.  Missing or scientifically inadequate inputs are
left unknown rather than promoted to evidence.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
import re
import stat
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from build_putative_transfer_evidence import (
    EvidenceInputError,
    read_candidate_rows,
    validate_public_value,
)


HARD_MAX_CANDIDATES = 100
MAX_CROSSWALK_BYTES = 64 * 1024 * 1024
MAX_CROSSWALK_ROWS = 500_000
MAX_RANKING_BYTES = 32 * 1024 * 1024
MAX_RANKING_ROWS = 250_000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_ROWS = 5_000
MAX_PANEL_BYTES = 32 * 1024 * 1024
MAX_PANEL_TOTAL_BYTES = 256 * 1024 * 1024
MAX_PANELS = 500
MAX_PANEL_SCAN_DIRS = 5_000
MAX_PANEL_SCAN_ENTRIES = 20_000
MAX_PANEL_CLUSTERS = 100
MAX_PANEL_GENES = 20_000
MAX_PANEL_LINKS = 100_000
MAX_REGION_BYTES = 64 * 1024 * 1024
MAX_REGION_FILES = 2_000
MAX_REGION_TOTAL_BYTES = 512 * 1024 * 1024
MAX_GENOME_BYTES = 2 * 1024 * 1024 * 1024
MAX_GENOME_FILES = 250
MAX_GENOME_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
MAX_CONTEXT_MEMBERS = 2_000
MAX_TEXT_CHUNK_CHARS = 1024 * 1024

MIN_SYNTENY_PAIRS = 5
MIN_SYNTENY_ORDER_FRACTION = 0.70
MIN_SYNTENY_CLUSTER_COVERAGE = 0.30
MIN_REFERENCE_PAIRS = 5
MIN_REFERENCE_COVERAGE = 0.50
MIN_REFERENCE_SIMILARITY = 0.50
MIN_CLINKER_LINK_IDENTITY = 0.30
MIN_REGION_CANONICAL_BASES = 5_000
MIN_GENOME_CANONICAL_BASES = 100_000
MIN_CANONICAL_FRACTION = 0.90
COMPOSITION_DEVIATION_DELTA_PERCENT = 10.0

CONTEXT_FIELDS = (
    "synteny_support",
    "synteny_gene_order_matches",
    "synteny_gene_count",
    "synteny_gene_order_fraction",
    "synteny_homolog_pair_count",
    "synteny_min_cluster_coverage",
    "synteny_basis",
    "synteny_method",
    "characterized_reference_support",
    "characterized_reference_id",
    "characterized_reference_similarity_percent",
    "characterized_reference_method",
    "characterized_reference_match_count",
    "characterized_reference_coverage",
    "mobile_element_context",
    "mobile_element_count",
    "mobile_element_method",
    "composition_outlier",
    "composition_deviation",
    "composition_region_gc_percent",
    "composition_genome_gc_percent",
    "composition_gc_delta_percent",
    "composition_method",
    "composition_deviation_scope",
    "composition_evaluated_region_count",
    "contamination_check",
    "contamination_method",
    "assembly_check",
    "assembly_context_method",
    "assembly_context_scope",
    "assembly_region_edge_context",
    "paralogy_check",
    "sampling_check",
    "conserved_enzyme_risk",
    "long_branch_attraction_risk",
)

SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+\-]{0,254}$")
SAFE_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
MIBIG_RE = re.compile(r"\b(BGC[0-9]{7}(?:\.[0-9]+)?)\b", re.IGNORECASE)
MOBILE_RE = re.compile(
    r"\b(?:transposase|integrase|insertion\s+sequence|mobile\s+(?:genetic\s+)?element|"
    r"integron|relaxase|conjugative\s+transposon|prophage|phage\s+integrase|resolvase)\b",
    re.IGNORECASE,
)
FEATURE_START_RE = re.compile(r"^ {5}(\S+)\s+")
QUALIFIER_RE = re.compile(r"^\s{21}/([A-Za-z0-9_]+)=?(.*)$")
CONTIG_EDGE_RE = re.compile(r'/contig_edge="?(True|False)"?', re.IGNORECASE)


class ContextInputError(ValueError):
    """Raised when bounded context inputs violate their expected schema."""


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def format_number(value: float, digits: int = 3) -> str:
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def safe_component(value: object) -> str:
    text = clean(value)
    return text if SAFE_COMPONENT_RE.fullmatch(text) and text not in {".", ".."} else ""


def safe_project_name(value: object) -> str:
    text = clean(value)
    return text if SAFE_PROJECT_RE.fullmatch(text) and text not in {".", ".."} else ""


def canonical_directory(path: Path, label: str, *, optional: bool = False) -> Path | None:
    try:
        if path.is_symlink():
            raise ContextInputError(f"{label} must not be a symlink")
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        if optional:
            return None
        raise ContextInputError(f"{label} is unavailable")
    except OSError as exc:
        raise ContextInputError(f"{label} is unavailable") from exc
    if not resolved.is_dir():
        if optional:
            return None
        raise ContextInputError(f"{label} must be a directory")
    return resolved


def contained_regular_file(root: Path, *parts: str) -> Path | None:
    candidate = root.joinpath(*parts)
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    current = root
    try:
        for part in parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                return None
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    try:
        return resolved if stat.S_ISREG(resolved.stat().st_mode) else None
    except OSError:
        return None


def split_families(value: object) -> tuple[str, ...]:
    families: list[str] = []
    seen: set[str] = set()
    for part in clean(value).split(";"):
        family = safe_component(part)
        if family and family not in seen:
            families.append(family)
            seen.add(family)
    return tuple(families)


def normalized_taxon(value: object) -> str:
    token = clean(value).casefold()
    return token if token in {"fungi", "bacteria"} else ""


def read_tsv(
    path: Path,
    *,
    max_bytes: int,
    max_rows: int,
    required_fields: Iterable[str] = (),
    optional: bool = False,
) -> tuple[list[str], list[dict[str, str]]]:
    if optional and not path.is_file():
        return [], []
    try:
        info = path.lstat()
    except OSError as exc:
        raise ContextInputError(f"input TSV is unavailable: {path.name}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ContextInputError(f"input TSV must be a non-symlink regular file: {path.name}")
    size = info.st_size
    if size > max_bytes:
        raise ContextInputError(f"input TSV exceeds its byte bound: {path.name}")
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            fields = [clean(field) for field in (reader.fieldnames or [])]
            if not fields or any(not field for field in fields) or len(fields) != len(set(fields)):
                raise ContextInputError(f"input TSV has invalid headers: {path.name}")
            missing = sorted(set(required_fields).difference(fields))
            if missing:
                raise ContextInputError(f"input TSV requires {missing[0]}: {path.name}")
            rows: list[dict[str, str]] = []
            for index, raw in enumerate(reader, start=1):
                if index > max_rows:
                    raise ContextInputError(f"input TSV exceeds its row bound: {path.name}")
                if None in raw:
                    raise ContextInputError(f"input TSV has extra values: {path.name}")
                rows.append({field: clean(raw.get(field)) for field in fields})
    except (csv.Error, UnicodeError) as exc:
        raise ContextInputError(f"input TSV is malformed: {path.name}") from exc
    return fields, rows


@dataclass(frozen=True, order=True)
class RegionMember:
    genome: str
    taxon: str
    region: str


@dataclass(frozen=True)
class SequenceStats:
    canonical: int
    ambiguous: int
    gc: int

    @property
    def total(self) -> int:
        return self.canonical + self.ambiguous

    @property
    def canonical_fraction(self) -> float:
        return self.canonical / self.total if self.total else 0.0

    @property
    def gc_percent(self) -> float | None:
        return 100.0 * self.gc / self.canonical if self.canonical else None


@dataclass(frozen=True)
class RegionContext:
    sequence: SequenceStats
    mobile_feature_count: int
    edge_status: str


@dataclass(frozen=True)
class SyntenyObservation:
    supported: bool
    ordered_matches: int
    homolog_pairs: int
    order_fraction: float
    min_cluster_coverage: float
    stable_key: str

    @property
    def rank(self) -> tuple[object, ...]:
        return (
            int(self.supported),
            self.order_fraction,
            self.min_cluster_coverage,
            self.homolog_pairs,
            self.stable_key,
        )


@dataclass(frozen=True)
class ReferenceObservation:
    supported: bool
    accession: str
    similarity: float | None
    method: str
    match_count: int | None = None
    coverage: float | None = None
    stable_key: str = ""

    @property
    def rank(self) -> tuple[object, ...]:
        # These producers expose different quantities. Never rank antiSMASH
        # reference-gene match coverage against Clinker protein similarity.
        method_priority = {
            "clinker_MIBiG_median_protein_similarity": 2,
            "antiSMASH_KnownClusterBlast_reference_gene_match_coverage": 1,
        }.get(self.method, 0)
        return (
            int(self.supported),
            method_priority,
            self.coverage if self.coverage is not None else -1.0,
            self.match_count if self.match_count is not None else -1,
            self.similarity if self.similarity is not None else -1.0,
            self.accession,
            self.stable_key,
        )


def crosswalk_members(path: Path, selected: set[str]) -> dict[str, tuple[RegionMember, ...]]:
    _, rows = read_tsv(
        path,
        max_bytes=MAX_CROSSWALK_BYTES,
        max_rows=MAX_CROSSWALK_ROWS,
        required_fields=("genome", "taxon_group", "antismash_region", "gcf_id"),
    )
    members: dict[str, set[RegionMember]] = {family: set() for family in selected}
    membership_count = 0
    for row in rows:
        genome = safe_component(row.get("genome"))
        taxon = normalized_taxon(row.get("taxon_group"))
        region = safe_component(row.get("antismash_region"))
        if not genome or not taxon or not region:
            continue
        member = RegionMember(genome, taxon, region)
        for family in split_families(row.get("gcf_id")):
            if family in members:
                if member not in members[family]:
                    membership_count += 1
                    if membership_count > MAX_CONTEXT_MEMBERS:
                        raise ContextInputError("selected context exceeds its member bound")
                members[family].add(member)
    return {family: tuple(sorted(values)) for family, values in members.items()}


def parse_percent(value: object) -> float | None:
    text = clean(value).rstrip("%").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 100.0 else None


def ranking_references(path: Path, selected: set[str]) -> dict[str, ReferenceObservation]:
    _, rows = read_tsv(
        path,
        max_bytes=MAX_RANKING_BYTES,
        max_rows=MAX_RANKING_ROWS,
        optional=True,
    )
    best: dict[str, ReferenceObservation] = {}
    for row_number, row in enumerate(rows, start=2):
        family_text = row.get("resolved_gcf_ids") or row.get("gcf_selected_id") or row.get("gcf_id")
        families = set(split_families(family_text)).intersection(selected)
        if not families:
            continue
        accession_text = row.get("antismash_knowncluster_accession") or ""
        match = MIBIG_RE.search(accession_text)
        if match is None:
            match = MIBIG_RE.search(row.get("nearest_mibig_or_annotation_if_available") or "")
        if match is None:
            continue
        accession = match.group(1).upper()
        similarity = parse_percent(row.get("antismash_knowncluster_similarity_score"))
        observation = ReferenceObservation(
            supported=similarity is not None and similarity >= 50.0,
            accession=accession,
            similarity=similarity,
            method="antiSMASH_KnownClusterBlast_reference_gene_match_coverage",
            stable_key=f"ranking-{row_number:09d}",
        )
        for family in families:
            current = best.get(family)
            if current is None or observation.rank > current.rank:
                best[family] = observation
    return best


def taxonomy_by_genome(path: Path) -> dict[str, str]:
    _, rows = read_tsv(
        path,
        max_bytes=MAX_MANIFEST_BYTES,
        max_rows=MAX_MANIFEST_ROWS,
        required_fields=("genome_id", "taxon_group"),
        optional=True,
    )
    output: dict[str, str] = {}
    for row in rows:
        genome = safe_component(row.get("genome_id"))
        taxon = normalized_taxon(row.get("taxon_group"))
        if genome and taxon and genome not in output:
            output[genome] = taxon
    return output


def longest_increasing(values: Sequence[int]) -> int:
    tails: list[int] = []
    for value in values:
        index = bisect.bisect_left(tails, value)
        if index == len(tails):
            tails.append(value)
        else:
            tails[index] = value
    return len(tails)


def cluster_gene_positions(cluster: dict[str, object]) -> dict[str, int]:
    ordered: list[tuple[int, int, int, str]] = []
    for locus_index, locus in enumerate(cluster.get("loci", []) or []):
        if not isinstance(locus, dict):
            continue
        for gene in locus.get("genes", []) or []:
            if not isinstance(gene, dict):
                continue
            uid = clean(gene.get("uid"))
            if not uid:
                continue
            try:
                start = int(gene.get("start", 0))
                end = int(gene.get("end", start))
            except (TypeError, ValueError):
                start = end = 0
            ordered.append((locus_index, min(start, end), max(start, end), uid))
    ordered.sort()
    return {item[3]: index for index, item in enumerate(ordered)}


def bounded_panel_payload(path: Path, remaining_bytes: int) -> tuple[dict[str, object], int]:
    with path.open("r", encoding="utf-8") as handle:
        size = os.fstat(handle.fileno()).st_size
        if size > MAX_PANEL_BYTES or size > remaining_bytes:
            raise ContextInputError("clinker panel exceeds its byte bound")
        # Bound the read even if a concurrently replaced/growing local artifact
        # no longer matches the descriptor size observed above.
        text = handle.read(MAX_PANEL_BYTES + 1)
        if len(text) > MAX_PANEL_BYTES:
            raise ContextInputError("clinker panel exceeds its read bound")
    marker = "const data="
    start = text.find(marker)
    if start < 0:
        raise ContextInputError("clinker panel has no bounded data payload")
    start += len(marker)
    end = text.find(";function serialise", start)
    if end < 0:
        raise ContextInputError("clinker panel data payload is incomplete")
    payload = json.loads(text[start:end])
    if not isinstance(payload, dict):
        raise ContextInputError("clinker panel data payload is not an object")
    return payload, size


def bounded_panel_manifests(clinker_root: Path) -> list[Path]:
    manifests: list[Path] = []
    pending_directories = [clinker_root]
    seen_directories = {clinker_root}
    scanned_directories = 0
    scanned_entries = 0
    while pending_directories:
        current = pending_directories.pop()
        scanned_directories += 1
        if scanned_directories > MAX_PANEL_SCAN_DIRS:
            raise ContextInputError("clinker panel scan exceeds its directory bound")
        child_directories: list[Path] = []
        has_manifest = False
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    scanned_entries += 1
                    if scanned_entries > MAX_PANEL_SCAN_ENTRIES:
                        raise ContextInputError(
                            "clinker panel scan exceeds its entry bound"
                        )
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.name == "panel_manifest.tsv" and entry.is_file(
                            follow_symlinks=False
                        ):
                            has_manifest = True
                            continue
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        resolved = Path(entry.path).resolve(strict=True)
                        resolved.relative_to(clinker_root)
                        if resolved not in seen_directories:
                            seen_directories.add(resolved)
                            child_directories.append(resolved)
                    except (OSError, ValueError):
                        continue
        except ContextInputError:
            raise
        except OSError:
            continue

        if has_manifest:
            try:
                relative = (current / "panel_manifest.tsv").relative_to(clinker_root)
            except ValueError:
                relative = None
            if relative is not None:
                manifest = contained_regular_file(clinker_root, *relative.parts)
                if manifest is not None:
                    manifests.append(manifest)
                    if len(manifests) >= MAX_PANELS:
                        return manifests

        child_directories.sort(
            key=lambda path: path.relative_to(clinker_root).as_posix()
        )
        pending_directories.extend(reversed(child_directories))
    return manifests

def panel_observations(
    clinker_root: Path | None,
    taxon_by_genome: dict[str, str],
    selected: set[str],
) -> tuple[dict[str, SyntenyObservation], dict[str, ReferenceObservation]]:
    synteny: dict[str, SyntenyObservation] = {}
    references: dict[str, ReferenceObservation] = {}
    if clinker_root is None:
        return synteny, references
    manifests = bounded_panel_manifests(clinker_root)
    consumed_bytes = 0
    for manifest_index, manifest_path in enumerate(manifests):
        try:
            manifest_size = manifest_path.stat().st_size
            if manifest_size > MAX_PANEL_TOTAL_BYTES - consumed_bytes:
                break
            # Charge each candidate artifact before parsing so malformed panels
            # cannot bypass the cumulative I/O/memory budget.
            consumed_bytes += manifest_size
            _, manifest_rows = read_tsv(
                manifest_path,
                max_bytes=MAX_MANIFEST_BYTES,
                max_rows=MAX_PANEL_CLUSTERS,
                required_fields=("order", "role", "genome", "gcf_id"),
            )
            manifest_rows.sort(key=lambda row: (int(row.get("order") or 0), row.get("genome", "")))
            panel_relative = manifest_path.parent.relative_to(clinker_root) / "panel.html"
            html_path = contained_regular_file(clinker_root, *panel_relative.parts)
            if html_path is None:
                continue
            panel_size = html_path.stat().st_size
            if panel_size > MAX_PANEL_TOTAL_BYTES - consumed_bytes:
                break
            consumed_bytes += panel_size
            # Passing the precharged size also detects a file that grows
            # between accounting and the bounded open/read.
            payload, _ = bounded_panel_payload(html_path, panel_size)
        except (ContextInputError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
            continue
        clusters = payload.get("clusters", [])
        links = payload.get("links", [])
        if not isinstance(clusters, list) or not isinstance(links, list):
            continue
        if not (2 <= len(clusters) <= MAX_PANEL_CLUSTERS) or len(clusters) != len(manifest_rows):
            continue
        if len(links) > MAX_PANEL_LINKS:
            continue
        positions: list[dict[str, int]] = []
        uid_location: dict[str, tuple[int, int]] = {}
        total_genes = 0
        for cluster_index, cluster in enumerate(clusters):
            if not isinstance(cluster, dict):
                positions.append({})
                continue
            cluster_positions = cluster_gene_positions(cluster)
            positions.append(cluster_positions)
            total_genes += len(cluster_positions)
            for uid, position in cluster_positions.items():
                uid_location.setdefault(uid, (cluster_index, position))
        if total_genes > MAX_PANEL_GENES:
            continue

        by_pair: dict[tuple[int, int], list[tuple[float, float, int, int, str, str]]] = {}
        for link in links:
            if not isinstance(link, dict):
                continue
            query = link.get("query", {})
            target = link.get("target", {})
            if not isinstance(query, dict) or not isinstance(target, dict):
                continue
            query_uid = clean(query.get("uid"))
            target_uid = clean(target.get("uid"))
            query_location = uid_location.get(query_uid)
            target_location = uid_location.get(target_uid)
            if query_location is None or target_location is None:
                continue
            qi, qp = query_location
            ti, tp = target_location
            if qi == ti:
                continue
            try:
                similarity = float(link.get("similarity", 0.0))
                identity = float(link.get("identity", 0.0))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(similarity) or not 0.0 < similarity <= 1.0:
                continue
            if not math.isfinite(identity) or not MIN_CLINKER_LINK_IDENTITY <= identity <= 1.0:
                continue
            if qi > ti:
                qi, ti = ti, qi
                qp, tp = tp, qp
                query_uid, target_uid = target_uid, query_uid
            by_pair.setdefault((qi, ti), []).append(
                (similarity, identity, qp, tp, query_uid, target_uid)
            )

        for (left_index, right_index), pair_links in sorted(by_pair.items()):
            chosen: list[tuple[float, float, int, int, str, str]] = []
            used_left: set[str] = set()
            used_right: set[str] = set()
            for link in sorted(
                pair_links,
                key=lambda item: (-item[0], -item[1], item[2], item[3], item[4], item[5]),
            ):
                if link[4] in used_left or link[5] in used_right:
                    continue
                used_left.add(link[4])
                used_right.add(link[5])
                chosen.append(link)
            if not chosen:
                continue
            ordered = sorted((item[2], item[3]) for item in chosen)
            right_positions = [item[1] for item in ordered]
            ordered_matches = max(
                longest_increasing(right_positions),
                longest_increasing([-value for value in right_positions]),
            )
            homolog_pairs = len(chosen)
            order_fraction = ordered_matches / homolog_pairs
            larger_cluster = max(len(positions[left_index]), len(positions[right_index]))
            coverage = homolog_pairs / larger_cluster if larger_cluster else 0.0

            left_row = manifest_rows[left_index]
            right_row = manifest_rows[right_index]
            left_families = set(split_families(left_row.get("gcf_id")))
            right_families = set(split_families(right_row.get("gcf_id")))
            families = left_families.intersection(right_families).intersection(selected)
            if not families:
                continue
            left_role = clean(left_row.get("role")).casefold()
            right_role = clean(right_row.get("role")).casefold()
            stable_key = f"panel-{manifest_index:04d}-{left_index:03d}-{right_index:03d}"

            if "mibig_reference" in {left_role, right_role}:
                reference_index = left_index if left_role == "mibig_reference" else right_index
                reference_row = manifest_rows[reference_index]
                accession_match = MIBIG_RE.search(
                    f"{reference_row.get('genome', '')} {reference_row.get('antismash_region', '')}"
                )
                if accession_match is None:
                    continue
                similarities = [item[0] for item in chosen if item[0] > 0.0]
                similarity = statistics.median(similarities) if similarities else None
                reference_gene_count = len(positions[reference_index])
                reference_coverage = homolog_pairs / reference_gene_count if reference_gene_count else 0.0
                supported = bool(
                    homolog_pairs >= MIN_REFERENCE_PAIRS
                    and reference_coverage >= MIN_REFERENCE_COVERAGE
                    and similarity is not None
                    and similarity >= MIN_REFERENCE_SIMILARITY
                )
                observation = ReferenceObservation(
                    supported=supported,
                    accession=accession_match.group(1).upper(),
                    similarity=100.0 * similarity if similarity is not None else None,
                    method="clinker_MIBiG_median_protein_similarity",
                    match_count=homolog_pairs,
                    coverage=reference_coverage,
                    stable_key=stable_key,
                )
                for family in families:
                    current = references.get(family)
                    if current is None or observation.rank > current.rank:
                        references[family] = observation
                continue

            left_genome = clean(left_row.get("genome"))
            right_genome = clean(right_row.get("genome"))
            left_taxon = taxon_by_genome.get(left_genome, "")
            right_taxon = taxon_by_genome.get(right_genome, "")
            if {left_taxon, right_taxon} != {"fungi", "bacteria"}:
                continue
            supported = bool(
                homolog_pairs >= MIN_SYNTENY_PAIRS
                and order_fraction >= MIN_SYNTENY_ORDER_FRACTION
                and coverage >= MIN_SYNTENY_CLUSTER_COVERAGE
            )
            observation = SyntenyObservation(
                supported=supported,
                ordered_matches=ordered_matches,
                homolog_pairs=homolog_pairs,
                order_fraction=order_fraction,
                min_cluster_coverage=coverage,
                stable_key=stable_key,
            )
            for family in families:
                current = synteny.get(family)
                if current is None or observation.rank > current.rank:
                    synteny[family] = observation
    return synteny, references


def sequence_counts(text: str) -> tuple[int, int, int]:
    canonical = ambiguous = gc = 0
    for character in text:
        upper = character.upper()
        if upper in {"A", "C", "G", "T"}:
            canonical += 1
            if upper in {"G", "C"}:
                gc += 1
        elif character.isalpha():
            ambiguous += 1
    return canonical, ambiguous, gc


def iter_text_chunks(handle: object) -> Iterable[tuple[str, bool, bool]]:
    line_start = True
    while True:
        chunk = handle.readline(MAX_TEXT_CHUNK_CHARS)
        if not chunk:
            return
        line_end = chunk.endswith("\n") or len(chunk) < MAX_TEXT_CHUNK_CHARS
        yield chunk, line_start, line_end
        line_start = line_end


def parse_region_context(path: Path) -> RegionContext:
    if path.stat().st_size > MAX_REGION_BYTES:
        raise ContextInputError("antiSMASH region exceeds its byte bound")
    canonical = ambiguous = gc = 0
    in_origin = False
    feature_key = ""
    feature_chunks: list[str] = []
    mobile_count = 0
    edge_values: list[str] = []

    def flush_feature() -> None:
        nonlocal mobile_count, feature_chunks
        if not feature_key:
            feature_chunks = []
            return
        text = " ".join(feature_chunks)[:32_768]
        if feature_key == "mobile_element" or MOBILE_RE.search(text):
            mobile_count += 1
        feature_chunks = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line, line_start, line_end in iter_text_chunks(handle):
            if line_start and line.startswith("ORIGIN"):
                flush_feature()
                in_origin = True
                continue
            if in_origin:
                if line_start and line.startswith("//"):
                    in_origin = False
                    continue
                line_canonical, line_ambiguous, line_gc = sequence_counts(line)
                canonical += line_canonical
                ambiguous += line_ambiguous
                gc += line_gc
                continue
            edge_match = CONTIG_EDGE_RE.search(line)
            if not line_start or not line_end:
                raise ContextInputError("antiSMASH annotation line exceeds its memory bound")
            if edge_match:
                edge_values.append(edge_match.group(1).casefold())
            feature_match = FEATURE_START_RE.match(line)
            if feature_match:
                flush_feature()
                feature_key = feature_match.group(1).casefold()
                continue
            qualifier_match = QUALIFIER_RE.match(line)
            if qualifier_match and feature_key in {
                "cds",
                "gene",
                "misc_feature",
                "mobile_element",
                "repeat_region",
            }:
                qualifier = qualifier_match.group(1).casefold()
                if qualifier in {"gene", "product", "function", "note", "mobile_element_type"}:
                    feature_chunks.append(qualifier_match.group(2).strip().strip('"'))
            elif feature_chunks and line.startswith(" " * 21):
                feature_chunks.append(line.strip().strip('"'))
    flush_feature()
    if "true" in edge_values:
        edge_status = "concern"
    elif "false" in edge_values:
        edge_status = "clear"
    else:
        edge_status = "unknown"
    return RegionContext(
        sequence=SequenceStats(canonical, ambiguous, gc),
        mobile_feature_count=mobile_count,
        edge_status=edge_status,
    )


def count_sequence_file(path: Path) -> SequenceStats:
    if path.stat().st_size > MAX_GENOME_BYTES:
        raise ContextInputError("normalized genome exceeds its byte bound")
    fasta = path.suffix.casefold() in {".fa", ".fasta", ".fna", ".fsa"}
    in_origin = False
    canonical = ambiguous = gc = 0
    skipping_fasta_header = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line, line_start, line_end in iter_text_chunks(handle):
            if fasta:
                if line_start:
                    skipping_fasta_header = line.startswith(">")
                if skipping_fasta_header:
                    if line_end:
                        skipping_fasta_header = False
                    continue
            else:
                if line_start and line.startswith("ORIGIN"):
                    in_origin = True
                    continue
                if line_start and line.startswith("//"):
                    in_origin = False
                    continue
                if not in_origin:
                    continue
            line_canonical, line_ambiguous, line_gc = sequence_counts(line)
            canonical += line_canonical
            ambiguous += line_ambiguous
            gc += line_gc
    return SequenceStats(canonical, ambiguous, gc)


def exact_genome_path(genomes_root: Path | None, project_name: str, member: RegionMember) -> Path | None:
    if genomes_root is None:
        return None
    suffixes = (".fna", ".fasta", ".fa", ".fsa", ".gbff", ".gbk", ".gb")
    for suffix in suffixes:
        candidate = contained_regular_file(genomes_root, member.taxon, project_name, f"{member.genome}{suffix}")
        if candidate is not None:
            return candidate
    return None


def exact_region_path(antismash_root: Path | None, member: RegionMember) -> Path | None:
    if antismash_root is None:
        return None
    filename = member.region if member.region.casefold().endswith(".gbk") else f"{member.region}.gbk"
    return contained_regular_file(antismash_root, member.genome, filename)


def choose_reference(
    first: ReferenceObservation | None,
    second: ReferenceObservation | None,
) -> ReferenceObservation | None:
    if first is None:
        return second
    if second is None:
        return first
    return first if first.rank >= second.rank else second


def fill(row: dict[str, str], field: str, value: object) -> None:
    if clean(row.get(field)):
        return
    text = clean(value)
    if text:
        row[field] = text


def enrich_rows(
    rows: list[dict[str, str]],
    members: dict[str, tuple[RegionMember, ...]],
    ranking_reference: dict[str, ReferenceObservation],
    panel_synteny: dict[str, SyntenyObservation],
    panel_reference: dict[str, ReferenceObservation],
    antismash_root: Path | None,
    genomes_root: Path | None,
    project_name: str,
) -> list[dict[str, str]]:
    region_cache: dict[RegionMember, RegionContext | None] = {}
    genome_cache: dict[tuple[str, str], SequenceStats | None] = {}
    parsed_regions = 0
    region_bytes = 0
    parsed_genomes = 0
    genome_bytes = 0
    enriched: list[dict[str, str]] = []
    for row_number, source in enumerate(rows, start=2):
        row = dict(source)
        family = clean(row.get("gcf_id"))
        synteny = panel_synteny.get(family)
        if synteny is not None:
            fill(row, "synteny_support", "yes" if synteny.supported else "no")
            fill(row, "synteny_gene_order_matches", synteny.ordered_matches)
            fill(row, "synteny_gene_count", synteny.homolog_pairs)
            fill(row, "synteny_gene_order_fraction", format_number(synteny.order_fraction))
            fill(row, "synteny_homolog_pair_count", synteny.homolog_pairs)
            fill(row, "synteny_min_cluster_coverage", format_number(synteny.min_cluster_coverage))
            fill(row, "synteny_basis", "cross_domain_dataset_clinker")
            fill(row, "synteny_method", "clinker_homolog_order_LIS_or_reverse")

        reference = choose_reference(ranking_reference.get(family), panel_reference.get(family))
        if reference is not None:
            fill(row, "characterized_reference_support", "yes" if reference.supported else "no")
            fill(row, "characterized_reference_id", reference.accession)
            if reference.similarity is not None:
                fill(
                    row,
                    "characterized_reference_similarity_percent",
                    format_number(reference.similarity),
                )
            fill(row, "characterized_reference_method", reference.method)
            if reference.match_count is not None:
                fill(row, "characterized_reference_match_count", reference.match_count)
            if reference.coverage is not None:
                fill(row, "characterized_reference_coverage", format_number(reference.coverage))

        contexts: list[tuple[RegionMember, RegionContext]] = []
        composition: list[tuple[float, str, str, float, float]] = []
        for member in members.get(family, ()):
            if member not in region_cache:
                if parsed_regions >= MAX_REGION_FILES:
                    region_cache[member] = None
                else:
                    region_path = exact_region_path(antismash_root, member)
                    if region_path is None:
                        region_cache[member] = None
                    else:
                        try:
                            region_size = region_path.stat().st_size
                        except OSError:
                            region_cache[member] = None
                        else:
                            if (
                                region_size > MAX_REGION_BYTES
                                or region_bytes + region_size > MAX_REGION_TOTAL_BYTES
                            ):
                                region_cache[member] = None
                            else:
                                parsed_regions += 1
                                region_bytes += region_size
                                try:
                                    region_cache[member] = parse_region_context(region_path)
                                except (ContextInputError, OSError):
                                    region_cache[member] = None
            context = region_cache[member]
            if context is None:
                continue
            contexts.append((member, context))
            genome_key = (member.taxon, member.genome)
            if genome_key not in genome_cache:
                genome_path = exact_genome_path(genomes_root, project_name, member)
                if genome_path is None:
                    genome_cache[genome_key] = None
                else:
                    try:
                        genome_size = genome_path.stat().st_size
                    except OSError:
                        genome_cache[genome_key] = None
                    else:
                        if (
                            parsed_genomes >= MAX_GENOME_FILES
                            or genome_size > MAX_GENOME_BYTES
                            or genome_bytes + genome_size > MAX_GENOME_TOTAL_BYTES
                        ):
                            genome_cache[genome_key] = None
                        else:
                            parsed_genomes += 1
                            genome_bytes += genome_size
                            try:
                                genome_cache[genome_key] = count_sequence_file(genome_path)
                            except (ContextInputError, OSError):
                                genome_cache[genome_key] = None
            genome_stats = genome_cache[genome_key]
            region_stats = context.sequence
            if (
                genome_stats is None
                or region_stats.canonical < MIN_REGION_CANONICAL_BASES
                or genome_stats.canonical < MIN_GENOME_CANONICAL_BASES
                or region_stats.canonical_fraction < MIN_CANONICAL_FRACTION
                or genome_stats.canonical_fraction < MIN_CANONICAL_FRACTION
                or region_stats.gc_percent is None
                or genome_stats.gc_percent is None
            ):
                continue
            delta = abs(region_stats.gc_percent - genome_stats.gc_percent)
            composition.append(
                (
                    delta,
                    member.genome,
                    member.region,
                    region_stats.gc_percent,
                    genome_stats.gc_percent,
                )
            )

        if contexts:
            mobile_count = sum(context.mobile_feature_count for _, context in contexts)
            fill(row, "mobile_element_context", "present" if mobile_count else "absent")
            fill(row, "mobile_element_count", mobile_count)
            fill(row, "mobile_element_method", "antiSMASH_region_annotation_lexicon")
            edge_values = [context.edge_status for _, context in contexts]
            if "concern" in edge_values:
                edge_context = "concern"
                fill(row, "assembly_check", "concern")
            elif edge_values and all(value == "clear" for value in edge_values):
                edge_context = "clear"
            else:
                edge_context = "not_tested"
            fill(row, "assembly_region_edge_context", edge_context)
            fill(row, "assembly_check", "not_tested")
            fill(row, "assembly_context_method", "antiSMASH_region_contig_edge")
            fill(row, "assembly_context_scope", "all_available_candidate_regions")
        else:
            fill(row, "assembly_region_edge_context", "not_tested")
            fill(row, "assembly_check", "not_tested")

        if composition:
            delta, _, _, region_gc, genome_gc = max(
                composition,
                key=lambda item: (item[0], item[1], item[2]),
            )
            fill(
                row,
                "composition_deviation",
                "yes" if delta >= COMPOSITION_DEVIATION_DELTA_PERCENT else "no",
            )
            fill(row, "composition_region_gc_percent", format_number(region_gc))
            fill(row, "composition_genome_gc_percent", format_number(genome_gc))
            fill(row, "composition_gc_delta_percent", format_number(delta))
            fill(row, "composition_method", "BGC_vs_whole_assembly_GC_abs_delta_ge_10pp_heuristic")
            fill(row, "composition_deviation_scope", "maximum_across_evaluated_candidate_regions")
            fill(row, "composition_evaluated_region_count", len(composition))

        # A dedicated contamination screen is not part of the existing core
        # artifacts.  Never manufacture a pass from taxonomy or composition.
        fill(row, "contamination_check", "not_tested")
        fill(row, "contamination_method", "not_run_no_dedicated_screen")
        fill(row, "paralogy_check", "not_tested")
        fill(row, "sampling_check", "not_tested")
        fill(row, "conserved_enzyme_risk", "not_tested")
        fill(row, "long_branch_attraction_risk", "not_tested")

        for field, value in row.items():
            validate_public_value(field, value, row_number)
        enriched.append(row)
    return enriched


def atomic_write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def enrich(args: argparse.Namespace) -> int:
    if not args.explicit_request:
        raise ContextInputError("--explicit-request is required")
    if not 1 <= args.max_candidates <= HARD_MAX_CANDIDATES:
        raise ContextInputError("--max-candidates must be between 1 and 100")
    project_name = safe_project_name(args.project_name)
    if not project_name:
        raise ContextInputError("--project-name must be one safe path component")
    antismash_root = canonical_directory(args.antismash_root, "antiSMASH root", optional=True)
    clinker_root = canonical_directory(args.clinker_root, "Clinker root", optional=True)
    genomes_root = canonical_directory(args.genomes_root, "genomes root", optional=True)

    headers, rows = read_candidate_rows(args.candidates, args.max_candidates)
    selected = {clean(row.get("gcf_id")) for row in rows}
    members = crosswalk_members(args.crosswalk, selected)
    ranking_reference = ranking_references(args.ranking, selected)
    taxon_map = taxonomy_by_genome(args.taxon_manifest)
    panel_synteny, panel_reference = panel_observations(clinker_root, taxon_map, selected)
    enriched = enrich_rows(
        rows,
        members,
        ranking_reference,
        panel_synteny,
        panel_reference,
        antismash_root,
        genomes_root,
        project_name,
    )
    output_fields = list(headers)
    for field in CONTEXT_FIELDS:
        if field not in output_fields:
            output_fields.append(field)
    for row in enriched:
        for field in output_fields:
            row.setdefault(field, "")
    atomic_write_tsv(args.output, output_fields, enriched)
    return len(enriched)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explicit-request", action="store_true")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--ranking", type=Path, required=True)
    parser.add_argument("--taxon-manifest", type=Path, required=True)
    parser.add_argument("--antismash-root", type=Path, required=True)
    parser.add_argument("--clinker-root", type=Path, required=True)
    parser.add_argument("--genomes-root", type=Path, required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-candidates", type=int, default=25)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        count = enrich(parse_args(argv))
    except (ContextInputError, EvidenceInputError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        message = re.sub(r"[^A-Za-z0-9_. -]+", "_", str(exc))[:180]
        print(f"CONTEXT_EVIDENCE_ENRICH status=failed message={message}")
        return 2
    print(f"CONTEXT_EVIDENCE_ENRICH status=success candidates_enriched={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
