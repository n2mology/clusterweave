"""Current scientific profile defaults and supplied-row applicability counts."""

from __future__ import annotations

from collections.abc import Iterable


def default_prediction_method(
    taxon_group: str, *, has_annotated_genbank: bool = False
) -> str:
    """Project a supported taxon and an already observed uploaded-CDS choice."""

    if taxon_group == "plants":
        return "existing_cds" if has_annotated_genbank else "annotation_required"
    if taxon_group == "bacteria":
        return "prodigal"
    return "existing_cds" if has_annotated_genbank else "funannotate"


def default_detector_profile(taxon_group: str) -> str:
    """Return the current detector profile for a supported taxon."""

    if taxon_group == "plants":
        return "plantismash"
    return "antismash+funbgcex" if taxon_group == "fungi" else "antismash"


def summarize_profiles(
    taxon_groups: Iterable[object], prediction_methods: Iterable[object]
) -> tuple[dict[str, int], dict[str, int]]:
    """Count supplied projections; callers retain route validation and filtering."""

    groups = tuple(taxon_groups)
    methods = tuple(prediction_methods)
    fungi = sum(1 for group in groups if group == "fungi")
    bacteria = sum(1 for group in groups if group == "bacteria")
    plants = sum(1 for group in groups if group == "plants")
    total = fungi + bacteria + plants
    return (
        {"fungi": fungi, "bacteria": bacteria, **({"plants": plants} if plants else {}), "total": total},
        {
            "funannotate": sum(1 for method in methods if method == "funannotate"),
            "prodigal": sum(1 for method in methods if method == "prodigal"),
            "antismash": fungi + bacteria,
            **({"plantismash": plants} if plants else {}),
            "funbgcex": fungi,
            "funbgcex_not_applicable_taxon": bacteria + plants,
            "bigscape": total,
            "taxon_tree_figure": total,
        },
    )
