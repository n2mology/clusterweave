from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "run_annotation_and_detection.sh"
FUNBGCEX_IMAGE = "clusterweave-funbgcex:latest"


def docker_image_available(image: str) -> bool:
    return subprocess.run(
        ["docker", "image", "inspect", image],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    ).returncode == 0


@unittest.skipUnless(docker_image_available(FUNBGCEX_IMAGE), f"{FUNBGCEX_IMAGE} is required for Biopython-backed GBK sanitizer tests")
class AntiSmashInputSanitizerTests(unittest.TestCase):
    def run_bash(self, command: str, tmp: Path) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["SANITIZER_TEST_TMP"] = str(tmp)
        return subprocess.run(
            ["bash", "-lc", command],
            cwd=str(REPO_ROOT),
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def write_duplicate_cds_fixture(self, path: Path) -> None:
        command = f"""
set -euo pipefail
mkdir -p {shlex.quote(str(path.parent))}
docker run --rm -i -v {shlex.quote(str(path.parent))}:{shlex.quote(str(path.parent))} {FUNBGCEX_IMAGE} python3 - {shlex.quote(str(path))} <<'PYFIXTURE'
import sys
from pathlib import Path
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import CompoundLocation, FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

out = Path(sys.argv[1])
record = SeqRecord(Seq("ATG" * 3200), id="CP000001.1", name="CP000001", description="duplicate CDS fixture")
record.annotations["molecule_type"] = "DNA"
record.features.append(SeqFeature(FeatureLocation(0, len(record.seq), strand=1), type="source", qualifiers={{"organism": ["Cryptococcus neoformans"]}}))
shared_location = CompoundLocation([
    FeatureLocation(7684, 7769, strand=-1),
    FeatureLocation(6208, 7626, strand=-1),
])
record.features.append(SeqFeature(shared_location, type="CDS", qualifiers={{
    "locus_tag": ["CKF44_07303"],
    "protein_id": ["KEEP001"],
    "product": ["first translated duplicate"],
    "translation": ["M" + "A" * 12],
}}))
record.features.append(SeqFeature(shared_location, type="CDS", qualifiers={{
    "locus_tag": ["CKF44_07303"],
    "protein_id": ["DROP001"],
    "product": ["second translated duplicate"],
    "translation": ["M" + "G" * 12],
}}))
record.features.append(SeqFeature(FeatureLocation(100, 190, strand=1), type="CDS", qualifiers={{
    "locus_tag": ["CKF44_00001"],
    "protein_id": ["UNIQUE001"],
    "product": ["unique translated CDS"],
    "translation": ["M" + "T" * 8],
}}))
SeqIO.write([record], out, "genbank")
PYFIXTURE
"""
        self.run_bash(command, path.parent)

    def test_duplicate_same_location_cds_is_removed_only_from_antismash_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "source.gbk"
            antismash_copy = tmp / "antismash.gbk"
            self.write_duplicate_cds_fixture(source)
            before = source.read_text(encoding="utf-8")

            command = rf"""
set -euo pipefail
source <(awk '/^filter_gbk_drop_gene_less_records\(\)/{{flag=1}} /^###############################################################################$/ && flag{{seen += 1; if (seen == 2) flag=0}} flag{{print}}' {shlex.quote(str(SCRIPT_PATH))})
funbgcex_python_exec() {{
  docker run -i --rm -v "$SANITIZER_TEST_TMP:$SANITIZER_TEST_TMP" {FUNBGCEX_IMAGE} python3 "$@"
}}
sanitize_antismash_duplicate_cds_locations {shlex.quote(str(source))} {shlex.quote(str(antismash_copy))} Cryptococcus_neoformans_KN99
"""
            result = self.run_bash(command, tmp)

            self.assertEqual(before, source.read_text(encoding="utf-8"))
            sanitized = antismash_copy.read_text(encoding="utf-8")
            self.assertEqual(sanitized.count("     CDS             "), 2)
            self.assertIn('/protein_id="KEEP001"', sanitized)
            self.assertIn('/protein_id="UNIQUE001"', sanitized)
            self.assertNotIn('DROP001', sanitized)
            self.assertRegex(result.stdout, r'"dropped_duplicate_cds"\s*:\s*1')
            self.assertIn("CKF44_07303", result.stdout)
            self.assertIn("DROP001", result.stdout)


if __name__ == "__main__":
    unittest.main()
