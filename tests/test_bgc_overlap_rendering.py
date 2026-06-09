import csv
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "render_bgc_overlap.py"


def load_module():
    bin_dir = str(REPO_ROOT / "bin")
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)
    spec = importlib.util.spec_from_file_location("render_bgc_overlap", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BgcOverlapRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_shared_counts_are_not_double_counted_and_tool_specific_classes_are_union_relative_bars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            summary_path = project_root / "data" / "results" / "demo" / "summary" / "all_tools_shared_unshared_summary.csv"
            output_dir = project_root / "data" / "results" / "demo" / "figures"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                ("Aspergillus_alpha_NRRL_1", "antismash", "BGC", "NRPS", "5", "2", "7"),
                ("Aspergillus_alpha_NRRL_1", "funbgcex", "BGC", "NRPS", "5", "3", "8"),
                ("Aspergillus_alpha_NRRL_1", "antismash", "BGC", "terpene", "1", "4", "5"),
                ("Aspergillus_alpha_NRRL_1", "funbgcex", "BGC", "terpene", "1", "0", "1"),
            ]
            with summary_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["genome", "tool", "entity_type", "class_norm", "shared_count", "unshared_count", "total"],
                )
                writer.writeheader()
                for genome, tool, entity_type, class_norm, shared_count, unshared_count, total in rows:
                    writer.writerow(
                        {
                            "genome": genome,
                            "tool": tool,
                            "entity_type": entity_type,
                            "class_norm": class_norm,
                            "shared_count": shared_count,
                            "unshared_count": unshared_count,
                            "total": total,
                        }
                    )

            genomes, matrix = self.module.overlap_counts(summary_path)
            self.assertEqual(genomes, ["Aspergillus_alpha_NRRL_1"])
            self.assertEqual(matrix["Aspergillus_alpha_NRRL_1"]["shared"]["NRPS"], 5)
            self.assertEqual(matrix["Aspergillus_alpha_NRRL_1"]["antismash_only"]["NRPS"], 2)
            self.assertEqual(matrix["Aspergillus_alpha_NRRL_1"]["funbgcex_only"]["NRPS"], 3)
            self.assertEqual(matrix["Aspergillus_alpha_NRRL_1"]["unshared"]["NRPS"], 5)
            self.assertEqual(matrix["Aspergillus_alpha_NRRL_1"]["unshared"]["terpene"], 4)

            rc = self.module.main(
                [
                    "--project-root",
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--formats",
                    "svg",
                ]
            )
            self.assertEqual(rc, 0)
            svg = (output_dir / "bgc_overlap.svg").read_text(encoding="utf-8")
            self.assertIn("BGC scaffold overlap between antiSMASH and FunBGCeX", svg)
            self.assertIn(">Shared (n = 6)</text>", svg)
            self.assertIn('data-segment="shared"', svg)
            self.assertIn('data-chart="agreement-pie"', svg)
            self.assertIn('data-radius="100.0"', svg)
            self.assertIn('data-chart="class-horizontal-bars"', svg)
            self.assertIn('data-orientation="horizontal"', svg)
            self.assertIn('data-x-axis="raw-count"', svg)
            self.assertIn('data-scale-max="4"', svg)
            self.assertIn('data-exploded="true"', svg)
            self.assertIn('data-connector="slice-to-bar"', svg)
            self.assertIn('data-curve="curved-bend"', svg)
            self.assertIn('data-bend-x=', svg)
            connector_paths = [line for line in svg.splitlines() if 'data-connector="slice-to-bar"' in line]
            self.assertTrue(connector_paths)
            self.assertTrue(all(" Q " in path for path in connector_paths))
            self.assertTrue(all(path.count(" Q ") == 1 for path in connector_paths))
            self.assertIn('data-tool="antismash_only"', svg)
            self.assertIn('data-tool="funbgcex_only"', svg)
            self.assertIn('data-value="2"', svg)
            self.assertIn('data-value="3"', svg)
            self.assertIn('data-value="4"', svg)
            self.assertIn('data-total-percent="40%"', svg)
            self.assertIn('data-total-percent="20%"', svg)
            self.assertIn('data-percent="13%"', svg)
            self.assertIn('data-percent="27%"', svg)
            self.assertIn('data-percent="20%"', svg)
            self.assertIn(">13%</text>", svg)
            self.assertIn(">27%</text>", svg)
            self.assertIn(">20%</text>", svg)
            self.assertIn("Shared: 6 BGCs; 40% of genome union", svg)
            self.assertIn("antiSMASH-only (n = 6)", svg)
            self.assertIn("FunBGCeX-only (n = 3)", svg)
            self.assertNotIn("Agreement pie (% of union)", svg)
            self.assertNotIn("Tool-specific class bars (% of union)", svg)
            self.assertNotIn("union n=", svg)
            self.assertNotIn("Legend", svg)
            self.assertNotIn("Tool-specific classes (% of tool-only calls)", svg)
            self.assertNotIn("Tool-specific class pies (% of union)", svg)
            self.assertNotIn('data-chart="class-pie"', svg)
            self.assertNotIn('data-chart="class-vertical-bars"', svg)
            self.assertNotIn('data-connector="slice-edge-to-bar"', svg)
            self.assertNotIn('data-elbow-x=', svg)
            self.assertNotIn('data-curve="straight"', svg)
            self.assertNotIn('data-curve="one-bend"', svg)
            self.assertNotIn('data-curve="j-elbow"', svg)
            self.assertNotIn('data-curve="c-curve"', svg)
            self.assertNotIn('stroke-opacity="0.55"', svg)
            self.assertNotIn('data-role="class-bar-background"', svg)
            self.assertNotIn("% of genome union</text>", svg)
            self.assertNotIn('data-class="PKS"', svg)
            self.assertNotIn('data-class="RiPP"', svg)
            self.assertNotIn('data-class="hybrid"', svg)
            self.assertNotIn('data-class="other"', svg)
            self.assertNotIn('paint-order="stroke"', svg)
            self.assertNotIn('data-percent="33%"', svg)
            self.assertNotIn('data-percent="67%"', svg)
            self.assertNotIn('data-percent="100%"', svg)
            self.assertNotIn("n=6 (40%)", svg)
            self.assertNotIn("n=3 (20%)", svg)


if __name__ == "__main__":
    unittest.main()
