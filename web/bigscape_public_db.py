"""Create a redacted public derivative of a BiG-SCAPE SQLite database.

The upstream database is never modified. A private work copy has raw sequence
contents, sequence fingerprints, filenames, and execution paths redacted.
VACUUM INTO then creates a fresh SQLite file so removed values cannot survive
in freelist pages, journals, or WAL files.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from result_policy import (
    PUBLIC_BIGSCAPE_DATABASE_FILENAME,
    PUBLIC_BIGSCAPE_EXPORT_TABLE,
    PUBLIC_BIGSCAPE_EXPORT_VERSION,
    PUBLIC_BIGSCAPE_PATH_POLICY,
    PUBLIC_BIGSCAPE_PUBLIC_DIR,
    PUBLIC_BIGSCAPE_ROOTS,
    PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME,
)


RAW_BIGSCAPE_DATABASE_FILENAMES = {"big_scape.db", "data_sqlite.db"}
PUBLIC_EXPORT_VERSION = PUBLIC_BIGSCAPE_EXPORT_VERSION
PUBLIC_PATH_POLICY = PUBLIC_BIGSCAPE_PATH_POLICY
PUBLIC_EXPORT_TABLE = PUBLIC_BIGSCAPE_EXPORT_TABLE
SIDECAR_FILENAME = f".{PUBLIC_BIGSCAPE_DATABASE_FILENAME}.source.json"
PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE = "clusterweave_viewer_export"
PUBLIC_BIGSCAPE_VIEWER_EXPORT_VERSION = 1
PUBLIC_BIGSCAPE_VIEWER_QUERY_CONTRACT = "bigscape-2.0.0-clusterweave-v1"
PUBLIC_BIGSCAPE_VIEWER_PATH_POLICY = "portable-redacted-bigscape-viewer-v1"
VIEWER_SIDECAR_FILENAME = f".{PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME}.source.json"
DEFAULT_MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_VIEWER_BYTES = 64 * 1024 * 1024
MIN_FREE_BYTES = 64 * 1024 * 1024

_BIGSCAPE_200_JS_SHA256 = "8ade9f32fd51260d47817d49ea33e6132f6f0876eaf2d0805d42918c35bec9ee"
_MAX_VIEWER_ASSET_BYTES = 16 * 1024 * 1024
_VIEWER_INDEX_EXEC_CALLS = 14
_VIEWER_SCRIPT_EXEC_CALLS = 1
_VIEWER_INDEX_QUERY_FRAGMENTS = (
 "CREATE TABLE rec_ids (rec_id int)", "CREATE TABLE gbk_ids (gbk_id int)", "CREATE TABLE cds_ids (cds_id int)", "SELECT * FROM run", "SELECT cc.id, family.id, family.center_id, bgc_record_family.record_id, gbk.path FROM family", "SELECT DISTINCT cc1.id, cc2.id FROM connected_component AS cc1", "SELECT DISTINCT connected_component.id FROM connected_component", "SELECT bgc_record.id, gbk.path, bgc_record.record_type,", "SELECT hsp.cds_id, hsp.accession, hsp.env_start, hsp.env_stop, hsp.bit_score FROM hsp", "SELECT cds.gbk_id, cds.orf_num, cds.strand, cds.nt_start, cds.nt_stop, cds.id FROM cds", "SELECT gbk.id, gbk.description, length(gbk.nt_seq), gbk.hash, gbk.path,", "SELECT distance.record_a_id, distance.record_b_id, distance.distance FROM distance", "SELECT distance.record_a_id, distance.record_b_id, distance.lcs_domain_a_start,", "SELECT family.newick FROM family WHERE family.id ==", "SELECT gbk.organism, COUNT(gbk.organism) FROM gbk", "SELECT bgc_record.product, COUNT(bgc_record.product) as c", "SELECT gbk.organism, gbk.path, family.id, family.bin_label FROM gbk",
)
_VIEWER_SCRIPT_QUERY_FRAGMENT = "SELECT distance.record_a_id, distance.record_b_id, distance.distance FROM distance"

_EXPECTED_BIGSCAPE_COLUMNS = {
    "bgc_record": (
        "id", "gbk_id", "parent_id", "record_number", "contig_edge",
        "record_type", "nt_start", "nt_stop", "product", "category", "merged",
    ),
    "bgc_record_family": ("record_id", "family_id"),
    "cds": (
        "id", "gbk_id", "nt_start", "nt_stop", "orf_num", "strand",
        "gene_kind", "aa_seq",
    ),
    "connected_component": ("id", "record_id", "cutoff", "bin_label", "run_id"),
    "distance": (
        "record_a_id", "record_b_id", "distance", "jaccard", "adjacency", "dss",
        "edge_param_id", "lcs_a_start", "lcs_a_stop", "lcs_b_start",
        "lcs_b_stop", "ext_a_start", "ext_a_stop", "ext_b_start", "ext_b_stop",
        "reverse", "lcs_domain_a_start", "lcs_domain_a_stop",
        "lcs_domain_b_start", "lcs_domain_b_stop",
    ),
    "edge_params": ("id", "weights", "alignment_mode", "extend_strategy"),
    "family": ("id", "center_id", "newick", "cutoff", "bin_label", "run_id"),
    "gbk": ("id", "path", "hash", "nt_seq", "organism", "taxonomy", "description"),
    "hsp": ("id", "cds_id", "accession", "env_start", "env_stop", "bit_score"),
    "hsp_alignment": ("hsp_id", "alignment"),
    "run": (
        "id", "label", "start_time", "end_time", "duration", "mode", "input_dir",
        "output_dir", "reference_dir", "query_path", "mibig_version",
        "record_type", "classify", "weights", "alignment_mode",
        "extend_strategy", "include_singletons", "cutoffs", "min_bgc_length",
        "include_categories", "exclude_categories", "include_classes",
        "exclude_classes", "config_hash",
    ),
    "scanned_cds": ("cds_id",),
}
_EXPECTED_BIGSCAPE_INDEXES = {
    ("distance_record_id_index", "distance"),
    ("record_id_index", "bgc_record"),
}

_VIEWER_MARKER_COLUMNS = (
    "export_version", "query_contract", "path_policy",
    "source_export_version", "source_user_version", "source_bytes",
    "source_sha256", "index_bytes", "index_sha256",
    "bigscape_js_bytes", "bigscape_js_sha256", "reachable_records",
    "gbk_rows", "distance_rows",
)
_VIEWER_GBK_COLUMNS = _EXPECTED_BIGSCAPE_COLUMNS["gbk"] + (
    "clusterweave_nt_length",
)
_VIEWER_SCHEMA_SQL = """
CREATE TABLE run (
    id INTEGER, label TEXT, start_time TEXT, end_time TEXT, duration TEXT,
    mode TEXT, input_dir TEXT, output_dir TEXT, reference_dir TEXT,
    query_path TEXT, mibig_version TEXT, record_type TEXT, classify TEXT,
    weights TEXT, alignment_mode TEXT, extend_strategy TEXT,
    include_singletons TEXT, cutoffs TEXT, min_bgc_length INTEGER,
    include_categories TEXT, exclude_categories TEXT, include_classes TEXT,
    exclude_classes TEXT, config_hash TEXT
);
CREATE TABLE edge_params (
    id INTEGER, weights TEXT, alignment_mode TEXT, extend_strategy TEXT
);
CREATE TABLE gbk (
    id INTEGER,
    path TEXT,
    hash TEXT,
    nt_seq BLOB GENERATED ALWAYS AS (
        zeroblob(clusterweave_nt_length)
    ) VIRTUAL,
    organism TEXT,
    taxonomy TEXT,
    description TEXT,
    clusterweave_nt_length INTEGER
);
CREATE TABLE bgc_record (
    id INTEGER, gbk_id INTEGER, parent_id INTEGER, record_number INTEGER,
    contig_edge BOOLEAN, record_type TEXT, nt_start INTEGER, nt_stop INTEGER,
    product TEXT, category TEXT, merged BOOLEAN
);
CREATE TABLE cds (
    id INTEGER, gbk_id INTEGER, nt_start INTEGER, nt_stop INTEGER,
    orf_num INTEGER, strand INTEGER, gene_kind TEXT, aa_seq TEXT
);
CREATE TABLE hsp (
    id INTEGER, cds_id INTEGER, accession TEXT, env_start INTEGER,
    env_stop INTEGER, bit_score REAL
);
CREATE TABLE hsp_alignment (hsp_id INTEGER, alignment TEXT);
CREATE TABLE family (
    id INTEGER, center_id INTEGER, newick TEXT, cutoff REAL,
    bin_label TEXT, run_id INTEGER
);
CREATE TABLE bgc_record_family (record_id INTEGER, family_id INTEGER);
CREATE TABLE connected_component (
    id INTEGER, record_id INTEGER, cutoff REAL, bin_label TEXT, run_id INTEGER
);
CREATE TABLE distance (
    record_a_id INTEGER, record_b_id INTEGER, distance REAL, jaccard REAL,
    adjacency REAL, dss REAL, edge_param_id INTEGER, lcs_a_start INTEGER,
    lcs_a_stop INTEGER, lcs_b_start INTEGER, lcs_b_stop INTEGER,
    ext_a_start INTEGER, ext_a_stop INTEGER, ext_b_start INTEGER,
    ext_b_stop INTEGER, reverse BOOLEAN, lcs_domain_a_start INTEGER,
    lcs_domain_a_stop INTEGER, lcs_domain_b_start INTEGER,
    lcs_domain_b_stop INTEGER,
    UNIQUE(record_a_id, record_b_id, edge_param_id)
);
CREATE TABLE scanned_cds (cds_id INTEGER);
CREATE INDEX record_id_index ON bgc_record(gbk_id);
CREATE TABLE clusterweave_viewer_export (
    export_version INTEGER NOT NULL,
    query_contract TEXT NOT NULL,
    path_policy TEXT NOT NULL,
    source_export_version INTEGER NOT NULL,
    source_user_version INTEGER NOT NULL,
    source_bytes INTEGER NOT NULL,
    source_sha256 TEXT NOT NULL,
    index_bytes INTEGER NOT NULL,
    index_sha256 TEXT NOT NULL,
    bigscape_js_bytes INTEGER NOT NULL,
    bigscape_js_sha256 TEXT NOT NULL,
    reachable_records INTEGER NOT NULL,
    gbk_rows INTEGER NOT NULL,
    distance_rows INTEGER NOT NULL
);
"""

@dataclass(frozen=True)
class _ViewerProjection:
    table: str
    source_select: str
    viewer_select: str
    source_where: str
    order_by: str

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_PUBLIC_PSEUDONYM_RE = re.compile(r"cwpub_[0-9a-f]{64}")
_PRIVATE_BINARY_MARKERS = (
    b"/data/jobs/",
    b"/home/",
    b"/root/",
    b"/tmp/",
    b"/var/tmp/",
    b"/clusterweave/",
    b"/workspace/",
    b"/scratch/",
    b"/mnt/",
    b"/opt/",
    b"file:///",
)


class BigscapePublicDatabaseError(RuntimeError):
    """Raised when a database cannot be sanitized without weakening policy."""


@dataclass(frozen=True)
class PublicBigscapeDatabase:
    source_name: str
    public_path: Path
    reused: bool
    source_bytes: int
    public_bytes: int
    dataset_paths: int
    reference_paths: int
    query_paths: int
    viewer_path: Path | None = None
    viewer_bytes: int = 0


@dataclass(frozen=True)
class PublicBigscapePreparation:
    databases: tuple[PublicBigscapeDatabase, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class _SourceBaseline:
    schema: tuple[tuple[str, str, str, str], ...]
    row_counts: tuple[tuple[str, int], ...]
    user_version: int
    gbk_count: int
    gbk_distinct_paths: int
    gbk_mibig_paths: int
    gbk_hash_equivalence_digest: str
    gbk_nt_length_digest: str
    path_markers: tuple[bytes, ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _column_csv(columns: Iterable[str]) -> str:
    return ", ".join(_quote_identifier(column) for column in columns)


def _projection(
    table: str,
    *,
    source_where: str = "",
    order_by: tuple[str, ...] | None = None,
) -> _ViewerProjection:
    columns = _EXPECTED_BIGSCAPE_COLUMNS[table]
    selected = _column_csv(columns)
    ordering = _column_csv(order_by or columns)
    return _ViewerProjection(table, selected, selected, source_where, ordering)


_VIEWER_PROJECTIONS = (
    _projection("run"),
    _projection("edge_params"),
    _projection("family"),
    _projection("bgc_record_family"),
    _projection("connected_component"),
    _projection(
        "bgc_record",
        source_where=(
            "id IN (SELECT record_id FROM clusterweave_reachable_records)"
        ),
    ),
    _ViewerProjection(
        "gbk",
        "id, path, hash, length(CAST(nt_seq AS BLOB)), "
        "organism, taxonomy, description",
        "id, path, hash, length(CAST(nt_seq AS BLOB)), "
        "organism, taxonomy, description",
        "id IN (SELECT gbk_id FROM bgc_record WHERE id IN "
        "(SELECT record_id FROM clusterweave_reachable_records))",
        "id, path, hash, length(CAST(nt_seq AS BLOB)), "
        "organism, taxonomy, description",
    ),
    _projection(
        "cds",
        source_where=(
            "gbk_id IN (SELECT gbk_id FROM bgc_record WHERE id IN "
            "(SELECT record_id FROM clusterweave_reachable_records))"
        ),
    ),
    _projection(
        "hsp",
        source_where=(
            "cds_id IN (SELECT id FROM cds WHERE gbk_id IN "
            "(SELECT gbk_id FROM bgc_record WHERE id IN "
            "(SELECT record_id FROM clusterweave_reachable_records)))"
        ),
    ),
    _projection(
        "hsp_alignment",
        source_where=(
            "hsp_id IN (SELECT id FROM hsp WHERE cds_id IN "
            "(SELECT id FROM cds WHERE gbk_id IN "
            "(SELECT gbk_id FROM bgc_record WHERE id IN "
            "(SELECT record_id FROM clusterweave_reachable_records))))"
        ),
    ),
    _projection(
        "scanned_cds",
        source_where=(
            "cds_id IN (SELECT id FROM cds WHERE gbk_id IN "
            "(SELECT gbk_id FROM bgc_record WHERE id IN "
            "(SELECT record_id FROM clusterweave_reachable_records)))"
        ),
    ),
    _projection(
        "distance",
        source_where=(
            "record_a_id IN (SELECT record_id FROM clusterweave_reachable_records) "
            "AND record_b_id IN (SELECT record_id FROM clusterweave_reachable_records)"
        ),
        order_by=("record_a_id", "record_b_id", "edge_param_id"),
    ),
)


def _table_columns(connection: sqlite3.Connection, table: str) -> list[tuple]:
    return list(connection.execute(f"PRAGMA table_xinfo({_quote_identifier(table)})"))


def _user_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _schema_signature(connection: sqlite3.Connection) -> tuple[tuple[str, str, str, str], ...]:
    rows = connection.execute(
        "SELECT type, name, tbl_name, COALESCE(sql, '') "
        "FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' AND name != ? "
        "ORDER BY type, name",
        (PUBLIC_EXPORT_TABLE,),
    )
    return tuple(tuple(str(value) for value in row) for row in rows)


def _row_counts(connection: sqlite3.Connection) -> tuple[tuple[str, int], ...]:
    return tuple(
        (table, int(connection.execute(
            f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
        ).fetchone()[0]))
        for table in _user_tables(connection)
        if table != PUBLIC_EXPORT_TABLE
    )


def _safe_component(value: object, fallback: str) -> str:
    text = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
    text = "".join(ch for ch in text if ch >= " " and ch != "\x7f")
    text = _SAFE_COMPONENT_RE.sub("_", text).strip("._")
    if not text:
        text = fallback
    if len(text) > 180:
        stem, suffix = os.path.splitext(text)
        text = f"{stem[: max(1, 180 - len(suffix))]}{suffix}"
    return text


def _is_null_sentinel(value: object) -> bool:
    return value is None or str(value).strip().lower() in {"", "none", "null"}


def _looks_absolute_or_private(value: object) -> bool:
    text = str(value or "").strip().replace("\\", "/")
    lower = text.lower()
    if not text:
        return False
    if text.startswith("/") or text.startswith("//") or _WINDOWS_ABSOLUTE_RE.match(text):
        return True
    if lower.startswith("file:") or any(marker.decode().lower() in lower for marker in _PRIVATE_BINARY_MARKERS):
        return True
    parts = PurePosixPath(text).parts
    return ".." in parts


def _root_marker(value: object) -> bytes | None:
    text = str(value or "").strip().replace("\\", "/")
    if not text.startswith("/"):
        return None
    parts = [part for part in text.split("/") if part]
    if not parts:
        return None
    if len(parts) >= 2 and parts[0] == "data" and parts[1] == "jobs":
        return b"/data/jobs/"
    take = 2 if len(parts) >= 2 else 1
    return ("/" + "/".join(parts[:take]) + "/").encode("utf-8", errors="ignore")


def _hash_values(values: Iterable[object]) -> str:
    digest = hashlib.sha256()
    for value in values:
        encoded = str(value if value is not None else "<NULL>").encode(
            "utf-8", errors="surrogatepass"
        )
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _gbk_hash_equivalence_digest(connection: sqlite3.Connection) -> str:
    columns = {str(row[1]).lower() for row in _table_columns(connection, "gbk")}
    if "hash" not in columns:
        raise BigscapePublicDatabaseError("BiG-SCAPE gbk.hash column is unavailable")
    labels: dict[object, int] = {}
    values: list[object] = []
    for row_id, value in connection.execute("SELECT id, hash FROM gbk ORDER BY id"):
        if value is None:
            label: object = "<NULL>"
        else:
            if value not in labels:
                labels[value] = len(labels) + 1
            label = labels[value]
        values.extend((row_id, label))
    return _hash_values(values)


def _gbk_nt_length_digest(connection: sqlite3.Connection) -> str:
    values = (
        value
        for row in connection.execute(
            "SELECT id, nt_seq IS NULL, length(CAST(nt_seq AS BLOB)) "
            "FROM gbk ORDER BY id"
        )
        for value in row
    )
    return _hash_values(values)


def _source_baseline(connection: sqlite3.Connection) -> _SourceBaseline:
    tables = set(_user_tables(connection))
    if tables != set(_EXPECTED_BIGSCAPE_COLUMNS):
        raise BigscapePublicDatabaseError("Unsupported BiG-SCAPE table profile")
    for table, expected in _EXPECTED_BIGSCAPE_COLUMNS.items():
        observed = tuple(str(row[1]).lower() for row in _table_columns(connection, table))
        if observed != expected:
            raise BigscapePublicDatabaseError(
                f"Unsupported BiG-SCAPE column profile: {table}"
            )
    indexes = {
        (str(name), str(table))
        for name, table in connection.execute(
            "SELECT name, tbl_name FROM sqlite_master "
            "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if indexes != _EXPECTED_BIGSCAPE_INDEXES:
        raise BigscapePublicDatabaseError("Unsupported BiG-SCAPE index profile")
    other_objects = int(connection.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type NOT IN ('table', 'index') AND name NOT LIKE 'sqlite_%'"
    ).fetchone()[0])
    if other_objects:
        raise BigscapePublicDatabaseError("Unsupported BiG-SCAPE schema objects")
    missing_paths = int(connection.execute(
        "SELECT COUNT(*) FROM gbk WHERE path IS NULL OR TRIM(path) = ''"
    ).fetchone()[0])
    if missing_paths:
        raise BigscapePublicDatabaseError("BiG-SCAPE gbk paths are incomplete")
    missing_identity = int(connection.execute(
        "SELECT COUNT(*) FROM gbk "
        "WHERE hash IS NULL OR TRIM(hash) = '' "
        "OR nt_seq IS NULL OR length(CAST(nt_seq AS BLOB)) = 0"
    ).fetchone()[0])
    if missing_identity:
        raise BigscapePublicDatabaseError(
            "BiG-SCAPE gbk sequence identity fields are incomplete"
        )

    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if not integrity or str(integrity[0]).lower() != "ok":
        raise BigscapePublicDatabaseError("Source BiG-SCAPE database failed integrity_check")
    if list(connection.execute("PRAGMA foreign_key_check")):
        raise BigscapePublicDatabaseError("Source BiG-SCAPE database failed foreign_key_check")

    markers = set(_PRIVATE_BINARY_MARKERS)
    for (value,) in connection.execute("SELECT path FROM gbk WHERE path IS NOT NULL"):
        marker = _root_marker(value)
        if marker:
            markers.add(marker)
    run_columns = {str(row[1]).lower() for row in _table_columns(connection, "run")}
    for column in ("input_dir", "output_dir", "reference_dir", "query_path"):
        if column not in run_columns:
            continue
        for (value,) in connection.execute(
            f"SELECT {_quote_identifier(column)} FROM run "
            f"WHERE {_quote_identifier(column)} IS NOT NULL"
        ):
            marker = _root_marker(value)
            if marker:
                markers.add(marker)

    gbk_count = int(connection.execute("SELECT COUNT(*) FROM gbk").fetchone()[0])
    gbk_distinct_paths = int(connection.execute(
        "SELECT COUNT(DISTINCT path) FROM gbk"
    ).fetchone()[0])
    if gbk_count != gbk_distinct_paths:
        raise BigscapePublicDatabaseError(
            "BiG-SCAPE gbk paths are not uniquely attributable"
        )
    gbk_mibig_paths = sum(
        1
        for (value,) in connection.execute("SELECT path FROM gbk")
        if "mibig" in str(value or "").replace("\\", "/").lower()
    )

    return _SourceBaseline(
        schema=_schema_signature(connection),
        row_counts=_row_counts(connection),
        user_version=int(connection.execute("PRAGMA user_version").fetchone()[0]),
        gbk_count=gbk_count,
        gbk_distinct_paths=gbk_distinct_paths,
        gbk_mibig_paths=gbk_mibig_paths,
        gbk_hash_equivalence_digest=_gbk_hash_equivalence_digest(connection),
        gbk_nt_length_digest=_gbk_nt_length_digest(connection),
        path_markers=tuple(sorted(marker for marker in markers if marker)),
    )


def _public_mibig_version(value: object) -> str:
    """Return the path-safe value the browser will read from run.mibig_version."""
    if value is None:
        # JavaScript template interpolation renders a SQL NULL as ``null``.
        return "null"
    return _safe_component(value, "unknown")


def _run_context(
    connection: sqlite3.Connection,
) -> tuple[set[str], set[str], tuple[str, ...]]:
    columns = {str(row[1]).lower() for row in _table_columns(connection, "run")}
    reference_prefixes: set[str] = set()
    query_names: set[str] = set()
    mibig_versions: set[str] = set()
    if "reference_dir" in columns:
        for (value,) in connection.execute(
            "SELECT reference_dir FROM run WHERE reference_dir IS NOT NULL"
        ):
            if not _is_null_sentinel(value):
                reference_prefixes.add(str(value).replace("\\", "/").rstrip("/").lower())
    if "query_path" in columns:
        for (value,) in connection.execute(
            "SELECT query_path FROM run WHERE query_path IS NOT NULL"
        ):
            if not _is_null_sentinel(value):
                query_names.add(str(value).replace("\\", "/").rsplit("/", 1)[-1].lower())
    if "mibig_version" in columns:
        for (value,) in connection.execute("SELECT mibig_version FROM run"):
            mibig_versions.add(_public_mibig_version(value))
    if not mibig_versions:
        mibig_versions.add("unknown")
    return reference_prefixes, query_names, tuple(sorted(mibig_versions))


def _sanitize_gbk_paths(
    connection: sqlite3.Connection,
) -> tuple[int, int, int, str | None]:
    reference_prefixes, query_names, mibig_versions = _run_context(connection)
    mibig_prefix = "/".join(
        f"mibig_antismash_{version}_gbk" for version in mibig_versions
    )
    rows = list(connection.execute("SELECT id, path, hash FROM gbk ORDER BY id"))
    prepared: list[tuple[int, str, str, str]] = []
    unique_paths: dict[str, tuple[int, str, str, str]] = {}
    for row_id, raw_path, content_hash in rows:
        basename = _safe_component(raw_path, f"record_{row_id}.gbk")
        item = (int(row_id), str(raw_path), str(content_hash or ""), basename)
        prepared.append(item)
        unique_paths.setdefault(str(raw_path), item)

    used: set[str] = set()
    counts = {"dataset": 0, "reference": 0, "query": 0}
    path_map: dict[str, str] = {}
    path_roles: dict[str, str] = {}
    query_filename: str | None = None
    for row_id, raw_path, _, _ in unique_paths.values():
        normalized = raw_path.replace("\\", "/")
        lower = normalized.lower()
        filename_lower = normalized.rsplit("/", 1)[-1].lower()
        if "mibig" in lower:
            role = "reference"
            # BiG-SCAPE's browser identifies MIBiG records with this exact safe
            # marker. Include every run version so multi-run DBs retain the
            # same source classification without retaining a private path.
            prefix = f"inputs/reference/{mibig_prefix}"
            public_name = f"reference_{row_id:08d}.gbk"
        elif any(prefix and prefix in lower for prefix in reference_prefixes):
            role = "reference"
            prefix = "inputs/reference"
            public_name = f"reference_{row_id:08d}.gbk"
        elif filename_lower in query_names:
            role = "query"
            prefix = "inputs/query"
            public_name = f"query_{row_id:08d}.gbk"
            query_filename = public_name
        else:
            role = "dataset"
            prefix = "inputs/dataset"
            public_name = f"dataset_{row_id:08d}.gbk"
        candidate = f"{prefix}/{public_name}"
        if candidate.lower() in used:
            raise BigscapePublicDatabaseError("Could not create unique public gbk paths")
        used.add(candidate.lower())
        path_map[raw_path] = candidate
        path_roles[raw_path] = role

    for row_id, raw_path, _, _ in prepared:
        counts[path_roles[raw_path]] += 1
        connection.execute("UPDATE gbk SET path=? WHERE id=?", (path_map[raw_path], row_id))

    return counts["dataset"], counts["reference"], counts["query"], query_filename


def _sanitize_run_paths(
    connection: sqlite3.Connection,
    *,
    query_filename: str | None,
) -> None:
    columns = {str(row[1]).lower() for row in _table_columns(connection, "run")}
    replacements = {
        "input_dir": "inputs/dataset",
        "output_dir": "outputs",
        "reference_dir": "inputs/reference",
    }
    for column, replacement in replacements.items():
        if column not in columns:
            continue
        connection.execute(
            f"UPDATE run SET {_quote_identifier(column)}=? "
            f"WHERE {_quote_identifier(column)} IS NOT NULL "
            f"AND LOWER(TRIM({_quote_identifier(column)})) NOT IN ('', 'none', 'null')",
            (replacement,),
        )
    if "query_path" in columns:
        values = list(connection.execute("SELECT rowid, query_path FROM run"))
        for row_id, value in values:
            if not _is_null_sentinel(value):
                connection.execute(
                    "UPDATE run SET query_path=? WHERE rowid=?",
                    (query_filename or "query.gbk", row_id),
                )
    if "mibig_version" in columns:
        values = list(connection.execute("SELECT rowid, mibig_version FROM run"))
        for row_id, value in values:
            if value is not None:
                connection.execute(
                    "UPDATE run SET mibig_version=? WHERE rowid=?",
                    (_public_mibig_version(value), row_id),
                )


def _redact_sequence_contents_and_hashes(connection: sqlite3.Connection) -> None:
    raw_hashes = list(connection.execute("SELECT id, hash FROM gbk ORDER BY id"))
    salt_digest = hashlib.sha256(b"clusterweave-public-bigscape-v2\x00")
    for row_id, value in raw_hashes:
        salt_digest.update(str(row_id).encode("ascii"))
        salt_digest.update(b"\x00")
        encoded = str(value if value is not None else "<NULL>").encode(
            "utf-8", errors="surrogatepass"
        )
        salt_digest.update(len(encoded).to_bytes(8, "big"))
        salt_digest.update(encoded)
    salt = salt_digest.digest()
    pseudonyms: list[tuple[str, int]] = []
    for row_id, value in raw_hashes:
        if value is None:
            continue
        original = str(value).encode("utf-8", errors="surrogatepass")
        pseudonym = "cwpub_" + hashlib.sha256(salt + b"\x00" + original).hexdigest()
        pseudonyms.append((pseudonym, int(row_id)))
    connection.executemany("UPDATE gbk SET hash=? WHERE id=?", pseudonyms)
    config_pseudonyms: list[tuple[str, int]] = []
    for row_id, value in connection.execute(
        "SELECT rowid, config_hash FROM run ORDER BY rowid"
    ):
        if _is_null_sentinel(value):
            continue
        original = str(value).encode("utf-8", errors="surrogatepass")
        pseudonym = "cwpub_" + hashlib.sha256(
            salt + b"\x01" + original
        ).hexdigest()
        config_pseudonyms.append((pseudonym, int(row_id)))
    connection.executemany(
        "UPDATE run SET config_hash=? WHERE rowid=?", config_pseudonyms
    )
    connection.execute(
        "UPDATE gbk SET nt_seq = CASE WHEN nt_seq IS NULL THEN NULL "
        "ELSE zeroblob(length(CAST(nt_seq AS BLOB))) END"
    )
    connection.execute("UPDATE cds SET aa_seq=''")
    connection.execute("UPDATE hsp_alignment SET alignment=''")


def _create_export_marker(
    connection: sqlite3.Connection,
    *,
    source_name: str,
    dataset_paths: int,
    reference_paths: int,
    query_paths: int,
) -> None:
    connection.execute(f"DROP TABLE IF EXISTS {_quote_identifier(PUBLIC_EXPORT_TABLE)}")
    connection.execute(
        f"CREATE TABLE {_quote_identifier(PUBLIC_EXPORT_TABLE)} ("
        "export_version INTEGER NOT NULL, "
        "source_name TEXT NOT NULL, "
        "path_policy TEXT NOT NULL, "
        "dataset_paths INTEGER NOT NULL, "
        "reference_paths INTEGER NOT NULL, "
        "query_paths INTEGER NOT NULL)"
    )
    connection.execute(
        f"INSERT INTO {_quote_identifier(PUBLIC_EXPORT_TABLE)} VALUES (?, ?, ?, ?, ?, ?)",
        (
            PUBLIC_EXPORT_VERSION,
            _safe_component(source_name, "big_scape.db"),
            PUBLIC_PATH_POLICY,
            dataset_paths,
            reference_paths,
            query_paths,
        ),
    )


def _contains_binary_marker(path: Path, markers: Iterable[bytes]) -> bytes | None:
    needles = tuple(sorted({marker for marker in markers if marker}, key=len, reverse=True))
    if not needles:
        return None
    overlap = max(len(marker) for marker in needles) - 1
    tail = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            block = tail + chunk
            for marker in needles:
                if marker in block:
                    return marker
            tail = block[-overlap:] if overlap > 0 else b""
    return None


def _validate_public_database(
    path: Path,
    baseline: _SourceBaseline,
    *,
    binary_markers: Iterable[bytes],
) -> tuple[int, int, int]:
    if not path.is_file() or path.is_symlink():
        raise BigscapePublicDatabaseError("Sanitized database is not a regular file")
    with path.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise BigscapePublicDatabaseError("Sanitized database has invalid SQLite magic")

    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            raise BigscapePublicDatabaseError("Sanitized database failed integrity_check")
        if list(connection.execute("PRAGMA foreign_key_check")):
            raise BigscapePublicDatabaseError("Sanitized database failed foreign_key_check")
        if int(connection.execute("PRAGMA user_version").fetchone()[0]) != baseline.user_version:
            raise BigscapePublicDatabaseError("Sanitized database changed user_version")
        if _schema_signature(connection) != baseline.schema:
            raise BigscapePublicDatabaseError("Sanitized database changed upstream schema")
        if _row_counts(connection) != baseline.row_counts:
            raise BigscapePublicDatabaseError("Sanitized database changed upstream row counts")
        if _gbk_hash_equivalence_digest(connection) != baseline.gbk_hash_equivalence_digest:
            raise BigscapePublicDatabaseError("Sanitized database changed gbk hash equality")
        if _gbk_nt_length_digest(connection) != baseline.gbk_nt_length_digest:
            raise BigscapePublicDatabaseError("Sanitized database changed nucleotide lengths")
        bad_hashes = int(connection.execute(
            "SELECT COUNT(*) FROM gbk WHERE hash IS NULL "
            "OR length(hash) != 70 OR substr(hash, 1, 6) != 'cwpub_' "
            "OR substr(hash, 7) GLOB '*[^0-9a-f]*'"
        ).fetchone()[0])
        if bad_hashes:
            raise BigscapePublicDatabaseError("Sanitized database contains an unsafe gbk hash")
        for (value,) in connection.execute("SELECT config_hash FROM run"):
            if not _is_null_sentinel(value) and not _PUBLIC_PSEUDONYM_RE.fullmatch(
                str(value)
            ):
                raise BigscapePublicDatabaseError(
                    "Sanitized database contains an unsafe run config hash"
                )
        raw_nt = int(connection.execute(
            "SELECT COUNT(*) FROM gbk WHERE nt_seq IS NULL "
            "OR typeof(nt_seq) != 'blob' "
            "OR nt_seq != zeroblob(length(nt_seq))"
        ).fetchone()[0])
        raw_aa = int(connection.execute(
            "SELECT COUNT(*) FROM cds WHERE typeof(aa_seq) != 'text' OR aa_seq != ''"
        ).fetchone()[0])
        raw_alignment = int(connection.execute(
            "SELECT COUNT(*) FROM hsp_alignment "
            "WHERE typeof(alignment) != 'text' OR alignment != ''"
        ).fetchone()[0])
        if raw_nt or raw_aa or raw_alignment:
            raise BigscapePublicDatabaseError("Sanitized database contains raw sequence content")

        marker = connection.execute(
            f"SELECT export_version, path_policy, dataset_paths, reference_paths, query_paths "
            f"FROM {_quote_identifier(PUBLIC_EXPORT_TABLE)}"
        ).fetchall()
        if len(marker) != 1 or marker[0][0] != PUBLIC_EXPORT_VERSION:
            raise BigscapePublicDatabaseError("Sanitized database export marker is invalid")
        if marker[0][1] != PUBLIC_PATH_POLICY:
            raise BigscapePublicDatabaseError("Sanitized database path policy is invalid")

        paths = [str(row[0] or "") for row in connection.execute("SELECT path FROM gbk")]
        if len(paths) != baseline.gbk_count or len(set(paths)) != baseline.gbk_distinct_paths:
            raise BigscapePublicDatabaseError("Sanitized database changed gbk path cardinality")
        for value in paths:
            parts = PurePosixPath(value).parts
            if (
                not value
                or value.startswith("/")
                or "\\" in value
                or ".." in parts
                or not re.fullmatch(
                    r"inputs/(?:dataset/dataset|query/query)_\d{8}\.gbk|"
                    r"inputs/reference/reference_\d{8}\.gbk|"
                    r"inputs/reference/"
                    r"(?:mibig_antismash_[A-Za-z0-9._-]+_gbk/)+"
                    r"reference_\d{8}\.gbk",
                    value,
                )
                or _looks_absolute_or_private(value)
            ):
                raise BigscapePublicDatabaseError("Sanitized database contains an unsafe gbk path")

        allowed_run_values = {
            "input_dir": {"inputs/dataset"},
            "output_dir": {"outputs"},
            "reference_dir": {"inputs/reference"},
        }
        for column, allowed in allowed_run_values.items():
            for (value,) in connection.execute(
                f"SELECT {_quote_identifier(column)} FROM run "
                f"WHERE {_quote_identifier(column)} IS NOT NULL"
            ):
                if not _is_null_sentinel(value) and str(value) not in allowed:
                    raise BigscapePublicDatabaseError(
                        "Sanitized database contains an unsafe run path"
                    )
        for (value,) in connection.execute(
            "SELECT query_path FROM run WHERE query_path IS NOT NULL"
        ):
            if (
                not _is_null_sentinel(value)
                and str(value) != "query.gbk"
                and not re.fullmatch(r"query_\d{8}\.gbk", str(value))
            ):
                raise BigscapePublicDatabaseError(
                    "Sanitized database contains an unsafe query path"
                )

        mibig_markers = {
            f"mibig_antismash_{_public_mibig_version(value)}_gbk"
            for (value,) in connection.execute("SELECT mibig_version FROM run")
        }
        if not mibig_markers:
            mibig_markers.add("mibig_antismash_unknown_gbk")
        reference_gbk_paths = [
            value
            for value in paths
            if "/mibig_antismash_" in value
        ]
        if len(reference_gbk_paths) != baseline.gbk_mibig_paths:
            raise BigscapePublicDatabaseError(
                "Sanitized database changed its MIBiG path classification"
            )
        for value in reference_gbk_paths:
            if any(f"/{marker}/" not in value for marker in mibig_markers):
                raise BigscapePublicDatabaseError(
                    "Sanitized database lost its MIBiG viewer marker"
                )

        dataset_paths, reference_paths, query_paths = (
            int(marker[0][2]),
            int(marker[0][3]),
            int(marker[0][4]),
        )
        if dataset_paths + reference_paths + query_paths != baseline.gbk_count:
            raise BigscapePublicDatabaseError("Sanitized database marker counts are inconsistent")
    finally:
        connection.close()

    leaked = _contains_binary_marker(path, binary_markers)
    if leaked:
        raise BigscapePublicDatabaseError("Sanitized database retained a private path marker")
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(path) + suffix).exists():
            raise BigscapePublicDatabaseError("Sanitized database left a SQLite sidecar")
    return dataset_paths, reference_paths, query_paths


def _source_fingerprint(source: Path) -> dict[str, int | str]:
    stat = source.stat()
    return {
        "source_name": source.name,
        "source_bytes": int(stat.st_size),
        "source_mtime_ns": int(stat.st_mtime_ns),
        "source_sha256": _sha256_file(source),
        "export_version": PUBLIC_EXPORT_VERSION,
    }


def _read_sidecar(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_sidecar(path: Path, payload: dict[str, object]) -> None:
    temp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp, 0o640)
    os.replace(temp, path)


def _remove_sqlite_artifact(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal")):
        try:
            if candidate.is_file() or candidate.is_symlink():
                candidate.unlink()
        except OSError:
            pass


def _assert_no_source_sidecars(source: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(source) + suffix).exists():
            raise BigscapePublicDatabaseError(
                "Raw BiG-SCAPE database still has an active SQLite sidecar"
            )


def _public_directory_for_source(source: Path) -> Path:
    parent = source.parent
    if parent.name.lower() == "output_files":
        parent = parent.parent
    return parent / PUBLIC_BIGSCAPE_PUBLIC_DIR


def _viewer_asset_paths(public_database: Path) -> tuple[Path, Path]:
    tool_root = public_database.parent.parent
    return (
        tool_root / "index.html",
        tool_root / "html_content" / "js" / "bigscape.js",
    )


def _viewer_assets_present(public_database: Path) -> bool:
    index_path, script_path = _viewer_asset_paths(public_database)
    present = tuple(
        path.exists() or path.is_symlink() for path in (index_path, script_path)
    )
    if any(present) and not all(present):
        raise BigscapePublicDatabaseError(
            "BiG-SCAPE viewer assets are incomplete"
        )
    return all(present)


def _read_bounded_viewer_asset(path: Path, label: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise BigscapePublicDatabaseError(
            f"BiG-SCAPE {label} is not a regular file"
        )
    size = int(path.stat().st_size)
    if size <= 0 or size > _MAX_VIEWER_ASSET_BYTES:
        raise BigscapePublicDatabaseError(
            f"BiG-SCAPE {label} exceeds the viewer contract limit"
        )
    payload = path.read_bytes()
    if len(payload) != size:
        raise BigscapePublicDatabaseError(
            f"BiG-SCAPE {label} changed while it was read"
        )
    return payload


def _viewer_source_fingerprint(
    public_database: Path,
    baseline: _SourceBaseline,
) -> dict[str, object]:
    index_path, script_path = _viewer_asset_paths(public_database)
    index_payload = _read_bounded_viewer_asset(index_path, "index")
    script_payload = _read_bounded_viewer_asset(script_path, "script")
    try:
        index_text = index_payload.decode("utf-8")
        script_text = script_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BigscapePublicDatabaseError(
            "BiG-SCAPE viewer assets are not UTF-8"
        ) from exc

    script_sha256 = hashlib.sha256(script_payload).hexdigest()
    if script_sha256 != _BIGSCAPE_200_JS_SHA256:
        raise BigscapePublicDatabaseError(
            "Unsupported BiG-SCAPE browser script contract"
        )
    if index_text.count("window.db.exec") != _VIEWER_INDEX_EXEC_CALLS:
        raise BigscapePublicDatabaseError(
            "Unsupported BiG-SCAPE index query contract"
        )
    if script_text.count("window.db.exec") != _VIEWER_SCRIPT_EXEC_CALLS:
        raise BigscapePublicDatabaseError(
            "Unsupported BiG-SCAPE script query contract"
        )
    if any(fragment not in index_text for fragment in _VIEWER_INDEX_QUERY_FRAGMENTS):
        raise BigscapePublicDatabaseError(
            "BiG-SCAPE index query projection drifted"
        )
    if _VIEWER_SCRIPT_QUERY_FRAGMENT not in script_text:
        raise BigscapePublicDatabaseError(
            "BiG-SCAPE script query projection drifted"
        )

    source_stat = public_database.stat()
    return {
        "viewer_export_version": PUBLIC_BIGSCAPE_VIEWER_EXPORT_VERSION,
        "query_contract": PUBLIC_BIGSCAPE_VIEWER_QUERY_CONTRACT,
        "path_policy": PUBLIC_BIGSCAPE_VIEWER_PATH_POLICY,
        "source_name": PUBLIC_BIGSCAPE_DATABASE_FILENAME,
        "source_export_version": PUBLIC_EXPORT_VERSION,
        "source_user_version": baseline.user_version,
        "source_bytes": int(source_stat.st_size),
        "source_sha256": _sha256_file(public_database),
        "index_name": "index.html",
        "index_bytes": len(index_payload),
        "index_sha256": hashlib.sha256(index_payload).hexdigest(),
        "bigscape_js_name": "html_content/js/bigscape.js",
        "bigscape_js_bytes": len(script_payload),
        "bigscape_js_sha256": script_sha256,
    }


def _public_source_baseline(public_database: Path) -> _SourceBaseline:
    if (
        public_database.name != PUBLIC_BIGSCAPE_DATABASE_FILENAME
        or public_database.parent.name != PUBLIC_BIGSCAPE_PUBLIC_DIR
        or not public_database.is_file()
        or public_database.is_symlink()
    ):
        raise BigscapePublicDatabaseError(
            "Viewer source is not the canonical sanitized database"
        )
    _assert_no_source_sidecars(public_database)
    connection = sqlite3.connect(
        f"{public_database.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        expected_tables = set(_EXPECTED_BIGSCAPE_COLUMNS) | {PUBLIC_EXPORT_TABLE}
        if set(_user_tables(connection)) != expected_tables:
            raise BigscapePublicDatabaseError(
                "Sanitized viewer source has an unsupported table profile"
            )
        for table, expected in _EXPECTED_BIGSCAPE_COLUMNS.items():
            observed = tuple(
                str(row[1]).lower() for row in _table_columns(connection, table)
            )
            if observed != expected:
                raise BigscapePublicDatabaseError(
                    f"Sanitized viewer source changed columns: {table}"
                )
        marker_columns = tuple(
            str(row[1]).lower()
            for row in _table_columns(connection, PUBLIC_EXPORT_TABLE)
        )
        if marker_columns != (
            "export_version", "source_name", "path_policy", "dataset_paths",
            "reference_paths", "query_paths",
        ):
            raise BigscapePublicDatabaseError(
                "Sanitized viewer source marker schema is invalid"
            )
        indexes = {
            (str(name), str(table))
            for name, table in connection.execute(
                "SELECT name, tbl_name FROM sqlite_master "
                "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if indexes != _EXPECTED_BIGSCAPE_INDEXES:
            raise BigscapePublicDatabaseError(
                "Sanitized viewer source changed indexes"
            )
        other_objects = int(connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type NOT IN ('table', 'index') AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0])
        if other_objects:
            raise BigscapePublicDatabaseError(
                "Sanitized viewer source has unsupported schema objects"
            )
        if int(connection.execute("PRAGMA freelist_count").fetchone()[0]) != 0:
            raise BigscapePublicDatabaseError(
                "Sanitized viewer source contains free pages"
            )
        marker = connection.execute(
            f"SELECT export_version,source_name,path_policy,dataset_paths,reference_paths,query_paths "
            f"FROM {_quote_identifier(PUBLIC_EXPORT_TABLE)}"
        ).fetchall()
        if (
            len(marker) != 1
            or marker[0][0] != PUBLIC_EXPORT_VERSION
            or str(marker[0][1]).lower() not in RAW_BIGSCAPE_DATABASE_FILENAMES
            or marker[0][2] != PUBLIC_PATH_POLICY
        ):
            raise BigscapePublicDatabaseError(
                "Sanitized viewer source marker is invalid"
            )
        paths = [str(row[0] or "") for row in connection.execute("SELECT path FROM gbk")]
        gbk_count = len(paths)
        baseline = _SourceBaseline(
            schema=_schema_signature(connection),
            row_counts=_row_counts(connection),
            user_version=int(connection.execute("PRAGMA user_version").fetchone()[0]),
            gbk_count=gbk_count,
            gbk_distinct_paths=len(set(paths)),
            gbk_mibig_paths=sum(
                1 for value in paths
                if "mibig" in value.replace("\\", "/").lower()
            ),
            gbk_hash_equivalence_digest=_gbk_hash_equivalence_digest(connection),
            gbk_nt_length_digest=_gbk_nt_length_digest(connection),
            path_markers=tuple(_PRIVATE_BINARY_MARKERS),
        )
    finally:
        connection.close()
    _validate_public_database(
        public_database,
        baseline,
        binary_markers=baseline.path_markers,
    )
    return baseline


def _create_reachable_records(connection: sqlite3.Connection) -> int:
    connection.execute(
        "CREATE TEMP TABLE clusterweave_reachable_records "
        "(record_id INTEGER PRIMARY KEY)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO clusterweave_reachable_records(record_id) "
        "SELECT record_id FROM bgc_record_family WHERE record_id IS NOT NULL "
        "UNION SELECT record_id FROM connected_component WHERE record_id IS NOT NULL "
        "UNION SELECT center_id FROM family WHERE center_id IS NOT NULL"
    )
    missing = int(connection.execute(
        "SELECT COUNT(*) FROM clusterweave_reachable_records AS reachable "
        "LEFT JOIN bgc_record ON bgc_record.id=reachable.record_id "
        "WHERE bgc_record.id IS NULL"
    ).fetchone()[0])
    if missing:
        raise BigscapePublicDatabaseError(
            "BiG-SCAPE viewer reachability contains missing records"
        )
    return int(connection.execute(
        "SELECT COUNT(*) FROM clusterweave_reachable_records"
    ).fetchone()[0])


def _projection_sql(projection: _ViewerProjection, *, source: bool) -> str:
    selected = projection.source_select if source else projection.viewer_select
    query = f"SELECT {selected} FROM {_quote_identifier(projection.table)}"
    if source and projection.source_where:
        query += f" WHERE {projection.source_where}"
    return f"{query} ORDER BY {projection.order_by}"


def _typed_query_digest(cursor: sqlite3.Cursor) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    for row in cursor:
        count += 1
        digest.update(len(row).to_bytes(4, "big"))
        for value in row:
            if value is None:
                tag, encoded = b"n", b""
            elif isinstance(value, bytes):
                tag, encoded = b"b", value
            elif isinstance(value, int):
                tag, encoded = b"i", str(value).encode("ascii")
            elif isinstance(value, float):
                tag, encoded = b"f", value.hex().encode("ascii")
            else:
                tag = b"s"
                encoded = str(value).encode("utf-8", errors="surrogatepass")
            digest.update(tag)
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return count, digest.hexdigest()


def _copy_viewer_projection(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    projection: _ViewerProjection,
) -> int:
    if projection.table == "gbk":
        target_columns = (
            "id", "path", "hash", "clusterweave_nt_length",
            "organism", "taxonomy", "description",
        )
    else:
        target_columns = _EXPECTED_BIGSCAPE_COLUMNS[projection.table]
    placeholders = ",".join("?" for _ in target_columns)
    before = target.total_changes
    target.executemany(
        f"INSERT INTO {_quote_identifier(projection.table)} "
        f"({_column_csv(target_columns)}) VALUES ({placeholders})",
        source.execute(_projection_sql(projection, source=True)),
    )
    return int(target.total_changes - before)


def _viewer_marker_values(
    fingerprint: dict[str, object],
    *,
    reachable_records: int,
    gbk_rows: int,
    distance_rows: int,
) -> tuple[object, ...]:
    return (
        fingerprint["viewer_export_version"],
        fingerprint["query_contract"],
        fingerprint["path_policy"],
        fingerprint["source_export_version"],
        fingerprint["source_user_version"],
        fingerprint["source_bytes"],
        fingerprint["source_sha256"],
        fingerprint["index_bytes"],
        fingerprint["index_sha256"],
        fingerprint["bigscape_js_bytes"],
        fingerprint["bigscape_js_sha256"],
        reachable_records,
        gbk_rows,
        distance_rows,
    )


def _validate_viewer_schema(connection: sqlite3.Connection) -> None:
    expected_tables = set(_EXPECTED_BIGSCAPE_COLUMNS) | {
        PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE
    }
    if set(_user_tables(connection)) != expected_tables:
        raise BigscapePublicDatabaseError(
            "Viewer database has an unsupported table profile"
        )
    for table, expected in _EXPECTED_BIGSCAPE_COLUMNS.items():
        if table == "gbk":
            expected = _VIEWER_GBK_COLUMNS
        rows = _table_columns(connection, table)
        observed = tuple(str(row[1]).lower() for row in rows)
        if observed != expected:
            raise BigscapePublicDatabaseError(
                f"Viewer database changed columns: {table}"
            )
        if table == "gbk":
            hidden = {str(row[1]).lower(): int(row[6]) for row in rows}
            if hidden.get("nt_seq") != 2 or hidden.get("clusterweave_nt_length") != 0:
                raise BigscapePublicDatabaseError(
                    "Viewer nucleotide projection is not virtual"
                )
    marker_columns = tuple(
        str(row[1]).lower()
        for row in _table_columns(connection, PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE)
    )
    if marker_columns != _VIEWER_MARKER_COLUMNS:
        raise BigscapePublicDatabaseError(
            "Viewer database marker columns are invalid"
        )

    named_indexes = {
        (str(name), str(table))
        for name, table in connection.execute(
            "SELECT name, tbl_name FROM sqlite_master "
            "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if named_indexes != {("record_id_index", "bgc_record")}:
        raise BigscapePublicDatabaseError(
            "Viewer database has unsupported named indexes"
        )
    record_index_columns = tuple(
        str(row[2]).lower()
        for row in connection.execute("PRAGMA index_info('record_id_index')")
    )
    if record_index_columns != ("gbk_id",):
        raise BigscapePublicDatabaseError(
            "Viewer record index has an unsupported projection"
        )
    unique_distance_indexes = []
    for row in connection.execute("PRAGMA index_list('distance')"):
        if int(row[2]) == 1 and str(row[3]).lower() == "u" and int(row[4]) == 0:
            columns = tuple(
                str(item[2]).lower()
                for item in connection.execute(
                    f"PRAGMA index_info({_quote_identifier(str(row[1]))})"
                )
            )
            unique_distance_indexes.append(columns)
    if unique_distance_indexes != [
        ("record_a_id", "record_b_id", "edge_param_id")
    ]:
        raise BigscapePublicDatabaseError(
            "Viewer distance index has an unsupported projection"
        )
    other_objects = int(connection.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type NOT IN ('table', 'index') AND name NOT LIKE 'sqlite_%'"
    ).fetchone()[0])
    if other_objects:
        raise BigscapePublicDatabaseError(
            "Viewer database has unsupported schema objects"
        )
    gbk_sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='gbk'"
    ).fetchone()
    normalized_gbk_sql = re.sub(
        r"\s+", "", str(gbk_sql_row[0] if gbk_sql_row else "").lower()
    )
    if (
        "nt_seqblobgeneratedalwaysas(zeroblob(clusterweave_nt_length))virtual"
        not in normalized_gbk_sql
    ):
        raise BigscapePublicDatabaseError(
            "Viewer nucleotide projection expression is invalid"
        )


def _validate_viewer_relationships(connection: sqlite3.Connection) -> None:
    checks = (
        (
            "SELECT COUNT(*) FROM bgc_record LEFT JOIN gbk ON gbk.id=bgc_record.gbk_id "
            "WHERE bgc_record.gbk_id IS NOT NULL AND gbk.id IS NULL",
            "bgc_record.gbk_id",
        ),
        (
            "SELECT COUNT(*) FROM family LEFT JOIN bgc_record "
            "ON bgc_record.id=family.center_id "
            "WHERE family.center_id IS NOT NULL AND bgc_record.id IS NULL",
            "family.center_id",
        ),
        (
            "SELECT COUNT(*) FROM family LEFT JOIN run ON run.id=family.run_id "
            "WHERE family.run_id IS NOT NULL AND run.id IS NULL",
            "family.run_id",
        ),
        (
            "SELECT COUNT(*) FROM bgc_record_family LEFT JOIN bgc_record "
            "ON bgc_record.id=bgc_record_family.record_id "
            "WHERE bgc_record_family.record_id IS NOT NULL AND bgc_record.id IS NULL",
            "bgc_record_family.record_id",
        ),
        (
            "SELECT COUNT(*) FROM bgc_record_family LEFT JOIN family "
            "ON family.id=bgc_record_family.family_id "
            "WHERE bgc_record_family.family_id IS NOT NULL AND family.id IS NULL",
            "bgc_record_family.family_id",
        ),
        (
            "SELECT COUNT(*) FROM connected_component LEFT JOIN bgc_record "
            "ON bgc_record.id=connected_component.record_id "
            "WHERE connected_component.record_id IS NOT NULL AND bgc_record.id IS NULL",
            "connected_component.record_id",
        ),
        (
            "SELECT COUNT(*) FROM connected_component LEFT JOIN run "
            "ON run.id=connected_component.run_id "
            "WHERE connected_component.run_id IS NOT NULL AND run.id IS NULL",
            "connected_component.run_id",
        ),
        (
            "SELECT COUNT(*) FROM cds LEFT JOIN gbk ON gbk.id=cds.gbk_id "
            "WHERE cds.gbk_id IS NOT NULL AND gbk.id IS NULL",
            "cds.gbk_id",
        ),
        (
            "SELECT COUNT(*) FROM hsp LEFT JOIN cds ON cds.id=hsp.cds_id "
            "WHERE hsp.cds_id IS NOT NULL AND cds.id IS NULL",
            "hsp.cds_id",
        ),
        (
            "SELECT COUNT(*) FROM hsp_alignment LEFT JOIN hsp "
            "ON hsp.id=hsp_alignment.hsp_id "
            "WHERE hsp_alignment.hsp_id IS NOT NULL AND hsp.id IS NULL",
            "hsp_alignment.hsp_id",
        ),
        (
            "SELECT COUNT(*) FROM scanned_cds LEFT JOIN cds "
            "ON cds.id=scanned_cds.cds_id "
            "WHERE scanned_cds.cds_id IS NOT NULL AND cds.id IS NULL",
            "scanned_cds.cds_id",
        ),
        (
            "SELECT COUNT(*) FROM distance LEFT JOIN bgc_record "
            "ON bgc_record.id=distance.record_a_id "
            "WHERE distance.record_a_id IS NOT NULL AND bgc_record.id IS NULL",
            "distance.record_a_id",
        ),
        (
            "SELECT COUNT(*) FROM distance LEFT JOIN bgc_record "
            "ON bgc_record.id=distance.record_b_id "
            "WHERE distance.record_b_id IS NOT NULL AND bgc_record.id IS NULL",
            "distance.record_b_id",
        ),
        (
            "SELECT COUNT(*) FROM distance LEFT JOIN edge_params "
            "ON edge_params.id=distance.edge_param_id "
            "WHERE distance.edge_param_id IS NOT NULL AND edge_params.id IS NULL",
            "distance.edge_param_id",
        ),
    )
    for query, label in checks:
        if int(connection.execute(query).fetchone()[0]):
            raise BigscapePublicDatabaseError(
                f"Viewer database has an orphaned {label} relationship"
            )


def _validate_viewer_candidate(
    path: Path,
    public_database: Path,
    baseline: _SourceBaseline,
    fingerprint: dict[str, object],
    *,
    max_viewer_bytes: int,
    require_sidecar: bool,
) -> dict[str, int]:
    if not path.is_file() or path.is_symlink():
        raise BigscapePublicDatabaseError(
            "Viewer database is not a regular file"
        )
    viewer_bytes = int(path.stat().st_size)
    if viewer_bytes <= 0 or viewer_bytes > max_viewer_bytes:
        raise BigscapePublicDatabaseError(
            "Viewer database exceeds the strict size limit"
        )
    with path.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise BigscapePublicDatabaseError(
                "Viewer database has invalid SQLite magic"
            )
    if require_sidecar:
        sidecar = path.parent / VIEWER_SIDECAR_FILENAME
        if sidecar.is_symlink() or _read_sidecar(sidecar) != fingerprint:
            raise BigscapePublicDatabaseError(
                "Viewer database source sidecar is invalid"
            )

    current_baseline = _public_source_baseline(public_database)
    if current_baseline != baseline:
        raise BigscapePublicDatabaseError(
            "Viewer source baseline changed during validation"
        )

    viewer = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    source = sqlite3.connect(
        f"{public_database.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    )
    try:
        integrity = viewer.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            raise BigscapePublicDatabaseError(
                "Viewer database failed integrity_check"
            )
        if list(viewer.execute("PRAGMA foreign_key_check")):
            raise BigscapePublicDatabaseError(
                "Viewer database failed foreign_key_check"
            )
        if int(viewer.execute("PRAGMA freelist_count").fetchone()[0]) != 0:
            raise BigscapePublicDatabaseError(
                "Viewer database contains free pages"
            )
        if int(viewer.execute("PRAGMA user_version").fetchone()[0]) != baseline.user_version:
            raise BigscapePublicDatabaseError(
                "Viewer database changed user_version"
            )
        _validate_viewer_schema(viewer)
        _validate_viewer_relationships(viewer)
        raw_nt = int(viewer.execute(
            "SELECT COUNT(*) FROM gbk WHERE clusterweave_nt_length IS NULL "
            "OR clusterweave_nt_length < 0 OR typeof(nt_seq) != 'blob' "
            "OR length(nt_seq) != clusterweave_nt_length"
        ).fetchone()[0])
        raw_aa = int(viewer.execute(
            "SELECT COUNT(*) FROM cds WHERE typeof(aa_seq) != 'text' OR aa_seq != ''"
        ).fetchone()[0])
        raw_alignment = int(viewer.execute(
            "SELECT COUNT(*) FROM hsp_alignment "
            "WHERE typeof(alignment) != 'text' OR alignment != ''"
        ).fetchone()[0])
        if raw_nt or raw_aa or raw_alignment:
            raise BigscapePublicDatabaseError(
                "Viewer database contains raw sequence content"
            )

        reachable_records = _create_reachable_records(source)
        counts: dict[str, int] = {}
        for projection in _VIEWER_PROJECTIONS:
            expected = _typed_query_digest(
                source.execute(_projection_sql(projection, source=True))
            )
            observed = _typed_query_digest(
                viewer.execute(_projection_sql(projection, source=False))
            )
            if observed != expected:
                raise BigscapePublicDatabaseError(
                    f"Viewer projection changed rows: {projection.table}"
                )
            counts[projection.table] = observed[0]
        marker = viewer.execute(
            f"SELECT {_column_csv(_VIEWER_MARKER_COLUMNS)} FROM "
            f"{_quote_identifier(PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE)}"
        ).fetchall()
        expected_marker = _viewer_marker_values(
            fingerprint,
            reachable_records=reachable_records,
            gbk_rows=counts["gbk"],
            distance_rows=counts["distance"],
        )
        if marker != [expected_marker]:
            raise BigscapePublicDatabaseError(
                "Viewer database export marker is invalid"
            )
    finally:
        source.close()
        viewer.close()

    leaked = _contains_binary_marker(path, _PRIVATE_BINARY_MARKERS)
    if leaked:
        raise BigscapePublicDatabaseError(
            "Viewer database retained a private path marker"
        )
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(path) + suffix).exists():
            raise BigscapePublicDatabaseError(
                "Viewer database left a SQLite sidecar"
            )
    if _viewer_source_fingerprint(public_database, baseline) != fingerprint:
        raise BigscapePublicDatabaseError(
            "Viewer source changed during validation"
        )
    counts["viewer_bytes"] = viewer_bytes
    counts["reachable_records"] = reachable_records
    return counts


def validate_public_bigscape_viewer_database(
    path: Path,
    *,
    max_viewer_bytes: int = DEFAULT_MAX_VIEWER_BYTES,
) -> dict[str, int]:
    path = Path(path)
    if max_viewer_bytes <= 0 or max_viewer_bytes > DEFAULT_MAX_VIEWER_BYTES:
        raise BigscapePublicDatabaseError(
            "Viewer database size policy is invalid"
        )
    if (
        path.name != PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME
        or path.parent.name != PUBLIC_BIGSCAPE_PUBLIC_DIR
    ):
        raise BigscapePublicDatabaseError(
            "Viewer database path is not canonical"
        )
    public_database = path.parent / PUBLIC_BIGSCAPE_DATABASE_FILENAME
    baseline = _public_source_baseline(public_database)
    fingerprint = _viewer_source_fingerprint(public_database, baseline)
    return _validate_viewer_candidate(
        path,
        public_database,
        baseline,
        fingerprint,
        max_viewer_bytes=max_viewer_bytes,
        require_sidecar=True,
    )


def public_bigscape_viewer_database_valid(path: Path) -> bool:
    try:
        validate_public_bigscape_viewer_database(path)
        return True
    except (BigscapePublicDatabaseError, OSError, sqlite3.Error):
        return False


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_public_bigscape_viewer_database(
    public_database: Path,
    *,
    max_viewer_bytes: int = DEFAULT_MAX_VIEWER_BYTES,
    force: bool = False,
) -> tuple[Path, bool, int] | None:
    public_database = Path(public_database)
    if max_viewer_bytes <= 0 or max_viewer_bytes > DEFAULT_MAX_VIEWER_BYTES:
        raise BigscapePublicDatabaseError(
            "Viewer database size policy is invalid"
        )
    if not _viewer_assets_present(public_database):
        return None

    baseline = _public_source_baseline(public_database)
    fingerprint = _viewer_source_fingerprint(public_database, baseline)
    output = public_database.parent / PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME
    sidecar = public_database.parent / VIEWER_SIDECAR_FILENAME
    if output.is_symlink() or sidecar.is_symlink():
        raise BigscapePublicDatabaseError(
            "BiG-SCAPE viewer artifact is a symlink"
        )
    existing_bytes = int(output.stat().st_size) if output.is_file() else 0
    required_free = (max_viewer_bytes * 2) + existing_bytes + MIN_FREE_BYTES
    if shutil.disk_usage(output.parent).free < required_free:
        raise BigscapePublicDatabaseError(
            "Insufficient free space for compact BiG-SCAPE viewer database"
        )

    if (
        not force
        and output.is_file()
        and _read_sidecar(sidecar) == fingerprint
    ):
        try:
            checked = _validate_viewer_candidate(
                output,
                public_database,
                baseline,
                fingerprint,
                max_viewer_bytes=max_viewer_bytes,
                require_sidecar=True,
            )
            return output, True, checked["viewer_bytes"]
        except BigscapePublicDatabaseError:
            pass

    token = secrets.token_hex(8)
    work = output.parent / f".{output.name}.{token}.work"
    vacuumed = output.parent / f".{output.name}.{token}.vacuum"
    _remove_sqlite_artifact(work)
    _remove_sqlite_artifact(vacuumed)
    try:
        source = sqlite3.connect(
            f"{public_database.resolve().as_uri()}?mode=ro&immutable=1",
            uri=True,
        )
        target = sqlite3.connect(work)
        try:
            target.execute("PRAGMA page_size=4096")
            target.execute("PRAGMA journal_mode=DELETE")
            target.execute("PRAGMA auto_vacuum=NONE")
            target.execute("PRAGMA secure_delete=ON")
            target.executescript(_VIEWER_SCHEMA_SQL)
            target.execute(f"PRAGMA user_version={int(baseline.user_version)}")
            reachable_records = _create_reachable_records(source)
            target.execute("BEGIN IMMEDIATE")
            copied = {
                projection.table: _copy_viewer_projection(
                    source, target, projection
                )
                for projection in _VIEWER_PROJECTIONS
            }
            marker_values = _viewer_marker_values(
                fingerprint,
                reachable_records=reachable_records,
                gbk_rows=copied["gbk"],
                distance_rows=copied["distance"],
            )
            target.execute(
                f"INSERT INTO "
                f"{_quote_identifier(PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE)} "
                f"({_column_csv(_VIEWER_MARKER_COLUMNS)}) VALUES "
                f"({','.join('?' for _ in _VIEWER_MARKER_COLUMNS)})",
                marker_values,
            )
            target.commit()
            target.execute("VACUUM INTO ?", (str(vacuumed),))
        finally:
            target.close()
            source.close()

        checked = _validate_viewer_candidate(
            vacuumed,
            public_database,
            baseline,
            fingerprint,
            max_viewer_bytes=max_viewer_bytes,
            require_sidecar=False,
        )
        if _viewer_source_fingerprint(public_database, baseline) != fingerprint:
            raise BigscapePublicDatabaseError(
                "Viewer source changed during generation"
            )
        os.chmod(vacuumed, 0o640)
        with vacuumed.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(vacuumed, output)
        _write_sidecar(sidecar, fingerprint)
        _fsync_directory(output.parent)
        return output, False, checked["viewer_bytes"]
    except BigscapePublicDatabaseError:
        raise
    except Exception as exc:
        raise BigscapePublicDatabaseError(
            f"Could not create compact BiG-SCAPE viewer database: {type(exc).__name__}"
        ) from exc
    finally:
        _remove_sqlite_artifact(work)
        _remove_sqlite_artifact(vacuumed)


def _prepare_optional_bigscape_viewer(
    public_database: Path,
    *,
    max_viewer_bytes: int,
    force: bool,
) -> tuple[Path | None, int]:
    try:
        prepared = create_public_bigscape_viewer_database(
            public_database,
            max_viewer_bytes=max_viewer_bytes,
            force=force,
        )
        return (prepared[0], prepared[2]) if prepared is not None else (None, 0)
    except (BigscapePublicDatabaseError, OSError, sqlite3.Error):
        # Remove only the attestation sidecar. Any stale viewer file is then
        # impossible to advertise or serve, while remaining available for
        # operator diagnosis.
        sidecar = public_database.parent / VIEWER_SIDECAR_FILENAME
        try:
            if sidecar.is_file() or sidecar.is_symlink():
                sidecar.unlink()
        except OSError:
            pass
        return None, 0


def sanitize_bigscape_database(
    source: Path,
    *,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    max_viewer_bytes: int = DEFAULT_MAX_VIEWER_BYTES,
    force: bool = False,
) -> PublicBigscapeDatabase:
    source = Path(source)
    if not source.is_file() or source.is_symlink():
        raise BigscapePublicDatabaseError("Raw BiG-SCAPE database is not a regular file")
    if source.name.lower() not in RAW_BIGSCAPE_DATABASE_FILENAMES:
        raise BigscapePublicDatabaseError("Raw BiG-SCAPE database filename is unsupported")
    source_size = int(source.stat().st_size)
    if source_size <= 0 or source_size > max_source_bytes:
        raise BigscapePublicDatabaseError("Raw BiG-SCAPE database exceeds the publication limit")
    _assert_no_source_sidecars(source)

    public_dir = _public_directory_for_source(source)
    if public_dir.exists() and public_dir.is_symlink():
        raise BigscapePublicDatabaseError("BiG-SCAPE public database directory is a symlink")
    public_dir.mkdir(parents=True, exist_ok=True)
    output = public_dir / PUBLIC_BIGSCAPE_DATABASE_FILENAME
    sidecar = public_dir / SIDECAR_FILENAME
    if output.is_symlink() or sidecar.is_symlink():
        raise BigscapePublicDatabaseError("BiG-SCAPE public database artifact is a symlink")
    existing_bytes = int(output.stat().st_size) if output.is_file() else 0
    required_free = (source_size * 2) + existing_bytes + MIN_FREE_BYTES
    if shutil.disk_usage(public_dir).free < required_free:
        raise BigscapePublicDatabaseError(
            "Insufficient free space for sanitized BiG-SCAPE database"
        )

    try:
        fingerprint = _source_fingerprint(source)
        source_connection = sqlite3.connect(
            f"{source.resolve().as_uri()}?mode=ro",
            uri=True,
        )
        try:
            baseline = _source_baseline(source_connection)
        finally:
            source_connection.close()
    except BigscapePublicDatabaseError:
        raise
    except Exception as exc:
        raise BigscapePublicDatabaseError(
            f"Could not inspect raw BiG-SCAPE database: {type(exc).__name__}"
        ) from exc

    if (
        not force
        and output.is_file()
        and _read_sidecar(sidecar) == fingerprint
    ):
        try:
            dataset, reference, query = _validate_public_database(
                output,
                baseline,
                binary_markers=baseline.path_markers,
            )
            viewer_path, viewer_bytes = _prepare_optional_bigscape_viewer(
                output,
                max_viewer_bytes=max_viewer_bytes,
                force=force,
            )
            return PublicBigscapeDatabase(
                source.name,
                output,
                True,
                source_size,
                int(output.stat().st_size),
                dataset,
                reference,
                query,
                viewer_path,
                viewer_bytes,
            )
        except BigscapePublicDatabaseError:
            pass

    token = secrets.token_hex(8)
    work = public_dir / f".{PUBLIC_BIGSCAPE_DATABASE_FILENAME}.{token}.work"
    vacuumed = public_dir / f".{PUBLIC_BIGSCAPE_DATABASE_FILENAME}.{token}.vacuum"
    _remove_sqlite_artifact(work)
    _remove_sqlite_artifact(vacuumed)

    try:
        source_connection = sqlite3.connect(
            f"{source.resolve().as_uri()}?mode=ro",
            uri=True,
        )
        work_connection = sqlite3.connect(work)
        try:
            source_connection.backup(work_connection, pages=16_384)
            work_connection.execute("PRAGMA journal_mode=DELETE")
            work_connection.execute("PRAGMA secure_delete=ON")
            work_connection.execute("BEGIN IMMEDIATE")
            dataset, reference, query, query_filename = _sanitize_gbk_paths(
                work_connection
            )
            _sanitize_run_paths(
                work_connection,
                query_filename=query_filename,
            )
            _redact_sequence_contents_and_hashes(work_connection)
            _create_export_marker(
                work_connection,
                source_name=source.name,
                dataset_paths=dataset,
                reference_paths=reference,
                query_paths=query,
            )
            work_connection.commit()
            work_connection.execute("VACUUM INTO ?", (str(vacuumed),))
        finally:
            work_connection.close()
            source_connection.close()

        checked = _validate_public_database(
            vacuumed,
            baseline,
            binary_markers=baseline.path_markers,
        )
        if checked != (dataset, reference, query):
            raise BigscapePublicDatabaseError("Sanitized database validation counts changed")
        if _source_fingerprint(source) != fingerprint:
            raise BigscapePublicDatabaseError(
                "Raw BiG-SCAPE database changed during sanitization"
            )
        os.chmod(vacuumed, 0o640)
        with vacuumed.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(vacuumed, output)
        _write_sidecar(sidecar, fingerprint)
        viewer_path, viewer_bytes = _prepare_optional_bigscape_viewer(
            output,
            max_viewer_bytes=max_viewer_bytes,
            force=force,
        )
        return PublicBigscapeDatabase(
            source.name,
            output,
            False,
            source_size,
            int(output.stat().st_size),
            dataset,
            reference,
            query,
            viewer_path,
            viewer_bytes,
        )
    except Exception as exc:
        if isinstance(exc, BigscapePublicDatabaseError):
            raise
        raise BigscapePublicDatabaseError(
            f"Could not create sanitized BiG-SCAPE database: {type(exc).__name__}"
        ) from exc
    finally:
        _remove_sqlite_artifact(work)
        _remove_sqlite_artifact(vacuumed)


def find_raw_bigscape_databases(results_root: Path) -> list[Path]:
    results_root = Path(results_root)
    if not results_root.is_dir() or results_root.is_symlink():
        return []
    candidates: list[Path] = []
    relative_candidates = (
        Path("big_scape.db"),
        Path("data_sqlite.db"),
        Path("output_files") / "data_sqlite.db",
        Path("output_files") / "big_scape.db",
    )
    for root_name in sorted(PUBLIC_BIGSCAPE_ROOTS):
        tool_root = results_root / root_name
        for relative in relative_candidates:
            source = tool_root / relative
            if source.is_file() and not source.is_symlink():
                candidates.append(source)
                break
    return candidates


def prepare_public_bigscape_databases(
    results_root: Path,
    *,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    max_viewer_bytes: int = DEFAULT_MAX_VIEWER_BYTES,
    force: bool = False,
) -> PublicBigscapePreparation:
    databases: list[PublicBigscapeDatabase] = []
    errors: list[str] = []
    for source in find_raw_bigscape_databases(results_root):
        try:
            databases.append(
                sanitize_bigscape_database(
                    source,
                    max_source_bytes=max_source_bytes,
                    max_viewer_bytes=max_viewer_bytes,
                    force=force,
                )
            )
        except BigscapePublicDatabaseError as exc:
            errors.append(f"{source.name}: {exc}")
    return PublicBigscapePreparation(tuple(databases), tuple(errors))


__all__ = [
    "BigscapePublicDatabaseError",
    "DEFAULT_MAX_SOURCE_BYTES",
    "DEFAULT_MAX_VIEWER_BYTES",
    "MIN_FREE_BYTES",
    "PUBLIC_EXPORT_TABLE",
    "PUBLIC_EXPORT_VERSION",
    "PUBLIC_PATH_POLICY",
    "PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME",
    "PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE",
    "PUBLIC_BIGSCAPE_VIEWER_EXPORT_VERSION",
    "PUBLIC_BIGSCAPE_VIEWER_PATH_POLICY",
    "PUBLIC_BIGSCAPE_VIEWER_QUERY_CONTRACT",
    "PublicBigscapeDatabase",
    "PublicBigscapePreparation",
    "find_raw_bigscape_databases",
    "create_public_bigscape_viewer_database",
    "prepare_public_bigscape_databases",
    "public_bigscape_viewer_database_valid",
    "sanitize_bigscape_database",
    "validate_public_bigscape_viewer_database",
]
