import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class BigscapeTaxonStagingTests(unittest.TestCase):
    def test_root_region_staging_writes_safe_taxon_crosswalk(self) -> None:
        text = (REPO_ROOT / "run_bigscape.sh").read_text(encoding="utf-8")

        self.assertIn("BIGSCAPE_REGION_CROSSWALK", text)
        self.assertIn(
            "staged_gbk\\tgenome_id\\ttaxon_group\\tprediction_method\\tsource_region_key",
            text,
        )
        self.assertIn('"${genome}/${base}"', text)
        self.assertNotIn("shard_dir", text[text.index("manifest_route_fields()") :])

    def test_zero_region_project_writes_valid_empty_bigscape_universe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            antismash = root / "results" / "antismash"
            antismash.mkdir(parents=True)
            output = root / "results" / "big_scape"
            crosswalk = root / "results" / "summary_tables" / "bigscape_region_crosswalk.tsv"
            env = os.environ.copy()
            env.update(
                {
                    "PROJECT_DIR": str(REPO_ROOT),
                    "PROJECT_NAME": "demo",
                    "DATA_ROOT": str(root / "data"),
                    "RESULTS_ROOT": str(root / "results"),
                    "ANTISMASH_ROOT": str(antismash),
                    "BIGSCAPE_OUT": str(output),
                    "STAGE_DIR": str(root / "work" / "stage"),
                    "BIGSCAPE_REGION_CROSSWALK": str(crosswalk),
                    "LOGDIR": str(root / "results" / "logs"),
                    "ENGINE": "docker",
                }
            )
            completed = subprocess.run(
                ["bash", str(REPO_ROOT / "run_bigscape.sh")],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(
                "BIGSCAPE_RESULT status=insufficient_data regions=0 families=0",
                completed.stdout,
            )
            self.assertTrue((output / "output_files").is_dir())
            self.assertEqual(
                crosswalk.read_text(encoding="utf-8"),
                "staged_gbk\tgenome_id\ttaxon_group\tprediction_method\tsource_region_key\n",
            )


if __name__ == "__main__":
    unittest.main()
