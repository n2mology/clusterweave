"""Exact, disposable metadata index for the validated accession store."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from urllib.parse import quote

SCHEMA = 1
MAX_ROWS = 16384
MAX_BATCH = 50
MAX_AGE = 90
ACCESSION = re.compile(r"GC[AF]_[0-9]+\.[1-9][0-9]*\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
CONTRACTS = {
    "accession-snapshot-v2": "retrieval", "accession-detection-v2": "detection",
    "accession-detection-v3": "detection",
    "bacterial-genbank-v1": "preparation", "fungal-existing-cds-v1": "preparation",
}
STATES = {"candidate_available", "expired", "quarantined", "absent"}


class CatalogUnavailable(ValueError):
    pass


def catalog_path(root: Path | None = None, *, data_dir: Path | None = None) -> Path:
    """Only worker metadata is shared with the web service, never payloads."""
    data = data_dir or (Path(os.environ["DATA_DIR"]) if os.environ.get("DATA_DIR") else None)
    if data is not None:
        return data / "worker" / "accession-cache" / "catalog.sqlite"
    if root is None:
        raise CatalogUnavailable("catalog_not_configured")
    return root / "catalog.sqlite"


def _safe(path: Path, *, directory=False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
            or (not stat.S_ISDIR(info.st_mode) if directory else
                not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 64 * 1024 * 1024)):
        raise CatalogUnavailable("catalog_owner_or_type")


def _parents(path: Path):
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise CatalogUnavailable("catalog_path")


def manifest_row(manifest: dict, *, digest: str, populated: float, max_age: int) -> dict:
    identity = manifest["identity"]
    contract = identity["contract"]
    return {
        "key": manifest["key"], "accession": identity["accession"],
        "contract": contract, "stage": CONTRACTS.get(contract, "unsupported"),
        "taxon": identity["route"]["taxon"], "input_sha256": identity["genome_sha256"],
        "source_sha256": identity["source_sha256"], "runtime_sha256": identity["runtime_sha256"],
        "manifest_sha256": digest, "populated_at": populated, "expires_at": populated + max_age,
        "state": "candidate_available",
    }


def checked_row(row):
    fields = {"key", "accession", "contract", "stage", "taxon", "input_sha256", "source_sha256",
              "runtime_sha256", "manifest_sha256", "populated_at", "expires_at", "state"}
    if (set(row) != fields or len(str(row["accession"])) > 64 or not ACCESSION.fullmatch(str(row["accession"]))
            or row["contract"] not in CONTRACTS or CONTRACTS[row["contract"]] != row["stage"]
            or row["taxon"] not in {"bacteria", "fungi"} or row["state"] not in STATES
            or any(not DIGEST.fullmatch(str(row[n])) for n in
                   ("key", "input_sha256", "source_sha256", "runtime_sha256", "manifest_sha256"))
            or any(type(row[n]) not in (int, float) or not 0 < row[n] < 1e12
                   for n in ("populated_at", "expires_at"))):
        raise CatalogUnavailable("catalog_row")
    return row


class Catalog:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self, *, write=False):
        _parents(self.path)
        if write:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _safe(self.path.parent, directory=True)
        if write and not self.path.exists():
            try:
                os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
            except FileExistsError:
                pass
        _safe(self.path)
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = Path(str(self.path) + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                _safe(sidecar)
        uri = "file:" + quote(str(self.path), safe="/") + ("?mode=rw" if write else "?mode=ro")
        con = sqlite3.connect(uri, uri=True, timeout=0.2)
        con.row_factory = sqlite3.Row
        deadline = time.monotonic() + 2
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        try:
            con.execute("PRAGMA trusted_schema=OFF")
            if write:
                con.execute("PRAGMA max_page_count=8192")
                version = con.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, SCHEMA):
                    raise CatalogUnavailable("catalog_schema")
                con.executescript("""
                    CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS entries (
                        key TEXT PRIMARY KEY, accession TEXT NOT NULL, stage TEXT NOT NULL,
                        state TEXT NOT NULL, expires REAL NOT NULL, updated REAL NOT NULL, row_json TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS by_accession ON entries(accession, stage);
                    CREATE TABLE IF NOT EXISTS legacy (accession TEXT NOT NULL, stage TEXT NOT NULL,
                        PRIMARY KEY(accession,stage));
                    CREATE TABLE IF NOT EXISTS active (key TEXT PRIMARY KEY, accession TEXT NOT NULL,
                        stage TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS failures (key TEXT PRIMARY KEY, accession TEXT NOT NULL,
                        stage TEXT NOT NULL, code TEXT NOT NULL, updated REAL NOT NULL);
                    PRAGMA user_version=1;
                """)
            elif con.execute("PRAGMA user_version").fetchone()[0] != SCHEMA:
                raise CatalogUnavailable("catalog_schema")
            yield con
            if write:
                con.commit()
        except BaseException:
            if write:
                con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _bind(con, store_id):
        if not re.fullmatch(r"[0-9a-f]{32}", store_id):
            raise CatalogUnavailable("catalog_store")
        old = con.execute("SELECT value FROM metadata WHERE name='store_id'").fetchone()
        if old is None or old[0] != store_id:
            for table in ("entries", "active", "legacy", "failures", "metadata"):
                con.execute("DELETE FROM " + table)
            con.execute("INSERT INTO metadata VALUES ('store_id',?)", (store_id,))

    @staticmethod
    def _put(con, row, now):
        checked_row(row)
        con.execute("INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?,?,?)", (
            row["key"], row["accession"], row["stage"], row["state"], row["expires_at"], now,
            json.dumps(row, sort_keys=True, separators=(",", ":"))))
        if row["state"] == "candidate_available":
            con.execute("DELETE FROM failures WHERE key=?", (row["key"],))

    @staticmethod
    def _bound(con, now):
        con.execute("DELETE FROM entries WHERE updated < ?", (now - 30 * 86400,))
        con.execute("DELETE FROM entries WHERE key IN (SELECT key FROM entries "
                    "ORDER BY updated DESC, key DESC LIMIT -1 OFFSET ?)", (MAX_ROWS,))
        con.execute("DELETE FROM failures WHERE updated < ?", (now - 30 * 86400,))
        con.execute("DELETE FROM failures WHERE key IN (SELECT key FROM failures "
                    "ORDER BY updated DESC,key DESC LIMIT -1 OFFSET ?)", (MAX_ROWS,))

    def failure(self, store_id, key, accession, stage, code):
        if (not DIGEST.fullmatch(key) or not ACCESSION.fullmatch(accession)
                or stage not in set(CONTRACTS.values()) or not re.fullmatch(r"[a-z_]{1,64}", code)):
            raise CatalogUnavailable("catalog_failure_record")
        with self.connection(write=True) as con:
            self._bind(con, store_id)
            con.execute("INSERT OR REPLACE INTO failures VALUES (?,?,?,?,?)", (key, accession, stage, code, time.time()))
            self._bound(con, time.time())

    def record(self, store_id, *, row=None, key=None, state=None):
        now = time.time()
        with self.connection(write=True) as con:
            self._bind(con, store_id)
            if row is not None:
                self._put(con, row, now)
            elif DIGEST.fullmatch(str(key)) and state in STATES:
                previous = con.execute("SELECT row_json FROM entries WHERE key=?", (key,)).fetchone()
                if previous:
                    value = json.loads(previous[0]); value["state"] = state
                    self._put(con, value, now)
            self._bound(con, now)

    def reconcile(self, store_id, rows, *, legacy=(), active=(), failures=(), complete=True):
        now = time.time()
        rows = list(rows)
        if len(rows) > MAX_ROWS:
            raise CatalogUnavailable("catalog_capacity")
        with self.connection(write=True) as con:
            self._bind(con, store_id)
            present = {r["key"] for r in rows}
            for old in con.execute("SELECT key,row_json FROM entries WHERE state='candidate_available'").fetchall():
                if old[0] not in present:
                    value = json.loads(old[1]); value["state"] = "absent"
                    self._put(con, value, now)
            for row in rows:
                self._put(con, row, now)
            con.execute("DELETE FROM legacy"); con.execute("DELETE FROM active")
            for accession, stage in set(legacy):
                if ACCESSION.fullmatch(accession) and stage == "detection":
                    con.execute("INSERT OR IGNORE INTO legacy VALUES (?,?)", (accession, stage))
            for key, accession, stage in set(active):
                if DIGEST.fullmatch(key) and ACCESSION.fullmatch(accession) and stage in set(CONTRACTS.values()):
                    con.execute("INSERT OR IGNORE INTO active VALUES (?,?,?)", (key, accession, stage))
            for key, accession, stage, code in set(failures):
                if (DIGEST.fullmatch(key) and ACCESSION.fullmatch(accession) and stage in set(CONTRACTS.values())
                        and re.fullmatch(r"[a-z_]{1,64}", code)
                        and not con.execute("SELECT 1 FROM entries WHERE key=? AND state='candidate_available'", (key,)).fetchone()):
                    con.execute("INSERT OR IGNORE INTO failures VALUES (?,?,?,?,?)", (key, accession, stage, code, now))
            con.execute("INSERT OR REPLACE INTO metadata VALUES ('refreshed_at',?)", (str(now),))
            con.execute("INSERT OR REPLACE INTO metadata VALUES ('inventory_complete',?)", (str(int(complete)),))
            self._bound(con, now)

    def availability(self, accessions, *, stage="detection", keys=None):
        accessions = list(accessions)
        if len(accessions) > MAX_BATCH or any(not isinstance(a, str) for a in accessions):
            raise ValueError("invalid_catalog_query")
        accessions = list(dict.fromkeys(accessions)); keys = keys or {}
        if (not 1 <= len(accessions) <= MAX_BATCH or stage not in set(CONTRACTS.values())
                or any(not isinstance(a, str) or not ACCESSION.fullmatch(a) for a in accessions)
                or set(keys) - set(accessions) or any(not DIGEST.fullmatch(str(k)) for k in keys.values())):
            raise ValueError("invalid_catalog_query")
        now = time.time()
        with self.connection() as con:
            metadata = dict(con.execute("SELECT name,value FROM metadata"))
            refreshed = float(metadata.get("refreshed_at", "0"))
            if not 0 <= now - refreshed <= MAX_AGE:
                raise CatalogUnavailable("catalog_stale")
            results = []
            for accession in accessions:
                requested = keys.get(accession)
                exact = con.execute("SELECT row_json FROM entries WHERE accession=? AND stage=? AND key=?",
                                    (accession, stage, requested)).fetchone() if requested else None
                records = con.execute("SELECT row_json FROM entries WHERE accession=? AND stage=? "
                                      "ORDER BY updated DESC,key LIMIT 17", (accession, stage)).fetchall()
                rows = [checked_row(json.loads(r[0])) for r in records]
                if exact and not any(r["key"] == requested for r in rows):
                    rows.append(checked_row(json.loads(exact[0])))
                for row in rows:
                    if row["expires_at"] <= now and row["state"] == "candidate_available":
                        row["state"] = "expired"
                matching = [r for r in rows if not requested or r["key"] == requested]
                available = [r for r in matching if r["state"] == "candidate_available"]
                active = con.execute("SELECT 1 FROM active WHERE accession=? AND stage=?" +
                                     (" AND key=?" if requested else "") + " LIMIT 1",
                                     (accession, stage, requested) if requested else (accession, stage)).fetchone()
                historical = con.execute("SELECT 1 FROM legacy WHERE accession=? AND stage=?", (accession, stage)).fetchone()
                failure = con.execute("SELECT code FROM failures WHERE accession=? AND stage=?" +
                                      (" AND key=?" if requested else "") + " ORDER BY updated DESC LIMIT 1",
                                      (accession, stage, requested) if requested else (accession, stage)).fetchone()
                if available:
                    status, reason = "candidate_available", "payload_verification_required"
                elif active:
                    status, reason = "in_progress", "pending_validation_and_population"
                elif failure and re.fullmatch(r"[a-z_]{1,64}", failure[0]):
                    status, reason = "population_failed", failure[0]
                elif requested and any(r["state"] == "candidate_available" for r in rows):
                    status, reason = "incompatible", "different_scientific_identity"
                elif matching and any(r["state"] == "quarantined" for r in matching):
                    status, reason = "quarantined", "authoritative_store_rejected_entry"
                elif matching and any(r["state"] == "expired" for r in matching):
                    status, reason = "expired", "retention_elapsed"
                elif historical:
                    status, reason = "legacy_unverified", "complete_original_identity_missing"
                elif metadata.get("inventory_complete") != "1" or len(rows) > 16:
                    status, reason = "unknown", "catalog_inventory_incomplete"
                else:
                    status, reason = "absent", "not_in_catalog"
                results.append({"accession": accession, "stage": stage, "status": status, "reason": reason,
                                "requested_key": requested, "candidates": available[:16],
                                "variants_truncated": len(rows) > 16})
        return {"schema": SCHEMA, "advisory": True, "refreshed_at": refreshed, "results": results}


def _store_events(body):
    """Run outside the scientific producer's Python/native runtime."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
    from accession_cache import Store, identity_key
    request = json.loads(body)
    root = Path(request["root"])
    store = Store(root, max_age_seconds=request["max_age"])
    catalog, store_id = store._catalog()
    for event in request["events"]:
        key = event["key"]
        if not isinstance(key, str) or not DIGEST.fullmatch(key):
            continue
        entry = root / "entries" / key
        if "failure" in event:
            identity = event["failure"]["identity"]
            if identity_key(identity) == key and identity["contract"] in CONTRACTS:
                catalog.failure(store_id, key, identity["accession"], CONTRACTS[identity["contract"]],
                                event["failure"]["code"])
        elif entry.exists() and not entry.is_symlink():
            row = store._catalog_row(entry)
            if row["contract"] in CONTRACTS:
                catalog.record(store_id, row=row)
        else:
            catalog.record(store_id, key=key, state=event["state"])


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3 or sys.argv[1] != "--store-events" or len(sys.argv[2]) > 100000:
        raise SystemExit(2)
    try:
        _store_events(sys.argv[2])
    except Exception:
        raise SystemExit(2)
