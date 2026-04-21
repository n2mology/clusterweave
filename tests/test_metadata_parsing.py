import importlib.util
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
