#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import threading
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
JOBS_DIR = DATA_DIR / "jobs"
QUEUE_DIR = DATA_DIR / "queue"
RETENTION_DIR = DATA_DIR / "retention"
RETENTION_TOTALS_PATH = RETENTION_DIR / "sweep_totals.json"
JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

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


LOG_INDEX_CHECKPOINT_LINES = env_int(
    "CLUSTERWEAVE_LOG_INDEX_CHECKPOINT_LINES", 2048, minimum=128
)
LOG_INDEX_CACHE_JOBS = env_int(
    "CLUSTERWEAVE_LOG_INDEX_CACHE_JOBS", 16, minimum=1
)
LOG_PREFIX_GUARD_WINDOWS = 8
LOG_PREFIX_GUARD_BYTES = 64
JOB_SUMMARY_FILENAME = "job_summary.v1.json"
JOB_SUMMARY_STAGE_SETTINGS = (
    "run_genome_prep",
    "run_annotation",
    "run_bigscape",
    "run_summary",
    "run_crosswalk",
    "run_clinker",
    "execute_clinker",
    "run_figures",
    "run_nplinker",
)


@dataclass(frozen=True)
class LogSlice:
    lines: list[str]
    total: int
    generation: str


@dataclass(frozen=True)
class LogWindow:
    lines: list[str]
    start: int
    end: int
    total: int
    generation: str


@dataclass
class _LogFileIndex:
    identity: tuple[int, int] | None
    generation: str = field(default_factory=lambda: uuid.uuid4().hex)
    scan_offset: int = 0
    total_lines: int = 0
    checkpoints: list[int] = field(default_factory=lambda: [0])
    prefix_guards: list[tuple[int, bytes]] = field(default_factory=list)
    pending_rewrite: tuple[int, int, int] | None = None


_LOG_INDEX_LOCK = threading.RLock()
_LOG_INDEXES: OrderedDict[str, _LogFileIndex] = OrderedDict()


def _new_log_file_index(identity: tuple[int, int] | None) -> _LogFileIndex:
    return _LogFileIndex(identity=identity)


def _remember_log_file_index(job_id: str, state: _LogFileIndex) -> None:
    _LOG_INDEXES[job_id] = state
    _LOG_INDEXES.move_to_end(job_id)
    while len(_LOG_INDEXES) > LOG_INDEX_CACHE_JOBS:
        _LOG_INDEXES.popitem(last=False)


def _clone_log_file_index(state: _LogFileIndex) -> _LogFileIndex:
    return _LogFileIndex(
        identity=state.identity,
        generation=state.generation,
        scan_offset=state.scan_offset,
        total_lines=state.total_lines,
        checkpoints=list(state.checkpoints),
        prefix_guards=list(state.prefix_guards),
        pending_rewrite=state.pending_rewrite,
    )


def _log_prefix_guard_positions(length: int) -> list[int]:
    if length <= 0:
        return []
    last_start = max(0, length - LOG_PREFIX_GUARD_BYTES)
    if last_start == 0:
        return [0]
    return sorted(
        {
            (last_start * index) // (LOG_PREFIX_GUARD_WINDOWS - 1)
            for index in range(LOG_PREFIX_GUARD_WINDOWS)
        }
    )


def _capture_log_prefix_guards(handle: Any, length: int) -> list[tuple[int, bytes]]:
    original = handle.tell()
    guards: list[tuple[int, bytes]] = []
    try:
        for offset in _log_prefix_guard_positions(length):
            handle.seek(offset)
            guards.append((offset, handle.read(LOG_PREFIX_GUARD_BYTES)))
    finally:
        handle.seek(original)
    return guards


def _log_prefix_guards_match(handle: Any, state: _LogFileIndex) -> bool:
    if state.scan_offset <= 0:
        return True
    if not state.prefix_guards:
        return False
    original = handle.tell()
    try:
        for offset, expected in state.prefix_guards:
            handle.seek(offset)
            if handle.read(len(expected)) != expected:
                return False
    finally:
        handle.seek(original)
    return True


@contextmanager
def _job_log_write_lock(job_id: str) -> Iterator[None]:
    lock_path = job_dir(job_id) / ".logs.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


def valid_job_id(job_id: object) -> bool:
    value = str(job_id or "")
    return bool(JOB_ID_RE.fullmatch(value)) and value not in {".", ".."}


def job_dir(job_id: str) -> Path:
    value = str(job_id or "")
    if not valid_job_id(value):
        raise ValueError("Invalid ClusterWeave job identifier")
    return JOBS_DIR / value


def job_meta_path(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def job_logs_path(job_id: str) -> Path:
    return job_dir(job_id) / "logs.txt"


def job_cancel_path(job_id: str) -> Path:
    return job_dir(job_id) / "cancel.requested"


def job_delete_path(job_id: str) -> Path:
    return job_dir(job_id) / "delete.requested"



def job_summary_path(job_id: str) -> Path:
    return job_dir(job_id) / JOB_SUMMARY_FILENAME

def job_cancel_requested(job_id: str) -> bool:
    if not valid_job_id(job_id):
        return True
    return job_cancel_path(job_id).exists()


def request_job_cancel(job_id: str, reason: str = "Cancellation requested", *, delete_after_cancel: bool = False) -> None:
    target = job_dir(job_id)
    target.mkdir(parents=True, exist_ok=True)
    payload = {"requested_at": now_iso(), "reason": reason, "delete_after_cancel": delete_after_cancel}
    job_cancel_path(job_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if delete_after_cancel:
        job_delete_path(job_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_job(job_id: str) -> dict[str, Any] | None:
    if not valid_job_id(job_id):
        return None
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


def compact_job_summary(job: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded, public-safe shape used by the admin job drawer."""

    summary: dict[str, Any] = {
        key: job[key]
        for key in (
            "id", "public_run_id", "name", "project_name", "status", "stage", "created_at",
            "updated_at", "completed_at", "failed_at", "expires_at",
            "retention_days", "log_count", "rerun_count", "analysis_scope",
            "taxon_counts", "applicability_counts",
        )
        if key in job
    }
    result_files = job.get("result_files")
    summary["result_file_count"] = (
        len(result_files) if isinstance(result_files, (list, tuple)) else 0
    )
    settings = job.get("settings")
    if isinstance(settings, dict):
        stage_settings = {
            key: settings[key]
            for key in JOB_SUMMARY_STAGE_SETTINGS
            if key in settings
        }
        if stage_settings:
            summary["settings"] = stage_settings
        if "analysis_scope" not in summary and "analysis_scope" in settings:
            summary["analysis_scope"] = settings["analysis_scope"]
    rerun_source = job.get("submission_settings")
    if not isinstance(rerun_source, dict):
        rerun_source = settings
    if isinstance(rerun_source, dict):
        rerun_stage_settings = {
            key: (
                value
                if isinstance(value := rerun_source[key], bool)
                else str(value).strip().lower() in {"1", "true", "yes", "on"}
            )
            for key in JOB_SUMMARY_STAGE_SETTINGS
            if key in rerun_source
        }
        if rerun_stage_settings:
            summary["rerun_stage_settings"] = rerun_stage_settings
    input_summary = job.get("input_summary")
    if isinstance(input_summary, dict):
        summary["input_summary"] = {
            key: input_summary[key]
            for key in (
                "accession_count", "genome_file_count", "metadata_file_count",
                "genome_count", "analysis_scope", "taxon_counts",
                "applicability_counts",
            )
            if key in input_summary
        }
    return summary


def write_job(job: dict[str, Any]) -> None:
    apply_retention_metadata(job)
    path = job_meta_path(job["id"])
    atomic_write_text(path, json.dumps(job, ensure_ascii=False, indent=2))
    atomic_write_text(
        job_summary_path(str(job["id"])),
        json.dumps(compact_job_summary(job), ensure_ascii=False, separators=(",", ":")),
    )


def list_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for path in sorted(JOBS_DIR.glob("*/job.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(job, dict):
                continue
            job_id = str(job.get("id") or "")
            if not valid_job_id(job_id) or job_id != path.parent.name:
                continue
            jobs.append(job)
        except Exception:
            continue
    jobs.sort(key=lambda j: j.get("updated_at", ""), reverse=True)
    return jobs


def list_job_summaries() -> list[dict[str, Any]]:
    """Read compact drawer records, with a legacy job.json fallback."""

    summaries: list[dict[str, Any]] = []
    for directory in sorted(JOBS_DIR.iterdir() if JOBS_DIR.exists() else []):
        if not directory.is_dir() or not valid_job_id(directory.name):
            continue
        summary_path = directory / JOB_SUMMARY_FILENAME
        source_path = summary_path if summary_path.is_file() else directory / "job.json"
        try:
            value = json.loads(source_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                continue
            if source_path != summary_path:
                value = compact_job_summary(value)
            elif "rerun_stage_settings" not in value:
                legacy_job_path = directory / "job.json"
                legacy_job = json.loads(legacy_job_path.read_text(encoding="utf-8"))
                legacy_job_id = (
                    str(legacy_job.get("id") or "")
                    if isinstance(legacy_job, dict)
                    else ""
                )
                if legacy_job_id != directory.name or not valid_job_id(legacy_job_id):
                    continue
                value = compact_job_summary(legacy_job)
                atomic_write_text(
                    summary_path,
                    json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                )
            job_id = str(value.get("id") or "")
            if job_id != directory.name or not valid_job_id(job_id):
                continue
            summaries.append(value)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    summaries.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return summaries


def read_logs(job_id: str) -> list[str]:
    if not valid_job_id(job_id):
        return []
    path = job_logs_path(job_id)
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _refresh_log_file_index(
    job_id: str, path: Path, minimum_total: int = 0
) -> tuple[_LogFileIndex, int, bytes, bool]:
    """Refresh a sparse newline index and return newly completed log bytes.

    Supported writers either append or atomically replace ``logs.txt``. Prefix
    guards also detect legacy/external same-inode rewrites without making every
    poll hash the full history. A transient truncate-and-rewrite is withheld
    until it is stable, and ``minimum_total`` lets job metadata protect a known
    historical prefix while an older worker is being drained.
    """

    original = _LOG_INDEXES.get(job_id)
    try:
        handle = path.open("rb")
    except OSError:
        if original is None:
            state = _new_log_file_index(None)
            _remember_log_file_index(job_id, state)
            return state, 0, b"", True
        if original.identity is None:
            return original, original.total_lines, b"", True
        return original, original.total_lines, b"", False

    with handle:
        before = os.fstat(handle.fileno())
        identity = (int(before.st_dev), int(before.st_ino))
        before_signature = (
            int(before.st_size),
            int(before.st_mtime_ns),
            int(before.st_ctime_ns),
        )
        replacement = original is None or original.identity != identity

        if replacement:
            working = _new_log_file_index(identity)
        elif int(before.st_size) < original.scan_offset:
            if original.pending_rewrite != before_signature:
                pending = _clone_log_file_index(original)
                pending.pending_rewrite = before_signature
                _remember_log_file_index(job_id, pending)
                return pending, pending.total_lines, b"", False
            working = _new_log_file_index(identity)
            replacement = True
        elif not _log_prefix_guards_match(handle, original):
            working = _new_log_file_index(identity)
            replacement = True
        else:
            working = _clone_log_file_index(original)
            working.pending_rewrite = None

        appended_start_line = working.total_lines
        appended_complete = b""
        target_size = int(before.st_size)
        if target_size > working.scan_offset:
            handle.seek(working.scan_offset)
            appended = handle.read(target_size - working.scan_offset)
            complete_end = appended.rfind(b"\n") + 1
            if complete_end > 0:
                appended_complete = appended[:complete_end]
                base_offset = working.scan_offset
                cursor = 0
                while True:
                    newline = appended_complete.find(b"\n", cursor)
                    if newline < 0:
                        break
                    cursor = newline + 1
                    working.total_lines += 1
                    if working.total_lines % LOG_INDEX_CHECKPOINT_LINES == 0:
                        working.checkpoints.append(base_offset + cursor)
                working.scan_offset += complete_end

        after = os.fstat(handle.fileno())
        after_identity = (int(after.st_dev), int(after.st_ino))
        after_signature = (
            int(after.st_size),
            int(after.st_mtime_ns),
            int(after.st_ctime_ns),
        )
        stable = after_identity == identity and int(after.st_size) >= target_size
        if replacement:
            # A replacement must be quiescent for the complete scan. Appends to
            # an already indexed file may safely continue beyond target_size.
            stable = stable and after_signature == before_signature
        elif original is not None:
            stable = stable and _log_prefix_guards_match(handle, original)

        if stable:
            working.prefix_guards = _capture_log_prefix_guards(
                handle, working.scan_offset
            )
            final = os.fstat(handle.fileno())
            final_identity = (int(final.st_dev), int(final.st_ino))
            stable = final_identity == identity and int(final.st_size) >= working.scan_offset
            if replacement:
                stable = stable and (
                    int(final.st_size),
                    int(final.st_mtime_ns),
                    int(final.st_ctime_ns),
                ) == before_signature

        if not stable or working.total_lines < max(0, int(minimum_total)):
            if original is not None:
                return original, original.total_lines, b"", False
            return working, 0, b"", False

        _remember_log_file_index(job_id, working)
        return working, appended_start_line, appended_complete, True


def read_log_slice(
    job_id: str,
    since: int = 0,
    minimum_total: int = 0,
    limit: int | None = None,
) -> LogSlice:
    """Read a bounded log slice without splitting the whole file."""

    if not valid_job_id(job_id):
        return LogSlice(lines=[], total=0, generation="")
    try:
        requested = max(0, int(since))
    except (TypeError, ValueError):
        requested = 0
    path = job_logs_path(job_id)

    with _LOG_INDEX_LOCK:
        state, appended_start_line, appended_complete, readable = (
            _refresh_log_file_index(job_id, path, minimum_total)
        )
        if not readable:
            return LogSlice(lines=[], total=requested, generation=state.generation)
        total = state.total_lines
        if requested >= total:
            return LogSlice(lines=[], total=total, generation=state.generation)

        bounded_limit = None if limit is None else max(0, int(limit))
        target_end = total if bounded_limit is None else min(total, requested + bounded_limit)
        if target_end <= requested:
            return LogSlice(lines=[], total=total, generation=state.generation)

        if appended_complete and requested >= appended_start_line:
            data = appended_complete
            skip = requested - appended_start_line
        else:
            checkpoint_index = min(
                requested // LOG_INDEX_CHECKPOINT_LINES,
                len(state.checkpoints) - 1,
            )
            checkpoint_line = checkpoint_index * LOG_INDEX_CHECKPOINT_LINES
            start_offset = state.checkpoints[checkpoint_index]
            end_checkpoint_index = (
                target_end + LOG_INDEX_CHECKPOINT_LINES - 1
            ) // LOG_INDEX_CHECKPOINT_LINES
            end_offset = (
                state.checkpoints[end_checkpoint_index]
                if end_checkpoint_index < len(state.checkpoints)
                else state.scan_offset
            )
            try:
                with path.open("rb") as handle:
                    current = os.fstat(handle.fileno())
                    current_identity = (int(current.st_dev), int(current.st_ino))
                    if (
                        current_identity != state.identity
                        or int(current.st_size) < state.scan_offset
                        or not _log_prefix_guards_match(handle, state)
                    ):
                        return LogSlice(
                            lines=[], total=requested, generation=state.generation
                        )
                    handle.seek(start_offset)
                    data = handle.read(max(0, end_offset - start_offset))
                    if not _log_prefix_guards_match(handle, state):
                        return LogSlice(
                            lines=[], total=requested, generation=state.generation
                        )
            except OSError:
                return LogSlice(lines=[], total=requested, generation=state.generation)
            skip = requested - checkpoint_line

        decoded = data.decode("utf-8", errors="replace").splitlines()
        lines = decoded[skip : skip + (target_end - requested)]
        return LogSlice(lines=lines, total=total, generation=state.generation)


def read_log_window(
    job_id: str,
    *,
    tail: bool = False,
    before: int | None = None,
    limit: int = 500,
    minimum_total: int = 0,
) -> LogWindow:
    """Return one bounded log page suitable for lazy QA hydration."""

    bounded_limit = min(1000, max(1, int(limit)))
    snapshot = read_log_slice(job_id, 0, minimum_total, limit=0)
    total = snapshot.total
    if before is not None:
        end = min(total, max(0, int(before)))
        start = max(0, end - bounded_limit)
    elif tail:
        end = total
        start = max(0, total - bounded_limit)
    else:
        start = 0
        end = min(total, bounded_limit)
    page = read_log_slice(
        job_id,
        start,
        minimum_total,
        limit=max(0, end - start),
    )
    stable_end = min(page.total, start + len(page.lines))
    return LogWindow(
        lines=page.lines,
        start=start,
        end=stable_end,
        total=page.total,
        generation=page.generation,
    )


def read_logs_since(
    job_id: str, since: int = 0, minimum_total: int = 0
) -> tuple[list[str], int]:
    snapshot = read_log_slice(job_id, since, minimum_total)
    return snapshot.lines, snapshot.total


def write_logs(job_id: str, lines: list[str]) -> None:
    path = job_logs_path(job_id)
    data = "\n".join(lines)
    if data:
        data += "\n"
    with _LOG_INDEX_LOCK:
        with _job_log_write_lock(job_id):
            atomic_write_text(path, data)
        _LOG_INDEXES.pop(job_id, None)


def append_log_lines(job_id: str, lines: list[str]) -> int:
    """Append complete logical records without rewriting prior log history."""

    materialized = [str(line).rstrip("\r\n") for line in lines]
    if not materialized:
        return 0
    payload = ("\n".join(materialized) + "\n").encode("utf-8")
    path = job_logs_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _job_log_write_lock(job_id):
        with path.open("a+b", buffering=0) as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size:
                handle.seek(-1, os.SEEK_END)
                needs_separator = handle.read(1) != b"\n"
            else:
                needs_separator = False
            handle.seek(0, os.SEEK_END)
            if needs_separator:
                handle.write(b"\n")
            view = memoryview(payload)
            while view:
                written = handle.write(view)
                if not written:
                    raise OSError("Unable to append ClusterWeave log records")
                view = view[written:]
    return len(materialized)


def append_log(job_id: str, message: str) -> str:
    line = ts_line(message)
    append_log_lines(job_id, [line])
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
            "completed_jobs_deleted": 0,
            "expired_files_deleted": 0,
            "expired_bytes_deleted": 0,
            "last_sweep_at": None,
        }
    try:
        payload = json.loads(RETENTION_TOTALS_PATH.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    expired_jobs_deleted = int(payload.get("expired_jobs_deleted") or 0)
    return {
        "expired_jobs_deleted": expired_jobs_deleted,
        # Preserve terminal history written before this counter existed.
        "completed_jobs_deleted": int(
            payload.get("completed_jobs_deleted", expired_jobs_deleted) or 0
        ),
        "expired_files_deleted": int(payload.get("expired_files_deleted") or 0),
        "expired_bytes_deleted": int(payload.get("expired_bytes_deleted") or 0),
        "last_sweep_at": payload.get("last_sweep_at"),
    }


def write_retention_totals(totals: dict[str, Any]) -> None:
    RETENTION_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(RETENTION_TOTALS_PATH, json.dumps(totals, ensure_ascii=False, indent=2))


def record_deleted_terminal_job(job: dict[str, Any]) -> None:
    if str(job.get("status") or "").lower() not in {"success", "failed"}:
        return
    totals = read_retention_totals()
    totals["completed_jobs_deleted"] = int(totals.get("completed_jobs_deleted") or 0) + 1
    write_retention_totals(totals)


def job_is_expired(job: dict[str, Any], now: datetime | None = None) -> bool:
    # Retention applies only after a job reaches a terminal state. Pending jobs
    # can legitimately remain queued longer than the retention window during a
    # large public backlog, and running jobs must never be removed underneath an
    # active worker merely because their creation timestamp is old.
    if str(job.get("status") or "").lower() not in {"success", "failed"}:
        return False
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
    totals["completed_jobs_deleted"] = int(totals.get("completed_jobs_deleted") or 0) + deleted_jobs
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
