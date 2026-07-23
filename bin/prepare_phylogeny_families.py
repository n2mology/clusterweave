#!/usr/bin/env python3
"""Prepare bounded cross-domain protein-family inputs for optional phylogeny.

The helper is intentionally dependency-free and explicit-request only.  It
does not infer homology from sequence similarity.  Instead, it groups proteins
only when antiSMASH wrote the same stable smCOG or biosynthetic-domain
annotation on their CDS features within a shortlisted cross-domain GCF.

All generated FASTAs and sequence mappings are private phylogeny inputs.  They
are not part of ClusterWeave's public result allowlist.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


SCHEMA_VERSION = "clusterweave-phylogeny-family-inputs-v1"
MAX_CANDIDATE_BYTES = 2 * 1024 * 1024
MAX_CROSSWALK_BYTES = 16 * 1024 * 1024
MAX_CROSSWALK_ROWS = 100_000
HARD_MAX_CANDIDATES = 100
HARD_MAX_FAMILIES = 100
HARD_MAX_SEQUENCES_PER_FAMILY = 1_000
HARD_MAX_REGIONS_PER_CANDIDATE = 500
HARD_MAX_REGION_BYTES = 100 * 1024 * 1024
HARD_MAX_TOTAL_INPUT_BYTES = 2 * 1024 * 1024 * 1024
HARD_MAX_TOTAL_OUTPUT_BYTES = 200 * 1024 * 1024
MAX_CDS_PER_REGION = 10_000
MAX_TRANSLATION_AA = 50_000
MIN_TRANSLATION_AA = 10

SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+@-]{0,199}$")
SAFE_GCF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+\-]{0,127}$")
SMCOG_RE = re.compile(r"\bSMCOG\d+\b", re.IGNORECASE)
PFAM_RE = re.compile(r"\bPF\d{4,7}\b", re.IGNORECASE)
AA_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYBXZJUO*]+$", re.IGNORECASE)

FAMILY_FIELDS = (
    "family_id",
    "taxon_group",
    "input_path",
    "sequence_map_path",
    "gcf_id",
    "annotation_key",
    "sequence_count",
    "fungal_sequence_count",
    "bacterial_sequence_count",
    "region_count",
    "schema_version",
)
MAP_FIELDS = (
    "sequence_id",
    "family_id",
    "gcf_id",
    "annotation_key",
    "genome_id",
    "taxon_group",
    "region_id",
    "cds_id",
)
DIAGNOSTIC_FIELDS = (
    "gcf_id",
    "genome_id",
    "taxon_group",
    "region_id",
    "status",
    "message",
)


class PreparationError(ValueError):
    """Raised when bounded family preparation cannot safely continue."""


@dataclass(frozen=True)
class Protein:
    genome_id: str
    taxon_group: str
    region_id: str
    cds_id: str
    translation: str
    annotation_keys: tuple[str, ...]


@dataclass(frozen=True)
class FamilyMember:
    sequence_id: str
    family_id: str
    gcf_id: str
    annotation_key: str
    protein: Protein


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def safe_identifier(value: str, *, limit: int = 80) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")[:limit]
    return text or "family"


def normalized_annotation(value: str) -> str:
    text = re.sub(r"\([^)]*(?:e-value|score|bitscore)[^)]*\)", "", value, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:e-value|score|bitscore)\s*[:=].*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^A-Za-z0-9_.+-]+", "_", text).strip("._-").casefold()
    return text[:96]


def split_gcf_ids(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[;,]", value) if item.strip()]


def bounded_rows(path: Path, *, max_bytes: int, max_rows: int) -> tuple[list[str], list[dict[str, str]]]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PreparationError(f"input TSV is unavailable: {path.name}") from exc
    if size > max_bytes:
        raise PreparationError(f"input TSV exceeds the {max_bytes}-byte bound: {path.name}")
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            fields = [clean(field) for field in (reader.fieldnames or [])]
            if not fields or any(not field for field in fields) or len(fields) != len(set(fields)):
                raise PreparationError(f"input TSV has invalid headers: {path.name}")
            rows: list[dict[str, str]] = []
            for index, raw in enumerate(reader, 1):
                if index > max_rows:
                    raise PreparationError(f"input TSV exceeds the {max_rows}-row bound: {path.name}")
                rows.append({field: clean(raw.get(field)) for field in fields})
    except UnicodeError as exc:
        raise PreparationError(f"input TSV must be valid UTF-8: {path.name}") from exc
    return fields, rows


def read_candidates(path: Path, max_candidates: int) -> list[str]:
    fields, rows = bounded_rows(
        path, max_bytes=MAX_CANDIDATE_BYTES, max_rows=HARD_MAX_CANDIDATES + 1
    )
    if "gcf_id" not in fields:
        raise PreparationError("candidate TSV requires gcf_id")
    if len(rows) > max_candidates:
        raise PreparationError("candidate TSV exceeds the explicit candidate bound")
    candidates: list[str] = []
    for number, row in enumerate(rows, 2):
        gcf_id = row["gcf_id"]
        if not SAFE_GCF_RE.fullmatch(gcf_id):
            raise PreparationError(f"candidate TSV row {number} has an unsafe gcf_id")
        cross_domain = clean(
            row.get("cross_domain_gcf") or row.get("cross_domain") or row.get("is_cross_domain")
        ).casefold()
        if cross_domain not in {"1", "true", "yes"}:
            continue
        if gcf_id not in candidates:
            candidates.append(gcf_id)
    return candidates


def read_crosswalk(path: Path, candidates: set[str]) -> dict[str, list[dict[str, str]]]:
    fields, rows = bounded_rows(
        path, max_bytes=MAX_CROSSWALK_BYTES, max_rows=MAX_CROSSWALK_ROWS
    )
    required = {"genome", "taxon_group", "antismash_region", "gcf_id"}
    missing = sorted(required.difference(fields))
    if missing:
        raise PreparationError(f"crosswalk requires column {missing[0]}")
    by_gcf: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen: set[tuple[str, str, str, str]] = set()
    for number, row in enumerate(rows, 2):
        genome = row["genome"]
        taxon = row["taxon_group"].casefold()
        region = row["antismash_region"]
        if taxon not in {"fungi", "bacteria"}:
            continue
        if not SAFE_COMPONENT_RE.fullmatch(genome) or not SAFE_COMPONENT_RE.fullmatch(region):
            raise PreparationError(f"crosswalk row {number} has an unsafe genome or region identifier")
        for gcf_id in split_gcf_ids(row["gcf_id"]):
            if gcf_id not in candidates:
                continue
            key = (gcf_id, genome, taxon, region)
            if key in seen:
                continue
            seen.add(key)
            by_gcf[gcf_id].append(
                {
                    "gcf_id": gcf_id,
                    "genome": genome,
                    "taxon_group": taxon,
                    "antismash_region": region,
                }
            )
    for gcf_id in by_gcf:
        by_gcf[gcf_id].sort(
            key=lambda row: (row["taxon_group"], row["genome"], row["antismash_region"])
        )
    return by_gcf


def resolve_region(root: Path, genome: str, region: str) -> Path | None:
    root_real = root.resolve()
    genome_dir = (root_real / genome).resolve()
    if genome_dir.parent != root_real or not genome_dir.is_dir():
        return None
    names = [region] if region.casefold().endswith(".gbk") else [f"{region}.gbk", region]
    for name in names:
        candidate = (genome_dir / name).resolve()
        if candidate.parent == genome_dir and candidate.is_file():
            return candidate
    return None


def feature_qualifiers(lines: Sequence[str]) -> Iterable[tuple[str, dict[str, list[str]]]]:
    """Yield feature keys and qualifiers from a GenBank FEATURES block."""

    feature_key = ""
    qualifiers: dict[str, list[str]] = defaultdict(list)
    active_qualifier = ""
    active_value: list[str] = []

    def finish_qualifier() -> None:
        nonlocal active_qualifier, active_value
        if active_qualifier:
            value = " ".join(part.strip() for part in active_value).strip()
            if value.startswith('"'):
                value = value[1:]
            if value.endswith('"'):
                value = value[:-1]
            if active_qualifier == "translation":
                value = re.sub(r"\s+", "", value)
            qualifiers[active_qualifier].append(value)
        active_qualifier = ""
        active_value = []

    def finish_feature() -> tuple[str, dict[str, list[str]]] | None:
        finish_qualifier()
        if not feature_key:
            return None
        return feature_key, dict(qualifiers)

    in_features = False
    for line in lines:
        if line.startswith("FEATURES"):
            in_features = True
            continue
        if not in_features:
            continue
        if line.startswith("ORIGIN") or line.startswith("//"):
            result = finish_feature()
            if result is not None:
                yield result
            return
        match = re.match(r"^     (\S+)\s+(.+)$", line)
        if match and not match.group(1).startswith("/"):
            result = finish_feature()
            if result is not None:
                yield result
            feature_key = match.group(1)
            qualifiers = defaultdict(list)
            continue
        qualifier = re.match(r"^\s+/([^=\s]+)(?:=(.*))?$", line)
        if qualifier:
            finish_qualifier()
            active_qualifier = qualifier.group(1)
            active_value = [qualifier.group(2) or ""]
        elif active_qualifier and line.startswith("                     "):
            active_value.append(line.strip())
    result = finish_feature()
    if result is not None:
        yield result


def annotation_keys(qualifiers: dict[str, list[str]]) -> tuple[str, ...]:
    smcogs = sorted(
        {
            match.group(0).upper()
            for value in qualifiers.get("smCOG", []) + qualifiers.get("smcog", [])
            for match in SMCOG_RE.finditer(value)
        }
    )
    if smcogs:
        if len(smcogs) == 1:
            return (f"smcog:{smcogs[0]}",)
        return ("smcog_signature:" + "+".join(smcogs),)

    keys: set[str] = set()
    for value in qualifiers.get("sec_met_domain", []):
        pfams = {match.group(0).upper() for match in PFAM_RE.finditer(value)}
        if pfams:
            keys.update(f"sec_met_domain:{pfam}" for pfam in pfams)
            continue
        token = normalized_annotation(value)
        if token:
            keys.add(f"sec_met_domain:{token}")
    for value in qualifiers.get("NRPS_PKS", []) + qualifiers.get("nrps_pks", []):
        match = re.search(r"\bDomain\s*:\s*([^;]+)", value, flags=re.IGNORECASE)
        token = normalized_annotation(match.group(1) if match else value)
        if token:
            keys.add(f"nrps_pks:{token}")
    ordered = sorted(keys)
    if len(ordered) <= 1:
        return tuple(ordered)
    # Full proteins with different multidomain architectures should not be
    # treated as homologous merely because they share one common catalytic
    # domain.  The fallback therefore requires an identical complete set of
    # explicit antiSMASH domain annotations.
    return ("domain_signature:" + "+".join(ordered),)


def parse_region(
    path: Path,
    *,
    genome: str,
    taxon: str,
    region: str,
    max_region_bytes: int,
) -> list[Protein]:
    size = path.stat().st_size
    if size > max_region_bytes:
        raise PreparationError(f"region {region} exceeds the configured byte bound")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeError as exc:
        raise PreparationError(f"region {region} is not valid UTF-8 GenBank text") from exc
    proteins: list[Protein] = []
    cds_index = 0
    for key, qualifiers in feature_qualifiers(lines):
        if key != "CDS":
            continue
        cds_index += 1
        if cds_index > MAX_CDS_PER_REGION:
            raise PreparationError(f"region {region} exceeds the CDS feature bound")
        translations = qualifiers.get("translation", [])
        if len(translations) != 1:
            continue
        translation = translations[0].strip().rstrip("*").upper()
        if not (MIN_TRANSLATION_AA <= len(translation) <= MAX_TRANSLATION_AA):
            continue
        if not AA_RE.fullmatch(translation):
            continue
        keys = annotation_keys(qualifiers)
        if not keys:
            continue
        cds_id = clean(
            next(iter(qualifiers.get("locus_tag", [])), "")
            or next(iter(qualifiers.get("protein_id", [])), "")
            or f"cds_{cds_index:05d}"
        )
        cds_id = safe_identifier(cds_id, limit=100)
        proteins.append(
            Protein(
                genome_id=genome,
                taxon_group=taxon,
                region_id=region,
                cds_id=cds_id,
                translation=translation,
                annotation_keys=keys,
            )
        )
    return proteins


def family_identifier(gcf_id: str, annotation_key: str) -> str:
    readable = safe_identifier(f"{gcf_id}__{annotation_key}", limit=92)
    digest = hashlib.sha256(f"{gcf_id}\t{annotation_key}".encode()).hexdigest()[:10]
    return f"{readable}__{digest}"


def sequence_identifier(gcf_id: str, annotation_key: str, protein: Protein) -> str:
    payload = "\t".join(
        (gcf_id, annotation_key, protein.genome_id, protein.region_id, protein.cds_id)
    )
    return f"cwseq_{hashlib.sha256(payload.encode()).hexdigest()[:20]}"


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def prepare(args: argparse.Namespace) -> tuple[int, int]:
    if not args.explicit_request:
        raise PreparationError("--explicit-request is required")
    for label, value, hard_max in (
        ("max-candidates", args.max_candidates, HARD_MAX_CANDIDATES),
        ("max-families", args.max_families, HARD_MAX_FAMILIES),
        ("max-sequences-per-family", args.max_sequences_per_family, HARD_MAX_SEQUENCES_PER_FAMILY),
        ("max-regions-per-candidate", args.max_regions_per_candidate, HARD_MAX_REGIONS_PER_CANDIDATE),
        ("max-region-bytes", args.max_region_bytes, HARD_MAX_REGION_BYTES),
        ("max-total-input-bytes", args.max_total_input_bytes, HARD_MAX_TOTAL_INPUT_BYTES),
        ("max-total-output-bytes", args.max_total_output_bytes, HARD_MAX_TOTAL_OUTPUT_BYTES),
    ):
        if value < 1 or value > hard_max:
            raise PreparationError(f"--{label} must be between 1 and {hard_max}")

    candidates = read_candidates(args.candidates, args.max_candidates)
    crosswalk = read_crosswalk(args.crosswalk, set(candidates))
    antismash_root = args.antismash_root.resolve()
    if not antismash_root.is_dir():
        raise PreparationError("antiSMASH result root is unavailable")

    grouped: dict[tuple[str, str], list[Protein]] = defaultdict(list)
    diagnostics: list[dict[str, str]] = []
    seen_region_paths: set[Path] = set()
    total_input_bytes = 0
    for gcf_id in candidates:
        region_rows = crosswalk.get(gcf_id, [])
        if len(region_rows) > args.max_regions_per_candidate:
            raise PreparationError(
                f"candidate {gcf_id} exceeds the configured region bound"
            )
        for row in region_rows:
            genome, taxon, region = (
                row["genome"],
                row["taxon_group"],
                row["antismash_region"],
            )
            path = resolve_region(antismash_root, genome, region)
            if path is None:
                diagnostics.append(
                    {
                        "gcf_id": gcf_id,
                        "genome_id": genome,
                        "taxon_group": taxon,
                        "region_id": region,
                        "status": "missing_region",
                        "message": "assembled root-level antiSMASH region was not found",
                    }
                )
                continue
            if path not in seen_region_paths:
                try:
                    total_input_bytes += path.stat().st_size
                except OSError as exc:
                    raise PreparationError("antiSMASH region size could not be read") from exc
                if total_input_bytes > args.max_total_input_bytes:
                    raise PreparationError(
                        "antiSMASH region inputs exceed the configured aggregate byte bound"
                    )
                seen_region_paths.add(path)
            try:
                proteins = parse_region(
                    path,
                    genome=genome,
                    taxon=taxon,
                    region=region,
                    max_region_bytes=args.max_region_bytes,
                )
            except (OSError, PreparationError) as exc:
                diagnostics.append(
                    {
                        "gcf_id": gcf_id,
                        "genome_id": genome,
                        "taxon_group": taxon,
                        "region_id": region,
                        "status": "invalid_region",
                        "message": safe_identifier(str(exc), limit=180).replace("_", " "),
                    }
                )
                continue
            diagnostics.append(
                {
                    "gcf_id": gcf_id,
                    "genome_id": genome,
                    "taxon_group": taxon,
                    "region_id": region,
                    "status": "parsed",
                    "message": f"{len(proteins)} explicitly annotated proteins",
                }
            )
            for protein in proteins:
                for key in protein.annotation_keys:
                    grouped[(gcf_id, key)].append(protein)

    eligible: list[tuple[str, str, list[Protein]]] = []
    for (gcf_id, key), raw_proteins in grouped.items():
        unique: dict[tuple[str, str, str], Protein] = {}
        for protein in raw_proteins:
            unique.setdefault(
                (protein.genome_id, protein.region_id, protein.cds_id), protein
            )
        proteins = sorted(
            unique.values(),
            key=lambda item: (
                item.taxon_group,
                item.genome_id,
                item.region_id,
                item.cds_id,
            ),
        )
        taxa = {item.taxon_group for item in proteins}
        if taxa != {"fungi", "bacteria"} or len(proteins) < 3:
            continue
        if len(proteins) > args.max_sequences_per_family:
            continue
        eligible.append((gcf_id, key, proteins))
    eligible.sort(
        key=lambda item: (
            -len({protein.genome_id for protein in item[2]}),
            -len(item[2]),
            item[0],
            item[1],
        )
    )
    eligible = eligible[: args.max_families]

    args.output_root.mkdir(parents=True, exist_ok=True)
    families_dir = args.output_root / "families"
    temporary = Path(
        tempfile.mkdtemp(prefix=".families.", dir=str(args.output_root))
    )
    try:
        temporary_families = temporary / "families"
        temporary_families.mkdir()
        map_path = temporary / "sequence_taxon_map.tsv"
        manifest_path = temporary / "families.tsv"
        diagnostics_path = temporary / "family_preparation_diagnostics.tsv"
        manifest_rows: list[dict[str, object]] = []
        mapping_rows: list[dict[str, object]] = []
        total_output_bytes = 0
        for gcf_id, key, proteins in eligible:
            family_id = family_identifier(gcf_id, key)
            members = [
                FamilyMember(
                    sequence_id=sequence_identifier(gcf_id, key, protein),
                    family_id=family_id,
                    gcf_id=gcf_id,
                    annotation_key=key,
                    protein=protein,
                )
                for protein in proteins
            ]
            fasta_path = temporary_families / f"{family_id}.faa"
            with fasta_path.open("w", encoding="utf-8", newline="") as handle:
                for member in members:
                    handle.write(f">{member.sequence_id}\n{member.protein.translation}\n")
            total_output_bytes += fasta_path.stat().st_size
            if total_output_bytes > args.max_total_output_bytes:
                raise PreparationError("prepared FASTA output exceeds the configured byte bound")
            fungal_count = sum(
                member.protein.taxon_group == "fungi" for member in members
            )
            bacterial_count = len(members) - fungal_count
            final_fasta = families_dir / fasta_path.name
            final_map = args.output_root / "sequence_taxon_map.tsv"
            manifest_rows.append(
                {
                    "family_id": family_id,
                    "taxon_group": "both",
                    "input_path": str(final_fasta.resolve()),
                    "sequence_map_path": str(final_map.resolve()),
                    "gcf_id": gcf_id,
                    "annotation_key": key,
                    "sequence_count": len(members),
                    "fungal_sequence_count": fungal_count,
                    "bacterial_sequence_count": bacterial_count,
                    "region_count": len(
                        {(member.protein.genome_id, member.protein.region_id) for member in members}
                    ),
                    "schema_version": SCHEMA_VERSION,
                }
            )
            mapping_rows.extend(
                {
                    "sequence_id": member.sequence_id,
                    "family_id": family_id,
                    "gcf_id": gcf_id,
                    "annotation_key": key,
                    "genome_id": member.protein.genome_id,
                    "taxon_group": member.protein.taxon_group,
                    "region_id": member.protein.region_id,
                    "cds_id": member.protein.cds_id,
                }
                for member in members
            )
        mapping_rows.sort(key=lambda row: (str(row["family_id"]), str(row["sequence_id"])))
        diagnostics.sort(
            key=lambda row: (
                row["gcf_id"], row["taxon_group"], row["genome_id"], row["region_id"]
            )
        )
        write_tsv(manifest_path, FAMILY_FIELDS, manifest_rows)
        write_tsv(map_path, MAP_FIELDS, mapping_rows)
        write_tsv(diagnostics_path, DIAGNOSTIC_FIELDS, diagnostics)
        total_output_bytes += sum(
            path.stat().st_size for path in (manifest_path, map_path, diagnostics_path)
        )
        if total_output_bytes > args.max_total_output_bytes:
            raise PreparationError(
                "prepared family inputs exceed the configured total byte bound"
            )

        if families_dir.exists():
            shutil.rmtree(families_dir)
        os.replace(temporary_families, families_dir)
        for source in (manifest_path, map_path, diagnostics_path):
            os.replace(source, args.output_root / source.name)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return len(eligible), len(mapping_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explicit-request", action="store_true")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--antismash-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-candidates", type=int, default=25)
    parser.add_argument("--max-families", type=int, default=10)
    parser.add_argument("--max-sequences-per-family", type=int, default=250)
    parser.add_argument("--max-regions-per-candidate", type=int, default=100)
    parser.add_argument("--max-region-bytes", type=int, default=25 * 1024 * 1024)
    parser.add_argument("--max-total-input-bytes", type=int, default=250 * 1024 * 1024)
    parser.add_argument("--max-total-output-bytes", type=int, default=50 * 1024 * 1024)
    return parser.parse_args()


def main() -> int:
    try:
        family_count, sequence_count = prepare(parse_args())
    except (OSError, PreparationError) as exc:
        print(f"PHYLOGENY_PREPARE status=failed message={safe_identifier(str(exc), limit=180)}", file=sys.stderr)
        return 2
    status = "success" if family_count else "insufficient_data"
    print(
        f"PHYLOGENY_PREPARE status={status} families={family_count} sequences={sequence_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
