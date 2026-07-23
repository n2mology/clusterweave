"""Shared public-result allowlist policy for ClusterWeave.

The canonical collector and the web API must agree on this policy.  Keep it
pure (no job-store or pipeline imports) so both runtimes can use it.
"""

from __future__ import annotations

from pathlib import Path


PUBLIC_RESULTS_MANIFEST_PATH = "downloads/public_results_manifest.tsv"

PUBLIC_SUMMARY_FILENAMES = {
    "all_tools_bgc_comparison.csv",
    "all_tools_shared_unshared_summary.csv",
    "candidate_bgc_gcf_crosswalk.tsv",
    "family_atlas_shortlist.md",
    "family_atlas_shortlist.tsv",
    "priority_shortlist.md",
    "priority_shortlist.tsv",
    "shared_family_shortlist.md",
    "shared_family_shortlist.tsv",
}

# These are derived, bounded tables intended for result browsing.  Other files
# in summary_tables (especially logs and execution manifests) remain private.
PUBLIC_SUMMARY_TABLE_FILENAMES = {
    "antismash_product_types_exact.tsv",
    "bacteria_id_legend.tsv",
    "ecobac_metadata_normalized.tsv",
    "ecofun_metadata_normalized.tsv",
    "ecofun_metadata_template.tsv",
    "fungal_id_legend.tsv",
    "genome_id_legend.tsv",
    "genome_taxon_manifest.tsv",
    "routing_diagnostics.tsv",
    "taxonomy_metadata_normalized.tsv",
}

PUBLIC_CROSS_KINGDOM_EVIDENCE_FILENAMES = {
    "cross_kingdom_evidence.tsv",
    "cross_kingdom_evidence.json",
    "cross_kingdom_evidence_cards.txt",
}

# Preserve read/download access for exact artifacts emitted by historical
# jobs. New runs publish only the canonical cross-kingdom filenames above.
LEGACY_PUBLIC_INTEGRATED_EVIDENCE_FILENAMES = {
    "putative_transfer_evidence.tsv",
    "putative_transfer_evidence.json",
    "putative_transfer_evidence_cards.txt",
}
PUBLIC_INTEGRATED_EVIDENCE_FILENAMES = (
    PUBLIC_CROSS_KINGDOM_EVIDENCE_FILENAMES
    | LEGACY_PUBLIC_INTEGRATED_EVIDENCE_FILENAMES
)

PUBLIC_FIGURE_EXTENSIONS = {".svg", ".png", ".pdf", ".graphml", ".tsv"}

# figures/phylogeny is deliberately stricter than the general figures tree.
# JSON, Newick and ZIP are only public at these exact paths.
TAXON_TREE_FILENAMES = {
    "clusterweave_taxon_tree.svg",
    "clusterweave_taxon_tree.png",
    "clusterweave_taxon_tree.nwk",
    "clusterweave_taxon_tree_leaf_profiles.tsv",
    "clusterweave_gcf_network_edges.tsv",
    "clusterweave_taxon_tree.graphml",
    "clusterweave_tree_manifest.json",
    "clusterweave_tree_methods.json",
    "clusterweave_tree_bundle.zip",
}
TAXON_TREE_RELATIVE_PATHS = {
    f"figures/phylogeny/{filename}" for filename in TAXON_TREE_FILENAMES
}

PUBLIC_TOOL_WEB_EXTENSIONS = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".map",
}
# BiG-SCAPE databases retain execution-time input/output paths and can be
# hundreds of MiB.  Publish the static web assets and derived figures/tables,
# never raw SQLite state.
PUBLIC_BIGSCAPE_EXTENSIONS = PUBLIC_TOOL_WEB_EXTENSIONS
PUBLIC_BIGSCAPE_PUBLIC_DIR = "public"
PUBLIC_BIGSCAPE_DATABASE_FILENAME = "clusterweave_public.sqlite"
PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME = "clusterweave_viewer.sqlite"
PUBLIC_BIGSCAPE_EXPORT_TABLE = "clusterweave_public_export"
PUBLIC_BIGSCAPE_EXPORT_VERSION = 2
PUBLIC_BIGSCAPE_PATH_POLICY = "portable-redacted-bigscape-v2"
PUBLIC_TOOL_ROOTS = {
    "antismash",
    "funbgcex",
    "big_scape",
    "bigscape",
    "big-scape",
    "clinker",
    "clinker_shared_family",
}
PUBLIC_BIGSCAPE_ROOTS = {"big_scape", "bigscape", "big-scape"}

PUBLIC_TOOL_PRIVATE_PARTS = {
    "__pycache__",
    "braker3",
    "cache",
    "caches",
    "command_logs",
    "commands",
    "funannotate",
    "input_gbks",
    "inputs",
    "logs",
    "reproducibility",
    "run_manifests",
    "scratch",
    "shard_manifests",
    "shards",
    "temp",
    "tmp",
    "work",
}
PUBLIC_TOOL_PRIVATE_FILENAMES = {
    "external_artifacts.tsv",
    "panel_manifest.tsv",
    "panels_manifest.tsv",
    "provenance.json",
    "provenance.tsv",
    "run_clusterweave_context.env",
    "run_panel.sh",
    "panel_notes.md",
}
PRIVATE_FILE_SUFFIXES = {".env", ".log", ".pyc"}


def normalized_job_result_path(value: object) -> str:
    """Return a safe, job-relative POSIX path or an empty string."""

    rel_path = str(value or "").replace("\\", "/").lstrip("/")
    parts = Path(rel_path).parts
    if not rel_path or not parts or ".." in parts or any(part in {"", "."} for part in parts):
        return ""
    return "/".join(parts)


normalize_result_path = normalized_job_result_path


def _private_filename(filename: str) -> bool:
    lower = filename.lower()
    stem = Path(lower).stem
    if lower.startswith(".") or Path(lower).suffix in PRIVATE_FILE_SUFFIXES:
        return True
    if lower in PUBLIC_TOOL_PRIVATE_FILENAMES:
        return True
    return (
        "run_manifest" in stem
        or "shard_manifest" in stem
        or "panel_manifest" in stem
        or "command_log" in stem
    )


def result_path_forbidden(rel_path: str) -> bool:
    normalized = normalized_job_result_path(rel_path)
    if not normalized:
        return True
    lower = normalized.lower()
    if lower in {"job.json", "logs.txt"}:
        return True
    if lower.startswith(("inputs/", "work/", "data/genomes/")):
        return True
    parts = lower.split("/")
    if any(part in PUBLIC_TOOL_PRIVATE_PARTS for part in parts):
        return True
    return _private_filename(parts[-1])


is_result_path_forbidden = result_path_forbidden


def result_is_public_archive(rel_path: str) -> bool:
    """Return whether this is the canonical job-level public result package."""

    lower = normalized_job_result_path(rel_path).lower()
    return (
        len(lower.split("/")) == 2
        and lower.startswith("downloads/")
        and lower.endswith("_public_results.zip")
    )


is_public_results_archive = result_is_public_archive


def result_tool_public_shape(subparts: list[str], suffix: str) -> bool:
    if not subparts:
        return False
    parts = [part.lower() for part in subparts]
    root = parts[0]
    filename = parts[-1]
    if root not in PUBLIC_TOOL_ROOTS:
        return False
    if any(part in PUBLIC_TOOL_PRIVATE_PARTS for part in parts):
        return False
    if _private_filename(filename):
        return False

    # antiSMASH JSON can carry complete raw records/sequences.  Its HTML and
    # static web assets remain public, but JSON is never generally approved.
    if root == "antismash" and suffix.lower() == ".json":
        return False

    if root in PUBLIC_BIGSCAPE_ROOTS and suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        return _is_exact_public_bigscape_database_parts(subparts)
    allowed = PUBLIC_BIGSCAPE_EXTENSIONS if root in PUBLIC_BIGSCAPE_ROOTS else PUBLIC_TOOL_WEB_EXTENSIONS
    return suffix.lower() in allowed


def _is_exact_public_bigscape_database_parts(parts: list[str]) -> bool:
    if not parts or parts[0] not in PUBLIC_BIGSCAPE_ROOTS:
        return False
    canonical = (
        parts[0],
        PUBLIC_BIGSCAPE_PUBLIC_DIR,
        PUBLIC_BIGSCAPE_DATABASE_FILENAME,
    )
    nested = (
        parts[0],
        "output_files",
        PUBLIC_BIGSCAPE_PUBLIC_DIR,
        PUBLIC_BIGSCAPE_DATABASE_FILENAME,
    )
    return tuple(parts) in {canonical, nested}


def _is_exact_public_bigscape_viewer_database_parts(parts: list[str]) -> bool:
    """Match the web-only compact viewer derivative at its exact path.

    This predicate is deliberately separate from the ordinary public-result
    shape. The viewer database is authorized only by the dedicated web
    delivery branch and must never enter result listings, manifests, or ZIPs.
    """

    if not parts or parts[0] not in PUBLIC_BIGSCAPE_ROOTS:
        return False
    canonical = (
        parts[0],
        PUBLIC_BIGSCAPE_PUBLIC_DIR,
        PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME,
    )
    nested = (
        parts[0],
        "output_files",
        PUBLIC_BIGSCAPE_PUBLIC_DIR,
        PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME,
    )
    return tuple(parts) in {canonical, nested}


def result_is_public_bigscape_database(rel_path: str) -> bool:
    """Return true only for an exact generated public BiG-SCAPE database path."""

    normalized = normalized_job_result_path(rel_path)
    if not normalized or result_path_forbidden(normalized):
        return False
    parts = normalized.split("/")
    if len(parts) >= 4 and parts[0:2] == ["data", "results"]:
        parts = parts[3:]
    return _is_exact_public_bigscape_database_parts(parts)


def result_is_public_bigscape_viewer_database(rel_path: str) -> bool:
    """Return true only for an exact compact web-viewer database path."""

    normalized = normalized_job_result_path(rel_path)
    if not normalized or result_path_forbidden(normalized):
        return False
    parts = normalized.split("/")
    if len(parts) >= 4 and parts[0:2] == ["data", "results"]:
        parts = parts[3:]
    return _is_exact_public_bigscape_viewer_database_parts(parts)


def is_public_analysis_relative_path(rel_path: str) -> bool:
    """Check a path relative to data/results/<project>."""

    normalized = normalized_job_result_path(rel_path)
    if not normalized or result_path_forbidden(normalized):
        return False
    parts = normalized.split("/")
    filename = parts[-1]
    suffix = Path(filename).suffix.lower()

    if result_tool_public_shape(parts, suffix):
        return True

    if parts[0] == "figures":
        if len(parts) >= 2 and parts[1] == "phylogeny":
            return len(parts) == 3 and filename in TAXON_TREE_FILENAMES
        return len(parts) >= 2 and suffix in PUBLIC_FIGURE_EXTENSIONS

    if len(parts) == 2 and parts[0] == "summary":
        return filename in PUBLIC_SUMMARY_FILENAMES
    if len(parts) == 2 and parts[0] == "summary_tables":
        return filename in PUBLIC_SUMMARY_TABLE_FILENAMES
    if len(parts) == 2 and parts[0] == "integrated_evidence":
        return filename in PUBLIC_INTEGRATED_EVIDENCE_FILENAMES
    return False


def result_path_public_shape(rel_path: str) -> bool:
    """Check a path relative to a job directory."""

    normalized = normalized_job_result_path(rel_path)
    if not normalized or result_path_forbidden(normalized):
        return False
    if normalized == PUBLIC_RESULTS_MANIFEST_PATH:
        return True
    if result_is_public_archive(normalized):
        return True

    parts = normalized.split("/")
    lower_parts = [part.lower() for part in parts]
    # Retain the small pre-canonical result layout used by historical jobs.
    if lower_parts[0] == "results":
        return len(parts) >= 2 and Path(parts[-1]).suffix.lower() in PUBLIC_FIGURE_EXTENSIONS
    if len(parts) < 4 or lower_parts[0:2] != ["data", "results"]:
        return False
    return is_public_analysis_relative_path("/".join(parts[3:]))


is_public_job_result_path = result_path_public_shape


__all__ = [
    "PUBLIC_BIGSCAPE_EXTENSIONS",
    "PUBLIC_BIGSCAPE_DATABASE_FILENAME",
    "PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME",
    "PUBLIC_BIGSCAPE_EXPORT_TABLE",
    "PUBLIC_BIGSCAPE_EXPORT_VERSION",
    "PUBLIC_BIGSCAPE_PATH_POLICY",
    "PUBLIC_BIGSCAPE_PUBLIC_DIR",
    "PUBLIC_BIGSCAPE_ROOTS",
    "PUBLIC_CROSS_KINGDOM_EVIDENCE_FILENAMES",
    "PUBLIC_FIGURE_EXTENSIONS",
    "PUBLIC_INTEGRATED_EVIDENCE_FILENAMES",
    "LEGACY_PUBLIC_INTEGRATED_EVIDENCE_FILENAMES",
    "PUBLIC_RESULTS_MANIFEST_PATH",
    "PUBLIC_SUMMARY_FILENAMES",
    "PUBLIC_SUMMARY_TABLE_FILENAMES",
    "PUBLIC_TOOL_PRIVATE_FILENAMES",
    "PUBLIC_TOOL_PRIVATE_PARTS",
    "PUBLIC_TOOL_ROOTS",
    "PUBLIC_TOOL_WEB_EXTENSIONS",
    "TAXON_TREE_FILENAMES",
    "TAXON_TREE_RELATIVE_PATHS",
    "is_public_analysis_relative_path",
    "is_public_job_result_path",
    "is_public_results_archive",
    "is_result_path_forbidden",
    "normalize_result_path",
    "normalized_job_result_path",
    "result_is_public_archive",
    "result_is_public_bigscape_database",
    "result_is_public_bigscape_viewer_database",
    "result_path_forbidden",
    "result_path_public_shape",
    "result_tool_public_shape",
]
