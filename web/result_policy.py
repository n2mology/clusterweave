"""Shared public-result allowlist policy for ClusterWeave.

The canonical collector and the web API must agree on this policy.  Keep it
pure (no job-store or pipeline imports) so both runtimes can use it.
"""

from __future__ import annotations

from pathlib import Path
import re

from legacy_job_results import legacy_result_path_public_shape


PUBLIC_RESULTS_MANIFEST_PATH = "downloads/public_results_manifest.tsv"
PUBLIC_EVIDENCE_MANIFEST_PATH = "evidence/clusterweave_evidence_manifest.tsv"
# Persisted manifests and their signed indexes use one bounded read/write
# envelope.  Keep this shared with the web reader so publication cannot create
# an index that the supported result routes reject.
PUBLIC_RESULT_INDEX_MAX_BYTES = 32 * 1024 * 1024

_ANTISMASH_REGION_GBK_RE = re.compile(r"(?:^|[._-])region[0-9]+\.gbk$")

PUBLIC_SUMMARY_FILENAMES = {
    "cohort_outcomes.json",
    "all_tools_bgc_comparison.csv",
    "all_tools_shared_unshared_summary.csv",
    "candidate_bgc_gcf_crosswalk.tsv",
    "native_reporting_keys.json",
    "native_comparison_selection.json",
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
    "native_detection.json",
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
    "plantismash",
    "native_bgc",
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


def _analysis_relative_parts(rel_path: str) -> list[str]:
    normalized = normalized_job_result_path(rel_path)
    if not normalized:
        return []
    parts = normalized.split("/")
    if (
        len(parts) >= 4
        and [part.lower() for part in parts[:2]] == ["data", "results"]
        and bool(parts[2])
    ):
        return parts[3:]
    return parts


def public_evidence_role(rel_path: str) -> str:
    """Return the exact public scientific-evidence role for one path."""

    parts = _analysis_relative_parts(rel_path)
    if not parts:
        return ""
    lower = [part.lower() for part in parts]
    if "/".join(lower) == PUBLIC_EVIDENCE_MANIFEST_PATH:
        return "evidence_manifest"
    if (
        len(parts) == 2
        and lower[0] == "input_gbks"
        and Path(parts[1]).suffix.lower() == ".gbk"
    ):
        return "staged_genome_genbank"
    if (
        len(parts) == 3
        and lower[0] == "antismash"
        and _ANTISMASH_REGION_GBK_RE.search(lower[2]) is not None
    ):
        return "antismash_region_genbank"
    if lower[0] in {"clinker", "clinker_shared_family"} and lower[-1] == "portable-clinker.zip":
        return "portable_clinker_archive"
    # Exact native report downloads, for a single record or an assembled shard.
    # No general CSV/gzip or private-shard extension exception.
    plant_path = None
    if len(parts) >= 4 and lower[0] == "plantismash" and lower[2] == "native":
        if lower[3] == "shards":
            if len(parts) >= 7 and re.fullmatch(r"[0-9]{6}", lower[4]) and lower[5] == "native":
                plant_path = lower[6:]
        else:
            plant_path = lower[3:]
    if plant_path:
        if len(plant_path) == 1 and re.fullmatch(r"[a-z][a-z0-9_]*[0-9]+\.[0-9]+\.(?:cluster[0-9]+\.gbk|final\.gbk|geneclusters\.xlsx|zip)", plant_path[0]):
            return "native_plant_record_download"
        if (plant_path == ["tfbs_hits_all_bgcs.csv"]
                or len(plant_path) == 2 and plant_path[0] == "tfbs"
                and re.fullmatch(r"tfbs_hits_cluster[0-9]+_[a-z][a-z0-9_]*[0-9]+\.[0-9]+\.tsv\.gz", plant_path[1])):
            return "native_plant_tfbs_download"
    if len(parts) >= 3 and lower[0] == "plantismash" and lower[2] != "native":
        exported = lower[2:]
        if (len(exported) == 1 and exported[0] in {"records.final.gbk", "geneclusters.csv", "record-cluster-map.tsv", "provenance.json"}
                or len(exported) >= 3 and exported[0] in {"data", "tfbs", "subgroup", "smcogs", "clusterblast", "knownclusterblast", "subclusterblast", "structures"}
                and Path(exported[-1]).suffix in {".gbk", ".xlsx", ".csv", ".tsv", ".gz", ".txt", ".fasta", ".fa", ".sto", ".tre", ".nwk", ".jplace", ".hmm"}
                and not any(part in PUBLIC_TOOL_PRIVATE_PARTS for part in exported)
                and not _private_filename(exported[-1])):
            return "native_plant_scientific_export"
    if len(parts) == 3 and lower[0] == "plantismash" and lower[2] == "complete-native.zip":
        return "complete_native_plant_archive"
    if len(parts) == 3 and lower[0] in {"plantismash", "native_bgc"} and re.search(r"\.cluster[0-9]+\.gbk$", lower[2]):
        return "native_bgc_genbank"
    if (
        len(parts) == 6
        and lower[0] == "funbgcex"
        and lower[2] == "results"
        and lower[3].endswith(".funbgcex_results")
        and lower[4] == "bgcs"
        and Path(parts[5]).suffix.lower() == ".gbk"
    ):
        return "funbgcex_bgc_genbank"
    return ""


def result_is_public_evidence(rel_path: str) -> bool:
    """Match only declared genome/BGC evidence files and their redacted index."""

    return bool(public_evidence_role(rel_path))


def _plant_record_web_path(parts: list[str]) -> bool:
    """Only the native report's asset graph may cross the private shard boundary.

    Execution receipts, inputs, logs, GBKs and arbitrary nested shard content
    remain private here; complete native downloads have their separate policy.
    """
    relative = parts[3:] if len(parts) > 3 and parts[:2] == ["data", "results"] else parts
    return (
        len(relative) >= 7
        and relative[0] == "plantismash"
        and relative[2:4] == ["native", "shards"]
        and re.fullmatch(r"[0-9]{6}", relative[4]) is not None
        and relative[5] == "native"
        and not any(part in PUBLIC_TOOL_PRIVATE_PARTS for part in relative[6:])
        and Path(relative[-1]).suffix in PUBLIC_TOOL_WEB_EXTENSIONS - {".json", ".map"}
        and not _private_filename(relative[-1])
    )


def result_path_forbidden(rel_path: str) -> bool:
    normalized = normalized_job_result_path(rel_path)
    if not normalized:
        return True
    if result_is_public_evidence(normalized):
        return False
    lower = normalized.lower()
    if lower in {"job.json", "logs.txt"}:
        return True
    if lower.startswith(("inputs/", "work/", "data/genomes/")):
        return True
    parts = lower.split("/")
    if any(part in PUBLIC_TOOL_PRIVATE_PARTS for part in parts) and not _plant_record_web_path(parts):
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
    if any(part in PUBLIC_TOOL_PRIVATE_PARTS for part in parts) and not _plant_record_web_path(parts):
        return False
    if _private_filename(filename):
        return False

    # antiSMASH JSON can carry complete raw records/sequences.  Its HTML and
    # static web assets remain public, but JSON is never generally approved.
    if root == "plantismash":
        if len(parts) >= 4 and parts[2] == "native":
            return suffix.lower() in PUBLIC_TOOL_WEB_EXTENSIONS
        if len(parts) == 3:
            return filename in {"index.html", "geneclusters.js", "native-assets.js", "native-completion.json", "outcome.json"}
        return len(parts) >= 4 and parts[2] in {"css", "js", "images", "svg", "html", "structures", "subgroup", "smcogs", "clusterblast", "subclusterblast", "knownclusterblast", "tfbs"} and suffix.lower() in PUBLIC_TOOL_WEB_EXTENSIONS
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
    if not normalized:
        return False
    if normalized in {"METHODS.md", "run_metadata.json", "resources.tsv", "CITATIONS.bib", "CITATION.cff"}:
        return True
    if result_is_public_evidence(normalized):
        return True
    if result_path_forbidden(normalized):
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
    if lower_parts[0] == "results":
        return legacy_result_path_public_shape(normalized)
    if len(parts) < 4 or lower_parts[0:2] != ["data", "results"]:
        return False
    return is_public_analysis_relative_path("/".join(parts[3:]))


def public_archive_entry_name(rel_path: str) -> str:
    """Map a job-relative result path to its portable package member name."""

    parts = normalized_job_result_path(rel_path).split("/")
    if len(parts) >= 4 and [part.lower() for part in parts[:2]] == ["data", "results"]:
        return "/".join(parts[3:])
    return "/".join(parts)


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
    "PUBLIC_EVIDENCE_MANIFEST_PATH",
    "PUBLIC_RESULT_INDEX_MAX_BYTES",
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
    "public_archive_entry_name",
    "public_evidence_role",
    "result_is_public_archive",
    "result_is_public_bigscape_database",
    "result_is_public_bigscape_viewer_database",
    "result_is_public_evidence",
    "result_path_forbidden",
    "result_path_public_shape",
    "result_tool_public_shape",
]
