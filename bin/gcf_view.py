"""Selected BiG-SCAPE GCF view helpers for downstream consumers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Mapping


SELECTED_GCF_SCHEMA_FIELDS = (
    "gcf_selected_category",
    "gcf_selected_threshold",
    "gcf_selected_id",
)
GCF_PROVENANCE_FIELDS = (
    "gcf_id",
    "gcf_memberships",
    "gcf_selected_category",
    "gcf_selected_threshold",
    "gcf_selected_id",
    "gcf_selected_status",
)


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"", "na", "n/a", "none", "-"} else text


def canonical_gcf_category(value: object) -> str:
    return clean(value).casefold()


def canonical_gcf_threshold(value: object) -> str:
    text = clean(value).casefold()
    if text.startswith("c"):
        text = text[1:]
    if not text:
        return ""
    try:
        normalized = format(Decimal(text).normalize(), "f")
    except InvalidOperation:
        return text
    return (
        normalized.rstrip("0").rstrip(".") if "." in normalized else normalized
    )


def clustering_view(path: Path) -> tuple[str, str]:
    match = re.match(r"(.+)_clustering_c([^/]+)\.tsv$", path.name)
    if match is None:
        return canonical_gcf_category(path.parent.name), ""
    return (
        canonical_gcf_category(match.group(1)),
        canonical_gcf_threshold(match.group(2)),
    )


def has_selected_gcf_schema(row: Mapping[str, object]) -> bool:
    """Return true when the row declares the selected-view schema.

    Presence, rather than truthiness, is intentional: an explicitly blank
    selected ID means unassigned and must never fall back to the compatibility
    union.
    """

    return all(field in row for field in SELECTED_GCF_SCHEMA_FIELDS)


def selected_gcf_status(row: Mapping[str, object]) -> str:
    if has_selected_gcf_schema(row):
        status = clean(row.get("gcf_selected_status")).casefold()
        if status:
            return status
        return "assigned" if clean(row.get("gcf_selected_id")) else "unassigned"
    return "assigned" if clean(row.get("gcf_id")) else "unassigned"


def selected_gcf_id(row: Mapping[str, object]) -> str:
    """Return the canonical selected-view IDs, with schema-aware fallback."""

    if has_selected_gcf_schema(row):
        if selected_gcf_status(row) != "assigned":
            return ""
        return clean(row.get("gcf_selected_id"))
    return clean(row.get("gcf_id"))


def selected_gcf_ids(row: Mapping[str, object]) -> tuple[str, ...]:
    seen: set[str] = set()
    families: list[str] = []
    for token in selected_gcf_id(row).split(";"):
        family = token.strip()
        if not family or family in seen:
            continue
        seen.add(family)
        families.append(family)
    return tuple(families)


def selected_gcf_view(row: Mapping[str, object]) -> tuple[str, str]:
    if not has_selected_gcf_schema(row):
        return "", ""
    return (
        canonical_gcf_category(row.get("gcf_selected_category")),
        canonical_gcf_threshold(row.get("gcf_selected_threshold")),
    )


def selected_views_compatible(
    left: Mapping[str, object], right: Mapping[str, object]
) -> bool:
    left_schema = has_selected_gcf_schema(left)
    right_schema = has_selected_gcf_schema(right)
    if left_schema != right_schema:
        return False
    if not left_schema:
        return True
    return selected_gcf_view(left) == selected_gcf_view(right)


def gcf_provenance(row: Mapping[str, object]) -> dict[str, str]:
    return {field: clean(row.get(field)) for field in GCF_PROVENANCE_FIELDS}


def materialized_gcf_provenance(
    row: Mapping[str, object],
    *,
    fallback_selected_id: str = "",
    fallback_category: str = "",
    fallback_threshold: str = "",
) -> dict[str, str]:
    """Return explicit selected-view columns without weakening new-schema blanks."""

    provenance = gcf_provenance(row)
    if has_selected_gcf_schema(row):
        return provenance
    selected = selected_gcf_id(row) or clean(fallback_selected_id)
    provenance["gcf_selected_category"] = canonical_gcf_category(
        fallback_category
    )
    provenance["gcf_selected_threshold"] = canonical_gcf_threshold(
        fallback_threshold
    )
    provenance["gcf_selected_id"] = selected
    provenance["gcf_selected_status"] = "assigned" if selected else "unassigned"
    return provenance
