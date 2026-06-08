#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

try:
    from job_store import DATA_DIR, QUEUE_DIR, append_log, list_jobs, now_iso, read_job, read_logs, write_job, write_logs
    from canonical_pipeline import Job, JobStatus, run_pipeline
    from notifications import maybe_send_terminal_notification
    from runtime_capabilities import runtime_health
except ImportError:  # pragma: no cover - package-style imports in local tests
    from .job_store import DATA_DIR, QUEUE_DIR, append_log, list_jobs, now_iso, read_job, read_logs, write_job, write_logs
    from .canonical_pipeline import Job, JobStatus, run_pipeline
    from .notifications import maybe_send_terminal_notification
    from .runtime_capabilities import runtime_health

POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))
WORKER_CONCURRENCY = max(1, int(os.environ.get("WORKER_CONCURRENCY", "1")))
WORKER_DIR = DATA_DIR / "worker"
WORKER_STATUS_PATH = WORKER_DIR / "status.json"


def state_progress(state: str) -> int:
    return {
        "bootstrapping": 0,
        "ready": 100,
        "idle": 100,
        "processing": 100,
        "error": 100,
    }.get(state, 0)


def write_worker_status(
    state: str,
    detail: str = "",
    substep: str = "",
    active_jobs: list[str] | None = None,
) -> None:
    runtime = runtime_health()
    WORKER_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ready": state in {"ready", "idle", "processing"},
        "state": state,
        "phase": state,
        "progress": state_progress(state),
        "detail": detail,
        "substep": substep,
        "updated_at": now_iso(),
        "runtime": {
            "mode": runtime.get("mode"),
            "engine": runtime.get("engine"),
            "docker_ready": runtime.get("docker_ready"),
            "docker_socket_enabled": runtime.get("docker_socket_enabled"),
        },
        "worker": {
            "concurrency": WORKER_CONCURRENCY,
            "active_jobs": active_jobs or [],
            "active_count": len(active_jobs or []),
        },
        "capabilities": runtime,
    }
    WORKER_STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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


def queue_path_for_job(job_id: str) -> Path:
    return QUEUE_DIR / f"{job_id}.json"


def stale_queue_paths(job_id: str) -> list[Path]:
    return [*QUEUE_DIR.glob(f"{job_id}*.json"), *QUEUE_DIR.glob(f"{job_id}*.working")]


def queue_payload(job_id: str, cpus: int, settings: dict[str, Any]) -> dict[str, Any]:
    return {"job_id": job_id, "cpus": cpus, "settings": settings}


def stage_has_passed_genome_prep(stage: object) -> bool:
    normalized = str(stage or "").strip().lower()
    if not normalized:
        return False
    prep_stages = {
        "queued",
        "preparing clusterweave project layout",
        "installing ncbi cli",
        "preparing genomes from accessions",
    }
    return normalized not in prep_stages


def recover_orphaned_running_jobs() -> list[str]:
    recovered: list[str] = []
    for meta in list_jobs():
        job_id = str(meta.get("id") or "")
        if not job_id or str(meta.get("status") or "").lower() != JobStatus.RUNNING.value:
            continue
        if queue_path_for_job(job_id).exists():
            continue

        for path in stale_queue_paths(job_id):
            path.unlink(missing_ok=True)

        settings = dict(meta.get("settings") or meta.get("submission_settings") or {})
        settings["reuse_existing_layout"] = True
        previous_stage = str(meta.get("stage") or "")
        if stage_has_passed_genome_prep(previous_stage):
            settings["run_genome_prep"] = False
        try:
            cpus = max(1, int(meta.get("cpus", 4)))
        except (TypeError, ValueError):
            cpus = 4

        append_log(job_id, "Recovered interrupted running job after worker restart; re-queued for worker slot.")
        if stage_has_passed_genome_prep(previous_stage):
            append_log(
                job_id,
                "Recovery resume skipped accession genome prep because the interrupted run had already passed genome preparation.",
            )
        meta["status"] = JobStatus.PENDING.value
        meta["stage"] = "queued"
        meta["error"] = None
        meta["cpus"] = cpus
        meta["settings"] = settings
        meta["log_count"] = len(read_logs(job_id))
        meta["updated_at"] = now_iso()
        write_job(meta)
        queue_path_for_job(job_id).write_text(json.dumps(queue_payload(job_id, cpus, settings)), encoding="utf-8")
        recovered.append(job_id)
    return recovered


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
        project_name=str(meta.get("project_name", "")),
        result_root=str(meta.get("result_root", "")),
    )
    return job


def persist_job(job: Job, cpus: int, settings: dict[str, Any]) -> None:
    write_logs(job.id, job.log_lines)
    payload = dict(read_job(job.id) or {})
    payload.update(job.to_dict())
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
    maybe_send_terminal_notification(job_id)


async def process_claim(job_id: str, cpus: int, settings: dict[str, Any]) -> None:
    try:
        await process_one(job_id, cpus, settings)
    except Exception as exc:
        meta = read_job(job_id)
        if meta is not None:
            job = build_job_from_meta(meta)
            job.status = JobStatus.FAILED
            job.error = str(exc)
            job.add_log(f"FATAL: {exc}")
            persist_job(job, cpus, settings)
            maybe_send_terminal_notification(job_id)
        raise


async def worker_loop() -> None:
    print(f"ClusterWeave worker started. concurrency={WORKER_CONCURRENCY}")
    recovered = recover_orphaned_running_jobs()
    if recovered:
        write_worker_status("ready", f"Recovered {len(recovered)} interrupted job(s)", ", ".join(recovered))
    else:
        write_worker_status("ready", f"Worker loop started (concurrency={WORKER_CONCURRENCY})")
    active: dict[str, asyncio.Task[None]] = {}
    while True:
        for job_id, task in list(active.items()):
            if not task.done():
                continue
            active.pop(job_id, None)
            try:
                task.result()
            except Exception as exc:
                write_worker_status("error", str(exc), active_jobs=sorted(active))

        while len(active) < WORKER_CONCURRENCY:
            claim = claim_next_job()
            if claim is None:
                break
            job_id, cpus, settings = claim
            active[job_id] = asyncio.create_task(process_claim(job_id, cpus, settings))

        if active:
            ids = sorted(active)
            write_worker_status("processing", f"Processing {len(ids)} job(s)", ", ".join(ids), active_jobs=ids)
        else:
            write_worker_status("idle", "Waiting for queued jobs")
        await asyncio.sleep(POLL_SECONDS)


def main() -> None:
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
