import csv
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "render_bigscape_network.py"


def load_module():
    spec = importlib.util.spec_from_file_location("render_bigscape_network", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def build_synthetic_bigscape_project(tmpdir: str) -> tuple[Path, Path]:
    project_root = Path(tmpdir)
    run_dir = project_root / "Data" / "Results" / "demo" / "big_scape" / "output_files" / "2026-01-01_00-00-00_c0.3"
    mix_dir = run_dir / "mix"

    records = [
        ("genomeA__ctg1.region001.gbk_region_1", "genomeA__ctg1.region001", "10", "FAM_00001"),
        ("genomeB__ctg2.region001.gbk_region_1", "genomeB__ctg2.region001", "10", "FAM_00001"),
        ("BGC0000001.gbk_region_1", "BGC0000001", "10", "FAM_00001"),
        ("genomeC__ctg3.region001.gbk_region_1", "genomeC__ctg3.region001", "20", "FAM_00002"),
        ("genomeD__ctg4.region001.gbk_region_1", "genomeD__ctg4.region001", "30", "FAM_00003"),
        ("BGC0009999.gbk_region_1", "BGC0009999", "99", "FAM_99999"),
    ]
    write_tsv(
        mix_dir / "mix_clustering_c0.3.tsv",
        ["Record", "GBK", "Record_Type", "Record_Number", "CC", "Family"],
        [
            {
                "Record": record,
                "GBK": gbk,
                "Record_Type": "region",
                "Record_Number": "1",
                "CC": cc,
                "Family": family,
            }
            for record, gbk, cc, family in records
        ],
    )
    write_tsv(
        run_dir / "record_annotations.tsv",
        ["Record", "GBK", "Record_Type", "Record_Number", "Class", "Category", "Organism", "Taxonomy", "Description"],
        [
            {
                "Record": "genomeA__ctg1.region001.gbk_region_1",
                "GBK": "genomeA__ctg1.region001",
                "Record_Type": "region",
                "Record_Number": "1",
                "Class": "NRPS",
                "Category": "NRPS",
                "Organism": "genomeA",
                "Taxonomy": "Fungi",
                "Description": "sample A",
            },
            {
                "Record": "genomeB__ctg2.region001.gbk_region_1",
                "GBK": "genomeB__ctg2.region001",
                "Record_Type": "region",
                "Record_Number": "1",
                "Class": "T1PKS",
                "Category": "PKS",
                "Organism": "genomeB",
                "Taxonomy": "Fungi",
                "Description": "sample B",
            },
            {
                "Record": "BGC0000001.gbk_region_1",
                "GBK": "BGC0000001",
                "Record_Type": "region",
                "Record_Number": "1",
                "Class": "terpene",
                "Category": "terpene",
                "Organism": "MiBIG organism",
                "Taxonomy": "Fungi",
                "Description": "MiBIG reference",
            },
            {
                "Record": "genomeC__ctg3.region001.gbk_region_1",
                "GBK": "genomeC__ctg3.region001",
                "Record_Type": "region",
                "Record_Number": "1",
                "Class": "",
                "Category": "",
                "Organism": "genomeC",
                "Taxonomy": "Fungi",
                "Description": "missing class",
            },
            {
                "Record": "genomeD__ctg4.region001.gbk_region_1",
                "GBK": "genomeD__ctg4.region001",
                "Record_Type": "region",
                "Record_Number": "1",
                "Class": "NRPS.T1PKS",
                "Category": "NRPS.PKS",
                "Organism": "genomeD",
                "Taxonomy": "Fungi",
                "Description": "hybrid class",
            },
            {
                "Record": "BGC0009999.gbk_region_1",
                "GBK": "BGC0009999",
                "Record_Type": "region",
                "Record_Number": "1",
                "Class": "T1PKS",
                "Category": "PKS",
                "Organism": "Aspergillus nidulans FGSC A4",
                "Taxonomy": "Fungi",
                "Description": "MiBIG-only singleton",
            },
        ],
    )
    write_tsv(
        mix_dir / "mix_c0.3.network",
        [
            "Record_a",
            "GBK_a",
            "Record_Type_a",
            "Record_Number_a",
            "ORF_coords_a",
            "Record_b",
            "GBK_b",
            "Record_Type_b",
            "Record_Number_b",
            "ORF_coords_b",
            "distance",
            "jaccard",
            "adjacency",
            "dss",
            "weights",
            "alignment_mode",
            "extend_strategy",
        ],
        [
            {
                "Record_a": "genomeA__ctg1.region001.gbk_region_1",
                "GBK_a": "genomeA__ctg1.region001",
                "Record_Type_a": "region",
                "Record_Number_a": "1",
                "ORF_coords_a": "0:4",
                "Record_b": "genomeB__ctg2.region001.gbk_region_1",
                "GBK_b": "genomeB__ctg2.region001",
                "Record_Type_b": "region",
                "Record_Number_b": "1",
                "ORF_coords_b": "0:4",
                "distance": "0.10",
                "jaccard": "0.9",
                "adjacency": "0.8",
                "dss": "0.7",
                "weights": "mix",
                "alignment_mode": "GLOCAL",
                "extend_strategy": "LEGACY",
            },
            {
                "Record_a": "genomeB__ctg2.region001.gbk_region_1",
                "GBK_a": "genomeB__ctg2.region001",
                "Record_Type_a": "region",
                "Record_Number_a": "1",
                "ORF_coords_a": "0:4",
                "Record_b": "BGC0000001.gbk_region_1",
                "GBK_b": "BGC0000001",
                "Record_Type_b": "region",
                "Record_Number_b": "1",
                "ORF_coords_b": "0:4",
                "distance": "0.20",
                "jaccard": "0.8",
                "adjacency": "0.7",
                "dss": "0.6",
                "weights": "mix",
                "alignment_mode": "GLOCAL",
                "extend_strategy": "LEGACY",
            },
            {
                "Record_a": "genomeA__ctg1.region001.gbk_region_1",
                "GBK_a": "genomeA__ctg1.region001",
                "Record_Type_a": "region",
                "Record_Number_a": "1",
                "ORF_coords_a": "0:4",
                "Record_b": "genomeD__ctg4.region001.gbk_region_1",
                "GBK_b": "genomeD__ctg4.region001",
                "Record_Type_b": "region",
                "Record_Number_b": "1",
                "ORF_coords_b": "0:4",
                "distance": "0.30",
                "jaccard": "0.7",
                "adjacency": "0.6",
                "dss": "0.5",
                "weights": "mix",
                "alignment_mode": "GLOCAL",
                "extend_strategy": "LEGACY",
            },
        ],
    )
    metadata_path = project_root / "metadata.tsv"
    write_tsv(
        metadata_path,
        ["fungal_id", "ecology_category"],
        [
            {"fungal_id": "genomeA", "ecology_category": "root"},
            {"fungal_id": "genomeB", "ecology_category": "leaf"},
            {"fungal_id": "genomeD", "ecology_category": "root"},
            {"fungal_id": "metadata_only", "ecology_category": "soil"},
        ],
    )
    write_tsv(
        project_root / "Data" / "Results" / "demo" / "summary" / "candidate_bgc_gcf_crosswalk.tsv",
        ["genome", "antismash_region", "bigscape_record", "nearest_mibig_or_annotation_if_available"],
        [
            {
                "genome": "genomeA",
                "antismash_region": "ctg1.region001",
                "bigscape_record": "genomeA__ctg1.region001.gbk_region_1",
                "nearest_mibig_or_annotation_if_available": "BGC0000123.1 | synthetic product; clustercompare 0.95: synthetic product",
            },
            {
                "genome": "genomeB",
                "antismash_region": "ctg2.region001",
                "bigscape_record": "genomeB__ctg2.region001.gbk_region_1",
                "nearest_mibig_or_annotation_if_available": "BGC0000123.1 | synthetic product; clustercompare 0.75: synthetic product",
            },
        ],
    )
    return project_root, metadata_path


class BigscapeNetworkRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_loading_metadata_class_mapping_mibig_and_singletons(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root, metadata_path = build_synthetic_bigscape_project(tmpdir)
            inputs = self.module.select_bigscape_inputs(
                project_root / "Data" / "Results" / "demo" / "big_scape" / "output_files",
                "mix",
                "0.3",
            )
            annotations = self.module.load_annotations(inputs.annotations_path)
            nodes, node_warnings = self.module.load_nodes(inputs.clustering_path, annotations)
            edges, _ = self.module.load_edges(inputs.network_path, set(nodes), None, None)
            metadata, metadata_warnings, columns = self.module.load_metadata(metadata_path, "ecology_category")
            merge_warnings = self.module.assign_metadata_and_labels(nodes, metadata)
            annotated_records, _ = self.module.load_mibig_annotation_records(
                project_root / "Data" / "Results" / "demo" / "summary" / "candidate_bgc_gcf_crosswalk.tsv"
            )
            marker_warnings = self.module.mark_mibig_annotations(nodes, annotated_records)
            product_labels, _ = self.module.load_product_labels(
                project_root / "Data" / "Results" / "demo" / "summary" / "candidate_bgc_gcf_crosswalk.tsv"
            )
            self.module.assign_product_labels(nodes, product_labels)

            self.assertEqual(len(nodes), 6)
            self.assertEqual(len(edges), 3)
            self.assertEqual(nodes["genomeA__ctg1.region001.gbk_region_1"].bgc_class, "NRPS")
            self.assertEqual(nodes["genomeB__ctg2.region001.gbk_region_1"].bgc_class, "PKS")
            self.assertEqual(nodes["genomeD__ctg4.region001.gbk_region_1"].bgc_class, "hybrid")
            self.assertEqual(nodes["genomeC__ctg3.region001.gbk_region_1"].bgc_class, "unknown")
            self.assertTrue(nodes["BGC0000001.gbk_region_1"].is_mibig)
            self.assertTrue(nodes["genomeA__ctg1.region001.gbk_region_1"].has_mibig_annotation)
            self.assertFalse(nodes["genomeB__ctg2.region001.gbk_region_1"].has_mibig_annotation)
            self.assertTrue(any("Collapsed MiBIG accession markers" in warning for warning in marker_warnings))
            self.assertEqual(nodes["genomeA__ctg1.region001.gbk_region_1"].putative_products, ("synthetic product",))
            self.assertEqual(
                nodes["genomeA__ctg1.region001.gbk_region_1"].putative_product_scores,
                {"synthetic product": {"ClusterCompare": ("95%",)}},
            )
            self.assertEqual(nodes["genomeA__ctg1.region001.gbk_region_1"].ecology_category, "root")
            self.assertIn("fungal_id", columns)
            self.assertFalse(metadata_warnings)
            self.assertTrue(any("genomeC" in warning for warning in merge_warnings))
            self.assertTrue(any("metadata_only" in warning for warning in merge_warnings))
            self.assertTrue(any("Missing BGC class" in warning for warning in node_warnings))

            components = self.module.graph_components(nodes, edges)
            self.assertEqual([len(component) for component in components], [4, 1, 1])
            filtered_nodes, filtered_edges, filter_warnings = self.module.filter_dataset_dependent_mibig_references(nodes, edges)
            self.assertEqual(len(filtered_nodes), 5)
            self.assertEqual(len(filtered_edges), 3)
            self.assertNotIn("BGC0009999.gbk_region_1", filtered_nodes)
            self.assertTrue(any("Omitted MiBIG reference" in warning for warning in filter_warnings))

    def test_render_outputs_include_legends_graphml_warnings_and_deterministic_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root, metadata_path = build_synthetic_bigscape_project(tmpdir)
            output_dir = project_root / "Data" / "Results" / "demo" / "figures"

            rc = self.module.main(
                [
                    "--project-root",
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--metadata",
                    str(metadata_path),
                    "--formats",
                    "svg,graphml",
                    "--prefix",
                    "test_network",
                    "--layout-iterations",
                    "10",
                ]
            )
            self.assertEqual(rc, 0)

            svg_text = (output_dir / "test_network.svg").read_text(encoding="utf-8")
            graphml_text = (output_dir / "test_network.graphml").read_text(encoding="utf-8")
            node_attrs = (output_dir / "test_network_node_attributes.tsv").read_text(encoding="utf-8")
            legend = (output_dir / "test_network_fungal_id_legend.tsv").read_text(encoding="utf-8")
            warnings = (output_dir / "test_network_warnings.txt").read_text(encoding="utf-8")

            self.assertIn("Node Labels", svg_text)
            self.assertIn("BGC Class Fill", svg_text)
            self.assertIn("Ecology Border", svg_text)
            self.assertIn("MiBIG Marker", svg_text)
            self.assertIn("representative dataset hit", svg_text)
            self.assertNotIn("dataset BGC accession hit", svg_text)
            self.assertIn("synthetic product", svg_text)
            self.assertIn("95% / 75%", svg_text)
            self.assertIn("Product scores are antiSMASH ClusterCompare percentages.", svg_text)
            self.assertNotIn("rotate(", svg_text)
            self.assertIn("Connected GCFs", svg_text)
            self.assertNotIn('stroke="#D0D0D0"', svg_text)
            self.assertNotIn('fill-opacity="0.88"', svg_text)
            self.assertNotIn("Medium and small connected components", svg_text)
            self.assertNotIn("Singletons and no-significant-similarity records", svg_text)
            self.assertNotIn("FBGC", svg_text)
            self.assertIn("Singletons", svg_text)
            self.assertIn(self.module.MIBIG_BLUE, svg_text)
            self.assertIn("<graphml", graphml_text)
            self.assertIn("hybrid", node_attrs)
            self.assertIn("unknown", node_attrs)
            self.assertIn("has_mibig_annotation", node_attrs)
            self.assertIn("putative_products", node_attrs)
            self.assertIn("putative_product_scores", node_attrs)
            self.assertIn("synthetic product", node_attrs)
            self.assertIn("95%", node_attrs)
            self.assertNotIn("FBGC", node_attrs)
            self.assertIn("synthetic product", graphml_text)
            self.assertIn("putative_product_scores", graphml_text)
            self.assertNotIn("FBGC", graphml_text)
            self.assertIn("true", node_attrs)
            self.assertNotIn("BGC0009999", node_attrs)
            self.assertIn("MiBIG reference", legend)
            self.assertIn("Omitted MiBIG reference", warnings)
            self.assertIn("genomeC", warnings)
            self.assertIn("metadata_only", warnings)

            inputs = self.module.select_bigscape_inputs(project_root / "Data" / "Results" / "demo" / "big_scape", "mix", "0.3")
            nodes, _ = self.module.load_nodes(inputs.clustering_path, self.module.load_annotations(inputs.annotations_path))
            edges, _ = self.module.load_edges(inputs.network_path, set(nodes), None, None)
            nodes, edges, _ = self.module.filter_dataset_dependent_mibig_references(nodes, edges)
            self.module.assign_metadata_and_labels(nodes, self.module.load_metadata(metadata_path, "ecology_category")[0])
            layout_a = self.module.build_layout(nodes, edges, 900, 10)
            layout_b = self.module.build_layout(nodes, edges, 900, 10)
            self.assertEqual(layout_a.positions, layout_b.positions)

    def test_all_unknown_ecology_omits_redundant_border_legend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root, metadata_path = build_synthetic_bigscape_project(tmpdir)
            write_tsv(
                metadata_path,
                ["fungal_id", "ecology_category"],
                [
                    {"fungal_id": "genomeA", "ecology_category": ""},
                    {"fungal_id": "genomeB", "ecology_category": ""},
                    {"fungal_id": "genomeC", "ecology_category": ""},
                    {"fungal_id": "genomeD", "ecology_category": ""},
                ],
            )
            output_dir = project_root / "Data" / "Results" / "demo" / "figures"

            self.module.main(
                [
                    "--project-root",
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--metadata",
                    str(metadata_path),
                    "--formats",
                    "svg,graphml",
                    "--prefix",
                    "no_ecology_signal",
                ]
            )

            svg_text = (output_dir / "no_ecology_signal.svg").read_text(encoding="utf-8")
            warnings = (output_dir / "no_ecology_signal_warnings.txt").read_text(encoding="utf-8")
            self.assertNotIn("Ecology Border", svg_text)
            self.assertIn("No non-unknown ecology categories", warnings)


if __name__ == "__main__":
    unittest.main()
