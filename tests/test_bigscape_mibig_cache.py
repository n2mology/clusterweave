from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "run_bigscape.sh"


class BigscapeMibigCacheTests(unittest.TestCase):
    def cache_probe(self, cache: Path, version: str = "4.0") -> bool:
        command = f"""
set -euo pipefail
MIBIG_VERSION_DEFAULT=4.0
source <(awk '/^mibig_cache_has_gbks\\(\\)/{{flag=1}} /^mibig_archive_candidates\\(\\)/{{flag=0}} flag{{print}}' {shlex.quote(str(SCRIPT_PATH))})
mibig_cache_has_gbks {shlex.quote(str(cache))} {shlex.quote(version)}
"""
        result = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(REPO_ROOT),
            env=dict(os.environ),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.returncode == 0

    def test_raw_mibig_gbks_do_not_masquerade_as_bigscape_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            raw = cache / "mibig_gbk_4.0"
            raw.mkdir()
            (raw / "BGC0000001.gbk").write_text("LOCUS test\n", encoding="utf-8")

            self.assertFalse(self.cache_probe(cache))

    def test_antismash_processed_version_directory_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            ready = cache / "mibig_antismash_4.0_gbk"
            ready.mkdir()
            (ready / "BGC0000001.gbk").write_text("LOCUS test\n", encoding="utf-8")

            self.assertTrue(self.cache_probe(cache))

    def test_release_suffix_directory_is_normalized_to_bigscape_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            released = cache / "mibig_antismash_4.0_gbk_as8b1"
            released.mkdir()
            (released / "BGC0000001.gbk").write_text("LOCUS test\n", encoding="utf-8")
            command = f"""
set -euo pipefail
MIBIG_VERSION_DEFAULT=4.0
source <(awk '/^mibig_cache_has_gbks\\(\\)/{{flag=1}} /^mibig_archive_candidates\\(\\)/{{flag=0}} flag{{print}}' {shlex.quote(str(SCRIPT_PATH))})
normalize_mibig_version_dir {shlex.quote(str(cache))} 4.0
"""
            subprocess.run(
                ["bash", "-lc", command],
                cwd=str(REPO_ROOT),
                env=dict(os.environ),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertFalse(released.exists())
            self.assertTrue(self.cache_probe(cache))

    def test_docker_runner_mounts_shared_volume_mibig_subpath(self) -> None:
        command = f"""
set -euo pipefail
source <(awk '/^docker_run_args\\(\\)/{{flag=1}} /^cexec\\(\\)/{{flag=0}} flag{{print}}' {shlex.quote(str(SCRIPT_PATH))})
BIGSCAPE_DOCKER_CPUS=8
BIGSCAPE_DOCKER_MEMORY=
BIGSCAPE_DOCKER_PIDS_LIMIT=
CLUSTERWEAVE_JOB_ID=
BIGSCAPE_DOCKER_DATA_VOLUME=clusterweave_job_data
BIGSCAPE_DOCKER_PFAM_VOLUME=clusterweave_pfam_db
PROJECT_DIR=/data/project
RESULTS_ROOT=/data/results
BIGSCAPE_SOFTDIR=/data/software/big_scape
LOCAL_BIN=/data/software/bin
BIGSCAPE_OUT=/data/results/big_scape
STAGE_DIR=/data/work/stage
PFAM_DIR=/databases/pfam
MIBIG_VERSION=4.0
MIBIG_CACHE=/data/software/big_scape/resources/mibig_cache
docker_run_args | tr '\\0' '\\n'
"""
        result = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(REPO_ROOT),
            env=dict(os.environ),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertIn("--mount", result.stdout.splitlines())
        self.assertIn(
            "type=volume,src=clusterweave_job_data,"
            "dst=/home/mambauser/BiG-SCAPE/big_scape/MIBiG,"
            "volume-subpath=software/big_scape/resources/mibig_cache",
            result.stdout.splitlines(),
        )


if __name__ == "__main__":
    unittest.main()
