"""Read-only compatibility for jobs created before canonical public results."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable


_PUBLIC_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LEGACY_FIGURE_EXTENSIONS = {".svg", ".png", ".pdf", ".graphml", ".tsv"}


def legacy_public_run_id(
    internal_job_id: object,
    *,
    opaque_hmac: Callable[..., str],
) -> str:
    """Return the stable opaque alias used by pre-v1 public-result links."""

    job_id = str(internal_job_id or "")
    if not job_id:
        return ""
    return opaque_hmac(b"clusterweave-public-run-legacy-v1", job_id)


def legacy_job_result_format(job: dict[str, Any]) -> str:
    """Classify only formats that predate stored canonical public identities."""

    if _PUBLIC_RUN_ID_RE.fullmatch(str(job.get("public_run_id") or "")):
        return ""
    if job.get("read_token_hash") or job.get("read_token_hashes"):
        return "transitional"
    return "pre-public"


def legacy_additional_read_token_hashes(job: dict[str, Any]) -> tuple[str, ...]:
    """Read transitional email-token hashes without affecting canonical jobs."""

    if legacy_job_result_format(job) != "transitional":
        return ()
    values = job.get("read_token_hashes")
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, str) and value)


def legacy_result_path_public_shape(value: object) -> bool:
    """Recognize the bounded results/ figure layout used by old jobs."""

    raw = str(value or "").replace("\\", "/").lstrip("/")
    parts = raw.split("/")
    if (
        len(parts) < 2
        or parts[0].lower() != "results"
        or any(part in {"", ".", ".."} for part in parts)
    ):
        return False
    return Path(parts[-1]).suffix.lower() in _LEGACY_FIGURE_EXTENSIONS


def legacy_internal_metadata_job_id(route: str, job: dict[str, Any]) -> str:
    """Return an old metadata-bookmark ID, never a nested or canonical route."""

    if legacy_job_result_format(job) not in {"pre-public", "transitional"}:
        return ""
    parts = str(route or "").split("/")
    if len(parts) != 4 or parts[:3] != ["", "api", "jobs"]:
        return ""
    job_id = parts[3]
    if (
        not _JOB_ID_RE.fullmatch(job_id)
        or job_id in {".", ".."}
        or str(job.get("id") or "") != job_id
    ):
        return ""
    return job_id


def read_legacy_job_summary(
    directory: Path,
    *,
    compact: Callable[[dict[str, Any]], dict[str, Any]],
    valid_job_id: Callable[[object], bool],
) -> dict[str, Any] | None:
    """Project an old job.json into the current summary shape without writes."""

    try:
        job = json.loads((directory / "job.json").read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(job, dict):
        return None
    job_id = str(job.get("id") or "")
    if job_id != directory.name or not valid_job_id(job_id):
        return None
    return compact(job)


__all__ = [
    "legacy_additional_read_token_hashes",
    "legacy_internal_metadata_job_id",
    "legacy_job_result_format",
    "legacy_public_run_id",
    "legacy_result_path_public_shape",
    "read_legacy_job_summary",
]
