from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
BIN = REPO_ROOT / "bin"


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


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def load_stage_module():
    spec = importlib.util.spec_from_file_location(
        "selected_gcf_stage_under_test",
        BIN / "stage_clinker_panels.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SelectedGcfDownstreamTests(unittest.TestCase):
    def create_project(self, root: Path) -> tuple[Path, Path]:
        results = root / "data" / "results" / "demo"
        summary = results / "summary"
        tables = results / "summary_tables"
        genomes = ["A", "B", "C", "D", "U"]

        write_table(
            tables / "ecofun_metadata_normalized.tsv",
            [
                "accession",
                "genome_id_current",
                "ecofun_primary",
                "ecofun_secondary",
            ],
            [
                {
                    "accession": "ACC_" + genome,
                    "genome_id_current": genome,
                    "ecofun_primary": "soil",
                    "ecofun_secondary": "",
                }
                for genome in genomes
            ],
        )
        write_table(
            summary / "all_tools_shared_unshared_summary.csv",
            [
                "genome",
                "tool",
                "entity_type",
                "class_norm",
                "shared_count",
                "unshared_count",
                "total",
            ],
            [],
            delimiter=",",
        )

        comparison_fields = [
            "genome",
            "taxon_group",
            "prediction_method",
            "funbgcex_applicability",
            "antismash_bgc_id",
            "funbgcex_bgc_id",
            "antismash_bgc_class",
            "funbgcex_core_enzymes",
            "overlap_bp",
            "antismash_knowncluster_similarity_score",
            "antismash_knowncluster_accession",
            "antismash_knowncluster_product",
            "antismash_clustercompare_similarity_score",
            "antismash_clustercompare_compounds",
            "antismash_clustercompare_organism",
            "funbgcex_similarity_score",
            "funbgcex_similar_bgc",
            "funbgcex_putative_product",
            "same_putative_product_exact",
            "same_putative_product_keyword",
        ]
        write_table(
            summary / "all_tools_bgc_comparison.csv",
            comparison_fields,
            [
                {
                    "genome": genome,
                    "taxon_group": "fungi",
                    "prediction_method": "funannotate",
                    "funbgcex_applicability": "applicable",
                    "antismash_bgc_id": "region001",
                    "funbgcex_bgc_id": "cluster001",
                    "antismash_bgc_class": "NRPS",
                    "funbgcex_core_enzymes": "NRPS",
                    "overlap_bp": "100",
                    "antismash_knowncluster_similarity_score": "50",
                    "antismash_knowncluster_accession": "BGC0000001",
                    "antismash_knowncluster_product": "Known product",
                    "antismash_clustercompare_similarity_score": "0",
                    "antismash_clustercompare_compounds": "",
                    "antismash_clustercompare_organism": "",
                    "funbgcex_similarity_score": "11",
                    "funbgcex_similar_bgc": "FBGC1",
                    "funbgcex_putative_product": "Known product",
                    "same_putative_product_exact": "yes",
                    "same_putative_product_keyword": "yes",
                }
                for genome in genomes
            ],
            delimiter=",",
        )

        crosswalk_fields = [
            "genome",
            "taxon_group",
            "prediction_method",
            "funbgcex_applicability",
            "antismash_region",
            "antismash_class",
            "gcf_id",
            "gcf_memberships",
            "gcf_selected_category",
            "gcf_selected_threshold",
            "gcf_selected_id",
            "gcf_selected_status",
            "nearest_mibig_or_annotation_if_available",
            "funbgcex_cluster",
            "notes",
        ]
        selected = {
            "A": ("MIX_SHARED;NRPS_ALIAS_A", "mix@c0.3=MIX_SHARED;nrps@c0.3=NRPS_ALIAS_A", "MIX_SHARED", "assigned"),
            "B": ("MIX_SHARED;NRPS_ALIAS_B", "mix@c0.3=MIX_SHARED;nrps@c0.3=NRPS_ALIAS_B", "MIX_SHARED", "assigned"),
            "C": ("MIX_C;NRPS_ALIAS_COMMON", "mix@c0.3=MIX_C;nrps@c0.3=NRPS_ALIAS_COMMON", "MIX_C", "assigned"),
            "D": ("MIX_D;NRPS_ALIAS_COMMON", "mix@c0.3=MIX_D;nrps@c0.3=NRPS_ALIAS_COMMON", "MIX_D", "assigned"),
            "U": ("NRPS_ALIAS_U", "nrps@c0.3=NRPS_ALIAS_U", "", "unassigned"),
        }
        write_table(
            summary / "candidate_bgc_gcf_crosswalk.tsv",
            crosswalk_fields,
            [
                {
                    "genome": genome,
                    "taxon_group": "fungi",
                    "prediction_method": "funannotate",
                    "funbgcex_applicability": "applicable",
                    "antismash_region": "region001",
                    "antismash_class": "NRPS",
                    "gcf_id": selected[genome][0],
                    "gcf_memberships": selected[genome][1],
                    "gcf_selected_category": "mix",
                    "gcf_selected_threshold": "0.3",
                    "gcf_selected_id": selected[genome][2],
                    "gcf_selected_status": selected[genome][3],
                    "nearest_mibig_or_annotation_if_available": "BGC0000001 | Known product",
                    "funbgcex_cluster": "cluster001",
                    "notes": "",
                }
                for genome in genomes
            ],
        )

        antismash = results / "antismash"
        for genome in genomes:
            gbk = antismash / genome / "region001.gbk"
            gbk.parent.mkdir(parents=True, exist_ok=True)
            gbk.write_text("LOCUS       region001\n", encoding="utf-8")

        bigscape = results / "big_scape" / "output_files"
        annotations = []
        mix_rows = []
        family_by_genome = {
            "A": ("MIX_SHARED", "1"),
            "B": ("MIX_SHARED", "1"),
            "C": ("MIX_C", "2"),
            "D": ("MIX_D", "3"),
        }
        for genome, (family, cc) in family_by_genome.items():
            record = genome + "_record"
            gbk = genome + "__region001"
            annotations.append(
                {
                    "Record": record,
                    "GBK": gbk,
                    "Organism": genome,
                    "Class": "NRPS",
                }
            )
            mix_rows.append(
                {
                    "Record": record,
                    "GBK": gbk,
                    "Family": family,
                    "CC": cc,
                }
            )
        write_table(
            bigscape / "record_annotations.tsv",
            ["Record", "GBK", "Organism", "Class"],
            annotations,
        )
        write_table(
            bigscape / "mix" / "mix_clustering_c0.3.tsv",
            ["Record", "GBK", "Family", "CC"],
            mix_rows,
        )
        write_table(
            bigscape / "NRPS" / "NRPS_clustering_c0.3.tsv",
            ["Record", "GBK", "Family", "CC"],
            [
                {
                    "Record": genome + "_record",
                    "GBK": genome + "__region001",
                    "Family": (
                        "NRPS_ALIAS_COMMON"
                        if genome in {"C", "D"}
                        else "NRPS_ALIAS_" + genome
                    ),
                    "CC": "9",
                }
                for genome in ["A", "B", "C", "D"]
            ],
        )
        write_table(
            bigscape / "mix" / "mix_clustering_c0.4.tsv",
            ["Record", "GBK", "Family", "CC"],
            [
                {
                    "Record": "A_record",
                    "GBK": "A__region001",
                    "Family": "MIX_WRONG_THRESHOLD",
                    "CC": "7",
                }
            ],
        )
        return results, summary

    def run_checked(self, command: list[str]) -> None:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_selected_view_drives_ranking_shortlists_atlas_and_panels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results, summary = self.create_project(root)
            metadata = (
                results
                / "summary_tables"
                / "ecofun_metadata_normalized.tsv"
            )

            self.run_checked(
                [
                    sys.executable,
                    str(BIN / "build_candidate_tables.py"),
                    "--project-root",
                    str(root),
                    "--project-name",
                    "demo",
                    "--metadata",
                    str(metadata),
                    "--ecology-field",
                    "ecofun_primary",
                ]
            )
            ranking_path = summary / "targeted_candidate_ranking.tsv"
            ranking = {row["genome"]: row for row in read_tsv(ranking_path)}

            self.assertEqual(ranking["A"]["gcf_genome_count"], "2")
            self.assertEqual(ranking["B"]["gcf_genome_count"], "2")
            self.assertEqual(ranking["C"]["gcf_genome_count"], "1")
            self.assertEqual(ranking["D"]["gcf_genome_count"], "1")
            self.assertEqual(ranking["U"]["gcf_genome_count"], "0")
            self.assertEqual(ranking["U"]["gcf_family_count"], "0")
            self.assertEqual(ranking["U"]["gcf_ecology_pattern"], "no_gcf")
            self.assertEqual(
                int(ranking["A"]["priority_score"])
                - int(ranking["U"]["priority_score"]),
                2,
            )
            self.assertEqual(ranking["A"]["gcf_selected_id"], "MIX_SHARED")
            self.assertEqual(
                ranking["A"]["gcf_id"],
                "MIX_SHARED;NRPS_ALIAS_A",
            )
            self.assertIn(
                "nrps@c0.3=NRPS_ALIAS_A",
                ranking["A"]["gcf_memberships"],
            )
            context_text = (
                summary / "gcf_ecology_distribution.tsv"
            ).read_text(encoding="utf-8")
            self.assertIn("MIX_SHARED", context_text)
            self.assertNotIn("NRPS_ALIAS", context_text)

            self.run_checked(
                [
                    sys.executable,
                    str(BIN / "export_priority_shortlist.py"),
                    "--project-root",
                    str(root),
                    "--project-name",
                    "demo",
                    "--genome",
                    "A",
                ]
            )
            priority = read_tsv(summary / "priority_shortlist.tsv")
            self.assertEqual(len(priority), 1)
            self.assertEqual(priority[0]["gcf_selected_id"], "MIX_SHARED")
            self.assertEqual(
                priority[0]["gcf_id"],
                "MIX_SHARED;NRPS_ALIAS_A",
            )
            self.assertIn(
                "nrps@c0.3=NRPS_ALIAS_A",
                priority[0]["gcf_memberships"],
            )

            self.run_checked(
                [
                    sys.executable,
                    str(BIN / "export_shared_family_shortlist.py"),
                    "--project-root",
                    str(root),
                    "--project-name",
                    "demo",
                    "--metadata",
                    str(metadata),
                    "--genome",
                    "A",
                    "--stage-limit",
                    "4",
                    "--min-records",
                    "1",
                    "--gcf-category",
                    "MIX",
                    "--gcf-threshold",
                    "c0.30",
                ]
            )
            shared = read_tsv(summary / "shared_family_shortlist.tsv")
            self.assertEqual(len(shared), 1)
            self.assertEqual(shared[0]["gcf_selected_id"], "MIX_SHARED")
            self.assertEqual(
                shared[0]["gcf_selected_category"],
                "mix",
            )
            self.assertEqual(
                shared[0]["shared_cc_all_family_aliases"],
                "MIX_SHARED",
            )
            self.assertIn("NRPS_ALIAS_A", shared[0]["gcf_id"])
            self.assertIn(
                "NRPS_ALIAS_A",
                shared[0]["gcf_memberships"],
            )

            self.run_checked(
                [
                    sys.executable,
                    str(BIN / "export_dataset_family_atlas.py"),
                    "--project-root",
                    str(root),
                    "--project-name",
                    "demo",
                    "--metadata",
                    str(metadata),
                    "--stage-limit",
                    "4",
                    "--min-records",
                    "1",
                    "--gcf-category",
                    "mix",
                    "--gcf-threshold",
                    "0.3",
                ]
            )
            atlas = read_tsv(summary / "family_atlas_shortlist.tsv")
            self.assertEqual(
                {row["gcf_selected_id"] for row in atlas},
                {"MIX_SHARED", "MIX_C", "MIX_D"},
            )
            self.assertTrue(
                all("NRPS_ALIAS_COMMON" not in row["shared_cc_all_family_aliases"] for row in atlas)
            )
            self.assertTrue(
                all(row["gcf_selected_category"] == "mix" for row in atlas)
            )

            self.run_checked(
                [
                    sys.executable,
                    str(BIN / "stage_clinker_panels.py"),
                    "--project-root",
                    str(root),
                    "--repo-root",
                    str(REPO_ROOT),
                    "--project-name",
                    "demo",
                    "--genome",
                    "A",
                    "--shortlist",
                    str(summary / "priority_shortlist.tsv"),
                    "--ranking",
                    str(ranking_path),
                    "--bucket",
                    "clinker_now",
                    "--limit",
                    "1",
                    "--max-same-ecology",
                    "3",
                    "--max-other-ecology",
                    "0",
                    "--max-comparators",
                    "3",
                ]
            )
            panel_manifests = list(
                (results / "clinker" / "panels").rglob(
                    "panel_manifest.tsv"
                )
            )
            self.assertEqual(len(panel_manifests), 1)
            panel_rows = read_tsv(panel_manifests[0])
            self.assertEqual(
                [(row["role"], row["genome"]) for row in panel_rows],
                [("target", "A"), ("comparator", "B")],
            )
            self.assertEqual(panel_rows[1]["match_type"], "exact_gcf")
            self.assertEqual(panel_rows[1]["gcf_selected_id"], "MIX_SHARED")
            self.assertIn("NRPS_ALIAS_B", panel_rows[1]["gcf_id"])
            self.assertIn(
                "NRPS_ALIAS_B",
                panel_rows[1]["gcf_memberships"],
            )

            module = load_stage_module()
            selected = module.choose_comparators(
                ranking["C"],
                list(ranking.values()),
                results / "antismash",
                max_same_ecology=4,
                max_other_ecology=0,
                max_comparators=4,
            )
            self.assertEqual(selected, [])

            wrapper = (REPO_ROOT / "run_clinker.sh").read_text(
                encoding="utf-8"
            )
            self.assertGreaterEqual(wrapper.count("--gcf-category"), 2)
            self.assertGreaterEqual(wrapper.count("--gcf-threshold"), 2)

    def test_legacy_rows_fall_back_but_explicit_unassigned_never_does(self) -> None:
        module = load_stage_module()
        with tempfile.TemporaryDirectory() as tmp:
            antismash = Path(tmp)
            for genome in ("legacy_a", "legacy_b", "new_unassigned"):
                path = antismash / genome / "region001.gbk"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("LOCUS       region001\n", encoding="utf-8")

            legacy_target = {
                "genome": "legacy_a",
                "antismash_region": "region001",
                "gcf_id": "LEGACY_GCF",
                "ecology_group": "soil",
            }
            legacy_peer = {
                "genome": "legacy_b",
                "antismash_region": "region001",
                "gcf_id": "LEGACY_GCF",
                "ecology_group": "soil",
            }
            explicit_unassigned = {
                "genome": "new_unassigned",
                "antismash_region": "region001",
                "gcf_id": "NONSELECTED_ALIAS",
                "gcf_memberships": "nrps@c0.3=NONSELECTED_ALIAS",
                "gcf_selected_category": "mix",
                "gcf_selected_threshold": "0.3",
                "gcf_selected_id": "",
                "gcf_selected_status": "unassigned",
                "ecology_group": "soil",
            }
            selected = module.choose_comparators(
                legacy_target,
                [legacy_target, legacy_peer, explicit_unassigned],
                antismash,
                max_same_ecology=3,
                max_other_ecology=0,
                max_comparators=3,
            )
            self.assertEqual(
                [(row["genome"], row["match_type"]) for row in selected],
                [("legacy_b", "exact_gcf")],
            )


if __name__ == "__main__":
    unittest.main()
