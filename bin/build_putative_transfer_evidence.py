#!/usr/bin/env python3
"""Build bounded, public-safe cross-kingdom evidence artifacts.

This is an explicitly invoked terminal builder.  It does not discover inputs,
run inference, download data, or change core ClusterWeave rankings.  The caller
must provide a pre-shortlisted, public-safe TSV and an output directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


SCHEMA_VERSION = "clusterweave-cross-kingdom-evidence-v1"
DEFAULT_MAX_CANDIDATES = 25
HARD_MAX_CANDIDATES = 100
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_FIELD_CHARS = 512
MAX_JSON_BYTES = 1024 * 1024
MIN_SYNTENY_GENES = 5
MIN_SYNTENY_FRACTION = 0.70
MIN_REFERENCE_SIMILARITY = 0.50
MIN_TOPOLOGY_SUPPORT = 0.80

OUTPUT_TSV = "cross_kingdom_evidence.tsv"
OUTPUT_JSON = "cross_kingdom_evidence.json"
OUTPUT_CARDS = "cross_kingdom_evidence_cards.txt"

INTERPRETATION_BOUNDARY = (
    "Computational context does not establish an evolutionary event, mechanism, or direction."
)

CONFIDENCE_LABELS = ("exploratory", "supportive", "strong")
DERIVED_TSV_FIELDS = (
    "evidence_id",
    "confidence",
    "independent_signal_count",
    "independent_signals",
    "supported_topology_discordance",
    "contamination_interpretation",
    "assembly_interpretation",
    "evidence_summary",
    "caveats",
    "evidence_card",
)

# Inputs are deliberately allowlisted.  All accepted fields are bounded scalar
# summaries; paths, raw sequences, alignments, commands, URLs, and credentials
# are not accepted or copied into public artifacts.
ALLOWED_INPUT_FIELDS = frozenset(
    {
        # Stable public identifiers and bounded context.
        "candidate_id",
        "candidate_key",
        "candidate_label",
        "gcf_id",
        "family_id",
        "gene_family_id",
        "source_taxon_group",
        "target_taxon_group",
        "taxon_groups",
        "source_genome_id",
        "target_genome_id",
        "member_count",
        "fungal_member_count",
        "bacterial_member_count",
        "cross_domain",
        "cross_domain_gcf",
        "is_cross_domain",
        "bgc_class",
        "product_type",
        "antismash_product",
        "bgc_count",
        # Synteny summaries.
        "synteny_support",
        "synteny_gene_order_matches",
        "synteny_matched_genes",
        "synteny_shared_genes",
        "synteny_gene_count",
        "synteny_total_genes",
        "synteny_compared_genes",
        "synteny_gene_order_fraction",
        "synteny_homolog_pair_count",
        "synteny_min_cluster_coverage",
        "synteny_basis",
        "synteny_method",
        # Characterized-reference summaries.
        "characterized_reference_support",
        "characterized_reference_id",
        "characterized_reference_similarity",
        "characterized_reference_similarity_percent",
        "characterized_reference_method",
        "characterized_reference_match_count",
        "characterized_reference_coverage",
        "reference_support",
        "reference_id",
        "reference_similarity_percent",
        # Optional inferred family-tree comparison summaries.
        "family_tree_id",
        "tree_id",
        "topology_discordance",
        "tree_topology_discordance",
        "topology_discordance_supported",
        "topology_comparison_status",
        "topology_support",
        "tree_support",
        "bootstrap_support",
        "topology_test_support",
        "topology_support_method",
        "support_method",
        "tree_method",
        "alignment_method",
        "trimming_method",
        "model_selection",
        "model",
        "tree_sequence_count",
        "sequence_count",
        "tree_taxon_count",
        "taxon_count",
        "outgroup_status",
        "tree_tool_version",
        "alignment_tool_version",
        # Context signals and explicit quality checks.
        "mobile_element_context",
        "mobile_element_support",
        "composition_outlier",
        "composition_deviation",
        "mobile_element_count",
        "mobile_element_method",
        "composition_support",
        "contamination_check",
        "contamination_status",
        "composition_region_gc_percent",
        "composition_genome_gc_percent",
        "composition_gc_delta_percent",
        "composition_method",
        "composition_deviation_scope",
        "composition_evaluated_region_count",
        "assembly_region_edge_context",
        "assembly_check",
        "assembly_context_check",
        "assembly_status",
        "contamination_method",
        "paralogy_check",
        "paralogy_status",
        "sampling_check",
        "assembly_context_method",
        "assembly_context_scope",
        "sampling_status",
        "incomplete_sampling",
        "conserved_enzyme_risk",
        "conserved_enzyme_family",
        "long_branch_attraction_risk",
        "long_branch_risk",
    }
)

FORBIDDEN_HEADER_PARTS = frozenset(
    {
        "authorization",
        "command",
        "cookie",
        "credential",
        "directory",
        "environment",
        "fasta",
        "fastq",
        "file",
        "genbank",
        "newick",
        "password",
        "path",
        "private",
        "raw",
        "secret",
        "sequence",
        "token",
        "url",
    }
)

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+\-]{0,127}$")
URL_RE = re.compile(r"(?i)\b(?:https?|ftp|file|data)://")
WINDOWS_PATH_RE = re.compile(r"(?i)(?:^|\s)[A-Z]:[\\/]")
UNIX_PATH_RE = re.compile(r"(?:^|\s)/(?:[^/\s]+/)+[^/\s]*")
RELATIVE_FILE_PATH_RE = re.compile(
    r"(?i)(?:^|\s)(?:\.?\.?[\\/])?(?:[A-Za-z0-9_.-]+[\\/])+"
    r"[A-Za-z0-9_.-]+\.(?:aln|csv|fa|faa|fasta|fastq|fna|gb|gbk|gbff|json|nwk|pem|tsv|txt|yaml|yml)"
    r"(?=$|\s)"
)
SECRET_VALUE_RE = re.compile(
    r"(?i)(?:\b(?:authorization|api[_-]?key|password|passwd|secret|token)\s*[:=]|"
    r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9_-]{16,}\b|"
    r"\bgh[pousr]_[A-Za-z0-9]{16,}\b)"
)
PROHIBITED_CLAIM_RE = re.compile(
    r"(?i)\b(?:confirmed|proven|definitive)\s+(?:horizontal\s+gene\s+transfer|HGT)\b"
)


class EvidenceInputError(ValueError):
    """Raised when an input cannot be included in public evidence artifacts."""


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def normalized_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean(value).casefold()).strip("_")


def header_parts(value: str) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9]+", value.casefold()) if part}


def looks_like_raw_sequence(value: str) -> bool:
    text = value.strip()
    if len(text) >= 60 and re.fullmatch(r"[ACGTUNRYSWKMBDHV.-]+", text, flags=re.IGNORECASE):
        return True
    if len(text) >= 100 and not any(char.isspace() for char in text):
        return bool(re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWYBXZJUO*.-]+", text, flags=re.IGNORECASE))
    return False


def validate_public_value(field: str, value: str, row_number: int) -> None:
    if len(value) > MAX_FIELD_CHARS:
        raise EvidenceInputError(
            f"row {row_number}: field {field!r} exceeds the {MAX_FIELD_CHARS}-character public limit"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise EvidenceInputError(f"row {row_number}: field {field!r} contains control characters")
    if (
        URL_RE.search(value)
        or WINDOWS_PATH_RE.search(value)
        or UNIX_PATH_RE.search(value)
        or RELATIVE_FILE_PATH_RE.search(value)
    ):
        raise EvidenceInputError(f"row {row_number}: field {field!r} contains a URL or filesystem path")
    if "../" in value or "..\\" in value or value.startswith(("~/", "~\\")):
        raise EvidenceInputError(f"row {row_number}: field {field!r} contains a path traversal")
    if SECRET_VALUE_RE.search(value):
        raise EvidenceInputError(f"row {row_number}: field {field!r} contains secret-like material")
    if looks_like_raw_sequence(value):
        raise EvidenceInputError(f"row {row_number}: field {field!r} resembles raw sequence data")
    if PROHIBITED_CLAIM_RE.search(value):
        raise EvidenceInputError(f"row {row_number}: field {field!r} contains a prohibited definitive claim")


def validate_headers(fieldnames: Sequence[str]) -> list[str]:
    headers = [str(name or "").strip() for name in fieldnames]
    if not headers or any(not name for name in headers):
        raise EvidenceInputError("candidate TSV must have non-empty column names")
    if len(headers) != len(set(headers)):
        raise EvidenceInputError("candidate TSV contains duplicate column names")
    normalized = [normalized_token(name) for name in headers]
    if len(normalized) != len(set(normalized)):
        raise EvidenceInputError("candidate TSV contains normalization-colliding column names")
    for name in headers:
        if name in DERIVED_TSV_FIELDS:
            raise EvidenceInputError(f"input column {name!r} is reserved for derived evidence")
        if name in ALLOWED_INPUT_FIELDS:
            continue
        dangerous = header_parts(name) & FORBIDDEN_HEADER_PARTS
        if dangerous:
            raise EvidenceInputError(
                f"input column {name!r} is forbidden in public evidence ({sorted(dangerous)[0]})"
            )
        raise EvidenceInputError(f"input column {name!r} is not in the public-safe evidence schema")
    if "gcf_id" not in headers:
        raise EvidenceInputError("candidate TSV requires a gcf_id column")
    if not {"cross_domain", "cross_domain_gcf", "is_cross_domain"}.intersection(headers):
        raise EvidenceInputError("candidate TSV requires an explicit cross-domain field")
    return headers


def alias_value(row: dict[str, str], names: Sequence[str], label: str) -> str:
    present = [(name, clean(row.get(name))) for name in names if clean(row.get(name))]
    if not present:
        return ""
    distinct = {value.casefold() for _, value in present}
    if len(distinct) > 1:
        columns = ", ".join(name for name, _ in present)
        raise EvidenceInputError(f"conflicting {label} values across columns: {columns}")
    return present[0][1]


TRUE_TOKENS = frozenset(
    {
        "1",
        "adequate",
        "detected",
        "discordance_supported",
        "discordant",
        "intact",
        "pass",
        "passed",
        "present",
        "supported",
        "supported_discordance",
        "strongly_supported",
        "true",
        "yes",
    }
)
FALSE_TOKENS = frozenset(
    {
        "0",
        "absent",
        "concordant",
        "false",
        "no",
        "none",
        "not_detected",
        "not_supported",
        "unsupported",
    }
)
UNKNOWN_TOKENS = frozenset(
    {
        "",
        "insufficient_data",
        "na",
        "not_applicable",
        "not_available",
        "not_run",
        "not_tested",
        "unknown",
    }
)


def optional_flag(value: str, label: str) -> bool | None:
    token = normalized_token(value)
    if token in TRUE_TOKENS:
        return True
    if token in FALSE_TOKENS:
        return False
    if token in UNKNOWN_TOKENS:
        return None
    raise EvidenceInputError(f"unsupported {label} value: {value!r}")


def optional_int(value: str, label: str) -> int | None:
    text = clean(value)
    if not text:
        return None
    if not re.fullmatch(r"[0-9]+", text):
        raise EvidenceInputError(f"{label} must be a non-negative integer")
    return int(text)


def optional_fraction(value: str, label: str, *, unit: str = "auto") -> float | None:
    raw = clean(value)
    text = raw.rstrip("%").strip()
    if not text:
        return None
    if unit not in {"auto", "percent"}:
        raise EvidenceInputError(f"unsupported numeric unit for {label}")
    try:
        number = float(text)
    except ValueError as exc:
        raise EvidenceInputError(f"{label} must be numeric") from exc
    if unit == "percent" or raw.endswith("%"):
        number /= 100.0
    elif number > 1.0:
        number /= 100.0
    if not 0.0 <= number <= 1.0:
        raise EvidenceInputError(f"{label} must be between 0 and 1 (or 0 and 100 percent)")
    return number

def aliased_fraction(row: dict[str, str], fields: Sequence[tuple[str, str]], label: str) -> float | None:
    present: list[tuple[str, float]] = []
    for field, unit in fields:
        text = clean(row.get(field))
        if not text:
            continue
        parsed = optional_fraction(text, label, unit=unit)
        if parsed is None:
            continue
        present.append((field, parsed))
    if not present:
        return None
    first = present[0][1]
    if any(abs(value - first) > 1e-12 for _, value in present[1:]):
        columns = ", ".join(field for field, _ in present)
        raise EvidenceInputError(f"conflicting {label} values across columns: {columns}")
    return first


def check_status(value: str, label: str, passed: set[str], concern: set[str]) -> str:
    token = normalized_token(value)
    if token in passed:
        return "passed"
    if token in concern:
        return "concern"
    if token in UNKNOWN_TOKENS:
        return "unknown"
    raise EvidenceInputError(f"unsupported {label} value: {value!r}")


def risk_status(value: str, label: str) -> str:
    flag = optional_flag(value, label)
    if flag is True:
        return "present"
    if flag is False:
        return "absent"
    return "unknown"


def percent_text(value: float | None) -> str:
    if value is None:
        return ""
    percent = value * 100.0
    if abs(percent - round(percent)) < 1e-9:
        return f"{int(round(percent))}%"
    return f"{percent:.1f}%"


def safe_identifier(value: str, label: str) -> str:
    text = clean(value)
    if not text or not SAFE_ID_RE.fullmatch(text):
        raise EvidenceInputError(
            f"{label} must be 1-128 characters using letters, numbers, dot, colon, at, plus, or hyphen"
        )
    return text


def validate_cross_domain_context(row: dict[str, str]) -> None:
    cross_domain = alias_value(
        row,
        ("cross_domain_gcf", "cross_domain", "is_cross_domain"),
        "cross-domain declaration",
    )
    if optional_flag(cross_domain, "cross-domain declaration") is not True:
        raise EvidenceInputError("only explicitly declared cross-domain GCF candidates are eligible")

    domains: list[str] = []
    for field in ("source_taxon_group", "target_taxon_group"):
        value = normalized_token(row.get(field, ""))
        if value:
            if value not in {"fungi", "bacteria"}:
                raise EvidenceInputError(f"{field} must be fungi or bacteria")
            domains.append(value)
    taxon_groups = clean(row.get("taxon_groups"))
    if taxon_groups:
        parsed = {
            normalized_token(part)
            for part in re.split(r"[;,|]+", taxon_groups)
            if normalized_token(part)
        }
        if not parsed.issubset({"fungi", "bacteria"}):
            raise EvidenceInputError("taxon_groups may contain only fungi and bacteria")
        domains.extend(sorted(parsed))
    if domains and set(domains) != {"fungi", "bacteria"}:
        raise EvidenceInputError("provided taxon context must contain both fungi and bacteria")


def read_candidate_rows(path: Path, max_candidates: int) -> tuple[list[str], list[dict[str, str]]]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise EvidenceInputError("candidate TSV is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise EvidenceInputError("candidate TSV must be a non-symlink regular file")
    size = info.st_size
    if size > MAX_INPUT_BYTES:
        raise EvidenceInputError(f"candidate TSV exceeds the {MAX_INPUT_BYTES}-byte input limit")
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            headers = validate_headers(reader.fieldnames or [])
            rows: list[dict[str, str]] = []
            for row_number, parsed in enumerate(reader, start=2):
                if None in parsed:
                    raise EvidenceInputError(f"row {row_number}: more values than declared columns")
                row = {header: "" if parsed.get(header) is None else str(parsed[header]) for header in headers}
                if not any(clean(value) for value in row.values()):
                    raise EvidenceInputError(f"row {row_number}: empty candidate rows are not allowed")
                for field, value in row.items():
                    validate_public_value(field, value, row_number)
                safe_identifier(row.get("gcf_id", ""), f"row {row_number} gcf_id")
                for identifier_field in (
                    "candidate_id",
                    "candidate_key",
                    "family_id",
                    "gene_family_id",
                    "source_genome_id",
                    "target_genome_id",
                    "family_tree_id",
                    "tree_id",
                ):
                    if clean(row.get(identifier_field)):
                        safe_identifier(row[identifier_field], f"row {row_number} {identifier_field}")
                validate_cross_domain_context(row)
                rows.append(row)
                if len(rows) > max_candidates:
                    raise EvidenceInputError(
                        f"candidate TSV has more than the explicit --max-candidates bound ({max_candidates})"
                    )
    except UnicodeError as exc:
        raise EvidenceInputError("candidate TSV must be valid UTF-8 text") from exc
    except csv.Error as exc:
        raise EvidenceInputError("candidate TSV is malformed") from exc
    if not rows:
        raise EvidenceInputError("candidate TSV contains no candidates")
    return headers, rows


def normalized_contamination(row: dict[str, str]) -> str:
    value = alias_value(row, ("contamination_check", "contamination_status"), "contamination check")
    return check_status(
        value,
        "contamination check",
        {"pass", "passed", "screen_passed", "clear", "no_concern"},
        {"concern", "failed", "fail", "possible", "contaminated", "screen_failed"},
    )


def normalized_assembly(row: dict[str, str]) -> str:
    explicit_value = alias_value(
        row,
        ("assembly_check", "assembly_context_check", "assembly_status"),
        "assembly-context check",
    )
    explicit = check_status(
        explicit_value,
        "assembly-context check",
        {"pass", "passed", "intact", "contiguous", "context_intact", "no_concern"},
        {"concern", "failed", "fail", "fragmented", "fragmentation", "context_fragmented"},
    )
    edge = check_status(
        clean(row.get("assembly_region_edge_context")),
        "candidate-region edge context",
        {"clear"},
        {"concern", "edge", "contig_edge"},
    )
    # A region-edge concern is an independent assembly warning and must
    # dominate a broader check marked passed. Conversely, a clear antiSMASH
    # edge flag alone is not a dedicated assembly-fragmentation screen and
    # therefore cannot manufacture a pass.
    if explicit == "concern" or edge == "concern":
        return "concern"
    return explicit


def normalized_paralogy(row: dict[str, str]) -> str:
    value = alias_value(row, ("paralogy_check", "paralogy_status"), "paralogy check")
    return check_status(
        value,
        "paralogy check",
        {"pass", "passed", "single_copy", "no_concern", "screen_passed"},
        {"concern", "failed", "fail", "paralogs_present", "possible_paralogy"},
    )


def normalized_sampling(row: dict[str, str]) -> str:
    status_value = alias_value(row, ("sampling_check", "sampling_status"), "sampling check")
    status = check_status(
        status_value,
        "sampling check",
        {"pass", "passed", "adequate", "sufficient", "broad"},
        {"concern", "failed", "fail", "incomplete", "limited", "sparse"},
    )
    incomplete_value = clean(row.get("incomplete_sampling"))
    if incomplete_value:
        incomplete = risk_status(incomplete_value, "incomplete-sampling risk")
        derived = "concern" if incomplete == "present" else "passed" if incomplete == "absent" else "unknown"
        if status != "unknown" and derived != "unknown" and status != derived:
            raise EvidenceInputError("sampling_check conflicts with incomplete_sampling")
        if status == "unknown":
            status = derived
    return status


def synteny_evidence(row: dict[str, str]) -> tuple[bool, str]:
    explicit = optional_flag(clean(row.get("synteny_support")), "synteny support")
    matched_value = alias_value(
        row,
        ("synteny_gene_order_matches", "synteny_matched_genes", "synteny_shared_genes"),
        "synteny matched-gene count",
    )
    total_value = alias_value(
        row,
        ("synteny_gene_count", "synteny_total_genes", "synteny_compared_genes"),
        "synteny compared-gene count",
    )
    matched = optional_int(matched_value, "synteny matched-gene count")
    total = optional_int(total_value, "synteny compared-gene count")
    if (matched is None) != (total is None):
        raise EvidenceInputError("synteny matched and compared gene counts must be supplied together")
    if matched is not None and total is not None and (total == 0 or matched > total):
        raise EvidenceInputError("synteny counts require 0 <= matched <= compared and compared > 0")
    ratio = optional_fraction(clean(row.get("synteny_gene_order_fraction")), "synteny gene-order fraction")
    if ratio is None and matched is not None and total is not None:
        ratio = matched / total
    if explicit is True:
        supported = True
    elif explicit is False:
        supported = False
    else:
        supported = bool(total is not None and total >= MIN_SYNTENY_GENES and ratio is not None and ratio >= MIN_SYNTENY_FRACTION)
    if matched is not None and total is not None:
        return supported, f"{matched}/{total} compared genes retain similar order"
    if ratio is not None:
        return supported, f"gene-order similarity is {percent_text(ratio)}"
    return supported, "gene-order/synteny support was reported" if supported else ""


def reference_evidence(row: dict[str, str]) -> tuple[bool, str]:
    explicit_value = alias_value(
        row,
        ("characterized_reference_support", "reference_support"),
        "characterized-reference support",
    )
    explicit = optional_flag(explicit_value, "characterized-reference support")
    reference_id = alias_value(
        row,
        ("characterized_reference_id", "reference_id"),
        "characterized-reference identifier",
    )
    reference_method = clean(row.get("characterized_reference_method"))
    reference_metric = (
        "reference-gene match coverage"
        if reference_method == "antiSMASH_KnownClusterBlast_reference_gene_match_coverage"
        else "similarity"
    )
    similarity = aliased_fraction(
        row,
        (
            ("characterized_reference_similarity", "auto"),
            ("characterized_reference_similarity_percent", "percent"),
            ("reference_similarity_percent", "percent"),
        ),
        "characterized-reference similarity",
    )
    if explicit is True:
        supported = True
    elif explicit is False:
        supported = False
    else:
        supported = bool(reference_id and similarity is not None and similarity >= MIN_REFERENCE_SIMILARITY)
    if not supported:
        return False, ""
    detail = "characterized-reference support is present"
    if reference_id:
        detail += f" ({reference_id}"
        detail += f", {percent_text(similarity)} {reference_metric}" if similarity is not None else ""
        detail += ")"
    elif similarity is not None:
        detail += f" ({percent_text(similarity)} {reference_metric})"
    return True, detail


def topology_evidence(row: dict[str, str]) -> tuple[bool, float | None, str]:
    discordance_value = alias_value(
        row,
        (
            "topology_discordance",
            "tree_topology_discordance",
            "topology_discordance_supported",
            "topology_comparison_status",
        ),
        "topology-discordance comparison",
    )
    discordance = optional_flag(discordance_value, "topology-discordance comparison")
    support_value = alias_value(
        row,
        ("topology_support", "tree_support", "bootstrap_support", "topology_test_support"),
        "topology support",
    )
    support = optional_fraction(support_value, "topology support")
    token = normalized_token(discordance_value)
    explicitly_supported = token in {
        "supported",
        "supported_discordance",
        "discordance_supported",
        "strongly_supported",
    }
    supported = bool(discordance is True and (explicitly_supported or (support is not None and support >= MIN_TOPOLOGY_SUPPORT)))
    if not supported:
        return False, support, ""
    family_tree = alias_value(row, ("family_tree_id", "tree_id"), "family-tree identifier")
    detail = "family-tree topology discordance is supported"
    if support is not None:
        detail += f" ({percent_text(support)})"
    if family_tree:
        detail += f" in {family_tree}"
    return True, support, detail


def caveat_clauses(
    contamination: str,
    assembly: str,
    paralogy: str,
    sampling: str,
    conserved_enzyme: str,
    long_branch: str,
) -> tuple[str, ...]:
    contamination_text = {
        "passed": "screen passed, but residual contamination remains possible",
        "concern": "a contamination concern was reported and limits interpretation",
        "unknown": "contamination was not excluded",
    }[contamination]
    paralogy_text = {
        "passed": "check passed, but hidden paralogs remain possible",
        "concern": "possible paralogy was reported",
        "unknown": "paralogy was not fully assessed",
    }[paralogy]
    sampling_text = {
        "passed": "sampling was marked adequate, but unsampled diversity can change topology",
        "concern": "sampling is incomplete",
        "unknown": "sampling completeness is unknown",
    }[sampling]
    conserved_text = {
        "absent": "no specific risk was reported, but conserved families can produce similar patterns",
        "present": "a conserved-enzyme-family risk was reported",
        "unknown": "conserved-enzyme-family effects were not excluded",
    }[conserved_enzyme]
    long_branch_text = {
        "absent": "no specific concern was reported, but tree artifacts remain possible",
        "present": "a long-branch-attraction risk was reported",
        "unknown": "long-branch-attraction effects were not excluded",
    }[long_branch]
    assembly_text = {
        "passed": "an explicit context check passed, but local breaks remain possible",
        "concern": "an assembly-context or candidate-region edge concern was reported",
        "unknown": "assembly fragmentation was not excluded by a dedicated check",
    }[assembly]
    return (
        f"contamination: {contamination_text}",
        f"paralogy: {paralogy_text}",
        f"incomplete sampling: {sampling_text}",
        f"conserved enzymes: {conserved_text}",
        f"long-branch attraction: {long_branch_text}",
        f"assembly fragmentation: {assembly_text}",
        "synteny/reference context: similarity and retained gene order have multiple possible explanations",
        "composition/mobile context: the GC-deviation heuristic and mobility annotations are non-specific; absence is not exclusion",
    )


def evidence_identifier(row: dict[str, str]) -> str:
    gcf_id = clean(row["gcf_id"])
    candidate_key = clean(row.get("candidate_id") or row.get("candidate_key")) or gcf_id
    identity = {
        "candidate_key": candidate_key,
        "gcf_id": gcf_id,
        "source_taxon_group": clean(row.get("source_taxon_group")),
        "target_taxon_group": clean(row.get("target_taxon_group")),
        "source_genome_id": clean(row.get("source_genome_id")),
        "target_genome_id": clean(row.get("target_genome_id")),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "-", candidate_key.casefold()).strip("-")[:32] or "candidate"
    return f"cke-{slug}-{digest}"


@dataclass(frozen=True)
class EvidenceRecord:
    source: dict[str, str]
    evidence_id: str
    confidence: str
    signals: tuple[str, ...]
    supported_topology: bool
    contamination: str
    assembly: str
    paralogy: str
    sampling: str
    conserved_enzyme: str
    long_branch: str
    summary: str
    caveats: tuple[str, ...]
    card: str

    def tsv_values(self) -> dict[str, str]:
        derived = {
            "evidence_id": self.evidence_id,
            "confidence": self.confidence,
            "independent_signal_count": str(len(self.signals)),
            "independent_signals": ";".join(self.signals),
            "supported_topology_discordance": "yes" if self.supported_topology else "no",
            "contamination_interpretation": self.contamination,
            "assembly_interpretation": self.assembly,
            "evidence_summary": self.summary,
            "caveats": "; ".join(self.caveats),
            "evidence_card": self.card,
        }
        return {**self.source, **derived}

    def json_values(self) -> dict[str, object]:
        return {
            "assembly_interpretation": self.assembly,
            "caveats": list(self.caveats),
            "confidence": self.confidence,
            "contamination_interpretation": self.contamination,
            "evidence_card": self.card,
            "evidence_id": self.evidence_id,
            "evidence_summary": self.summary,
            "independent_signal_count": len(self.signals),
            "independent_signals": list(self.signals),
            "input": dict(self.source),
            "quality_context": {
                "assembly": self.assembly,
                "conserved_enzyme_risk": self.conserved_enzyme,
                "contamination": self.contamination,
                "long_branch_attraction_risk": self.long_branch,
                "paralogy": self.paralogy,
                "sampling": self.sampling,
            },
            "supported_topology_discordance": self.supported_topology,
        }


def evaluate_candidate(row: dict[str, str]) -> EvidenceRecord:
    synteny, synteny_detail = synteny_evidence(row)
    reference, reference_detail = reference_evidence(row)
    topology, _, topology_detail = topology_evidence(row)
    mobile = optional_flag(
        alias_value(row, ("mobile_element_context", "mobile_element_support"), "mobile-element context"),
        "mobile-element context",
    ) is True
    composition = optional_flag(
        alias_value(row, ("composition_deviation", "composition_outlier", "composition_support"), "composition context"),
        "composition context",
    ) is True

    contamination = normalized_contamination(row)
    assembly = normalized_assembly(row)
    paralogy = normalized_paralogy(row)
    sampling = normalized_sampling(row)
    conserved_enzyme = risk_status(clean(row.get("conserved_enzyme_risk")), "conserved-enzyme risk")
    if clean(row.get("conserved_enzyme_family")):
        # A named conserved family is itself a reported risk; it cannot be
        # negated by a contradictory boolean field.
        conserved_enzyme = "present"
    long_branch = risk_status(
        alias_value(
            row,
            ("long_branch_attraction_risk", "long_branch_risk"),
            "long-branch-attraction risk",
        ),
        "long-branch-attraction risk",
    )

    signals: list[str] = []
    details: list[str] = []
    if synteny:
        signals.append("synteny")
        details.append(synteny_detail)
    if reference:
        signals.append("characterized_reference")
        details.append(reference_detail)
    if topology:
        signals.append("supported_topology_discordance")
        details.append(topology_detail)
    if mobile or composition:
        signals.append("mobile_or_composition_context")
        context_parts = []
        if mobile:
            context_parts.append("mobile-element context is present")
        if composition:
            context_parts.append("a GC-composition deviation heuristic is reported")
        details.append(" and ".join(context_parts))

    strong = (
        topology
        and contamination == "passed"
        and assembly == "passed"
        and paralogy == "passed"
        and sampling == "passed"
        and conserved_enzyme == "absent"
        and long_branch == "absent"
        and len(signals) >= 3
    )
    if contamination == "concern":
        confidence = "exploratory"
    elif strong:
        confidence = "strong"
    elif len(signals) >= 2:
        confidence = "supportive"
    else:
        confidence = "exploratory"

    details.append(
        {
            "passed": "the contamination screen passed",
            "concern": "the contamination screen reported a concern",
            "unknown": "no passed contamination screen was supplied",
        }[contamination]
    )
    details.append(
        {
            "passed": "the assembly-context check passed",
            "concern": "an assembly-context or candidate-region edge concern was reported",
            "unknown": "assembly context was not fully checked",
        }[assembly]
    )
    if not signals:
        details.insert(0, "no independent supporting signal was supplied")
    summary = "; ".join(details)
    caveats = caveat_clauses(
        contamination,
        assembly,
        paralogy,
        sampling,
        conserved_enzyme,
        long_branch,
    )
    evidence_id = evidence_identifier(row)
    gcf_id = clean(row["gcf_id"])
    card = (
        f"{evidence_id} [{confidence}] — Cross-domain GCF {gcf_id} is shared computational family "
        f"context. Evidence: {summary}. Interpretation tier: {confidence}. "
        f"{INTERPRETATION_BOUNDARY} Caveats: {'; '.join(caveats)}."
    )
    return EvidenceRecord(
        source=dict(row),
        evidence_id=evidence_id,
        confidence=confidence,
        signals=tuple(signals),
        supported_topology=topology,
        contamination=contamination,
        assembly=assembly,
        paralogy=paralogy,
        sampling=sampling,
        conserved_enzyme=conserved_enzyme,
        long_branch=long_branch,
        summary=summary,
        caveats=caveats,
        card=card,
    )


def candidate_sort_key(row: dict[str, str]) -> tuple[str, ...]:
    return (
        clean(row.get("gcf_id")).casefold(),
        clean(row.get("candidate_id") or row.get("candidate_key")).casefold(),
        clean(row.get("source_taxon_group")).casefold(),
        clean(row.get("target_taxon_group")).casefold(),
        clean(row.get("source_genome_id")).casefold(),
        clean(row.get("target_genome_id")).casefold(),
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
    )


def build_records(rows: list[dict[str, str]]) -> list[EvidenceRecord]:
    records = [evaluate_candidate(row) for row in sorted(rows, key=candidate_sort_key)]
    seen: set[str] = set()
    for record in records:
        if record.evidence_id in seen:
            raise EvidenceInputError(
                "candidate identities are not unique; supply distinct candidate_id or candidate_key values"
            )
        seen.add(record.evidence_id)
    return records


def render_tsv(headers: list[str], records: list[EvidenceRecord]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=[*headers, *DERIVED_TSV_FIELDS],
        delimiter="\t",
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for record in records:
        writer.writerow(record.tsv_values())
    return buffer.getvalue()


def render_json(records: list[EvidenceRecord]) -> str:
    payload = {
        "candidate_count": len(records),
        "confidence_vocabulary": list(CONFIDENCE_LABELS),
        "disclaimer": (
            "Cross-domain GCF membership is computational context only. "
            f"{INTERPRETATION_BOUNDARY}"
        ),
        "records": [record.json_values() for record in records],
        "schema_version": SCHEMA_VERSION,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise EvidenceInputError(f"bounded JSON would exceed {MAX_JSON_BYTES} bytes")
    return text


def render_cards(records: list[EvidenceRecord]) -> str:
    return "\n\n".join(record.card for record in records) + "\n"


def atomic_write_text(path: Path, text: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def build_artifacts(candidate_tsv: Path, output_dir: Path, max_candidates: int) -> list[EvidenceRecord]:
    if not 1 <= max_candidates <= HARD_MAX_CANDIDATES:
        raise EvidenceInputError(
            f"--max-candidates must be between 1 and {HARD_MAX_CANDIDATES}"
        )
    headers, rows = read_candidate_rows(candidate_tsv, max_candidates)
    records = build_records(rows)
    tsv_text = render_tsv(headers, records)
    json_text = render_json(records)
    cards_text = render_cards(records)

    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir():
        raise EvidenceInputError("--output-dir must name a directory")
    atomic_write_text(output_dir / OUTPUT_TSV, tsv_text)
    atomic_write_text(output_dir / OUTPUT_JSON, json_text)
    atomic_write_text(output_dir / OUTPUT_CARDS, cards_text)
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build bounded, public-safe cross-kingdom evidence cards from a safe candidate TSV."
    )
    parser.add_argument(
        "--explicit-request",
        action="store_true",
        help="Confirm that this optional terminal evidence layer was explicitly requested.",
    )
    parser.add_argument("--candidates", type=Path, required=True, help="Public-safe shortlisted candidate TSV.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Caller-provided evidence output directory.")
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=DEFAULT_MAX_CANDIDATES,
        help=f"Explicit candidate bound (default {DEFAULT_MAX_CANDIDATES}, hard maximum {HARD_MAX_CANDIDATES}).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.explicit_request:
        parser.error("--explicit-request is required; optional cross-kingdom evidence is never built implicitly")
    try:
        records = build_artifacts(args.candidates, args.output_dir, args.max_candidates)
    except (EvidenceInputError, OSError) as exc:
        parser.error(str(exc))
    print(f"Wrote {len(records)} bounded cross-kingdom evidence card(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
