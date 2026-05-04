#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from job_store import QUEUE_DIR, now_iso, read_job, read_logs, write_job, write_logs
from pipeline import Job, JobStatus, run_pipeline

POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))


def claim_next_job() -> tuple[str, int, dict[str, Any]] | None:
    for queue_path in sorted(QUEUE_DIR.glob("*.json")):
        working = queue_path.with_suffix(".working")
        try:
            queue_path.rename(working)
        except FileNotFoundError:
            continue
        except OSError:
            continue

        try:
            payload = json.loads(working.read_text(encoding="utf-8"))
            job_id = str(payload["job_id"])
            cpus = int(payload.get("cpus", 4))
            settings = payload.get("settings") or {}
            if not isinstance(settings, dict):
                settings = {}
            return job_id, max(1, cpus), settings
        finally:
            working.unlink(missing_ok=True)
    return None


def build_job_from_meta(meta: dict) -> Job:
    status = meta.get("status", "pending")
    try:
        job_status = JobStatus(status)
    except ValueError:
        job_status = JobStatus.PENDING

    job = Job(
        id=str(meta["id"]),
        name=str(meta.get("name", "job")),
        status=job_status,
        created_at=str(meta.get("created_at", now_iso())),
        updated_at=str(meta.get("updated_at", now_iso())),
        stage=str(meta.get("stage", "queued")),
        log_lines=read_logs(str(meta["id"])),
        result_files=list(meta.get("result_files", [])),
        error=meta.get("error"),
    )
    return job


def persist_job(job: Job, cpus: int, settings: dict[str, Any]) -> None:
    write_logs(job.id, job.log_lines)
    payload = job.to_dict()
    payload["status"] = job.status.value
    payload["log_count"] = len(job.log_lines)
    payload["cpus"] = cpus
    payload["settings"] = settings
    payload["updated_at"] = now_iso()
    write_job(payload)


async def process_one(job_id: str, cpus: int, queued_settings: dict[str, Any]) -> None:
    meta = read_job(job_id)
    if meta is None:
        return

    settings = dict(meta.get("settings") or {})
    settings.update(queued_settings)

    job = build_job_from_meta(meta)

    def on_change() -> None:
        persist_job(job, cpus, settings)

    job.on_change = on_change
    persist_job(job, cpus, settings)

    input_dir = Path(os.environ.get("DATA_DIR", "/data")) / "jobs" / job_id / "inputs"
    files = sorted([p for p in input_dir.iterdir() if p.is_file()])
    await run_pipeline(
        job=job,
        input_files=files,
        job_dir=input_dir.parent,
        cpus=cpus,
        settings=settings,
        on_update=on_change,
    )
    persist_job(job, cpus, settings)


def main() -> None:
    print("ClusterWeave worker started.")
    while True:
        claim = claim_next_job()
        if claim is None:
            time.sleep(POLL_SECONDS)
            continue

        job_id, cpus, settings = claim
        try:
            asyncio.run(process_one(job_id, cpus, settings))
        except Exception as exc:
            meta = read_job(job_id)
            if meta is not None:
                job = build_job_from_meta(meta)
                job.status = JobStatus.FAILED
                job.error = str(exc)
                job.add_log(f"FATAL: {exc}")
                persist_job(job, cpus, settings)


if __name__ == "__main__":
    main()
