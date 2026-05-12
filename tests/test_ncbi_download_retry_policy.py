from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class NcbiDownloadRetryPolicyTests(unittest.TestCase):
    def test_no_matching_assembly_error_is_not_retried_across_include_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            call_log = root / "datasets-calls.txt"
            datasets = fake_bin / "datasets"
            datasets.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    printf '%s\\n' "$*" >> "${CALL_LOG}"
                    echo "Error: There are no genome assemblies that match your query." >&2
                    echo "Please try again using different search criteria." >&2
                    exit 1
                    """
                ),
                encoding="utf-8",
            )
            datasets.chmod(0o755)

            accessions = root / "accessions.txt"
            accessions.write_text("GCA_012011425.1\n", encoding="utf-8")

            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
                "CALL_LOG": str(call_log),
                "PROJECT_ROOT": str(REPO_ROOT),
                "ACCESSIONS_FILE": str(accessions),
                "GENOME_ROOT": str(root / "genomes"),
                "RETRIES": "2",
                "SLEEP_BETWEEN": "0",
            }
            result = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "ncbi" / "download_ncbi_genomes.sh")],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            calls = call_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(calls), 1, result.stdout + result.stderr)
            self.assertIn("nonretryable=accession_not_found", result.stdout)
            self.assertEqual(result.stderr.count("There are no genome assemblies that match your query"), 1)


if __name__ == "__main__":
    unittest.main()
