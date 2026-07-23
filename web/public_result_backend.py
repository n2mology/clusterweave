"""Server-side lookup/cache for opaque public results."""

from __future__ import annotations

from collections import OrderedDict
import importlib
import os
from pathlib import Path
import threading
from typing import Callable

from public_results import (
    ArtifactCatalog,
    build_artifact_catalog,
    public_run_id_for_job,
    valid_public_run_id,
)
from result_attestation import (
    RESULT_ATTESTATION_PATH,
    read_result_attestation,
    schedule_result_attestation_backfill,
)
from result_policy import PUBLIC_RESULTS_MANIFEST_PATH


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


_CACHE_JOBS = _env_int("CLUSTERWEAVE_PUBLIC_ARTIFACT_CACHE_JOBS", 8)
_LOCK = threading.RLock()
_RUN_LOOKUP: OrderedDict[str, str] = OrderedDict()
_CATALOGS: OrderedDict[tuple[object, ...], ArtifactCatalog] = OrderedDict()


def _safe_file_identity(path: Path, base: Path) -> tuple[int, int, int, int, int] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        resolved = path.resolve()
        resolved.relative_to(base)
        info = resolved.stat()
        return (int(info.st_dev), int(info.st_ino), int(info.st_size), int(info.st_mtime_ns), int(info.st_ctime_ns))
    except (OSError, ValueError):
        return None


def _remember_run(public_id: str, internal_id: str) -> None:
    with _LOCK:
        _RUN_LOOKUP[public_id] = internal_id
        _RUN_LOOKUP.move_to_end(public_id)
        while len(_RUN_LOOKUP) > 1024:
            _RUN_LOOKUP.popitem(last=False)


def resolve_public_job(public_id: object) -> dict[str, object] | None:
    """Resolve an opaque alias through bounded summaries, never raw job scans."""

    requested = str(public_id or "")
    store = importlib.import_module("job_store")
    if not valid_public_run_id(requested):
        return None
    with _LOCK:
        cached_internal = _RUN_LOOKUP.get(requested, "")
    if cached_internal:
        cached = store.read_job(cached_internal)
        if cached is not None and public_run_id_for_job(cached) == requested:
            _remember_run(requested, cached_internal)
            return cached
        with _LOCK:
            _RUN_LOOKUP.pop(requested, None)

    matched_internal = ""
    for summary in store.list_job_summaries():
        if public_run_id_for_job(summary) != requested:
            continue
        candidate = str(summary.get("id") or "")
        if not candidate or (matched_internal and candidate != matched_internal):
            # A practically impossible collision fails closed.
            return None
        matched_internal = candidate
    if not matched_internal:
        return None
    job = store.read_job(matched_internal)
    if job is None or public_run_id_for_job(job) != requested:
        return None
    _remember_run(requested, matched_internal)
    return job


def artifact_catalog_for_job(
    job: dict[str, object],
    base_dir: Path,
    *,
    path_validator: Callable[[str], bool],
) -> ArtifactCatalog | None:
    """Return one generation-bound full server index from the signed attestation."""

    internal_id = str(job.get("id") or "")
    if not internal_id:
        return None
    base = base_dir.resolve()
    attestation_path = base / RESULT_ATTESTATION_PATH
    manifest = base / PUBLIC_RESULTS_MANIFEST_PATH
    attestation_identity = _safe_file_identity(attestation_path, base)
    manifest_identity = _safe_file_identity(manifest, base)
    if (
        attestation_identity is None
        or manifest_identity is None
    ):
        schedule_result_attestation_backfill(
            base,
            internal_id,
            path_validator=path_validator,
        )
        return None
    key = (
        internal_id,
        public_run_id_for_job(job),
        attestation_identity,
        manifest_identity,
    )
    with _LOCK:
        cached = _CATALOGS.get(key)
        if cached is not None:
            _CATALOGS.move_to_end(key)
            return cached
    attestation = read_result_attestation(base, internal_id)
    if attestation is None:
        schedule_result_attestation_backfill(
            base,
            internal_id,
            path_validator=path_validator,
        )
        return None
    if (
        _safe_file_identity(attestation_path, base) != attestation_identity
        or _safe_file_identity(manifest, base) != manifest_identity
    ):
        return None
    try:
        catalog = build_artifact_catalog(
            job,
            attestation,
            manifest_size=manifest_identity[2],
        )
    except (TypeError, ValueError):
        return None
    with _LOCK:
        for stale_key in [
            candidate
            for candidate in _CATALOGS
            if candidate[0] == internal_id and candidate != key
        ]:
            _CATALOGS.pop(stale_key, None)
        _CATALOGS[key] = catalog
        _CATALOGS.move_to_end(key)
        while len(_CATALOGS) > _CACHE_JOBS:
            _CATALOGS.popitem(last=False)
    return catalog


__all__ = ["artifact_catalog_for_job", "resolve_public_job"]
