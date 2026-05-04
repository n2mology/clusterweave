import importlib.util
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "export_dataset_family_atlas.py"


def load_module():
    spec = importlib.util.spec_from_file_location("export_dataset_family_atlas", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DatasetFamilyAtlasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_atlas_now_skips_representatives_already_covered_by_prior_cc(self) -> None:
        rows = [
            {
                "bigscape_cc": "100",
                "shared_cc_record_count": "10",
                "genome": "genome_a",
                "antismash_region": "region001",
            },
            {
                "bigscape_cc": "200",
                "shared_cc_record_count": "8",
                "genome": "genome_a",
                "antismash_region": "region001",
            },
            {
                "bigscape_cc": "300",
                "shared_cc_record_count": "7",
                "genome": "genome_b",
                "antismash_region": "region002",
            },
            {
                "bigscape_cc": "400",
                "shared_cc_record_count": "6",
                "genome": "genome_c",
                "antismash_region": "region003",
            },
        ]
        candidate_regions_by_cc = {
            "100": {("genome_a", "region001"), ("genome_b", "region002")},
            "200": {("genome_a", "region001")},
            "300": {("genome_b", "region002")},
            "400": {("genome_c", "region003")},
        }

        self.module.assign_atlas_review_buckets(
            rows,
            candidate_regions_by_cc,
            stage_limit=2,
            min_records=2,
        )

        self.assertEqual([row["atlas_rank"] for row in rows], [1, 2, 3, 4])
        self.assertEqual(
            [row["manual_review_bucket"] for row in rows],
            ["atlas_now", "atlas_context", "atlas_context", "atlas_now"],
        )


if __name__ == "__main__":
    unittest.main()
