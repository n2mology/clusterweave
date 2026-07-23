import csv
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]], delimiter: str = "\t") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter=delimiter, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


class BacterialMultipanelRenderingTests(unittest.TestCase):
    def test_figure_wrapper_uses_shared_taxon_specific_bigscape_renderer(self) -> None:
        text = (REPO_ROOT / "run_figures.sh").read_text(encoding="utf-8")
        self.assertIn('RUN_BGC_OVERLAP_FIGURE}" == "1" && "${FUNGI_COUNT}" -gt 0', text)
        self.assertIn("render_taxon_bigscape_multipanel", text)
        self.assertIn("--taxon-group", text)
        self.assertIn("--region-crosswalk", text)
        self.assertIn("fungi_big_scape_multipanel", text)
        self.assertIn("bacteria_big_scape_multipanel", text)
        self.assertNotIn("RENDER_BACTERIAL_MULTIPANEL_PY", text)
        self.assertNotIn("RUN_BACTERIAL_MULTIPANEL_FIGURE", text)
        self.assertNotIn("render_bacterial_multipanel.py", text)
        self.assertIn("FUNGAL_SUMMARY_TABLE", text)
        # Historical output names remain only so forced refreshes can clean them.
        self.assertIn('"${output_dir}/big_scape_multipanel.svg"', text)
        self.assertIn('"${output_dir}/bacterial_multipanel.svg"', text)

    def test_mixed_fungal_subset_filter_preserves_quoted_csv_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            summary = results / "summary" / "all_tools_shared_unshared_summary.csv"
            manifest = results / "summary_tables" / "genome_taxon_manifest.tsv"
            summary.parent.mkdir(parents=True)
            manifest.parent.mkdir(parents=True)
            write_rows(
                manifest,
                ["genome_id", "taxon_group"],
                [
                    {"genome_id": "fungus_a", "taxon_group": "fungi"},
                    {"genome_id": "bacterium_b", "taxon_group": "bacteria"},
                ],
            )
            write_rows(
                summary,
                ["genome", "taxon_group", "product_label"],
                [
                    {"genome": "fungus_a", "taxon_group": "fungi", "product_label": "NRPS, hybrid"},
                    {"genome": "bacterium_b", "taxon_group": "bacteria", "product_label": "RiPP, class I"},
                ],
                delimiter=",",
            )
            env = os.environ.copy()
            env.update(
                {
                    "PROJECT_DIR": str(REPO_ROOT),
                    "PROJECT_NAME": "demo",
                    "RESULTS_ROOT": str(results),
                    "WORK_ROOT": str(root / "work"),
                    "SUMMARY_TABLE": str(summary),
                    "GENOME_TAXON_MANIFEST": str(manifest),
                    "ANALYSIS_SCOPE": "both",
                    "RUN_SUMMARY_FIGURES": "0",
                    "RUN_BGC_OVERLAP_FIGURE": "0",
                    "RUN_BIGSCAPE_NETWORK_FIGURE": "0",
                    "RUN_BIGSCAPE_MULTIPANEL_FIGURE": "0",
                    "RUN_TAXON_TREE_FIGURE": "0",
                }
            )
            completed = subprocess.run(
                ["bash", str(REPO_ROOT / "run_figures.sh")],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with (root / "work" / "figures" / "fungal_summary.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows, [{"genome": "fungus_a", "taxon_group": "fungi", "product_label": "NRPS, hybrid"}])


if __name__ == "__main__":
    unittest.main()
