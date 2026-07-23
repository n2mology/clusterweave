import csv
import hashlib
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "render_bigscape_multipanel.py"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "bigscape_multipanel"


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

    def test_fungal_count_chart_matches_byte_stable_fixture(self) -> None:
        summary_path = FIXTURE_DIR / "synthetic_fungi_summary.csv"
        with tempfile.TemporaryDirectory() as tmpdir:
            first_path = Path(tmpdir) / "first.svg"
            second_path = Path(tmpdir) / "second.svg"
            first_warnings: list[str] = []
            second_warnings: list[str] = []

            self.module.write_count_chart_svg(
                first_path, summary_path, first_warnings, taxon_group="fungi"
            )
            self.module.write_count_chart_svg(
                second_path, summary_path, second_warnings, taxon_group="fungi"
            )
            first = first_path.read_bytes()
            second = second_path.read_bytes()

        self.assertFalse(first_warnings)
        self.assertFalse(second_warnings)
        self.assertEqual(first, second)
        self.assertEqual(
            hashlib.sha256(first).hexdigest(),
            "d59e7e3638228f66602f9c2514f65b6e1f20875f6e53530aab0413e67e4299a8",
        )

    def test_multipanel_legends_remain_readable_at_3_15_and_50_genomes(self) -> None:
        namespace = "{http://www.w3.org/2000/svg}"
        classes = self.module.CHART_CLASSES
        for genome_count in (3, 15, 50):
            with self.subTest(genome_count=genome_count), tempfile.TemporaryDirectory() as tmpdir:
                project_root = Path(tmpdir)
                output_dir = project_root / "figures"
                summary_path = project_root / "summary.csv"
                sample_ids = [
                    f"Aspergillus_fixture_{index:03d}"
                    for index in range(1, genome_count + 1)
                ]
                with summary_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=[
                            "genome",
                            "taxon_group",
                            "tool",
                            "entity_type",
                            "class_norm",
                            "total",
                        ],
                    )
                    writer.writeheader()
                    for index, sample_id in enumerate(sample_ids):
                        for row_index, (tool, entity_type) in enumerate(
                            (
                                ("funbgcex", "BGC"),
                                ("antismash", "BGC"),
                                ("antismash", "GCF"),
                            )
                        ):
                            writer.writerow(
                                {
                                    "genome": sample_id,
                                    "taxon_group": "fungi",
                                    "tool": tool,
                                    "entity_type": entity_type,
                                    "class_norm": classes[
                                        (index * 3 + row_index) % len(classes)
                                    ],
                                    "total": str(2 + (index + row_index) % 9),
                                }
                            )

                network = self.module.network
                inputs = network.BigscapeInputs(
                    output_root=project_root,
                    run_dir=project_root,
                    category="mix",
                    clustering_path=project_root / "mix.tsv",
                    network_path=None,
                    annotations_path=None,
                )
                nodes: dict[str, object] = {}
                edges = []
                for index, sample_id in enumerate(sample_ids, start=1):
                    node_ids = []
                    for offset in range(2):
                        node_id = f"record_{index:03d}_{offset + 1}"
                        bgc_class = classes[
                            ((index - 1) * 2 + offset) % len(classes)
                        ]
                        nodes[node_id] = network.NodeRecord(
                            record=node_id,
                            sample_id=sample_id,
                            label_number=str(index),
                            bgc_class=bgc_class,
                            taxon_group="fungi",
                            fill_color=network.CLASS_COLORS[bgc_class],
                        )
                        node_ids.append(node_id)
                    edges.append(network.EdgeRecord(*node_ids, distance=0.15))

                args = self.module.build_arg_parser().parse_args(
                    [
                        "--project-root",
                        str(project_root),
                        "--project-name",
                        "scale_fixture",
                        "--summary-table",
                        str(summary_path),
                        "--output-dir",
                        str(output_dir),
                        "--taxon-group",
                        "fungi",
                        "--formats",
                        "svg",
                        "--layout-iterations",
                        "0",
                        "--no-standalone-chart",
                        "--no-warnings-file",
                        "--no-manifest",
                    ]
                )
                with mock.patch.object(
                    self.module,
                    "prepare_network_data",
                    return_value=(inputs, nodes, edges, []),
                ):
                    self.assertEqual(self.module.render_multipanel(args), 0)

                svg_bytes = (
                    output_dir / "fungi_big_scape_multipanel.svg"
                ).read_bytes()
                if genome_count == 3:
                    self.assertEqual(
                        hashlib.sha256(svg_bytes).hexdigest(),
                        "28159d44e6ee59cf4b7dcefafd0e67958223bbc68c4817dd52a83b962fd5af5d",
                    )
                root = ET.fromstring(svg_bytes)
                canvas_x, canvas_y, canvas_width, canvas_height = map(
                    float, root.attrib["viewBox"].split()
                )
                self.assertEqual((canvas_x, canvas_y), (0.0, 0.0))

                legend_boxes = [
                    element
                    for element in root.iter(f"{namespace}rect")
                    if element.attrib.get("stroke") == "#DADADA"
                ]
                self.assertEqual(len(legend_boxes), 1)
                legend_box = legend_boxes[0]
                legend_x = float(legend_box.attrib["x"])
                legend_y = float(legend_box.attrib["y"])
                legend_width = float(legend_box.attrib["width"])
                legend_height = float(legend_box.attrib["height"])
                self.assertGreaterEqual(legend_x, canvas_x)
                self.assertGreaterEqual(legend_y, canvas_y)
                self.assertLessEqual(legend_x + legend_width, canvas_width)
                self.assertLessEqual(legend_y + legend_height, canvas_height)

                text_elements = list(root.iter(f"{namespace}text"))
                chart_sample_labels = [
                    element
                    for element in text_elements
                    if element.attrib.get("x") == "168.0"
                    and any(
                        child.attrib.get("font-style") == "italic"
                        for child in element
                    )
                ]
                self.assertEqual(len(chart_sample_labels), genome_count)
                chart_label_y = sorted(
                    float(element.attrib["y"]) for element in chart_sample_labels
                )
                self.assertTrue(
                    all(
                        right - left >= 90.0
                        for left, right in zip(chart_label_y, chart_label_y[1:])
                    )
                )
                self.assertTrue(
                    all(
                        float(element.attrib["font-size"]) >= 14.0
                        for element in chart_sample_labels
                    )
                )

                legend_sample_labels = [
                    element
                    for element in text_elements
                    if any(
                        child.attrib.get("font-weight") == "800"
                        for child in element
                    )
                ]
                self.assertEqual(len(legend_sample_labels), genome_count)
                legend_label_y = sorted(
                    float(element.attrib["y"]) for element in legend_sample_labels
                )
                self.assertTrue(
                    all(
                        right - left >= 20.0
                        for left, right in zip(legend_label_y, legend_label_y[1:])
                    )
                )
                self.assertTrue(
                    all(
                        legend_x
                        <= float(element.attrib["x"])
                        <= legend_x + legend_width
                        and legend_y
                        <= float(element.attrib["y"])
                        <= legend_y + legend_height
                        for element in legend_sample_labels
                    )
                )

                visible_text = " ".join(
                    text.strip() for text in root.itertext() if text.strip()
                )
                self.assertIn("Node Labels", visible_text)
                self.assertIn("BGC Class Fill", visible_text)
                for class_name in classes:
                    self.assertIn(class_name, visible_text)


    def test_bacterial_chart_omits_funbgcex_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.csv"
            with summary_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "genome", "taxon_group", "tool", "entity_type",
                        "class_norm", "total",
                    ],
                )
                writer.writeheader()
                for tool, entity_type, class_norm, total in [
                    ("antismash", "BGC", "NRPS", "5"),
                    ("antismash", "GCF", "NRPS", "3"),
                    ("funbgcex", "BGC", "PKS", "99"),
                ]:
                    writer.writerow(
                        {
                            "genome": "bacteria_Demo",
                            "taxon_group": "bacteria",
                            "tool": tool,
                            "entity_type": entity_type,
                            "class_norm": class_norm,
                            "total": total,
                        }
                    )

            warnings: list[str] = []
            svg = "\n".join(
                self.module.chart_lines(
                    summary_path, 0, 0, 650, 330, warnings, taxon_group="bacteria"
                )
            )
            self.assertIn("antiSMASH", svg)
            self.assertIn(">GCF<", svg)
            self.assertNotIn("FunBGCeX", svg)


    def test_legacy_bacterial_multipanel_hides_only_ncbi_routing_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            output_dir = project_root / "figures"
            summary_path = project_root / "summary.csv"
            manifest_path = project_root / "genome_taxon_manifest.tsv"
            sample_ids = [
                "bacteria_Bacillus_subtilis_168",
                "bacteria_isolate_7",
            ]
            with summary_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "genome",
                        "taxon_group",
                        "tool",
                        "entity_type",
                        "class_norm",
                        "total",
                    ],
                )
                writer.writeheader()
                for sample_id in sample_ids:
                    for entity_type in ("BGC", "GCF"):
                        writer.writerow(
                            {
                                "genome": sample_id,
                                "taxon_group": "bacteria",
                                "tool": "antismash",
                                "entity_type": entity_type,
                                "class_norm": "NRPS",
                                "total": "1",
                            }
                        )
            with manifest_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["genome_id", "taxon_group", "taxon_source"],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "genome_id": sample_ids[0],
                            "taxon_group": "bacteria",
                            "taxon_source": "ncbi",
                        },
                        {
                            "genome_id": sample_ids[1],
                            "taxon_group": "bacteria",
                            "taxon_source": "user_declaration",
                        },
                    ]
                )

            network = self.module.network
            inputs = network.BigscapeInputs(
                output_root=project_root,
                run_dir=project_root,
                category="mix",
                clustering_path=project_root / "mix.tsv",
                network_path=None,
                annotations_path=None,
            )
            nodes = {
                f"record_{index}": network.NodeRecord(
                    record=f"record_{index}",
                    sample_id=sample_id,
                    label_number=str(index),
                    bgc_class="NRPS",
                    taxon_group="bacteria",
                )
                for index, sample_id in enumerate(sample_ids, start=1)
            }
            args = self.module.build_arg_parser().parse_args(
                [
                    "--project-root",
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--summary-table",
                    str(summary_path),
                    "--taxon-manifest",
                    str(manifest_path),
                    "--output-dir",
                    str(output_dir),
                    "--taxon-group",
                    "bacteria",
                    "--formats",
                    "svg",
                    "--layout-iterations",
                    "0",
                    "--no-standalone-chart",
                    "--no-warnings-file",
                    "--no-manifest",
                ]
            )
            with mock.patch.object(
                self.module,
                "prepare_network_data",
                return_value=(inputs, nodes, [], []),
            ):
                self.assertEqual(self.module.render_multipanel(args), 0)

            svg = (
                output_dir / "bacteria_big_scape_multipanel.svg"
            ).read_text(encoding="utf-8")
            self.assertNotIn(">bacteria Bacillus", svg)
            self.assertEqual(svg.count(">Bacillus subtilis<"), 2)
            self.assertEqual(svg.count(">bacteria<"), 2)

    def test_region_key_normalizes_crosswalk_and_clustering_variants(self) -> None:
        normalize = self.module.normalized_region_key
        self.assertEqual(
            normalize("genome__contig.region001.gbk"),
            normalize("genome__contig.region001"),
        )
        self.assertEqual(
            normalize("genome__contig.region001.gbk_region_1"),
            normalize("genome__contig.region001.gbk"),
        )

    def test_taxon_filter_keeps_selected_dataset_and_connected_mibig(self) -> None:
        network = self.module.network
        nodes = {
            "fungal": network.NodeRecord(record="fungal", taxon_group="fungi"),
            "bacterial": network.NodeRecord(record="bacterial", taxon_group="bacteria"),
            "mibig_connected": network.NodeRecord(record="mibig_connected", is_mibig=True),
            "mibig_unconnected": network.NodeRecord(record="mibig_unconnected", is_mibig=True),
        }
        edges = [network.EdgeRecord("bacterial", "mibig_connected", distance=0.1)]
        filtered_nodes, filtered_edges, _ = self.module.filter_nodes_for_taxon(
            nodes, edges, "bacteria"
        )
        self.assertEqual(set(filtered_nodes), {"bacterial", "mibig_connected"})
        self.assertEqual(len(filtered_edges), 1)

    def test_taxon_multipanel_svg_has_document_accessibility_metadata(self) -> None:
        for taxon_group, taxon_label in (("fungi", "Fungal"), ("bacteria", "Bacterial")):
            with self.subTest(taxon_group=taxon_group), tempfile.TemporaryDirectory() as tmpdir:
                project_root = Path(tmpdir)
                output_dir = project_root / "figures"
                summary_path = project_root / "summary.csv"
                with summary_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=[
                            "genome",
                            "taxon_group",
                            "tool",
                            "entity_type",
                            "class_norm",
                            "total",
                        ],
                    )
                    writer.writeheader()
                    writer.writerows(
                        [
                            {
                                "genome": f"{taxon_group}_demo",
                                "taxon_group": taxon_group,
                                "tool": "antismash",
                                "entity_type": entity_type,
                                "class_norm": "NRPS",
                                "total": total,
                            }
                            for entity_type, total in (("BGC", "2"), ("GCF", "1"))
                        ]
                    )

                network = self.module.network
                inputs = network.BigscapeInputs(
                    output_root=project_root,
                    run_dir=project_root,
                    category="mix",
                    clustering_path=project_root / "mix.tsv",
                    network_path=None,
                    annotations_path=None,
                )
                nodes = {
                    "record_1": network.NodeRecord(
                        record="record_1",
                        sample_id=f"{taxon_group}_demo",
                        label_number="1",
                        bgc_class="NRPS",
                        taxon_group=taxon_group,
                    )
                }
                args = self.module.build_arg_parser().parse_args(
                    [
                        "--project-root",
                        str(project_root),
                        "--project-name",
                        "demo",
                        "--summary-table",
                        str(summary_path),
                        "--output-dir",
                        str(output_dir),
                        "--taxon-group",
                        taxon_group,
                        "--formats",
                        "svg",
                        "--layout-iterations",
                        "0",
                        "--no-standalone-chart",
                        "--no-warnings-file",
                        "--no-manifest",
                    ]
                )
                with mock.patch.object(
                    self.module,
                    "prepare_network_data",
                    return_value=(inputs, nodes, [], []),
                ):
                    self.assertEqual(self.module.render_multipanel(args), 0)

                svg_path = output_dir / f"{taxon_group}_big_scape_multipanel.svg"
                root = ET.fromstring(svg_path.read_text(encoding="utf-8"))
                namespace = "{http://www.w3.org/2000/svg}"
                title = root.find(f"{namespace}title")
                description = root.find(f"{namespace}desc")

                self.assertEqual(root.attrib.get("role"), "img")
                self.assertIsNotNone(title)
                self.assertIsNotNone(description)
                assert title is not None
                assert description is not None
                self.assertEqual(root.attrib.get("aria-labelledby"), title.attrib.get("id"))
                self.assertEqual(root.attrib.get("aria-describedby"), description.attrib.get("id"))
                self.assertEqual(title.text, f"{taxon_label} BGC and GCF multipanel")
                self.assertIn(f"1 {taxon_label.lower()} genome", description.text or "")
                self.assertIn("Panel A compares BGC and GCF counts", description.text or "")
                self.assertIn("Panel B shows a BiG-SCAPE clustering network", description.text or "")

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
