#!/usr/bin/env python3
"""Immutable local entries for supported accession-preparation contracts."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
from typing import Callable
import uuid

SCHEMA = 1
CONTRACTS = {
    "bacterial-genbank-v1": {"prepared.gbk", "record_map.tsv", "record_ids.txt"},
    "fungal-existing-cds-v1": {"prepared.gbk"},
    "accession-snapshot-v1": {"bundle.tar"},
    "accession-detection-v1": {"bundle.tar"},
    "accession-snapshot-v2": {"bundle.tar"},
    "accession-detection-v2": {"bundle.tar"},
    "accession-detection-v3": {"bundle.tar"},
}
ACCESSION = re.compile(r"GC[AF]_[0-9]+\.[1-9][0-9]*\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 16384


class Unavailable(ValueError):
    """The store or identity cannot safely be used."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity_key(identity: dict) -> str:
    expected = {"schema", "contract", "accession", "genome_sha256", "route", "source_sha256",
                "runtime_sha256", "tools", "containers", "databases", "models", "parameters"}
    if set(identity) != expected or type(identity["schema"]) is not int or identity["schema"] != SCHEMA:
        raise Unavailable("identity_schema")
    contract = identity["contract"]
    if not isinstance(contract, str) or contract not in CONTRACTS:
        raise Unavailable("identity_contract")
    if not isinstance(identity["accession"], str) or not ACCESSION.fullmatch(identity["accession"]):
        raise Unavailable("accession_version")
    for name in ("genome_sha256", "source_sha256", "runtime_sha256"):
        if not isinstance(identity[name], str) or not DIGEST.fullmatch(identity[name]):
            raise Unavailable("identity_digest")
    if contract in {"accession-snapshot-v1", "accession-detection-v1", "accession-snapshot-v2", "accession-detection-v2", "accession-detection-v3"}:
        from cached_accession import validate_identity
        validate_identity(identity)
        return sha256(canonical(identity))
    bacterial = contract == "bacterial-genbank-v1"
    if identity["route"] != {"taxon": "bacteria" if bacterial else "fungi",
                              "annotation": "sequence-only" if bacterial else "existing-cds"}:
        raise Unavailable("identity_route")
    if identity["tools"] != {"python": identity["runtime_sha256"], "preparation": identity["source_sha256"]}:
        raise Unavailable("identity_tools")
    if any(identity[name] != "not-used" for name in ("containers", "databases", "models")):
        raise Unavailable("identity_dependencies")
    params = identity["parameters"]
    if not isinstance(params, dict) or set(params) != {"genome_label_sha256", "min_record_bp", "max_record_bp"}:
        raise Unavailable("identity_parameters")
    if not isinstance(params["genome_label_sha256"], str) or not DIGEST.fullmatch(params["genome_label_sha256"]):
        raise Unavailable("identity_parameters")
    if any(type(params[name]) is not int for name in ("min_record_bp", "max_record_bp")):
        raise Unavailable("identity_parameters")
    if bacterial:
        if not 1 <= params["min_record_bp"] <= params["max_record_bp"] <= MAX_FILE_BYTES:
            raise Unavailable("identity_parameters")
    elif params["min_record_bp"] != 0 or params["max_record_bp"] != 0:
        raise Unavailable("identity_parameters")
    return sha256(canonical(identity))


def regular_bytes(path: Path, limit: int = MAX_FILE_BYTES, *, allow_empty: bool = False) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not (0 if allow_empty else 1) <= info.st_size <= limit:
            raise Unavailable("file_type_or_size")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read(limit + 1)
        after = os.fstat(descriptor)
        if len(data) != info.st_size or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (info.st_size, info.st_mtime_ns, info.st_ctime_ns):
            raise Unavailable("file_changed")
        return data
    finally:
        os.close(descriptor)


def safe_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise Unavailable("directory_type")
    info = path.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise Unavailable("directory_owner_or_mode")


def reject_symlink_parents(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise Unavailable("symlink_path")


class Store:
    def __init__(self, root: Path, *, max_bytes: int = 10 * 1024**3,
                 max_entries: int = 256, max_age_seconds: int = 30 * 86400):
        if not root.is_absolute():
            raise Unavailable("absolute_root_required")
        self.root = root
        if min(max_bytes, max_entries, max_age_seconds) < 1:
            raise Unavailable("capacity")
        self.max_bytes, self.max_entries, self.max_age = max_bytes, max_entries, max_age_seconds
        self._catalog_pending = []
        self._catalog_locked = False

    @contextmanager
    def locked(self):
        # The operator provisions the root; a typo must not create storage in job data.
        reject_symlink_parents(self.root)
        safe_directory(self.root)
        lock = os.open(self.root / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
                raise Unavailable("lock_type")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Unavailable("busy") from exc
            for name in ("entries", "quarantine"):
                directory = self.root / name
                directory.mkdir(mode=0o700, exist_ok=True)
                safe_directory(directory)
            # Staging through rename holds this lock; leftovers are abandoned.
            for path in self.root.glob(".pending-*"):
                self._remove(path)
            self._catalog_locked = True
            yield
        finally:
            os.close(lock)
            self._catalog_locked = False
            self._flush_catalog_events()

    @staticmethod
    def _remove(path: Path) -> None:
        if path.is_symlink() or not path.is_dir():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path)

    def _quarantine(self, entry: Path) -> None:
        os.replace(entry, self.root / "quarantine" / uuid.uuid4().hex)
        self._catalog_event(key=entry.name, state="quarantined")

    def _catalog(self):
        # The index is metadata only. It must never change a scientific hit/miss.
        reject_symlink_parents(self.root)
        safe_directory(self.root)
        web = Path(__file__).resolve().parents[1] / "web"
        if str(web) not in sys.path:
            sys.path.insert(0, str(web))
        from accession_catalog import Catalog, catalog_path
        identifier = self.root / ".catalog-id"
        if not identifier.exists():
            try:
                fd = os.open(identifier, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(uuid.uuid4().hex.encode())
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError:
                pass
        store_id = regular_bytes(identifier, 32).decode()
        info = identifier.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise Unavailable("catalog_identifier_owner_or_mode")
        return Catalog(catalog_path(self.root)), store_id

    def _catalog_row(self, entry: Path, manifest: dict | None = None, *, expected_key=None):
        from accession_catalog import manifest_row
        safe_directory(entry)
        raw = regular_bytes(entry / "manifest.json", MAX_MANIFEST_BYTES)
        value = json.loads(raw)
        if (canonical(value) != raw or set(value) != {"schema", "key", "identity", "files"}
                or type(value["schema"]) is not int or value["schema"] != SCHEMA
                or value["key"] != (expected_key or entry.name)
                or identity_key(value["identity"]) != value["key"]
                or manifest is not None and value != manifest):
            raise Unavailable("catalog_manifest")
        contract = value["identity"]["contract"]
        if set(value["files"]) != CONTRACTS[contract]:
            raise Unavailable("catalog_inventory")
        if {p.name for p in entry.iterdir()} != CONTRACTS[contract] | {"manifest.json"}:
            raise Unavailable("catalog_inventory")
        for name, item in value["files"].items():
            info = (entry / name).lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or set(item) != {"bytes", "sha256"} or type(item["bytes"]) is not int
                    or not 0 < item["bytes"] <= MAX_FILE_BYTES or item["bytes"] != info.st_size
                    or not isinstance(item["sha256"], str) or not DIGEST.fullmatch(item["sha256"])):
                raise Unavailable("catalog_inventory")
        return manifest_row(value, digest=sha256(raw), populated=entry.stat().st_mtime, max_age=self.max_age)

    def _catalog_event(self, *, entry=None, manifest=None, key=None, state=None, failure=None):
        event = {"key": entry.name if entry is not None else key, "state": state}
        if failure is not None:
            event["failure"] = failure
        self._catalog_pending.append(event)
        if not self._catalog_locked:
            self._flush_catalog_events()

    def _flush_catalog_events(self):
        # Loading SQLite in a scientific preparation process changes its loaded
        # native-library fingerprint. Isolate bookkeeping in a separate process.
        events, self._catalog_pending = self._catalog_pending, []
        if not events:
            return
        try:
            script = Path(__file__).resolve().parents[1] / "web/accession_catalog.py"
            body = canonical({"root": str(self.root), "max_age": self.max_age, "events": events}).decode()
            actions = [(os.POSIX_SPAWN_OPEN, fd, os.devnull, os.O_WRONLY, 0o600) for fd in (1, 2)]
            pid = os.posix_spawn(sys.executable, [sys.executable, "-B", str(script), "--store-events", body],
                                 dict(os.environ), file_actions=actions)
            deadline = time.monotonic() + 3
            while not os.waitpid(pid, os.WNOHANG)[0]:
                if time.monotonic() >= deadline:
                    os.kill(pid, 9)
                    os.waitpid(pid, 0)
                    break
                time.sleep(0.01)
        except Exception:
            # A failed index update is repaired by reconciliation. Lookup remains
            # authoritative even when the catalog is unavailable or incomplete.
            pass

    def reconcile_catalog(self, *, legacy=(), active=(), failures=(), complete=True):
        with self.locked():
            catalog, store_id = self._catalog()
            rows = []
            from accession_catalog import CONTRACTS as indexed_contracts
            for entry in (self.root / "entries").iterdir():
                try:
                    row = self._catalog_row(entry)
                    if row["contract"] in indexed_contracts:
                        rows.append(row)
                except Exception:
                    complete = False
            present = {row["key"] for row in rows}
            for entry in (self.root / "quarantine").iterdir():
                try:
                    safe_directory(entry)
                    raw = json.loads(regular_bytes(entry / "manifest.json", MAX_MANIFEST_BYTES))
                    row = self._catalog_row(entry, expected_key=raw["key"])
                    if row["contract"] in indexed_contracts and row["key"] not in present:
                        row["state"] = "quarantined"
                        rows.append(row)
                        present.add(row["key"])
                except Exception:
                    # A quarantine manifest may itself be the corrupt file.
                    continue
            catalog.reconcile(store_id, rows, legacy=legacy, active=active, failures=failures, complete=complete)
            return catalog

    def _prune(self, *, reserve: int = 0, slots: int = 0) -> None:
        candidates = []
        now = time.time()
        for group in ("quarantine", "entries"):
            for entry in (self.root / group).iterdir():
                if entry.is_symlink() or not entry.is_dir():
                    self._remove(entry)
                    continue
                size = sum(p.lstat().st_size for p in entry.rglob("*") if not p.is_dir() or p.is_symlink())
                age = entry.stat().st_mtime
                if now - age > self.max_age:
                    self._remove(entry)
                    if group == "entries":
                        self._catalog_event(key=entry.name, state="expired")
                else:
                    candidates.append((group != "quarantine", age, entry, size))
        candidates.sort(key=lambda row: (row[0], row[1], row[2].name))
        total = sum(row[3] for row in candidates)
        count = len(candidates)
        for _, _, entry, size in candidates:
            if total + reserve <= self.max_bytes and count + slots <= self.max_entries:
                break
            self._remove(entry)
            if entry.parent.name == "entries":
                self._catalog_event(key=entry.name, state="absent")
            total -= size
            count -= 1

    def _read(self, key: str, identity: dict, validate: Callable) -> tuple[dict, dict]:
        entry = self.root / "entries" / key
        safe_directory(entry)
        if {p.name for p in entry.iterdir()} != CONTRACTS[identity["contract"]] | {"manifest.json"}:
            raise Unavailable("file_inventory")
        raw = regular_bytes(entry / "manifest.json", MAX_MANIFEST_BYTES)
        manifest = json.loads(raw)
        if canonical(manifest) != raw or set(manifest) != {"schema", "key", "identity", "files"}:
            raise Unavailable("manifest_schema")
        if type(manifest["schema"]) is not int or manifest["schema"] != SCHEMA or manifest["key"] != key or manifest["identity"] != identity:
            raise Unavailable("manifest_identity")
        if identity_key(manifest["identity"]) != key:
            raise Unavailable("manifest_key")
        files = manifest["files"]
        if not isinstance(files, dict) or set(files) != CONTRACTS[identity["contract"]]:
            raise Unavailable("manifest_files")
        payload = {}
        for name, record in files.items():
            data = regular_bytes(entry / name)
            if record != {"bytes": len(data), "sha256": sha256(data)}:
                raise Unavailable("file_digest")
            payload[name] = data
        validate(payload)
        return payload, manifest

    def lookup(self, identity: dict, validate: Callable) -> tuple[dict | None, str, dict | None]:
        key = identity_key(identity)
        with self.locked():
            self._prune()
            entry = self.root / "entries" / key
            if not entry.exists() and not entry.is_symlink():
                self._catalog_event(key=key, state="absent")
                return None, "absent", None
            try:
                payload, manifest = self._read(key, identity, validate)
                self._catalog_event(entry=entry, manifest=manifest)
                return payload, "verified", manifest
            except Exception:
                self._quarantine(entry)
                self._prune()
                return None, "quarantined", None

    def publish(self, identity: dict, payload: dict[str, bytes], validate: Callable,
                *, can_publish: Callable[[], bool] = lambda: True) -> str:
        try:
            outcome = self._publish(identity, payload, validate, can_publish=can_publish)
            if outcome == "capacity":
                self._catalog_event(key=identity_key(identity), failure={"identity": identity, "code": "capacity"})
            return outcome
        except Exception as exc:
            try:
                key = identity_key(identity)
                reason = str(exc) if isinstance(exc, Unavailable) else "storage_error" if isinstance(exc, OSError) else "validation_error"
                if reason == "busy":
                    reason = "store_busy"
                if not re.fullmatch(r"[a-z_]{1,64}", reason):
                    reason = "population_error"
                self._catalog_event(key=key, failure={"identity": identity, "code": reason})
            except Exception:
                pass
            raise

    def _publish(self, identity: dict, payload: dict[str, bytes], validate: Callable,
                 *, can_publish: Callable[[], bool] = lambda: True) -> str:
        key = identity_key(identity)
        if set(payload) != CONTRACTS[identity["contract"]] or any(not 0 < len(v) <= MAX_FILE_BYTES for v in payload.values()):
            raise Unavailable("payload_inventory")
        validate(payload)
        manifest = {"schema": SCHEMA, "key": key, "identity": identity,
                    "files": {name: {"bytes": len(data), "sha256": sha256(data)} for name, data in payload.items()}}
        encoded = canonical(manifest)
        size = sum(map(len, payload.values())) + len(encoded)
        if size > self.max_bytes or len(encoded) > MAX_MANIFEST_BYTES:
            return "capacity"
        with self.locked():
            if not can_publish():
                return "cancelled_or_changed"
            entry = self.root / "entries" / key
            if entry.exists() or entry.is_symlink():
                try:
                    previous, _ = self._read(key, identity, validate)
                except Exception:
                    self._quarantine(entry)
                else:
                    if previous == payload:
                        self._catalog_event(entry=entry)
                        return "duplicate"
                    self._quarantine(entry)
                    self._prune()
                    return "conflicting_outputs"
            self._prune(reserve=size, slots=1)
            pending = self.root / (".pending-" + uuid.uuid4().hex)
            pending.mkdir(mode=0o700)
            try:
                for name, data in {**payload, "manifest.json": encoded}.items():
                    with (pending / name).open("xb") as handle:
                        os.chmod(handle.name, 0o600)
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                self._sync(pending)
                if not can_publish():
                    return "cancelled_or_changed"
                os.replace(pending, entry)
                self._sync(self.root / "entries")
                self._catalog_event(entry=entry, manifest=manifest)
            finally:
                if pending.exists():
                    self._remove(pending)
        return "published"

    @staticmethod
    def _sync(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def inspect(self, *, delete: str | None = None) -> list[dict]:
        if delete is not None and not DIGEST.fullmatch(delete):
            raise Unavailable("delete_key")
        with self.locked():
            if delete:
                self._remove(self.root / "entries" / delete)
                self._catalog_event(key=delete, state="absent")
            self._prune()
            rows = []
            for entry in sorted((self.root / "entries").iterdir()):
                rows.append({"key": entry.name, "bytes": sum(p.stat().st_size for p in entry.iterdir() if p.is_file())})
            return rows


def materialize(payload: dict[str, bytes], destinations: dict[str, Path]) -> None:
    """Copy verified bytes, with rollback if a destination replacement fails."""
    if set(payload) != set(destinations):
        raise Unavailable("destinations")
    if len({str(p.resolve()) for p in destinations.values()}) != len(destinations):
        raise Unavailable("duplicate_destination")
    staged, backups, installed = {}, {}, []
    try:
        for name, path in destinations.items():
            reject_symlink_parents(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            backups[name] = regular_bytes(path) if path.exists() else None
            descriptor, temporary = tempfile.mkstemp(prefix=".accession-copy-", dir=path.parent)
            staged[name] = Path(temporary)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload[name])
                handle.flush()
                os.fsync(handle.fileno())
        for name, path in destinations.items():
            os.replace(staged[name], path)
            installed.append(name)
    except BaseException:
        for name in reversed(installed):
            path = destinations[name]
            if backups[name] is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(backups[name])
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
