#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
JOBS_DIR = DATA_DIR / "jobs"
QUEUE_DIR = DATA_DIR / "queue"
RETENTION_DIR = DATA_DIR / "retention"
RETENTION_TOTALS_PATH = RETENTION_DIR / "sweep_totals.json"

JOBS_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now().isoformat()


def env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def configured_retention_days() -> int | None:
    raw = os.environ.get("CLUSTERWEAVE_JOB_RETENTION_DAYS", "30").strip().lower()
    if raw in {"0", "never", "none"}:
        if env_bool("CLUSTERWEAVE_ALLOW_NEVER_EXPIRE_JOBS", False):
            return None
        raise ValueError(
            "CLUSTERWEAVE_JOB_RETENTION_DAYS=0/never requires "
            "CLUSTERWEAVE_ALLOW_NEVER_EXPIRE_JOBS=1 and public admin documentation"
        )
    try:
        days = int(raw)
    except (TypeError, ValueError):
        days = 30
    return max(1, days)


def plus_days_iso(value: object, days: int) -> str:
    try:
        base = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        base = datetime.now()
    return (base + timedelta(days=days)).isoformat()


def apply_retention_metadata(job: dict[str, Any]) -> None:
    days = configured_retention_days()
    if days is None:
        job["retention_days"] = "never"
        job["expires_at"] = None
    else:
        job["retention_days"] = days

    status = str(job.get("status", "")).lower()
    if status == "success":
        job.setdefault("completed_at", job.get("updated_at") or now_iso())
        job.pop("failed_at", None)
        if days is not None:
            job["expires_at"] = plus_days_iso(job["completed_at"], days)
        return

    if status == "failed":
        job.setdefault("failed_at", job.get("updated_at") or now_iso())
        job.pop("completed_at", None)
        if days is not None:
            job["expires_at"] = plus_days_iso(job["failed_at"], days)
        return

    job.pop("completed_at", None)
    job.pop("failed_at", None)
    if days is not None:
        job["expires_at"] = plus_days_iso(job.get("created_at") or now_iso(), days)


def ts_line(message: str) -> str:
    ts = datetime.now().strftime("%H:%M:%S")
    return f"[{ts}] {message}"


def job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def job_meta_path(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def job_logs_path(job_id: str) -> Path:
    return job_dir(job_id) / "logs.txt"


def job_cancel_path(job_id: str) -> Path:
    return job_dir(job_id) / "cancel.requested"


def job_delete_path(job_id: str) -> Path:
    return job_dir(job_id) / "delete.requested"


def job_cancel_requested(job_id: str) -> bool:
    return job_cancel_path(job_id).exists()


def request_job_cancel(job_id: str, reason: str = "Cancellation requested", *, delete_after_cancel: bool = False) -> None:
    target = job_dir(job_id)
    target.mkdir(parents=True, exist_ok=True)
    payload = {"requested_at": now_iso(), "reason": reason, "delete_after_cancel": delete_after_cancel}
    job_cancel_path(job_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if delete_after_cancel:
        job_delete_path(job_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_job(job_id: str) -> dict[str, Any] | None:
    path = job_meta_path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def write_job(job: dict[str, Any]) -> None:
    apply_retention_metadata(job)
    path = job_meta_path(job["id"])
    atomic_write_text(path, json.dumps(job, ensure_ascii=False, indent=2))


def list_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for path in sorted(JOBS_DIR.glob("*/job.json")):
        try:
            jobs.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    jobs.sort(key=lambda j: j.get("updated_at", ""), reverse=True)
    return jobs


def read_logs(job_id: str) -> list[str]:
    path = job_logs_path(job_id)
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def write_logs(job_id: str, lines: list[str]) -> None:
    path = job_logs_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "\n".join(lines)
    if data:
        data += "\n"
    path.write_text(data, encoding="utf-8")


def append_log(job_id: str, message: str) -> str:
    line = ts_line(message)
    path = job_logs_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return line


def path_size_and_file_count(path: Path) -> tuple[int, int]:
    total = 0
    files = 0
    if not path.exists():
        return total, files
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        files += 1
        try:
            total += child.stat().st_size
        except OSError:
            continue
    return total, files


def read_retention_totals() -> dict[str, Any]:
    if not RETENTION_TOTALS_PATH.exists():
        return {
            "expired_jobs_deleted": 0,
            "expired_files_deleted": 0,
            "expired_bytes_deleted": 0,
            "last_sweep_at": None,
        }
    try:
        payload = json.loads(RETENTION_TOTALS_PATH.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return {
        "expired_jobs_deleted": int(payload.get("expired_jobs_deleted") or 0),
        "expired_files_deleted": int(payload.get("expired_files_deleted") or 0),
        "expired_bytes_deleted": int(payload.get("expired_bytes_deleted") or 0),
        "last_sweep_at": payload.get("last_sweep_at"),
    }


def write_retention_totals(totals: dict[str, Any]) -> None:
    RETENTION_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(RETENTION_TOTALS_PATH, json.dumps(totals, ensure_ascii=False, indent=2))


def job_is_expired(job: dict[str, Any], now: datetime | None = None) -> bool:
    expires_at = job.get("expires_at")
    if not expires_at:
        return False
    now_dt = now or datetime.now()
    try:
        expires_dt = datetime.fromisoformat(str(expires_at))
    except ValueError:
        return False
    return expires_dt <= now_dt


def sweep_expired_jobs(now: datetime | None = None) -> dict[str, Any]:
    totals = read_retention_totals()
    deleted_jobs = 0
    deleted_files = 0
    deleted_bytes = 0

    for job in list_jobs():
        job_id = str(job.get("id") or "")
        if not job_id or not job_is_expired(job, now):
            continue
        target = job_dir(job_id)
        size, files = path_size_and_file_count(target)
        shutil.rmtree(target, ignore_errors=True)
        for q in QUEUE_DIR.glob(f"{job_id}*.json"):
            q.unlink(missing_ok=True)
        for q in QUEUE_DIR.glob(f"{job_id}*.working"):
            q.unlink(missing_ok=True)
        deleted_jobs += 1
        deleted_files += files
        deleted_bytes += size

    totals["expired_jobs_deleted"] = int(totals.get("expired_jobs_deleted") or 0) + deleted_jobs
    totals["expired_files_deleted"] = int(totals.get("expired_files_deleted") or 0) + deleted_files
    totals["expired_bytes_deleted"] = int(totals.get("expired_bytes_deleted") or 0) + deleted_bytes
    totals["last_sweep_at"] = now_iso()
    write_retention_totals(totals)
    return {
        "deleted_jobs": deleted_jobs,
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "totals": totals,
    }
