import csv
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "normalize_metadata.py"


def load_module():
    spec = importlib.util.spec_from_file_location("normalize_metadata", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class MetadataParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_accessions_parser_accepts_genome_size_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "accessions.tsv"
            path.write_text(
                "GCA_000011425.1\tAspergillus_nidulans_FGSC_A4\t227321\t29.83\n",
                encoding="utf-8",
            )
            rows = self.module._parse_accessions(path)
        self.assertEqual(rows[0]["accession"], "GCA_000011425.1")
        self.assertEqual(rows[0]["taxonomy_id"], "227321")
        self.assertEqual(rows[0]["genome_size_mb"], "29.83")

    def test_genome_dir_fallback_writes_blank_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            genome_dir = root / "genomes"
            genome_dir.mkdir()
            (genome_dir / "Septoria_glycines_17Sg100.fna").write_text(">seq\nATGC\n", encoding="utf-8")
            (genome_dir / "Sphaerulina_musiva_MN-14.gbff").write_text("LOCUS test\n", encoding="utf-8")
            (genome_dir / "notes.txt").write_text("ignore me\n", encoding="utf-8")
            out = root / "ecofun_metadata_normalized.tsv"
            template = root / "ecofun_metadata_template.tsv"
            missing_accessions = root / "missing_accessions.tsv"

            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--accessions",
                    str(missing_accessions),
                    "--genome-dir",
                    str(genome_dir),
                    "--out",
                    str(out),
                    "--template-out",
                    str(template),
                    "--allow-missing-legacy",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            with out.open("r", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            template_lines = template.read_text(encoding="utf-8").splitlines()

        self.assertIn("Metadata input source: genome files in", result.stdout)
        self.assertEqual(
            [row["genome_id_current"] for row in rows],
            ["Septoria_glycines_17Sg100", "Sphaerulina_musiva_MN-14"],
        )
        self.assertEqual([row["accession"] for row in rows], ["", ""])
        self.assertEqual([row["taxonomy_id"] for row in rows], ["", ""])
        self.assertEqual([row["ecofun_primary"] for row in rows], ["", ""])
        self.assertEqual(len(template_lines), 1)


if __name__ == "__main__":
    unittest.main()
