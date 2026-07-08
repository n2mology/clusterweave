#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from job_store import (
        DATA_DIR,
        QUEUE_DIR,
        append_log,
        job_cancel_requested,
        job_delete_path,
        job_dir,
        list_jobs,
        now_iso,
        read_job,
        read_logs,
        write_job,
        write_logs,
    )
    from canonical_pipeline import Job, JobStatus, run_pipeline
    from notifications import maybe_send_terminal_notification
    from runtime_capabilities import runtime_health
except ImportError:  # pragma: no cover - package-style imports in local tests
    from .job_store import (
        DATA_DIR,
        QUEUE_DIR,
        append_log,
        job_cancel_requested,
        job_delete_path,
        job_dir,
        list_jobs,
        now_iso,
        read_job,
        read_logs,
        write_job,
        write_logs,
    )
    from .canonical_pipeline import Job, JobStatus, run_pipeline
    from .notifications import maybe_send_terminal_notification
    from .runtime_capabilities import runtime_health

POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))
WORKER_CONCURRENCY = max(1, int(os.environ.get("WORKER_CONCURRENCY", "1")))
EXECUTOR = os.environ.get("CLUSTERWEAVE_EXECUTOR", "local").strip().lower() or "local"
WORKER_DIR = DATA_DIR / "worker"
WORKER_STATUS_PATH = WORKER_DIR / "status.json"
CANCELLED_ERROR = "Cancelled by administrator"


def _docker(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["docker", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None


def _running_container_ids_for_job(job_id: str) -> list[str]:
    ids: set[str] = set()
    labeled = _docker(["ps", "-q", "--filter", f"label=clusterweave.job_id={job_id}"])
    if labeled and labeled.returncode == 0:
        ids.update(line.strip() for line in labeled.stdout.splitlines() if line.strip())

    all_running = _docker(["ps", "-q"])
    running_ids = [line.strip() for line in (all_running.stdout if all_running else "").splitlines() if line.strip()]
    if running_ids:
        inspected = _docker(
            [
                "inspect",
                "--format",
                "{{.Id}}\t{{json .Config.Cmd}}\t{{json .Mounts}}\t{{json .Config.Labels}}",
                *running_ids,
            ],
            timeout=30,
        )
        if inspected and inspected.returncode == 0:
            for line in inspected.stdout.splitlines():
                container_id, _, details = line.partition("\t")
                if f"/data/jobs/{job_id}" in details or f"clusterweave.job_id\":\"{job_id}" in details:
                    ids.add(container_id.strip())
    return sorted(ids)


def stop_job_containers(job_id: str) -> None:
    ids = _running_container_ids_for_job(job_id)
    if not ids:
        return
    append_log(job_id, f"Stopping {len(ids)} active tool container(s) for cancelled job.")
    _docker(["stop", "--time", "10", *ids], timeout=60)


def finalize_cancelled_job(job_id: str, cpus: int, settings: dict[str, Any], detail: str = CANCELLED_ERROR) -> None:
    meta = read_job(job_id)
    if meta is not None:
        job = build_job_from_meta(meta)
        job.status = JobStatus.FAILED
        job.stage = "cancelled"
        job.error = detail
        job.add_log(f"Cancelled: {detail}.")
        persist_job(job, cpus, settings)
    if job_delete_path(job_id).exists():
        shutil.rmtree(job_dir(job_id), ignore_errors=True)


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
            "executor": EXECUTOR,
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
            cpus = max(1, cpus)
            if job_cancel_requested(job_id):
                append_log(job_id, "Cancelled queued job before worker start.")
                finalize_cancelled_job(job_id, cpus, settings, "Cancelled before worker start")
                continue
            return job_id, cpus, settings
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

        if job_cancel_requested(job_id):
            append_log(job_id, "Cancelled interrupted running job during worker recovery.")
            finalize_cancelled_job(job_id, cpus, settings, "Cancelled during worker recovery")
            continue

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


def runtime_slurm_job_id() -> str:
    for key in ["SLURM_JOB_ID", "SLURM_JOBID"]:
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    return ""


def apply_runtime_scheduler_metadata(payload: dict[str, Any]) -> None:
    runtime_job_id = runtime_slurm_job_id()
    scheduler = payload.get("scheduler")
    scheduler_payload = dict(scheduler) if isinstance(scheduler, dict) else {}
    scheduler_job_id = str(scheduler_payload.get("job_id") or payload.get("slurm_job_id") or "").strip()
    slurm_job_id = scheduler_job_id or runtime_job_id
    if not slurm_job_id:
        return

    scheduler_payload.setdefault("kind", "slurm")
    scheduler_payload.setdefault("job_id", slurm_job_id)
    scheduler_payload.setdefault("state", "RUNNING")
    scheduler_payload["clusterweave_status"] = str(payload.get("status") or scheduler_payload.get("clusterweave_status") or "")
    scheduler_payload.setdefault("submit_script", "slurm/submit.sbatch")
    scheduler_payload.setdefault("queue_payload", "slurm/queue_payload.json")
    scheduler_payload.setdefault("stdout", "slurm/slurm-%j.out")
    scheduler_payload.setdefault("stderr", "slurm/slurm-%j.err")
    scheduler_payload["updated_at"] = now_iso()

    payload["executor"] = "slurm"
    payload["slurm_job_id"] = slurm_job_id
    payload["scheduler"] = scheduler_payload


def persist_job(job: Job, cpus: int, settings: dict[str, Any]) -> None:
    write_logs(job.id, job.log_lines)
    payload = dict(read_job(job.id) or {})
    payload.update(job.to_dict())
    payload["status"] = job.status.value
    payload["log_count"] = len(job.log_lines)
    payload["cpus"] = cpus
    payload["settings"] = settings
    payload["updated_at"] = now_iso()
    apply_runtime_scheduler_metadata(payload)
    write_job(payload)


async def process_one(job_id: str, cpus: int, queued_settings: dict[str, Any]) -> None:
    meta = read_job(job_id)
    if meta is None:
        return

    settings = dict(meta.get("settings") or {})
    settings.update(queued_settings)

    if job_cancel_requested(job_id):
        raise asyncio.CancelledError(CANCELLED_ERROR)

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
    except asyncio.CancelledError:
        stop_job_containers(job_id)
        finalize_cancelled_job(job_id, cpus, settings)
        return
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
    cancelling: set[str] = set()
    while True:
        for job_id, task in list(active.items()):
            if job_cancel_requested(job_id) and not task.done():
                if job_id not in cancelling:
                    cancelling.add(job_id)
                    append_log(job_id, "Worker observed cancellation marker; stopping active workflow task.")
                    stop_job_containers(job_id)
                    task.cancel()
                continue
            if not task.done():
                continue
            active.pop(job_id, None)
            cancelling.discard(job_id)
            try:
                task.result()
            except asyncio.CancelledError:
                pass
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


def _payload_from_path(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    payload_path = Path(path)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _one_shot_claim(job_id: str, *, cpus: int | None = None, queue_payload: str | None = None) -> tuple[int, dict[str, Any]]:
    meta = read_job(job_id)
    if meta is None:
        raise ValueError(f"Job '{job_id}' not found")

    payload = _payload_from_path(queue_payload)
    settings = dict(meta.get("settings") or {})
    queued_settings = payload.get("settings")
    if isinstance(queued_settings, dict):
        settings.update(queued_settings)

    if cpus is None:
        raw_cpus = payload.get("cpus", meta.get("cpus", 4))
        try:
            cpus = int(raw_cpus)
        except (TypeError, ValueError):
            cpus = 4
    return max(1, cpus), settings


def run_one_shot(job_id: str, *, cpus: int | None = None, queue_payload: str | None = None) -> int:
    try:
        resolved_cpus, settings = _one_shot_claim(job_id, cpus=cpus, queue_payload=queue_payload)
        asyncio.run(process_claim(job_id, resolved_cpus, settings))
    except Exception as exc:
        print(f"ClusterWeave one-shot worker failed for {job_id}: {exc}", file=sys.stderr)
        return 1

    meta = read_job(job_id)
    if meta is None:
        return 1
    return 1 if str(meta.get("status") or "").lower() == JobStatus.FAILED.value else 0


async def slurm_loop() -> None:
    try:
        from slurm_backend import SlurmBackend
    except ImportError:  # pragma: no cover - package-style imports in local tests
        from .slurm_backend import SlurmBackend

    backend = SlurmBackend(claim_next_job=claim_next_job, status_writer=write_worker_status)
    await backend.loop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClusterWeave queue worker")
    parser.add_argument("--once", metavar="JOB_ID", help="run exactly one already-created ClusterWeave job")
    parser.add_argument("--queue-payload", help="queue payload JSON captured by a scheduler submitter")
    parser.add_argument("--cpus", type=int, help="override CPU count for --once")
    args = parser.parse_args(argv)

    if args.once:
        return run_one_shot(args.once, cpus=args.cpus, queue_payload=args.queue_payload)

    if EXECUTOR == "slurm":
        asyncio.run(slurm_loop())
        return 0
    if EXECUTOR != "local":
        print(f"Unknown CLUSTERWEAVE_EXECUTOR={EXECUTOR!r}; expected 'local' or 'slurm'.", file=sys.stderr)
        return 2

    asyncio.run(worker_loop())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
