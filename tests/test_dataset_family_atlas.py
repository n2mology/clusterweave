import importlib.util
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "export_dataset_family_atlas.py"
SHARED_MODULE_PATH = REPO_ROOT / "bin" / "export_shared_family_shortlist.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DatasetFamilyAtlasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module("export_dataset_family_atlas", MODULE_PATH)
        cls.shared_module = load_module(
            "export_shared_family_shortlist", SHARED_MODULE_PATH
        )

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

    def test_canonical_record_key_uses_staged_id_not_organism_display(self) -> None:
        self.assertEqual(
            self.module.canonical_record_key(
                "Aspergillus_niger__NT_166521.1.region002.gbk_region_2",
                "Aspergillus_niger__NT_166521.1.region002",
            ),
            ("Aspergillus_niger", "NT_166521.1.region002"),
        )
        self.assertEqual(
            self.module.canonical_record_key("BGC0001089.gbk_region_1", "BGC0001089"),
            ("", ""),
        )

    def test_current_record_key_preserves_mixed_scope_route_prefixes(self) -> None:
        self.assertEqual(
            self.module.canonical_record_key(
                "bacteria_Streptomyces_coelicolor_A3_2__bacteria_Streptomyces_coelicolor_A3_2_NC_003888.3.region016.gbk_region_16",
                "bacteria_Streptomyces_coelicolor_A3_2__bacteria_Streptomyces_coelicolor_A3_2_NC_003888.3.region016",
            ),
            (
                "bacteria_Streptomyces_coelicolor_A3_2",
                "bacteria_Streptomyces_coelicolor_A3_2_NC_003888.3.region016",
            ),
        )
        self.assertEqual(
            self.module.compatible_record_keys(
                "bacteria_Streptomyces_coelicolor_A3_2__bacteria_Streptomyces_coelicolor_A3_2_NC_003888.3.region016.gbk_region_16",
                "bacteria_Streptomyces_coelicolor_A3_2__bacteria_Streptomyces_coelicolor_A3_2_NC_003888.3.region016",
            ),
            (
                (
                    "bacteria_Streptomyces_coelicolor_A3_2",
                    "bacteria_Streptomyces_coelicolor_A3_2_NC_003888.3.region016",
                ),
                (
                    "Streptomyces_coelicolor_A3_2",
                    "Streptomyces_coelicolor_A3_2_NC_003888.3.region016",
                ),
            ),
        )

    def test_latest_bigscape_run_dir_ignores_historical_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            older = output_root / "2026-07-21_02-48-23_c0.3"
            latest = output_root / "2026-07-21_14-09-07_c0.3"
            older.mkdir()
            latest.mkdir()
            (output_root / "notes.txt").write_text("not a run", encoding="utf-8")
            self.assertEqual(
                self.module.latest_bigscape_run_dir(output_root),
                latest,
            )

    def test_public_path_label_omits_private_job_workspace(self) -> None:
        private_path = Path(
            "/data/jobs/private-run/data/results/demo/summary/"
            "bigscape_family_atlas.tsv"
        )
        expected = "data/results/demo/summary/bigscape_family_atlas.tsv"
        for module in (self.module, self.shared_module):
            with self.subTest(module=module.__name__):
                self.assertEqual(expected, module.public_path_label(private_path))
                self.assertNotIn("jobs", module.public_path_label(private_path))


if __name__ == "__main__":
    unittest.main()
