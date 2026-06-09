import csv
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "render_bigscape_multipanel.py"


def load_module():
    bin_dir = str(REPO_ROOT / "bin")
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)
    spec = importlib.util.spec_from_file_location("render_bigscape_multipanel", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BigscapeMultipanelRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_chart_uses_horizontal_bgc_tool_rows_then_gcf_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.csv"
            rows = [
                ("Fungus_alpha", "antismash", "BGC", "NRPS", "10"),
                ("Fungus_alpha", "funbgcex", "BGC", "PKS", "12"),
                ("Fungus_alpha", "antismash", "GCF", "NRPS;PKS", "4"),
            ]
            with summary_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["genome", "tool", "entity_type", "class_norm", "shared_count", "unshared_count", "total"],
                )
                writer.writeheader()
                for genome, tool, entity_type, class_norm, total in rows:
                    writer.writerow(
                        {
                            "genome": genome,
                            "tool": tool,
                            "entity_type": entity_type,
                            "class_norm": class_norm,
                            "shared_count": total,
                            "unshared_count": "0",
                            "total": total,
                        }
                    )

            warnings: list[str] = []
            svg = "\n".join(self.module.chart_lines(summary_path, 0, 0, 650, 360, warnings))

            self.assertFalse(warnings)
            self.assertIn("BGC and GCF count", svg)
            self.assertIn('font-style="italic">Fungus alpha', svg)
            self.assertLess(svg.index("FunBGCeX"), svg.index("antiSMASH"))
            self.assertLess(svg.index("antiSMASH"), svg.index(">GCF<"))
            self.assertIn('font-weight="700" text-anchor="middle"', svg)
            rects = [
                (float(width), float(height))
                for width, height in re.findall(r'<rect [^>]*width="([0-9.]+)" height="([0-9.]+)"', svg)
            ]
            self.assertTrue(any(width > height for width, height in rects))

    def test_chart_height_scales_with_fungus_count(self) -> None:
        height_three = self.module.chart_height_for_genome_count(3)
        height_ten = self.module.chart_height_for_genome_count(10)

        self.assertLess(height_three, 450)
        self.assertGreater(height_ten, height_three)

    def test_network_column_keeps_all_section_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            network = self.module.network
            nodes = {
                node_id: network.NodeRecord(record=node_id, sample_id="Aspergillus_alpha_NRRL_1", label_number="1")
                for node_id in ["node1", "node2", "node3", "node4", "node5", "node6"]
            }
            edges = [
                network.EdgeRecord("node1", "node2", distance=0.1),
                network.EdgeRecord("node2", "node3", distance=0.1),
                network.EdgeRecord("node1", "node3", distance=0.1),
                network.EdgeRecord("node4", "node5", distance=0.1),
            ]
            layout = network.build_layout(
                nodes,
                edges,
                900,
                0,
                reserved_top_left=(160.0, 100000.0),
                combine_connected_components=True,
            )
            path = Path(tmpdir) / "network.svg"
            inputs = network.BigscapeInputs(
                output_root=Path(tmpdir),
                run_dir=Path(tmpdir),
                category="mix",
                clustering_path=Path(tmpdir) / "mix.tsv",
                network_path=None,
                annotations_path=None,
            )

            network.render_svg(path, nodes, edges, layout, inputs, section_titles={"large": None}, section_x=230.0)
            svg = path.read_text(encoding="utf-8")

            self.assertIn("Connected GCFs", svg)
            self.assertIn("Doubletons", svg)
            self.assertIn("Singletons", svg)
            self.assertIn('stroke="#DADADA"', svg)
            self.assertNotIn("BiG-SCAPE category:", svg)


if __name__ == "__main__":
    unittest.main()
