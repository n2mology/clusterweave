#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
JOBS_DIR = DATA_DIR / "jobs"
QUEUE_DIR = DATA_DIR / "queue"

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


def plus_days_iso(value: object, days: int) -> str:
    try:
        base = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        base = datetime.now()
    return (base + timedelta(days=days)).isoformat()


def apply_retention_metadata(job: dict[str, Any]) -> None:
    days = env_int("CLUSTERWEAVE_JOB_RETENTION_DAYS", 30, minimum=1)
    job["retention_days"] = days

    status = str(job.get("status", "")).lower()
    if status == "success":
        job.setdefault("completed_at", job.get("updated_at") or now_iso())
        job.pop("failed_at", None)
        job["expires_at"] = plus_days_iso(job["completed_at"], days)
        return

    if status == "failed":
        job.setdefault("failed_at", job.get("updated_at") or now_iso())
        job.pop("completed_at", None)
        job["expires_at"] = plus_days_iso(job["failed_at"], days)
        return

    job.pop("completed_at", None)
    job.pop("failed_at", None)
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


def read_job(job_id: str) -> dict[str, Any] | None:
    path = job_meta_path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_job(job: dict[str, Any]) -> None:
    apply_retention_metadata(job)
    path = job_meta_path(job["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


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
