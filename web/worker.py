#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from job_store import (
        DATA_DIR,
        QUEUE_DIR,
        append_log,
        append_log_lines,
        atomic_write_text,
        job_cancel_requested,
        job_delete_path,
        job_dir,
        list_jobs,
        now_iso,
        read_job,
        read_logs,
        write_job,
    )
    from canonical_pipeline import Job, JobStatus, run_pipeline
    from notifications import maybe_send_terminal_notification
    from resource_policy import MemoryFormula, estimate_job_resources, genome_count_from_input_summary
    from runtime_capabilities import runtime_health
except ImportError:  # pragma: no cover - package-style imports in local tests
    from .job_store import (
        DATA_DIR,
        QUEUE_DIR,
        append_log,
        append_log_lines,
        atomic_write_text,
        job_cancel_requested,
        job_delete_path,
        job_dir,
        list_jobs,
        now_iso,
        read_job,
        read_logs,
        write_job,
    )
    from .canonical_pipeline import Job, JobStatus, run_pipeline
    from .notifications import maybe_send_terminal_notification
    from .resource_policy import MemoryFormula, estimate_job_resources, genome_count_from_input_summary
    from .runtime_capabilities import runtime_health

POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))
PENDING_RECOVERY_SECONDS = max(
    5.0, float(os.environ.get("WORKER_PENDING_RECOVERY_SECONDS", "30.0"))
)
PENDING_RECOVERY_GRACE_SECONDS = max(
    5.0, float(os.environ.get("WORKER_PENDING_RECOVERY_GRACE_SECONDS", "60.0"))
)
WORKER_CONCURRENCY = max(1, int(os.environ.get("WORKER_CONCURRENCY", "1")))
EXECUTOR = os.environ.get("CLUSTERWEAVE_EXECUTOR", "local").strip().lower() or "local"
WORKER_DIR = DATA_DIR / "worker"
WORKER_STATUS_PATH = WORKER_DIR / "status.json"
CANCELLED_ERROR = "Cancelled by administrator"


def _env_nonnegative_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return max(0.0, value)


def _read_positive_int(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw or raw.lower() == "max":
            return None
        value = int(raw)
    except (OSError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def effective_cpu_count() -> int:
    """Return the narrowest host, affinity, or cgroup CPU ceiling."""
    candidates = [max(1, int(os.cpu_count() or 1))]
    try:
        candidates.append(max(1, len(os.sched_getaffinity(0))))
    except (AttributeError, OSError):
        pass

    try:
        cpu_max = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="utf-8").strip().split()
        if len(cpu_max) >= 2 and cpu_max[0] != "max":
            quota = int(cpu_max[0])
            period = int(cpu_max[1])
            if quota > 0 and period > 0:
                candidates.append(max(1, quota // period))
    except (OSError, TypeError, ValueError):
        quota = _read_positive_int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"))
        period = _read_positive_int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us"))
        if quota and period:
            candidates.append(max(1, quota // period))
    return max(1, min(candidates))


def effective_memory_limit_mb() -> int:
    """Return the effective cgroup/host memory limit in MiB."""
    candidates: list[int] = []
    for path in [
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ]:
        value = _read_positive_int(path)
        # Some cgroup v1 hosts report a sentinel close to LONG_MAX.
        if value and value < (1 << 60):
            candidates.append(max(1, value // (1024 * 1024)))
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        if pages > 0 and page_size > 0:
            candidates.append(max(1, (pages * page_size) // (1024 * 1024)))
    except (OSError, TypeError, ValueError):
        pass
    # This is only a final fallback; normal Linux hosts expose one of the above.
    return max(1024, min(candidates) if candidates else 4096)


def _budget_from_env(name: str, automatic: int) -> int:
    raw = str(os.environ.get(name, "auto") or "auto").strip().lower()
    if raw in {"", "auto"}:
        return max(1, automatic)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return max(1, automatic)


def _memory_term_from_env(name: str, default: int, *, minimum: int = 0) -> int:
    raw = str(os.environ.get(name, default)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _memory_safety_factor(default: float) -> float:
    try:
        value = float(os.environ.get("WORKER_MEMORY_SAFETY_FACTOR", str(default)))
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value) or value < 1.0:
        return default
    return value


_EFFECTIVE_CPU_COUNT = effective_cpu_count()
_EFFECTIVE_MEMORY_LIMIT_MB = effective_memory_limit_mb()
WORKER_CPU_BUDGET = min(
    _EFFECTIVE_CPU_COUNT,
    _budget_from_env("WORKER_CPU_BUDGET", _EFFECTIVE_CPU_COUNT),
)
# Leave 20% of the effective memory ceiling for the worker, engine, and bursty
# subprocess overhead unless an operator supplies an explicit hard budget.
WORKER_MEMORY_BUDGET_MB = _budget_from_env(
    "WORKER_MEMORY_BUDGET_MB",
    max(1024, int(_EFFECTIVE_MEMORY_LIMIT_MB * 0.80)),
)
WORKER_MEMORY_BUDGET_MB = min(WORKER_MEMORY_BUDGET_MB, _EFFECTIVE_MEMORY_LIMIT_MB)
WORKER_MIN_FREE_DISK_GB = _env_nonnegative_float("WORKER_MIN_FREE_DISK_GB", 0.0)
_DEFAULT_MEMORY_FORMULA = MemoryFormula()
WORKER_MEMORY_FORMULA = MemoryFormula(
    base_memory_mb=_memory_term_from_env(
        "WORKER_MEMORY_BASE_MB", _DEFAULT_MEMORY_FORMULA.base_memory_mb
    ),
    per_genome_memory_mb=_memory_term_from_env(
        "WORKER_MEMORY_PER_GENOME_MB", _DEFAULT_MEMORY_FORMULA.per_genome_memory_mb
    ),
    per_antismash_shard_memory_mb=_memory_term_from_env(
        "WORKER_MEMORY_PER_ANTISMASH_SHARD_MB",
        _DEFAULT_MEMORY_FORMULA.per_antismash_shard_memory_mb,
    ),
    per_annotation_cpu_memory_mb=_memory_term_from_env(
        "WORKER_MEMORY_PER_ANNOTATION_CPU_MB",
        _DEFAULT_MEMORY_FORMULA.per_annotation_cpu_memory_mb,
    ),
    per_funbgcex_worker_memory_mb=_memory_term_from_env(
        "WORKER_MEMORY_PER_FUNBGCEX_WORKER_MB",
        _DEFAULT_MEMORY_FORMULA.per_funbgcex_worker_memory_mb,
    ),
    phylogeny_base_memory_mb=_memory_term_from_env(
        "WORKER_MEMORY_PHYLOGENY_BASE_MB",
        _DEFAULT_MEMORY_FORMULA.phylogeny_base_memory_mb,
    ),
    per_phylogeny_cpu_memory_mb=_memory_term_from_env(
        "WORKER_MEMORY_PER_PHYLOGENY_CPU_MB",
        _DEFAULT_MEMORY_FORMULA.per_phylogeny_cpu_memory_mb,
    ),
    safety_factor=_memory_safety_factor(_DEFAULT_MEMORY_FORMULA.safety_factor),
    minimum_memory_mb=_memory_term_from_env(
        "WORKER_MEMORY_MINIMUM_MB",
        _DEFAULT_MEMORY_FORMULA.minimum_memory_mb,
        minimum=1,
    ),
)


def _auto_resource_estimate_settings(cpus: int, settings: dict[str, Any]) -> dict[str, Any]:
    """Return the worst-case shell plan when operator auto mode is enabled.

    The shell may expand persisted conservative targets in auto mode. Admission
    must therefore reserve against the operator auto ceilings, not the smaller
    submitted shape. CPU bounding remains delegated to the shared planner.
    """

    mode = str(os.environ.get("PIPELINE_RESOURCE_MODE", "conservative") or "").strip().lower()
    if mode != "auto":
        return settings
    resolved = dict(settings)
    resolved.update(
        {
            "genome_parallelism": _budget_from_env(
                "PIPELINE_AUTO_MAX_GENOME_PARALLELISM", 4
            ),
            "antismash_record_parallelism": _budget_from_env(
                "PIPELINE_AUTO_MAX_ANTISMASH_RECORD_PARALLELISM", 3
            ),
            # Zero has the shell/shared-planner meaning: derive the largest
            # per-shard allocation that still fits the whole-job CPU budget.
            "antismash_shard_cpus": 0,
            "antismash_legacy_cpus": max(1, int(cpus)),
            "anno_cpus": _budget_from_env("PIPELINE_AUTO_MAX_ANNO_CPUS", 8),
            "workers": _budget_from_env("PIPELINE_AUTO_MAX_FUNBGCEX_WORKERS", 2),
        }
    )
    return resolved


@dataclass(frozen=True)
class JobResourceReservation:
    cpu_slots: int
    memory_mb: int


@dataclass(frozen=True)
class LocalClaim:
    job_id: str
    cpus: int
    settings: dict[str, Any]
    lease_path: Path
    reservation: JobResourceReservation


class ResourceAdmission:
    """Aggregate, fail-closed local-worker resource reservations."""

    def __init__(
        self,
        *,
        cpu_budget: int = WORKER_CPU_BUDGET,
        memory_budget_mb: int = WORKER_MEMORY_BUDGET_MB,
        max_jobs: int = WORKER_CONCURRENCY,
    ) -> None:
        self.cpu_budget = max(1, int(cpu_budget))
        self.memory_budget_mb = max(1, int(memory_budget_mb))
        self.max_jobs = max(1, int(max_jobs))
        self._reservations: dict[str, JobResourceReservation] = {}

    @property
    def allocated_cpu_slots(self) -> int:
        return sum(item.cpu_slots for item in self._reservations.values())

    @property
    def allocated_memory_mb(self) -> int:
        return sum(item.memory_mb for item in self._reservations.values())

    def capacity_reason(self, reservation: JobResourceReservation) -> str | None:
        if len(self._reservations) >= self.max_jobs:
            return f"worker concurrency ceiling reached ({self.max_jobs})"
        if self.allocated_cpu_slots + reservation.cpu_slots > self.cpu_budget:
            return (
                "CPU budget unavailable "
                f"({self.allocated_cpu_slots}+{reservation.cpu_slots}>{self.cpu_budget})"
            )
        if self.allocated_memory_mb + reservation.memory_mb > self.memory_budget_mb:
            return (
                "memory budget unavailable "
                f"({self.allocated_memory_mb}+{reservation.memory_mb}>{self.memory_budget_mb} MiB)"
            )
        return None

    def reserve(self, job_id: str, reservation: JobResourceReservation) -> bool:
        if job_id in self._reservations or self.capacity_reason(reservation) is not None:
            return False
        self._reservations[job_id] = reservation
        return True

    def release(self, job_id: str) -> JobResourceReservation | None:
        return self._reservations.pop(job_id, None)

    def snapshot(self) -> dict[str, Any]:
        allocated_cpu = self.allocated_cpu_slots
        allocated_memory = self.allocated_memory_mb
        return {
            "cpu_budget": self.cpu_budget,
            "memory_budget_mb": self.memory_budget_mb,
            "allocated_cpu_slots": allocated_cpu,
            "allocated_memory_mb": allocated_memory,
            "available_cpu_slots": max(0, self.cpu_budget - allocated_cpu),
            "available_memory_mb": max(0, self.memory_budget_mb - allocated_memory),
            "min_free_disk_gb": WORKER_MIN_FREE_DISK_GB,
            "reservations": {
                job_id: {"cpu_slots": item.cpu_slots, "memory_mb": item.memory_mb}
                for job_id, item in sorted(self._reservations.items())
            },
        }


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


def _stop_job_containers(job_id: str, reason: str) -> None:
    ids = _running_container_ids_for_job(job_id)
    if not ids:
        return
    append_log(job_id, f"Stopping {len(ids)} active tool container(s) for {reason}.")
    _docker(["stop", "--time", "10", *ids], timeout=60)


def stop_job_containers(job_id: str) -> None:
    _stop_job_containers(job_id, "cancelled or interrupted job")


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
    admission: ResourceAdmission | None = None,
    admission_hold: str = "",
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
            "resource_admission": admission.snapshot() if admission else {
                "cpu_budget": WORKER_CPU_BUDGET,
                "memory_budget_mb": WORKER_MEMORY_BUDGET_MB,
                "allocated_cpu_slots": 0,
                "allocated_memory_mb": 0,
                "available_cpu_slots": WORKER_CPU_BUDGET,
                "available_memory_mb": WORKER_MEMORY_BUDGET_MB,
                "min_free_disk_gb": WORKER_MIN_FREE_DISK_GB,
                "reservations": {},
            },
            "admission_hold": admission_hold or None,
        },
        "capabilities": runtime,
    }
    atomic_write_text(WORKER_STATUS_PATH, json.dumps(payload, ensure_ascii=False))


def _read_queue_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Queue payload is not an object: {path.name}")
    return payload


def _queue_time_value(path: Path, payload: dict[str, Any]) -> float:
    raw = payload.get("enqueued_at") or payload.get("created_at")
    if isinstance(raw, (int, float)):
        return float(raw)
    if raw:
        try:
            normalized = str(raw).strip().replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            return parsed.timestamp()
        except (TypeError, ValueError):
            pass
    try:
        return path.stat().st_mtime
    except OSError:
        return float("inf")


def ordered_queue_paths() -> list[Path]:
    """Order queue entries by enqueue time, never by random job UUID."""
    ordered: list[tuple[float, int, str, Path]] = []
    for path in QUEUE_DIR.glob("*.json"):
        try:
            payload = _read_queue_payload(path)
        except (OSError, ValueError, json.JSONDecodeError):
            payload = {}
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0
        ordered.append((_queue_time_value(path, payload), mtime_ns, path.name, path))
    return [item[-1] for item in sorted(ordered)]


def _claim_fields(payload: dict[str, Any]) -> tuple[str, int, dict[str, Any]]:
    job_id = str(payload["job_id"])
    cpus = max(1, int(payload.get("cpus", 4)))
    settings = payload.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}
    return job_id, cpus, settings


def _job_genome_count(job_id: str, settings: dict[str, Any]) -> int | None:
    meta = read_job(job_id) or {}
    summary = meta.get("input_summary")
    if isinstance(summary, dict) and summary:
        return genome_count_from_input_summary(summary)
    for key in ["genome_count", "input_genome_count"]:
        try:
            count = int(settings.get(key, 0) or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            return count
    return None


def estimate_claim_reservation(job_id: str, cpus: int, settings: dict[str, Any]) -> JobResourceReservation:
    estimate_settings = _auto_resource_estimate_settings(cpus, settings)
    estimate = estimate_job_resources(
        cpus,
        estimate_settings,
        _job_genome_count(job_id, estimate_settings),
        memory_formula=WORKER_MEMORY_FORMULA,
    )
    return JobResourceReservation(
        # Reserve at least the declared job CPU allocation because stages such
        # as BiG-SCAPE may consume THREADS even when annotation fan-out is low.
        cpu_slots=max(cpus, int(estimate.cpu_slots)),
        memory_mb=max(1, int(estimate.memory_mb)),
    )


def free_disk_gb(path: Path = DATA_DIR) -> float:
    try:
        return shutil.disk_usage(path).free / (1024**3)
    except OSError:
        # Failure to observe a configured disk floor is a fail-closed hold.
        return 0.0


def _terminalize_queue_rejection(job_id: str, reason: str) -> None:
    meta = read_job(job_id)
    if meta is None:
        return
    if str(meta.get("status") or "").lower() in {
        JobStatus.SUCCESS.value,
        JobStatus.FAILED.value,
    }:
        return
    append_log(job_id, f"Scheduler rejected queued job: {reason}.")
    finished_at = now_iso()
    meta["status"] = JobStatus.FAILED.value
    meta["stage"] = "scheduler rejected"
    meta["error"] = reason
    meta["finished_at"] = finished_at
    meta["updated_at"] = finished_at
    meta["log_count"] = len(read_logs(job_id))
    meta.pop("worker_reservation", None)
    write_job(meta)
    maybe_send_terminal_notification(job_id)


def _quarantine_invalid_queue_entry(queue_path: Path) -> None:
    rejected_dir = WORKER_DIR / "rejected_queue"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    target = rejected_dir / f"{queue_path.name}.{time.time_ns()}.invalid"
    try:
        queue_path.replace(target)
    except FileNotFoundError:
        pass


def claim_next_job() -> tuple[str, int, dict[str, Any]] | None:
    """Legacy one-shot/Slurm claim path, now with FIFO ordering."""
    for queue_path in ordered_queue_paths():
        working = queue_path.with_suffix(".working")
        try:
            queue_path.rename(working)
        except FileNotFoundError:
            continue
        except OSError:
            continue

        try:
            payload = _read_queue_payload(working)
            job_id, cpus, settings = _claim_fields(payload)
            if job_cancel_requested(job_id):
                append_log(job_id, "Cancelled queued job before worker start.")
                finalize_cancelled_job(job_id, cpus, settings, "Cancelled before worker start")
                continue
            return job_id, cpus, settings
        finally:
            working.unlink(missing_ok=True)
    return None


def claim_next_admissible_job(admission: ResourceAdmission) -> tuple[LocalClaim | None, str]:
    """Claim only the FIFO head when disk and aggregate resources permit it."""
    if WORKER_MIN_FREE_DISK_GB > 0:
        available = free_disk_gb()
        if available < WORKER_MIN_FREE_DISK_GB:
            return None, (
                f"queue held: free disk {available:.1f} GiB is below "
                f"WORKER_MIN_FREE_DISK_GB={WORKER_MIN_FREE_DISK_GB:.1f}"
            )

    for queue_path in ordered_queue_paths():
        try:
            payload = _read_queue_payload(queue_path)
            job_id, cpus, settings = _claim_fields(payload)
            reservation = estimate_claim_reservation(job_id, cpus, settings)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            reason = "invalid or truncated queue payload"
            _terminalize_queue_rejection(queue_path.stem, reason)
            _quarantine_invalid_queue_entry(queue_path)
            continue

        if queue_path.stem != job_id or read_job(job_id) is None:
            _quarantine_invalid_queue_entry(queue_path)
            continue

        if (
            reservation.cpu_slots > admission.cpu_budget
            or reservation.memory_mb > admission.memory_budget_mb
        ):
            reason = (
                "resource request cannot fit this worker "
                f"(job={reservation.cpu_slots} CPU/{reservation.memory_mb} MiB; "
                f"worker={admission.cpu_budget} CPU/{admission.memory_budget_mb} MiB)"
            )
            queue_path.unlink(missing_ok=True)
            _terminalize_queue_rejection(job_id, reason)
            continue

        reason = admission.capacity_reason(reservation)
        if reason is not None:
            return None, f"queue held for {job_id}: {reason}"

        working = queue_path.with_suffix(".working")
        try:
            queue_path.rename(working)
        except FileNotFoundError:
            continue
        except OSError as exc:
            return None, f"queue held: could not lease {queue_path.name}: {exc}"

        if job_cancel_requested(job_id):
            try:
                append_log(job_id, "Cancelled queued job before worker start.")
                finalize_cancelled_job(job_id, cpus, settings, "Cancelled before worker start")
            finally:
                working.unlink(missing_ok=True)
            continue

        if not admission.reserve(job_id, reservation):
            try:
                working.rename(queue_path)
            except OSError:
                pass
            return None, f"queue held for {job_id}: aggregate reservation changed during claim"

        return LocalClaim(job_id, cpus, settings, working, reservation), ""
    return None, ""


def queue_path_for_job(job_id: str) -> Path:
    return QUEUE_DIR / f"{job_id}.json"


def stale_queue_paths(job_id: str) -> list[Path]:
    return [*QUEUE_DIR.glob(f"{job_id}*.json"), *QUEUE_DIR.glob(f"{job_id}*.working")]


def queue_payload(
    job_id: str,
    cpus: int,
    settings: dict[str, Any],
    *,
    enqueued_at: str | None = None,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "cpus": cpus,
        "settings": settings,
        "enqueued_at": enqueued_at or now_iso(),
    }


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


def _recovery_settings(meta: dict[str, Any]) -> tuple[int, dict[str, Any], str]:
    settings = dict(meta.get("settings") or meta.get("submission_settings") or {})
    settings["reuse_existing_layout"] = True
    previous_stage = str(meta.get("stage") or "")
    if stage_has_passed_genome_prep(previous_stage):
        settings["run_genome_prep"] = False
    try:
        cpus = max(1, int(meta.get("cpus", 4)))
    except (TypeError, ValueError):
        cpus = 4
    return cpus, settings, previous_stage


def _mark_recovered_pending(meta: dict[str, Any], cpus: int, settings: dict[str, Any]) -> None:
    job_id = str(meta["id"])
    meta["status"] = JobStatus.PENDING.value
    meta["stage"] = "queued"
    meta["error"] = None
    meta["cpus"] = cpus
    meta["settings"] = settings
    meta.pop("worker_reservation", None)
    meta["log_count"] = len(read_logs(job_id))
    meta["updated_at"] = now_iso()
    write_job(meta)


def recover_stale_working_leases() -> list[str]:
    """Recover each interrupted local claim to one canonical queue entry."""
    recovered: list[str] = []
    for working in sorted(QUEUE_DIR.glob("*.working")):
        try:
            payload = _read_queue_payload(working)
        except (OSError, ValueError, json.JSONDecodeError):
            payload = {}
        # The canonical lease filename is a second durable job-id source. This
        # lets startup recover a truncated/legacy payload instead of allowing an
        # unreadable .working file to strand a known running job forever.
        job_id = str(payload.get("job_id") or working.stem)

        meta = read_job(job_id)
        try:
            cpus = max(1, int(payload.get("cpus", (meta or {}).get("cpus", 4))))
        except (TypeError, ValueError):
            cpus = 4
        raw_settings = payload.get("settings")
        settings = dict(raw_settings) if isinstance(raw_settings, dict) else dict(
            (meta or {}).get("settings") or (meta or {}).get("submission_settings") or {}
        )
        if meta is None or str(meta.get("status") or "").lower() in {
            JobStatus.SUCCESS.value,
            JobStatus.FAILED.value,
        }:
            working.unlink(missing_ok=True)
            continue

        if job_cancel_requested(job_id):
            append_log(job_id, "Cancelled interrupted claim during worker recovery.")
            finalize_cancelled_job(job_id, cpus, settings, "Cancelled during worker recovery")
            working.unlink(missing_ok=True)
            continue

        canonical = queue_path_for_job(job_id)
        if str(meta.get("status") or "").lower() == JobStatus.RUNNING.value:
            _stop_job_containers(job_id, "interrupted job recovery")
            cpus, settings, previous_stage = _recovery_settings(meta)
            append_log(
                job_id,
                "Recovered interrupted running job from worker lease; re-queued exactly once.",
            )
            if stage_has_passed_genome_prep(previous_stage):
                append_log(
                    job_id,
                    "Recovery resume skipped accession genome prep because the interrupted run had already passed genome preparation.",
                )
            _mark_recovered_pending(meta, cpus, settings)
            payload = queue_payload(
                job_id,
                cpus,
                settings,
                enqueued_at=str(payload.get("enqueued_at") or meta.get("created_at") or now_iso()),
            )
            atomic_write_text(working, json.dumps(payload))

        if canonical.exists():
            working.unlink(missing_ok=True)
        else:
            try:
                working.rename(canonical)
            except FileExistsError:
                working.unlink(missing_ok=True)
            except OSError:
                continue
        recovered.append(job_id)
    return recovered


def recover_orphaned_running_jobs() -> list[str]:
    recovered = recover_stale_working_leases()
    for meta in list_jobs():
        job_id = str(meta.get("id") or "")
        if not job_id or str(meta.get("status") or "").lower() != JobStatus.RUNNING.value:
            continue
        if queue_path_for_job(job_id).exists():
            continue
        if any(QUEUE_DIR.glob(f"{job_id}*.working")):
            continue

        cpus, settings, previous_stage = _recovery_settings(meta)

        if job_cancel_requested(job_id):
            append_log(job_id, "Cancelled interrupted running job during worker recovery.")
            finalize_cancelled_job(job_id, cpus, settings, "Cancelled during worker recovery")
            continue

        # Stop old labeled work before publishing a replacement queue entry;
        # otherwise the recovered job could overlap its orphaned containers.
        _stop_job_containers(job_id, "orphaned job recovery")
        append_log(job_id, "Recovered interrupted running job after worker restart; re-queued for worker slot.")
        if stage_has_passed_genome_prep(previous_stage):
            append_log(
                job_id,
                "Recovery resume skipped accession genome prep because the interrupted run had already passed genome preparation.",
            )
        queue_path = queue_path_for_job(job_id)
        recovery_lease = queue_path.with_suffix(".working")
        atomic_write_text(
            recovery_lease,
            json.dumps(
                queue_payload(
                    job_id,
                    cpus,
                    settings,
                    enqueued_at=str(meta.get("created_at") or now_iso()),
                )
            ),
        )
        _mark_recovered_pending(meta, cpus, settings)
        recovery_lease.rename(queue_path)
        recovered.append(job_id)
    return recovered


def recover_stranded_pending_jobs() -> list[str]:
    """Republish pending metadata left behind by an interrupted web enqueue."""

    recovered: list[str] = []
    for meta in list_jobs():
        job_id = str(meta.get("id") or "")
        if not job_id or str(meta.get("status") or "").lower() != JobStatus.PENDING.value:
            continue
        if stale_queue_paths(job_id):
            continue
        raw_timestamp = str(meta.get("updated_at") or meta.get("created_at") or "").strip()
        try:
            parsed_timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            current_time = datetime.now(parsed_timestamp.tzinfo)
            age_seconds = (current_time - parsed_timestamp).total_seconds()
        except (TypeError, ValueError):
            # Do not race an actively publishing web request when age cannot be
            # established. Normal metadata always carries an ISO timestamp.
            continue
        if age_seconds < PENDING_RECOVERY_GRACE_SECONDS:
            continue
        try:
            cpus = max(1, int(meta.get("cpus", 4)))
        except (TypeError, ValueError):
            cpus = 4
        raw_settings = meta.get("settings") or meta.get("submission_settings") or {}
        settings = dict(raw_settings) if isinstance(raw_settings, dict) else {}
        if job_cancel_requested(job_id):
            finalize_cancelled_job(job_id, cpus, settings, "Cancelled before queue recovery")
            continue
        atomic_write_text(
            queue_path_for_job(job_id),
            json.dumps(
                queue_payload(
                    job_id,
                    cpus,
                    settings,
                    enqueued_at=str(meta.get("created_at") or now_iso()),
                )
            ),
        )
        append_log(job_id, "Recovered pending job whose queue publication was interrupted.")
        meta["log_count"] = len(read_logs(job_id))
        meta["updated_at"] = now_iso()
        write_job(meta)
        recovered.append(job_id)
    return recovered


def build_job_from_meta(meta: dict) -> Job:
    status = meta.get("status", "pending")
    try:
        job_status = JobStatus(status)
    except ValueError:
        job_status = JobStatus.PENDING

    log_lines = read_logs(str(meta["id"]))
    job = Job(
        id=str(meta["id"]),
        name=str(meta.get("name", "job")),
        status=job_status,
        created_at=str(meta.get("created_at", now_iso())),
        updated_at=str(meta.get("updated_at", now_iso())),
        stage=str(meta.get("stage", "queued")),
        log_lines=log_lines,
        result_files=list(meta.get("result_files", [])),
        bigscape_viewer_database=str(
            meta.get("bigscape_viewer_database", "")
        ),
        error=meta.get("error"),
        project_name=str(meta.get("project_name", "")),
        result_root=str(meta.get("result_root", "")),
        _synced_log_count=len(log_lines),
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


def sync_job_logs(job: Job) -> None:
    """Append only the Job records not yet persisted by this worker."""

    synced = max(0, int(job._synced_log_count))
    if synced > len(job.log_lines):
        raise RuntimeError(
            f"Job {job.id} log history shrank from {synced} to {len(job.log_lines)} lines"
        )
    pending = job.log_lines[synced:]
    if pending:
        append_log_lines(job.id, pending)
    job._synced_log_count = len(job.log_lines)


def persist_job(job: Job, cpus: int, settings: dict[str, Any]) -> None:
    sync_job_logs(job)
    payload = dict(read_job(job.id) or {})
    payload.update(job.to_dict())
    payload["status"] = job.status.value
    payload["log_count"] = len(job.log_lines)
    payload["cpus"] = cpus
    payload["settings"] = settings
    payload["updated_at"] = now_iso()
    if job.status in {JobStatus.SUCCESS, JobStatus.FAILED}:
        payload.pop("worker_reservation", None)
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


def mark_claim_running(
    job_id: str,
    cpus: int,
    settings: dict[str, Any],
    reservation: JobResourceReservation,
) -> None:
    """Durably publish running state before the claim lease is removed."""
    meta = read_job(job_id)
    if meta is None:
        raise ValueError(f"Job '{job_id}' disappeared while its worker lease was held")
    merged_settings = dict(meta.get("settings") or {})
    merged_settings.update(settings)
    meta["status"] = JobStatus.RUNNING.value
    meta["stage"] = "starting"
    meta["error"] = None
    meta["cpus"] = cpus
    meta["settings"] = merged_settings
    meta["worker_reservation"] = {
        "cpu_slots": reservation.cpu_slots,
        "memory_mb": reservation.memory_mb,
    }
    meta["updated_at"] = now_iso()
    write_job(meta)


async def process_claim(
    job_id: str,
    cpus: int,
    settings: dict[str, Any],
    *,
    lease_path: Path | None = None,
    reservation: JobResourceReservation | None = None,
    admission: ResourceAdmission | None = None,
) -> None:
    resolved_reservation = reservation or estimate_claim_reservation(job_id, cpus, settings)
    running_persisted = lease_path is None
    terminalized = False
    try:
        if lease_path is not None:
            if job_cancel_requested(job_id):
                raise asyncio.CancelledError(CANCELLED_ERROR)
            mark_claim_running(job_id, cpus, settings, resolved_reservation)
            running_persisted = True
            lease_path.unlink(missing_ok=True)
        await process_one(job_id, cpus, settings)
    except asyncio.CancelledError:
        stop_job_containers(job_id)
        finalize_cancelled_job(job_id, cpus, settings)
        terminalized = True
        return
    except Exception as exc:
        if not running_persisted:
            # The .working lease remains authoritative and startup recovery can
            # retry it; do not convert a transient metadata-write failure into
            # a terminal job or silently lose the claim.
            raise
        meta = read_job(job_id)
        if meta is not None:
            job = build_job_from_meta(meta)
            job.status = JobStatus.FAILED
            job.error = str(exc)
            job.add_log(f"FATAL: {exc}")
            persist_job(job, cpus, settings)
            maybe_send_terminal_notification(job_id)
            terminalized = True
        raise
    finally:
        if lease_path is not None and terminalized:
            lease_path.unlink(missing_ok=True)
        if admission is not None:
            admission.release(job_id)


async def worker_loop() -> None:
    admission = ResourceAdmission()
    print(
        "ClusterWeave worker started. "
        f"concurrency={WORKER_CONCURRENCY} cpu_budget={admission.cpu_budget} "
        f"memory_budget_mb={admission.memory_budget_mb}"
    )
    recovered = recover_orphaned_running_jobs()
    recovered.extend(recover_stranded_pending_jobs())
    if recovered:
        write_worker_status(
            "ready",
            f"Recovered {len(recovered)} interrupted job(s)",
            ", ".join(recovered),
            admission=admission,
        )
    else:
        write_worker_status(
            "ready",
            f"Worker loop started (concurrency={WORKER_CONCURRENCY})",
            admission=admission,
        )
    active: dict[str, asyncio.Task[None]] = {}
    cancelling: set[str] = set()
    next_pending_recovery = time.monotonic() + PENDING_RECOVERY_SECONDS
    while True:
        if time.monotonic() >= next_pending_recovery:
            recover_stranded_pending_jobs()
            next_pending_recovery = time.monotonic() + PENDING_RECOVERY_SECONDS
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
                write_worker_status(
                    "error",
                    str(exc),
                    active_jobs=sorted(active),
                    admission=admission,
                )

        admission_hold = ""
        while len(active) < WORKER_CONCURRENCY:
            claim, admission_hold = claim_next_admissible_job(admission)
            if claim is None:
                break
            active[claim.job_id] = asyncio.create_task(
                process_claim(
                    claim.job_id,
                    claim.cpus,
                    claim.settings,
                    lease_path=claim.lease_path,
                    reservation=claim.reservation,
                    admission=admission,
                )
            )

        if active:
            ids = sorted(active)
            detail = f"Processing {len(ids)} job(s)"
            if admission_hold:
                detail = f"{detail}; {admission_hold}"
            write_worker_status(
                "processing",
                detail,
                ", ".join(ids),
                active_jobs=ids,
                admission=admission,
                admission_hold=admission_hold,
            )
        else:
            detail = admission_hold or "Waiting for queued jobs"
            write_worker_status(
                "idle",
                detail,
                admission=admission,
                admission_hold=admission_hold,
            )
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
