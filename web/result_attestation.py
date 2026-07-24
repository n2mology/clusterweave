"""Persistent, signed public-result indexes for low-latency result browsing."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
import uuid

from result_policy import (
    PUBLIC_RESULTS_MANIFEST_PATH,
    normalized_job_result_path,
    result_is_public_archive,
    result_is_public_bigscape_viewer_database,
    result_path_public_shape,
)

RESULT_ATTESTATION_PATH = "downloads/.clusterweave_result_index.v1.json"
RESULT_ATTESTATION_SCHEMA = 1
MAX_ATTESTATION_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BACKFILL_LOCK = threading.Lock()
_BACKFILLS: set[str] = set()


@dataclass(frozen=True)
class ResultAttestation:
    job_id: str
    generation: str
    manifest_sha256: str
    files: tuple[tuple[str, int, str], ...]
    viewer_path: str = ""
    archive_path: str = ""
    archive_size: int = 0
    archive_sha256: str = ""
    archive_identity: tuple[int, int, int, int, int] = ()


def _secret() -> bytes:
    configured = os.environ.get("CLUSTERWEAVE_JOB_TOKEN_SECRET", "")
    seed = configured.encode("utf-8") if configured else b"clusterweave-local-result-index-v1"
    return hmac.new(seed, b"clusterweave-result-index-attestation-v1", hashlib.sha256).digest()


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _signature(payload: dict[str, object]) -> str:
    return hmac.new(_secret(), _canonical_bytes(payload), hashlib.sha256).hexdigest()


def _stable_bytes(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise OSError("index input is not a regular file")
    before = path.stat()
    if before.st_size > maximum:
        raise OSError("index input exceeds the bounded size")
    raw = path.read_bytes()
    after = path.stat()
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise OSError("index input changed while it was read")
    if len(raw) > maximum:
        raise OSError("index input exceeds the bounded size")
    return raw


def _manifest_rows(raw: bytes) -> tuple[tuple[str, int, str], ...]:
    lines = raw.decode("utf-8", errors="strict").splitlines()
    if not lines or lines[0] != "path\tbytes\tsha256":
        raise ValueError("invalid public result manifest header")
    rows: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for line in lines[1:]:
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            raise ValueError("invalid public result manifest row")
        raw_path, raw_size, digest = fields
        rel_path = normalized_job_result_path(raw_path)
        if (
            not rel_path
            or rel_path != raw_path
            or rel_path in seen
            or rel_path.lower() == PUBLIC_RESULTS_MANIFEST_PATH
            or result_is_public_archive(rel_path)
            or not result_path_public_shape(rel_path)
            or not raw_size.isdigit()
            or _SHA256_RE.fullmatch(digest) is None
        ):
            raise ValueError("unsafe public result manifest row")
        seen.add(rel_path)
        rows.append((rel_path, int(raw_size), digest))
    return tuple(rows)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(path: Path) -> tuple[int, int, int, int, int]:
    info = path.stat()
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def _archive_record(
    base: Path,
    rel_path: str,
) -> tuple[str, int, str, tuple[int, int, int, int, int]]:
    normalized = normalized_job_result_path(rel_path)
    if not normalized or not result_is_public_archive(normalized):
        raise ValueError("invalid public result package role")
    candidate = base / normalized
    if candidate.is_symlink():
        raise OSError("public result package symlink rejected")
    full = candidate.resolve(strict=True)
    full.relative_to(base)
    if not full.is_file():
        raise OSError("public result package is not a regular file")
    before = _file_identity(full)
    digest = _file_digest(full)
    after = _file_identity(full)
    if before != after:
        raise OSError("public result package changed while it was attested")
    return normalized, after[2], digest, after


def _validate_files(
    base: Path,
    rows: Iterable[tuple[str, int, str]],
    *,
    verify_hashes: bool,
    path_validator: Callable[[str], bool] | None,
) -> None:
    for rel_path, expected_size, expected_digest in rows:
        if path_validator is not None and not path_validator(rel_path):
            raise ValueError("public result failed its family-specific policy")
        candidate = base / rel_path
        if candidate.is_symlink():
            raise OSError("public result symlink rejected")
        full = candidate.resolve()
        full.relative_to(base)
        if not full.is_file() or full.stat().st_size != expected_size:
            raise OSError("public result identity does not match manifest")
        if verify_hashes and not hmac.compare_digest(_file_digest(full), expected_digest):
            raise OSError("public result digest does not match manifest")


def write_result_attestation(
    base_dir: Path,
    job_id: str,
    *,
    verify_hashes: bool,
    path_validator: Callable[[str], bool] | None = None,
    viewer_path: str = "",
    archive_path: str = "",
) -> ResultAttestation:
    base = base_dir.resolve()
    manifest_path = (base / PUBLIC_RESULTS_MANIFEST_PATH).resolve()
    manifest_path.relative_to(base)
    raw_manifest = _stable_bytes(manifest_path, MAX_MANIFEST_BYTES)
    rows = _manifest_rows(raw_manifest)
    _validate_files(
        base,
        rows,
        verify_hashes=verify_hashes,
        path_validator=path_validator,
    )
    normalized_viewer = normalized_job_result_path(viewer_path)
    if normalized_viewer:
        if (
            not result_is_public_bigscape_viewer_database(normalized_viewer)
            or not (base / normalized_viewer).is_file()
            or (base / normalized_viewer).is_symlink()
        ):
            raise ValueError("invalid BiG-SCAPE viewer role")
    manifest_sha256 = hashlib.sha256(raw_manifest).hexdigest()
    normalized_archive = ""
    archive_size = 0
    archive_sha256 = ""
    archive_identity: tuple[int, int, int, int, int] = ()
    if archive_path:
        (
            normalized_archive,
            archive_size,
            archive_sha256,
            archive_identity,
        ) = _archive_record(base, archive_path)
    generation = hashlib.sha256(
        f"{job_id}\0{manifest_sha256}".encode("utf-8")
    ).hexdigest()[:24]
    unsigned: dict[str, object] = {
        "schema_version": RESULT_ATTESTATION_SCHEMA,
        "job_id": str(job_id),
        "generation": generation,
        "created_at": datetime.now().isoformat(),
        "manifest": {
            "path": PUBLIC_RESULTS_MANIFEST_PATH,
            "bytes": len(raw_manifest),
            "sha256": manifest_sha256,
        },
        "files": [
            {"path": path, "bytes": size, "sha256": digest}
            for path, size, digest in rows
        ],
        "viewer_path": normalized_viewer,
    }
    if normalized_archive:
        unsigned["archive"] = {
            "path": normalized_archive,
            "bytes": archive_size,
            "sha256": archive_sha256,
            "identity": list(archive_identity),
        }
    payload = dict(unsigned)
    payload["signature"] = _signature(unsigned)
    target = base / RESULT_ATTESTATION_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_bytes(_canonical_bytes(payload) + b"\n")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return ResultAttestation(
        str(job_id),
        generation,
        manifest_sha256,
        rows,
        normalized_viewer,
        normalized_archive,
        archive_size,
        archive_sha256,
        archive_identity,
    )


def read_result_attestation(base_dir: Path, job_id: str) -> ResultAttestation | None:
    base = base_dir.resolve()
    target = base / RESULT_ATTESTATION_PATH
    try:
        raw = _stable_bytes(target, MAX_ATTESTATION_BYTES)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        signature = payload.pop("signature", None)
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature, _signature(payload)
        ):
            return None
        if payload.get("schema_version") != RESULT_ATTESTATION_SCHEMA:
            return None
        if str(payload.get("job_id") or "") != str(job_id):
            return None
        generation = str(payload.get("generation") or "")
        if not re.fullmatch(r"[0-9a-f]{24}", generation):
            return None
        manifest = payload.get("manifest")
        if not isinstance(manifest, dict):
            return None
        if manifest.get("path") != PUBLIC_RESULTS_MANIFEST_PATH:
            return None
        manifest_path = (base / PUBLIC_RESULTS_MANIFEST_PATH).resolve()
        manifest_path.relative_to(base)
        raw_manifest = _stable_bytes(manifest_path, MAX_MANIFEST_BYTES)
        manifest_sha256 = hashlib.sha256(raw_manifest).hexdigest()
        if (
            int(manifest.get("bytes", -1)) != len(raw_manifest)
            or not hmac.compare_digest(str(manifest.get("sha256") or ""), manifest_sha256)
        ):
            return None
        manifest_rows = _manifest_rows(raw_manifest)
        files = payload.get("files")
        if not isinstance(files, list):
            return None
        rows: list[tuple[str, int, str]] = []
        for item in files:
            if not isinstance(item, dict):
                return None
            rows.append(
                (
                    str(item.get("path") or ""),
                    int(item.get("bytes", -1)),
                    str(item.get("sha256") or ""),
                )
            )
        if tuple(rows) != manifest_rows:
            return None
        viewer_path = normalized_job_result_path(payload.get("viewer_path"))
        if viewer_path:
            if (
                not result_is_public_bigscape_viewer_database(viewer_path)
                or not (base / viewer_path).is_file()
                or (base / viewer_path).is_symlink()
            ):
                return None
        archive_path = ""
        archive_size = 0
        archive_sha256 = ""
        archive_identity: tuple[int, int, int, int, int] = ()
        archive = payload.get("archive")
        if archive is not None:
            if not isinstance(archive, dict):
                return None
            raw_archive_path = str(archive.get("path") or "")
            normalized_archive = normalized_job_result_path(raw_archive_path)
            raw_identity = archive.get("identity")
            try:
                signed_size = int(archive.get("bytes", -1))
                signed_identity = tuple(int(value) for value in raw_identity)
            except (TypeError, ValueError):
                return None
            signed_digest = str(archive.get("sha256") or "")
            if (
                normalized_archive != raw_archive_path
                or not result_is_public_archive(normalized_archive)
                or signed_size < 0
                or _SHA256_RE.fullmatch(signed_digest) is None
                or len(signed_identity) != 5
                or any(value < 0 for value in signed_identity)
                or signed_identity[2] != signed_size
            ):
                return None
            candidate = base / normalized_archive
            try:
                if candidate.is_symlink():
                    raise OSError("public result package symlink rejected")
                full = candidate.resolve(strict=True)
                full.relative_to(base)
                observed_identity = _file_identity(full)
            except (OSError, ValueError):
                observed_identity = ()
            if observed_identity == signed_identity:
                archive_path = normalized_archive
                archive_size = signed_size
                archive_sha256 = signed_digest
                archive_identity = signed_identity
        return ResultAttestation(
            str(job_id),
            generation,
            manifest_sha256,
            tuple(rows),
            viewer_path,
            archive_path,
            archive_size,
            archive_sha256,
            archive_identity,
        )
    except (OSError, ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        return None


def schedule_result_attestation_backfill(
    base_dir: Path,
    job_id: str,
    *,
    path_validator: Callable[[str], bool],
) -> bool:
    """Start at most one verified legacy backfill without blocking a request."""

    key = f"{base_dir.resolve()}::{job_id}"
    with _BACKFILL_LOCK:
        if key in _BACKFILLS:
            return False
        _BACKFILLS.add(key)

    def run() -> None:
        try:
            write_result_attestation(
                base_dir,
                job_id,
                verify_hashes=True,
                path_validator=path_validator,
            )
        except (OSError, ValueError, UnicodeError):
            pass
        finally:
            with _BACKFILL_LOCK:
                _BACKFILLS.discard(key)

    threading.Thread(
        target=run,
        name=f"result-index-{str(job_id)[:24]}",
        daemon=True,
    ).start()
    return True
