#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

try:
    from job_store import now_iso, read_job, write_job
    from public_results import public_run_id_for_job
except ImportError:  # pragma: no cover - package-style imports in local tests
    from .job_store import now_iso, read_job, write_job
    from .public_results import public_run_id_for_job


TERMINAL_STATUSES = {"success", "failed"}


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def smtp_enabled() -> bool:
    return env_bool("CLUSTERWEAVE_SMTP_ENABLED", False)


def validate_email(value: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value.strip()))


def job_token_hash(token: str) -> str:
    secret = os.environ.get("CLUSTERWEAVE_JOB_TOKEN_SECRET", "")
    secret_bytes = secret.encode("utf-8") if secret else b"clusterweave-job-read-token-v1"
    return hmac.new(secret_bytes, token.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_job_read_token() -> str:
    return secrets.token_urlsafe(32)


def add_email_read_token(job: dict[str, Any]) -> str:
    token = generate_job_read_token()
    token_hash = job_token_hash(token)
    hashes = [h for h in job.get("read_token_hashes", []) if isinstance(h, str) and h]
    if token_hash not in hashes:
        hashes.append(token_hash)
    job["read_token_hashes"] = hashes
    job["email_read_token_created_at"] = now_iso()
    return token


def base_url_for_job(job: dict[str, Any]) -> str:
    base = str(job.get("public_base_url") or os.environ.get("CLUSTERWEAVE_PUBLIC_BASE_URL") or "").strip()
    if not base:
        base = "http://localhost:8080/"
    return base.rstrip("/") + "/"


def result_link(job: dict[str, Any], read_token: str) -> str:
    base = base_url_for_job(job)
    return f"{base}#/results/{public_run_id_for_job(job)}/{read_token}"


def retention_phrase(job: dict[str, Any]) -> str:
    days = job.get("retention_days")
    if days == "never":
        return "until an administrator removes them"
    if days == 30 or str(days) == "30":
        return "for one month"
    return f"for {days} days"


def docs_link() -> str:
    return os.environ.get("CLUSTERWEAVE_CITATION_URL", "").strip() or "https://github.com/n2mology/clusterweave"


def display_timestamp(value: Any, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    return text.replace("T", " ", 1)


def public_stage_name(stage: str) -> str:
    raw = str(stage or "").lower()
    if "accession" in raw or "genome" in raw or "layout" in raw or "ncbi" in raw:
        return "Prep / NCBI retrieval"
    if "annotation" in raw or "bgc" in raw or "canonical clusterweave workflow" in raw:
        return "Annotation / BGC detection"
    if "big" in raw:
        return "BiG-SCAPE"
    if "summary" in raw or "crosswalk" in raw:
        return "Summary"
    if "clinker" in raw or "synteny" in raw:
        return "clinker"
    if "figure" in raw:
        return "Figures"
    return "Workflow"


def stage_enabled(job: dict[str, Any], name: str, default: bool = True) -> bool:
    settings = job.get("settings") if isinstance(job.get("settings"), dict) else {}
    value = settings.get(name)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def workflow_summary_lines(job: dict[str, Any]) -> list[str]:
    status = str(job.get("status") or "").lower()
    complete = status == "success"
    return [
        f"- Prep / NCBI retrieval: {'complete' if complete else 'see result status'}",
        f"- Annotation / BGC detection: {'complete' if complete and stage_enabled(job, 'run_annotation') else 'skipped' if not stage_enabled(job, 'run_annotation') else 'see result status'}",
        f"- BiG-SCAPE: {'complete' if complete and stage_enabled(job, 'run_bigscape') else 'skipped' if not stage_enabled(job, 'run_bigscape') else 'see result status'}",
        f"- Summary: {'complete' if complete and stage_enabled(job, 'run_summary') else 'skipped' if not stage_enabled(job, 'run_summary') else 'see result status'}",
        f"- clinker: {'complete' if complete and stage_enabled(job, 'run_clinker') else 'skipped' if not stage_enabled(job, 'run_clinker') else 'see result status'}",
        f"- Figures: {'complete' if complete and stage_enabled(job, 'run_figures') else 'skipped' if not stage_enabled(job, 'run_figures') else 'see result status'}",
    ]


def input_summary_lines(job: dict[str, Any]) -> list[str]:
    summary = job.get("input_summary") if isinstance(job.get("input_summary"), dict) else {}
    settings = job.get("settings") if isinstance(job.get("settings"), dict) else {}
    ecology = "enabled" if settings.get("run_ecology_analysis") else "disabled"
    return [
        f"- Accessions: {summary.get('accession_count', 0)}",
        f"- Genome files: {summary.get('genome_file_count', 0)}",
        f"- Ecology-aware analysis: {ecology}",
    ]


def result_status_label(status: str) -> str:
    normalized = str(status or "").lower()
    if normalized == "success":
        return "complete"
    if normalized == "failed":
        return "failed"
    return normalized or "unknown"


def plural_count(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def submission_input_phrase(job: dict[str, Any]) -> str:
    summary = job.get("input_summary") if isinstance(job.get("input_summary"), dict) else {}
    accessions = int(summary.get("accession_count") or 0)
    genomes = int(summary.get("genome_file_count") or 0)
    parts: list[str] = []
    if accessions:
        parts.append(plural_count(accessions, "NCBI accession"))
    if genomes:
        parts.append(plural_count(genomes, "uploaded genome file"))
    if not parts:
        return "with the submitted input"
    if len(parts) == 1:
        return f"with {parts[0]}"
    return f"with {' and '.join(parts)}"


def result_retention_line(job: dict[str, Any]) -> str:
    phrase = retention_phrase(job)
    expires = str(job.get("expires_at") or "").strip()
    if expires:
        return f"Results will be kept {phrase} and then deleted automatically on {display_timestamp(expires)}."
    return f"Results will be kept {phrase}."


def sanitized_failure_reason(job: dict[str, Any]) -> str:
    text = str(job.get("error") or job.get("stage") or "").lower()
    if "accession" in text or "ncbi" in text:
        return "NCBI accession retrieval or validation did not complete."
    if "genome" in text or "upload" in text or "input" in text:
        return "No supported genome input was available for one of the workflow stages."
    if "runtime" in text or "unavailable" in text or "missing" in text:
        return "A required public workflow runtime was unavailable."
    return "A workflow stage did not complete successfully."


def build_job_email(job: dict[str, Any], link: str, access_code: str = "") -> EmailMessage:
    status = str(job.get("status") or "unknown")
    status_label = result_status_label(status)
    job_id = public_run_id_for_job(job) or "unknown"
    project = str(job.get("project_name") or job.get("name") or "ClusterWeave project")
    submitted = display_timestamp(job.get("created_at"))
    result_access_code = access_code or link.rsplit("/", 1)[-1]
    result_lines = [
        "You can find the results at" if status == "success" else "You can review logs and any partial results at",
        link,
        "",
        f"Result access code: {result_access_code}",
    ]

    lead = (
        f"The ClusterWeave job {job_id} you submitted on {submitted} for project '{project}' "
        f"{submission_input_phrase(job)} has finished with status {status_label}."
    )

    if status == "success":
        body = [
            "Dear ClusterWeave user,",
            "",
            lead,
            "",
            *result_lines,
            "",
            result_retention_line(job),
            "",
            "If you found ClusterWeave useful, please cite the project using",
            docs_link(),
            "",
        ]
    else:
        body = [
            "Dear ClusterWeave user,",
            "",
            lead,
            "",
            "ClusterWeave could not complete this job.",
            "",
            f"Failed stage: {public_stage_name(str(job.get('stage') or ''))}",
            f"Likely issue: {sanitized_failure_reason(job)}",
            "Suggested fixes:",
            "- Check that NCBI accessions are valid and one per line.",
            "- Check that uploaded genomes use supported extensions: .fasta, .fa, .fna, .fsa, .gb, .gbk, .gbff.",
            "- Submit only public or releasable data; for sensitive or advanced troubleshooting, run ClusterWeave locally with Docker.",
            "",
            *result_lines,
            "",
            result_retention_line(job),
            "",
            "For help and citation instructions, see",
            docs_link(),
            "",
        ]

    message = EmailMessage()
    message["Subject"] = f"ClusterWeave job {job_id} finished: {status_label}"
    message["To"] = str(job.get("notify_email") or "")
    message["From"] = (
        os.environ.get("CLUSTERWEAVE_SMTP_FROM")
        or os.environ.get("CLUSTERWEAVE_EMAIL_FROM")
        or os.environ.get("CLUSTERWEAVE_SMTP_USERNAME")
        or "clusterweave@localhost"
    )
    message.set_content("\n".join(body), cte="8bit")
    return message


def deliver_email(message: EmailMessage) -> None:
    outbox = os.environ.get("CLUSTERWEAVE_SMTP_OUTBOX_DIR", "").strip()
    if outbox:
        out_dir = Path(outbox)
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_subject = re.sub(r"[^A-Za-z0-9._-]+", "_", str(message["Subject"]))[:80]
        (out_dir / f"{safe_subject}.eml").write_text(message.as_string(), encoding="utf-8")
        return

    host = os.environ.get("CLUSTERWEAVE_SMTP_HOST", "").strip()
    if not host:
        raise RuntimeError("SMTP host is not configured")
    port = int(os.environ.get("CLUSTERWEAVE_SMTP_PORT", "587"))
    username = os.environ.get("CLUSTERWEAVE_SMTP_USERNAME", "").strip()
    password = os.environ.get("CLUSTERWEAVE_SMTP_PASSWORD", "")
    timeout = float(os.environ.get("CLUSTERWEAVE_SMTP_TIMEOUT", "10"))
    use_ssl = env_bool("CLUSTERWEAVE_SMTP_SSL", False)
    use_tls = env_bool("CLUSTERWEAVE_SMTP_TLS", True)
    smtp_factory = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP

    with smtp_factory(host, port, timeout=timeout) as smtp:
        if use_tls and not use_ssl:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


def maybe_send_terminal_notification(job_id: str) -> dict[str, Any] | None:
    if not smtp_enabled():
        return None
    job = read_job(job_id)
    if not job:
        return None
    status = str(job.get("status") or "").lower()
    if status not in TERMINAL_STATUSES:
        return None
    email = str(job.get("notify_email") or "").strip()
    if not email or not validate_email(email):
        return None
    notification = job.get("notification") if isinstance(job.get("notification"), dict) else {}
    if notification.get("status") == status and notification.get("sent_at"):
        return notification

    token = add_email_read_token(job)
    write_job(job)
    link = result_link(job, token)
    message = build_job_email(job, link, token)
    try:
        deliver_email(message)
        outcome = {
            "status": status,
            "sent_at": now_iso(),
            "delivery": "sent",
        }
    except Exception:
        outcome = {
            "status": status,
            "attempted_at": now_iso(),
            "delivery": "failed",
            "error": "SMTP delivery failed",
        }
    latest = read_job(job_id) or job
    latest["notification"] = outcome
    write_job(latest)
    return outcome
