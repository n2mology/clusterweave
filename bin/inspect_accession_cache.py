#!/usr/bin/env python3
"""Inspect exact accession availability without reading scientific payloads."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
for module_root in (Path("/app"), ROOT / "web"):
    if module_root.is_dir():
        sys.path.insert(0, str(module_root))
from accession_catalog import Catalog, CatalogUnavailable, catalog_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("query", "refresh"))
    parser.add_argument("--accession", action="append", default=[])
    parser.add_argument("--stage", choices=("retrieval", "preparation", "detection"), default="detection")
    parser.add_argument("--key", help="Exact scientific identity key, for a single accession")
    args = parser.parse_args()
    try:
        raw = os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_ROOT", "")
        if not raw:
            raise CatalogUnavailable("cache_not_configured")
        root = Path(raw)
        if args.action == "refresh":
            from accession_cache import Store
            if os.environ.get("DATA_DIR"):
                from cache_status import refresh_catalog, catalog_jobs
                from job_store import job_dir
                refresh_catalog(catalog_jobs(Path(os.environ["DATA_DIR"])), job_dir)
            else:
                Store(root, max_age_seconds=int(os.environ.get("CLUSTERWEAVE_ACCESSION_CACHE_MAX_AGE_SECONDS", 30 * 86400))).reconcile_catalog()
            print(json.dumps({"catalog": "refreshed", "scientific_payloads": "unchanged"}))
            return 0
        if args.key and len(args.accession) != 1:
            parser.error("--key requires exactly one --accession")
        print(json.dumps(Catalog(catalog_path(root)).availability(
            args.accession, stage=args.stage, keys={args.accession[0]: args.key} if args.key else None), sort_keys=True))
        return 0
    except (CatalogUnavailable, OSError, ValueError, sqlite3.Error):
        print("Cache catalog unavailable or query invalid; authoritative cache lookup remains available", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
