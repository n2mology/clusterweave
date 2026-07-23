#!/usr/bin/env python3
"""Pure validation and normalization for immutable per-genome taxon routes."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import BinaryIO, TextIO


ANALYSIS_SCOPES = frozenset({"fungi", "bacteria", "both"})
TAXON_GROUPS = frozenset({"fungi", "bacteria"})
MAX_ASSIGNMENT_BYTES = 64 * 1024
MAX_ASSIGNMENT_ROWS = 100
INPUT_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
ROUTING_MUTATION_FIELDS = frozenset(
    {
        "analysis_scope",
        "taxon_assignments",
        "taxon_assignments_json",
        "taxon_routes",
        "taxon_counts",
        "applicability_counts",
        "taxonomy_metadata",
    }
)


class TaxonRoutingError(ValueError):
    """Raised when submitted routing state is incomplete or contradictory."""


def normalize_analysis_scope(value: object) -> str:
    """Return a canonical scope, retaining fungi as the historical default."""

    if value is None or str(value).strip() == "":
        return "fungi"
    normalized = str(value).strip().lower()
    if normalized not in ANALYSIS_SCOPES:
        raise TaxonRoutingError(
            "analysis_scope must be one of: fungi, bacteria, both"
        )
    return normalized


def _bounded_text(value: object, label: str, max_bytes: int) -> str:
    if isinstance(value, bytes):
        raw = value
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise TaxonRoutingError(f"{label} must be UTF-8 text") from exc
    else:
        text = str(value or "")
        raw = text.encode("utf-8")
    if len(raw) > max_bytes:
        raise TaxonRoutingError(
            f"{label} exceeds the {max_bytes} byte routing metadata limit"
        )
    return text


def _assignment_key(value: object) -> str:
    key = str(value or "").strip()
    if not INPUT_KEY_RE.fullmatch(key):
        raise TaxonRoutingError(
            "taxon assignment input_key must use 1-120 letters, numbers, dots, "
            "underscores, or hyphens"
        )
    return key


def _assignment_group(value: object) -> str:
    group = str(value or "").strip().lower()
    if group not in TAXON_GROUPS:
        raise TaxonRoutingError(
            "taxon assignment taxon_group must be fungi or bacteria"
        )
    return group


def _add_assignment(
    assignments: dict[str, str],
    canonical_keys: dict[str, str],
    input_key: object,
    taxon_group: object,
) -> None:
    key = _assignment_key(input_key)
    group = _assignment_group(taxon_group)
    normalized = key.casefold()
    previous = assignments.get(normalized)
    if previous is not None and previous != group:
        raise TaxonRoutingError(
            f"Contradictory taxon assignments were supplied for input_key '{key}'"
        )
    assignments[normalized] = group
    canonical_keys.setdefault(normalized, key)


def _canonical_assignment_dict(
    assignments: Mapping[str, str], canonical_keys: Mapping[str, str]
) -> dict[str, str]:
    return {
        canonical_keys[normalized]: assignments[normalized]
        for normalized in sorted(assignments)
    }


def parse_assignment_json(
    value: object,
    *,
    max_bytes: int = MAX_ASSIGNMENT_BYTES,
    max_rows: int = MAX_ASSIGNMENT_ROWS,
) -> dict[str, str]:
    """Parse a bounded JSON form value into ``input_key -> taxon_group``."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return {}
    if isinstance(value, (str, bytes)):
        text = _bounded_text(value, "taxon_assignments JSON", max_bytes)
        if not text.strip():
            return {}

        def reject_conflicting_object_keys(
            pairs: list[tuple[str, object]],
        ) -> dict[str, object]:
            parsed: dict[str, object] = {}
            for key, item in pairs:
                if key in parsed and parsed[key] != item:
                    raise TaxonRoutingError(
                        f"Contradictory duplicate JSON key '{key}' in taxon_assignments"
                    )
                parsed[key] = item
            return parsed

        try:
            payload = json.loads(
                text, object_pairs_hook=reject_conflicting_object_keys
            )
        except json.JSONDecodeError as exc:
            raise TaxonRoutingError("taxon_assignments must be valid JSON") from exc
    else:
        try:
            encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise TaxonRoutingError("taxon_assignments must be JSON-compatible") from exc
        if len(encoded) > max_bytes:
            raise TaxonRoutingError(
                f"taxon_assignments JSON exceeds the {max_bytes} byte routing metadata limit"
            )
        payload = value

    if isinstance(payload, Mapping):
        rows = list(payload.items())
    elif isinstance(payload, list):
        rows = []
        for index, row in enumerate(payload, start=1):
            if not isinstance(row, Mapping):
                raise TaxonRoutingError(
                    f"taxon_assignments row {index} must be an object"
                )
            if "input_key" not in row or "taxon_group" not in row:
                raise TaxonRoutingError(
                    f"taxon_assignments row {index} requires input_key and taxon_group"
                )
            rows.append((row.get("input_key"), row.get("taxon_group")))
    else:
        raise TaxonRoutingError(
            "taxon_assignments must be an object or an array of assignment rows"
        )

    if len(rows) > max_rows:
        raise TaxonRoutingError(
            f"taxon_assignments may contain at most {max_rows} rows"
        )
    assignments: dict[str, str] = {}
    canonical_keys: dict[str, str] = {}
    for input_key, taxon_group in rows:
        _add_assignment(
            assignments, canonical_keys, input_key, taxon_group
        )
    return _canonical_assignment_dict(assignments, canonical_keys)


def parse_assignment_tsv(
    value: object,
    *,
    max_bytes: int = MAX_ASSIGNMENT_BYTES,
    max_rows: int = MAX_ASSIGNMENT_ROWS,
) -> dict[str, str]:
    """Parse the exact two-column ``taxon_assignments.tsv`` contract."""

    text = _bounded_text(value, "taxon_assignments.tsv", max_bytes)
    lines = text.splitlines()
    if not lines or lines[0] != "input_key\ttaxon_group":
        raise TaxonRoutingError(
            "taxon_assignments.tsv must start with exactly: input_key<TAB>taxon_group"
        )

    assignments: dict[str, str] = {}
    canonical_keys: dict[str, str] = {}
    row_count = 0
    for line_number, raw_line in enumerate(lines[1:], start=2):
        if not raw_line.strip():
            continue
        columns = raw_line.split("\t")
        if len(columns) != 2:
            raise TaxonRoutingError(
                f"taxon_assignments.tsv line {line_number} must have exactly two columns"
            )
        row_count += 1
        if row_count > max_rows:
            raise TaxonRoutingError(
                f"taxon_assignments.tsv may contain at most {max_rows} rows"
            )
        _add_assignment(assignments, canonical_keys, columns[0], columns[1])
    return _canonical_assignment_dict(assignments, canonical_keys)


def merge_assignments(*assignment_sets: Mapping[str, str]) -> dict[str, str]:
    assignments: dict[str, str] = {}
    canonical_keys: dict[str, str] = {}
    for assignment_set in assignment_sets:
        for input_key, taxon_group in assignment_set.items():
            _add_assignment(
                assignments, canonical_keys, input_key, taxon_group
            )
    return _canonical_assignment_dict(assignments, canonical_keys)


def _decoded_lines(handle: BinaryIO | TextIO) -> Iterable[str]:
    for raw_line in handle:
        if isinstance(raw_line, bytes):
            yield raw_line.decode("utf-8", errors="replace")
        else:
            yield str(raw_line)


def _lineage_has(lineage: str, name: str) -> bool:
    return bool(
        re.search(
            rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])",
            lineage,
            re.I,
        )
    )


def parse_genbank_taxonomy_lines(
    lines: Iterable[str],
) -> dict[str, object] | None:
    """Read authoritative source lineage without guessing from organism names."""

    organisms: list[str] = []
    taxids: list[int] = []
    lineage_parts: list[str] = []
    in_header_lineage = False

    for raw_line in lines:
        line = str(raw_line).rstrip("\r\n")
        organism_match = re.match(r'^\s{0,4}ORGANISM\s+(.+?)\s*$', line)
        if organism_match:
            organisms.append(organism_match.group(1).strip())
            in_header_lineage = True
            continue

        if in_header_lineage:
            stripped = line.strip()
            if line.startswith("            ") and stripped and not stripped.startswith("/"):
                lineage_parts.append(stripped)
                continue
            in_header_lineage = False

        qualifier_organism = re.search(r'/organism\s*=\s*"([^"]+)"', line, re.I)
        if qualifier_organism:
            organisms.append(qualifier_organism.group(1).strip())
        for match in re.finditer(r'/db_xref\s*=\s*"taxon:(\d+)"', line, re.I):
            taxids.append(int(match.group(1)))
        qualifier_lineage = re.search(r'/lineage\s*=\s*"([^"]+)"', line, re.I)
        if qualifier_lineage:
            lineage_parts.append(qualifier_lineage.group(1).strip())

    lineage = " ".join(lineage_parts)
    has_fungi = 4751 in taxids or _lineage_has(lineage, "Fungi")
    has_bacteria = 2 in taxids or _lineage_has(lineage, "Bacteria")
    has_archaea = _lineage_has(lineage, "Archaea")
    has_virus = _lineage_has(lineage, "Viruses") or _lineage_has(
        lineage, "Viroids"
    )
    has_eukaryota = _lineage_has(lineage, "Eukaryota")
    has_nonfungal_eukaryote = any(
        _lineage_has(lineage, name)
        for name in ("Metazoa", "Viridiplantae")
    )
    conflicting_authority = (
        (has_fungi and has_bacteria)
        or (has_fungi and (has_archaea or has_virus or has_nonfungal_eukaryote))
        or (has_bacteria and (has_archaea or has_virus or has_eukaryota))
    )
    if conflicting_authority:
        raise TaxonRoutingError(
            "GenBank source taxonomy contains conflicting supported/unsupported lineages"
        )

    if has_fungi:
        group = "fungi"
    elif has_bacteria:
        group = "bacteria"
    elif has_archaea or has_virus or has_eukaryota or has_nonfungal_eukaryote:
        group = "unsupported"
    else:
        return None

    return {
        "taxon_group": group,
        "taxon_source": "genbank_source",
        "taxid": taxids[0] if taxids else None,
        "organism_name": organisms[0] if organisms else "",
        "lineage": lineage,
    }


def parse_genbank_taxonomy(value: str | bytes) -> dict[str, object] | None:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return parse_genbank_taxonomy_lines(text.splitlines())


def parse_genbank_taxonomy_stream(
    handle: BinaryIO | TextIO,
) -> dict[str, object] | None:
    return parse_genbank_taxonomy_lines(_decoded_lines(handle))


def _scope_allows(scope: str, taxon_group: str) -> bool:
    return scope == "both" or scope == taxon_group


def _safe_taxid(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _route_row(
    *,
    input_key: str,
    genome_id: object = "",
    taxon_group: str,
    taxon_source: str,
    taxid: object = None,
    organism_name: object = "",
    source_accession: object = "",
    prediction_method: str,
    route_reason: str,
) -> dict[str, object]:
    resolved_genome_id = str(genome_id or input_key).strip()
    if not INPUT_KEY_RE.fullmatch(resolved_genome_id):
        raise TaxonRoutingError(
            f"Taxon route genome_id '{resolved_genome_id}' must use 1-120 letters, numbers, dots, underscores, or hyphens"
        )
    return {
        "input_key": input_key,
        "genome_id": resolved_genome_id,
        "taxon_group": taxon_group,
        "taxon_source": taxon_source,
        "taxid": _safe_taxid(taxid),
        "organism_name": str(organism_name or "").strip(),
        "source_accession": str(source_accession or "").strip(),
        "prediction_method": prediction_method,
        "detector_profile": (
            "antismash+funbgcex" if taxon_group == "fungi" else "antismash"
        ),
        "input_path_key": input_key,
        "route_status": "accepted",
        "route_reason": route_reason,
    }


def build_taxon_routes(
    analysis_scope: object,
    logical_inputs: Sequence[Mapping[str, object]],
    accession_records: Sequence[Mapping[str, object]],
    assignments: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Validate authority/assignment precedence and return frozen route rows."""

    scope = normalize_analysis_scope(analysis_scope)
    normalized_assignments: dict[str, str] = {}
    assignment_keys: dict[str, str] = {}
    for key, value in (assignments or {}).items():
        canonical_key = _assignment_key(key)
        normalized = canonical_key.casefold()
        group = _assignment_group(value)
        previous = normalized_assignments.get(normalized)
        if previous is not None and previous != group:
            raise TaxonRoutingError(
                f"Contradictory taxon assignments were supplied for input_key '{canonical_key}'"
            )
        normalized_assignments[normalized] = group
        assignment_keys.setdefault(normalized, canonical_key)
    inputs_by_key: dict[str, Mapping[str, object]] = {}
    canonical_input_keys: dict[str, str] = {}
    for logical_input in logical_inputs:
        input_key = _assignment_key(logical_input.get("input_key"))
        normalized = input_key.casefold()
        if normalized in inputs_by_key:
            raise TaxonRoutingError(
                f"Logical genome input_key '{input_key}' was supplied more than once"
            )
        inputs_by_key[normalized] = logical_input
        canonical_input_keys[normalized] = input_key

    accessions_by_key: dict[str, Mapping[str, object]] = {}
    for record in accession_records:
        accession = _assignment_key(record.get("accession"))
        normalized = accession.casefold()
        if normalized in accessions_by_key or normalized in inputs_by_key:
            raise TaxonRoutingError(
                f"Routing input_key '{accession}' is duplicated"
            )
        accessions_by_key[normalized] = record

    for normalized, group in normalized_assignments.items():
        if normalized in accessions_by_key:
            accession = str(accessions_by_key[normalized].get("accession") or normalized)
            raise TaxonRoutingError(
                f"Taxon assignment for NCBI accession '{accession}' cannot override authoritative NCBI taxonomy"
            )
        if normalized not in inputs_by_key:
            raise TaxonRoutingError(
                f"Taxon assignment references unknown input_key '{assignment_keys[normalized]}'"
            )
        if scope != "both" and group != scope:
            raise TaxonRoutingError(
                f"Taxon assignment for '{canonical_input_keys[normalized]}' conflicts with selected {scope} scope"
            )

    routes: list[dict[str, object]] = []
    for normalized in sorted(accessions_by_key):
        record = accessions_by_key[normalized]
        accession = str(record.get("accession") or "").strip().upper()
        taxon_group = str(record.get("taxon_group") or "").strip().lower()
        if taxon_group not in TAXON_GROUPS:
            raise TaxonRoutingError(
                f"NCBI accession '{accession}' has unsupported or unresolved taxonomy"
            )
        if not _scope_allows(scope, taxon_group):
            raise TaxonRoutingError(
                f"NCBI accession '{accession}' resolves to {taxon_group}, outside selected {scope} scope"
            )
        routes.append(
            _route_row(
                input_key=accession,
                genome_id=record.get("genome_id") or accession,
                taxon_group=taxon_group,
                taxon_source="ncbi",
                taxid=record.get("tax_id"),
                organism_name=record.get("organism_name"),
                source_accession=accession,
                prediction_method=(
                    "prodigal" if taxon_group == "bacteria" else "funannotate"
                ),
                route_reason="authoritative_ncbi_taxonomy",
            )
        )

    for normalized in sorted(inputs_by_key):
        logical_input = inputs_by_key[normalized]
        input_key = canonical_input_keys[normalized]
        authority = logical_input.get("authoritative_taxonomy")
        authoritative = authority if isinstance(authority, Mapping) else None
        declared_group = normalized_assignments.get(normalized)

        if authoritative is not None:
            taxon_group = str(authoritative.get("taxon_group") or "").strip().lower()
            if taxon_group not in TAXON_GROUPS:
                organism = str(authoritative.get("organism_name") or input_key)
                raise TaxonRoutingError(
                    f"GenBank input '{input_key}' has unsupported authoritative taxonomy ({organism})"
                )
            if not _scope_allows(scope, taxon_group):
                raise TaxonRoutingError(
                    f"GenBank input '{input_key}' resolves to {taxon_group}, outside selected {scope} scope"
                )
            if declared_group is not None and declared_group != taxon_group:
                raise TaxonRoutingError(
                    f"Taxon assignment for '{input_key}' conflicts with authoritative GenBank taxonomy"
                )
            taxon_source = "genbank_source"
            taxid = authoritative.get("taxid")
            organism_name = authoritative.get("organism_name")
            route_reason = "authoritative_genbank_taxonomy"
        else:
            if scope == "both" and declared_group is None:
                raise TaxonRoutingError(
                    f"Both scope requires a fungi or bacteria assignment for input_key '{input_key}'"
                )
            taxon_group = declared_group or scope
            taxon_source = "user_declaration"
            taxid = None
            organism_name = ""
            route_reason = (
                "explicit_both_mode_assignment"
                if scope == "both"
                else f"selected_{scope}_scope_declaration"
            )

        prediction_method = (
            "prodigal"
            if taxon_group == "bacteria"
            else (
                "existing_cds"
                if bool(logical_input.get("has_annotated_genbank"))
                else "funannotate"
            )
        )
        routes.append(
            _route_row(
                input_key=input_key,
                taxon_group=taxon_group,
                taxon_source=taxon_source,
                taxid=taxid,
                organism_name=organism_name,
                prediction_method=prediction_method,
                route_reason=route_reason,
            )
        )
    genome_ids: dict[str, str] = {}
    for route in routes:
        genome_id = str(route.get("genome_id") or "")
        normalized = genome_id.casefold()
        previous = genome_ids.get(normalized)
        if previous is not None:
            if route.get("taxon_source") == "ncbi":
                accession = str(
                    route.get("source_accession") or route.get("input_key") or ""
                ).strip()
                suffix_room = len(accession) + 1
                base = genome_id[: max(1, 120 - suffix_room)].rstrip("._-")
                disambiguated = f"{base}_{accession}"
                if not INPUT_KEY_RE.fullmatch(disambiguated):
                    raise TaxonRoutingError(
                        f"Cannot safely disambiguate duplicate NCBI genome_id '{genome_id}'"
                    )
                route["genome_id"] = disambiguated
                genome_id = disambiguated
                normalized = genome_id.casefold()
                if normalized in genome_ids:
                    raise TaxonRoutingError(
                        f"NCBI genome_id collision remains ambiguous for '{route.get('input_key')}'"
                    )
            else:
                raise TaxonRoutingError(
                    f"Taxon routes for '{previous}' and '{route.get('input_key')}' resolve to duplicate genome_id '{genome_id}'; provide distinct upload IDs"
                )
        genome_ids[normalized] = str(route.get("input_key") or genome_id)
    return routes


def summarize_taxon_routes(
    routes: Sequence[Mapping[str, object]],
) -> tuple[dict[str, int], dict[str, int]]:
    fungi = sum(1 for row in routes if row.get("taxon_group") == "fungi")
    bacteria = sum(1 for row in routes if row.get("taxon_group") == "bacteria")
    total = fungi + bacteria
    funannotate = sum(
        1 for row in routes if row.get("prediction_method") == "funannotate"
    )
    prodigal = sum(
        1 for row in routes if row.get("prediction_method") == "prodigal"
    )
    taxon_counts = {"fungi": fungi, "bacteria": bacteria, "total": total}
    applicability_counts = {
        "funannotate": funannotate,
        "prodigal": prodigal,
        "antismash": total,
        "funbgcex": fungi,
        "funbgcex_not_applicable_taxon": bacteria,
        "bigscape": total,
        "taxon_tree_figure": total,
    }
    return taxon_counts, applicability_counts
