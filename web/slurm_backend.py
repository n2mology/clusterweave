#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from job_store import (
        DATA_DIR,
        append_log,
        job_cancel_path,
        job_cancel_requested,
        job_delete_path,
        job_dir,
        list_jobs,
        now_iso,
        read_job,
        read_logs,
        write_job,
    )
    from notifications import maybe_send_terminal_notification
except ImportError:  # pragma: no cover - package-style imports in local tests
    from .job_store import (
        DATA_DIR,
        append_log,
        job_cancel_path,
        job_cancel_requested,
        job_delete_path,
        job_dir,
        list_jobs,
        now_iso,
        read_job,
        read_logs,
        write_job,
    )
    from .notifications import maybe_send_terminal_notification


Claim = tuple[str, int, dict[str, Any]]
ClaimProvider = Callable[[], Claim | None]
CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]

TERMINAL_STATUSES = {"success", "failed"}
SLURM_PENDING_STATES = {
    "PENDING",
    "CONFIGURING",
    "REQUEUED",
    "REQUEUE_FED",
    "REQUEUE_HOLD",
    "RESIZING",
    "SIGNALING",
    "SPECIAL_EXIT",
    "STAGE_OUT",
    "SUBMITTED",
}
SLURM_RUNNING_STATES = {
    "COMPLETING",
    "RUNNING",
    "SUSPENDED",
    "STOPPED",
}
SLURM_SUCCESS_STATES = {"COMPLETED"}
SLURM_FAILED_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "REVOKED",
    "TIMEOUT",
}


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _clean_env(value: str | None) -> str:
    return str(value or "").strip()


def _repo_root_from_env() -> Path:
    configured = _clean_env(os.environ.get("CLUSTERWEAVE_ROOT"))
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SlurmConfig:
    account: str = ""
    partition: str = ""
    qos: str = ""
    time: str = "04:00:00"
    mem: str = "16G"
    nodes: int = 1
    cpus_per_task: int = 4
    max_submitted: int = 10
    workdir: str = ""
    prologue: str = ""
    engine: str = ""
    repo_root: Path = Path(".")
    python: str = "python3"
    poll_seconds: float = 15.0
    command_timeout: int = 30

    @classmethod
    def from_env(cls) -> "SlurmConfig":
        engine = _clean_env(os.environ.get("ENGINE")) or _clean_env(os.environ.get("CLUSTERWEAVE_CONTAINER_ENGINE"))
        try:
            poll_seconds = float(os.environ.get("WORKER_POLL_SECONDS", "15.0"))
        except (TypeError, ValueError):
            poll_seconds = 15.0
        return cls(
            account=_clean_env(os.environ.get("CLUSTERWEAVE_SLURM_ACCOUNT")),
            partition=_clean_env(os.environ.get("CLUSTERWEAVE_SLURM_PARTITION")),
            qos=_clean_env(os.environ.get("CLUSTERWEAVE_SLURM_QOS")),
            time=_clean_env(os.environ.get("CLUSTERWEAVE_SLURM_TIME")) or "04:00:00",
            mem=_clean_env(os.environ.get("CLUSTERWEAVE_SLURM_MEM")) or "16G",
            nodes=_env_int("CLUSTERWEAVE_SLURM_NODES", 1, minimum=1),
            cpus_per_task=_env_int("CLUSTERWEAVE_SLURM_CPUS_PER_TASK", 4, minimum=1),
            max_submitted=_env_int("CLUSTERWEAVE_SLURM_MAX_SUBMITTED", 10, minimum=1),
            workdir=_clean_env(os.environ.get("CLUSTERWEAVE_SLURM_WORKDIR")),
            prologue=os.environ.get("CLUSTERWEAVE_SLURM_PROLOGUE", ""),
            engine=engine,
            repo_root=_repo_root_from_env(),
            python=_clean_env(os.environ.get("CLUSTERWEAVE_SLURM_PYTHON")) or "python3",
            poll_seconds=max(1.0, poll_seconds),
            command_timeout=_env_int("CLUSTERWEAVE_SLURM_COMMAND_TIMEOUT", 30, minimum=1),
        )

    @property
    def worker_script(self) -> Path:
        configured = _clean_env(os.environ.get("CLUSTERWEAVE_SLURM_WORKER_SCRIPT"))
        if configured:
            return Path(configured)
        return self.repo_root / "web" / "worker.py"


def _safe_job_name(job_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", job_id).strip(".-")
    return f"cw-{safe[:48] or 'job'}"


def _shell(value: object) -> str:
    return shlex.quote(str(value))


def _rel_to_job(job_id: str, path: Path) -> str:
    try:
        return path.relative_to(job_dir(job_id)).as_posix()
    except ValueError:
        return path.as_posix()


def render_sbatch_script(
    config: SlurmConfig,
    *,
    job_id: str,
    cpus: int,
    payload_path: Path,
    slurm_dir: Path,
) -> str:
    requested_cpus = max(1, int(cpus or config.cpus_per_task))
    cpus_per_task = max(requested_cpus, config.cpus_per_task)
    run_dir = Path(config.workdir) if config.workdir else job_dir(job_id)
    stdout_path = slurm_dir / "slurm-%j.out"
    stderr_path = slurm_dir / "slurm-%j.err"

    lines = [
        "#!/usr/bin/env bash",
        f"#SBATCH --job-name={_safe_job_name(job_id)}",
        f"#SBATCH --output={stdout_path}",
        f"#SBATCH --error={stderr_path}",
        f"#SBATCH --chdir={run_dir}",
        f"#SBATCH --time={config.time}",
        f"#SBATCH --mem={config.mem}",
        f"#SBATCH --nodes={config.nodes}",
        f"#SBATCH --cpus-per-task={cpus_per_task}",
    ]
    if config.account:
        lines.append(f"#SBATCH --account={config.account}")
    if config.partition:
        lines.append(f"#SBATCH --partition={config.partition}")
    if config.qos:
        lines.append(f"#SBATCH --qos={config.qos}")

    lines.extend(
        [
            "",
            "set -euo pipefail",
            f"export DATA_DIR={_shell(DATA_DIR)}",
            f"export CLUSTERWEAVE_ROOT={_shell(config.repo_root)}",
            f"export CLUSTERWEAVE_SOFTWARE_ROOT={_shell(os.environ.get('CLUSTERWEAVE_SOFTWARE_ROOT', str(DATA_DIR / 'software')))}",
            "export CLUSTERWEAVE_EXECUTOR=local",
            "export CLUSTERWEAVE_ENABLE_DOCKER_SOCKET=0",
            f"export OMP_NUM_THREADS=${{SLURM_CPUS_PER_TASK:-{cpus_per_task}}}",
        ]
    )
    if config.engine:
        lines.append(f"export ENGINE={_shell(config.engine)}")
        lines.append(f"export CLUSTERWEAVE_CONTAINER_ENGINE={_shell(config.engine)}")
    if config.prologue.strip():
        lines.extend(["", "# Operator-provided CADES/module setup.", config.prologue.rstrip()])
    lines.extend(
        [
            "",
            f"cd {_shell(config.repo_root)}",
            (
                f"{_shell(config.python)} {_shell(config.worker_script)} --once {_shell(job_id)} "
                f"--queue-payload {_shell(payload_path)}"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def parse_sbatch_job_id(stdout: str) -> str:
    first = stdout.strip().splitlines()[0] if stdout.strip() else ""
    first = first.split(";", 1)[0].strip()
    match = re.match(r"^(\d+)", first)
    return match.group(1) if match else ""


def normalize_slurm_state(value: str | None) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return "UNKNOWN"
    raw = raw.split("|", 1)[0].strip()
    raw = raw.split()[0].strip()
    raw = raw.split("+", 1)[0].strip()
    raw = raw.replace(" ", "_")
    return raw or "UNKNOWN"


def parse_squeue_state(stdout: str) -> str:
    for line in stdout.splitlines():
        state = normalize_slurm_state(line)
        if state != "UNKNOWN":
            return state
    return ""


def parse_sacct_state(stdout: str) -> str:
    for line in stdout.splitlines():
        state = normalize_slurm_state(line)
        if state != "UNKNOWN":
            return state
    return ""


def clusterweave_status_for_slurm_state(state: str) -> tuple[str, str, str | None]:
    normalized = normalize_slurm_state(state)
    if normalized in SLURM_SUCCESS_STATES:
        return "success", "complete", None
    if normalized in SLURM_FAILED_STATES:
        if normalized == "CANCELLED":
            return "failed", "cancelled", "Cancelled by Slurm or administrator"
        return "failed", "failed", f"Slurm job ended with state {normalized}"
    if normalized in SLURM_RUNNING_STATES:
        return "running", "running on Slurm", None
    return "pending", "queued on Slurm", None


def _default_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))
    except subprocess.SubprocessError as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def slurm_job_id_for(job: dict[str, Any]) -> str:
    scheduler = job.get("scheduler")
    if isinstance(scheduler, dict) and str(scheduler.get("kind") or "").lower() == "slurm":
        return str(scheduler.get("job_id") or job.get("slurm_job_id") or "").strip()
    return str(job.get("slurm_job_id") or "").strip()


def slurm_scheduler_metadata(job: dict[str, Any]) -> dict[str, Any]:
    scheduler = job.get("scheduler")
    if isinstance(scheduler, dict) and str(scheduler.get("kind") or "").lower() == "slurm":
        return dict(scheduler)
    return {}


class SlurmBackend:
    def __init__(
        self,
        *,
        config: SlurmConfig | None = None,
        claim_next_job: ClaimProvider | None = None,
        runner: CommandRunner | None = None,
        status_writer: Callable[..., None] | None = None,
    ) -> None:
        self.config = config or SlurmConfig.from_env()
        self.claim_next_job = claim_next_job
        self.runner = runner or _default_runner
        self.status_writer = status_writer

    def _run(self, args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        return self.runner(args, timeout or self.config.command_timeout)

    def _write_status(
        self,
        state: str,
        detail: str,
        substep: str = "",
        active_jobs: list[str] | None = None,
    ) -> None:
        if self.status_writer is None:
            return
        self.status_writer(state, detail, substep, active_jobs=active_jobs or [])

    def _set_scheduler_metadata(self, job: dict[str, Any], **updates: Any) -> dict[str, Any]:
        scheduler = slurm_scheduler_metadata(job)
        scheduler.setdefault("kind", "slurm")
        scheduler.update({key: value for key, value in updates.items() if value is not None})
        scheduler["updated_at"] = now_iso()
        job["executor"] = "slurm"
        job["scheduler"] = scheduler
        if scheduler.get("job_id"):
            job["slurm_job_id"] = scheduler["job_id"]
        return scheduler

    def submit_claim(self, claim: Claim) -> str | None:
        job_id, cpus, settings = claim
        meta = read_job(job_id)
        if meta is None:
            return None

        slurm_dir = job_dir(job_id) / "slurm"
        slurm_dir.mkdir(parents=True, exist_ok=True)
        payload_path = slurm_dir / "queue_payload.json"
        script_path = slurm_dir / "submit.sbatch"
        payload = {"job_id": job_id, "cpus": max(1, int(cpus or 1)), "settings": settings}
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        script = render_sbatch_script(
            self.config,
            job_id=job_id,
            cpus=int(payload["cpus"]),
            payload_path=payload_path,
            slurm_dir=slurm_dir,
        )
        script_path.write_text(script, encoding="utf-8")
        try:
            script_path.chmod(0o700)
        except OSError:
            pass

        append_log(job_id, f"Slurm: wrote submit script {_rel_to_job(job_id, script_path)}.")
        meta["status"] = "pending"
        meta["stage"] = "queued on Slurm"
        meta["error"] = None
        meta["cpus"] = payload["cpus"]
        meta["settings"] = settings
        self._set_scheduler_metadata(
            meta,
            state="SUBMITTED",
            clusterweave_status="pending",
            submit_script=_rel_to_job(job_id, script_path),
            queue_payload=_rel_to_job(job_id, payload_path),
            stdout=_rel_to_job(job_id, slurm_dir / "slurm-%j.out"),
            stderr=_rel_to_job(job_id, slurm_dir / "slurm-%j.err"),
        )
        meta["log_count"] = len(read_logs(job_id))
        meta["updated_at"] = now_iso()
        write_job(meta)

        result = self._run(["sbatch", "--parsable", str(script_path)])
        slurm_job_id = parse_sbatch_job_id(result.stdout)
        if result.returncode != 0 or not slurm_job_id:
            error = (result.stderr or result.stdout or "sbatch did not return a Slurm job id").strip()
            self._mark_submission_failed(job_id, error)
            return None

        meta = read_job(job_id)
        if meta is None:
            return None
        append_log(job_id, f"Slurm: submitted as scheduler job {slurm_job_id}.")
        meta["status"] = "pending"
        meta["stage"] = "queued on Slurm"
        self._set_scheduler_metadata(
            meta,
            job_id=slurm_job_id,
            state="PENDING",
            clusterweave_status="pending",
            submitted_at=now_iso(),
        )
        meta["log_count"] = len(read_logs(job_id))
        meta["updated_at"] = now_iso()
        write_job(meta)
        return job_id

    def _mark_submission_failed(self, job_id: str, error: str) -> None:
        meta = read_job(job_id)
        if meta is None:
            return
        append_log(job_id, f"Slurm: submission failed: {error}")
        meta["status"] = "failed"
        meta["stage"] = "failed"
        meta["error"] = f"Slurm submission failed: {error}"
        self._set_scheduler_metadata(meta, state="SUBMIT_FAILED", clusterweave_status="failed")
        meta["log_count"] = len(read_logs(job_id))
        meta["updated_at"] = now_iso()
        write_job(meta)
        maybe_send_terminal_notification(job_id)

    def poll_scheduler_state(self, slurm_job_id: str) -> str:
        squeue = self._run(["squeue", "-h", "-j", slurm_job_id, "-o", "%T"])
        if squeue.returncode == 0:
            state = parse_squeue_state(squeue.stdout)
            if state:
                return state

        sacct = self._run(
            ["sacct", "-n", "-X", "-j", slurm_job_id, "--format=State", "--parsable2"],
            timeout=self.config.command_timeout,
        )
        if sacct.returncode == 0:
            state = parse_sacct_state(sacct.stdout)
            if state:
                return state
        return "UNKNOWN"

    def _read_cancel_request(self, job_id: str) -> dict[str, Any]:
        path = job_cancel_path(job_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def cancel_job(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("id") or "")
        if not job_id:
            return
        scheduler_id = slurm_job_id_for(job)
        if scheduler_id:
            result = self._run(["scancel", scheduler_id])
            if result.returncode == 0:
                append_log(job_id, f"Slurm: requested cancellation for scheduler job {scheduler_id}.")
            else:
                detail = (result.stderr or result.stdout or "scancel failed").strip()
                append_log(job_id, f"Slurm: scancel for scheduler job {scheduler_id} failed: {detail}")
        else:
            append_log(job_id, "Slurm: cancellation requested before scheduler job id was recorded.")

        cancel_request = self._read_cancel_request(job_id)
        meta = read_job(job_id) or dict(job)
        meta["status"] = "failed"
        meta["stage"] = "cancelled"
        meta["error"] = str(cancel_request.get("reason") or "Cancelled by administrator")
        self._set_scheduler_metadata(
            meta,
            state="CANCELLED",
            clusterweave_status="failed",
            cancelled_at=now_iso(),
        )
        meta["log_count"] = len(read_logs(job_id))
        meta["updated_at"] = now_iso()
        write_job(meta)
        maybe_send_terminal_notification(job_id)
        if cancel_request.get("delete_after_cancel") or job_delete_path(job_id).exists():
            shutil.rmtree(job_dir(job_id), ignore_errors=True)

    def apply_polled_state(self, job: dict[str, Any], state: str) -> None:
        job_id = str(job.get("id") or "")
        if not job_id:
            return
        normalized = normalize_slurm_state(state)
        meta = read_job(job_id) or dict(job)
        previous_status = str(meta.get("status") or "").lower()
        previous_scheduler_state = str(slurm_scheduler_metadata(meta).get("state") or "")
        status, stage, error = clusterweave_status_for_slurm_state(normalized)

        if normalized != previous_scheduler_state:
            append_log(job_id, f"Slurm: scheduler state is {normalized}.")

        if previous_status not in TERMINAL_STATUSES and status in TERMINAL_STATUSES:
            meta["status"] = status
            meta["stage"] = stage
            meta["error"] = error
        elif previous_status not in TERMINAL_STATUSES:
            meta["status"] = status
            meta["stage"] = stage
            if error is not None:
                meta["error"] = error

        self._set_scheduler_metadata(
            meta,
            state=normalized,
            clusterweave_status=status,
            last_checked_at=now_iso(),
        )
        meta["log_count"] = len(read_logs(job_id))
        meta["updated_at"] = now_iso()
        write_job(meta)

        if previous_status not in TERMINAL_STATUSES and status in TERMINAL_STATUSES:
            maybe_send_terminal_notification(job_id)

    def poll_once(self) -> list[str]:
        active_job_ids: list[str] = []
        for job in list_jobs():
            job_id = str(job.get("id") or "")
            if not job_id:
                continue
            status = str(job.get("status") or "").lower()
            scheduler_id = slurm_job_id_for(job)
            if not scheduler_id:
                continue
            scheduler_state = normalize_slurm_state(slurm_scheduler_metadata(job).get("state"))
            scheduler_status, _, _ = clusterweave_status_for_slurm_state(scheduler_state)
            if status not in {"pending", "running"} and scheduler_status in TERMINAL_STATUSES:
                continue
            if job_cancel_requested(job_id):
                self.cancel_job(job)
                continue
            state = self.poll_scheduler_state(scheduler_id)
            self.apply_polled_state(job, state)
            updated = read_job(job_id) or job
            if str(updated.get("status") or "").lower() in {"pending", "running"}:
                active_job_ids.append(job_id)
        return active_job_ids

    def active_managed_job_ids(self) -> list[str]:
        ids: list[str] = []
        for job in list_jobs():
            if str(job.get("status") or "").lower() not in {"pending", "running"}:
                continue
            if slurm_job_id_for(job):
                ids.append(str(job.get("id")))
        return sorted(ids)

    def submit_waiting_claims(self) -> list[str]:
        if self.claim_next_job is None:
            return []
        submitted: list[str] = []
        active_count = len(self.active_managed_job_ids())
        while active_count < self.config.max_submitted:
            claim = self.claim_next_job()
            if claim is None:
                break
            job_id = self.submit_claim(claim)
            if job_id:
                submitted.append(job_id)
                active_count += 1
        return submitted

    async def loop(self) -> None:
        print(f"ClusterWeave Slurm backend started. max_submitted={self.config.max_submitted}")
        self._write_status(
            "ready",
            f"Slurm backend started (max_submitted={self.config.max_submitted})",
            "Waiting for queued jobs",
        )
        while True:
            active_ids = self.poll_once()
            submitted = self.submit_waiting_claims()
            if submitted:
                active_ids = self.active_managed_job_ids()
            if active_ids:
                self._write_status(
                    "processing",
                    f"Managing {len(active_ids)} Slurm job(s)",
                    ", ".join(active_ids),
                    active_jobs=active_ids,
                )
            else:
                self._write_status("idle", "Waiting for queued jobs")
            await asyncio.sleep(self.config.poll_seconds)
