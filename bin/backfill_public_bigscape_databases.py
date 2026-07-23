#!/usr/bin/env python3
"""Backfill attested public BiG-SCAPE databases for terminal jobs.

The command is deliberately serial and resumable. It never processes active,
expired, or delete-requested jobs, and it refreshes persisted result indexes
only after the sanitized database, manifest, and prebuilt ZIP all succeed.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
for candidate in (Path("/app"), REPO_ROOT / "web"):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from bigscape_public_db import (  # noqa: E402
    find_raw_bigscape_databases,
    prepare_public_bigscape_databases,
)
from canonical_pipeline import (  # noqa: E402
    Job,
    JobStatus,
    ProjectLayout,
    _collect_result_files,
)
from job_store import (  # noqa: E402
    JOBS_DIR,
    append_log_lines,
    job_delete_path,
    now_iso,
    read_job,
    read_logs,
    write_job,
)
from result_policy import result_is_public_bigscape_database  # noqa: E402


TERMINAL_STATUSES = {JobStatus.SUCCESS.value, JobStatus.FAILED.value}


class _BackfillStateChanged(RuntimeError):
    """Stop publication when the historical job no longer matches the snapshot."""


def _expired(meta: dict[str, object]) -> bool:
    raw = str(meta.get("expires_at") or "").strip()
    if not raw:
        return False
    try:
        expires = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        now = datetime.now(expires.tzinfo)
    except (TypeError, ValueError):
        return True
    return expires <= now


def _safe_result_root(meta: dict[str, object], job_dir: Path) -> Path | None:
    try:
        resolved_job_dir = job_dir.resolve(strict=True)
    except OSError:
        return None
    raw = str(meta.get("result_root") or "").replace("\\", "/").strip("/")
    if raw:
        parts = Path(raw).parts
        if (
            len(parts) != 3
            or tuple(part.lower() for part in parts[:2]) != ("data", "results")
            or parts[2] in {"", ".", ".."}
        ):
            return None
        candidate = job_dir.joinpath(*parts)
        try:
            candidate.resolve(strict=True).relative_to(resolved_job_dir)
        except (OSError, ValueError):
            return None
        if candidate.is_dir() and not candidate.is_symlink():
            return candidate
    unresolved_base = job_dir / "data" / "results"
    try:
        base = unresolved_base.resolve(strict=True)
        base.relative_to(resolved_job_dir)
    except (OSError, ValueError):
        return None
    candidates: list[Path] = []
    if base.is_dir():
        for path in sorted(base.iterdir()):
            try:
                resolved_path = path.resolve(strict=True)
            except OSError:
                continue
            if (
                path.is_dir()
                and not path.is_symlink()
                and resolved_job_dir in resolved_path.parents
            ):
                candidates.append(path)
    return candidates[0] if len(candidates) == 1 else None


def _layout(_meta: dict[str, object], job_dir: Path, results_root: Path) -> ProjectLayout:
    # The verified result directory is the canonical project component. Do
    # not use historical user metadata to construct the public ZIP filename or
    # any filesystem path: older job records may predate current name
    # normalization.
    project_name = results_root.name
    data_root = job_dir / "data"
    return ProjectLayout(
        project_name=project_name,
        repo_root=Path(os.environ.get("CLUSTERWEAVE_ROOT", str(REPO_ROOT))),
        data_root=data_root,
        fungi_genome_root=data_root / "genomes" / "fungi" / project_name,
        bacteria_genome_root=data_root / "genomes" / "bacteria" / project_name,
        results_root=results_root,
        software_root=Path(
            os.environ.get("CLUSTERWEAVE_SOFTWARE_ROOT", "/data/software")
        ),
        work_root=job_dir / "work",
        downloads_root=job_dir / "downloads",
    )


def _job(meta: dict[str, object]) -> Job:
    status = JobStatus(str(meta.get("status") or JobStatus.FAILED.value).lower())
    return Job(
        id=str(meta["id"]),
        name=str(meta.get("name") or "job"),
        status=status,
        created_at=str(meta.get("created_at") or now_iso()),
        updated_at=str(meta.get("updated_at") or now_iso()),
        stage=str(meta.get("stage") or "complete"),
        log_lines=[],
        result_files=list(meta.get("result_files") or []),
        bigscape_viewer_database=str(
            meta.get("bigscape_viewer_database") or ""
        ),
        error=meta.get("error") if isinstance(meta.get("error"), str) else None,
        project_name=str(meta.get("project_name") or ""),
        result_root=str(meta.get("result_root") or ""),
    )


@contextmanager
def _publication_lock(job_dir: Path) -> Iterator[bool]:
    lock_path = job_dir / ".public-results.lock"
    with lock_path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _eligible(meta: dict[str, object], job_id: str, job_dir: Path) -> str:
    if str(meta.get("id") or "") != job_id:
        return "invalid metadata"
    if str(meta.get("status") or "").lower() not in TERMINAL_STATUSES:
        return "active"
    if job_delete_path(job_id).exists():
        return "delete requested"
    if _expired(meta):
        return "expired"
    if not job_dir.is_dir() or job_dir.is_symlink():
        return "unsafe job directory"
    return ""


def _state_token(meta: dict[str, object]) -> tuple[str, str, str, str, str]:
    """Return the immutable publication guard for one historical job state."""

    return (
        str(meta.get("status") or "").lower(),
        str(meta.get("updated_at") or ""),
        str(meta.get("result_root") or ""),
        str(meta.get("project_name") or ""),
        str(meta.get("expires_at") or ""),
    )


def backfill_one(job_id: str, *, force: bool = False, dry_run: bool = False) -> str:
    job_dir = JOBS_DIR / job_id
    meta = read_job(job_id)
    if not isinstance(meta, dict):
        return "skip: missing metadata"
    reason = _eligible(meta, job_id, job_dir)
    if reason:
        return f"skip: {reason}"
    if dry_run:
        results_root = _safe_result_root(meta, job_dir)
        if results_root is None:
            return "skip: ambiguous result root"
        if not find_raw_bigscape_databases(results_root):
            return "skip: no raw BiG-SCAPE database"
        return "ready"

    with _publication_lock(job_dir) as locked:
        if not locked:
            return "skip: publication busy"
        before = read_job(job_id)
        if not isinstance(before, dict):
            return "skip: metadata disappeared"
        reason = _eligible(before, job_id, job_dir)
        if reason:
            return f"skip: {reason}"
        # Re-resolve the root from the locked, freshly read metadata. The job
        # may have changed between the optimistic eligibility read above and
        # lock acquisition; sanitizing the earlier root would publish a stale
        # run under the newer job state.
        results_root = _safe_result_root(before, job_dir)
        if results_root is None:
            return "skip: ambiguous result root"
        if not find_raw_bigscape_databases(results_root):
            return "skip: no raw BiG-SCAPE database"
        state_token = _state_token(before)

        try:
            preparation = prepare_public_bigscape_databases(
                results_root,
                force=force,
            )
        except Exception as exc:
            return f"failed: sanitizer {type(exc).__name__}"
        if preparation.errors or not preparation.databases:
            return "failed: sanitized derivative unavailable"

        # Sanitizing a production-sized database is the longest operation. Do
        # not begin replacing public indexes if a rerun, delete, expiry, or
        # other state transition happened while the derivative was built.
        publish_state = read_job(job_id)
        if not isinstance(publish_state, dict):
            return "skip: metadata disappeared"
        if _state_token(publish_state) != state_token:
            return "skip: job state changed"
        reason = _eligible(publish_state, job_id, job_dir)
        if reason:
            return f"skip: {reason}"

        job = _job(publish_state)
        layout = _layout(publish_state, job_dir, results_root)
        job.bigscape_viewer_database = ""
        for database in preparation.databases:
            action = "reused" if database.reused else "created"
            job.add_log(
                "PUBLICATION: sanitized BiG-SCAPE database "
                f"{action} ({database.public_bytes} bytes)."
            )
        viewer_paths = [
            database.viewer_path
            for database in preparation.databases
            if getattr(database, "viewer_path", None) is not None
        ]
        if len(viewer_paths) == 1:
            try:
                job.bigscape_viewer_database = viewer_paths[0].relative_to(
                    job_dir
                ).as_posix()
            except ValueError:
                job.bigscape_viewer_database = ""
            if job.bigscape_viewer_database:
                viewer_bytes = next(
                    int(getattr(database, "viewer_bytes", 0))
                    for database in preparation.databases
                    if getattr(database, "viewer_path", None) == viewer_paths[0]
                )
                job.add_log(
                    "PUBLICATION: compact BiG-SCAPE web viewer ready "
                    f"({viewer_bytes} bytes)."
                )

        def assert_publish_state() -> None:
            current = read_job(job_id)
            if not isinstance(current, dict):
                raise _BackfillStateChanged("metadata disappeared")
            if _state_token(current) != state_token:
                raise _BackfillStateChanged("job state changed")
            reason = _eligible(current, job_id, job_dir)
            if reason:
                raise _BackfillStateChanged(reason)

        try:
            _collect_result_files(
                job,
                job_dir,
                layout,
                attested_bigscape_databases={
                    database.public_path.resolve()
                    for database in preparation.databases
                },
                before_publish=assert_publish_state,
            )
        except _BackfillStateChanged:
            return "skip: job state changed"
        except Exception as exc:
            return f"failed: publication {type(exc).__name__}"
        if not any(
            result_is_public_bigscape_database(path)
            for path in job.result_files
        ):
            return "failed: sanitized database was not indexed"

        current = read_job(job_id)
        if not isinstance(current, dict):
            return "skip: metadata disappeared"
        current_token = _state_token(current)
        if current_token != state_token or _eligible(current, job_id, job_dir):
            return "skip: job state changed"

        if job.log_lines:
            append_log_lines(job_id, job.log_lines)
        current["result_files"] = job.result_files
        current["bigscape_viewer_database"] = job.bigscape_viewer_database
        current["log_count"] = len(read_logs(job_id))
        current["updated_at"] = now_iso()
        write_job(current)
        action = "reused" if all(item.reused for item in preparation.databases) else "created"
        return f"ok: {action}"


def _job_ids(selected: list[str], limit: int) -> list[str]:
    if selected:
        values = selected
    else:
        values = sorted(
            path.parent.name
            for path in JOBS_DIR.glob("*/job.json")
            if path.parent.is_dir()
        )
    deduped = list(dict.fromkeys(values))
    return deduped[:limit] if limit > 0 else deduped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", action="append", default=[], help="job id (repeatable)")
    parser.add_argument("--limit", type=int, default=0, help="maximum jobs to inspect")
    parser.add_argument("--force", action="store_true", help="regenerate valid derivatives")
    parser.add_argument("--dry-run", action="store_true", help="report eligibility only")
    args = parser.parse_args()

    failures = 0
    for job_id in _job_ids(args.job, max(0, args.limit)):
        try:
            result = backfill_one(job_id, force=args.force, dry_run=args.dry_run)
        except Exception as exc:
            # A corrupt historical job must not prevent later jobs from being
            # inspected and repaired. Keep CLI output bounded and path-free.
            result = f"failed: unexpected {type(exc).__name__}"
        print(f"{job_id}\t{result}", flush=True)
        if result.startswith("failed:"):
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
