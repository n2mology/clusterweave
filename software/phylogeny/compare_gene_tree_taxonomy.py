#!/usr/bin/env python3
"""Compare one inferred gene tree with the saved fungi/bacteria context.

This helper is executed inside ClusterWeave's pinned phylogeny runtime, where
ETE 4 is installed.  It performs a deliberately conservative unrooted domain-
split check. A mixed, well-supported clade is reported only as supported
topology discordance. Computational context does not establish an evolutionary
event, mechanism, or direction.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "clusterweave-ete4-domain-topology-v1"
MAX_TREE_BYTES = 5 * 1024 * 1024
MAX_MAPPING_BYTES = 8 * 1024 * 1024
MAX_MAPPING_ROWS = 10_000
MAX_TREE_SEQUENCES = 1_000
MIN_DOMAIN_SEQUENCES = 2
DEFAULT_SUPPORT_THRESHOLD = 80.0
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+\-]{0,199}$")
SAFE_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+\-]{0,99}$")

OUTPUT_FIELDS = (
    "gcf_id",
    "gene_family_id",
    "family_tree_id",
    "comparison_status",
    "topology_discordance",
    "topology_support",
    "topology_support_method",
    "tree_method",
    "alignment_method",
    "trimming_method",
    "model_selection",
    "model",
    "tree_sequence_count",
    "tree_taxon_count",
    "fungal_sequence_count",
    "bacterial_sequence_count",
    "outgroup_status",
    "tree_tool_version",
    "alignment_tool_version",
    "comparator_version",
    "schema_version",
)


class ComparisonError(ValueError):
    """Raised when an inferred tree cannot be compared safely."""


@dataclass(frozen=True)
class Comparison:
    status: str
    topology_discordance: str
    support: float | None
    sequence_count: int
    fungal_count: int
    bacterial_count: int


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def bounded_id(value: str, label: str) -> str:
    if not SAFE_ID_RE.fullmatch(value):
        raise ComparisonError(f"{label} is not a safe bounded identifier")
    return value


def bounded_model(value: str) -> str:
    value = clean(value) or "undetermined"
    if not SAFE_MODEL_RE.fullmatch(value):
        raise ComparisonError("selected model is not a safe bounded IQ-TREE model identifier")
    return value


def node_children(node: object) -> list[object]:
    return list(getattr(node, "children", []) or [])


def node_name(node: object) -> str:
    name = clean(getattr(node, "name", ""))
    if not name:
        props = getattr(node, "props", {}) or {}
        if isinstance(props, Mapping):
            name = clean(props.get("name"))
    return name


def node_support(node: object) -> float | None:
    raw = getattr(node, "support", None)
    if raw is None:
        props = getattr(node, "props", {}) or {}
        if isinstance(props, Mapping):
            raw = props.get("support")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    if value <= 1:
        value *= 100.0
    return min(100.0, value)


def traverse(node: object) -> Iterable[object]:
    method = getattr(node, "traverse", None)
    if callable(method):
        yield from method("preorder")
        return
    yield node
    for child in node_children(node):
        yield from traverse(child)


def leaf_names(node: object) -> set[str]:
    method = getattr(node, "leaf_names", None)
    if callable(method):
        return {clean(value) for value in method() if clean(value)}
    children = node_children(node)
    if not children:
        name = node_name(node)
        return {name} if name else set()
    result: set[str] = set()
    for child in children:
        result.update(leaf_names(child))
    return result


def leaf_name_list(node: object) -> list[str]:
    method = getattr(node, "leaves", None)
    if callable(method):
        return [node_name(leaf) for leaf in method()]
    children = node_children(node)
    if not children:
        return [node_name(node)]
    result: list[str] = []
    for child in children:
        result.extend(leaf_name_list(child))
    return result


def compare_nodes(
    tree: object,
    taxon_by_sequence: Mapping[str, str],
    *,
    support_threshold: float = DEFAULT_SUPPORT_THRESHOLD,
) -> Comparison:
    leaf_list = leaf_name_list(tree)
    if any(not name for name in leaf_list) or len(leaf_list) != len(set(leaf_list)):
        raise ComparisonError("tree leaves require unique non-empty sequence identifiers")
    leaves = set(leaf_list)
    if not leaves or len(leaves) > MAX_TREE_SEQUENCES:
        raise ComparisonError("tree leaf count is outside the bounded range")
    if leaves != set(taxon_by_sequence):
        raise ComparisonError("tree leaves do not exactly match the family sequence mapping")
    taxa = {taxon_by_sequence[leaf] for leaf in leaves}
    if not taxa.issubset({"fungi", "bacteria"}):
        raise ComparisonError("sequence mapping contains an unsupported taxon")
    fungal_count = sum(taxon_by_sequence[leaf] == "fungi" for leaf in leaves)
    bacterial_count = len(leaves) - fungal_count
    if fungal_count < MIN_DOMAIN_SEQUENCES or bacterial_count < MIN_DOMAIN_SEQUENCES:
        return Comparison(
            status="insufficient_domain_replication",
            topology_discordance="insufficient_data",
            support=None,
            sequence_count=len(leaves),
            fungal_count=fungal_count,
            bacterial_count=bacterial_count,
        )

    # Trees are unrooted.  Every non-root internal node represents one side of
    # an edge bipartition; its complement is the other side.  A clean
    # fungi/bacteria edge means the saved domain topology is not contradicted.
    internal: list[tuple[set[str], float | None]] = []
    for node in traverse(tree):
        children = node_children(node)
        if not children:
            continue
        subset = leaf_names(node)
        if not subset or subset == leaves:
            continue
        internal.append((subset, node_support(node)))

    for subset, support in internal:
        complement = leaves - subset
        subset_taxa = {taxon_by_sequence[leaf] for leaf in subset}
        complement_taxa = {taxon_by_sequence[leaf] for leaf in complement}
        if len(subset_taxa) == 1 and len(complement_taxa) == 1 and subset_taxa != complement_taxa:
            return Comparison(
                status="concordant_domain_split",
                topology_discordance="not_supported",
                support=support,
                sequence_count=len(leaves),
                fungal_count=fungal_count,
                bacterial_count=bacterial_count,
            )

    mixed_supports = [
        support
        for subset, support in internal
        if support is not None
        and len({taxon_by_sequence[leaf] for leaf in subset}) > 1
        and len(subset) >= 2
    ]
    strongest = max(mixed_supports, default=None)
    supported = strongest is not None and strongest >= support_threshold
    return Comparison(
        status=(
            "supported_domain_topology_discordance"
            if supported
            else "domain_topology_discordance_low_support"
        ),
        topology_discordance="supported" if supported else "not_supported",
        support=strongest,
        sequence_count=len(leaves),
        fungal_count=fungal_count,
        bacterial_count=bacterial_count,
    )


def read_mapping(path: Path, family_id: str) -> dict[str, str]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ComparisonError("sequence mapping is unavailable") from exc
    if size > MAX_MAPPING_BYTES:
        raise ComparisonError("sequence mapping exceeds its byte bound")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"sequence_id", "family_id", "taxon_group"}
        if not required.issubset(reader.fieldnames or []):
            raise ComparisonError("sequence mapping has an invalid schema")
        result: dict[str, str] = {}
        for index, row in enumerate(reader, 1):
            if index > MAX_MAPPING_ROWS:
                raise ComparisonError("sequence mapping exceeds its row bound")
            if clean(row.get("family_id")) != family_id:
                continue
            sequence_id = bounded_id(clean(row.get("sequence_id")), "sequence_id")
            taxon = clean(row.get("taxon_group")).casefold()
            if taxon not in {"fungi", "bacteria"}:
                raise ComparisonError("sequence mapping contains an unsupported taxon")
            if sequence_id in result:
                raise ComparisonError("sequence mapping contains a duplicate sequence_id")
            result[sequence_id] = taxon
    if not result:
        raise ComparisonError("sequence mapping has no rows for the requested family")
    return result


def load_ete_tree(path: Path) -> tuple[object, str]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ComparisonError("tree file is unavailable") from exc
    if size > MAX_TREE_BYTES:
        raise ComparisonError("tree file exceeds its byte bound")
    try:
        import ete4  # type: ignore
    except ImportError as exc:
        raise ComparisonError("ETE 4 is unavailable in the pinned runtime") from exc
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ComparisonError("tree file is empty")
    try:
        return ete4.Tree(text, parser=0), clean(getattr(ete4, "__version__", "")) or "unknown"
    except Exception as exc:  # ETE exposes parser-specific exception classes.
        raise ComparisonError("ETE 4 could not parse the inferred Newick tree") from exc


def atomic_write_tsv(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(OUTPUT_FIELDS), delimiter="\t", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerow(row)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def run(args: argparse.Namespace) -> Comparison:
    if not args.explicit_request:
        raise ComparisonError("--explicit-request is required")
    if not 50 <= args.support_threshold <= 100:
        raise ComparisonError("--support-threshold must be between 50 and 100")
    family_id = bounded_id(args.family_id, "family_id")
    gcf_id = bounded_id(args.gcf_id, "gcf_id")
    tree_id = bounded_id(args.tree_id, "tree_id")
    selected_model = bounded_model(getattr(args, "selected_model", "undetermined"))
    mapping = read_mapping(args.mapping, family_id)
    tree, ete_version = load_ete_tree(args.tree)
    comparison = compare_nodes(
        tree, mapping, support_threshold=float(args.support_threshold)
    )
    support_text = "" if comparison.support is None else f"{comparison.support:.6g}"
    atomic_write_tsv(
        args.output,
        {
            "gcf_id": gcf_id,
            "gene_family_id": family_id,
            "family_tree_id": tree_id,
            "comparison_status": comparison.status,
            "topology_discordance": comparison.topology_discordance,
            "topology_support": support_text,
            "topology_support_method": "IQ-TREE_2_ultrafast_bootstrap_ETE4_unrooted_domain_split",
            "tree_method": "IQ-TREE_2_maximum_likelihood",
            "alignment_method": "MAFFT_7.526",
            "trimming_method": "trimAl_automated1",
            "model_selection": "MFP",
            "model": selected_model,
            "tree_sequence_count": comparison.sequence_count,
            "tree_taxon_count": 2,
            "fungal_sequence_count": comparison.fungal_count,
            "bacterial_sequence_count": comparison.bacterial_count,
            "outgroup_status": "unrooted_no_directional_inference",
            "tree_tool_version": "IQ-TREE_2.4.0",
            "alignment_tool_version": "MAFFT_7.526",
            "comparator_version": f"ETE_4_{ete_version}",
            "schema_version": SCHEMA_VERSION,
        },
    )
    return comparison


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explicit-request", action="store_true")
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--family-id", required=True)
    parser.add_argument("--gcf-id", required=True)
    parser.add_argument("--tree-id", required=True)
    parser.add_argument("--selected-model", default="undetermined")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--support-threshold", type=float, default=DEFAULT_SUPPORT_THRESHOLD)
    return parser.parse_args()


def main() -> int:
    try:
        result = run(parse_args())
    except (OSError, UnicodeError, ComparisonError) as exc:
        message = re.sub(r"[^A-Za-z0-9_. -]+", "_", str(exc))[:180]
        print(f"TOPOLOGY_COMPARISON status=failed message={message}", file=sys.stderr)
        return 2
    support = "na" if result.support is None else f"{result.support:.3g}"
    print(
        "TOPOLOGY_COMPARISON "
        f"status={result.status} discordance={result.topology_discordance} "
        f"support={support} sequences={result.sequence_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
