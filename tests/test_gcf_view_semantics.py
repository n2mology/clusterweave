from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CROSSWALK_BUILDER = REPO_ROOT / "bin" / "build_bgc_gcf_crosswalk.py"
TREE_RENDERER = REPO_ROOT / "bin" / "render_phylo_taxon_profile.py"


def write_table(
    path: Path,
    fields: list[str],
    rows: list[dict[str, str]],
    *,
    delimiter: str = "\t",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


class GcfViewSemanticsTests(unittest.TestCase):
    def test_crosswalk_preserves_every_view_and_selects_mix_c03(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "data" / "results" / "demo"
            summary = results / "summary"
            bigscape = results / "big_scape" / "output_files"
            comparison_fields = [
                "genome",
                "taxon_group",
                "prediction_method",
                "funbgcex_applicability",
                "antismash_bgc_id",
                "antismash_bgc_class",
                "funbgcex_bgc_id",
            ]
            write_table(
                summary / "all_tools_bgc_comparison.csv",
                comparison_fields,
                [
                    {
                        "genome": "Genome_A",
                        "taxon_group": "fungi",
                        "prediction_method": "funannotate",
                        "funbgcex_applicability": "applicable",
                        "antismash_bgc_id": "region001",
                        "antismash_bgc_class": "NRPS",
                        "funbgcex_bgc_id": "",
                    },
                    {
                        "genome": "Genome_Unassigned",
                        "taxon_group": "fungi",
                        "prediction_method": "funannotate",
                        "funbgcex_applicability": "applicable",
                        "antismash_bgc_id": "region001",
                        "antismash_bgc_class": "NRPS",
                        "funbgcex_bgc_id": "",
                    },
                    {
                        "genome": "Detector_Only",
                        "taxon_group": "fungi",
                        "prediction_method": "funannotate",
                        "funbgcex_applicability": "applicable",
                        "antismash_bgc_id": "",
                        "antismash_bgc_class": "",
                        "funbgcex_bgc_id": "cluster_001",
                    },
                    {
                        "genome": "Bacterium_A",
                        "taxon_group": "bacteria",
                        "prediction_method": "",
                        "funbgcex_applicability": "",
                        "antismash_bgc_id": "Bacterium_A_NC_1.region001",
                        "antismash_bgc_class": "NRPS",
                        "funbgcex_bgc_id": "",
                    },
                ],
                delimiter=",",
            )
            record = "Genome_A__region001.gbk_region_1"
            gbk = "Genome_A__region001"
            bacterial_gbk = (
                "bacteria_Bacterium_A__bacteria_Bacterium_A_NC_1.region001"
            )
            bacterial_record = f"{bacterial_gbk}.gbk_region_1"
            annotation_rows = [
                {"Record": record, "GBK": gbk, "Description": "fixture"},
                {
                    "Record": bacterial_record,
                    "GBK": bacterial_gbk,
                    "Description": "bacterial fixture",
                },
            ]
            write_table(
                bigscape / "record_annotations.tsv",
                ["Record", "GBK", "Description"],
                annotation_rows,
            )
            clustering_fields = ["Record", "GBK", "Family", "CC"]
            for relative, family in (
                ("mix/mix_clustering_c0.3.tsv", "FAM_MIX"),
                ("mix/mix_clustering_c0.4.tsv", "FAM_MIX_04"),
                ("NRPS/NRPS_clustering_c0.3.tsv", "FAM_NRPS"),
            ):
                write_table(
                    bigscape / relative,
                    clustering_fields,
                    [
                        {"Record": record, "GBK": gbk, "Family": family, "CC": ""},
                        {
                            "Record": bacterial_record,
                            "GBK": bacterial_gbk,
                            "Family": family,
                            "CC": "",
                        },
                    ],
                )

            output = summary / "candidate_bgc_gcf_crosswalk.tsv"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(CROSSWALK_BUILDER),
                    "--project-root",
                    str(root),
                    "--project-name",
                    "demo",
                    "--output",
                    str(output),
                    "--selected-gcf-category",
                    "MIX",
                    "--selected-gcf-threshold",
                    "c0.30",
                ],
                cwd=REPO_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with output.open(newline="", encoding="utf-8") as handle:
                rows = {
                    row["genome"]: row
                    for row in csv.DictReader(handle, delimiter="\t")
                }

            assigned = rows["Genome_A"]
            self.assertEqual(
                assigned["gcf_id"],
                "FAM_MIX;FAM_MIX_04;FAM_NRPS",
            )
            self.assertEqual(
                assigned["gcf_memberships"],
                (
                    "mix@c0.3=FAM_MIX;"
                    "mix@c0.4=FAM_MIX_04;"
                    "nrps@c0.3=FAM_NRPS"
                ),
            )
            self.assertEqual(assigned["gcf_selected_category"], "mix")
            self.assertEqual(assigned["gcf_selected_threshold"], "0.3")
            self.assertEqual(assigned["gcf_selected_id"], "FAM_MIX")
            self.assertEqual(assigned["gcf_selected_status"], "assigned")
            self.assertEqual(
                rows["Genome_Unassigned"]["gcf_selected_status"],
                "unassigned",
            )
            self.assertEqual(
                rows["Detector_Only"]["gcf_selected_status"],
                "not_applicable_detector_only",
            )
            self.assertEqual(rows["Bacterium_A"]["gcf_selected_id"], "FAM_MIX")
            self.assertEqual(
                rows["Bacterium_A"]["funbgcex_applicability"],
                "not_applicable_taxon",
            )
            self.assertEqual(
                rows["Bacterium_A"]["antismash_region"],
                "Bacterium_A_NC_1.region001",
            )

    def test_tree_uses_selected_view_and_exports_unassigned_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "genome_taxon_manifest.tsv"
            exact = root / "antismash_product_types_exact.tsv"
            crosswalk = root / "candidate_bgc_gcf_crosswalk.tsv"
            output = root / "tree"
            write_table(
                manifest,
                [
                    "genome_id",
                    "taxon_group",
                    "taxon_source",
                    "taxid",
                    "organism_name",
                    "lineage_names",
                    "lineage_ids",
                    "prediction_method",
                    "detector_profile",
                ],
                [
                    {
                        "genome_id": "Fungus_A",
                        "taxon_group": "fungi",
                        "taxon_source": "ncbi",
                        "taxid": "100",
                        "organism_name": "Fixture fungus",
                        "lineage_names": "Eukaryota|Fungi|Ascomycota",
                        "lineage_ids": "2759|4751|4890",
                        "prediction_method": "funannotate",
                        "detector_profile": "antismash+funbgcex",
                    },
                    {
                        "genome_id": "bacteria_Bacterium_A",
                        "taxon_group": "bacteria",
                        "taxon_source": "ncbi",
                        "taxid": "200",
                        "organism_name": "Fixture bacterium",
                        "lineage_names": "Bacteria|Pseudomonadota",
                        "lineage_ids": "2|1224",
                        "prediction_method": "prodigal",
                        "detector_profile": "antismash",
                    },
                ],
            )
            write_table(
                exact,
                [
                    "genome",
                    "bgc_id",
                    "exact_product_type",
                    "broad_display_class",
                ],
                [
                    {
                        "genome": "Fungus_A",
                        "bgc_id": "region001",
                        "exact_product_type": "NRPS",
                        "broad_display_class": "NRPS",
                    },
                    {
                        "genome": "bacteria_Bacterium_A",
                        "bgc_id": "region001",
                        "exact_product_type": "NRPS",
                        "broad_display_class": "NRPS",
                    },
                ],
            )
            fields = [
                "genome",
                "taxon_group",
                "antismash_region",
                "antismash_class",
                "gcf_id",
                "gcf_memberships",
                "gcf_selected_category",
                "gcf_selected_threshold",
                "gcf_selected_id",
                "gcf_selected_status",
            ]
            write_table(
                crosswalk,
                fields,
                [
                    {
                        "genome": "Fungus_A",
                        "taxon_group": "fungi",
                        "antismash_region": "region001",
                        "antismash_class": "NRPS",
                        "gcf_id": "MIX_PRIVATE;MIX_SHARED;NRPS_ALIAS_F",
                        "gcf_memberships": (
                            "mix@c0.3=MIX_PRIVATE;"
                            "mix@c0.3=MIX_SHARED;"
                            "nrps@c0.3=NRPS_ALIAS_F"
                        ),
                        "gcf_selected_category": "mix",
                        "gcf_selected_threshold": "0.3",
                        "gcf_selected_id": "MIX_PRIVATE;MIX_SHARED",
                        "gcf_selected_status": "assigned",
                    },
                    {
                        "genome": "Fungus_A",
                        "taxon_group": "fungi",
                        "antismash_region": "region002",
                        "antismash_class": "PKS",
                        "gcf_id": "",
                        "gcf_memberships": "",
                        "gcf_selected_category": "mix",
                        "gcf_selected_threshold": "0.3",
                        "gcf_selected_id": "",
                        "gcf_selected_status": "unassigned",
                    },
                    {
                        "genome": "Fungus_A",
                        "taxon_group": "fungi",
                        "antismash_region": "",
                        "antismash_class": "",
                        "gcf_id": "",
                        "gcf_memberships": "",
                        "gcf_selected_category": "mix",
                        "gcf_selected_threshold": "0.3",
                        "gcf_selected_id": "",
                        "gcf_selected_status": "not_applicable_detector_only",
                    },
                    {
                        "genome": "Bacterium_A",
                        "taxon_group": "bacteria",
                        "antismash_region": "region001",
                        "antismash_class": "NRPS",
                        "gcf_id": "MIX_SHARED;NRPS_ALIAS_B",
                        "gcf_memberships": (
                            "mix@c0.3=MIX_SHARED;"
                            "nrps@c0.3=NRPS_ALIAS_B"
                        ),
                        "gcf_selected_category": "mix",
                        "gcf_selected_threshold": "0.3",
                        "gcf_selected_id": "MIX_SHARED",
                        "gcf_selected_status": "assigned",
                    },
                ],
            )
            command = [
                sys.executable,
                str(TREE_RENDERER),
                "--manifest",
                str(manifest),
                "--exact-products",
                str(exact),
                "--crosswalk",
                str(crosswalk),
                "--output-dir",
                str(output),
                "--gcf-category",
                "MIX",
                "--gcf-threshold",
                "c0.30",
            ]
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            with (
                output / "clusterweave_taxon_tree_leaf_profiles.tsv"
            ).open(newline="", encoding="utf-8") as handle:
                profiles = {
                    row["genome_id"]: row
                    for row in csv.DictReader(handle, delimiter="\t")
                }
            fungus = profiles["Fungus_A"]
            bacterium = profiles["bacteria_Bacterium_A"]
            self.assertEqual(fungus["gcf_selected_category"], "mix")
            self.assertEqual(fungus["gcf_selected_threshold"], "0.3")
            self.assertEqual(fungus["gcf_total"], "2")
            self.assertEqual(fungus["gcf_shared_across_taxon"], "1")
            self.assertEqual(fungus["gcf_private_singleton"], "1")
            self.assertEqual(fungus["gcf_unassigned_rows"], "1")
            self.assertEqual(fungus["gcf_not_applicable_rows"], "1")
            self.assertEqual(fungus["gcf_ids"], "MIX_PRIVATE;MIX_SHARED")
            self.assertEqual(bacterium["gcf_total"], "1")

            with (
                output / "clusterweave_gcf_network_edges.tsv"
            ).open(newline="", encoding="utf-8") as handle:
                edges = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(edges), 1)
            edge = edges[0]
            self.assertEqual(edge["gcf_category"], "mix")
            self.assertEqual(edge["gcf_threshold"], "0.3")
            self.assertEqual(edge["shared_gcf_ids"], "MIX_SHARED")
            self.assertEqual(edge["cross_taxon"], "yes")
            self.assertNotIn("NRPS_ALIAS", repr(edges))

            svg = (output / "clusterweave_taxon_tree.svg").read_text(
                encoding="utf-8"
            )
            self.assertIn("50.0%", svg)
            self.assertIn("100.0%", svg)
            self.assertIn(
                "GCF overlap 50.0% (Jaccard); 1 shared GCFs",
                svg,
            )

            graphml = (
                output / "clusterweave_taxon_tree.graphml"
            ).read_text(encoding="utf-8")
            self.assertIn(
                '<data key="selected_category">mix</data>',
                graphml,
            )
            self.assertIn(
                '<data key="selected_threshold">0.3</data>',
                graphml,
            )
            self.assertIn('<data key="gcf_unassigned">1</data>', graphml)
            self.assertNotIn("NRPS_ALIAS", graphml)

            methods = json.loads(
                (output / "clusterweave_tree_methods.json").read_text(
                    encoding="utf-8"
                )
            )
            manifest_json = json.loads(
                (output / "clusterweave_tree_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(methods["schema_version"], 2)
            self.assertEqual(manifest_json["schema_version"], 2)
            self.assertEqual(methods["gcf_selected_category"], "mix")
            self.assertEqual(methods["gcf_selected_threshold"], "0.3")
            self.assertIn(
                "excluded from private/singleton",
                methods["gcf_unassigned_interpretation"],
            )
            self.assertEqual(manifest_json["gcf_assigned_family_count"], 2)
            self.assertEqual(manifest_json["gcf_unassigned_row_count"], 1)
            self.assertEqual(manifest_json["gcf_not_applicable_row_count"], 1)

            svg = (
                output / "clusterweave_taxon_tree.svg"
            ).read_text(encoding="utf-8")
            self.assertIn("Pairwise GCF sharing", svg)
            self.assertIn('fill="url(#crossHatch)"', svg)
            self.assertNotIn("NRPS_ALIAS", svg)

            first = {
                path.name: path.read_bytes()
                for path in output.iterdir()
                if path.is_file()
            }
            repeated = subprocess.run(
                command,
                cwd=REPO_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            second = {
                path.name: path.read_bytes()
                for path in output.iterdir()
                if path.is_file()
            }
            self.assertEqual(second, first)

    def test_wrappers_pass_one_explicit_gcf_view(self) -> None:
        figures = (REPO_ROOT / "run_figures.sh").read_text(encoding="utf-8")
        summary = (
            REPO_ROOT / "summarize_clusterweave.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '--gcf-category "${BIGSCAPE_NETWORK_CATEGORY}"',
            figures,
        )
        self.assertIn(
            '--gcf-threshold "${BIGSCAPE_NETWORK_CLUSTERING_THRESHOLD}"',
            figures,
        )
        self.assertIn(
            '--selected-gcf-category "${BIGSCAPE_GCF_CATEGORY}"',
            summary,
        )
        self.assertIn(
            '--selected-gcf-threshold "${BIGSCAPE_GCF_THRESHOLD}"',
            summary,
        )


if __name__ == "__main__":
    unittest.main()
