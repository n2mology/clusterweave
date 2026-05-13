#!/usr/bin/env python3
from __future__ import annotations

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
import uuid
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

HOST = "0.0.0.0"
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
PUBLIC_ECOLOGY_METADATA_FILENAME = "ecofun_metadata_normalized.tsv"
MANUAL_ACCESSIONS_FILENAME = "manual_accessions.txt"
NCBI_ASSEMBLY_ACCESSION_RE = re.compile(r"^(?:GCA|GCF)_\d{9}\.\d+$", re.IGNORECASE)
PUBLIC_ACTIVITY_TOKEN_RE = re.compile(r"[^A-Za-z0-9._-]+")
BYTES_PER_MB = 1024 * 1024
WORKER_STATUS_PATH = Path(os.environ.get("DATA_DIR", "/data")) / "worker" / "status.json"
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
    if re.search(r"Stage 1/4:\s+running run_annotation_and_detection\.sh", message, re.IGNORECASE):
        return "annotation"
    if re.search(r"Stage 2/4:\s+running run_bigscape\.sh", message, re.IGNORECASE):
        return "bigscape"
    if re.search(r"Stage 3/4:\s+running summarize_clusterweave\.sh", message, re.IGNORECASE):
        return "summary"
    if re.search(r"Stage 4/4:\s+running run_clinker\.sh", message, re.IGNORECASE):
        return "clinker"
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
                "annotation": "Running annotation and BGC detection",
                "bigscape": "Running BiG-SCAPE family graph",
                "summary": "Building summary tables",
                "clinker": "Staging synteny panels",
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

        if re.search(r"\brender(?:ing)?\s+summary\s+figures\b", message, re.IGNORECASE):
            current_stage = "figures"
            add_public_activity_event(events, seen, "figures", "Rendering summary figures", "Visual summaries", observed_at)
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


def job_payload(job: dict[str, object], *, admin: bool, include_public_events: bool = False) -> dict[str, object]:
    payload = dict(job)
    for key in SENSITIVE_JOB_FIELDS:
        payload.pop(key, None)
    if PUBLIC_MODE and not admin:
        for key in ["settings", "submission_settings", "last_rerun_settings"]:
            if key in payload:
                payload[key] = redact_env_overrides(payload[key])
    if include_public_events:
        job_id = str(job.get("id") or "")
        payload["public_events"] = public_activity_from_logs(job_id, read_logs(job_id)) if job_id else []
    return payload


def jobs_processed_count() -> int:
    return sum(1 for job in list_jobs() if str(job.get("status", "")).lower() in PROCESSED_JOB_STATUSES)


def queued_job_count() -> int:
    return sum(1 for job in list_jobs() if str(job.get("status", "")).lower() in QUEUED_JOB_STATUSES)


def redacted_system_status() -> dict[str, object]:
    submissions_open = SUBMISSIONS_OPEN
    return {
        "online": True,
        "service": "online",
        "submissions_open": submissions_open,
        "submissions": "open" if submissions_open else "paused",
        "jobs_processed": jobs_processed_count(),
        "smtp_enabled": SMTP_ENABLED,
    }


def full_system_status() -> dict[str, object]:
    payload = worker_status()
    payload["smtp_enabled"] = SMTP_ENABLED
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


def parse_accession_text(filename: str, content: bytes) -> tuple[str | None, int]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return f"Accession list '{filename}' must be UTF-8 text", 0

    count = 0
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = [token for token in line.replace(",", " ").replace(";", " ").split() if token]
        if len(tokens) != 1:
            return f"Accession list '{filename}' must contain one accession per line; line {line_number} has multiple values", 0
        if tokens[0].lower() == "accession":
            return f"Accession list '{filename}' must not include a header row", 0
        if not NCBI_ASSEMBLY_ACCESSION_RE.match(tokens[0]):
            return (
                f"Accession list '{filename}' line {line_number} has invalid accession '{tokens[0]}'. "
                "Use NCBI assembly accessions like GCA_000011425.1 or GCF_000001405.40",
                0,
            )
        count += 1
    return None, count


def validate_manual_accession_uploads(uploads: list[dict[str, object]]) -> str | None:
    for item in uploads:
        filename = Path(str(item.get("filename") or "unknown")).name
        if filename != MANUAL_ACCESSIONS_FILENAME:
            continue
        error, _ = parse_accession_text(filename, bytes(item.get("content") or b""))
        if error:
            return error
    return None


def validate_public_uploads(
    uploads: list[dict[str, object]],
    settings: dict[str, object],
) -> tuple[str | None, dict[str, int]]:
    summary = {
        "accession_count": 0,
        "genome_file_count": 0,
        "metadata_file_count": 0,
        "upload_bytes": 0,
    }
    max_file_bytes = MAX_UPLOAD_FILE_MB * BYTES_PER_MB
    max_total_bytes = MAX_UPLOAD_TOTAL_MB * BYTES_PER_MB
    ecology_enabled = settings_bool(settings, "run_ecology_analysis")

    for item in uploads:
        filename = Path(str(item.get("filename") or "unknown")).name
        ext = Path(filename).suffix.lower()
        content = bytes(item.get("content") or b"")
        size = len(content)

        if size > max_file_bytes:
            return f"File '{filename}' exceeds the {MAX_UPLOAD_FILE_MB} MB public upload limit", summary

        summary["upload_bytes"] += size
        if summary["upload_bytes"] > max_total_bytes:
            return f"Total upload size exceeds the {MAX_UPLOAD_TOTAL_MB} MB public job limit", summary

        if ext in PUBLIC_GENOME_EXTENSIONS:
            summary["genome_file_count"] += 1
            if summary["genome_file_count"] > MAX_GENOME_FILES:
                return f"Public jobs may include at most {MAX_GENOME_FILES} genome files", summary
            continue

        if ext in PUBLIC_ACCESSION_EXTENSIONS:
            error, accession_count = parse_accession_text(filename, content)
            if error:
                return error, summary
            summary["accession_count"] += accession_count
            if summary["accession_count"] > MAX_ACCESSIONS:
                return f"Public jobs may include at most {MAX_ACCESSIONS} accessions", summary
            continue

        if filename == PUBLIC_ECOLOGY_METADATA_FILENAME:
            if not ecology_enabled:
                return "Ecology metadata is only accepted when ecology-aware analysis is enabled", summary
            summary["metadata_file_count"] += 1
            if summary["metadata_file_count"] > 1:
                return "Only one ecology metadata table may be submitted", summary
            continue

        if ext in {".tsv", ".csv"}:
            return "Public accession tables in TSV/CSV format are not supported yet; upload one accession per line as .txt", summary

        return (
            f"Unsupported public file type '{ext}'. Allowed: .txt accession lists, "
            ".fasta/.fa/.fna/.fsa/.gb/.gbk/.gbff genomes, and generated ecology metadata",
            summary,
        )

    if summary["accession_count"] + summary["genome_file_count"] <= 0:
        return "Submit at least one accession list or genome file", summary

    return None, summary


def apply_public_submission_policy(
    handler: BaseHTTPRequestHandler,
    settings: dict[str, object],
    uploads: list[dict[str, object]],
) -> tuple[str | None, dict[str, int]]:
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

    return validate_public_uploads(uploads, settings)


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
    bool_fields = [
        "run_genome_prep",
        "run_annotation",
        "run_bigscape",
        "run_summary",
        "run_crosswalk",
        "run_clinker",
        "execute_clinker",
        "run_figures",
        "run_nplinker",
        "force",
    ]
    for key in bool_fields:
        if key in payload:
            settings[key] = parse_payload_bool(payload, key, settings_bool(settings, key, False))

    settings["run_ncbi_install"] = parse_payload_bool(payload, "run_ncbi_install", False)
    settings["reuse_existing_layout"] = True
    if "run_summary" in payload and "run_crosswalk" not in payload:
        settings["run_crosswalk"] = settings["run_summary"]
    if "execute_clinker" not in payload and "run_clinker" in payload:
        settings["execute_clinker"] = settings["run_clinker"]
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
            index = Path(__file__).parent / "static" / "index.html"
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
                since = parse_int(query.get("since", ["0"])[0], 0)
                lines = read_logs(job_id)
                self._send_json(HTTPStatus.OK, {"lines": lines[max(0, since):], "total": len(lines)})
                return

            if len(parts) >= 5 and parts[4] == "files":
                if len(parts) == 5:
                    self._send_json(HTTPStatus.OK, {"files": job.get("result_files", [])})
                    return

                rel_path = urllib.parse.unquote("/".join(parts[5:]))
                base_dir = job_dir(job_id).resolve()
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

        runtime_error = validate_runtime_request(settings, worker_status())
        if runtime_error:
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

        lines = read_logs(job_id)
        job["log_count"] = len(lines)
        job["updated_at"] = now_iso()
        write_job(job)

        enqueue_job(job_id, cpus, settings)

        self._send_json(
            HTTPStatus.CREATED,
            {
                "job_id": job_id,
                "status": job["status"],
                "message": "Pipeline queued",
                "read_token": read_token,
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


def main() -> None:
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
