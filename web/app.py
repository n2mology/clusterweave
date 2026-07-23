#!/usr/bin/env python3
from __future__ import annotations

import codecs
import io
import warnings

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*cgi.*")
    import cgi
import json
import hashlib
import hmac
from collections import OrderedDict
import mimetypes
import os
import re
import secrets
import sqlite3
import shutil
import sys
import tempfile
import threading
from datetime import datetime
import urllib.parse
import urllib.error
import urllib.request
import uuid
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from genbank_readiness import inspect_genbank_translation_stream
from bigscape_public_db import (
    DEFAULT_MAX_VIEWER_BYTES,
    PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE,
    PUBLIC_BIGSCAPE_VIEWER_EXPORT_VERSION,
    PUBLIC_BIGSCAPE_VIEWER_PATH_POLICY,
    PUBLIC_BIGSCAPE_VIEWER_QUERY_CONTRACT,
)
from job_store import (
    DATA_DIR,
    QUEUE_DIR,
    append_log,
    atomic_write_text,
    job_dir,
    list_jobs,
    list_job_summaries,
    now_iso,
    read_retention_totals,
    read_job,
    read_log_window,
    read_log_slice,
    read_logs,
    read_logs_since,
    record_deleted_terminal_job,
    request_job_cancel,
    write_job,
)
from notifications import validate_email
from result_attestation import (
    read_result_attestation,
    schedule_result_attestation_backfill,
)
from public_results import (
    generate_public_run_id,
    public_run_id_for_job,
)
from public_result_backend import artifact_catalog_for_job, resolve_public_job
from public_result_http import handle_public_result_get, handle_public_result_post
from result_policy import (
    PUBLIC_RESULTS_MANIFEST_PATH,
    PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME,
    PUBLIC_BIGSCAPE_EXPORT_TABLE,
    PUBLIC_BIGSCAPE_EXPORT_VERSION,
    PUBLIC_BIGSCAPE_PATH_POLICY,
    PUBLIC_BIGSCAPE_ROOTS,
    result_is_public_bigscape_database,
    result_is_public_bigscape_viewer_database,
    normalized_job_result_path,
    result_is_public_archive,
    result_path_public_shape,
)
from resource_policy import ResourceRequest, genome_count_from_input_summary
from runtime_capabilities import unavailable_stage_reason
from taxon_routing import (
    MAX_ASSIGNMENT_BYTES,
    ROUTING_MUTATION_FIELDS,
    TaxonRoutingError,
    build_taxon_routes,
    merge_assignments,
    normalize_analysis_scope,
    parse_assignment_json,
    parse_assignment_tsv,
    parse_genbank_taxonomy_stream,
    summarize_taxon_routes,
)

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
ACCESS_LOG_SECRET_QUERY_RE = re.compile(
    r"(?i)([?&](?:access[_-]?token|api[_-]?key|auth[_-]?token|credential|googleaccessid|key-pair-id|password|policy|read[_-]?token|secret|sig|signature|token|x-amz-credential|x-amz-security-token|x-amz-signature|x-goog-credential|x-goog-signature)=)([^&#\s]+)"
)
ACCESS_LOG_SIGNED_QUERY_RE = re.compile(
    r"(?i)[?&](?:googleaccessid|key-pair-id|policy|sig|signature|x-amz-credential|x-amz-security-token|x-amz-signature|x-goog-credential|x-goog-signature)="
)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def sanitize_access_log_text(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").replace("\x00", "")
    if ACCESS_LOG_SIGNED_QUERY_RE.search(text):
        text = re.sub(r"\?[^\s\"]+", "?[signed-query-redacted]", text)
    else:
        text = ACCESS_LOG_SECRET_QUERY_RE.sub(
            lambda match: f"{match.group(1)}[redacted]", text
        )
    text = re.sub(
        r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*[^\s]+",
        lambda match: f"{match.group(1)}: [redacted]",
        text,
    )
    return text[:2048]


PUBLIC_MODE = env_bool("CLUSTERWEAVE_PUBLIC_MODE", False)
ALLOW_UNSAFE_LOCAL_MODE = env_bool("CLUSTERWEAVE_ALLOW_UNSAFE_LOCAL_MODE", False)
SUBMISSIONS_OPEN = env_bool("CLUSTERWEAVE_SUBMISSIONS_OPEN", True)
SUBMIT_TOKEN = os.environ.get("CLUSTERWEAVE_SUBMIT_TOKEN", "")
SUBMIT_TOKEN_SHA256 = (
    os.environ.get("CLUSTERWEAVE_SUBMIT_TOKEN_SHA256", "")
    or os.environ.get("CLUSTERWEAVE_SUBMIT_TOKEN_HASH", "")
)
ADMIN_TOKEN = os.environ.get("CLUSTERWEAVE_ADMIN_TOKEN", "")
ADMIN_TOKEN_SHA256 = (
    os.environ.get("CLUSTERWEAVE_ADMIN_TOKEN_SHA256", "")
    or os.environ.get("CLUSTERWEAVE_ADMIN_TOKEN_HASH", "")
)
JOB_TOKEN_SECRET = os.environ.get("CLUSTERWEAVE_JOB_TOKEN_SECRET", "")
ALLOW_ENV_OVERRIDES = env_bool("CLUSTERWEAVE_ALLOW_ENV_OVERRIDES", False)
MAX_ACCESSIONS = env_int("CLUSTERWEAVE_MAX_ACCESSIONS", 50, minimum=1)
MAX_GENOME_FILES = env_int("CLUSTERWEAVE_MAX_GENOME_FILES", 50, minimum=1)
MAX_UPLOAD_FILE_MB = env_int("CLUSTERWEAVE_MAX_UPLOAD_FILE_MB", 500, minimum=1)
MAX_UPLOAD_TOTAL_MB = env_int("CLUSTERWEAVE_MAX_UPLOAD_TOTAL_MB", 1024, minimum=1)
MAX_UPLOAD_BODY_OVERHEAD_MB = env_int(
    "CLUSTERWEAVE_MAX_UPLOAD_BODY_OVERHEAD_MB", 16, minimum=1
)
MAX_CONCURRENT_UPLOADS = env_int(
    "CLUSTERWEAVE_MAX_CONCURRENT_UPLOADS", 2, minimum=1
)
MAX_QUEUED_JOBS = env_int("CLUSTERWEAVE_MAX_QUEUED_JOBS", 50, minimum=0)
MAX_CPUS_PER_JOB = env_int("CLUSTERWEAVE_MAX_CPUS_PER_JOB", 8, minimum=1)
MIN_FREE_DISK_GB = env_int("CLUSTERWEAVE_MIN_FREE_DISK_GB", 0, minimum=0)
PUBLIC_GENOME_PARALLELISM = env_int("CLUSTERWEAVE_PUBLIC_GENOME_PARALLELISM", 1, minimum=1)
PUBLIC_ANTISMASH_RECORD_PARALLELISM = env_int(
    "CLUSTERWEAVE_PUBLIC_ANTISMASH_RECORD_PARALLELISM", 1, minimum=1
)
PUBLIC_FUNANNOTATE_CPUS_PER_GENOME = env_int(
    "CLUSTERWEAVE_PUBLIC_FUNANNOTATE_CPUS_PER_GENOME", 4, minimum=1
)
PUBLIC_FUNBGCEX_WORKERS_PER_GENOME = env_int(
    "CLUSTERWEAVE_PUBLIC_FUNBGCEX_WORKERS_PER_GENOME", 2, minimum=1
)
SMTP_ENABLED = env_bool("CLUSTERWEAVE_SMTP_ENABLED", False)
ALLOWED_CORS_ORIGINS = {
    origin.strip()
    for origin in os.environ.get("CLUSTERWEAVE_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}
WEB_DISABLED_ANNOTATION_FALLBACKS = {"braker3", "braker"}
WEB_PUBLIC_FUNANNOTATE_BUSCO_DB = "auto"
WEB_PUBLIC_FUNANNOTATE_ORGANISM_NAME = "auto"
WEB_DISABLED_RUNTIME_ENV_KEYS = {
    "BRAKER3_ENABLED",
    "BRAKER_BAM",
    "BRAKER_IMAGE_URI",
    "BRAKER_PROT_SEQ",
    "BRAKER_SIF",
    "GENEMARK_KEY",
    "GENEMARK_PATH",
    "TAXONOMY_METADATA",
}
WEB_RESOURCE_ENV_KEYS = {
    "CPUS",
    "THREADS",
    "ANNO_CPUS",
    "WORKERS",
    "GENOME_PARALLELISM",
    "ANNOTATION_GENOME_PARALLELISM",
    "ANTISMASH_RECORD_PARALLELISM",
    "ANTISMASH_SHARD_CPUS",
    "ANTISMASH_LEGACY_CPUS",
    "RUN_PHYLOGENY",
    "PHYLOGENY_CPUS",
    "PHYLOGENY_PARALLELISM",
    "PIPELINE_RESOURCE_MODE",
    "PIPELINE_MEMORY_BUDGET_MB",
    "PIPELINE_AUTO_MAX_CPUS",
    "PIPELINE_AUTO_MAX_GENOME_PARALLELISM",
    "PIPELINE_AUTO_MIN_CPUS_PER_GENOME",
    "PIPELINE_AUTO_MEMORY_PERCENT",
    "PIPELINE_AUTO_MEMORY_PER_GENOME_MB",
    "PIPELINE_AUTO_MAX_ANNO_CPUS",
    "PIPELINE_AUTO_MAX_FUNBGCEX_WORKERS",
    "PIPELINE_AUTO_MAX_ANTISMASH_RECORD_PARALLELISM",
    "CLUSTERWEAVE_TOOL_DOCKER_CPUS",
    "CLUSTERWEAVE_TOOL_DOCKER_MEMORY",
    "CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT",
    "CLUSTERWEAVE_CHILD_DOCKER_CPUS",
    "CLUSTERWEAVE_CHILD_DOCKER_MEMORY",
    "CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT",
    "CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
}

ALLOWED_EXTENSIONS = {
    ".gbk",
    ".gb",
    ".gbff",
    ".fasta",
    ".fa",
    ".fna",
    ".fsa",
    ".txt",
    ".tsv",
    ".csv",
    ".json",
    ".gff",
    ".gff3",
    ".faa",
    ".mgf",
    ".zip",
}

SENSITIVE_JOB_FIELDS = {
    "notify_email",
    "email_read_token_created_at",
    "read_token_hashes",
    "read_token",
    "read_token_hash",
    "read_token_created_at",
}
PROCESSED_JOB_STATUSES = {"success", "failed"}
QUEUED_JOB_STATUSES = {"pending", "running"}
PUBLIC_ACTIVITY_LIMIT = 40
PUBLIC_LOG_PROJECTION_CACHE_JOBS = env_int(
    "CLUSTERWEAVE_PUBLIC_LOG_PROJECTION_CACHE_JOBS", 16, minimum=1
)
_PUBLIC_LOG_PROJECTION_LOCK = threading.RLock()
_PUBLIC_LOG_PROJECTIONS: OrderedDict[str, dict[str, object]] = OrderedDict()
PUBLIC_GENOME_EXTENSIONS = {".fasta", ".fa", ".fna", ".fsa", ".gb", ".gbk", ".gbff"}
PUBLIC_ACCESSION_EXTENSIONS = {".txt"}
PUBLIC_FASTA_EXTENSIONS = {".fasta", ".fa", ".fna", ".fsa"}
PUBLIC_GENBANK_EXTENSIONS = {".gb", ".gbk", ".gbff"}
PUBLIC_GENOME_STEM_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
PUBLIC_NUCLEOTIDE_CHARS = set("ACGTRYSWKMBDHVNU-.")
PUBLIC_ECOLOGY_METADATA_FILENAME = "ecofun_metadata_normalized.tsv"
PUBLIC_TAXON_ASSIGNMENTS_FILENAME = "taxon_assignments.tsv"
MANUAL_ACCESSIONS_FILENAME = "manual_accessions.txt"
PUBLIC_GENERATED_ECOLOGY_FIELDS = (
    "accession",
    "genome_id_current",
    "taxonomy_id",
    "genome_size_mb",
    "genome_id_original_if_different",
    "ecofun_primary",
    "ecofun_secondary",
)
PUBLIC_GENERATED_ECOLOGY_MAX_BYTES = 64 * 1024
PUBLIC_GENERATED_ECOLOGY_LABEL_MAX_CHARS = 40
NCBI_ASSEMBLY_ACCESSION_RE = re.compile(r"^(?:GCA|GCF)_\d{9}\.\d+$", re.IGNORECASE)
NCBI_ACCESSION_EXAMPLES = "GCA_000011425.1 or GCA_030770425.1"
NCBI_DATASETS_API_BASE = os.environ.get("CLUSTERWEAVE_NCBI_DATASETS_API_BASE", "https://api.ncbi.nlm.nih.gov/datasets/v2").rstrip("/")
NCBI_ACCESSION_PREFLIGHT = env_bool("CLUSTERWEAVE_NCBI_ACCESSION_PREFLIGHT", True)
NCBI_PREFLIGHT_TIMEOUT_SECONDS = env_int("CLUSTERWEAVE_NCBI_PREFLIGHT_TIMEOUT_SECONDS", 8, minimum=1)
NCBI_FUNGAL_TAXON_ID = 4751
NCBI_BACTERIAL_TAXON_ID = 2
TAXONOMY_RANK_FIELDS = (
    "domain",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
)
TAXONOMY_METADATA_FIELDS = (
    "input_key",
    "source_accession",
    "taxid",
    "organism_name",
    "taxon_group",
    "taxon_source",
    *TAXONOMY_RANK_FIELDS,
    "lineage_names",
    "lineage_ids",
)
MAX_TAXONOMY_METADATA_ROWS = 200
MAX_TAXONOMY_NAME_CHARS = 240
MAX_TAXONOMY_LINEAGE_NAMES = 32
MAX_TAXONOMY_LINEAGE_CHARS = 2048
PUBLIC_ACTIVITY_TOKEN_RE = re.compile(r"[^A-Za-z0-9._-]+")
BYTES_PER_MB = 1024 * 1024
BYTES_PER_GB = 1024 * 1024 * 1024
UPLOAD_COPY_CHUNK_BYTES = 1024 * 1024
MULTIPART_FIELD_MAX_BYTES = 64 * 1024
UPLOAD_STAGING_DIR = Path(
    os.environ.get("CLUSTERWEAVE_UPLOAD_STAGING_DIR", str(DATA_DIR / ".upload_staging"))
)
UPLOAD_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_UPLOADS)
WORKER_STATUS_PATH = Path(os.environ.get("DATA_DIR", "/data")) / "worker" / "status.json"
STATIC_DIR = Path(__file__).parent / "static"
STATIC_ASSET_DIR = STATIC_DIR / "assets"
STATIC_VENDOR_DIR = STATIC_DIR / "vendor"
INLINE_MIME_OVERRIDES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml; charset=utf-8",
    ".svgz": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".sqlite": "application/vnd.sqlite3",
}


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_path(path: str) -> tuple[str, dict[str, list[str]]]:
    parsed = urllib.parse.urlparse(path)
    return parsed.path, urllib.parse.parse_qs(parsed.query)


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_payload_bool(payload: dict[str, object], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def settings_bool(settings: dict[str, object], key: str, default: bool = False) -> bool:
    value = settings.get(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def web_safe_annotation_fallback_order(value: object) -> str:
    parts = [
        part.strip()
        for part in str(value or "").split(",")
        if part.strip()
    ]
    allowed = [
        part
        for part in parts
        if part.lower() not in WEB_DISABLED_ANNOTATION_FALLBACKS
    ]
    return ",".join(allowed) or "funannotate"


def annotation_request_uses_web_disabled_fallback(settings: dict[str, object]) -> bool:
    mode = str(settings.get("genefinding_mode", "")).lower()
    order = str(settings.get("annotation_fallback_order", "")).lower()
    if any(token in mode for token in WEB_DISABLED_ANNOTATION_FALLBACKS):
        return True
    if any(token in order for token in WEB_DISABLED_ANNOTATION_FALLBACKS):
        return True
    return settings_bool(settings, "braker3_enabled", False)


def scrub_web_disabled_annotation_settings(settings: dict[str, object]) -> None:
    fallback_order = web_safe_annotation_fallback_order(settings.get("annotation_fallback_order", "funannotate"))
    settings["annotation_fallback_order"] = fallback_order
    if annotation_request_uses_web_disabled_fallback(settings):
        settings["genefinding_mode"] = "funannotate" if "funannotate" in fallback_order else "auto"
    settings["braker3_enabled"] = False


def restricted_env_override_key(env_overrides: str) -> str:
    for raw_line in env_overrides.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip().upper()
        if key in WEB_DISABLED_RUNTIME_ENV_KEYS or key in WEB_RESOURCE_ENV_KEYS:
            return key
    return ""


def validate_web_runtime_policy(settings: dict[str, object]) -> str | None:
    env_overrides = str(settings.get("env_overrides", "")).strip()
    restricted_key = restricted_env_override_key(env_overrides) if env_overrides else ""
    if restricted_key:
        return (
            f"Restricted runtime/resource key {restricted_key} is not available "
            "through the web portal"
        )
    return None


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, object] | None:
    content_length = parse_int(handler.headers.get("Content-Length", "0"), 0)
    if content_length <= 0:
        return {}
    try:
        payload = json.loads(handler.rfile.read(content_length).decode("utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def worker_status() -> dict[str, object]:
    if not WORKER_STATUS_PATH.exists():
        return {
            "ready": False,
            "state": "bootstrapping",
            "detail": "Worker has not started yet",
            "substep": "Waiting for worker container",
            "updated_at": None,
            "stale": True,
            "runtime": {},
            "worker": {},
            "capabilities": {},
        }

    try:
        payload = json.loads(WORKER_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "ready": False,
            "state": "bootstrapping",
            "detail": "Worker status unreadable",
            "substep": "Retrying status read",
            "updated_at": None,
            "stale": True,
            "runtime": {},
            "worker": {},
            "capabilities": {},
        }

    updated_at = payload.get("updated_at")
    stale = True
    if isinstance(updated_at, str):
        try:
            parsed_updated_at = datetime.fromisoformat(updated_at)
            comparison_now = (
                datetime.now(parsed_updated_at.tzinfo)
                if parsed_updated_at.tzinfo is not None
                else datetime.now()
            )
            age = (comparison_now - parsed_updated_at).total_seconds()
            stale = age > 30
        except (TypeError, ValueError):
            stale = True

    state = str(payload.get("state", "bootstrapping"))
    phase = str(payload.get("phase", state))
    detail = str(payload.get("detail", ""))
    substep = str(payload.get("substep", ""))

    raw_progress = payload.get("progress", 0)
    try:
        progress = int(raw_progress)
    except (TypeError, ValueError):
        progress = 0

    progress = max(0, min(100, progress))

    payload_ready = payload.get("ready")
    if isinstance(payload_ready, bool):
        ready = payload_ready and not stale
    else:
        ready = (state in {"ready", "idle", "processing"}) and not stale

    return {
        "ready": ready,
        "state": state,
        "phase": phase,
        "progress": progress,
        "detail": detail,
        "substep": substep,
        "updated_at": updated_at,
        "stale": stale,
        "runtime": payload.get("runtime", {}),
        "worker": payload.get("worker", {}),
        "capabilities": payload.get("capabilities", {}),
    }


def result_file_mime(path: Path) -> str:
    override = INLINE_MIME_OVERRIDES.get(path.suffix.lower())
    if override:
        return override
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def result_is_generated_tool_html(rel_path: str) -> bool:
    normalized = normalized_job_result_path(rel_path)
    if not normalized or Path(normalized).suffix.lower() not in {".html", ".htm"}:
        return False
    parts = normalized.split("/")
    return (
        len(parts) >= 6
        and parts[0:2] == ["data", "results"]
        and parts[3].lower() in {"antismash", "funbgcex"}
        and bool(parts[2])
        and bool(parts[4])
    )


def content_disposition(disposition: str, filename: str) -> str:
    safe_disposition = disposition if disposition in {"inline", "attachment"} else "attachment"
    clean_name = re.split(r"[\x00-\x1f\x7f]", str(filename or ""), maxsplit=1)[0]
    basename = Path(clean_name.replace("\\", "/")).name or "download"
    ascii_name = basename.encode("ascii", errors="ignore").decode("ascii") or "download"
    ascii_name = ascii_name.replace("\\", "_").replace('"', '\\"')
    encoded_name = urllib.parse.quote(basename, safe="")
    return f'{safe_disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'


def request_tokens(handler: BaseHTTPRequestHandler) -> list[str]:
    tokens: list[str] = []
    auth_header = handler.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            tokens.append(token)

    for header in [
        "X-ClusterWeave-Token",
        "X-ClusterWeave-Admin-Token",
        "X-ClusterWeave-Submit-Token",
        "X-ClusterWeave-Read-Token",
    ]:
        token = handler.headers.get(header, "").strip()
        if token:
            tokens.append(token)

    return tokens


def secure_token_match(candidate: str, expected: str) -> bool:
    return bool(candidate and expected) and hmac.compare_digest(candidate, expected)


def normalized_token_hash(value: str) -> str:
    digest = (value or "").strip().lower()
    if len(digest) != hashlib.sha256().digest_size * 2:
        return ""
    if any(ch not in "0123456789abcdef" for ch in digest):
        return ""
    return digest


def secure_token_hash_match(candidate: str, expected_hash: str) -> bool:
    digest = normalized_token_hash(expected_hash)
    if not (candidate and digest):
        return False
    candidate_hash = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate_hash, digest)


def token_credential_configured(plain: str, sha256_hash: str) -> bool:
    return bool(plain or sha256_hash)


def request_has_token(handler: BaseHTTPRequestHandler, expected: str, expected_sha256: str = "") -> bool:
    return any(
        secure_token_match(token, expected) or secure_token_hash_match(token, expected_sha256)
        for token in request_tokens(handler)
    )


def request_has_any_token(handler: BaseHTTPRequestHandler) -> bool:
    return bool(request_tokens(handler))


def request_is_admin(handler: BaseHTTPRequestHandler) -> bool:
    if not PUBLIC_MODE:
        return True
    return request_has_token(handler, ADMIN_TOKEN, ADMIN_TOKEN_SHA256)


def request_can_submit(handler: BaseHTTPRequestHandler) -> bool:
    if not PUBLIC_MODE:
        return True
    if request_is_admin(handler):
        return True
    if not token_credential_configured(SUBMIT_TOKEN, SUBMIT_TOKEN_SHA256):
        return True
    return request_has_token(handler, SUBMIT_TOKEN, SUBMIT_TOKEN_SHA256)


def job_token_hash(token: str) -> str:
    secret = JOB_TOKEN_SECRET.encode("utf-8") if JOB_TOKEN_SECRET else b"clusterweave-job-read-token-v1"
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_job_read_token() -> str:
    return secrets.token_urlsafe(32)


def attach_job_read_token(job: dict[str, object]) -> str:
    token = generate_job_read_token()
    job["read_token_hash"] = job_token_hash(token)
    job["read_token_created_at"] = now_iso()
    return token


def request_can_read_job(handler: BaseHTTPRequestHandler, job: dict[str, object]) -> bool:
    if not PUBLIC_MODE:
        return True
    if request_is_admin(handler):
        return True
    expected_hashes = []
    expected = job.get("read_token_hash")
    if isinstance(expected, str) and expected:
        expected_hashes.append(expected)
    extra_hashes = job.get("read_token_hashes")
    if isinstance(extra_hashes, list):
        expected_hashes.extend([item for item in extra_hashes if isinstance(item, str) and item])
    if not expected_hashes:
        return False
    return any(
        hmac.compare_digest(job_token_hash(token), expected)
        for token in request_tokens(handler)
        for expected in expected_hashes
    )


def result_file_exists(base_dir: Path, rel_path: str) -> bool:
    normalized = normalized_job_result_path(rel_path)
    if not normalized:
        return False
    base = base_dir.resolve()
    candidate = base / normalized
    try:
        candidate.relative_to(base)
    except ValueError:
        return False

    current = base
    for part in Path(normalized).parts:
        current = current / part
        if current.is_symlink():
            return False
    full = candidate.resolve()
    try:
        full.relative_to(base)
    except ValueError:
        return False
    return full.is_file()


_PUBLIC_BIGSCAPE_EXPECTED_COLUMNS = {
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
        "output_dir", "reference_dir", "query_path", "mibig_version", "record_type",
        "classify", "weights", "alignment_mode", "extend_strategy",
        "include_singletons", "cutoffs", "min_bgc_length", "include_categories",
        "exclude_categories", "include_classes", "exclude_classes", "config_hash",
    ),
    "scanned_cds": ("cds_id",),
}
_PUBLIC_BIGSCAPE_EXPECTED_INDEXES = {
    ("distance_record_id_index", "distance"),
    ("record_id_index", "bgc_record"),
}
_PUBLIC_BIGSCAPE_HASH_RE = re.compile(r"cwpub_[0-9a-f]{64}")
_PUBLIC_BIGSCAPE_PATH_ROLES = (
    ("dataset", re.compile(r"inputs/dataset/dataset_\d{8}\.gbk")),
    (
        "reference",
        re.compile(
            r"inputs/reference/"
            r"(?:mibig_antismash_[A-Za-z0-9._-]+_gbk/)*"
            r"reference_\d{8}\.gbk"
        ),
    ),
    ("query", re.compile(r"inputs/query/query_\d{8}\.gbk")),
)
_PUBLIC_BIGSCAPE_PRIVATE_MARKERS = (
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
_PUBLIC_BIGSCAPE_RAW_DATABASE_NAMES = ("big_scape.db", "data_sqlite.db")
_PUBLIC_BIGSCAPE_MAX_BYTES = 2 * 1024 * 1024 * 1024
_PUBLIC_BIGSCAPE_VALIDATION_CACHE_MAX = 32
_PUBLIC_BIGSCAPE_VALIDATION_CACHE: OrderedDict[
    tuple[str, int, int, int, int, int],
    bool,
] = OrderedDict()
_PUBLIC_BIGSCAPE_VALIDATION_CACHE_LOCK = threading.RLock()
_PUBLIC_BIGSCAPE_VIEWER_VALIDATION_CACHE: OrderedDict[
    tuple[object, ...],
    bool,
] = OrderedDict()
_PUBLIC_BIGSCAPE_VIEWER_VALIDATION_CACHE_LOCK = threading.RLock()
_PUBLIC_BIGSCAPE_VIEWER_EXPECTED_JS_SHA256 = (
    "8ade9f32fd51260d47817d49ea33e6132f6f0876eaf2d0805d42918c35bec9ee"
)
_PUBLIC_BIGSCAPE_VIEWER_MAX_ASSET_BYTES = 16 * 1024 * 1024
_PUBLIC_BIGSCAPE_VIEWER_MARKER_COLUMNS = (
    "export_version",
    "query_contract",
    "path_policy",
    "source_export_version",
    "source_user_version",
    "source_bytes",
    "source_sha256",
    "index_bytes",
    "index_sha256",
    "bigscape_js_bytes",
    "bigscape_js_sha256",
    "reachable_records",
    "gbk_rows",
    "distance_rows",
)
_PUBLIC_BIGSCAPE_VIEWER_GBK_COLUMNS = (
    *_PUBLIC_BIGSCAPE_EXPECTED_COLUMNS["gbk"],
    "clusterweave_nt_length",
)
_PUBLIC_BIGSCAPE_VIEWER_EXPECTED_COLUMNS = {
    **_PUBLIC_BIGSCAPE_EXPECTED_COLUMNS,
    "gbk": _PUBLIC_BIGSCAPE_VIEWER_GBK_COLUMNS,
}
_PUBLIC_BIGSCAPE_VIEWER_REACHABLE_RECORDS_SQL = (
    "SELECT center_id AS record_id FROM source.family WHERE center_id IS NOT NULL "
    "UNION SELECT record_id FROM source.bgc_record_family WHERE record_id IS NOT NULL "
    "UNION SELECT record_id FROM source.connected_component WHERE record_id IS NOT NULL"
)
_PUBLIC_BIGSCAPE_VIEWER_EXPECTED_TYPES = {
    "run": (
        "INTEGER", *("TEXT",) * 17, "INTEGER", *("TEXT",) * 5,
    ),
    "edge_params": ("INTEGER", "TEXT", "TEXT", "TEXT"),
    "gbk": (
        "INTEGER", "TEXT", "TEXT", "BLOB", "TEXT", "TEXT", "TEXT",
        "INTEGER",
    ),
    "bgc_record": (
        "INTEGER", "INTEGER", "INTEGER", "INTEGER", "BOOLEAN", "TEXT",
        "INTEGER", "INTEGER", "TEXT", "TEXT", "BOOLEAN",
    ),
    "cds": (
        "INTEGER", "INTEGER", "INTEGER", "INTEGER", "INTEGER", "INTEGER",
        "TEXT", "TEXT",
    ),
    "hsp": ("INTEGER", "INTEGER", "TEXT", "INTEGER", "INTEGER", "REAL"),
    "hsp_alignment": ("INTEGER", "TEXT"),
    "family": ("INTEGER", "INTEGER", "TEXT", "REAL", "TEXT", "INTEGER"),
    "bgc_record_family": ("INTEGER", "INTEGER"),
    "connected_component": ("INTEGER", "INTEGER", "REAL", "TEXT", "INTEGER"),
    "distance": (
        "INTEGER", "INTEGER", "REAL", "REAL", "REAL", "REAL", "INTEGER",
        *("INTEGER",) * 8, "BOOLEAN", *("INTEGER",) * 4,
    ),
    "scanned_cds": ("INTEGER",),
}
_PUBLIC_BIGSCAPE_VIEWER_INDEX_EXEC_CALLS = 14
_PUBLIC_BIGSCAPE_VIEWER_SCRIPT_EXEC_CALLS = 1
_PUBLIC_BIGSCAPE_VIEWER_INDEX_QUERY_FRAGMENTS = (
    "CREATE TABLE rec_ids (rec_id int)",
    "CREATE TABLE gbk_ids (gbk_id int)",
    "CREATE TABLE cds_ids (cds_id int)",
    "SELECT * FROM run",
    "SELECT cc.id, family.id, family.center_id, bgc_record_family.record_id, gbk.path FROM family",
    "SELECT DISTINCT cc1.id, cc2.id FROM connected_component AS cc1",
    "SELECT DISTINCT connected_component.id FROM connected_component",
    "SELECT bgc_record.id, gbk.path, bgc_record.record_type,",
    "SELECT hsp.cds_id, hsp.accession, hsp.env_start, hsp.env_stop, hsp.bit_score FROM hsp",
    "SELECT cds.gbk_id, cds.orf_num, cds.strand, cds.nt_start, cds.nt_stop, cds.id FROM cds",
    "SELECT gbk.id, gbk.description, length(gbk.nt_seq), gbk.hash, gbk.path,",
    "SELECT distance.record_a_id, distance.record_b_id, distance.distance FROM distance",
    "SELECT distance.record_a_id, distance.record_b_id, distance.lcs_domain_a_start,",
    "SELECT family.newick FROM family WHERE family.id ==",
    "SELECT gbk.organism, COUNT(gbk.organism) FROM gbk",
    "SELECT bgc_record.product, COUNT(bgc_record.product) as c",
    "SELECT gbk.organism, gbk.path, family.id, family.bin_label FROM gbk",
)
_PUBLIC_BIGSCAPE_VIEWER_SCRIPT_QUERY_FRAGMENT = (
    "SELECT distance.record_a_id, distance.record_b_id, distance.distance FROM distance"
)
_PUBLIC_MANIFEST_VALIDATION_CACHE_MAX = 32
_PUBLIC_MANIFEST_VALIDATION_CACHE: OrderedDict[
    tuple[object, ...],
    tuple[tuple[str, tuple[int, int, int, int, int]], ...],
] = OrderedDict()
_PUBLIC_MANIFEST_VALIDATION_CACHE_LOCK = threading.RLock()
_PUBLIC_MANIFEST_MAX_BYTES = 32 * 1024 * 1024
_PUBLIC_MANIFEST_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PUBLIC_FILE_SHA256_CACHE_MAX = 128
_PUBLIC_FILE_SHA256_CACHE: OrderedDict[tuple[object, ...], str] = OrderedDict()
_PUBLIC_FILE_SHA256_CACHE_LOCK = threading.RLock()


def _public_bigscape_has_sqlite_sidecar(path: Path) -> bool:
    candidates = [path]
    artifact_root = path.parent.parent
    source_root = (
        artifact_root.parent
        if artifact_root.name.lower() == "output_files"
        else artifact_root
    )
    source_roots = {source_root, source_root / "output_files"}
    for root in source_roots:
        candidates.extend(root / name for name in _PUBLIC_BIGSCAPE_RAW_DATABASE_NAMES)
    return any(
        Path(str(candidate) + suffix).exists()
        for candidate in candidates
        for suffix in ("-wal", "-shm", "-journal")
    )


def _public_bigscape_contains_private_marker(path: Path) -> bool:
    overlap = max(len(marker) for marker in _PUBLIC_BIGSCAPE_PRIVATE_MARKERS) - 1
    tail = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            block = tail + chunk
            if any(marker in block for marker in _PUBLIC_BIGSCAPE_PRIVATE_MARKERS):
                return True
            tail = block[-overlap:] if overlap > 0 else b""
    return False


def _public_bigscape_database_export_valid_uncached(path: Path) -> bool:
    """Independently attest the complete immutable public-export contract."""

    path = Path(path)
    if not path.is_file() or path.is_symlink():
        return False
    try:
        if path.stat().st_size > _PUBLIC_BIGSCAPE_MAX_BYTES:
            return False
        if _public_bigscape_has_sqlite_sidecar(path):
            return False
        with path.open("rb") as handle:
            if handle.read(16) != b"SQLite format 3\x00":
                return False
        if _public_bigscape_contains_private_marker(path):
            return False

        connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro&immutable=1",
            uri=True,
        )
        try:
            connection.execute("PRAGMA query_only=ON")
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                return False
            if list(connection.execute("PRAGMA foreign_key_check")):
                return False
            if int(connection.execute("PRAGMA freelist_count").fetchone()[0]) != 0:
                return False

            tables = {
                str(row[0]).lower()
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            expected_tables = set(_PUBLIC_BIGSCAPE_EXPECTED_COLUMNS)
            expected_tables.add(PUBLIC_BIGSCAPE_EXPORT_TABLE)
            if tables != expected_tables:
                return False
            for table, expected in _PUBLIC_BIGSCAPE_EXPECTED_COLUMNS.items():
                observed = tuple(
                    str(row[1]).lower()
                    for row in connection.execute(f'PRAGMA table_xinfo("{table}")')
                )
                if observed != expected:
                    return False
            indexes = {
                (str(name).lower(), str(table).lower())
                for name, table in connection.execute(
                    "SELECT name, tbl_name FROM sqlite_master "
                    "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if indexes != _PUBLIC_BIGSCAPE_EXPECTED_INDEXES:
                return False
            other_objects = int(
                connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type NOT IN ('table', 'index') "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchone()[0]
            )
            if other_objects:
                return False

            marker_info = [
                (str(row[1]).lower(), str(row[2]).upper(), int(row[3]), int(row[5]))
                for row in connection.execute(
                    f'PRAGMA table_info("{PUBLIC_BIGSCAPE_EXPORT_TABLE}")'
                )
            ]
            expected_marker_info = [
                ("export_version", "INTEGER", 1, 0),
                ("source_name", "TEXT", 1, 0),
                ("path_policy", "TEXT", 1, 0),
                ("dataset_paths", "INTEGER", 1, 0),
                ("reference_paths", "INTEGER", 1, 0),
                ("query_paths", "INTEGER", 1, 0),
            ]
            if marker_info != expected_marker_info:
                return False
            rows = connection.execute(
                f'SELECT export_version, source_name, path_policy, '
                f'dataset_paths, reference_paths, query_paths '
                f'FROM "{PUBLIC_BIGSCAPE_EXPORT_TABLE}"'
            ).fetchall()
            if len(rows) != 1:
                return False
            version, source_name, policy, dataset, reference, query = rows[0]
            if int(version) != PUBLIC_BIGSCAPE_EXPORT_VERSION:
                return False
            if str(policy) != PUBLIC_BIGSCAPE_PATH_POLICY:
                return False
            if str(source_name).lower() not in _PUBLIC_BIGSCAPE_RAW_DATABASE_NAMES:
                return False
            counts = {
                "dataset": int(dataset),
                "reference": int(reference),
                "query": int(query),
            }
            if any(count < 0 for count in counts.values()):
                return False

            public_paths = [
                str(row[0] or "")
                for row in connection.execute("SELECT path FROM gbk")
            ]
            if len(public_paths) != len(set(public_paths)):
                return False
            observed_counts = {role: 0 for role in counts}
            for value in public_paths:
                matches = [
                    role for role, pattern in _PUBLIC_BIGSCAPE_PATH_ROLES
                    if pattern.fullmatch(value)
                ]
                if len(matches) != 1:
                    return False
                observed_counts[matches[0]] += 1
            if observed_counts != counts:
                return False

            hashes = [row[0] for row in connection.execute("SELECT hash FROM gbk")]
            if any(
                not isinstance(value, str)
                or _PUBLIC_BIGSCAPE_HASH_RE.fullmatch(value) is None
                for value in hashes
            ):
                return False
            unsafe_nt = int(
                connection.execute(
                    "SELECT COUNT(*) FROM gbk "
                    "WHERE typeof(nt_seq) != 'blob' "
                    "OR length(nt_seq) <= 0 "
                    "OR nt_seq != zeroblob(length(nt_seq))"
                ).fetchone()[0]
            )
            unsafe_aa = int(
                connection.execute(
                    "SELECT COUNT(*) FROM cds "
                    "WHERE typeof(aa_seq) != 'text' OR aa_seq != ''"
                ).fetchone()[0]
            )
            unsafe_alignment = int(
                connection.execute(
                    "SELECT COUNT(*) FROM hsp_alignment "
                    "WHERE typeof(alignment) != 'text' OR alignment != ''"
                ).fetchone()[0]
            )
            if unsafe_nt or unsafe_aa or unsafe_alignment:
                return False

            allowed_run_values = {
                "input_dir": "inputs/dataset",
                "output_dir": "outputs",
                "reference_dir": "inputs/reference",
            }
            for column, allowed in allowed_run_values.items():
                for (value,) in connection.execute(f'SELECT "{column}" FROM run'):
                    if (
                        value is None
                        or str(value).strip().lower() in {"", "none", "null"}
                    ):
                        continue
                    if str(value) != allowed:
                        return False
            for (value,) in connection.execute("SELECT query_path FROM run"):
                if (
                    value is None
                    or str(value).strip().lower() in {"", "none", "null"}
                ):
                    continue
                if str(value) != "query.gbk" and re.fullmatch(
                    r"query_\d{8}\.gbk", str(value)
                ) is None:
                    return False
            for (value,) in connection.execute("SELECT config_hash FROM run"):
                if (
                    value is None
                    or str(value).strip().lower() in {"", "none", "null"}
                ):
                    continue
                if _PUBLIC_BIGSCAPE_HASH_RE.fullmatch(str(value)) is None:
                    return False
            mibig_markers: set[str] = set()
            for (value,) in connection.execute("SELECT mibig_version FROM run"):
                version = "null" if value is None else str(value)
                if (
                    not version
                    or len(version) > 180
                    or re.fullmatch(r"[A-Za-z0-9._-]+", version) is None
                ):
                    return False
                mibig_markers.add(f"mibig_antismash_{version}_gbk")
            if not mibig_markers:
                mibig_markers.add("mibig_antismash_unknown_gbk")
            for value in public_paths:
                if "/mibig_antismash_" not in value:
                    continue
                if any(f"/{marker}/" not in value for marker in mibig_markers):
                    return False
        finally:
            connection.close()
    except (OSError, TypeError, ValueError, sqlite3.Error):
        return False
    return True


def public_bigscape_database_export_valid(path: Path) -> bool:
    """Attest a public export, caching only an immutable file identity."""

    path = Path(path)
    if not path.is_file() or path.is_symlink():
        return False
    if _public_bigscape_has_sqlite_sidecar(path):
        return False
    try:
        stat = path.stat()
        if stat.st_size > _PUBLIC_BIGSCAPE_MAX_BYTES:
            return False
        identity = (
            str(path.resolve()),
            int(stat.st_dev),
            int(stat.st_ino),
            int(stat.st_size),
            int(stat.st_mtime_ns),
            int(stat.st_ctime_ns),
        )
    except OSError:
        return False
    with _PUBLIC_BIGSCAPE_VALIDATION_CACHE_LOCK:
        cached = _PUBLIC_BIGSCAPE_VALIDATION_CACHE.get(identity)
        if cached is not None:
            _PUBLIC_BIGSCAPE_VALIDATION_CACHE.move_to_end(identity)
            return cached

    valid = _public_bigscape_database_export_valid_uncached(path)
    with _PUBLIC_BIGSCAPE_VALIDATION_CACHE_LOCK:
        _PUBLIC_BIGSCAPE_VALIDATION_CACHE[identity] = valid
        _PUBLIC_BIGSCAPE_VALIDATION_CACHE.move_to_end(identity)
        while (
            len(_PUBLIC_BIGSCAPE_VALIDATION_CACHE)
            > _PUBLIC_BIGSCAPE_VALIDATION_CACHE_MAX
        ):
            _PUBLIC_BIGSCAPE_VALIDATION_CACHE.popitem(last=False)
    return valid


def _public_bigscape_viewer_paths(
    path: Path,
) -> tuple[Path, Path, Path, Path, Path] | None:
    path = Path(path)
    if (
        path.name != PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME
        or path.parent.name != "public"
    ):
        return None
    asset_root = path.parent.parent
    tool_root = (
        asset_root.parent
        if asset_root.name.lower() == "output_files"
        else asset_root
    )
    if tool_root.name.lower() not in PUBLIC_BIGSCAPE_ROOTS:
        return None
    return (
        path.with_name("clusterweave_public.sqlite"),
        asset_root / "index.html",
        asset_root / "html_content" / "js" / "bigscape.js",
        path.with_name(f".{PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME}.source.json"),
        tool_root,
    )


def _bounded_stable_file_bytes(
    path: Path,
    identity: tuple[int, int, int, int, int],
    *,
    maximum: int,
) -> bytes:
    if identity[2] <= 0 or identity[2] > maximum:
        raise OSError("bounded public file is outside its size contract")
    with _open_stable_public_file(path, identity) as handle:
        payload = handle.read(maximum + 1)
        if (
            len(payload) != identity[2]
            or len(payload) > maximum
            or _stat_identity(os.fstat(handle.fileno())) != identity
        ):
            raise OSError("bounded public file changed while it was read")
    if _public_file_identity(path) != identity:
        raise OSError("bounded public file was replaced while it was read")
    return payload


def _viewer_typed_query_digest(cursor: sqlite3.Cursor) -> tuple[int, str]:
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


def _viewer_projection_specs() -> tuple[tuple[str, str, str, str], ...]:
    def columns(table: str) -> str:
        return ", ".join(f'"{column}"' for column in _PUBLIC_BIGSCAPE_EXPECTED_COLUMNS[table])

    reachable = "clusterweave_reachable_records"
    specs: list[tuple[str, str, str, str]] = []
    for table in (
        "run", "edge_params", "family", "bgc_record_family",
        "connected_component",
    ):
        selected = columns(table)
        specs.append((table, selected, "", selected))
    selected = columns("bgc_record")
    specs.append((
        "bgc_record", selected,
        f"id IN (SELECT record_id FROM {reachable})", selected,
    ))
    gbk_selected = (
        "id, path, hash, length(CAST(nt_seq AS BLOB)), "
        "organism, taxonomy, description"
    )
    specs.append((
        "gbk", gbk_selected,
        "id IN (SELECT gbk_id FROM bgc_record WHERE id IN "
        f"(SELECT record_id FROM {reachable}))",
        gbk_selected,
    ))
    selected = columns("cds")
    specs.append((
        "cds", selected,
        "gbk_id IN (SELECT gbk_id FROM bgc_record WHERE id IN "
        f"(SELECT record_id FROM {reachable}))",
        selected,
    ))
    selected = columns("hsp")
    specs.append((
        "hsp", selected,
        "cds_id IN (SELECT id FROM cds WHERE gbk_id IN "
        "(SELECT gbk_id FROM bgc_record WHERE id IN "
        f"(SELECT record_id FROM {reachable})))",
        selected,
    ))
    selected = columns("hsp_alignment")
    specs.append((
        "hsp_alignment", selected,
        "hsp_id IN (SELECT id FROM hsp WHERE cds_id IN "
        "(SELECT id FROM cds WHERE gbk_id IN "
        "(SELECT gbk_id FROM bgc_record WHERE id IN "
        f"(SELECT record_id FROM {reachable}))))",
        selected,
    ))
    selected = columns("scanned_cds")
    specs.append((
        "scanned_cds", selected,
        "cds_id IN (SELECT id FROM cds WHERE gbk_id IN "
        "(SELECT gbk_id FROM bgc_record WHERE id IN "
        f"(SELECT record_id FROM {reachable})))",
        selected,
    ))
    selected = columns("distance")
    specs.append((
        "distance", selected,
        f"record_a_id IN (SELECT record_id FROM {reachable}) AND "
        f"record_b_id IN (SELECT record_id FROM {reachable})",
        "record_a_id, record_b_id, edge_param_id",
    ))
    return tuple(specs)


def _public_bigscape_viewer_database_export_valid_uncached(path: Path) -> bool:
    """Independently attest the compact, exact-query browser derivative."""

    path = Path(path)
    related = _public_bigscape_viewer_paths(path)
    if related is None or not path.is_file() or path.is_symlink():
        return False
    source, index_path, script_path, sidecar_path, _tool_root = related
    try:
        viewer_identity = _public_file_identity(path)
        if viewer_identity[2] <= 0 or viewer_identity[2] > DEFAULT_MAX_VIEWER_BYTES:
            return False
        if _public_bigscape_has_sqlite_sidecar(path):
            return False
        with path.open("rb") as handle:
            if handle.read(16) != b"SQLite format 3\x00":
                return False
        if _public_bigscape_contains_private_marker(path):
            return False
        if not public_bigscape_database_export_valid(source):
            return False

        source_identity = _public_file_identity(source)
        index_identity = _public_file_identity(index_path)
        script_identity = _public_file_identity(script_path)
        sidecar_identity = _public_file_identity(sidecar_path)
        index_payload = _bounded_stable_file_bytes(
            index_path,
            index_identity,
            maximum=_PUBLIC_BIGSCAPE_VIEWER_MAX_ASSET_BYTES,
        )
        script_payload = _bounded_stable_file_bytes(
            script_path,
            script_identity,
            maximum=_PUBLIC_BIGSCAPE_VIEWER_MAX_ASSET_BYTES,
        )
        sidecar_payload = _bounded_stable_file_bytes(
            sidecar_path,
            sidecar_identity,
            maximum=64 * 1024,
        )
        index_text = index_payload.decode("utf-8", errors="strict")
        script_text = script_payload.decode("utf-8", errors="strict")
        script_digest = hashlib.sha256(script_payload).hexdigest()
        if (
            script_digest != _PUBLIC_BIGSCAPE_VIEWER_EXPECTED_JS_SHA256
            or index_text.count("window.db.exec")
            != _PUBLIC_BIGSCAPE_VIEWER_INDEX_EXEC_CALLS
            or script_text.count("window.db.exec")
            != _PUBLIC_BIGSCAPE_VIEWER_SCRIPT_EXEC_CALLS
            or any(
                fragment not in index_text
                for fragment in _PUBLIC_BIGSCAPE_VIEWER_INDEX_QUERY_FRAGMENTS
            )
            or _PUBLIC_BIGSCAPE_VIEWER_SCRIPT_QUERY_FRAGMENT not in script_text
        ):
            return False

        source_digest = _stable_public_sha256(source, source_identity)
        fingerprint = {
            "viewer_export_version": PUBLIC_BIGSCAPE_VIEWER_EXPORT_VERSION,
            "query_contract": PUBLIC_BIGSCAPE_VIEWER_QUERY_CONTRACT,
            "path_policy": PUBLIC_BIGSCAPE_VIEWER_PATH_POLICY,
            "source_name": "clusterweave_public.sqlite",
            "source_export_version": PUBLIC_BIGSCAPE_EXPORT_VERSION,
            "source_user_version": None,
            "source_bytes": source_identity[2],
            "source_sha256": source_digest,
            "index_name": "index.html",
            "index_bytes": index_identity[2],
            "index_sha256": hashlib.sha256(index_payload).hexdigest(),
            "bigscape_js_name": "html_content/js/bigscape.js",
            "bigscape_js_bytes": script_identity[2],
            "bigscape_js_sha256": script_digest,
        }

        viewer = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro&immutable=1",
            uri=True,
        )
        source_connection = sqlite3.connect(
            f"{source.resolve().as_uri()}?mode=ro&immutable=1",
            uri=True,
        )
        try:
            viewer.execute("PRAGMA query_only=ON")
            integrity = viewer.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                return False
            if list(viewer.execute("PRAGMA foreign_key_check")):
                return False
            if int(viewer.execute("PRAGMA freelist_count").fetchone()[0]) != 0:
                return False
            tables = {
                str(row[0]).lower()
                for row in viewer.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            }
            if tables != (
                set(_PUBLIC_BIGSCAPE_VIEWER_EXPECTED_COLUMNS)
                | {PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE}
            ):
                return False
            for table, expected_names in _PUBLIC_BIGSCAPE_VIEWER_EXPECTED_COLUMNS.items():
                info = list(viewer.execute(f'PRAGMA table_xinfo("{table}")'))
                names = tuple(str(row[1]).lower() for row in info)
                types = tuple(str(row[2]).upper() for row in info)
                hidden = tuple(int(row[6]) for row in info)
                if (
                    names != expected_names
                    or types != _PUBLIC_BIGSCAPE_VIEWER_EXPECTED_TYPES[table]
                    or any(int(row[3]) or int(row[5]) or row[4] is not None for row in info)
                ):
                    return False
                expected_hidden = tuple(
                    2 if table == "gbk" and name == "nt_seq" else 0
                    for name in expected_names
                )
                if hidden != expected_hidden:
                    return False
                if list(viewer.execute(f'PRAGMA foreign_key_list("{table}")')):
                    return False

            marker_info = list(viewer.execute(
                f'PRAGMA table_xinfo("{PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE}")'
            ))
            marker_names = tuple(str(row[1]).lower() for row in marker_info)
            marker_types = tuple(str(row[2]).upper() for row in marker_info)
            expected_marker_types = (
                "INTEGER", "TEXT", "TEXT", "INTEGER", "INTEGER", "INTEGER",
                "TEXT", "INTEGER", "TEXT", "INTEGER", "TEXT", "INTEGER",
                "INTEGER", "INTEGER",
            )
            if (
                marker_names != _PUBLIC_BIGSCAPE_VIEWER_MARKER_COLUMNS
                or marker_types != expected_marker_types
                or any(
                    int(row[3]) != 1 or int(row[5]) != 0
                    or row[4] is not None or int(row[6]) != 0
                    for row in marker_info
                )
                or list(viewer.execute(
                    f'PRAGMA foreign_key_list("{PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE}")'
                ))
            ):
                return False

            named_indexes = {
                (str(name), str(table))
                for name, table in viewer.execute(
                    "SELECT name,tbl_name FROM sqlite_master WHERE type='index' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            }
            if named_indexes != {("record_id_index", "bgc_record")}:
                return False
            bgc_indexes = list(viewer.execute('PRAGMA index_list("bgc_record")'))
            if (
                len(bgc_indexes) != 1
                or str(bgc_indexes[0][1]) != "record_id_index"
                or int(bgc_indexes[0][2]) != 0
                or str(bgc_indexes[0][3]) != "c"
                or int(bgc_indexes[0][4]) != 0
                or [str(row[2]) for row in viewer.execute(
                    'PRAGMA index_info("record_id_index")'
                )] != ["gbk_id"]
            ):
                return False
            distance_indexes = list(viewer.execute('PRAGMA index_list("distance")'))
            if (
                len(distance_indexes) != 1
                or int(distance_indexes[0][2]) != 1
                or str(distance_indexes[0][3]) != "u"
                or int(distance_indexes[0][4]) != 0
                or [str(row[2]) for row in viewer.execute(
                    f'PRAGMA index_info("{distance_indexes[0][1]}")'
                )] != ["record_a_id", "record_b_id", "edge_param_id"]
            ):
                return False
            for table in set(_PUBLIC_BIGSCAPE_VIEWER_EXPECTED_COLUMNS) - {
                "bgc_record", "distance",
            }:
                if list(viewer.execute(f'PRAGMA index_list("{table}")')):
                    return False
            other_objects = int(viewer.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type NOT IN ('table','index') AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0])
            if other_objects:
                return False

            marker_rows = viewer.execute(
                f'SELECT {",".join(_PUBLIC_BIGSCAPE_VIEWER_MARKER_COLUMNS)} '
                f'FROM "{PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE}"'
            ).fetchall()
            if len(marker_rows) != 1:
                return False
            marker = dict(zip(_PUBLIC_BIGSCAPE_VIEWER_MARKER_COLUMNS, marker_rows[0]))
            source_user_version = int(
                source_connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if int(viewer.execute("PRAGMA user_version").fetchone()[0]) != source_user_version:
                return False
            fingerprint["source_user_version"] = source_user_version
            if json.loads(sidecar_payload.decode("utf-8", errors="strict")) != fingerprint:
                return False
            if (
                marker["export_version"] != PUBLIC_BIGSCAPE_VIEWER_EXPORT_VERSION
                or marker["query_contract"] != PUBLIC_BIGSCAPE_VIEWER_QUERY_CONTRACT
                or marker["path_policy"] != PUBLIC_BIGSCAPE_VIEWER_PATH_POLICY
                or marker["source_export_version"] != PUBLIC_BIGSCAPE_EXPORT_VERSION
                or marker["source_user_version"] != source_user_version
                or marker["source_bytes"] != source_identity[2]
                or marker["source_sha256"] != source_digest
                or marker["index_bytes"] != index_identity[2]
                or marker["index_sha256"] != fingerprint["index_sha256"]
                or marker["bigscape_js_bytes"] != script_identity[2]
                or marker["bigscape_js_sha256"] != script_digest
            ):
                return False

            gbk_sql_row = viewer.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='gbk'"
            ).fetchone()
            normalized_gbk_sql = re.sub(
                r"\s+", "", str(gbk_sql_row[0] if gbk_sql_row else "").lower()
            )
            if (
                "nt_seqblobgeneratedalwaysas(zeroblob(clusterweave_nt_length))virtual"
                not in normalized_gbk_sql
            ):
                return False

            relationship_checks = (
                "SELECT COUNT(*) FROM bgc_record LEFT JOIN gbk ON gbk.id=bgc_record.gbk_id WHERE bgc_record.gbk_id IS NOT NULL AND gbk.id IS NULL",
                "SELECT COUNT(*) FROM family LEFT JOIN bgc_record ON bgc_record.id=family.center_id WHERE family.center_id IS NOT NULL AND bgc_record.id IS NULL",
                "SELECT COUNT(*) FROM family LEFT JOIN run ON run.id=family.run_id WHERE family.run_id IS NOT NULL AND run.id IS NULL",
                "SELECT COUNT(*) FROM bgc_record_family LEFT JOIN bgc_record ON bgc_record.id=bgc_record_family.record_id WHERE bgc_record_family.record_id IS NOT NULL AND bgc_record.id IS NULL",
                "SELECT COUNT(*) FROM bgc_record_family LEFT JOIN family ON family.id=bgc_record_family.family_id WHERE bgc_record_family.family_id IS NOT NULL AND family.id IS NULL",
                "SELECT COUNT(*) FROM connected_component LEFT JOIN bgc_record ON bgc_record.id=connected_component.record_id WHERE connected_component.record_id IS NOT NULL AND bgc_record.id IS NULL",
                "SELECT COUNT(*) FROM connected_component LEFT JOIN run ON run.id=connected_component.run_id WHERE connected_component.run_id IS NOT NULL AND run.id IS NULL",
                "SELECT COUNT(*) FROM cds LEFT JOIN gbk ON gbk.id=cds.gbk_id WHERE cds.gbk_id IS NOT NULL AND gbk.id IS NULL",
                "SELECT COUNT(*) FROM hsp LEFT JOIN cds ON cds.id=hsp.cds_id WHERE hsp.cds_id IS NOT NULL AND cds.id IS NULL",
                "SELECT COUNT(*) FROM hsp_alignment LEFT JOIN hsp ON hsp.id=hsp_alignment.hsp_id WHERE hsp_alignment.hsp_id IS NOT NULL AND hsp.id IS NULL",
                "SELECT COUNT(*) FROM scanned_cds LEFT JOIN cds ON cds.id=scanned_cds.cds_id WHERE scanned_cds.cds_id IS NOT NULL AND cds.id IS NULL",
                "SELECT COUNT(*) FROM distance LEFT JOIN bgc_record ON bgc_record.id=distance.record_a_id WHERE distance.record_a_id IS NOT NULL AND bgc_record.id IS NULL",
                "SELECT COUNT(*) FROM distance LEFT JOIN bgc_record ON bgc_record.id=distance.record_b_id WHERE distance.record_b_id IS NOT NULL AND bgc_record.id IS NULL",
                "SELECT COUNT(*) FROM distance LEFT JOIN edge_params ON edge_params.id=distance.edge_param_id WHERE distance.edge_param_id IS NOT NULL AND edge_params.id IS NULL",
            )
            if any(int(viewer.execute(query).fetchone()[0]) for query in relationship_checks):
                return False

            source_connection.execute(
                "CREATE TEMP TABLE clusterweave_reachable_records "
                "(record_id INTEGER PRIMARY KEY)"
            )
            source_connection.execute(
                "INSERT OR IGNORE INTO clusterweave_reachable_records(record_id) "
                "SELECT record_id FROM bgc_record_family WHERE record_id IS NOT NULL "
                "UNION SELECT record_id FROM connected_component WHERE record_id IS NOT NULL "
                "UNION SELECT center_id FROM family WHERE center_id IS NOT NULL"
            )
            missing = int(source_connection.execute(
                "SELECT COUNT(*) FROM clusterweave_reachable_records AS reachable "
                "LEFT JOIN bgc_record ON bgc_record.id=reachable.record_id "
                "WHERE bgc_record.id IS NULL"
            ).fetchone()[0])
            reachable = int(source_connection.execute(
                "SELECT COUNT(*) FROM clusterweave_reachable_records"
            ).fetchone()[0])
            if missing or marker["reachable_records"] != reachable:
                return False
            projection_counts: dict[str, int] = {}
            for table, selected, source_where, order_by in _viewer_projection_specs():
                source_sql = f'SELECT {selected} FROM "{table}"'
                if source_where:
                    source_sql += f" WHERE {source_where}"
                source_sql += f" ORDER BY {order_by}"
                viewer_sql = f'SELECT {selected} FROM "{table}" ORDER BY {order_by}'
                source_projection = _viewer_typed_query_digest(
                    source_connection.execute(source_sql)
                )
                viewer_projection = _viewer_typed_query_digest(
                    viewer.execute(viewer_sql)
                )
                if source_projection != viewer_projection:
                    return False
                projection_counts[table] = viewer_projection[0]
            if (
                marker["gbk_rows"] != projection_counts["gbk"]
                or marker["distance_rows"] != projection_counts["distance"]
                or projection_counts["bgc_record"] != reachable
            ):
                return False

            unsafe_nt = int(viewer.execute(
                "SELECT COUNT(*) FROM gbk WHERE "
                "typeof(clusterweave_nt_length) != 'integer' "
                "OR clusterweave_nt_length <= 0 "
                "OR typeof(nt_seq) != 'blob' "
                "OR length(nt_seq) != clusterweave_nt_length "
                "OR nt_seq != zeroblob(clusterweave_nt_length)"
            ).fetchone()[0])
            unsafe_aa = int(viewer.execute(
                "SELECT COUNT(*) FROM cds WHERE typeof(aa_seq) != 'text' OR aa_seq != ''"
            ).fetchone()[0])
            unsafe_alignment = int(viewer.execute(
                "SELECT COUNT(*) FROM hsp_alignment "
                "WHERE typeof(alignment) != 'text' OR alignment != ''"
            ).fetchone()[0])
            if unsafe_nt or unsafe_aa or unsafe_alignment:
                return False
        finally:
            viewer.close()
            source_connection.close()

        if (
            _public_file_identity(path) != viewer_identity
            or _public_file_identity(source) != source_identity
            or _public_file_identity(index_path) != index_identity
            or _public_file_identity(script_path) != script_identity
            or _public_file_identity(sidecar_path) != sidecar_identity
        ):
            return False
    except (
        OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError,
        sqlite3.Error,
    ):
        return False
    return True


def public_bigscape_viewer_database_export_valid(path: Path) -> bool:
    """Cache only a full immutable identity for the compact viewer profile."""

    related = _public_bigscape_viewer_paths(Path(path))
    if related is None:
        return False
    source, index_path, script_path, sidecar_path, _tool_root = related
    try:
        identities = (
            _public_file_identity(Path(path)),
            _public_file_identity(source),
            _public_file_identity(index_path),
            _public_file_identity(script_path),
            _public_file_identity(sidecar_path),
        )
        if identities[0][2] > DEFAULT_MAX_VIEWER_BYTES:
            return False
        identity: tuple[object, ...] = (
            str(Path(path).resolve()),
            *(value for item in identities for value in item),
        )
    except (OSError, ValueError):
        return False
    if _public_bigscape_has_sqlite_sidecar(Path(path)):
        return False
    with _PUBLIC_BIGSCAPE_VIEWER_VALIDATION_CACHE_LOCK:
        cached = _PUBLIC_BIGSCAPE_VIEWER_VALIDATION_CACHE.get(identity)
        if cached is not None:
            _PUBLIC_BIGSCAPE_VIEWER_VALIDATION_CACHE.move_to_end(identity)
            return cached
    valid = _public_bigscape_viewer_database_export_valid_uncached(Path(path))
    with _PUBLIC_BIGSCAPE_VIEWER_VALIDATION_CACHE_LOCK:
        _PUBLIC_BIGSCAPE_VIEWER_VALIDATION_CACHE[identity] = valid
        _PUBLIC_BIGSCAPE_VIEWER_VALIDATION_CACHE.move_to_end(identity)
        while len(_PUBLIC_BIGSCAPE_VIEWER_VALIDATION_CACHE) > 32:
            _PUBLIC_BIGSCAPE_VIEWER_VALIDATION_CACHE.popitem(last=False)
    return valid


def result_file_is_publicly_servable(base_dir: Path, rel_path: str) -> bool:
    rel_path = normalized_job_result_path(rel_path)
    if rel_path.lower() == PUBLIC_RESULTS_MANIFEST_PATH:
        return public_manifest_is_fully_valid(base_dir)
    if result_is_public_archive(rel_path):
        # Stored manifests and publication ZIPs from older runs predate the
        # redacted SQLite contract.  They are inputs to validation only and
        # are never directly downloadable.
        return False
    if not result_file_exists(base_dir, rel_path):
        return False
    if not result_is_public_bigscape_database(rel_path):
        return True
    return public_bigscape_database_export_valid((base_dir / rel_path).resolve())



def append_unique_result_path(files: list[str], seen: set[str], rel_path: str) -> None:
    if rel_path and rel_path not in seen:
        seen.add(rel_path)
        files.append(rel_path)


def _stat_identity(stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_size),
        int(stat.st_mtime_ns),
        int(stat.st_ctime_ns),
    )


def _public_file_identity(path: Path) -> tuple[int, int, int, int, int]:
    if path.is_symlink() or not path.is_file():
        raise OSError("public result is not a regular file")
    return _stat_identity(path.stat())


def _open_stable_public_file(
    path: Path,
    expected_identity: tuple[int, int, int, int, int],
):
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if _stat_identity(os.fstat(descriptor)) != expected_identity:
            raise OSError("public result changed before it was opened")
        return os.fdopen(descriptor, "rb")
    except Exception:
        os.close(descriptor)
        raise


def _stable_public_sha256(
    path: Path,
    expected_identity: tuple[int, int, int, int, int],
) -> str:
    cache_key: tuple[object, ...] = (
        str(path.resolve()),
        *expected_identity,
    )
    try:
        if _public_file_identity(path) != expected_identity:
            raise OSError("public result identity changed before hashing")
    except OSError:
        raise
    with _PUBLIC_FILE_SHA256_CACHE_LOCK:
        cached = _PUBLIC_FILE_SHA256_CACHE.get(cache_key)
        if cached is not None:
            _PUBLIC_FILE_SHA256_CACHE.move_to_end(cache_key)
            return cached
    digest = hashlib.sha256()
    with _open_stable_public_file(path, expected_identity) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        if _stat_identity(os.fstat(handle.fileno())) != expected_identity:
            raise OSError("public result changed while it was read")
    if _public_file_identity(path) != expected_identity:
        raise OSError("public result was replaced while it was read")
    value = digest.hexdigest()
    with _PUBLIC_FILE_SHA256_CACHE_LOCK:
        _PUBLIC_FILE_SHA256_CACHE[cache_key] = value
        _PUBLIC_FILE_SHA256_CACHE.move_to_end(cache_key)
        while len(_PUBLIC_FILE_SHA256_CACHE) > _PUBLIC_FILE_SHA256_CACHE_MAX:
            _PUBLIC_FILE_SHA256_CACHE.popitem(last=False)
    return value


def _stable_public_manifest_bytes(
    base_dir: Path,
) -> tuple[bytes, Path, tuple[int, int, int, int, int]] | None:
    base = base_dir.resolve()
    manifest_path = base / PUBLIC_RESULTS_MANIFEST_PATH
    if not result_file_exists(base, PUBLIC_RESULTS_MANIFEST_PATH):
        return None
    try:
        manifest = manifest_path.resolve()
        manifest.relative_to(base)
        identity = _public_file_identity(manifest)
        if identity[2] > _PUBLIC_MANIFEST_MAX_BYTES:
            return None
        with _open_stable_public_file(manifest, identity) as handle:
            raw_manifest = handle.read(_PUBLIC_MANIFEST_MAX_BYTES + 1)
            if len(raw_manifest) > _PUBLIC_MANIFEST_MAX_BYTES:
                return None
            if _stat_identity(os.fstat(handle.fileno())) != identity:
                return None
        if _public_file_identity(manifest) != identity:
            return None
    except (OSError, ValueError):
        return None
    return raw_manifest, manifest, identity


def public_manifest_result_records(
    base_dir: Path,
) -> list[tuple[str, tuple[int, int, int, int, int]]]:
    if not result_file_exists(base_dir, PUBLIC_RESULTS_MANIFEST_PATH):
        return []
    manifest = (base_dir / PUBLIC_RESULTS_MANIFEST_PATH).resolve()
    try:
        manifest_identity = _public_file_identity(manifest)
        if manifest_identity[2] > _PUBLIC_MANIFEST_MAX_BYTES:
            return []
        with _open_stable_public_file(manifest, manifest_identity) as handle:
            raw_manifest = handle.read(_PUBLIC_MANIFEST_MAX_BYTES + 1)
            if len(raw_manifest) > _PUBLIC_MANIFEST_MAX_BYTES:
                return []
            if _stat_identity(os.fstat(handle.fileno())) != manifest_identity:
                return []
        if _public_file_identity(manifest) != manifest_identity:
            return []
        text = raw_manifest.decode("utf-8", errors="strict")
    except (OSError, UnicodeError):
        return []

    lines = text.splitlines()
    if not lines or lines[0] != "path\tbytes\tsha256":
        return []

    candidates: list[
        tuple[str, int, str, tuple[int, int, int, int, int]]
    ] = []
    seen: set[str] = set()
    for line in lines[1:]:
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            continue
        raw_path, raw_size, raw_digest = fields
        rel_path = normalized_job_result_path(raw_path)
        if not rel_path or rel_path != raw_path or rel_path in seen:
            continue
        seen.add(rel_path)
        if (
            rel_path.lower() == PUBLIC_RESULTS_MANIFEST_PATH
            or result_is_public_archive(rel_path)
            or not result_path_public_shape(rel_path)
            or not result_file_is_publicly_servable(base_dir, rel_path)
        ):
            continue
        if not raw_size.isdigit() or _PUBLIC_MANIFEST_SHA256_RE.fullmatch(raw_digest) is None:
            continue
        try:
            expected_size = int(raw_size)
            full = (base_dir / rel_path).resolve()
            identity = _public_file_identity(full)
        except (OSError, ValueError):
            continue
        if expected_size != identity[2]:
            continue
        candidates.append((rel_path, expected_size, raw_digest, identity))

    cache_key: tuple[object, ...] = (
        str(manifest),
        manifest_identity,
        tuple(candidates),
    )
    with _PUBLIC_MANIFEST_VALIDATION_CACHE_LOCK:
        cached = _PUBLIC_MANIFEST_VALIDATION_CACHE.get(cache_key)
        if cached is not None:
            _PUBLIC_MANIFEST_VALIDATION_CACHE.move_to_end(cache_key)
            return list(cached)

    valid: list[tuple[str, tuple[int, int, int, int, int]]] = []
    for rel_path, _expected_size, expected_digest, identity in candidates:
        try:
            observed_digest = _stable_public_sha256(
                (base_dir / rel_path).resolve(), identity
            )
        except OSError:
            continue
        if hmac.compare_digest(observed_digest, expected_digest):
            valid.append((rel_path, identity))

    cached_result = tuple(valid)
    with _PUBLIC_MANIFEST_VALIDATION_CACHE_LOCK:
        _PUBLIC_MANIFEST_VALIDATION_CACHE[cache_key] = cached_result
        _PUBLIC_MANIFEST_VALIDATION_CACHE.move_to_end(cache_key)
        while len(_PUBLIC_MANIFEST_VALIDATION_CACHE) > _PUBLIC_MANIFEST_VALIDATION_CACHE_MAX:
            _PUBLIC_MANIFEST_VALIDATION_CACHE.popitem(last=False)
    return list(cached_result)


def public_manifest_result_paths(base_dir: Path) -> list[str]:
    return [rel_path for rel_path, _identity in public_manifest_result_records(base_dir)]


def public_manifest_is_fully_valid(base_dir: Path) -> bool:
    """Allow direct checksum downloads only for a wholly safe, bound manifest."""

    if not result_file_exists(base_dir, PUBLIC_RESULTS_MANIFEST_PATH):
        return False
    manifest = (base_dir / PUBLIC_RESULTS_MANIFEST_PATH).resolve()
    try:
        identity = _public_file_identity(manifest)
        if identity[2] > _PUBLIC_MANIFEST_MAX_BYTES:
            return False
        with _open_stable_public_file(manifest, identity) as handle:
            raw_manifest = handle.read(_PUBLIC_MANIFEST_MAX_BYTES + 1)
            if len(raw_manifest) > _PUBLIC_MANIFEST_MAX_BYTES:
                return False
            if _stat_identity(os.fstat(handle.fileno())) != identity:
                return False
        if _public_file_identity(manifest) != identity:
            return False
        lines = raw_manifest.decode("utf-8", errors="strict").splitlines()
    except (OSError, UnicodeError):
        return False
    if not lines or lines[0] != "path\tbytes\tsha256":
        return False

    declared: list[str] = []
    seen: set[str] = set()
    for line in lines[1:]:
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            return False
        raw_path, raw_size, raw_digest = fields
        rel_path = normalized_job_result_path(raw_path)
        if (
            not rel_path
            or rel_path != raw_path
            or rel_path in seen
            or rel_path.lower() == PUBLIC_RESULTS_MANIFEST_PATH
            or result_is_public_archive(rel_path)
            or not result_path_public_shape(rel_path)
            or not raw_size.isdigit()
            or _PUBLIC_MANIFEST_SHA256_RE.fullmatch(raw_digest) is None
        ):
            return False
        seen.add(rel_path)
        declared.append(rel_path)
    return public_manifest_result_paths(base_dir) == declared


def authorize_direct_result_file(
    job: dict[str, object],
    base_dir: Path,
    requested_path: str,
) -> tuple[Path, tuple[int, int, int, int, int]] | None:
    """Authorize one public result without validating every manifest target."""

    requested = str(requested_path or "")
    rel_path = normalized_job_result_path(requested)
    if (
        not rel_path
        or rel_path != requested
        or not result_path_public_shape(rel_path)
        or result_is_public_archive(rel_path)
    ):
        return None

    base = base_dir.resolve()
    manifest_entry = base / PUBLIC_RESULTS_MANIFEST_PATH
    manifest_present = manifest_entry.exists() or manifest_entry.is_symlink()

    if not manifest_present:
        if rel_path == PUBLIC_RESULTS_MANIFEST_PATH:
            return None
        stored_result_files = job.get("result_files", [])
        if not isinstance(stored_result_files, (list, tuple)):
            return None
        stored_paths = {
            normalized_job_result_path(item)
            for item in stored_result_files
        }
        if rel_path not in stored_paths:
            return None
        if not result_file_is_publicly_servable(base, rel_path):
            return None
        try:
            full = (base / rel_path).resolve()
            full.relative_to(base)
            identity = _public_file_identity(full)
        except (OSError, ValueError):
            return None
        if not result_file_is_publicly_servable(base, rel_path):
            return None
        try:
            if (
                (base / rel_path).resolve() != full
                or _public_file_identity(full) != identity
            ):
                return None
        except OSError:
            return None
        return full, identity

    if rel_path == PUBLIC_RESULTS_MANIFEST_PATH:
        if not result_file_is_publicly_servable(base, rel_path):
            return None
        stable_manifest = _stable_public_manifest_bytes(base)
        if stable_manifest is None:
            return None
        _raw_manifest, full, identity = stable_manifest
        if not result_file_is_publicly_servable(base, rel_path):
            return None
        try:
            if _public_file_identity(full) != identity:
                return None
        except OSError:
            return None
        return full, identity

    if not result_file_is_publicly_servable(base, rel_path):
        return None
    stable_manifest = _stable_public_manifest_bytes(base)
    if stable_manifest is None:
        return None
    raw_manifest, _manifest, _manifest_identity = stable_manifest
    try:
        lines = raw_manifest.decode("utf-8", errors="strict").splitlines()
    except UnicodeError:
        return None
    if not lines or lines[0] != "path\tbytes\tsha256":
        return None

    matching_row: tuple[int, str] | None = None
    for line in lines[1:]:
        if not line:
            continue
        fields = line.split("\t")
        if not fields or fields[0] != rel_path:
            continue
        if matching_row is not None or len(fields) != 3:
            return None
        raw_path, raw_size, raw_digest = fields
        if (
            normalized_job_result_path(raw_path) != raw_path
            or not result_path_public_shape(raw_path)
            or raw_path == PUBLIC_RESULTS_MANIFEST_PATH
            or result_is_public_archive(raw_path)
            or not raw_size.isdigit()
            or _PUBLIC_MANIFEST_SHA256_RE.fullmatch(raw_digest) is None
        ):
            return None
        try:
            matching_row = (int(raw_size), raw_digest)
        except ValueError:
            return None
    if matching_row is None:
        return None

    expected_size, expected_digest = matching_row
    try:
        full = (base / rel_path).resolve()
        full.relative_to(base)
        identity = _public_file_identity(full)
    except (OSError, ValueError):
        return None
    if identity[2] != expected_size:
        return None
    try:
        observed_digest = _stable_public_sha256(full, identity)
    except OSError:
        return None
    if not hmac.compare_digest(observed_digest, expected_digest):
        return None
    if not result_file_is_publicly_servable(base, rel_path):
        return None
    try:
        if (base / rel_path).resolve() != full or _public_file_identity(full) != identity:
            return None
    except OSError:
        return None
    return full, identity


def result_file_allowlist(job: dict[str, object], *, base_dir: Path | None = None) -> list[str]:
    """Return a bounded result index without hashing bundle contents inline."""

    job_id = str(job.get("id") or "")
    if (
        base_dir is not None
        and job_id
        and result_file_exists(base_dir, PUBLIC_RESULTS_MANIFEST_PATH)
    ):
        attestation = read_result_attestation(base_dir, job_id)
        if attestation is not None:
            return [
                PUBLIC_RESULTS_MANIFEST_PATH,
                *(path for path, _size, _digest in attestation.files),
            ]
        schedule_result_attestation_backfill(
            base_dir,
            job_id,
            path_validator=lambda path: result_file_is_publicly_servable(base_dir, path),
        )

    files: list[str] = []
    seen: set[str] = set()
    stored_result_files = job.get("result_files", [])
    if not isinstance(stored_result_files, (list, tuple)):
        return files
    for item in stored_result_files:
        rel_path = normalized_job_result_path(item)
        if (
            not result_path_public_shape(rel_path)
            or rel_path.lower() == PUBLIC_RESULTS_MANIFEST_PATH
            or result_is_public_archive(rel_path)
            or rel_path in seen
        ):
            continue
        if base_dir is not None:
            if not result_file_exists(base_dir, rel_path):
                continue
            if (
                result_is_public_bigscape_database(rel_path)
                and not result_file_is_publicly_servable(base_dir, rel_path)
            ):
                continue
        seen.add(rel_path)
        files.append(rel_path)
    return files


def result_index_metadata(
    job: dict[str, object], base_dir: Path | None
) -> dict[str, object]:
    if base_dir is None:
        return {"result_index_state": "stored"}
    job_id = str(job.get("id") or "")
    attestation = read_result_attestation(base_dir, job_id) if job_id else None
    if attestation is None:
        return {"result_index_state": "indexing"}
    return {
        "result_index_state": "attested",
        "result_index_generation": attestation.generation,
        "result_file_count": len(attestation.files) + 1,
    }


def _paired_bigscape_viewer_path(public_database_path: str) -> str:
    """Derive one exact web-only viewer path from an attested full export."""

    rel_path = normalized_job_result_path(public_database_path)
    if not result_is_public_bigscape_database(rel_path):
        return ""
    viewer = Path(rel_path).with_name(
        PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME
    ).as_posix()
    return viewer if result_is_public_bigscape_viewer_database(viewer) else ""


def advertised_bigscape_viewer_database_path(
    job: dict[str, object],
    base_dir: Path,
    public_files: list[str],
) -> str:
    """Use signed viewer roles; deeply validate only legacy jobs once."""

    advertised = normalized_job_result_path(job.get("bigscape_viewer_database"))
    if not result_is_public_bigscape_viewer_database(advertised):
        return ""
    paired = {
        _paired_bigscape_viewer_path(path)
        for path in public_files
        if _paired_bigscape_viewer_path(path)
    }
    if paired != {advertised}:
        return ""
    attestation = read_result_attestation(base_dir, str(job.get("id") or ""))
    if attestation is not None:
        if attestation.viewer_path:
            return advertised if attestation.viewer_path == advertised else ""
    return public_bigscape_viewer_database_path(
        job,
        base_dir,
        public_files=public_files,
    )


def public_bigscape_viewer_database_path(
    job: dict[str, object],
    base_dir: Path,
    *,
    public_files: list[str] | None = None,
) -> str:
    """Return the one independently attested viewer paired to a full export."""

    base = base_dir.resolve()
    advertised = normalized_job_result_path(
        job.get("bigscape_viewer_database")
    )
    if not result_is_public_bigscape_viewer_database(advertised):
        return ""
    listed = (
        public_files
        if public_files is not None
        else result_file_allowlist(job, base_dir=base)
    )
    candidates: list[str] = []
    for public_database in listed:
        viewer = _paired_bigscape_viewer_path(public_database)
        if not viewer or viewer != advertised or viewer in candidates:
            continue
        if not result_file_exists(base, viewer):
            continue
        full = (base / viewer).resolve()
        try:
            full.relative_to(base)
        except ValueError:
            continue
        if public_bigscape_viewer_database_export_valid(full):
            candidates.append(viewer)
    return candidates[0] if len(candidates) == 1 else ""


def authorize_bigscape_viewer_database(
    job: dict[str, object],
    base_dir: Path,
) -> tuple[Path, tuple[int, int, int, int, int]] | None:
    """Bind the dedicated viewer response to an exact, stable file identity."""

    base = base_dir.resolve()
    rel_path = public_bigscape_viewer_database_path(job, base)
    if not rel_path:
        return None
    try:
        full = (base / rel_path).resolve()
        full.relative_to(base)
        identity = _public_file_identity(full)
    except (OSError, ValueError):
        return None
    if not public_bigscape_viewer_database_export_valid(full):
        return None
    try:
        if (
            (base / rel_path).resolve() != full
            or _public_file_identity(full) != identity
        ):
            return None
    except OSError:
        return None
    return full, identity


def public_archive_entry_name(rel_path: str) -> str:
    parts = normalized_job_result_path(rel_path).split("/")
    if len(parts) >= 4 and [part.lower() for part in parts[:2]] == ["data", "results"]:
        return "/".join(parts[3:])
    return "/".join(parts)


def public_safe_archive_entries(
    job: dict[str, object],
    base_dir: Path,
) -> list[tuple[Path, str, str, tuple[int, int, int, int, int]]]:
    """Return only manifest/allowlist-approved entries for the on-demand ZIP."""

    entries: list[
        tuple[Path, str, str, tuple[int, int, int, int, int]]
    ] = []
    seen: set[str] = set()
    if result_file_exists(base_dir, PUBLIC_RESULTS_MANIFEST_PATH):
        candidates = public_manifest_result_records(base_dir)
    else:
        candidates = []
        for rel_path in result_file_allowlist(job, base_dir=base_dir):
            try:
                identity = _public_file_identity((base_dir / rel_path).resolve())
            except OSError:
                continue
            candidates.append((rel_path, identity))
    for rel_path, identity in candidates:
        if not result_file_is_publicly_servable(base_dir, rel_path):
            continue
        archive_name = public_archive_entry_name(rel_path)
        if not archive_name or archive_name in seen:
            continue
        full = (base_dir / rel_path).resolve()
        seen.add(archive_name)
        entries.append((full, archive_name, rel_path, identity))
    return entries


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def _write_public_archive_member(
    archive: zipfile.ZipFile,
    source_path: Path,
    archive_name: str,
    expected_identity: tuple[int, int, int, int, int],
) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    with _open_stable_public_file(source_path, expected_identity) as source:
        with archive.open(_zip_info(archive_name), "w", force_zip64=True) as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                target.write(chunk)
                digest.update(chunk)
                total += len(chunk)
        if _stat_identity(os.fstat(source.fileno())) != expected_identity:
            raise OSError("public result changed while its archive was generated")
    if total != expected_identity[2] or _public_file_identity(source_path) != expected_identity:
        raise OSError("public result was replaced while its archive was generated")
    return total, digest.hexdigest()


def build_public_archive(job: dict[str, object], base_dir: Path) -> Path:
    """Build an authenticated public package on disk without trusting legacy ZIPs."""

    downloads_dir = base_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".clusterweave-public-download-",
        suffix=".zip",
        dir=str(downloads_dir),
    )
    os.close(descriptor)
    archive_path = Path(temp_name)
    try:
        entries = public_safe_archive_entries(job, base_dir)
        manifest_rows = ["path\tbytes\tsha256"]
        with zipfile.ZipFile(
            archive_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=1,
            allowZip64=True,
        ) as archive:
            for full, archive_name, rel_path, identity in entries:
                size, digest = _write_public_archive_member(
                    archive, full, archive_name, identity
                )
                manifest_rows.append(f"{archive_name}\t{size}\t{digest}")
            manifest_body = ("\n".join(manifest_rows) + "\n").encode("utf-8")
            with archive.open(
                _zip_info(PUBLIC_RESULTS_MANIFEST_PATH),
                "w",
                force_zip64=True,
            ) as target:
                target.write(manifest_body)
            if not entries:
                with archive.open(
                    _zip_info("README.txt"), "w", force_zip64=True
                ) as target:
                    target.write(
                        b"No public result files are available for this ClusterWeave run yet.\n"
                    )
        with archive_path.open("rb") as handle:
            os.fsync(handle.fileno())
        return archive_path
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise


def public_error_summary(error: object) -> str:
    text = str(error or "").strip()
    lower = text.lower()
    if "ncbi datasets cli" in lower or "datasets not found" in lower:
        return "Run stopped before genome download because the NCBI Datasets CLI is not ready on this server. Retry after worker bootstrap finishes."
    if "preparing genomes from accessions" in lower:
        return "Run stopped during NCBI genome retrieval. Check that each accession is current, then retry after the server runtime is ready."
    if not text:
        return "Run failed. Check public progress events and available files, or submit a new run after fixing the input."
    return "Run failed. Check public progress events and available files, or submit a new run after fixing the input."


def redact_env_overrides(settings: object) -> object:
    if not isinstance(settings, dict):
        return settings
    redacted = dict(settings)
    if redacted.get("env_overrides"):
        redacted["env_overrides"] = "[redacted]"
    return redacted


def public_activity_label(value: object) -> str:
    label = str(value or "").strip().strip("'\"")
    label = label.replace("\\", "/").rsplit("/", 1)[-1]
    lower_label = label.lower()
    for extension in sorted(PUBLIC_GENOME_EXTENSIONS, key=len, reverse=True):
        if lower_label.endswith(extension):
            label = label[: -len(extension)]
            break
    label = PUBLIC_ACTIVITY_TOKEN_RE.sub("_", label).strip("._-")
    return label[:72] or "genome"


def normalize_public_activity_message(message: str) -> str:
    text = message.strip()
    while True:
        updated = re.sub(r"^\[\d{4}-\d{2}-\d{2}[^\]]*\]\s*", "", text)
        updated = re.sub(r"^\[(?:INFO|WARN|ERROR|FAIL|OK)\]\s*", "", updated, flags=re.IGNORECASE)
        updated = updated.strip()
        if updated == text:
            return text
        text = updated


def public_activity_parts(line: object) -> tuple[str, str]:
    text = str(line or "").strip()
    match = re.match(r"^\[(?P<time>\d{2}:\d{2}:\d{2})\]\s*(?P<message>.*)$", text)
    if not match:
        return "", normalize_public_activity_message(text)
    return match.group("time"), normalize_public_activity_message(match.group("message"))


def public_activity_stage_from_marker(message: str) -> str | None:
    if re.search(r"=== Stage: (Preparing ClusterWeave project layout|Installing NCBI CLI|Preparing genomes from accessions)", message, re.IGNORECASE):
        return "prep"
    if re.search(r"Stage 1/4:\s+running run_annotation_and_detection\.sh", message, re.IGNORECASE):
        return "annotation"
    if re.search(r"Stage 2/4:\s+running run_bigscape\.sh", message, re.IGNORECASE):
        return "bigscape"
    if re.search(r"Stage 3/4:\s+running summarize_clusterweave\.sh", message, re.IGNORECASE):
        return "summary"
    if re.search(r"Stage 4/4:\s+running run_clinker\.sh", message, re.IGNORECASE):
        return "clinker"
    if re.search(r"=== Stage: Rendering summary figures", message, re.IGNORECASE):
        return "figures"
    if re.search(r"=== Stage: Running optional NPLinker follow-up", message, re.IGNORECASE):
        return "nplinker"
    return None


def public_tool_activity_tool_name(value: object) -> str:
    tool = public_activity_label(value).lower().replace("_", "-")
    if tool in {"antismash", "anti-smash"}:
        return "antiSMASH"
    if tool == "funannotate":
        return "funannotate"
    if tool == "funbgcex":
        return "FunBGCeX"
    return public_activity_label(value)


def public_tool_activity_message(value: object) -> str:
    text = normalize_public_activity_message(str(value or ""))
    text = text.replace("\\", "/")
    credential_patterns = [
        r"\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:",
        r"\b(?:authorization\s*[:=]\s*)?(?:basic|bearer)\s+\S+",
        r"(?:[?&]|\b)(?:access[_-]?token|api[_-]?key|auth[_-]?token|token|secret|password|passwd|credential|read[_-]?token|sig|signature|policy|key-pair-id|googleaccessid|x-amz-credential|x-amz-security-token|x-amz-signature|x-goog-credential|x-goog-signature)\s*=\s*[^\s&]+",
        r"\b[A-Za-z][A-Za-z0-9_-]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|CREDENTIAL)[A-Za-z0-9_-]*\s*[:=]\s*\S+",
        r"\b(?:token|secret|password|passwd|api[_-]?key|private[_-]?key|credential)\s*[:=]\s*\S+",
        r"\bX-[A-Za-z0-9-]*(?:Token|Secret|Api-Key)\s*:\s*\S+",
        r"\bfile://",
        r"(?:^|[\s=:(])[A-Za-z]:/(?:[^\s]+)",
        r"(?:^|[\s=:(])/(?:[^/\s]+/)+[^\s)]*",
    ]
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in credential_patterns):
        return "Running"
    text = re.sub(r"(?:^|\s)/(?:[^\s]+)", " ", text)
    text = re.sub(r"(?:^|\s)[A-Za-z]:/(?:[^\s]+)", " ", text)
    text = re.sub(r"[^A-Za-z0-9 ._:+/%()·|-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .:_-")
    return text[:90] or "Running"


def public_tool_activity_elapsed_text(value: object) -> str:
    try:
        seconds = max(0, int(value))
    except (TypeError, ValueError):
        seconds = 0
    if seconds < 60:
        return "under 1 min"
    if seconds < 3600:
        minutes = max(1, (seconds + 59) // 60)
        return f"{minutes} min"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if minutes:
        return f"{hours}h {minutes:02d}m"
    return f"{hours}h"


def public_tool_raw_activity_message(tool: object, raw: object) -> str:
    text = normalize_public_activity_message(str(raw or ""))
    if re.search(r"\bTOOL_(?:RAW|PROGRESS|HEARTBEAT)\b", text, re.IGNORECASE):
        return ""
    lower = text.lower()
    tool_name = public_activity_label(tool).lower()
    if tool_name in {"antismash", "anti-smash"}:
        overlap = re.search(
            r"\b(?P<record>[A-Za-z0-9_.-]+):\s*location contains overlapping exons\b",
            text,
            re.IGNORECASE,
        )
        if overlap:
            return (
                f"antiSMASH rejected record {overlap.group('record')}: "
                "overlapping exon coordinates in an annotated feature"
            )
        patterns = [
            (r"running whole-genome pfam search", "Running whole-genome PFAM search"),
            (r"detecting secondary metabolite clusters", "Detecting secondary metabolite clusters"),
            (r"running cluster pfam search", "Running cluster PFAM search"),
            (r"running clusterblast", "Running ClusterBlast"),
            (r"comparing regions to reference database", "Comparing regions to reference database"),
            (r"running tigrfam search", "Running TIGRFam search"),
            (r"running antismash\.detection\.full_hmmer", "Running full HMMER detection"),
            (r"running antismash\.detection\.hmm_detection", "Running HMM detection"),
            (r"running antismash\.detection\.cluster_hmmer", "Running cluster HMMER search"),
            (r"running antismash\.detection\.nrps_pks_domains", "Scanning NRPS/PKS domains"),
            (r"writing|output|result", "Writing antiSMASH outputs"),
        ]
    elif tool_name == "funannotate":
        patterns = [
            (r"busco|augustus|train|training", "Training gene models"),
            (r"predict|gene model|protein", "Predicting genes"),
            (r"gff|gbk|tbl|annotation|write|output|result", "Writing annotation outputs"),
            (r"sort|clean|prepare|assembly|contig|fasta", "Preparing assembly"),
        ]
    else:
        return ""
    for pattern, activity in patterns:
        if re.search(pattern, lower, re.IGNORECASE):
            return activity
    return ""


def public_tool_activity_marker(message: str) -> dict[str, str] | None:
    progress_match = re.match(
        r'^TOOL_PROGRESS\s+genome=(?P<genome>\S+)\s+tool=(?P<tool>\S+)\s+phase=(?P<phase>\S+)\s+message="(?P<message>.*)"\s*$',
        message,
        re.IGNORECASE,
    )
    if progress_match:
        payload = progress_match.groupdict()
        payload["kind"] = "progress"
        return payload
    heartbeat_match = re.match(
        r"^TOOL_HEARTBEAT\s+genome=(?P<genome>\S+)\s+tool=(?P<tool>\S+)\s+phase=(?P<phase>\S+)\s+elapsed=(?P<elapsed>\d+)s\b",
        message,
        re.IGNORECASE,
    )
    if heartbeat_match:
        payload = heartbeat_match.groupdict()
        payload["kind"] = "heartbeat"
        return payload
    raw_match = re.match(
        r"^TOOL_RAW\s+genome=(?P<genome>\S+)\s+tool=(?P<tool>\S+)\s+stream=(?P<stream>\S+)\s+(?P<raw>.*)$",
        message,
        re.IGNORECASE,
    )
    if raw_match:
        payload = raw_match.groupdict()
        activity = public_tool_raw_activity_message(payload.get("tool"), payload.get("raw"))
        if not activity:
            return None
        payload["kind"] = (
            "raw_error"
            if re.search(r"\brejected record\b|\bexceeded the available\b", activity, re.IGNORECASE)
            else "raw_progress"
        )
        payload["message"] = activity
        return payload
    return None


PUBLIC_TOOL_RAW_LINE_RE = re.compile(
    r"^\s*(?:\[\d{2}:\d{2}:\d{2}\]\s*)?(?:(?:\[\d{4}-\d{2}-\d{2}[^\]]*\]|\[(?:INFO|WARN|ERROR|FAIL|OK)\])\s*)*TOOL_RAW(?:\s|$)",
    re.IGNORECASE,
)
PUBLIC_TOOL_RAW_ACTIVITY_HINTS = (
    "pfam", "secondary", "cluster", "reference", "tigrfam", "hmmer", "hmm",
    "nrps", "pks", "writ", "output", "result", "busco", "augustus", "train",
    "predict", "gene", "protein", "gff", "gbk", "tbl", "annotation", "sort",
    "clean", "prepare", "assembly", "contig", "fasta", "overlapping exon",
)


def public_activity_projection_lines(
    job_id: str, minimum_total: int = 0
) -> list[str]:
    """Return a cached lossless projection for public activity parsing.

    Per-tool private files preserve every sanitized/truncated stream line. New
    central logs bound TOOL_RAW records per stream invocation, while legacy
    central logs may still be large. Public parsers ignore unrecognized
    TOOL_RAW records, so those records can be omitted from this projection
    without changing public events or per-genome state. Recognized legacy raw
    progress remains for backward compatibility. The LRU bounds cached jobs;
    retained structured history is intentionally uncapped so rerun resets and
    completed/warning genome states remain semantically lossless.
    """

    with _PUBLIC_LOG_PROJECTION_LOCK:
        cached = _PUBLIC_LOG_PROJECTIONS.get(job_id)
        cursor = int(cached.get("cursor", 0)) if cached else 0
        snapshot = read_log_slice(job_id, cursor, minimum_total)
        if (
            cached is None
            or cached.get("generation") != snapshot.generation
            or snapshot.total < cursor
        ):
            if cursor:
                snapshot = read_log_slice(job_id, 0, minimum_total)
            cached = {
                "generation": snapshot.generation,
                "cursor": 0,
                "lines": [],
            }

        projected = cached["lines"]
        assert isinstance(projected, list)
        for line in snapshot.lines:
            raw_candidate = PUBLIC_TOOL_RAW_LINE_RE.match(line) is not None
            if raw_candidate:
                lower_line = line.lower()
                if not any(hint in lower_line for hint in PUBLIC_TOOL_RAW_ACTIVITY_HINTS):
                    continue
            _, message = public_activity_parts(line)
            if not message:
                continue
            if raw_candidate and re.match(r"^TOOL_RAW(?:\s|$)", message, re.IGNORECASE):
                if public_tool_activity_marker(message) is None:
                    continue
            projected.append(line)

        cached["cursor"] = snapshot.total
        cached["generation"] = snapshot.generation
        _PUBLIC_LOG_PROJECTIONS[job_id] = cached
        _PUBLIC_LOG_PROJECTIONS.move_to_end(job_id)
        while len(_PUBLIC_LOG_PROJECTIONS) > PUBLIC_LOG_PROJECTION_CACHE_JOBS:
            _PUBLIC_LOG_PROJECTIONS.popitem(last=False)
        # Do not expose the mutable list held by the projection cache.
        return list(projected)


def add_public_activity_event(
    events: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    stage: str,
    title: str,
    meta: str = "",
    observed_at: str = "",
    *,
    refresh: bool = False,
) -> None:
    safe_title = str(title or "").strip()
    safe_meta = str(meta or "").strip()
    if not safe_title:
        return
    key = (stage, safe_title, safe_meta)
    if key in seen:
        if not refresh:
            return
        events[:] = [
            event for event in events
            if (event.get("stage"), event.get("title"), event.get("meta", "")) != key
        ]
    else:
        seen.add(key)
    event = {"stage": stage, "title": safe_title}
    if safe_meta:
        event["meta"] = safe_meta
    if observed_at:
        event["time"] = observed_at
    events.append(event)


def public_activity_active_meta_prefix(meta: object) -> str:
    text = str(meta or "").strip()
    text = re.sub(
        r"\s*/\s*(?:under 1 min|\d+ min|\d+h(?: \d{2}m)?) active$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip(" /")


def prune_public_activity_heartbeat(
    events: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    stage: str,
    title: str,
    meta_prefix: str,
) -> None:
    if not meta_prefix:
        return
    events[:] = [
        event for event in events
        if not (
            event.get("stage") == stage
            and event.get("title") == title
            and public_activity_active_meta_prefix(event.get("meta", "")) == meta_prefix
        )
    ]
    seen.difference_update(
        key for key in set(seen)
        if key[0] == stage
        and key[1] == title
        and public_activity_active_meta_prefix(key[2]) == meta_prefix
    )


def public_genome_progress(
    job: dict[str, object], lines: list[str]
) -> list[dict[str, object]]:
    """Return one sanitized milestone state for every accepted routed genome."""

    routes = job.get("taxon_routes")
    if not isinstance(routes, list):
        settings = job.get("settings")
        routes = settings.get("taxon_routes") if isinstance(settings, dict) else []
    route_rows = [row for row in routes if isinstance(row, dict)] if isinstance(routes, list) else []
    states: dict[str, dict[str, object]] = {}
    accession_to_genome: dict[str, str] = {}

    def annotation_method(value: object) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "existing_cds": "existing_cds",
            "funannotate": "funannotate",
            "braker": "braker3",
            "braker3": "braker3",
            "prodigal": "prodigal",
        }
        return aliases.get(normalized, "")

    def display_label(
        genome_id: str,
        taxon_group: str,
        taxon_source: object = "",
        organism_name: object = "",
    ) -> str:
        source = str(taxon_source or "").strip().lower()
        if taxon_group == "bacteria" and source in {"ncbi", "ncbi_taxonomy"}:
            organism = str(organism_name or "").strip()
            if organism:
                return public_activity_label(organism).replace("_", " ")
            if genome_id.lower().startswith("bacteria_"):
                genome_id = genome_id[len("bacteria_"):]
        return genome_id.replace("_", " ")

    def ensure_state(
        raw_genome: object,
        taxon: object = "",
        taxon_source: object = "",
        organism_name: object = "",
    ) -> dict[str, object]:
        genome_id = public_activity_label(raw_genome)
        state = states.get(genome_id)
        normalized_taxon = str(taxon or "").strip().lower()
        if normalized_taxon not in {"fungi", "bacteria"}:
            normalized_taxon = ""
        if state is None:
            taxon_group = normalized_taxon
            state = {
                "genome_id": genome_id,
                "display_label": display_label(
                    genome_id, taxon_group, taxon_source, organism_name
                ),
                "taxon_group": taxon_group,
                "stage": "download",
                "tool": "NCBI" if taxon_group else "workflow",
                "percent": 0,
                "status": "queued",
                "message": "Waiting to start",
                "annotation_method": "prodigal" if taxon_group == "bacteria" else "",
                "updated_at": "",
                "_warning": False,
                "_warning_tool": "",
                "_warning_message": "",
                "_stage_states": {},
            }
            states[genome_id] = state
        else:
            if normalized_taxon and not state.get("taxon_group"):
                state["taxon_group"] = normalized_taxon
                if normalized_taxon == "bacteria":
                    state["annotation_method"] = "prodigal"
            if str(taxon_source or "").strip():
                state["display_label"] = display_label(
                    str(state.get("genome_id") or genome_id),
                    str(state.get("taxon_group") or normalized_taxon),
                    taxon_source,
                    organism_name,
                )
        return state

    for route in route_rows:
        raw_genome = route.get("genome_id") or route.get("input_key") or "genome"
        state = ensure_state(
            raw_genome,
            route.get("taxon_group"),
            route.get("taxon_source"),
            route.get("organism_name"),
        )
        route_method = annotation_method(route.get("prediction_method"))
        taxon_source = str(route.get("taxon_source") or "").strip().lower()
        if state.get("taxon_group") == "bacteria":
            state["annotation_method"] = "prodigal"
        elif route_method == "existing_cds":
            state["annotation_method"] = "existing_cds"
        elif route_method in {"funannotate", "braker3"} and taxon_source not in {
            "ncbi",
            "ncbi_taxonomy",
        }:
            # Local FASTA/GenBank validation already knows whether prediction
            # is required. NCBI fungal routes remain undecided until the
            # downloaded GenBank is inspected by the worker.
            state["annotation_method"] = route_method
        accession = str(route.get("source_accession") or "").strip().upper()
        if NCBI_ASSEMBLY_ACCESSION_RE.fullmatch(accession):
            accession_to_genome[accession] = str(state["genome_id"])

    def update_state(
        state: dict[str, object], *, stage: str | None = None,
        tool: str | None = None, percent: int | None = None,
        status: str | None = None, message: object = None,
        observed_at: str = "", warning: bool = False,
    ) -> None:
        if stage:
            state["stage"] = public_activity_label(stage).lower()
        if tool:
            state["tool"] = public_tool_activity_tool_name(tool)
        if percent is not None:
            state["percent"] = max(int(state.get("percent", 0) or 0), min(100, max(0, percent)))
        if warning:
            state["_warning"] = True
            state["_warning_tool"] = str(state.get("tool") or "workflow")
        if status:
            state["status"] = (
                "complete_with_warning" if state.get("_warning") and status == "complete" else status
            )
        if message is not None:
            state["message"] = public_tool_activity_message(message)
        if observed_at:
            state["updated_at"] = observed_at

    def update_stage_state(
        state: dict[str, object], stage: str, status: str, message: object = None
    ) -> None:
        normalized = str(stage or "").strip().lower().replace("-", "_")
        aliases = {
            "download": "genome_acquired",
            "ncbi": "genome_acquired",
            "genome_acquired": "genome_acquired",
            "annotation": "funannotate",
            "funannotate": "funannotate",
            "antismash": "antismash",
            "anti_smash": "antismash",
            "funbgcex": "funbgcex",
            "complete": "complete",
        }
        key = aliases.get(normalized)
        if not key:
            return
        public_status = str(status or "queued").strip().lower()
        if public_status in {"warning", "error"}:
            public_status = "failed"
        stage_states = state.setdefault("_stage_states", {})
        assert isinstance(stage_states, dict)
        current = stage_states.get(key)
        if isinstance(current, dict) and current.get("status") == "failed" and public_status != "failed":
            return
        row: dict[str, str] = {"status": public_status}
        if message is not None:
            row["message"] = public_tool_activity_message(message)
        stage_states[key] = row

    def remember_tool_failure(
        state: dict[str, object], tool: str, message: object
    ) -> None:
        safe_message = public_tool_activity_message(message)
        tool_name = public_tool_activity_tool_name(tool)
        state["_warning"] = True
        state["_warning_tool"] = tool_name
        previous = str(state.get("_warning_message") or "")
        if not previous or "exited before producing" in safe_message.lower() or "rejected record" in safe_message.lower():
            state["_warning_message"] = safe_message

    for line in lines:
        observed_at, message = public_activity_parts(line)
        if not message:
            continue

        download_match = re.match(
            r'^NCBI_DOWNLOAD_PROGRESS\s+accession=(?P<accession>\S+)\s+taxon=(?P<taxon>\S+)\s+status=(?P<status>\S+)\s+percent=(?P<percent>\d+)\s+message="(?P<message>.*)"\s*$',
            message,
            re.IGNORECASE,
        )
        if download_match:
            values = download_match.groupdict()
            accession = values["accession"].upper()
            genome_id = accession_to_genome.get(accession, accession)
            state = ensure_state(genome_id, values.get("taxon"))
            marker_status = values["status"].lower()
            downloaded = marker_status in {
                "complete",
                "completed",
                "downloaded",
                "done",
                "ready",
                "success",
                "succeeded",
            }
            if marker_status in {"failed", "failure", "error"}:
                public_status = "warning"
            elif marker_status in {
                "complete",
                "completed",
                "downloaded",
                "done",
                "ready",
                "success",
                "succeeded",
                "pending",
                "queued",
                "waiting",
            }:
                # Download completion means this genome is ready for an
                # annotation lane; it is not evidence that a lane is active.
                public_status = "queued"
            else:
                public_status = "running"
            update_state(
                state,
                stage="download",
                tool="NCBI",
                percent=int(values["percent"]),
                status=public_status,
                message="NCBI genome downloaded | queued" if downloaded else values.get("message"),
                observed_at=observed_at,
                warning=public_status == "warning",
            )
            update_stage_state(
                state,
                "download",
                "complete" if downloaded else ("failed" if public_status == "warning" else public_status),
                "Genome acquired" if downloaded else values.get("message"),
            )
            continue

        route_match = re.match(
            r"^TAXON_ROUTE\s+genome=(?P<genome>\S+)\s+taxon=(?P<taxon>\S+)"
            r"(?:\s+source=(?P<source>\S+))?",
            message,
            re.IGNORECASE,
        )
        if route_match:
            values = route_match.groupdict()
            ensure_state(
                values["genome"], values["taxon"], values.get("source") or ""
            )
            continue

        annotation_decision_match = re.match(
            r'^GENOME_ANNOTATION_DECISION\s+genome=(?P<genome>\S+)\s+required=(?P<required>yes|no)\s+method=(?P<method>\S+)\s+message="(?P<message>.*)"\s*$',
            message,
            re.IGNORECASE,
        )
        if annotation_decision_match:
            values = annotation_decision_match.groupdict()
            state = ensure_state(values["genome"])
            selected = annotation_method(values.get("method"))
            if values["required"].lower() == "no":
                selected = selected or "existing_cds"
            if selected:
                state["annotation_method"] = selected
            continue

        record_progress_match = re.match(
            r'^ANTISMASH_RECORD_PROGRESS\s+genome=(?P<genome>\S+)\s+record=(?P<record>\S+)\s+ordinal=(?P<ordinal>\d+)/(?P<total>\d+)\s+percent=(?P<percent>\d+)\s+bar=\[[^\]]*\]\s+message="(?P<message>.*)"\s*$',
            message,
            re.IGNORECASE,
        )
        if record_progress_match:
            values = record_progress_match.groupdict()
            state = ensure_state(values["genome"])
            if state.get("taxon_group") == "fungi" and not state.get("annotation_method"):
                state["annotation_method"] = "existing_cds"
            total_records = max(1, int(values["total"]))
            ordinal = min(total_records, max(1, int(values["ordinal"])))
            record_percent = min(100, max(0, int(values["percent"])))
            # Record shards occupy 35-69%; the explicit GENOME_PROGRESS 70
            # milestone is reserved for whole-genome antiSMASH completion.
            overall_percent = 35 + min(34, (record_percent * 34 + 50) // 100)
            raw_message = str(values.get("message") or "")
            safe_message = public_tool_activity_message(raw_message)
            detail = f"Record {ordinal} of {total_records} · {record_percent}%"
            if safe_message != "Running":
                detail = f"{detail} · {safe_message}"
            update_state(
                state,
                stage="antismash",
                tool="antiSMASH",
                percent=overall_percent,
                # A record warning is provisional.  The authoritative
                # GENOME_PROGRESS milestone decides when the genome is done.
                status="running",
                message=detail,
                observed_at=observed_at,
            )
            update_stage_state(state, "genome_acquired", "complete", "Genome acquired")
            update_stage_state(state, "antismash", "running", detail)
            continue

        progress_match = re.match(
            r'^GENOME_PROGRESS\s+genome=(?P<genome>\S+)\s+stage=(?P<stage>\S+)\s+percent=(?P<percent>\d+)\s+bar=\[[^\]]*\]\s+message="(?P<message>.*)"\s*$',
            message,
            re.IGNORECASE,
        )
        if progress_match:
            values = progress_match.groupdict()
            state = ensure_state(values["genome"])
            percent = min(100, max(0, int(values["percent"])))
            # A rerun appends to the existing job log. Treat its explicit zero
            # milestone as a new attempt so an earlier terminal warning and
            # 100% value cannot mask the genome's current progress.
            if percent == 0 and (
                int(state.get("percent", 0) or 0) >= 100
                or str(state.get("status") or "") in {"complete", "complete_with_warning", "warning", "failed"}
            ):
                state["percent"] = 0
                state["status"] = "queued"
                state["_warning"] = False
                state["_warning_tool"] = ""
                state["_warning_message"] = ""
                state["_stage_states"] = {}
            raw_message = str(values.get("message") or "")
            progress_stage = str(values.get("stage") or "").strip().lower()
            if progress_stage == "funannotate" or re.search(
                r"\bfunannotate\b", raw_message, re.IGNORECASE
            ):
                state["annotation_method"] = "funannotate"
            elif (
                progress_stage == "antismash"
                and state.get("taxon_group") == "fungi"
                and not state.get("annotation_method")
            ):
                state["annotation_method"] = "existing_cds"
            safe_message = public_tool_activity_message(raw_message)
            lowered = raw_message.lower()
            warning = any(
                marker in lowered
                for marker in (
                    "dropped",
                    "failed",
                    "rejected",
                    "could not",
                    "exceeded the available",
                    "exited before producing",
                )
            )
            status = "complete" if percent >= 100 else "running"
            if warning:
                status = "warning"
            projected_stage = values["stage"]
            projected_tool = values["stage"]
            bacterial_terminal_alias = (
                state.get("taxon_group") == "bacteria"
                and (
                    (progress_stage == "funbgcex" and "not applicable" in lowered)
                    or (
                        progress_stage == "complete"
                        and "bgc detection complete" in lowered
                    )
                )
            )
            if bacterial_terminal_alias:
                # Normalize legacy FunBGCeX-N/A and transitional `complete`
                # markers onto the bacterial lane's actual terminal tool.
                projected_stage = "complete"
                projected_tool = "antiSMASH"
                if state.get("_warning"):
                    # Older workers emitted an unconditional success marker
                    # after antiSMASH failure. Preserve the truthful earlier
                    # warning while still making the lane terminal.
                    safe_message = str(state.get("message") or "antiSMASH failed")
                    warning = True
                    status = "warning"
                else:
                    safe_message = "BGC detection complete"
            update_state(
                state,
                stage="complete" if percent >= 100 and not warning else projected_stage,
                tool=projected_tool,
                percent=percent,
                status=status,
                message=safe_message,
                observed_at=observed_at,
                warning=warning,
            )
            stage_key = progress_stage
            if bacterial_terminal_alias:
                stage_key = "antismash"
            stage_status = "failed" if warning else (
                "complete"
                if (
                    (progress_stage == "antismash" and percent >= 70)
                    or (progress_stage == "funbgcex" and percent >= 100)
                    or progress_stage == "complete"
                )
                else "running"
            )
            update_stage_state(state, "genome_acquired", "complete", "Genome acquired")
            if progress_stage in {"antismash", "funbgcex", "complete"}:
                if (
                    state.get("annotation_method") == "funannotate"
                    and progress_stage in {"antismash", "funbgcex", "complete"}
                ):
                    update_stage_state(state, "funannotate", "complete", "Funannotate complete")
                update_stage_state(state, stage_key, stage_status, safe_message)
            elif progress_stage == "funannotate":
                update_stage_state(state, "funannotate", stage_status, safe_message)
            if warning:
                remember_tool_failure(state, projected_tool, safe_message)
            if percent >= 100:
                update_stage_state(
                    state,
                    "complete",
                    "queued" if state.get("_warning") else "complete",
                    "Not complete" if state.get("_warning") else "Genome workflow complete",
                )
            continue

        tool_marker = public_tool_activity_marker(message)
        if tool_marker:
            state = ensure_state(tool_marker.get("genome"))
            marker_tool = public_tool_activity_tool_name(tool_marker.get("tool"))
            marker_tool_lower = marker_tool.lower()
            if marker_tool_lower == "funannotate":
                state["annotation_method"] = "funannotate"
                marker_stage = "funannotate"
            elif marker_tool_lower in {"antismash", "anti-smash", "prodigal"}:
                marker_stage = "antismash"
                if state.get("taxon_group") == "fungi" and not state.get("annotation_method"):
                    state["annotation_method"] = "existing_cds"
            elif marker_tool_lower == "funbgcex":
                marker_stage = "funbgcex"
            else:
                marker_stage = "annotation"
            activity = tool_marker.get("message") or "Running"
            if tool_marker.get("kind") == "heartbeat":
                activity = f"Still running ({public_tool_activity_elapsed_text(tool_marker.get('elapsed'))})"
            marker_failed = tool_marker.get("kind") == "raw_error"
            update_state(
                state,
                stage=marker_stage,
                tool=marker_tool,
                status="warning" if marker_failed else "running",
                message=activity,
                observed_at=observed_at,
                warning=marker_failed,
            )
            update_stage_state(state, "genome_acquired", "complete", "Genome acquired")
            update_stage_state(
                state, marker_stage, "failed" if marker_failed else "running", activity
            )
            if marker_failed:
                remember_tool_failure(state, marker_tool, activity)
            continue

        genomes_match = re.search(r"Genomes to process\s+\(\d+\):\s*(.+)$", message, re.IGNORECASE)
        if genomes_match:
            for raw_genome in genomes_match.group(1).split(","):
                ensure_state(raw_genome)

    terminal_job = str(job.get("status") or "").lower() in {"success", "failed"}
    output: list[dict[str, object]] = []
    for state in states.values():
        if terminal_job and int(state.get("percent", 0) or 0) < 100:
            update_state(
                state,
                status="warning" if str(job.get("status") or "").lower() == "success" else "failed",
                message="No terminal genome milestone was reported",
                warning=str(job.get("status") or "").lower() == "success",
            )
        state["terminal"] = str(state.get("status")) in {
            "complete", "complete_with_warning", "warning", "failed"
        }
        if state.get("_warning_tool"):
            state["warning_tool"] = state["_warning_tool"]
        if state.get("_warning_message"):
            state["warning_message"] = state["_warning_message"]
        stage_states = state.get("_stage_states")
        if isinstance(stage_states, dict):
            state["stage_states"] = stage_states
        state.pop("_warning", None)
        output.append(state)
        state.pop("_warning_tool", None)
        state.pop("_warning_message", None)
        state.pop("_stage_states", None)
    return output


def public_activity_from_logs(job_id: str, lines: list[str]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    current_stage = "prep"
    genome_total = 0
    genome_position: dict[str, str] = {}

    for line in lines:
        observed_at, message = public_activity_parts(line)
        if not message:
            continue

        tool_marker = public_tool_activity_marker(message)
        if tool_marker:
            tool = public_tool_activity_tool_name(tool_marker.get("tool"))
            genome_label = public_activity_label(tool_marker.get("genome"))
            position = genome_position.get(genome_label)
            if tool_marker.get("kind") == "heartbeat":
                elapsed = public_tool_activity_elapsed_text(tool_marker.get("elapsed"))
                meta_prefix_parts = [genome_label]
                if position:
                    meta_prefix_parts.append(f"Genome {position}")
                meta_prefix = " / ".join(part for part in meta_prefix_parts if part)
                title = f"{tool} still running"
                prune_public_activity_heartbeat(events, seen, "annotation", title, meta_prefix)
                meta_parts = [meta_prefix, f"{elapsed} active"]
                add_public_activity_event(
                    events,
                    seen,
                    "annotation",
                    title,
                    " / ".join(part for part in meta_parts if part),
                    observed_at,
                    refresh=True,
                )
            else:
                activity = public_tool_activity_message(tool_marker.get("message"))
                meta_parts = [genome_label]
                if position:
                    meta_parts.append(f"Genome {position}")
                add_public_activity_event(
                    events,
                    seen,
                    "annotation",
                    f"{tool}: {activity}",
                    " / ".join(part for part in meta_parts if part),
                    observed_at,
                    refresh=True,
                )
            continue

        if re.match(r"^TOOL_", message, re.IGNORECASE):
            continue

        marker_stage = public_activity_stage_from_marker(message)
        if marker_stage:
            current_stage = marker_stage
            title_by_stage = {
                "prep": "Preparing input workspace",
                "annotation": "Running annotation and BGC detection",
                "bigscape": "Running BiG-SCAPE family graph",
                "summary": "Building summary tables",
                "clinker": "Staging synteny panels",
                "figures": "Rendering summary figures",
                "nplinker": "Running optional NPLinker follow-up",
            }
            add_public_activity_event(
                events,
                seen,
                current_stage,
                title_by_stage[current_stage],
                "Canonical workflow stage",
                observed_at,
            )
            continue

        staged_match = re.search(r"^(Staged genome input|Staged accession list|Staged ecology metadata):\s+(.+)$", message, re.IGNORECASE)
        if staged_match:
            label = public_activity_label(Path(staged_match.group(2)).name)
            kind = staged_match.group(1).lower()
            if "genome" in kind:
                title = "Staged genome input"
            elif "ecology" in kind:
                title = "Staged ecology labels"
            else:
                title = "Staged accession list"
            add_public_activity_event(events, seen, "prep", title, label, observed_at)
            continue

        if re.search(r"Reusing existing staged ClusterWeave layout for rerun", message, re.IGNORECASE):
            add_public_activity_event(events, seen, "prep", "Reused staged inputs for rerun", "Existing job workspace", observed_at)
            continue

        work_match = re.search(r"\[WORK\]\s+((?:GCA|GCF)_\d{9}\.\d+)", message, re.IGNORECASE)
        if work_match:
            accession = public_activity_label(work_match.group(1).upper())
            add_public_activity_event(events, seen, "prep", f"Fetching accession {accession}", "NCBI genome download", observed_at)
            continue

        genomes_match = re.search(r"Genomes to process\s+\((\d+)\):\s*(.+)$", message, re.IGNORECASE)
        if genomes_match:
            genome_total = max(0, int(genomes_match.group(1)))
            labels = [public_activity_label(part) for part in genomes_match.group(2).split(",")]
            labels = [label for label in labels if label]
            shown = ", ".join(labels[:3])
            if len(labels) > 3:
                shown = f"{shown}, +{len(labels) - 3} more"
            add_public_activity_event(
                events,
                seen,
                "annotation",
                f"Queued {genome_total} genome{'s' if genome_total != 1 else ''} for annotation",
                shown,
                observed_at,
            )
            continue

        genome_match = re.search(r"\[(\d+)/(\d+)\]\s+genome=([^\s]+)", message, re.IGNORECASE)
        if genome_match:
            index, total, genome = genome_match.groups()
            genome_total = max(genome_total, int(total))
            genome_label = public_activity_label(genome)
            genome_position[genome_label] = f"{index} of {total}"
            add_public_activity_event(
                events,
                seen,
                "annotation",
                f"Preparing genome {index} of {total}",
                genome_label,
                observed_at,
            )
            continue

        antismash_match = re.search(r"^([^:\s]+):\s+running antiSMASH\b", message, re.IGNORECASE)
        if antismash_match:
            genome_label = public_activity_label(antismash_match.group(1))
            meta = f"Genome {genome_position[genome_label]}" if genome_label in genome_position else "BGC detection"
            add_public_activity_event(
                events,
                seen,
                "annotation",
                f"Running antiSMASH on {genome_label}",
                meta,
                observed_at,
            )
            continue

        funbgcex_match = re.search(r"^([^:\s]+):\s+running FunBGCeX\b", message, re.IGNORECASE)
        if funbgcex_match:
            genome_label = public_activity_label(funbgcex_match.group(1))
            meta = f"Genome {genome_position[genome_label]}" if genome_label in genome_position else "BGC detection"
            add_public_activity_event(
                events,
                seen,
                "annotation",
                f"Running FunBGCeX on {genome_label}",
                meta,
                observed_at,
            )
            continue

        done_match = re.search(r"^([^:\s]+):\s+(antiSMASH|FunBGCeX)\s+OK\b", message, re.IGNORECASE)
        if done_match:
            genome_label = public_activity_label(done_match.group(1))
            tool = "antiSMASH" if done_match.group(2).lower() == "antismash" else "FunBGCeX"
            add_public_activity_event(
                events,
                seen,
                "annotation",
                f"Finished {tool} on {genome_label}",
                "BGC detection",
                observed_at,
            )
            continue

        training_match = re.search(
            r"^([^:\s]+):\s+funannotate could not train AUGUSTUS;\s+(.+)$",
            message,
            re.IGNORECASE,
        )
        if training_match:
            genome_label = public_activity_label(training_match.group(1))
            detail = training_match.group(2)
            count_match = re.search(
                r"validated_busco_models=(\d+)\s+required_training_models=(\d+)",
                detail,
                re.IGNORECASE,
            )
            meta = "Insufficient BUSCO training models"
            if count_match:
                meta = f"BUSCO training had {count_match.group(1)} of {count_match.group(2)} required models"
            add_public_activity_event(
                events,
                seen,
                "annotation",
                f"Annotation skipped for {genome_label}",
                meta,
                observed_at,
            )
            continue

        bigscape_region_match = re.search(r"Staged region GBKs:\s*(\d+)", message, re.IGNORECASE)
        if bigscape_region_match:
            add_public_activity_event(events, seen, "bigscape", "Staged region GBKs", f"{bigscape_region_match.group(1)} regions", observed_at)
            continue

        if re.search(r"Running BiG-SCAPE|BiG-SCAPE complete|BiG-SCAPE outputs already exist", message, re.IGNORECASE):
            title = "BiG-SCAPE complete" if re.search(r"complete|already exist", message, re.IGNORECASE) else "Running BiG-SCAPE clustering"
            add_public_activity_event(events, seen, "bigscape", title, "Family graph construction", observed_at)
            continue

        summary_written_match = re.search(r"Wrote (?:scaffold comparison table|BGC comparison table|summary table|.*crosswalk rows|ecology-group .*|GCF ecology distribution|targeted candidate ranking|.*shortlist(?: TSV| Markdown| note)?)", message, re.IGNORECASE)
        if summary_written_match:
            add_public_activity_event(events, seen, "summary", "Updated summary outputs", "Crosswalks and shortlist tables", observed_at)
            continue

        if re.search(r"Refreshing (candidate ranking|dataset-wide family atlas|priority shortlist|BiG-SCAPE shared-family shortlist)|Skipping .*shortlist refresh", message, re.IGNORECASE):
            add_public_activity_event(events, seen, "clinker", "Prepared synteny shortlist inputs", "Panel target selection", observed_at)
            continue

        clinker_panel_match = re.search(r"Staged (\d+) clinker panels", message, re.IGNORECASE)
        if clinker_panel_match:
            add_public_activity_event(events, seen, "clinker", "Staged clinker panels", f"{clinker_panel_match.group(1)} panels", observed_at)
            continue

        if re.search(r"Running .*clinker panels|run_clinker\.sh complete|Wrote panel manifest|Wrote master run script", message, re.IGNORECASE):
            add_public_activity_event(events, seen, "clinker", "Updated synteny panel outputs", "clinker staging", observed_at)
            continue

        if re.search(r"\brender(?:ing)?\s+summary\s+figures\b|Rendering BGC overlap figure|Rendering BiG-SCAPE (?:network|multipanel) figure", message, re.IGNORECASE):
            current_stage = "figures"
            add_public_activity_event(events, seen, "figures", "Rendering summary figures", "Visual summaries", observed_at)
            continue

        if re.search(r"Wrote .*\.(?:svg|png|pdf)$|run_figures\.sh complete", message, re.IGNORECASE):
            add_public_activity_event(events, seen, "figures", "Updated figure outputs", "Visual summaries", observed_at)
            continue

        if re.search(r"Wrote .*NPLinker|Wrote .*links to|Wrote .*summary rows to|Seeded BiG-SCAPE data", message, re.IGNORECASE):
            add_public_activity_event(events, seen, "nplinker", "Updated NPLinker outputs", "Optional omics follow-up", observed_at)
            continue

        if re.search(r"\b(FATAL|ERROR|FAILED|failed with exit code)\b", message):
            add_public_activity_event(
                events,
                seen,
                current_stage,
                "Run reported an error",
                "Check inputs and partial outputs.",
                observed_at,
            )

    return events[-PUBLIC_ACTIVITY_LIMIT:]



def worker_active_job_ids(status: dict[str, object] | None = None) -> list[str]:
    worker = (status or worker_status()).get("worker")
    if not isinstance(worker, dict):
        return []
    active = worker.get("active_jobs")
    if not isinstance(active, list):
        return []
    return [str(job_id) for job_id in active if str(job_id)]


def queue_sort_timestamp(value: object, fallback: float) -> float:
    text = str(value or "").strip()
    if not text:
        return fallback
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return fallback


def queued_job_ids() -> list[str]:
    queued: list[tuple[float, int, str, str]] = []
    for queue_path in QUEUE_DIR.glob("*.json"):
        job_id = queue_path.stem
        try:
            stat = queue_path.stat()
            fallback_timestamp = stat.st_mtime
            mtime_ns = stat.st_mtime_ns
        except OSError:
            fallback_timestamp = 0.0
            mtime_ns = 0
        timestamp = fallback_timestamp
        try:
            payload = json.loads(queue_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                if payload.get("job_id"):
                    job_id = str(payload["job_id"])
                timestamp = queue_sort_timestamp(
                    payload.get("enqueued_at") or payload.get("created_at"),
                    fallback_timestamp,
                )
        except Exception:
            pass
        if job_id:
            queued.append((timestamp, mtime_ns, queue_path.name, job_id))
    queued.sort(key=lambda item: item[:3])
    return [item[3] for item in queued]


def slurm_scheduler_metadata(job: dict[str, object]) -> dict[str, object]:
    scheduler = job.get("scheduler")
    if isinstance(scheduler, dict) and str(scheduler.get("kind") or "").lower() == "slurm":
        return scheduler
    return {}


def slurm_scheduler_job_id(job: dict[str, object]) -> str:
    scheduler = slurm_scheduler_metadata(job)
    return str(scheduler.get("job_id") or job.get("slurm_job_id") or "").strip()


def job_needs_scheduler_cancel_before_delete(job: dict[str, object]) -> bool:
    status = str(job.get("status") or "").lower()
    return status in QUEUED_JOB_STATUSES and bool(slurm_scheduler_job_id(job))


def job_queue_status(job: dict[str, object], *, admin: bool) -> dict[str, object] | None:
    job_id = str(job.get("id") or "")
    status = str(job.get("status") or "").lower()
    if not job_id or status not in QUEUED_JOB_STATUSES:
        return None

    worker = worker_status()
    active_ids = worker_active_job_ids(worker)
    queued_ids = queued_job_ids()
    active_count = len(active_ids)
    scheduler = slurm_scheduler_metadata(job)
    scheduler_id = slurm_scheduler_job_id(job)

    if scheduler_id:
        scheduler_state = str(scheduler.get("state") or "").upper()
        if status == "running" or scheduler_state in {"RUNNING", "COMPLETING", "SUSPENDED", "STOPPED"}:
            state = "running"
            detail = "Scheduler is processing this run."
        else:
            state = "queued"
            detail = "Submitted to the scheduler; waiting for compute resources."
        payload: dict[str, object] = {
            "state": state,
            "position": None,
            "jobs_ahead": active_count,
            "active_count": active_count,
            "queue_depth": len(queued_ids),
            "detail": detail,
        }
        if admin:
            payload["active_jobs"] = active_ids
            payload["scheduler"] = {
                "kind": "slurm",
                "job_id": scheduler_id,
                "state": scheduler_state or None,
            }
        return payload

    if job_id in active_ids or status == "running":
        detail = "Worker is processing this run."
        if job_id not in active_ids:
            detail = "Run is marked running; waiting for the next worker heartbeat."
        payload: dict[str, object] = {
            "state": "running",
            "position": 0,
            "jobs_ahead": 0,
            "active_count": active_count,
            "queue_depth": len(queued_ids),
            "detail": detail,
        }
        if admin:
            payload["active_jobs"] = active_ids
        return payload

    if job_id in queued_ids:
        queue_position = queued_ids.index(job_id) + 1
        jobs_ahead = active_count + queue_position - 1
        if jobs_ahead:
            detail = f"Waiting for worker slot; {jobs_ahead} active or queued run(s) ahead."
        else:
            detail = "Waiting for worker slot; this run is next."
        payload = {
            "state": "queued",
            "position": queue_position,
            "jobs_ahead": jobs_ahead,
            "active_count": active_count,
            "queue_depth": len(queued_ids),
            "detail": detail,
        }
        if admin:
            payload["active_jobs"] = active_ids
        return payload

    payload = {
        "state": "claiming",
        "position": None,
        "jobs_ahead": active_count,
        "active_count": active_count,
        "queue_depth": len(queued_ids),
        "detail": "Worker has claimed or is about to claim this run.",
    }
    if admin:
        payload["active_jobs"] = active_ids
    return payload

def safe_count_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for key, raw_value in value.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", key):
            continue
        try:
            count = int(raw_value)
        except (TypeError, ValueError):
            continue
        if count >= 0:
            counts[key] = count
    return counts


def public_input_summary(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    summary: dict[str, object] = {}
    for key in [
        "accession_count",
        "genome_file_count",
        "metadata_file_count",
        "taxon_assignment_file_count",
        "genome_count",
        "upload_bytes",
    ]:
        try:
            count = int(value.get(key, 0))
        except (TypeError, ValueError):
            continue
        if count >= 0:
            summary[key] = count
    try:
        summary["analysis_scope"] = normalize_analysis_scope(
            value.get("analysis_scope")
        )
    except TaxonRoutingError:
        summary["analysis_scope"] = "fungi"
    summary["taxon_counts"] = safe_count_mapping(value.get("taxon_counts"))
    summary["applicability_counts"] = safe_count_mapping(
        value.get("applicability_counts")
    )
    return summary


def saved_job_analysis_scope(job: dict[str, object]) -> str:
    value = job.get("analysis_scope")
    if value is None and isinstance(job.get("settings"), dict):
        value = job["settings"].get("analysis_scope")  # type: ignore[index]
    try:
        return normalize_analysis_scope(value)
    except TaxonRoutingError:
        return "fungi"



def job_summary_payload(job: dict[str, object]) -> dict[str, object]:
    """Project one compact admin-drawer record without result/log hydration."""

    payload = dict(job)
    for key in SENSITIVE_JOB_FIELDS:
        payload.pop(key, None)
    payload["public_run_id"] = public_run_id_for_job(job)
    stored_results = job.get("result_files")
    payload["result_file_count"] = (
        len(stored_results)
        if isinstance(stored_results, (list, tuple))
        else max(0, parse_int(job.get("result_file_count"), 0))
    )
    payload["analysis_scope"] = saved_job_analysis_scope(job)
    payload["taxon_counts"] = safe_count_mapping(job.get("taxon_counts"))
    payload["applicability_counts"] = safe_count_mapping(
        job.get("applicability_counts")
    )
    queue_status = job_queue_status(job, admin=True)
    if queue_status is not None:
        payload["queue_status"] = queue_status
    return payload

def job_payload(job: dict[str, object], *, admin: bool, include_public_events: bool = False, include_results: bool = True) -> dict[str, object]:
    skip_result_index = not include_results or str(job.get("status") or "").lower() in QUEUED_JOB_STATUSES
    if not admin:
        payload = {
            key: job[key]
            for key in [
                "name",
                "status",
                "stage",
                "created_at",
                "updated_at",
                "log_count",
                "cpus",
                "project_name",
                "retention_days",
                "expires_at",
                "completed_at",
                "failed_at",
            ]
            if key in job
        }
        public_id = public_run_id_for_job(job)
        payload["id"] = public_id
        payload["job_id"] = public_id
        payload["public_run_id"] = public_id
        stored_results = job.get("result_files")
        result_count = (
            len(stored_results) if isinstance(stored_results, (list, tuple)) else 0
        )
        payload["result_file_count"] = result_count
        payload["result_index_state"] = "stored" if result_count else "pending"
        payload["bigscape_viewer_available"] = result_is_public_bigscape_viewer_database(normalized_job_result_path(job.get("bigscape_viewer_database")))
        public_result_base = None
        if "input_summary" in job:
            payload["input_summary"] = public_input_summary(job.get("input_summary"))
        payload["analysis_scope"] = saved_job_analysis_scope(job)
        payload["taxon_counts"] = safe_count_mapping(
            job.get("taxon_counts")
        )
        payload["applicability_counts"] = safe_count_mapping(
            job.get("applicability_counts")
        )
        if job.get("error") or str(job.get("status", "")).lower() == "failed":
            payload["error"] = public_error_summary(job.get("error"))
            payload["error_summary"] = payload["error"]
    else:
        payload = dict(job)
        for key in SENSITIVE_JOB_FIELDS:
            payload.pop(key, None)
        payload["public_run_id"] = public_run_id_for_job(job)
        stored_results = job.get("result_files")
        payload["result_file_count"] = (
            len(stored_results)
            if isinstance(stored_results, (list, tuple))
            else max(0, parse_int(job.get("result_file_count"), 0))
        )
        # This persisted value is only an internal publication pointer. Never
        # echo it to admin or public clients until exact disk/profile
        # attestation below succeeds.
        payload.pop("bigscape_viewer_database", None)
        payload.setdefault("analysis_scope", saved_job_analysis_scope(job))
        # The admin run list is polled frequently. Shape-filter its stored
        # result index without hashing every large derivative on every fresh
        # process; individual job/file routes perform the full disk-backed
        # attestation before exposing bytes.
        public_result_base = (
            job_dir(str(job.get("id", ""))).resolve()
            if job.get("id") and include_public_events and not skip_result_index
            else None
        )
        allowed_files = [] if skip_result_index else result_file_allowlist(
            job,
            base_dir=public_result_base,
        )
        payload["result_files"] = allowed_files
        payload["bigscape_viewer_available"] = False
        if public_result_base is not None:
            viewer_path = advertised_bigscape_viewer_database_path(
                job,
                public_result_base,
                public_files=allowed_files,
            )
            payload["bigscape_viewer_available"] = bool(viewer_path)
            if viewer_path:
                payload["bigscape_viewer_database"] = viewer_path
    if public_result_base is not None:
        payload.update(result_index_metadata(job, public_result_base))
    queue_status = job_queue_status(job, admin=admin)
    if queue_status is not None:
        payload["queue_status"] = queue_status
    if include_public_events and not admin:
        job_id = str(job.get("id") or "")
        known_log_count = max(0, parse_int(job.get("log_count"), 0))
        lines = (
            public_activity_projection_lines(job_id, known_log_count)
            if job_id
            else []
        )
        payload["public_events"] = public_activity_from_logs(job_id, lines) if job_id else []
        payload["genome_progress"] = (
            public_genome_progress(job, lines) if job_id else []
        )
    return payload


def jobs_processed_count() -> int:
    retained = sum(
        1
        for job in list_jobs()
        if str(job.get("status", "")).lower() in PROCESSED_JOB_STATUSES
    )
    deleted = int(read_retention_totals().get("completed_jobs_deleted") or 0)
    return retained + deleted


def queued_job_count() -> int:
    return sum(1 for job in list_jobs() if str(job.get("status", "")).lower() == "pending")


def running_job_count() -> int:
    return sum(1 for job in list_jobs() if str(job.get("status", "")).lower() == "running")


def public_quota_payload() -> dict[str, int]:
    return {
        "max_accessions": MAX_ACCESSIONS,
        "max_genome_files": MAX_GENOME_FILES,
        "max_upload_file_mb": MAX_UPLOAD_FILE_MB,
        "max_upload_total_mb": MAX_UPLOAD_TOTAL_MB,
    }


def redacted_system_status() -> dict[str, object]:
    submissions_open = SUBMISSIONS_OPEN
    return {
        "online": True,
        "service": "online",
        "submissions_open": submissions_open,
        "submissions": "open" if submissions_open else "paused",
        "jobs_processed": jobs_processed_count(),
        "running_jobs": running_job_count(),
        "queued_jobs": queued_job_count(),
        "smtp_enabled": SMTP_ENABLED,
        "public_quota": public_quota_payload(),
    }


def full_system_status() -> dict[str, object]:
    payload = worker_status()
    submissions_open = SUBMISSIONS_OPEN
    active_ids = worker_active_job_ids(payload)
    worker = payload.get("worker")
    active_count = len(active_ids)
    if active_count == 0 and isinstance(worker, dict):
        try:
            active_count = max(0, int(worker.get("active_count", 0) or 0))
        except (TypeError, ValueError):
            active_count = 0
    payload["service"] = "online"
    payload["submissions_open"] = submissions_open
    payload["submissions"] = "open" if submissions_open else "paused"
    payload["jobs_processed"] = jobs_processed_count()
    payload["running_jobs"] = active_count
    payload["queued_jobs"] = queued_job_count()
    payload["smtp_enabled"] = SMTP_ENABLED
    payload["public_quota"] = public_quota_payload()
    return payload


def allowed_cors_origin(origin: str | None) -> str | None:
    if not PUBLIC_MODE:
        return "*"
    if not origin:
        return None
    if "*" in ALLOWED_CORS_ORIGINS:
        return origin
    if origin in ALLOWED_CORS_ORIGINS:
        return origin
    return None


def request_public_base_url(handler: BaseHTTPRequestHandler) -> str:
    configured = os.environ.get("CLUSTERWEAVE_PUBLIC_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/") + "/"
    proto = handler.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip() or "http"
    host = handler.headers.get("X-Forwarded-Host", "").split(",", 1)[0].strip() or handler.headers.get("Host", "").strip()
    if not host:
        host = f"localhost:{PORT}"
    return f"{proto}://{host}/"


def public_cpu_limit() -> int:
    return min(MAX_CPUS_PER_JOB, os.cpu_count() or MAX_CPUS_PER_JOB)


def clamp_public_cpus(value: int) -> int:
    if not PUBLIC_MODE:
        return max(1, min(value, os.cpu_count() or value))
    return max(1, min(value, public_cpu_limit()))


def hosted_resource_plan(
    cpus: int,
    genome_count: int,
    settings: dict[str, object],
):
    """Build the operator-selected execution shape for a hosted job.

    Hidden browser fields intentionally retain conservative local defaults, so
    they are not authoritative in public mode.  Both submit-token and ordinary
    admin WebUI submissions use these operator targets after the logical genome
    count is known.  Optional admin-only phylogeny settings remain part of the
    bounded whole-job plan.
    """

    return ResourceRequest(
        job_cpus=cpus,
        genome_count=genome_count,
        target_genome_parallelism=PUBLIC_GENOME_PARALLELISM,
        target_antismash_record_parallelism=PUBLIC_ANTISMASH_RECORD_PARALLELISM,
        target_antismash_shard_cpus=cpus,
        target_antismash_legacy_cpus=cpus,
        target_anno_cpus=PUBLIC_FUNANNOTATE_CPUS_PER_GENOME,
        target_funbgcex_workers=PUBLIC_FUNBGCEX_WORKERS_PER_GENOME,
        run_phylogeny=settings_bool(settings, "run_phylogeny"),
        target_phylogeny_cpus=max(
            1, parse_int(settings.get("phylogeny_cpus", 1), 1)
        ),
        target_phylogeny_parallelism=1,
    ).bounded_plan()


def submission_disk_error() -> str | None:
    if MIN_FREE_DISK_GB <= 0:
        return None
    try:
        free_bytes = shutil.disk_usage(DATA_DIR).free
    except OSError:
        return "Cannot verify free job-storage capacity; submissions are temporarily paused"
    minimum_bytes = MIN_FREE_DISK_GB * BYTES_PER_GB
    if free_bytes >= minimum_bytes:
        return None
    free_gb = free_bytes / BYTES_PER_GB
    return (
        f"Job storage is below the operator safety reserve "
        f"({free_gb:.1f} GiB free; {MIN_FREE_DISK_GB} GiB required)"
    )


def staged_upload_path(item: dict[str, object]) -> Path | None:
    raw_path = str(item.get("staged_path") or "").strip()
    return Path(raw_path) if raw_path else None


def upload_size(item: dict[str, object]) -> int:
    try:
        size = int(item.get("size", -1))
    except (TypeError, ValueError):
        size = -1
    if size >= 0:
        return size
    return len(bytes(item.get("content") or b""))


def open_upload_binary(item: dict[str, object]):
    path = staged_upload_path(item)
    if path is not None:
        return path.open("rb")
    return io.BytesIO(bytes(item.get("content") or b""))


def cleanup_staged_uploads(items: list[dict[str, object]]) -> None:
    for item in items:
        path = staged_upload_path(item)
        if path is None:
            continue
        path.unlink(missing_ok=True)
        item["staged_path"] = ""


def stage_multipart_upload(source: object) -> tuple[str, int]:
    """Copy one multipart file to bounded-memory, request-scoped disk staging."""
    UPLOAD_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix="upload-", dir=UPLOAD_STAGING_DIR)
    temporary_path = Path(temporary_name)
    size = 0
    try:
        try:
            source.seek(0)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
        with os.fdopen(descriptor, "wb") as destination:
            while True:
                chunk = source.read(UPLOAD_COPY_CHUNK_BYTES)  # type: ignore[attr-defined]
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                destination.write(chunk)
                size += len(chunk)
        return str(temporary_path), size
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def persist_upload(item: dict[str, object], destination: Path) -> None:
    """Atomically install a staged upload while retaining byte-input compatibility."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = staged_upload_path(item)
    if staged is not None:
        os.replace(staged, destination)
        item["staged_path"] = ""
        return

    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.upload")
    try:
        with temporary.open("wb") as handle:
            handle.write(bytes(item.get("content") or b""))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def parse_accession_list(filename: str, content: bytes) -> tuple[str | None, list[str]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return f"Accession list '{filename}' must be UTF-8 text", []

    accessions: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if re.search(r"[\s,;]+", line):
            return f"Accession list '{filename}' must contain one accession per line; line {line_number} has multiple values", []
        if line.lower() == "accession":
            return f"Accession list '{filename}' must not include a header row", []
        if not NCBI_ASSEMBLY_ACCESSION_RE.match(line):
            return (
                f"Accession list '{filename}' line {line_number} has invalid accession '{line}'. "
                f"Use current NCBI assembly accessions like {NCBI_ACCESSION_EXAMPLES}",
                [],
            )
        accessions.append(line.upper())
    return None, accessions


def parse_accession_text(filename: str, content: bytes) -> tuple[str | None, int]:
    error, accessions = parse_accession_list(filename, content)
    return error, len(accessions)


def parse_accession_upload(
    filename: str, item: dict[str, object]
) -> tuple[str | None, list[str]]:
    # Twenty-five valid assembly accessions occupy far less than 64 KiB. This
    # bound prevents an invalid single-line text upload from being materialized
    # in memory merely to reject it.
    with open_upload_binary(item) as handle:
        content = handle.read(64 * 1024 + 1)
    if len(content) > 64 * 1024:
        return (
            f"Accession list '{filename}' must contain one accession per line and no more than {MAX_ACCESSIONS} accessions",
            [],
        )
    return parse_accession_list(filename, content)


def accession_text_upload_requires_validation(filename: str) -> bool:
    lower = filename.lower()
    return filename == MANUAL_ACCESSIONS_FILENAME or (lower.endswith(".txt") and "accession" in lower)


def upload_requires_data_use_acknowledgment(
    item: dict[str, object],
    *,
    generated_ecology_metadata_is_ncbi_only: bool = False,
) -> bool:
    """Return whether a real user-added file needs the public-data acknowledgment.

    The browser-generated accession list is already constrained to public NCBI
    assembly identifiers. Its ecology sidecar is exempt only after the public
    upload validator has proven that every row is the browser-generated shape
    and maps exactly to those identifiers.
    """

    filename = Path(str(item.get("filename") or "unknown")).name
    if filename == MANUAL_ACCESSIONS_FILENAME:
        return False
    if (
        filename == PUBLIC_ECOLOGY_METADATA_FILENAME
        and generated_ecology_metadata_is_ncbi_only
    ):
        return False
    return True


def validate_generated_ecology_metadata_upload(
    item: dict[str, object],
    *,
    accessions: list[str],
    genome_stems: list[str],
) -> tuple[str | None, bool]:
    """Validate the exact bounded TSV emitted by metadataProfileText.

    Returns (error, ncbi_only). ncbi_only is true only when the validated rows
    map exactly to NCBI-panel accessions and no uploaded genome rows are present,
    which is the sole ecology-sidecar consent exemption.
    """

    filename = PUBLIC_ECOLOGY_METADATA_FILENAME
    with open_upload_binary(item) as handle:
        content = handle.read(PUBLIC_GENERATED_ECOLOGY_MAX_BYTES + 1)
    if len(content) > PUBLIC_GENERATED_ECOLOGY_MAX_BYTES:
        return f"Generated ecology metadata '{filename}' exceeds 64 KiB", False
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return f"Generated ecology metadata '{filename}' must be UTF-8 text", False

    lines = text.splitlines()
    if not lines:
        return f"Generated ecology metadata '{filename}' is empty", False
    header = tuple(lines[0].split("\t"))
    if header != PUBLIC_GENERATED_ECOLOGY_FIELDS:
        return (
            f"Generated ecology metadata '{filename}' has an invalid header; "
            "use the ecology labels created by this Input Station",
            False,
        )

    expected_accessions = {value.upper() for value in accessions}
    expected_genomes = set(genome_stems)
    seen_accessions: set[str] = set()
    seen_genomes: set[str] = set()
    maximum_rows = MAX_ACCESSIONS + MAX_GENOME_FILES
    data_lines = lines[1:]
    if not data_lines or len(data_lines) > maximum_rows:
        return (
            f"Generated ecology metadata '{filename}' must contain one row per submitted genome",
            False,
        )

    for line_number, line in enumerate(data_lines, start=2):
        if not line:
            return f"Generated ecology metadata '{filename}' has a blank row at line {line_number}", False
        fields = line.split("\t")
        if len(fields) != len(PUBLIC_GENERATED_ECOLOGY_FIELDS):
            return (
                f"Generated ecology metadata '{filename}' line {line_number} must contain "
                f"{len(PUBLIC_GENERATED_ECOLOGY_FIELDS)} tab-separated columns",
                False,
            )
        if any(value != value.strip() for value in fields):
            return f"Generated ecology metadata '{filename}' line {line_number} has padded values", False

        accession, genome_id, taxonomy_id, genome_size, original_id, primary, secondary = fields
        if taxonomy_id or genome_size or original_id:
            return (
                f"Generated ecology metadata '{filename}' line {line_number} contains fields "
                "that are not created by this Input Station",
                False,
            )
        for label in (primary, secondary):
            if len(label) > PUBLIC_GENERATED_ECOLOGY_LABEL_MAX_CHARS or any(
                ord(character) < 32 for character in label
            ):
                return (
                    f"Generated ecology metadata '{filename}' line {line_number} has an invalid ecology label",
                    False,
                )

        if accession:
            normalized_accession = accession.upper()
            if (
                not NCBI_ASSEMBLY_ACCESSION_RE.fullmatch(accession)
                or normalized_accession not in expected_accessions
                or genome_id != normalized_accession
                or normalized_accession in seen_accessions
            ):
                return (
                    f"Generated ecology metadata '{filename}' line {line_number} does not map "
                    "to exactly one submitted NCBI accession",
                    False,
                )
            seen_accessions.add(normalized_accession)
            continue

        if not genome_id or genome_id not in expected_genomes or genome_id in seen_genomes:
            return (
                f"Generated ecology metadata '{filename}' line {line_number} does not map "
                "to exactly one submitted genome file",
                False,
            )
        seen_genomes.add(genome_id)

    if seen_accessions != expected_accessions or seen_genomes != expected_genomes:
        return (
            f"Generated ecology metadata '{filename}' must contain exactly one row per submitted genome",
            False,
        )
    return None, bool(expected_accessions and not expected_genomes)


def validate_manual_accession_uploads(uploads: list[dict[str, object]]) -> str | None:
    for item in uploads:
        filename = Path(str(item.get("filename") or "unknown")).name
        if not accession_text_upload_requires_validation(filename):
            continue
        error, _ = parse_accession_upload(filename, item)
        if error:
            return error
    return None


def fetch_ncbi_datasets_json(path: str) -> dict[str, object]:
    url = f"{NCBI_DATASETS_API_BASE}/{path.lstrip('/')}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ClusterWeave accession preflight",
        },
    )
    with urllib.request.urlopen(request, timeout=NCBI_PREFLIGHT_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def ncbi_preflight_unavailable(accession: str) -> str:
    return (
        f"NCBI Datasets could not verify accession '{accession}' before job creation. "
        "Try again later, or upload a supported genome FASTA/GenBank file instead."
    )


def taxonomy_rank_node(taxonomy: dict[str, object], rank: str) -> object:
    classification = taxonomy.get("classification")
    if isinstance(classification, dict):
        node = classification.get(rank) or classification.get(rank.lower()) or classification.get(rank.upper())
        if node is not None:
            return node

    lineage = taxonomy.get("lineage")
    if isinstance(lineage, list):
        for node in lineage:
            if not isinstance(node, dict):
                continue
            if str(node.get("rank") or "").lower() != rank.lower():
                continue
            return node
    return None


def taxonomy_rank_name(taxonomy: dict[str, object], rank: str) -> str:
    node = taxonomy_rank_node(taxonomy, rank)
    if isinstance(node, dict):
        return str(node.get("name") or node.get("scientific_name") or "").strip()
    if isinstance(node, str):
        return node.strip()
    return ""


def taxonomy_rank_id(taxonomy: dict[str, object], rank: str) -> int | None:
    node = taxonomy_rank_node(taxonomy, rank)
    raw_id = node.get("id", node.get("tax_id")) if isinstance(node, dict) else None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def bounded_taxonomy_name(value: object, limit: int = MAX_TAXONOMY_NAME_CHARS) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip().strip(";")
    return text[:limit]


def safe_ncbi_genome_id(value: object) -> str:
    text = bounded_taxonomy_name(value, 240).replace(" ", "_")
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._-")
    return text[:120]


def ncbi_infraspecific_label(report: dict[str, object], organism_name: str) -> str:
    organism = report.get("organism")
    sources = [organism, report] if isinstance(organism, dict) else [report]
    preferred: dict[str, str] = {"strain": "", "isolate": ""}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for direct_key in ("strain", "isolate"):
            if not preferred[direct_key]:
                preferred[direct_key] = bounded_taxonomy_name(source.get(direct_key))
        infra = source.get("infraspecific_names") or source.get("infraspecificNames")
        entries = [infra] if isinstance(infra, dict) else infra if isinstance(infra, list) else []
        for item in entries:
            if not isinstance(item, dict):
                continue
            for direct_key in ("strain", "isolate"):
                direct_value = bounded_taxonomy_name(item.get(direct_key))
                if direct_value and not preferred[direct_key]:
                    preferred[direct_key] = direct_value
            category = str(
                item.get("class") or item.get("name_class") or item.get("nameClass") or item.get("type") or ""
            ).strip().lower()
            name = bounded_taxonomy_name(
                item.get("name") or item.get("value") or item.get("text")
            )
            if category in preferred and name and not preferred[category]:
                preferred[category] = name

    for category in ("strain", "isolate"):
        if preferred[category]:
            continue
        match = re.search(
            rf"\b{category}\b[:\s]+([A-Za-z0-9._-]+)",
            organism_name,
            flags=re.I,
        )
        if match:
            preferred[category] = match.group(1)
    return preferred["strain"] or preferred["isolate"]


def ncbi_route_genome_id(
    organism_name: str,
    taxon_group: str,
    report: dict[str, object],
    accession: str,
) -> str:
    words = bounded_taxonomy_name(organism_name).split()
    genus = words[0] if words else "UnknownGenus"
    species = words[1] if len(words) >= 2 else "sp"
    tag = ncbi_infraspecific_label(report, organism_name)
    identifier = safe_ncbi_genome_id(
        "_".join(part for part in [genus, species, tag] if part)
    )
    if not identifier:
        identifier = safe_ncbi_genome_id(accession) or "genome"
    return identifier


def taxonomy_lineage_name_values(value: object) -> list[str]:
    raw_values: list[object]
    if isinstance(value, list):
        raw_values = value
    elif value:
        raw_values = re.split(r"[;|]", str(value))
    else:
        raw_values = []

    names: list[str] = []
    seen: set[str] = set()
    total_chars = 0
    for raw_value in raw_values:
        candidate: object = raw_value
        if isinstance(raw_value, dict):
            candidate = raw_value.get("name") or raw_value.get("scientific_name") or ""
        elif isinstance(raw_value, (int, float)):
            continue
        name = bounded_taxonomy_name(candidate).rstrip(".")
        key = name.casefold()
        if not name or key in seen:
            continue
        projected = total_chars + len(name) + (1 if names else 0)
        if projected > MAX_TAXONOMY_LINEAGE_CHARS:
            break
        names.append(name)
        seen.add(key)
        total_chars = projected
        if len(names) >= MAX_TAXONOMY_LINEAGE_NAMES:
            break
    return names


def taxonomy_lineage_id_values(taxonomy: dict[str, object]) -> list[int]:
    values: list[object] = []
    for key in ("parents", "lineage"):
        raw = taxonomy.get(key)
        if isinstance(raw, list):
            values.extend(raw)
    classification = taxonomy.get("classification")
    if isinstance(classification, dict):
        values.extend(classification.values())
    values.append(taxonomy.get("tax_id"))

    ids: list[int] = []
    seen: set[int] = set()
    for item in values:
        raw_id: object = item
        if isinstance(item, dict):
            raw_id = item.get("id", item.get("tax_id"))
        try:
            tax_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if tax_id <= 0 or tax_id in seen:
            continue
        ids.append(tax_id)
        seen.add(tax_id)
    return ids


def ncbi_taxonomy_rank_metadata(
    taxonomy: dict[str, object], taxon_group: str
) -> dict[str, str]:
    ranks = {
        rank: bounded_taxonomy_name(taxonomy_rank_name(taxonomy, rank))
        for rank in TAXONOMY_RANK_FIELDS
    }
    if not ranks["domain"]:
        ranks["domain"] = bounded_taxonomy_name(
            taxonomy_rank_name(taxonomy, "superkingdom")
        )

    lineage_ids = taxonomy_lineage_ids(taxonomy)
    if not ranks["domain"]:
        if taxon_group == "bacteria" and NCBI_BACTERIAL_TAXON_ID in lineage_ids:
            ranks["domain"] = "Bacteria"
        elif taxon_group == "fungi" and 2759 in lineage_ids:
            ranks["domain"] = "Eukaryota"
    if not ranks["kingdom"] and taxon_group == "fungi" and NCBI_FUNGAL_TAXON_ID in lineage_ids:
        ranks["kingdom"] = "Fungi"

    ranked_names = [ranks[rank] for rank in TAXONOMY_RANK_FIELDS if ranks[rank]]
    ranked_ids = [
        taxonomy_rank_id(taxonomy, rank)
        for rank in TAXONOMY_RANK_FIELDS
        if ranks[rank]
    ]
    named_lineage = taxonomy_lineage_name_values(taxonomy.get("lineage"))
    lineage_names = ranked_names if len(ranked_names) >= 2 else named_lineage or ranked_names
    ranks["lineage_names"] = "|".join(taxonomy_lineage_name_values(lineage_names))
    ranks["lineage_ids"] = "|".join(str(value) for value in ranked_ids if value is not None)
    return ranks


def build_taxonomy_metadata(
    routes: list[dict[str, object]],
    accession_metadata: list[dict[str, object]],
    grouped_inputs: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    """Build bounded server-derived taxonomy rows without changing route fields."""

    if len(routes) > MAX_TAXONOMY_METADATA_ROWS:
        raise TaxonRoutingError(
            f"Taxonomy metadata exceeds the {MAX_TAXONOMY_METADATA_ROWS}-genome limit"
        )
    accessions_by_key = {
        str(row.get("accession") or "").casefold(): row
        for row in accession_metadata
        if str(row.get("accession") or "").strip()
    }
    rows: list[dict[str, object]] = []
    for route in routes:
        input_key = bounded_taxonomy_name(route.get("input_key"), 120)
        taxon_source = str(route.get("taxon_source") or "")
        source_accession = bounded_taxonomy_name(route.get("source_accession"), 120)
        source: dict[str, object] | None = None
        ranks = {rank: "" for rank in TAXONOMY_RANK_FIELDS}
        lineage_names: list[str] = []
        lineage_ids = ""

        if taxon_source == "ncbi":
            source = accessions_by_key.get((source_accession or input_key).casefold())
            if source is None:
                continue
            for rank in TAXONOMY_RANK_FIELDS:
                ranks[rank] = bounded_taxonomy_name(source.get(rank))
            lineage_names = taxonomy_lineage_name_values(source.get("lineage_names"))
            lineage_ids = "|".join(
                str(value)
                for value in re.findall(r"\d+", str(source.get("lineage_ids") or ""))[:MAX_TAXONOMY_LINEAGE_NAMES]
            )
        elif taxon_source == "genbank_source":
            grouped = grouped_inputs.get(input_key.casefold())
            authority = grouped.get("authoritative_taxonomy") if grouped else None
            if not isinstance(authority, dict):
                continue
            source = authority
            lineage_names = taxonomy_lineage_name_values(authority.get("lineage"))
            lowered = {name.casefold(): name for name in lineage_names}
            if "bacteria" in lowered:
                ranks["domain"] = lowered["bacteria"]
            elif "eukaryota" in lowered:
                ranks["domain"] = lowered["eukaryota"]
            if "fungi" in lowered:
                ranks["kingdom"] = lowered["fungi"]
        else:
            # A declaration supplies a domain route, not a resolved lineage.
            continue

        try:
            taxid = int(route.get("taxid")) if route.get("taxid") not in {None, ""} else None
        except (TypeError, ValueError):
            taxid = None
        row: dict[str, object] = {
            "input_key": input_key,
            "source_accession": source_accession,
            "taxid": taxid,
            "organism_name": bounded_taxonomy_name(
                source.get("organism_name") or route.get("organism_name")
            ),
            "taxon_group": str(route.get("taxon_group") or ""),
            "taxon_source": taxon_source,
            **ranks,
            "lineage_names": "|".join(taxonomy_lineage_name_values(lineage_names)),
            "lineage_ids": lineage_ids,
        }
        rows.append({field: row.get(field, "") for field in TAXONOMY_METADATA_FIELDS})
    return rows


def taxonomy_lineage_ids(taxonomy: dict[str, object]) -> set[int]:
    return set(taxonomy_lineage_id_values(taxonomy))


def taxonomy_from_dataset_payload(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    reports = payload.get("reports")
    if isinstance(reports, list) and reports and isinstance(reports[0], dict):
        taxonomy = reports[0].get("taxonomy")
        if isinstance(taxonomy, dict):
            return taxonomy
    taxonomy_nodes = payload.get("taxonomy_nodes")
    if isinstance(taxonomy_nodes, list) and taxonomy_nodes and isinstance(taxonomy_nodes[0], dict):
        taxonomy = taxonomy_nodes[0].get("taxonomy")
        if isinstance(taxonomy, dict):
            return taxonomy
    return None


def taxonomy_scientific_name(taxonomy: dict[str, object], fallback: str) -> str:
    current = taxonomy.get("current_scientific_name")
    if isinstance(current, dict):
        name = bounded_taxonomy_name(current.get("name") or current.get("scientific_name"))
        if name:
            return name
    return bounded_taxonomy_name(
        taxonomy.get("organism_name") or taxonomy.get("scientific_name") or fallback
    )


def ncbi_accession_taxonomy_details(
    accession: str,
) -> tuple[str | None, dict[str, object] | None]:
    quoted_accession = urllib.parse.quote(accession, safe="")
    try:
        report_payload = fetch_ncbi_datasets_json(f"genome/accession/{quoted_accession}/dataset_report")
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return ncbi_preflight_unavailable(accession), None

    reports = report_payload.get("reports") if isinstance(report_payload, dict) else None
    if not isinstance(reports, list) or not reports:
        return (
            f"NCBI Datasets did not find assembly accession '{accession}'. "
            f"Use a current NCBI assembly accession like {NCBI_ACCESSION_EXAMPLES}.",
            None,
        )

    report = reports[0]
    if not isinstance(report, dict):
        return ncbi_preflight_unavailable(accession), None

    assembly_info = report.get("assembly_info")
    assembly_status = ""
    if isinstance(assembly_info, dict):
        assembly_status = str(assembly_info.get("assembly_status") or "")
    if assembly_status and assembly_status.lower() != "current":
        return (
            f"NCBI assembly accession '{accession}' is not current ({assembly_status}). "
            f"Use a current assembly accession like {NCBI_ACCESSION_EXAMPLES}.",
            None,
        )

    organism = report.get("organism")
    tax_id = None
    organism_name = accession
    if isinstance(organism, dict):
        organism_name = str(organism.get("organism_name") or accession)
        raw_tax_id = organism.get("tax_id")
        try:
            tax_id = int(raw_tax_id)
        except (TypeError, ValueError):
            tax_id = None
    if tax_id is None:
        return ncbi_preflight_unavailable(accession), None

    try:
        taxonomy_payload = fetch_ncbi_datasets_json(
            f"taxonomy/taxon/{tax_id}/dataset_report"
        )
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return ncbi_preflight_unavailable(accession), None

    taxonomy = taxonomy_from_dataset_payload(taxonomy_payload)
    if not isinstance(taxonomy, dict):
        return ncbi_preflight_unavailable(accession), None

    lineage_ids = taxonomy_lineage_ids(taxonomy)
    taxonomy_name = taxonomy_scientific_name(taxonomy, organism_name or accession)
    assembly_organism_name = bounded_taxonomy_name(organism_name)
    if assembly_organism_name and assembly_organism_name.casefold() != accession.casefold():
        taxonomy_name = assembly_organism_name
    if tax_id == NCBI_FUNGAL_TAXON_ID or NCBI_FUNGAL_TAXON_ID in lineage_ids:
        taxon_group = "fungi"
    elif tax_id == NCBI_BACTERIAL_TAXON_ID or NCBI_BACTERIAL_TAXON_ID in lineage_ids:
        taxon_group = "bacteria"
    else:
        taxon_group = "unsupported"

    rank_metadata = ncbi_taxonomy_rank_metadata(taxonomy, taxon_group)
    genome_id = ncbi_route_genome_id(
        taxonomy_name, taxon_group, report, accession
    )
    order_name = rank_metadata["order"]
    family_name = rank_metadata["family"]
    class_name = rank_metadata["class"]

    return None, {
        "accession": accession,
        "assembly_status": assembly_status or "current",
        "organism_name": taxonomy_name,
        "tax_id": tax_id,
        "taxon_group": taxon_group,
        "genome_id": genome_id,
        "taxa": f"NCBI taxon {tax_id} / {taxon_group}",
        "order_name": order_name,
        "family_name": family_name,
        "class_name": class_name,
        "order_family": ":".join(part for part in [order_name, family_name] if part),
        **rank_metadata,
    }


def ncbi_scope_error(
    accession: str,
    record: dict[str, object],
    analysis_scope: object,
) -> str | None:
    scope = normalize_analysis_scope(analysis_scope)
    taxon_group = str(record.get("taxon_group") or "unsupported")
    taxonomy_name = str(record.get("organism_name") or accession)
    if taxon_group in {"fungi", "bacteria"} and (
        scope == "both" or scope == taxon_group
    ):
        return None
    if scope == "fungi":
        return (
            f"NCBI accession '{accession}' is {taxonomy_name}, not a fungal assembly. "
            f"Select Bacteria or Both for bacterial inputs; supported fungal examples include {NCBI_ACCESSION_EXAMPLES}."
        )
    if scope == "bacteria":
        return (
            f"NCBI accession '{accession}' is {taxonomy_name}, not a bacterial assembly. "
            "Select Fungi or Both for fungal inputs."
        )
    return (
        f"NCBI accession '{accession}' is {taxonomy_name} with unsupported taxonomy; "
        "ClusterWeave accepts fungal and bacterial assemblies only."
    )


def ncbi_accession_acceptability_details(
    accession: str,
    analysis_scope: object = "fungi",
) -> tuple[str | None, dict[str, object] | None]:
    error, record = ncbi_accession_taxonomy_details(accession)
    if error or record is None:
        return error, None
    scope_error = ncbi_scope_error(accession, record, analysis_scope)
    return (scope_error, None) if scope_error else (None, record)


def ncbi_accession_acceptability_error(
    accession: str, analysis_scope: object = "fungi"
) -> str | None:
    error, _ = ncbi_accession_acceptability_details(accession, analysis_scope)
    return error


def validate_ncbi_accession_preflight_details(
    accessions: list[str],
    analysis_scope: object = "fungi",
    *,
    force: bool = False,
) -> tuple[str | None, list[dict[str, object]]]:
    if not NCBI_ACCESSION_PREFLIGHT and not force:
        return None, []
    seen: set[str] = set()
    metadata: list[dict[str, object]] = []
    for accession in accessions:
        normalized = accession.strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        error, record = ncbi_accession_acceptability_details(
            normalized, analysis_scope
        )
        if error:
            return error, []
        if record:
            metadata.append(record)
    return None, metadata


def validate_ncbi_accession_preflight(
    accessions: list[str], analysis_scope: object = "fungi"
) -> str | None:
    error, _ = validate_ncbi_accession_preflight_details(
        accessions, analysis_scope
    )
    return error


def public_genome_stem(filename: str) -> str:
    return Path(filename).stem.strip()


def validate_public_genome_stem(filename: str, seen_stems: set[str]) -> tuple[str | None, str]:
    stem = public_genome_stem(filename)
    if not stem:
        return f"Genome file '{filename}' needs a filename stem before the extension", stem
    if not PUBLIC_GENOME_STEM_RE.match(stem):
        return (
            f"Genome file '{filename}' must use a simple stem with 1-120 letters, numbers, dots, underscores, or hyphens; "
            "avoid spaces, parentheses, slashes, and shell-like characters",
            stem,
        )
    normalized = stem.lower()
    if normalized in seen_stems:
        return f"Genome file stem '{stem}' is duplicated; use one unique genome assembly stem per file", stem
    seen_stems.add(normalized)
    return None, stem


def classify_public_fasta_stream(filename: str, handle: object) -> tuple[str, str]:
    first_content_seen = False
    sequence_lines = 0
    sequence_char_count = 0
    nucleotide_count = 0
    line_kind = ""
    line_has_sequence = False
    decoder = codecs.getincrementaldecoder("utf-8")("strict")

    def finish_line() -> None:
        nonlocal sequence_lines, line_kind, line_has_sequence
        if line_kind == "sequence" and line_has_sequence:
            sequence_lines += 1
        line_kind = ""
        line_has_sequence = False

    try:
        while True:
            raw = handle.read(UPLOAD_COPY_CHUNK_BYTES)  # type: ignore[attr-defined]
            text = decoder.decode(raw, final=not raw)
            for char in text:
                if char in "\r\n":
                    finish_line()
                    continue
                if char.isspace():
                    continue
                if not line_kind:
                    if not first_content_seen:
                        first_content_seen = True
                        if char != ">":
                            return (
                                "invalid",
                                f"FASTA genome '{filename}' must start with a FASTA header line beginning with >",
                            )
                    line_kind = "header" if char == ">" else "sequence"
                if line_kind == "sequence":
                    line_has_sequence = True
                    sequence_char_count += 1
                    if char.upper() in PUBLIC_NUCLEOTIDE_CHARS:
                        nucleotide_count += 1
            if not raw:
                break
    except UnicodeDecodeError:
        return "invalid", f"FASTA genome '{filename}' must be UTF-8 compatible text"
    finish_line()

    if not first_content_seen:
        return "invalid", f"FASTA genome '{filename}' is empty"

    if sequence_lines == 0 or sequence_char_count == 0:
        return "invalid", f"FASTA genome '{filename}' must include at least one nucleotide sequence line"

    nucleotide_ratio = nucleotide_count / sequence_char_count
    if nucleotide_ratio < 0.85:
        return (
            "invalid",
            f"FASTA genome '{filename}' looks like protein FASTA or arbitrary text; upload a nucleotide genome assembly FASTA",
        )

    return (
        "raw_fasta_requires_annotation",
        "Nucleotide FASTA accepted; funannotate must predict CDS/protein translations before downstream BGC tools can run, and may fail if the assembly is not annotatable",
    )


def classify_public_fasta(filename: str, content: bytes) -> tuple[str, str]:
    with io.BytesIO(content) as handle:
        return classify_public_fasta_stream(filename, handle)


def classify_public_genbank_stream(filename: str, handle: object) -> tuple[str, str]:
    readiness = inspect_genbank_translation_stream(handle)
    if not readiness.utf8_valid:
        return "invalid", f"GenBank genome '{filename}' must be UTF-8 compatible text"
    if readiness.record_count == 0 and readiness.cds_total == 0:
        return "invalid", f"GenBank genome '{filename}' is empty"
    required_markers = {
        "LOCUS": readiness.has_locus,
        "FEATURES": readiness.has_features,
        "ORIGIN": readiness.has_origin,
        "//": readiness.last_record_terminated
        and readiness.terminator_count == readiness.record_count,
    }
    missing = [name for name, present in required_markers.items() if not present]
    if missing:
        return "invalid", f"GenBank genome '{filename}' is missing required marker(s): {', '.join(missing)}"
    if readiness.usable_translated_cds:
        return "annotated_genbank_ready", "Annotated GenBank with CDS translations is ready for antiSMASH and FunBGCeX"
    return (
        "genbank_requires_fallback_or_translations",
        "GenBank structure is present, but it lacks complete non-empty CDS translations; submit a same-stem nucleotide FASTA or translated GenBank so funannotate can produce proteins before downstream BGC tools run",
    )


def classify_public_genbank(filename: str, content: bytes) -> tuple[str, str]:
    with io.BytesIO(content) as handle:
        return classify_public_genbank_stream(filename, handle)


def public_genome_upload_kind(ext: str) -> str:
    return "fasta" if ext in PUBLIC_FASTA_EXTENSIONS else "genbank"


def classify_public_genome_upload(filename: str, ext: str, content: bytes) -> tuple[str, str]:
    if ext in PUBLIC_FASTA_EXTENSIONS:
        return classify_public_fasta(filename, content)
    if ext in PUBLIC_GENBANK_EXTENSIONS:
        return classify_public_genbank(filename, content)
    return "invalid", f"Unsupported public genome file type '{ext}'"


def classify_public_genome_upload_item(
    filename: str, ext: str, item: dict[str, object]
) -> tuple[str, str]:
    with open_upload_binary(item) as handle:
        if ext in PUBLIC_FASTA_EXTENSIONS:
            return classify_public_fasta_stream(filename, handle)
        if ext in PUBLIC_GENBANK_EXTENSIONS:
            return classify_public_genbank_stream(filename, handle)
    return "invalid", f"Unsupported public genome file type '{ext}'"


def validate_public_uploads(
    uploads: list[dict[str, object]],
    settings: dict[str, object],
    *,
    accession_preflight: bool = False,
) -> tuple[str | None, dict[str, object]]:
    readiness_records: list[dict[str, str]] = []
    summary: dict[str, object] = {
        "accession_count": 0,
        "genome_file_count": 0,
        "metadata_file_count": 0,
        "upload_bytes": 0,
        "genome_readiness": readiness_records,
    }
    max_file_bytes = MAX_UPLOAD_FILE_MB * BYTES_PER_MB
    max_total_bytes = MAX_UPLOAD_TOTAL_MB * BYTES_PER_MB
    analysis_scope = normalize_analysis_scope(settings.get("analysis_scope"))
    ecology_enabled = settings_bool(settings, "run_ecology_analysis")
    genome_stem_kinds: dict[str, set[str]] = {}
    genome_stem_labels: dict[str, str] = {}
    accession_file_count = 0
    assignment_file_count = 0
    accessions_for_preflight: list[str] = []
    ecology_metadata_items: list[dict[str, object]] = []

    for item in uploads:
        raw_filename = str(item.get("filename") or "unknown")
        ext = Path(raw_filename).suffix.lower()
        filename = Path(raw_filename).name
        size = upload_size(item)

        if ext in PUBLIC_GENOME_EXTENSIONS and ("/" in raw_filename or "\\" in raw_filename):
            return f"Genome file '{filename}' must use a simple stem without folders or slashes", summary

        if size > max_file_bytes:
            return f"File '{filename}' exceeds the {MAX_UPLOAD_FILE_MB} MB public upload limit", summary

        summary["upload_bytes"] = int(summary["upload_bytes"]) + size
        if int(summary["upload_bytes"]) > max_total_bytes:
            return f"Total upload size exceeds the {MAX_UPLOAD_TOTAL_MB} MB public job limit", summary

        if ext in PUBLIC_GENOME_EXTENSIONS:
            summary["genome_file_count"] = int(summary["genome_file_count"]) + 1
            if int(summary["genome_file_count"]) > MAX_GENOME_FILES:
                return f"Public jobs may include at most {MAX_GENOME_FILES} genome files", summary
            stem_error, stem = validate_public_genome_stem(filename, set())
            if stem_error:
                return stem_error, summary
            stem_key = stem.lower()
            genome_stem_labels.setdefault(stem_key, stem)
            upload_kind = public_genome_upload_kind(ext)
            stem_kinds = genome_stem_kinds.setdefault(stem_key, set())
            if upload_kind in stem_kinds:
                return (
                    f"Genome file stem '{stem}' has duplicate {upload_kind.upper()} uploads; submit at most one FASTA and one GenBank file per genome assembly stem",
                    summary,
                )
            stem_kinds.add(upload_kind)
            readiness_class, reason = classify_public_genome_upload_item(
                filename, ext, item
            )
            readiness_records.append(
                {
                    "filename": filename,
                    "stem": stem,
                    "readiness": readiness_class,
                    "reason": reason,
                }
            )
            if readiness_class == "invalid":
                return reason, summary
            continue

        if ext in PUBLIC_ACCESSION_EXTENSIONS:
            accession_file_count += 1
            if accession_file_count > 1:
                return "Public jobs accept one accession list; combine NCBI assembly accessions into a single .txt file or the manual entry", summary
            error, accessions = parse_accession_upload(filename, item)
            if error:
                return error, summary
            summary["accession_count"] = int(summary["accession_count"]) + len(accessions)
            if int(summary["accession_count"]) > MAX_ACCESSIONS:
                return f"Public jobs may include at most {MAX_ACCESSIONS} accessions", summary
            accessions_for_preflight.extend(accessions)
            continue

        if filename == PUBLIC_TAXON_ASSIGNMENTS_FILENAME:
            assignment_file_count += 1
            if assignment_file_count > 1:
                return "Only one taxon_assignments.tsv sidecar may be submitted", summary
            summary["taxon_assignment_file_count"] = assignment_file_count
            continue

        if filename == PUBLIC_ECOLOGY_METADATA_FILENAME:
            if not ecology_enabled:
                return "Ecology metadata is only accepted when ecology-aware analysis is enabled", summary
            summary["metadata_file_count"] = int(summary["metadata_file_count"]) + 1
            if int(summary["metadata_file_count"]) > 1:
                return "Only one ecology metadata table may be submitted", summary
            ecology_metadata_items.append(item)
            continue

        if ext in {".tsv", ".csv"}:
            return "Public accession tables in TSV/CSV format are not supported yet; upload one accession per line as .txt", summary

        return (
            f"Unsupported public file type '{ext}'. Allowed: .txt accession lists, "
            ".fasta/.fa/.fna/.fsa/.gb/.gbk/.gbff genomes, exact taxon_assignments.tsv, "
            "and generated ecology metadata",
            summary,
        )

    if int(summary["accession_count"]) + int(summary["genome_file_count"]) <= 0:
        return "Submit at least one accession list or genome file", summary

    if ecology_metadata_items:
        metadata_error, ncbi_only = validate_generated_ecology_metadata_upload(
            ecology_metadata_items[0],
            accessions=accessions_for_preflight,
            genome_stems=list(genome_stem_labels.values()),
        )
        if metadata_error:
            return metadata_error, summary
        # Internal request-policy state; removed before the input summary is
        # persisted or returned to a client.
        summary["_generated_ecology_metadata_is_ncbi_only"] = ncbi_only

    for record in readiness_records:
        if record.get("readiness") != "genbank_requires_fallback_or_translations":
            continue
        if analysis_scope != "fungi":
            # Bacterial GenBank is intentionally sanitized to sequence-only input
            # and routed through Prodigal. Mixed-mode fungal applicability is
            # checked after authoritative taxonomy/assignments are resolved.
            continue
        stem = record.get("stem", "")
        stem_key = stem.lower()
        if "fasta" not in genome_stem_kinds.get(stem_key, set()):
            filename = record.get("filename") or f"{genome_stem_labels.get(stem_key, stem)}.gbk"
            return (
                f"GenBank genome '{filename}' lacks CDS translations and no same-stem nucleotide FASTA was submitted; upload translated GenBank or pair it with {stem}.fna so funannotate can create proteins before downstream BGC tools",
                summary,
            )

    if accession_preflight:
        ncbi_error, accession_metadata = validate_ncbi_accession_preflight_details(
            accessions_for_preflight, analysis_scope
        )
        if ncbi_error:
            return ncbi_error, summary
        if accession_metadata:
            summary["accession_metadata"] = accession_metadata

    return None, summary


def taxon_assignment_form_value(
    fields: dict[str, list[str]],
) -> tuple[str | None, str]:
    supplied: list[str] = []
    for key in ("taxon_assignments", "taxon_assignments_json"):
        values = [str(value) for value in fields.get(key, []) if str(value).strip()]
        if len(values) > 1:
            return f"Submit {key} only once", ""
        supplied.extend(values)
    if len(supplied) > 1:
        return (
            "Submit taxon assignments in one JSON form field or one taxon_assignments.tsv sidecar, not duplicate JSON fields",
            "",
        )
    return None, supplied[0] if supplied else ""


def read_taxon_assignment_sidecar(
    uploads: list[dict[str, object]],
) -> tuple[str | None, dict[str, str]]:
    matches = [
        item
        for item in uploads
        if Path(str(item.get("filename") or "")).name
        == PUBLIC_TAXON_ASSIGNMENTS_FILENAME
    ]
    if len(matches) > 1:
        return "Only one taxon_assignments.tsv sidecar may be submitted", {}
    if not matches:
        return None, {}
    with open_upload_binary(matches[0]) as handle:
        content = handle.read(MAX_ASSIGNMENT_BYTES + 1)
    try:
        return None, parse_assignment_tsv(content)
    except TaxonRoutingError as exc:
        return str(exc), {}


def submission_accessions(
    uploads: list[dict[str, object]],
) -> tuple[str | None, list[str]]:
    accessions: list[str] = []
    for item in uploads:
        raw_filename = str(item.get("filename") or "")
        filename = Path(raw_filename).name
        if filename in {
            PUBLIC_TAXON_ASSIGNMENTS_FILENAME,
            PUBLIC_ECOLOGY_METADATA_FILENAME,
        }:
            continue
        ext = Path(filename).suffix.lower()
        candidate_extensions = (
            PUBLIC_ACCESSION_EXTENSIONS
            if PUBLIC_MODE
            else PUBLIC_ACCESSION_EXTENSIONS | {".tsv", ".csv"}
        )
        if ext not in candidate_extensions:
            continue
        error, parsed = parse_accession_upload(filename, item)
        if error:
            if (
                PUBLIC_MODE
                or accession_text_upload_requires_validation(filename)
                or "accession" in filename.lower()
            ):
                return error, []
            continue
        if parsed:
            accessions.extend(parsed)
    return None, accessions


def safe_logical_input_key(filename: str) -> str:
    stem = public_genome_stem(filename)
    safe = PUBLIC_ACTIVITY_TOKEN_RE.sub("_", stem).strip("._-")
    return (safe or "genome")[:120]


def logical_taxon_inputs(
    uploads: list[dict[str, object]],
    input_summary: dict[str, object],
) -> tuple[str | None, list[dict[str, object]], dict[str, dict[str, object]]]:
    readiness_by_filename = {
        str(item.get("filename") or ""): str(item.get("readiness") or "")
        for item in input_summary.get("genome_readiness", [])
        if isinstance(item, dict)
    }
    grouped: dict[str, dict[str, object]] = {}
    for item in uploads:
        filename = Path(str(item.get("filename") or "")).name
        ext = Path(filename).suffix.lower()
        if ext not in PUBLIC_GENOME_EXTENSIONS:
            continue
        input_key = safe_logical_input_key(filename)
        normalized = input_key.casefold()
        group = grouped.setdefault(
            normalized,
            {
                "input_key": input_key,
                "raw_stem": public_genome_stem(filename),
                "has_fasta": False,
                "has_annotated_genbank": False,
                "needs_fungal_fallback": False,
                "authoritative_taxonomy": None,
            },
        )
        if str(group.get("raw_stem") or "").casefold() != public_genome_stem(
            filename
        ).casefold():
            return (
                f"Genome filenames collapse to the same safe input_key '{input_key}'",
                [],
                {},
            )
        if ext in PUBLIC_FASTA_EXTENSIONS:
            group["has_fasta"] = True
            continue

        readiness = readiness_by_filename.get(filename, "")
        if readiness == "annotated_genbank_ready":
            group["has_annotated_genbank"] = True
        if readiness == "genbank_requires_fallback_or_translations":
            group["needs_fungal_fallback"] = True
        try:
            with open_upload_binary(item) as handle:
                authority = parse_genbank_taxonomy_stream(handle)
        except TaxonRoutingError as exc:
            return f"GenBank input '{input_key}': {exc}", [], {}
        if authority is None:
            continue
        previous = group.get("authoritative_taxonomy")
        if isinstance(previous, dict) and previous.get("taxon_group") != authority.get(
            "taxon_group"
        ):
            return (
                f"Same-stem GenBank inputs for '{input_key}' contain conflicting authoritative taxonomy",
                [],
                {},
            )
        group["authoritative_taxonomy"] = previous or authority

    logical_inputs = [grouped[key] for key in sorted(grouped)]
    return None, logical_inputs, grouped


def build_submission_taxon_routing(
    uploads: list[dict[str, object]],
    input_summary: dict[str, object],
    analysis_scope: object,
    assignment_json: str,
) -> tuple[str | None, dict[str, object]]:
    try:
        scope = normalize_analysis_scope(analysis_scope)
        json_assignments = parse_assignment_json(assignment_json)
    except TaxonRoutingError as exc:
        return str(exc), {}

    sidecar_error, sidecar_assignments = read_taxon_assignment_sidecar(uploads)
    if sidecar_error:
        return sidecar_error, {}
    try:
        assignments = merge_assignments(json_assignments, sidecar_assignments)
    except TaxonRoutingError as exc:
        return str(exc), {}

    accession_error, accessions = submission_accessions(uploads)
    if accession_error:
        return accession_error, {}
    metadata = input_summary.get("accession_metadata")
    accession_metadata = (
        [dict(item) for item in metadata if isinstance(item, dict)]
        if isinstance(metadata, list)
        else []
    )
    if accessions and not accession_metadata:
        ncbi_error, accession_metadata = validate_ncbi_accession_preflight_details(
            accessions, scope, force=True
        )
        if ncbi_error:
            return ncbi_error, {}

    logical_error, logical_inputs, grouped = logical_taxon_inputs(
        uploads, input_summary
    )
    if logical_error:
        return logical_error, {}
    try:
        routes = build_taxon_routes(
            scope, logical_inputs, accession_metadata, assignments
        )
        taxonomy_metadata = build_taxonomy_metadata(
            routes, accession_metadata, grouped
        )
    except TaxonRoutingError as exc:
        return str(exc), {}

    for route in routes:
        if route.get("taxon_group") != "fungi":
            continue
        grouped_input = grouped.get(str(route.get("input_key") or "").casefold())
        if not grouped_input:
            continue
        if grouped_input.get("needs_fungal_fallback") and not grouped_input.get(
            "has_fasta"
        ):
            input_key = str(route.get("input_key") or "genome")
            return (
                f"GenBank genome '{input_key}' lacks CDS translations and no same-stem nucleotide FASTA was submitted; "
                f"upload translated GenBank or pair it with {input_key}.fna so funannotate can create proteins before downstream BGC tools",
                {},
            )

    taxon_counts, applicability_counts = summarize_taxon_routes(routes)
    return None, {
        "analysis_scope": scope,
        "taxon_routes": routes,
        "taxon_counts": taxon_counts,
        "applicability_counts": applicability_counts,
        "taxonomy_metadata": taxonomy_metadata,
        "accession_metadata": accession_metadata,
        "accession_count": len(accessions),
    }


def apply_public_submission_policy(
    handler: BaseHTTPRequestHandler,
    settings: dict[str, object],
    uploads: list[dict[str, object]],
) -> tuple[str | None, dict[str, object]]:
    if not PUBLIC_MODE:
        return None, {}

    if settings_bool(settings, "run_nplinker"):
        return "NPLinker is not available in the public WebUI yet", {}

    if str(settings.get("metadata_tsv", "")).strip():
        return "Raw metadata paths are not accepted in public submissions", {}

    env_overrides = str(settings.get("env_overrides", "")).strip()
    if env_overrides and not (request_is_admin(handler) and ALLOW_ENV_OVERRIDES):
        return "Raw environment overrides are admin-only and disabled for public submissions", {}
    if not (request_is_admin(handler) and ALLOW_ENV_OVERRIDES):
        settings["env_overrides"] = ""

    return validate_public_uploads(uploads, settings, accession_preflight=not request_is_admin(handler))


def validate_runtime_request(settings: dict[str, object], status: dict[str, object]) -> str | None:
    if not status.get("ready"):
        return "Worker is not ready yet. Wait for bootstrap to finish before submitting a job."

    capabilities = status.get("capabilities")
    if not isinstance(capabilities, dict):
        return None

    stages = capabilities.get("stages")
    if not isinstance(stages, dict):
        return None

    checks = [
        ("prepare", settings_bool(settings, "run_genome_prep") and bool(settings.get("has_accession_inputs"))),
        ("annotation", settings_bool(settings, "run_annotation")),
        ("bigscape", settings_bool(settings, "run_bigscape")),
        ("clinker", settings_bool(settings, "run_clinker") and settings_bool(settings, "execute_clinker")),
        ("nplinker", settings_bool(settings, "run_nplinker")),
        ("figures", settings_bool(settings, "run_figures") and settings_bool(settings, "figures_required")),
        (
            "sequence_phylogeny",
            settings_bool(settings, "run_phylogeny")
            and settings_bool(settings, "phylogeny_required"),
        ),
    ]
    for stage, required in checks:
        if not required:
            continue
        payload = stages.get(stage)
        if isinstance(payload, dict) and not payload.get("available", False):
            return f"Selected stage unavailable: {stage}. {unavailable_stage_reason(capabilities, stage)}"
    return None


def enqueue_job(job_id: str, cpus: int, settings: dict[str, object]) -> None:
    queue_payload = {
        "job_id": job_id,
        "cpus": cpus,
        "settings": settings,
        "enqueued_at": now_iso(),
    }
    queue_file = QUEUE_DIR / f"{job_id}.json"
    atomic_write_text(queue_file, json.dumps(queue_payload))


def base_job_settings(job: dict[str, object]) -> dict[str, object]:
    submission_settings = job.get("submission_settings")
    if isinstance(submission_settings, dict):
        settings = dict(submission_settings)
    else:
        current_settings = job.get("settings")
        settings = dict(current_settings) if isinstance(current_settings, dict) else {}
    settings["analysis_scope"] = saved_job_analysis_scope(job)
    for key in ("taxon_routes", "taxon_counts", "applicability_counts"):
        if key not in settings and key in job:
            settings[key] = job[key]
    return settings


def rerun_settings(base_settings: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    settings = dict(base_settings)
    try:
        settings["analysis_scope"] = normalize_analysis_scope(
            settings.get("analysis_scope")
        )
    except TaxonRoutingError:
        settings["analysis_scope"] = "fungi"
    stage_bool_fields = [
        "run_genome_prep",
        "run_annotation",
        "run_bigscape",
        "run_summary",
        "run_crosswalk",
        "run_clinker",
        "execute_clinker",
        "run_figures",
        "run_nplinker",
        "run_phylogeny",
        "run_cross_kingdom_evidence",
    ]
    for key in stage_bool_fields:
        settings[key] = parse_payload_bool(payload, key, False) if key in payload else False
    if "run_cross_kingdom_evidence" not in payload and "run_hgt_evidence" in payload:
        settings["run_cross_kingdom_evidence"] = parse_payload_bool(
            payload, "run_hgt_evidence", False
        )
    settings.pop("run_hgt_evidence", None)


    if "phylogeny_required" in payload:
        settings["phylogeny_required"] = parse_payload_bool(
            payload, "phylogeny_required", False
        )
    phylogeny_int_fields = {
        "phylogeny_cpus": (1, 256),
        "phylogeny_max_families": (1, 100),
        "phylogeny_max_sequences_per_family": (3, 1000),
        "phylogeny_max_input_bytes": (1, 2 * 1024 * 1024 * 1024),
        "phylogeny_max_alignment_bytes": (1, 200_000_000),
        "phylogeny_timeout_seconds": (1, 86_400),
    }
    for key, (minimum, maximum) in phylogeny_int_fields.items():
        if key in payload:
            settings[key] = min(
                maximum,
                max(minimum, parse_int(str(payload.get(key, minimum)), minimum)),
            )
    # The implemented family collector is deliberately serial.
    settings["phylogeny_parallelism"] = 1

    settings["force"] = parse_payload_bool(payload, "force", False)
    settings["run_ncbi_install"] = parse_payload_bool(payload, "run_ncbi_install", False)
    settings["reuse_existing_layout"] = True
    if "run_summary" in payload and "run_crosswalk" not in payload:
        settings["run_crosswalk"] = settings["run_summary"]
    if "execute_clinker" not in payload and "run_clinker" in payload:
        settings["execute_clinker"] = settings["run_clinker"]
    scrub_web_disabled_annotation_settings(settings)
    return settings


def parse_multipart_form_data(
    content_type: str,
    stream: object,
    *,
    content_length: int,
) -> tuple[dict[str, list[str]], list[dict[str, object]]]:
    """Parse multipart/form-data with every file copied to disk in bounded chunks."""
    environ = {
        "REQUEST_METHOD": "POST",
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(content_length),
    }
    form = cgi.FieldStorage(
        fp=stream,
        headers=None,
        environ=environ,
        keep_blank_values=True,
    )

    fields: dict[str, list[str]] = {}
    files: list[dict[str, object]] = []

    try:
        for part in form.list or []:
            name = str(part.name or "").strip()
            if not name:
                continue

            if part.filename is not None:
                source = part.file if part.file is not None else io.BytesIO()
                staged_path, size = stage_multipart_upload(source)
                files.append(
                    {
                        "field": name,
                        "filename": str(part.filename),
                        "staged_path": staged_path,
                        "size": size,
                    }
                )
                continue

            if part.file is None:
                value = ""
            else:
                try:
                    part.file.seek(0)
                except OSError:
                    pass
                value = part.file.read(MULTIPART_FIELD_MAX_BYTES + 1)
                if len(value) > MULTIPART_FIELD_MAX_BYTES:
                    raise ValueError(
                        f"Multipart field {name!r} exceeds {MULTIPART_FIELD_MAX_BYTES} bytes"
                    )
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            fields.setdefault(name, []).append(str(value))
    except BaseException:
        cleanup_staged_uploads(files)
        raise

    return fields, files


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        safe_args = tuple(sanitize_access_log_text(arg) for arg in args)
        try:
            message = format % safe_args
        except (TypeError, ValueError):
            message = " ".join(safe_args)
        sys.stderr.write(
            f"{self.client_address[0]} - - [{self.log_date_time_string()}] "
            f"{sanitize_access_log_text(message)}\n"
        )

    server_version = "ClusterWeaveHTTP/2.0"

    def _send_cors_headers(self) -> None:
        origin = allowed_cors_origin(self.headers.get("Origin"))
        if not origin:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        if origin != "*":
            self.send_header("Vary", "Origin")

    def _send_json(self, status: int, payload: object) -> None:
        cleanup_staged_uploads(getattr(self, "_request_staged_uploads", []))
        data = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _send_text(
        self,
        status: int,
        content_type: str,
        body: bytes,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(
        self,
        status: int,
        full: Path,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
        expected_identity: tuple[int, int, int, int, int] | None = None,
    ) -> None:
        handle = None
        try:
            handle = (
                _open_stable_public_file(full, expected_identity)
                if expected_identity is not None
                else full.open("rb")
            )
            observed_identity = _stat_identity(os.fstat(handle.fileno()))
            if expected_identity is not None and observed_identity != expected_identity:
                raise OSError("public result changed before streaming")
        except OSError:
            if handle is not None:
                handle.close()
            if expected_identity is None:
                raise
            self._send_json(
                HTTPStatus.CONFLICT,
                {"detail": "Public result changed before streaming; retry the download."},
            )
            return
        with handle:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(observed_identity[2]))
            self._send_cors_headers()
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            try:
                shutil.copyfileobj(handle, self.wfile, length=1024 * 1024)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # A browser may cancel an inline preview or download after it
                # has inspected the authenticated headers. That is a normal
                # client disconnect, not a server-side artifact failure.
                return
            if (
                expected_identity is not None
                and _stat_identity(os.fstat(handle.fileno())) != expected_identity
            ):
                raise OSError("public result changed while streaming")

    def _not_found(self, message: str = "Not found") -> None:
        self._send_json(HTTPStatus.NOT_FOUND, {"detail": message})

    def _bad_request(self, message: str) -> None:
        self._send_json(HTTPStatus.BAD_REQUEST, {"detail": message})

    def _auth_failed(self, message: str) -> None:
        status = HTTPStatus.FORBIDDEN if request_has_any_token(self) else HTTPStatus.UNAUTHORIZED
        self._send_json(status, {"detail": message})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-ClusterWeave-Token, X-ClusterWeave-Admin-Token, "
            "X-ClusterWeave-Submit-Token, X-ClusterWeave-Read-Token",
        )
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        route, query = parse_path(self.path)
        if handle_public_result_get(self, route, query):
            return


        if route == "/":
            index = STATIC_DIR / "index.html"
            if not index.exists():
                self._not_found("Frontend not found")
                return
            self._send_text(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                index.read_bytes(),
                {"Cache-Control": "no-store"},
            )
            return

        if route == "/favicon.ico":
            favicon = STATIC_DIR / "favicon.ico"
            if not favicon.exists():
                self._not_found("Favicon not found")
                return
            self._send_file(
                HTTPStatus.OK,
                favicon,
                result_file_mime(favicon),
                {
                    "Cache-Control": "public, max-age=86400",
                    "X-Content-Type-Options": "nosniff",
                },
            )
            return

        if route.startswith("/assets/"):
            asset_root = STATIC_ASSET_DIR.resolve()
            rel_path = urllib.parse.unquote(route.removeprefix("/assets/"))
            full = (asset_root / rel_path).resolve()
            try:
                full.relative_to(asset_root)
            except ValueError:
                self._bad_request("Invalid asset path")
                return
            if not full.exists() or not full.is_file():
                self._not_found("Asset not found")
                return
            self._send_text(
                HTTPStatus.OK,
                result_file_mime(full),
                full.read_bytes(),
                {
                    "Cache-Control": "public, max-age=86400",
                    "X-Content-Type-Options": "nosniff",
                },
            )
            return

        if route.startswith("/vendor/"):
            vendor_root = STATIC_VENDOR_DIR.resolve()
            rel_path = urllib.parse.unquote(route.removeprefix("/vendor/"))
            full = (vendor_root / rel_path).resolve()
            try:
                full.relative_to(vendor_root)
            except ValueError:
                self._bad_request("Invalid vendor path")
                return
            if not full.exists() or not full.is_file():
                self._not_found("Vendor asset not found")
                return
            self._send_text(
                HTTPStatus.OK,
                result_file_mime(full),
                full.read_bytes(),
                {
                    "Cache-Control": "public, max-age=86400",
                    "X-Content-Type-Options": "nosniff",
                },
            )
            return

        if route == "/api/jobs":
            if not request_is_admin(self):
                self._auth_failed("Admin token required")
                return
            self._send_json(
                HTTPStatus.OK,
                [job_summary_payload(job) for job in list_job_summaries()],
            )
            return

        if route == "/api/access/validate":
            if not request_has_any_token(self):
                self._auth_failed("Access code required")
                return
            is_admin = request_is_admin(self)
            submit_configured = token_credential_configured(SUBMIT_TOKEN, SUBMIT_TOKEN_SHA256)
            is_submit_token = submit_configured and request_has_token(self, SUBMIT_TOKEN, SUBMIT_TOKEN_SHA256)
            can_submit = is_admin or is_submit_token
            if not (is_admin or is_submit_token):
                self._auth_failed("Access code was not accepted")
                return
            self._send_json(HTTPStatus.OK, {"accepted": True, "admin": is_admin, "submit": can_submit})
            return

        if route == "/api/system/status":
            if PUBLIC_MODE and not request_is_admin(self):
                if request_has_any_token(self):
                    self._auth_failed("Admin token required for diagnostics")
                    return
                self._send_json(HTTPStatus.OK, redacted_system_status())
                return
            self._send_json(HTTPStatus.OK, full_system_status())
            return

        if route.startswith("/api/jobs/"):
            parts = route.split("/")
            if len(parts) < 4:
                self._not_found()
                return
            if (
                PUBLIC_MODE
                and len(parts) >= 5
                and not request_is_admin(self)
            ):
                self._not_found("Result not found")
                return
            job_id = parts[3]
            job = read_job(job_id)
            if job is None:
                if PUBLIC_MODE and not request_is_admin(self):
                    self._not_found("Result not found")
                else:
                    self._not_found(f"Job '{job_id}' not found")
                return
            if not request_can_read_job(self, job):
                if PUBLIC_MODE:
                    # Keep legacy internal IDs non-enumerable. A valid read
                    # token may use this metadata endpoint only to migrate an
                    # old bookmark to the opaque public result URL; every
                    # failed public read looks identical to an unknown job.
                    self._not_found("Result not found")
                    return
                self._auth_failed("Job read token or admin token required")
                return
            is_admin = request_is_admin(self)

            if len(parts) == 4:
                self._send_json(HTTPStatus.OK, job_payload(job, admin=is_admin, include_public_events=True, include_results=not parse_bool(query.get("compact", ["0"])[0], False)))
                return

            if len(parts) == 5 and parts[4] == "bigscape-viewer-database":
                if PUBLIC_MODE and not is_admin:
                    self._not_found("Result not found")
                    return
                authorized_viewer = authorize_bigscape_viewer_database(
                    job,
                    job_dir(job_id).resolve(),
                )
                if authorized_viewer is None:
                    self._auth_failed(
                        "BiG-SCAPE viewer database is not available for this run"
                    )
                    return
                full, expected_identity = authorized_viewer
                self._send_file(
                    HTTPStatus.OK,
                    full,
                    "application/vnd.sqlite3",
                    {
                        "Content-Disposition": content_disposition(
                            "inline", PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME
                        ),
                        "Cache-Control": "private, no-store",
                        "X-Content-Type-Options": "nosniff",
                    },
                    expected_identity=expected_identity,
                )
                return

            if len(parts) >= 5 and parts[4] == "logs":
                if PUBLIC_MODE and not is_admin:
                    self._auth_failed("Admin token required for raw logs")
                    return
                known_log_count = max(0, parse_int(job.get("log_count"), 0))
                if "tail" in query or "before" in query:
                    tail_value = parse_int(query.get("tail", ["500"])[0], 500)
                    limit = min(
                        1000,
                        max(1, parse_int(query.get("limit", [str(tail_value)])[0], 500)),
                    )
                    before = (
                        max(0, parse_int(query["before"][0], 0))
                        if "before" in query
                        else None
                    )
                    window = read_log_window(
                        job_id,
                        tail=before is None,
                        before=before,
                        limit=limit,
                        minimum_total=known_log_count,
                    )
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "lines": window.lines,
                            "start": window.start,
                            "end": window.end,
                            "total": window.total,
                            "generation": window.generation,
                            "has_earlier": window.start > 0,
                        },
                    )
                    return

                since = max(0, parse_int(query.get("since", ["0"])[0], 0))
                snapshot = read_log_slice(job_id, since, known_log_count)
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "lines": snapshot.lines,
                        "total": snapshot.total,
                        "generation": snapshot.generation,
                    },
                )
                return

            if len(parts) == 5 and parts[4] == "archive":
                if PUBLIC_MODE and not is_admin:
                    self._not_found("Result not found")
                    return
                base_dir = job_dir(job_id).resolve()
                safe_job_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", job_id).strip("._") or "clusterweave"
                try:
                    archive_path = build_public_archive(job, base_dir)
                except (OSError, RuntimeError, zipfile.BadZipFile):
                    self._send_json(
                        HTTPStatus.CONFLICT,
                        {
                            "detail": (
                                "Public result files changed while the package was "
                                "prepared; retry the download."
                            )
                        },
                    )
                    return
                try:
                    self._send_file(
                        HTTPStatus.OK,
                        archive_path,
                        "application/zip",
                        {
                            "Content-Disposition": content_disposition(
                                "attachment",
                                f"{safe_job_id}_clusterweave_results.zip",
                            ),
                            "Cache-Control": "no-store",
                            "X-Content-Type-Options": "nosniff",
                        },
                    )
                finally:
                    archive_path.unlink(missing_ok=True)
                return

            if len(parts) >= 5 and parts[4] == "files":
                if PUBLIC_MODE and not is_admin:
                    self._not_found("Result not found")
                    return
                base_dir = job_dir(job_id).resolve()
                if len(parts) == 5:
                    if PUBLIC_MODE and not is_admin:
                        self._not_found("Result not found")
                        return
                    allowed_files = result_file_allowlist(job, base_dir=base_dir)
                    payload = {"files": allowed_files}
                    viewer_path = advertised_bigscape_viewer_database_path(job, base_dir, public_files=allowed_files)
                    if viewer_path:
                        payload["bigscape_viewer_database"] = viewer_path
                    payload.update(result_index_metadata(job, base_dir))
                    self._send_json(HTTPStatus.OK, payload)
                    return

                requested_path = urllib.parse.unquote("/".join(parts[5:]))
                rel_path = normalized_job_result_path(requested_path)
                if not rel_path or rel_path != requested_path:
                    self._bad_request("Invalid path")
                    return
                authorized_file = authorize_direct_result_file(job, base_dir, rel_path)
                if authorized_file is None:
                    self._auth_failed("Result file is not available through the public manifest")
                    return
                full, expected_identity = authorized_file

                disposition = "attachment" if parse_bool(query.get("download", ["0"])[0], False) else "inline"
                headers = {
                    "Content-Disposition": content_disposition(disposition, full.name),
                    "X-Content-Type-Options": "nosniff",
                }
                if result_is_generated_tool_html(rel_path):
                    # Direct navigation is a safe static fallback only. The UI
                    # fetches the same bytes and renders the complete bundle in
                    # an opaque-origin sandbox; credentials never enter HTML.
                    headers["Cache-Control"] = "private, no-store"
                    headers["Content-Security-Policy"] = (
                        "sandbox; default-src 'none'; base-uri 'none'; "
                        "form-action 'none'; frame-ancestors 'none'"
                    )
                elif result_is_public_bigscape_database(rel_path):
                    headers["Cache-Control"] = "private, no-store"
                self._send_file(
                    HTTPStatus.OK,
                    full,
                    result_file_mime(full),
                    headers,
                    expected_identity=expected_identity,
                )
                return

        self._not_found()

    def do_POST(self) -> None:  # noqa: N802
        self._request_staged_uploads: list[dict[str, object]] = []
        route, _ = parse_path(self.path)
        upload_slot = False
        if route == "/api/jobs":
            upload_slot = UPLOAD_SEMAPHORE.acquire(blocking=False)
            if not upload_slot:
                self._send_json(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    {
                        "detail": (
                            "The upload intake is busy; retry shortly while current "
                            "submissions finish staging"
                        )
                    },
                )
                return
        try:
            self._handle_post()
        finally:
            cleanup_staged_uploads(self._request_staged_uploads)
            if upload_slot:
                UPLOAD_SEMAPHORE.release()

    def _handle_post(self) -> None:
        route, _ = parse_path(self.path)
        if handle_public_result_post(self, route):
            return

        if route.startswith("/api/jobs/") and route.endswith("/rerun"):
            if not request_is_admin(self):
                self._auth_failed("Admin token required")
                return
            parts = route.split("/")
            if len(parts) != 5:
                self._not_found()
                return
            job_id = parts[3]
            job = read_job(job_id)
            if job is None:
                self._not_found(f"Job '{job_id}' not found")
                return
            if job.get("status") in {"pending", "running"}:
                self._send_json(HTTPStatus.CONFLICT, {"detail": "Job is already queued or running"})
                return

            payload = read_json_body(self)
            if payload is None:
                self._bad_request("Expected JSON object")
                return
            mutation_fields = sorted(
                key for key in payload if key in ROUTING_MUTATION_FIELDS
            )
            if mutation_fields:
                self._bad_request(
                    "Taxon routing is immutable after submission; remove rerun field(s): "
                    + ", ".join(mutation_fields)
                )
                return

            base_settings = base_job_settings(job)
            settings = rerun_settings(base_settings, payload)
            if not any(
                settings_bool(settings, key)
                for key in ["run_genome_prep", "run_annotation", "run_bigscape", "run_summary", "run_clinker", "run_figures", "run_nplinker", "run_phylogeny", "run_cross_kingdom_evidence"]
            ):
                self._bad_request("Select at least one stage to rerun")
                return
            runtime_error = validate_runtime_request(settings, worker_status())
            if runtime_error:
                self._send_json(HTTPStatus.CONFLICT, {"detail": runtime_error})
                return

            cpus = clamp_public_cpus(parse_int(str(payload.get("cpus", job.get("cpus", 4))), 4))
            if PUBLIC_MODE:
                rerun_plan = ResourceRequest.from_settings(
                    cpus,
                    settings,
                    genome_count_from_input_summary(job.get("input_summary")),
                ).bounded_plan()
                settings.update(rerun_plan.as_settings())
            append_log(job_id, "Re-queued existing job with selected stage rerun settings.")
            append_log(job_id, "Queued: waiting for worker slot.")
            lines = read_logs(job_id)
            job["status"] = "pending"
            job["stage"] = "queued"
            job["error"] = None
            job["cpus"] = cpus
            job["settings"] = settings
            if not isinstance(job.get("submission_settings"), dict):
                job["submission_settings"] = base_settings
            job["last_rerun_settings"] = settings
            job.pop("scheduler", None)
            job.pop("slurm_job_id", None)
            job.pop("executor", None)
            job["log_count"] = len(lines)
            job["updated_at"] = now_iso()
            job["rerun_count"] = int(job.get("rerun_count", 0) or 0) + 1
            write_job(job)
            enqueue_job(job_id, cpus, settings)
            self._send_json(HTTPStatus.ACCEPTED, {"job_id": job_id, "status": "pending", "message": "Rerun queued"})
            return

        if route != "/api/jobs":
            self._not_found()
            return

        if not request_can_submit(self):
            self._auth_failed("Submission access code required")
            return
        if PUBLIC_MODE and not SUBMISSIONS_OPEN and not request_is_admin(self):
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"detail": "Submissions are paused"})
            return
        if PUBLIC_MODE and queued_job_count() >= MAX_QUEUED_JOBS:
            self._send_json(HTTPStatus.TOO_MANY_REQUESTS, {"detail": "Public queue is full; try again later"})
            return

        disk_error = submission_disk_error()
        if disk_error:
            self._send_json(HTTPStatus.INSUFFICIENT_STORAGE, {"detail": disk_error})
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._bad_request("Expected multipart/form-data")
            return

        content_length = parse_int(self.headers.get("Content-Length", "0"), 0)
        if content_length <= 0:
            self._bad_request("Missing or invalid Content-Length")
            return
        maximum_body_bytes = (
            MAX_UPLOAD_TOTAL_MB + MAX_UPLOAD_BODY_OVERHEAD_MB
        ) * BYTES_PER_MB
        if content_length > maximum_body_bytes:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {
                    "detail": (
                        f"Multipart request exceeds the {MAX_UPLOAD_TOTAL_MB} MB upload "
                        "limit plus bounded form overhead"
                    )
                },
            )
            return

        try:
            fields, files = parse_multipart_form_data(
                content_type,
                self.rfile,
                content_length=content_length,
            )
        except Exception:
            self._bad_request("Could not parse multipart upload")
            return
        self._request_staged_uploads.extend(files)

        data_use_ack = parse_bool(fields.get("data_use_ack", ["0"])[0], False)

        project_name = str(fields.get("project_name", [""])[0]).strip()
        if not project_name:
            self._bad_request("Project name is required")
            return
        cpus = clamp_public_cpus(parse_int(fields.get("cpus", ["4"])[0], 4))
        notify_email = str(fields.get("notify_email", [""])[0]).strip()
        if notify_email and not SMTP_ENABLED:
            self._bad_request("Email notifications are not enabled on this ClusterWeave server")
            return
        if notify_email and not validate_email(notify_email):
            self._bad_request("Notification email address is not valid")
            return

        try:
            analysis_scope = normalize_analysis_scope(
                fields.get("analysis_scope", [""])[0]
            )
        except TaxonRoutingError as exc:
            self._bad_request(str(exc))
            return
        assignment_error, assignment_json = taxon_assignment_form_value(fields)
        if assignment_error:
            self._bad_request(assignment_error)
            return
        ecology_field = str(
            fields.get("ecology_field", ["ecofun_primary"])[0]
        ).strip()
        if analysis_scope == "bacteria" and ecology_field in {"", "ecofun_primary"}:
            ecology_field = "ecobac_primary"

        admin_request = request_is_admin(self)
        # The normal WebUI carries hidden 1/1 resource fields for local-mode
        # compatibility.  On a hosted server those fields must not silently
        # disable operator-configured fan-out.  Direct admin/API callers can
        # still request a deliberate custom shape with this explicit opt-in;
        # submit-token callers cannot override hosted resource policy.
        explicit_admin_resource_plan = admin_request and str(
            fields.get("resource_plan_mode", [""])[0]
        ).strip().lower() == "explicit"
        settings = {
            "project_name": project_name,
            "analysis_scope": analysis_scope,
            "target_genome": str(fields.get("target_genome", [""])[0]).strip(),
            "run_ncbi_install": parse_bool(fields.get("run_ncbi_install", ["0"])[0], False),
            "run_genome_prep": parse_bool(fields.get("run_genome_prep", ["1"])[0], True),
            "run_annotation": parse_bool(fields.get("run_annotation", ["1"])[0], True),
            "run_bigscape": parse_bool(fields.get("run_bigscape", ["1"])[0], True),
            "run_crosswalk": parse_bool(fields.get("run_crosswalk", ["1"])[0], True),
            "run_summary": parse_bool(fields.get("run_summary", fields.get("run_crosswalk", ["1"]))[0], True),
            "run_clinker": parse_bool(fields.get("run_clinker", ["1"])[0], True),
            "execute_clinker": parse_bool(fields.get("execute_clinker", fields.get("run_clinker", ["1"]))[0], True),
            "run_figures": parse_bool(fields.get("run_figures", ["1"])[0], True),
            "run_nplinker": parse_bool(fields.get("run_nplinker", ["0"])[0], False),
            # Optional sequence inference and terminal Cross-Kingdom evidence are
            # operator/admin-only in public mode.  Anonymous/submit-token jobs
            # cannot enable new child-runtime concurrency.
            "run_phylogeny": admin_request and parse_bool(fields.get("run_phylogeny", ["0"])[0], False),
            "phylogeny_required": admin_request and parse_bool(fields.get("phylogeny_required", ["0"])[0], False),
            "run_cross_kingdom_evidence": admin_request and parse_bool(
                fields.get(
                    "run_cross_kingdom_evidence",
                    fields.get("run_hgt_evidence", ["0"]),
                )[0],
                False,
            ),
            "phylogeny_cpus": min(cpus, max(1, parse_int(fields.get("phylogeny_cpus", ["1"])[0], 1))),
            "phylogeny_parallelism": 1,
            "phylogeny_max_families": min(100, max(1, parse_int(fields.get("phylogeny_max_families", ["10"])[0], 10))),
            "phylogeny_max_sequences_per_family": min(1000, max(3, parse_int(fields.get("phylogeny_max_sequences_per_family", ["250"])[0], 250))),
            "phylogeny_max_input_bytes": min(2 * 1024 * 1024 * 1024, max(1, parse_int(fields.get("phylogeny_max_input_bytes", ["262144000"])[0], 262_144_000))),
            "phylogeny_max_alignment_bytes": min(200_000_000, max(1, parse_int(fields.get("phylogeny_max_alignment_bytes", ["50000000"])[0], 50_000_000))),
            "phylogeny_timeout_seconds": min(86_400, max(1, parse_int(fields.get("phylogeny_timeout_seconds", ["7200"])[0], 7200))),
            "run_ecology_analysis": parse_bool(fields.get("run_ecology_analysis", ["0"])[0], False),
            "ecology_field": ecology_field,
            "focus_ecology_label": str(fields.get("focus_ecology_label", [""])[0]).strip(),
            "genefinding_mode": str(fields.get("genefinding_mode", ["auto"])[0]).strip() or "auto",
            "bigscape_mix_mode": parse_bool(fields.get("bigscape_mix_mode", ["1"])[0], True),
            "force": parse_bool(fields.get("force", ["0"])[0], False),
            "workers": max(1, parse_int(fields.get("workers", ["2"])[0], 2)),
            "genome_parallelism": max(1, parse_int(fields.get("genome_parallelism", ["1"])[0], 1)),
            "antismash_record_parallelism": max(1, parse_int(fields.get("antismash_record_parallelism", ["1"])[0], 1)),
            "antismash_shard_cpus": max(0, parse_int(fields.get("antismash_shard_cpus", ["0"])[0], 0)),
            "threads": max(1, parse_int(fields.get("threads", [str(cpus)])[0], cpus)),
            "anno_cpus": max(1, parse_int(fields.get("anno_cpus", [str(cpus)])[0], cpus)),
            "annotation_fallback_order": str(fields.get("annotation_fallback_order", ["funannotate"])[0]).strip(),
            "braker3_enabled": parse_bool(fields.get("braker3_enabled", ["0"])[0], False),
            "funannotate_busco_db": str(fields.get("funannotate_busco_db", ["dikarya"])[0]).strip(),
            "funannotate_organism_name": str(fields.get("funannotate_organism_name", ["Fungal_sp"])[0]).strip(),
            "clinker_mode": str(fields.get("clinker_mode", ["auto"])[0]).strip() or "auto",
            "panel_target_set": str(fields.get("panel_target_set", ["both"])[0]).strip() or "both",
            "clinker_use_docker_image": parse_bool(fields.get("clinker_use_docker_image", ["1"])[0], True),
            "clinker_docker_image": str(fields.get("clinker_docker_image", [""])[0]).strip(),
            "clinker_docker_data_volume": str(fields.get("clinker_docker_data_volume", [""])[0]).strip(),
            "clinker_max_regions": max(0, parse_int(fields.get("clinker_max_regions", ["20"])[0], 20)),
            "atlas_stage_limit": max(1, parse_int(fields.get("atlas_stage_limit", ["20"])[0], 20)),
            "atlas_min_records": max(1, parse_int(fields.get("atlas_min_records", ["2"])[0], 2)),
            "shortlist_limit": max(1, parse_int(fields.get("shortlist_limit", ["12"])[0], 12)),
            "shared_family_stage_limit": max(1, parse_int(fields.get("shared_family_stage_limit", fields.get("shortlist_limit", ["12"]))[0], 12)),
            "shared_family_min_records": max(1, parse_int(fields.get("shared_family_min_records", ["4"])[0], 4)),
            "max_comparators": max(1, parse_int(fields.get("max_comparators", ["50"])[0], 50)),
            "max_same_ecology": max(0, parse_int(fields.get("max_same_ecology", ["20"])[0], 20)),
            "max_other_ecology": max(0, parse_int(fields.get("max_other_ecology", ["20"])[0], 20)),
            "capture_external_artifacts": parse_bool(fields.get("capture_external_artifacts", ["1"])[0], True),
            "auto_normalize_metadata": parse_bool(fields.get("auto_normalize_metadata", ["1"])[0], True),
            "metadata_tsv": str(fields.get("metadata_tsv", [""])[0]).strip(),
            "auto_pull_images": str(fields.get("auto_pull_images", ["always"])[0]).strip() or "always",
            "auto_build_funbgcex_sif": parse_bool(fields.get("auto_build_funbgcex_sif", ["1"])[0], True),
            "auto_pull_bigscape_sif": parse_bool(fields.get("auto_pull_bigscape_sif", ["1"])[0], True),
            "auto_download_pfam": parse_bool(fields.get("auto_download_pfam", ["1"])[0], True),
            "auto_download_fasttree": parse_bool(fields.get("auto_download_fasttree", ["1"])[0], True),
            "mibig_auto_download": parse_bool(fields.get("mibig_auto_download", ["1"])[0], True),
            "nplinker_run_mode": str(fields.get("nplinker_run_mode", ["local"])[0]).strip() or "local",
            "nplinker_podp_id": str(fields.get("nplinker_podp_id", [""])[0]).strip(),
            "massive_dataset_id": str(fields.get("massive_dataset_id", [""])[0]).strip(),
            "target_strain": str(fields.get("target_strain", fields.get("target_genome", [""]))[0]).strip(),
            "gnps_version": str(fields.get("gnps_version", ["2"])[0]).strip() or "2",
            "auto_pull_nplinker_sif": parse_bool(fields.get("auto_pull_nplinker_sif", ["1"])[0], True),
            "nplinker_bootstrap_env": parse_bool(fields.get("nplinker_bootstrap_env", ["1"])[0], True),
            "figures_required": parse_bool(fields.get("figures_required", ["0"])[0], False),
            "env_overrides": str(fields.get("env_overrides", [""])[0]),
        }

        if not settings["clinker_docker_image"]:
            settings["clinker_docker_image"] = os.environ.get(
                "CLINKER_DOCKER_IMAGE", "quay.io/biocontainers/clinker-py:0.0.32--pyhdfd78af_0"
            )
        if not settings["clinker_docker_data_volume"]:
            settings["clinker_docker_data_volume"] = os.environ.get("CLINKER_DOCKER_DATA_VOLUME", "")
        if settings["genefinding_mode"] in {"funannotate", "braker3,funannotate"}:
            settings["annotation_fallback_order"] = settings["genefinding_mode"]
            if "braker3" in settings["genefinding_mode"]:
                settings["braker3_enabled"] = True
        scrub_web_disabled_annotation_settings(settings)

        web_runtime_policy_error = validate_web_runtime_policy(settings)
        if web_runtime_policy_error:
            self._bad_request(web_runtime_policy_error)
            return

        if PUBLIC_MODE:
            settings["workers"] = min(max(1, int(settings["workers"])), cpus)
            settings["genome_parallelism"] = min(max(1, int(settings["genome_parallelism"])), cpus)
            settings["threads"] = min(max(1, int(settings["threads"])), cpus)
            settings["anno_cpus"] = min(max(1, int(settings["anno_cpus"])), cpus)

        uploads = [item for item in files if item["field"] == "files"]
        if not uploads:
            self._bad_request("At least one file is required")
            return

        manual_accession_error = validate_manual_accession_uploads(uploads)
        if manual_accession_error:
            self._bad_request(manual_accession_error)
            return

        public_policy_error, input_summary = apply_public_submission_policy(self, settings, uploads)
        if public_policy_error:
            self._bad_request(public_policy_error)
            return

        input_summary = dict(input_summary or {})
        generated_ecology_metadata_is_ncbi_only = bool(
            input_summary.pop("_generated_ecology_metadata_is_ncbi_only", False)
        )
        if (
            PUBLIC_MODE
            and not request_is_admin(self)
            and any(
                upload_requires_data_use_acknowledgment(
                    item,
                    generated_ecology_metadata_is_ncbi_only=(
                        generated_ecology_metadata_is_ncbi_only
                    ),
                )
                for item in uploads
            )
            and not data_use_ack
        ):
            self._bad_request("Data-use acknowledgment is required for uploaded files")
            return

        routing_error, routing_state = build_submission_taxon_routing(
            uploads, input_summary, analysis_scope, assignment_json
        )
        if routing_error:
            self._bad_request(routing_error)
            return
        taxon_routes = list(routing_state.get("taxon_routes") or [])
        taxon_counts = dict(routing_state.get("taxon_counts") or {})
        applicability_counts = dict(
            routing_state.get("applicability_counts") or {}
        )
        taxonomy_metadata = [
            dict(row)
            for row in routing_state.get("taxonomy_metadata", [])
            if isinstance(row, dict)
        ]
        input_summary["analysis_scope"] = analysis_scope
        input_summary["taxon_counts"] = taxon_counts
        input_summary["applicability_counts"] = applicability_counts
        input_summary["genome_count"] = int(taxon_counts.get("total") or 0)
        input_summary.setdefault(
            "accession_count", int(routing_state.get("accession_count") or 0)
        )
        input_summary.setdefault(
            "genome_file_count",
            sum(
                1
                for item in uploads
                if Path(str(item.get("filename") or "")).suffix.lower()
                in PUBLIC_GENOME_EXTENSIONS
            ),
        )
        accession_metadata = routing_state.get("accession_metadata")
        if accession_metadata:
            input_summary["accession_metadata"] = accession_metadata
        settings["analysis_scope"] = analysis_scope
        settings["taxon_routes"] = taxon_routes
        settings["taxon_counts"] = taxon_counts
        settings["applicability_counts"] = applicability_counts
        settings["taxonomy_metadata"] = taxonomy_metadata
        settings["has_accession_inputs"] = bool((input_summary or {}).get("accession_count"))

        if PUBLIC_MODE and not admin_request:
            cpus = public_cpu_limit()
            run_summary = settings_bool(settings, "run_summary")
            run_clinker = settings_bool(settings, "run_clinker")
            settings.update(
                {
                    "run_ncbi_install": False,
                    "run_genome_prep": True,
                    "run_annotation": True,
                    "run_crosswalk": run_summary,
                    "execute_clinker": run_clinker,
                    "run_nplinker": False,
                    "figures_required": False,
                    "force": False,
                    "genefinding_mode": "auto",
                    "annotation_fallback_order": "funannotate",
                    "braker3_enabled": False,
                    "funannotate_busco_db": WEB_PUBLIC_FUNANNOTATE_BUSCO_DB,
                    "funannotate_organism_name": WEB_PUBLIC_FUNANNOTATE_ORGANISM_NAME,
                    "threads": cpus,
                }
            )

        if PUBLIC_MODE:
            genome_count = genome_count_from_input_summary(input_summary)
            if explicit_admin_resource_plan:
                # Explicit admin resource requests retain their requested
                # shape, but still pass through the same CPU/input bounds used
                # by worker admission and execution.
                resource_plan = ResourceRequest.from_settings(
                    cpus,
                    settings,
                    genome_count,
                ).bounded_plan()
            else:
                # Ordinary admin submissions are hosted jobs too.  Ignore the
                # browser's legacy hidden 1/1 values and apply the same
                # operator-selected default used by submit-token jobs.
                cpus = public_cpu_limit()
                settings["threads"] = cpus
                resource_plan = hosted_resource_plan(cpus, genome_count, settings)
            settings.update(resource_plan.as_settings())

        runtime_error = validate_runtime_request(settings, worker_status())
        if runtime_error:
            if PUBLIC_MODE and not request_is_admin(self):
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "detail": (
                            "Hosted analysis is temporarily unavailable while the ClusterWeave "
                            "operator restores backend runtime services."
                        )
                    },
                )
                return
            self._send_json(HTTPStatus.CONFLICT, {"detail": runtime_error})
            return

        job_id = uuid.uuid4().hex[:8]
        public_run_id = generate_public_run_id()
        created_at = now_iso()
        job = {
            "public_run_id": public_run_id,
            "id": job_id,
            "name": project_name,
            "status": "pending",
            "stage": "queued",
            "created_at": created_at,
            "updated_at": created_at,
            "log_count": 0,
            "result_files": [],
            "error": None,
            "cpus": cpus,
            "settings": settings,
            "submission_settings": dict(settings),
            "analysis_scope": analysis_scope,
            "taxon_routes": taxon_routes,
            "taxon_counts": taxon_counts,
            "applicability_counts": applicability_counts,
            "public_base_url": request_public_base_url(self),
        }
        if notify_email:
            job["notify_email"] = notify_email
        if input_summary:
            job["input_summary"] = input_summary
        read_token = attach_job_read_token(job)

        out_dir = job_dir(job_id)
        in_dir = out_dir / "inputs"
        in_dir.mkdir(parents=True, exist_ok=True)

        for item in uploads:
            filename = Path(str(item.get("filename") or "unknown")).name
            ext = Path(filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                self._bad_request(
                    f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
                )
                return

            destination = in_dir / filename
            persist_upload(item, destination)
            append_log(job_id, f"Uploaded: {filename} ({destination.stat().st_size:,} bytes)")

        append_log(job_id, "Queued: waiting for worker slot.")
        lines = read_logs(job_id)
        job["log_count"] = len(lines)
        job["updated_at"] = now_iso()
        write_job(job)

        enqueue_job(job_id, cpus, settings)
        result_url = f"{job.get('public_base_url') or request_public_base_url(self)}#/results/{public_run_id}/{read_token}"
        response_job_id = job_id if request_is_admin(self) else public_run_id

        self._send_json(
            HTTPStatus.CREATED,
            {
                "job_id": response_job_id,
                "public_run_id": public_run_id,
                "status": job["status"],
                "message": "Pipeline queued",
                "read_token": read_token,
                "result_url": result_url,
                "expires_at": job.get("expires_at"),
                "input_summary": input_summary,
            },
        )

    def do_DELETE(self) -> None:  # noqa: N802
        route, _ = parse_path(self.path)
        if not route.startswith("/api/jobs/"):
            self._not_found()
            return
        if not request_is_admin(self):
            self._auth_failed("Admin token required")
            return
        parts = route.split("/")
        if len(parts) != 4:
            self._not_found()
            return
        job_id = parts[3]

        job = read_job(job_id)
        if job is None:
            self._not_found(f"Job '{job_id}' not found")
            return

        for q in QUEUE_DIR.glob(f"{job_id}*.json"):
            q.unlink(missing_ok=True)
        for q in QUEUE_DIR.glob(f"{job_id}*.working"):
            q.unlink(missing_ok=True)

        if str(job.get("status") or "").lower() == "running" or job_needs_scheduler_cancel_before_delete(job):
            request_job_cancel(job_id, "Admin delete requested", delete_after_cancel=True)
            append_log(job_id, "Cancel requested by administrator; stopping active workflow before deleting job data.")
            job["stage"] = "cancel requested"
            job["error"] = "Cancel requested by administrator"
            job["log_count"] = len(read_logs(job_id))
            job["updated_at"] = now_iso()
            write_job(job)
            self._send_json(
                HTTPStatus.ACCEPTED,
                {"job_id": job_id, "status": "cancel_requested", "message": "Active job cancellation requested"},
            )
            return

        target = job_dir(job_id)
        record_deleted_terminal_job(job)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)

        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()


def validate_startup_binding() -> None:
    if PUBLIC_MODE or ALLOW_UNSAFE_LOCAL_MODE:
        return
    if HOST in {"127.0.0.1", "localhost", "::1"}:
        return
    raise RuntimeError(
        "Refusing to start non-public ClusterWeave web server on a non-loopback host. "
        "Set CLUSTERWEAVE_PUBLIC_MODE=1 for shared deployments, or set "
        "CLUSTERWEAVE_ALLOW_UNSAFE_LOCAL_MODE=1 only for isolated lab QA."
    )


def main() -> None:
    validate_startup_binding()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"ClusterWeave web server listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
