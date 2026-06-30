#!/usr/bin/env python3
"""Install a legacy funannotate BUSCO DB during ClusterWeave image builds.

funannotate 1.8.17 stores the old ODB9 BUSCO URL map, but its setup downloader
uses urllib in a way that does not follow OSF's current HTTP 308 redirect. This
helper keeps the one-time image bake offline-first and redirect-aware without
adding job-time downloads.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from funannotate import resources


REDIRECT_CODES = {301, 302, 303, 307, 308}


class Redirect308Handler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def candidate_cache_files(cache_dir: Path, db: str) -> list[Path]:
    return [cache_dir / f"{db}.tar.gz", cache_dir / f"{db}_odb9.tar.gz"]


def safe_extract(tar: tarfile.TarFile, destination: Path) -> None:
    dest = destination.resolve()
    for member in tar.getmembers():
        target = (destination / member.name).resolve()
        if target != dest and dest not in target.parents:
            raise ValueError(f"refusing unsafe tar member path: {member.name}")
    tar.extractall(destination)


def tar_root(tar_path: Path) -> str:
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            root = Path(member.name).parts[0] if member.name else ""
            if root:
                return root
    raise ValueError(f"could not determine tar root for {tar_path}")


def download_tarball(db: str, destination: Path) -> str:
    if db not in resources.busco_links:
        valid = ", ".join(sorted(resources.busco_links))
        raise ValueError(f"unknown funannotate BUSCO DB {db!r}; valid values include: {valid}")
    url, expected_root = resources.busco_links[db]
    opener = urllib.request.build_opener(Redirect308Handler)
    current_url = url
    for _ in range(10):
        request = urllib.request.Request(current_url, headers={"User-Agent": "ClusterWeave funannotate DB bake"})
        try:
            with opener.open(request, timeout=120) as response, destination.open("wb") as out:
                shutil.copyfileobj(response, out)
            return expected_root
        except urllib.error.HTTPError as exc:
            if exc.code not in REDIRECT_CODES:
                raise
            location = exc.headers.get("Location")
            if not location:
                raise
            current_url = urllib.parse.urljoin(current_url, location)
    raise RuntimeError(f"too many redirects while downloading BUSCO DB {db!r} from {url}")


def install_tarball(tar_path: Path, expected_root: str, db: str, database: Path) -> None:
    root = tar_root(tar_path)
    if expected_root and root != expected_root:
        print(f"WARN: expected tar root {expected_root!r}, found {root!r}", file=sys.stderr)
    db_dir = database / db
    root_dir = database / root
    shutil.rmtree(db_dir, ignore_errors=True)
    if root_dir != db_dir:
        shutil.rmtree(root_dir, ignore_errors=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        safe_extract(tar, database)
    if root_dir != db_dir:
        if not root_dir.exists():
            raise FileNotFoundError(f"expected extracted BUSCO root missing: {root_dir}")
        root_dir.rename(db_dir)
    hmms = db_dir / "hmms"
    if not hmms.is_dir() or not any(path.is_file() for path in hmms.rglob("*")):
        raise FileNotFoundError(f"BUSCO DB {db!r} did not install a non-empty hmms/ directory")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--cache-dir", required=True, type=Path)
    args = parser.parse_args()

    args.database.mkdir(parents=True, exist_ok=True)
    for cached in candidate_cache_files(args.cache_dir, args.db):
        if cached.is_file() and cached.stat().st_size > 0:
            expected_root = resources.busco_links.get(args.db, (None, f"{args.db}_odb9"))[1]
            install_tarball(cached, expected_root, args.db, args.database)
            print(f"Installed {args.db} BUSCO DB from local cache: {cached}")
            return 0

    with tempfile.TemporaryDirectory(prefix=f"clusterweave-{args.db}-") as tmp:
        tar_path = Path(tmp) / f"{args.db}.tar.gz"
        expected_root = download_tarball(args.db, tar_path)
        install_tarball(tar_path, expected_root, args.db, args.database)
    print(f"Installed {args.db} BUSCO DB from funannotate resources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
