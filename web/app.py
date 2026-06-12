#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import hashlib
import hmac
import mimetypes
import os
import re
import secrets
import shutil
from datetime import datetime
import urllib.parse
import urllib.error
import urllib.request
import uuid
import zipfile
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from job_store import (
    QUEUE_DIR,
    append_log,
    job_dir,
    list_jobs,
    now_iso,
    read_job,
    read_logs,
    write_job,
)
from notifications import validate_email
from runtime_capabilities import unavailable_stage_reason

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))


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


PUBLIC_MODE = env_bool("CLUSTERWEAVE_PUBLIC_MODE", False)
ALLOW_UNSAFE_LOCAL_MODE = env_bool("CLUSTERWEAVE_ALLOW_UNSAFE_LOCAL_MODE", False)
SUBMISSIONS_OPEN = env_bool("CLUSTERWEAVE_SUBMISSIONS_OPEN", True)
SUBMIT_TOKEN = os.environ.get("CLUSTERWEAVE_SUBMIT_TOKEN", "")
ADMIN_TOKEN = os.environ.get("CLUSTERWEAVE_ADMIN_TOKEN", "")
JOB_TOKEN_SECRET = os.environ.get("CLUSTERWEAVE_JOB_TOKEN_SECRET", "")
ALLOW_ENV_OVERRIDES = env_bool("CLUSTERWEAVE_ALLOW_ENV_OVERRIDES", False)
MAX_ACCESSIONS = env_int("CLUSTERWEAVE_MAX_ACCESSIONS", 25, minimum=1)
MAX_GENOME_FILES = env_int("CLUSTERWEAVE_MAX_GENOME_FILES", 25, minimum=1)
MAX_UPLOAD_FILE_MB = env_int("CLUSTERWEAVE_MAX_UPLOAD_FILE_MB", 250, minimum=1)
MAX_UPLOAD_TOTAL_MB = env_int("CLUSTERWEAVE_MAX_UPLOAD_TOTAL_MB", 1024, minimum=1)
MAX_QUEUED_JOBS = env_int("CLUSTERWEAVE_MAX_QUEUED_JOBS", 50, minimum=0)
MAX_CPUS_PER_JOB = env_int("CLUSTERWEAVE_MAX_CPUS_PER_JOB", 8, minimum=1)
SMTP_ENABLED = env_bool("CLUSTERWEAVE_SMTP_ENABLED", False)
ALLOWED_CORS_ORIGINS = {
    origin.strip()
    for origin in os.environ.get("CLUSTERWEAVE_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}
WEB_DISABLED_ANNOTATION_FALLBACKS = {"braker3", "braker"}
WEB_DISABLED_RUNTIME_ENV_KEYS = {
    "BRAKER3_ENABLED",
    "BRAKER_BAM",
    "BRAKER_IMAGE_URI",
    "BRAKER_PROT_SEQ",
    "BRAKER_SIF",
    "GENEMARK_KEY",
    "GENEMARK_PATH",
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
PUBLIC_GENOME_EXTENSIONS = {".fasta", ".fa", ".fna", ".fsa", ".gb", ".gbk", ".gbff"}
PUBLIC_ACCESSION_EXTENSIONS = {".txt"}
PUBLIC_FASTA_EXTENSIONS = {".fasta", ".fa", ".fna", ".fsa"}
PUBLIC_GENBANK_EXTENSIONS = {".gb", ".gbk", ".gbff"}
PUBLIC_GENOME_STEM_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
PUBLIC_NUCLEOTIDE_CHARS = set("ACGTRYSWKMBDHVNU-.")
PUBLIC_ECOLOGY_METADATA_FILENAME = "ecofun_metadata_normalized.tsv"
MANUAL_ACCESSIONS_FILENAME = "manual_accessions.txt"
NCBI_ASSEMBLY_ACCESSION_RE = re.compile(r"^(?:GCA|GCF)_\d{9}\.\d+$", re.IGNORECASE)
NCBI_ACCESSION_EXAMPLES = "GCA_000011425.1 or GCA_030770425.1"
NCBI_DATASETS_API_BASE = os.environ.get("CLUSTERWEAVE_NCBI_DATASETS_API_BASE", "https://api.ncbi.nlm.nih.gov/datasets/v2").rstrip("/")
NCBI_ACCESSION_PREFLIGHT = env_bool("CLUSTERWEAVE_NCBI_ACCESSION_PREFLIGHT", True)
NCBI_PREFLIGHT_TIMEOUT_SECONDS = env_int("CLUSTERWEAVE_NCBI_PREFLIGHT_TIMEOUT_SECONDS", 8, minimum=1)
NCBI_FUNGAL_TAXON_ID = 4751
PUBLIC_ACTIVITY_TOKEN_RE = re.compile(r"[^A-Za-z0-9._-]+")
BYTES_PER_MB = 1024 * 1024
WORKER_STATUS_PATH = Path(os.environ.get("DATA_DIR", "/data")) / "worker" / "status.json"
STATIC_DIR = Path(__file__).parent / "static"
STATIC_ASSET_DIR = STATIC_DIR / "assets"
INLINE_MIME_OVERRIDES = {
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


def env_overrides_use_web_disabled_runtime(env_overrides: str) -> bool:
    for raw_line in env_overrides.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip().upper()
        if key in WEB_DISABLED_RUNTIME_ENV_KEYS:
            return True
    return False


def validate_web_runtime_policy(settings: dict[str, object]) -> str | None:
    env_overrides = str(settings.get("env_overrides", "")).strip()
    if env_overrides and env_overrides_use_web_disabled_runtime(env_overrides):
        return "Restricted annotation runtime keys are not available through the web portal"
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
            age = (datetime.now() - datetime.fromisoformat(updated_at)).total_seconds()
            stale = age > 30
        except ValueError:
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


def content_disposition(disposition: str, filename: str) -> str:
    basename = Path(filename).name or "download"
    ascii_name = basename.encode("ascii", errors="ignore").decode("ascii") or "download"
    ascii_name = ascii_name.replace("\\", "_").replace('"', '\\"')
    encoded_name = urllib.parse.quote(basename)
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'


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


def request_has_token(handler: BaseHTTPRequestHandler, expected: str) -> bool:
    return any(secure_token_match(token, expected) for token in request_tokens(handler))


def request_has_any_token(handler: BaseHTTPRequestHandler) -> bool:
    return bool(request_tokens(handler))


def request_is_admin(handler: BaseHTTPRequestHandler) -> bool:
    if not PUBLIC_MODE:
        return True
    return request_has_token(handler, ADMIN_TOKEN)


def request_can_submit(handler: BaseHTTPRequestHandler) -> bool:
    if not PUBLIC_MODE:
        return True
    if request_is_admin(handler):
        return True
    if not SUBMIT_TOKEN:
        return True
    return request_has_token(handler, SUBMIT_TOKEN)


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


def normalized_job_result_path(value: object) -> str:
    rel_path = str(value or "").replace("\\", "/").lstrip("/")
    if not rel_path or ".." in Path(rel_path).parts:
        return ""
    return rel_path


def result_path_forbidden(rel_path: str) -> bool:
    normalized = normalized_job_result_path(rel_path)
    if not normalized:
        return True
    lower = normalized.lower()
    if lower in {"job.json", "logs.txt"}:
        return True
    if lower.startswith(("inputs/", "work/", "data/genomes/")):
        return True
    private_markers = (
        "/funannotate/",
        "/braker3/",
        "/input_gbks/",
        "/summary_tables/logs/",
        "/reproducibility/",
    )
    if any(marker in f"/{lower}" for marker in private_markers):
        return True
    filename = lower.rsplit("/", 1)[-1]
    if filename in PUBLIC_TOOL_PRIVATE_FILENAMES:
        return True
    return False


PUBLIC_SUMMARY_FILENAMES = {
    "all_tools_shared_unshared_summary.csv",
    "family_atlas_shortlist.md",
    "family_atlas_shortlist.tsv",
    "priority_shortlist.md",
    "priority_shortlist.tsv",
    "shared_family_shortlist.md",
    "shared_family_shortlist.tsv",
}
PUBLIC_SUMMARY_TABLE_FILENAMES = {"ecofun_metadata_normalized.tsv", "ecofun_metadata_template.tsv"}
PUBLIC_FIGURE_EXTENSIONS = {".svg", ".png", ".pdf", ".graphml", ".tsv"}
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
PUBLIC_BIGSCAPE_EXTENSIONS = PUBLIC_TOOL_WEB_EXTENSIONS | {".db", ".sqlite", ".sqlite3"}
PUBLIC_TOOL_ROOTS = {"antismash", "funbgcex", "big_scape", "bigscape", "big-scape", "clinker", "clinker_shared_family"}
PUBLIC_BIGSCAPE_ROOTS = {"big_scape", "bigscape", "big-scape"}
PUBLIC_TOOL_PRIVATE_PARTS = {"inputs", "input_gbks", "logs", "tmp", "reproducibility", "funannotate", "braker3"}
PUBLIC_TOOL_PRIVATE_FILENAMES = {
    "external_artifacts.tsv",
    "run_clusterweave_context.env",
    "panel_manifest.tsv",
    "panels_manifest.tsv",
    "run_panel.sh",
    "panel_notes.md",
}
PUBLIC_RESULTS_MANIFEST_PATH = "downloads/public_results_manifest.tsv"


def result_is_public_archive(rel_path: str) -> bool:
    lower = normalized_job_result_path(rel_path).lower()
    return lower.startswith("downloads/") and lower.endswith("_public_results.zip")


def result_tool_public_shape(subparts: list[str], suffix: str) -> bool:
    if not subparts or subparts[0] not in PUBLIC_TOOL_ROOTS:
        return False
    if any(part in PUBLIC_TOOL_PRIVATE_PARTS for part in subparts):
        return False
    if subparts[-1] in PUBLIC_TOOL_PRIVATE_FILENAMES:
        return False
    allowed = PUBLIC_BIGSCAPE_EXTENSIONS if subparts[0] in PUBLIC_BIGSCAPE_ROOTS else PUBLIC_TOOL_WEB_EXTENSIONS
    return suffix.lower() in allowed


def result_path_public_shape(rel_path: str) -> bool:
    if result_path_forbidden(rel_path):
        return False
    lower = normalized_job_result_path(rel_path).lower()
    filename = lower.rsplit("/", 1)[-1]
    suffix = Path(filename).suffix.lower()
    if lower == PUBLIC_RESULTS_MANIFEST_PATH:
        return True
    if result_is_public_archive(lower):
        return True
    if lower.startswith("results/") and suffix in PUBLIC_FIGURE_EXTENSIONS:
        return True
    parts = lower.split("/")
    if len(parts) < 4 or parts[0] != "data" or parts[1] != "results":
        return False
    subparts = parts[3:]
    if result_tool_public_shape(subparts, suffix):
        return True
    if len(subparts) >= 2 and subparts[0] == "figures" and suffix in PUBLIC_FIGURE_EXTENSIONS:
        return True
    if len(subparts) == 2 and subparts[0] == "summary" and filename in PUBLIC_SUMMARY_FILENAMES:
        return True
    if len(subparts) == 2 and subparts[0] == "summary_tables" and filename in PUBLIC_SUMMARY_TABLE_FILENAMES:
        return True
    return False


def result_file_exists(base_dir: Path, rel_path: str) -> bool:
    full = (base_dir / rel_path).resolve()
    try:
        full.relative_to(base_dir)
    except ValueError:
        return False
    return full.is_file()


def append_unique_result_path(files: list[str], seen: set[str], rel_path: str) -> None:
    if rel_path and rel_path not in seen:
        seen.add(rel_path)
        files.append(rel_path)


def public_manifest_result_paths(base_dir: Path) -> list[str]:
    manifest = (base_dir / PUBLIC_RESULTS_MANIFEST_PATH).resolve()
    try:
        manifest.relative_to(base_dir)
    except ValueError:
        return []
    if not manifest.is_file():
        return []

    files: list[str] = []
    seen: set[str] = set()
    for index, line in enumerate(manifest.read_text(encoding="utf-8", errors="replace").splitlines()):
        if index == 0 and line.lower().startswith("path\t"):
            continue
        rel_path = normalized_job_result_path(line.split("\t", 1)[0] if line else "")
        lower = rel_path.lower()
        if lower == PUBLIC_RESULTS_MANIFEST_PATH or result_is_public_archive(rel_path):
            continue
        if not result_path_public_shape(rel_path) or not result_file_exists(base_dir, rel_path):
            continue
        append_unique_result_path(files, seen, rel_path)
    return files


def result_file_allowlist(job: dict[str, object], *, base_dir: Path | None = None) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    stored_files: list[str] = []
    for item in job.get("result_files", []):
        rel_path = normalized_job_result_path(item)
        if not result_path_public_shape(rel_path) or rel_path in seen:
            continue
        if base_dir is not None and not result_file_exists(base_dir, rel_path):
            continue
        seen.add(rel_path)
        stored_files.append(rel_path)

    if base_dir is None or not result_file_exists(base_dir, PUBLIC_RESULTS_MANIFEST_PATH):
        return stored_files

    files_seen: set[str] = set()
    for rel_path in stored_files:
        if result_is_public_archive(rel_path):
            append_unique_result_path(files, files_seen, rel_path)
    append_unique_result_path(files, files_seen, PUBLIC_RESULTS_MANIFEST_PATH)
    for rel_path in public_manifest_result_paths(base_dir):
        append_unique_result_path(files, files_seen, rel_path)
    return files


PUBLIC_SAFE_ARCHIVE_PRIVATE_DIRS = {"logs", "tmp", "reproducibility", "__pycache__"}
PUBLIC_SAFE_ARCHIVE_PRIVATE_FILENAMES = PUBLIC_TOOL_PRIVATE_FILENAMES | {
    "job.json",
    "logs.txt",
    ".done",
    "provenance.json",
    "provenance.tsv",
}
PUBLIC_SAFE_ARCHIVE_PRIVATE_SUFFIXES = {".env", ".log", ".pyc", ".zip"}


def public_safe_archive_project_names(job: dict[str, object]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        name = normalized_job_result_path(value)
        if not name or len(Path(name).parts) != 1 or name in seen:
            return
        seen.add(name)
        names.append(name)

    add(job.get("project_name"))
    add(job.get("name"))
    for item in job.get("result_files", []):
        parts = normalized_job_result_path(item).split("/")
        if len(parts) >= 4 and parts[0].lower() == "data" and parts[1].lower() == "results":
            add(parts[2])
    return names


def public_safe_archive_roots(job: dict[str, object], base_dir: Path) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()

    def add_root(root: Path) -> None:
        resolved = root.resolve()
        try:
            resolved.relative_to(base_dir)
        except ValueError:
            return
        if resolved.is_dir() and resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)

    for project_name in public_safe_archive_project_names(job):
        add_root(base_dir / "data" / "results" / project_name)
        add_root(base_dir / "Data" / "Results" / project_name)

    if roots:
        return roots

    for parent_rel in (("data", "results"), ("Data", "Results")):
        parent = (base_dir / Path(*parent_rel)).resolve()
        try:
            parent.relative_to(base_dir)
        except ValueError:
            continue
        if not parent.is_dir():
            continue
        children = [child for child in parent.iterdir() if child.is_dir() and not child.is_symlink()]
        if len(children) == 1:
            add_root(children[0])
    return roots


def public_safe_archive_excluded(root: Path, full: Path) -> bool:
    if full.is_symlink() or not full.is_file():
        return True
    resolved = full.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return True
    rel_path = normalized_job_result_path(resolved.relative_to(root).as_posix())
    if not rel_path:
        return True
    parts = [part.lower() for part in Path(rel_path).parts]
    if any(part in PUBLIC_SAFE_ARCHIVE_PRIVATE_DIRS for part in parts):
        return True
    filename = parts[-1]
    suffix = Path(filename).suffix.lower()
    if filename.startswith(".") or filename in PUBLIC_SAFE_ARCHIVE_PRIVATE_FILENAMES:
        return True
    if suffix in PUBLIC_SAFE_ARCHIVE_PRIVATE_SUFFIXES:
        return True
    if suffix == ".sh" and "clinker" in parts:
        return True
    if "provenance" in filename or filename.endswith("_context.env"):
        return True
    return False


def public_safe_archive_entries(job: dict[str, object], base_dir: Path) -> list[tuple[Path, str]]:
    entries: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for root in public_safe_archive_roots(job, base_dir):
        files = sorted(
            (path for path in root.rglob("*")),
            key=lambda path: path.relative_to(root).as_posix().lower(),
        )
        for full in files:
            if public_safe_archive_excluded(root, full):
                continue
            archive_name = normalized_job_result_path(full.resolve().relative_to(root).as_posix())
            if not archive_name or archive_name in seen:
                continue
            seen.add(archive_name)
            entries.append((full.resolve(), archive_name))

    if entries:
        return entries

    for rel_path in result_file_allowlist(job, base_dir=base_dir):
        lower = rel_path.lower()
        if lower.startswith("downloads/") and lower.endswith(".zip"):
            continue
        full = (base_dir / rel_path).resolve()
        try:
            full.relative_to(base_dir)
        except ValueError:
            continue
        if full.is_symlink() or not full.is_file() or rel_path in seen:
            continue
        seen.add(rel_path)
        entries.append((full, rel_path))
    return entries


def public_error_summary(error: object) -> str:
    if not str(error or "").strip():
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


def add_public_activity_event(
    events: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    stage: str,
    title: str,
    meta: str = "",
    observed_at: str = "",
) -> None:
    safe_title = str(title or "").strip()
    safe_meta = str(meta or "").strip()
    if not safe_title:
        return
    key = (stage, safe_title, safe_meta)
    if key in seen:
        return
    seen.add(key)
    event = {"stage": stage, "title": safe_title}
    if safe_meta:
        event["meta"] = safe_meta
    if observed_at:
        event["time"] = observed_at
    events.append(event)


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


def queued_job_ids() -> list[str]:
    ids: list[str] = []
    for queue_path in sorted(QUEUE_DIR.glob("*.json")):
        job_id = queue_path.stem
        try:
            payload = json.loads(queue_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("job_id"):
                job_id = str(payload["job_id"])
        except Exception:
            pass
        if job_id:
            ids.append(job_id)
    return ids


def job_queue_status(job: dict[str, object], *, admin: bool) -> dict[str, object] | None:
    job_id = str(job.get("id") or "")
    status = str(job.get("status") or "").lower()
    if not job_id or status not in QUEUED_JOB_STATUSES:
        return None

    worker = worker_status()
    active_ids = worker_active_job_ids(worker)
    queued_ids = queued_job_ids()
    active_count = len(active_ids)

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

def job_payload(job: dict[str, object], *, admin: bool, include_public_events: bool = False) -> dict[str, object]:
    if PUBLIC_MODE and not admin:
        payload = {
            key: job[key]
            for key in [
                "id",
                "name",
                "status",
                "stage",
                "created_at",
                "updated_at",
                "log_count",
                "cpus",
                "project_name",
                "input_summary",
                "retention_days",
                "expires_at",
                "completed_at",
                "failed_at",
            ]
            if key in job
        }
        public_result_base = job_dir(str(job.get("id", ""))).resolve() if job.get("id") else None
        payload["result_files"] = result_file_allowlist(job, base_dir=public_result_base)
        if job.get("error") or str(job.get("status", "")).lower() == "failed":
            payload["error"] = public_error_summary(job.get("error"))
            payload["error_summary"] = payload["error"]
    else:
        payload = dict(job)
        for key in SENSITIVE_JOB_FIELDS:
            payload.pop(key, None)
    queue_status = job_queue_status(job, admin=admin)
    if queue_status is not None:
        payload["queue_status"] = queue_status
    if include_public_events:
        job_id = str(job.get("id") or "")
        payload["public_events"] = public_activity_from_logs(job_id, read_logs(job_id)) if job_id else []
    return payload


def jobs_processed_count() -> int:
    return sum(1 for job in list_jobs() if str(job.get("status", "")).lower() in PROCESSED_JOB_STATUSES)


def queued_job_count() -> int:
    return sum(1 for job in list_jobs() if str(job.get("status", "")).lower() in QUEUED_JOB_STATUSES)


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
                f"Use current fungal NCBI assembly accessions like {NCBI_ACCESSION_EXAMPLES}",
                [],
            )
        accessions.append(line.upper())
    return None, accessions


def parse_accession_text(filename: str, content: bytes) -> tuple[str | None, int]:
    error, accessions = parse_accession_list(filename, content)
    return error, len(accessions)


def accession_text_upload_requires_validation(filename: str) -> bool:
    lower = filename.lower()
    return filename == MANUAL_ACCESSIONS_FILENAME or (lower.endswith(".txt") and "accession" in lower)


def validate_manual_accession_uploads(uploads: list[dict[str, object]]) -> str | None:
    for item in uploads:
        filename = Path(str(item.get("filename") or "unknown")).name
        if not accession_text_upload_requires_validation(filename):
            continue
        error, _ = parse_accession_text(filename, bytes(item.get("content") or b""))
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
        "Try again later, or upload a supported fungal genome FASTA/GenBank file instead."
    )


def ncbi_accession_acceptability_error(accession: str) -> str | None:
    quoted_accession = urllib.parse.quote(accession, safe="")
    try:
        report_payload = fetch_ncbi_datasets_json(f"genome/accession/{quoted_accession}/dataset_report")
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return ncbi_preflight_unavailable(accession)

    reports = report_payload.get("reports") if isinstance(report_payload, dict) else None
    if not isinstance(reports, list) or not reports:
        return (
            f"NCBI Datasets did not find assembly accession '{accession}'. "
            f"Use current fungal NCBI assembly accessions like {NCBI_ACCESSION_EXAMPLES}."
        )

    report = reports[0]
    if not isinstance(report, dict):
        return ncbi_preflight_unavailable(accession)

    assembly_info = report.get("assembly_info")
    assembly_status = ""
    if isinstance(assembly_info, dict):
        assembly_status = str(assembly_info.get("assembly_status") or "")
    if assembly_status and assembly_status.lower() != "current":
        return (
            f"NCBI assembly accession '{accession}' is not current ({assembly_status}). "
            f"Use a current fungal assembly accession like {NCBI_ACCESSION_EXAMPLES}."
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
        return ncbi_preflight_unavailable(accession)

    try:
        taxonomy_payload = fetch_ncbi_datasets_json(f"taxonomy/taxon/{tax_id}")
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return ncbi_preflight_unavailable(accession)

    taxonomy_nodes = taxonomy_payload.get("taxonomy_nodes") if isinstance(taxonomy_payload, dict) else None
    taxonomy = None
    if isinstance(taxonomy_nodes, list) and taxonomy_nodes and isinstance(taxonomy_nodes[0], dict):
        taxonomy = taxonomy_nodes[0].get("taxonomy")
    if not isinstance(taxonomy, dict):
        return ncbi_preflight_unavailable(accession)

    lineage = taxonomy.get("lineage")
    lineage_ids = {int(item) for item in lineage if isinstance(item, int) or str(item).isdigit()} if isinstance(lineage, list) else set()
    if tax_id != NCBI_FUNGAL_TAXON_ID and NCBI_FUNGAL_TAXON_ID not in lineage_ids:
        display_name = str(taxonomy.get("organism_name") or organism_name or accession)
        return (
            f"NCBI accession '{accession}' is {display_name}, not a fungal assembly. "
            f"ClusterWeave public runs accept fungal assemblies such as {NCBI_ACCESSION_EXAMPLES}."
        )

    return None


def validate_ncbi_accession_preflight(accessions: list[str]) -> str | None:
    if not NCBI_ACCESSION_PREFLIGHT:
        return None
    seen: set[str] = set()
    for accession in accessions:
        normalized = accession.strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        error = ncbi_accession_acceptability_error(normalized)
        if error:
            return error
    return None


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


def classify_public_fasta(filename: str, content: bytes) -> tuple[str, str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return "invalid", f"FASTA genome '{filename}' must be UTF-8 compatible text"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "invalid", f"FASTA genome '{filename}' is empty"
    if not lines[0].startswith(">"):
        return "invalid", f"FASTA genome '{filename}' must start with a FASTA header line beginning with >"

    sequence_chars: list[str] = []
    sequence_lines = 0
    for line in lines:
        if line.startswith(">"):
            continue
        clean = re.sub(r"\s+", "", line).upper()
        if not clean:
            continue
        sequence_lines += 1
        sequence_chars.extend(clean)

    if sequence_lines == 0 or not sequence_chars:
        return "invalid", f"FASTA genome '{filename}' must include at least one nucleotide sequence line"

    nucleotide_count = sum(1 for char in sequence_chars if char in PUBLIC_NUCLEOTIDE_CHARS)
    nucleotide_ratio = nucleotide_count / len(sequence_chars)
    if nucleotide_ratio < 0.85:
        return (
            "invalid",
            f"FASTA genome '{filename}' looks like protein FASTA or arbitrary text; upload a nucleotide genome assembly FASTA",
        )

    return (
        "raw_fasta_requires_annotation",
        "Nucleotide FASTA accepted; funannotate must predict CDS/protein translations before downstream BGC tools can run, and may fail if the assembly is not annotatable",
    )


def classify_public_genbank(filename: str, content: bytes) -> tuple[str, str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return "invalid", f"GenBank genome '{filename}' must be UTF-8 compatible text"

    if not text.strip():
        return "invalid", f"GenBank genome '{filename}' is empty"

    required_markers = {
        "LOCUS": re.search(r"^LOCUS\s+", text, re.MULTILINE),
        "FEATURES": re.search(r"^FEATURES\b", text, re.MULTILINE),
        "ORIGIN": re.search(r"^ORIGIN\b", text, re.MULTILINE),
        "//": re.search(r"^//\s*$", text, re.MULTILINE),
    }
    missing = [name for name, match in required_markers.items() if not match]
    if missing:
        return "invalid", f"GenBank genome '{filename}' is missing required marker(s): {', '.join(missing)}"

    has_cds = re.search(r"^\s+CDS\b", text, re.MULTILINE) is not None
    has_translation = re.search(r"/translation\s*=", text) is not None
    if has_cds and has_translation:
        return "annotated_genbank_ready", "Annotated GenBank with CDS translations is ready for antiSMASH and FunBGCeX"

    return (
        "genbank_requires_fallback_or_translations",
        "GenBank structure is present, but CDS translations were not detected; submit a same-stem nucleotide FASTA or translated GenBank so funannotate can produce proteins before downstream BGC tools run",
    )


def public_genome_upload_kind(ext: str) -> str:
    return "fasta" if ext in PUBLIC_FASTA_EXTENSIONS else "genbank"


def classify_public_genome_upload(filename: str, ext: str, content: bytes) -> tuple[str, str]:
    if ext in PUBLIC_FASTA_EXTENSIONS:
        return classify_public_fasta(filename, content)
    if ext in PUBLIC_GENBANK_EXTENSIONS:
        return classify_public_genbank(filename, content)
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
    ecology_enabled = settings_bool(settings, "run_ecology_analysis")
    genome_stem_kinds: dict[str, set[str]] = {}
    genome_stem_labels: dict[str, str] = {}
    accession_file_count = 0
    accessions_for_preflight: list[str] = []

    for item in uploads:
        raw_filename = str(item.get("filename") or "unknown")
        ext = Path(raw_filename).suffix.lower()
        filename = Path(raw_filename).name
        content = bytes(item.get("content") or b"")
        size = len(content)

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
            readiness_class, reason = classify_public_genome_upload(filename, ext, content)
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
            error, accessions = parse_accession_list(filename, content)
            if error:
                return error, summary
            summary["accession_count"] = int(summary["accession_count"]) + len(accessions)
            if int(summary["accession_count"]) > MAX_ACCESSIONS:
                return f"Public jobs may include at most {MAX_ACCESSIONS} accessions", summary
            accessions_for_preflight.extend(accessions)
            continue

        if filename == PUBLIC_ECOLOGY_METADATA_FILENAME:
            if not ecology_enabled:
                return "Ecology metadata is only accepted when ecology-aware analysis is enabled", summary
            summary["metadata_file_count"] = int(summary["metadata_file_count"]) + 1
            if int(summary["metadata_file_count"]) > 1:
                return "Only one ecology metadata table may be submitted", summary
            continue

        if ext in {".tsv", ".csv"}:
            return "Public accession tables in TSV/CSV format are not supported yet; upload one accession per line as .txt", summary

        return (
            f"Unsupported public file type '{ext}'. Allowed: .txt accession lists, "
            ".fasta/.fa/.fna/.fsa/.gb/.gbk/.gbff genomes, and generated ecology metadata",
            summary,
        )

    if int(summary["accession_count"]) + int(summary["genome_file_count"]) <= 0:
        return "Submit at least one accession list or genome file", summary

    for record in readiness_records:
        if record.get("readiness") != "genbank_requires_fallback_or_translations":
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
        ncbi_error = validate_ncbi_accession_preflight(accessions_for_preflight)
        if ncbi_error:
            return ncbi_error, summary

    return None, summary


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
        ("annotation", settings_bool(settings, "run_annotation")),
        ("bigscape", settings_bool(settings, "run_bigscape")),
        ("clinker", settings_bool(settings, "run_clinker") and settings_bool(settings, "execute_clinker")),
        ("nplinker", settings_bool(settings, "run_nplinker")),
        ("figures", settings_bool(settings, "run_figures") and settings_bool(settings, "figures_required")),
    ]
    for stage, required in checks:
        if not required:
            continue
        payload = stages.get(stage)
        if isinstance(payload, dict) and not payload.get("available", False):
            return f"Selected stage unavailable: {stage}. {unavailable_stage_reason(capabilities, stage)}"
    return None


def enqueue_job(job_id: str, cpus: int, settings: dict[str, object]) -> None:
    queue_payload = {"job_id": job_id, "cpus": cpus, "settings": settings}
    queue_file = QUEUE_DIR / f"{job_id}.json"
    queue_file.write_text(json.dumps(queue_payload), encoding="utf-8")


def base_job_settings(job: dict[str, object]) -> dict[str, object]:
    submission_settings = job.get("submission_settings")
    if isinstance(submission_settings, dict):
        return dict(submission_settings)
    current_settings = job.get("settings")
    return dict(current_settings) if isinstance(current_settings, dict) else {}


def rerun_settings(base_settings: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    settings = dict(base_settings)
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
    ]
    for key in stage_bool_fields:
        settings[key] = parse_payload_bool(payload, key, False) if key in payload else False

    settings["force"] = parse_payload_bool(payload, "force", False)
    settings["run_ncbi_install"] = parse_payload_bool(payload, "run_ncbi_install", False)
    settings["reuse_existing_layout"] = True
    if "run_summary" in payload and "run_crosswalk" not in payload:
        settings["run_crosswalk"] = settings["run_summary"]
    if "execute_clinker" not in payload and "run_clinker" in payload:
        settings["execute_clinker"] = settings["run_clinker"]
    scrub_web_disabled_annotation_settings(settings)
    return settings


def parse_multipart_form_data(content_type: str, body: bytes) -> tuple[dict[str, list[str]], list[dict[str, object]]]:
    """Parse multipart/form-data using the stdlib email package."""
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )

    fields: dict[str, list[str]] = {}
    files: list[dict[str, object]] = []

    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        if disposition != "form-data":
            continue

        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if not name:
            continue

        if filename is not None:
            files.append({
                "field": name,
                "filename": filename,
                "content": payload,
            })
            continue

        charset = part.get_content_charset() or "utf-8"
        value = payload.decode(charset, errors="replace")
        fields.setdefault(name, []).append(value)

    return fields, files


class Handler(BaseHTTPRequestHandler):
    server_version = "ClusterWeaveHTTP/2.0"

    def _send_cors_headers(self) -> None:
        origin = allowed_cors_origin(self.headers.get("Origin"))
        if not origin:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        if origin != "*":
            self.send_header("Vary", "Origin")

    def _send_json(self, status: int, payload: object) -> None:
        data = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
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

        if route == "/api/jobs":
            if not request_is_admin(self):
                self._auth_failed("Admin token required")
                return
            self._send_json(HTTPStatus.OK, [job_payload(job, admin=True) for job in list_jobs()])
            return

        if route == "/api/system/status":
            if PUBLIC_MODE and not request_is_admin(self):
                self._send_json(HTTPStatus.OK, redacted_system_status())
                return
            self._send_json(HTTPStatus.OK, full_system_status())
            return

        if route.startswith("/api/jobs/"):
            parts = route.split("/")
            if len(parts) < 4:
                self._not_found()
                return
            job_id = parts[3]
            job = read_job(job_id)
            if job is None:
                self._not_found(f"Job '{job_id}' not found")
                return
            if not request_can_read_job(self, job):
                self._auth_failed("Job read token or admin token required")
                return
            is_admin = request_is_admin(self)

            if len(parts) == 4:
                self._send_json(HTTPStatus.OK, job_payload(job, admin=is_admin, include_public_events=True))
                return

            if len(parts) >= 5 and parts[4] == "logs":
                if PUBLIC_MODE and not is_admin:
                    self._auth_failed("Admin token required for raw logs")
                    return
                since = parse_int(query.get("since", ["0"])[0], 0)
                lines = read_logs(job_id)
                self._send_json(HTTPStatus.OK, {"lines": lines[max(0, since):], "total": len(lines)})
                return

            if len(parts) == 5 and parts[4] == "archive":
                base_dir = job_dir(job_id).resolve()
                archive_buffer = io.BytesIO()
                added = 0
                with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                    for full, archive_name in public_safe_archive_entries(job, base_dir):
                        archive.write(full, archive_name)
                        added += 1
                    if not added:
                        archive.writestr("README.txt", "No public result files are available for this ClusterWeave run yet.\n")
                safe_job_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", job_id).strip("._") or "clusterweave"
                self._send_text(
                    HTTPStatus.OK,
                    "application/zip",
                    archive_buffer.getvalue(),
                    {
                        "Content-Disposition": content_disposition("attachment", f"{safe_job_id}_clusterweave_results.zip"),
                        "Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff",
                    },
                )
                return

            if len(parts) >= 5 and parts[4] == "files":
                base_dir = job_dir(job_id).resolve()
                allowed_files = result_file_allowlist(job, base_dir=base_dir)
                if len(parts) == 5:
                    self._send_json(HTTPStatus.OK, {"files": allowed_files})
                    return

                rel_path = normalized_job_result_path(urllib.parse.unquote("/".join(parts[5:])))
                if not rel_path:
                    self._bad_request("Invalid path")
                    return
                if rel_path not in set(allowed_files):
                    self._auth_failed("Result file is not available through the public manifest")
                    return
                full = (base_dir / rel_path).resolve()
                try:
                    full.relative_to(base_dir)
                except ValueError:
                    self._bad_request("Invalid path")
                    return
                if not full.exists() or not full.is_file():
                    self._not_found("File not found")
                    return

                disposition = "attachment" if parse_bool(query.get("download", ["0"])[0], False) else "inline"
                headers = {
                    "Content-Disposition": content_disposition(disposition, full.name),
                    "X-Content-Type-Options": "nosniff",
                }
                self._send_text(HTTPStatus.OK, result_file_mime(full), full.read_bytes(), headers)
                return

        self._not_found()

    def do_POST(self) -> None:  # noqa: N802
        route, _ = parse_path(self.path)
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

            base_settings = base_job_settings(job)
            settings = rerun_settings(base_settings, payload)
            if not any(
                settings_bool(settings, key)
                for key in ["run_genome_prep", "run_annotation", "run_bigscape", "run_summary", "run_clinker", "run_figures", "run_nplinker"]
            ):
                self._bad_request("Select at least one stage to rerun")
                return
            runtime_error = validate_runtime_request(settings, worker_status())
            if runtime_error:
                self._send_json(HTTPStatus.CONFLICT, {"detail": runtime_error})
                return

            cpus = clamp_public_cpus(parse_int(str(payload.get("cpus", job.get("cpus", 4))), 4))
            append_log(job_id, "Re-queued existing job with selected stage rerun settings.")
            append_log(job_id, "Queued: waiting for worker slot.")
            lines = read_logs(job_id)
            job["status"] = "pending"
            job["stage"] = "queued"
            job["error"] = None
            job["cpus"] = cpus
            job["settings"] = settings
            job["submission_settings"] = base_settings
            job["last_rerun_settings"] = settings
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

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._bad_request("Expected multipart/form-data")
            return

        content_length = parse_int(self.headers.get("Content-Length", "0"), 0)
        if content_length <= 0:
            self._bad_request("Missing or invalid Content-Length")
            return

        body = self.rfile.read(content_length)
        fields, files = parse_multipart_form_data(content_type, body)

        if PUBLIC_MODE and not request_is_admin(self):
            data_use_ack = parse_bool(fields.get("data_use_ack", ["0"])[0], False)
            if not data_use_ack:
                self._bad_request("Data-use acknowledgment is required")
                return

        project_name = str(fields.get("project_name", ["my_project"])[0])
        cpus = clamp_public_cpus(parse_int(fields.get("cpus", ["4"])[0], 4))
        notify_email = str(fields.get("notify_email", [""])[0]).strip()
        if notify_email and not SMTP_ENABLED:
            self._bad_request("Email notifications are not enabled on this ClusterWeave server")
            return
        if notify_email and not validate_email(notify_email):
            self._bad_request("Notification email address is not valid")
            return

        settings = {
            "project_name": project_name,
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
            "run_ecology_analysis": parse_bool(fields.get("run_ecology_analysis", ["0"])[0], False),
            "ecology_field": str(fields.get("ecology_field", ["ecofun_primary"])[0]).strip(),
            "focus_ecology_label": str(fields.get("focus_ecology_label", [""])[0]).strip(),
            "genefinding_mode": str(fields.get("genefinding_mode", ["auto"])[0]).strip() or "auto",
            "bigscape_mix_mode": parse_bool(fields.get("bigscape_mix_mode", ["1"])[0], True),
            "force": parse_bool(fields.get("force", ["0"])[0], False),
            "workers": max(1, parse_int(fields.get("workers", ["2"])[0], 2)),
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
            "clinker_max_regions": max(0, parse_int(fields.get("clinker_max_regions", ["0"])[0], 0)),
            "atlas_stage_limit": max(1, parse_int(fields.get("atlas_stage_limit", fields.get("shortlist_limit", ["12"]))[0], 12)),
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

        if PUBLIC_MODE and not request_is_admin(self):
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
                    "threads": cpus,
                    "anno_cpus": cpus,
                }
            )
            settings["workers"] = min(2, cpus)

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
        created_at = now_iso()
        job = {
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
            with destination.open("wb") as handle:
                handle.write(bytes(item["content"]))
            append_log(job_id, f"Uploaded: {filename} ({destination.stat().st_size:,} bytes)")

        append_log(job_id, "Queued: waiting for worker slot.")
        lines = read_logs(job_id)
        job["log_count"] = len(lines)
        job["updated_at"] = now_iso()
        write_job(job)

        enqueue_job(job_id, cpus, settings)
        result_url = f"{job.get('public_base_url') or request_public_base_url(self)}#/job/{job_id}/{read_token}"

        self._send_json(
            HTTPStatus.CREATED,
            {
                "job_id": job_id,
                "status": job["status"],
                "message": "Pipeline queued",
                "read_token": read_token,
                "result_url": result_url,
                "expires_at": job.get("expires_at"),
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

        target = job_dir(job_id)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)

        for q in QUEUE_DIR.glob(f"{job_id}*.json"):
            q.unlink(missing_ok=True)
        for q in QUEUE_DIR.glob(f"{job_id}*.working"):
            q.unlink(missing_ok=True)

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
