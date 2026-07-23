import csv
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_rows(
    path: Path,
    fields: list[str],
    rows: list[dict[str, str]],
    *,
    delimiter: str = "\t",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter=delimiter,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


class ZeroRegionDownstreamTests(unittest.TestCase):
    def test_clinker_emits_empty_manifests_from_explicit_ecobac_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            results = project_root / "data" / "results" / "demo"
            summary = results / "summary"
            summary_tables = results / "summary_tables"
            (results / "big_scape" / "output_files").mkdir(parents=True)
            (results / "antismash").mkdir()

            metadata = summary_tables / "ecobac_metadata_normalized.tsv"
            write_rows(
                metadata,
                [
                    "accession",
                    "genome_id_current",
                    "taxid",
                    "organism_name",
                    "ecobac_primary",
                    "ecobac_secondary",
                ],
                [
                    {
                        "accession": "GCA_000000001.1",
                        "genome_id_current": "Bac1",
                        "taxid": "1",
                        "organism_name": "Bacterium fixture",
                        "ecobac_primary": "soil",
                        "ecobac_secondary": "",
                    }
                ],
            )
            write_rows(
                summary / "all_tools_shared_unshared_summary.csv",
                [
                    "genome",
                    "taxon_group",
                    "tool",
                    "entity_type",
                    "class_norm",
                    "comparison_applicability",
                    "shared_count",
                    "unshared_count",
                    "not_applicable_count",
                    "total",
                ],
                [],
                delimiter=",",
            )
            write_rows(
                summary / "candidate_bgc_gcf_crosswalk.tsv",
                [
                    "genome",
                    "taxon_group",
                    "prediction_method",
                    "funbgcex_applicability",
                    "antismash_region",
                    "funbgcex_cluster",
                    "antismash_class",
                    "gcf_id",
                    "nearest_mibig_or_annotation_if_available",
                    "notes",
                ],
                [],
            )
            write_rows(
                summary / "all_tools_bgc_comparison.csv",
                [
                    "genome",
                    "taxon_group",
                    "prediction_method",
                    "funbgcex_applicability",
                    "antismash_bgc_id",
                    "funbgcex_bgc_id",
                ],
                [],
                delimiter=",",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PROJECT_DIR": str(REPO_ROOT),
                    "PROJECTS_ROOT": str(project_root),
                    "PROJECT_NAME": "demo",
                    "DATA_ROOT": str(project_root / "data"),
                    "RESULTS_ROOT": str(results),
                    "SUMMARY_ROOT": str(summary),
                    "ANALYSIS_SCOPE": "bacteria",
                    "METADATA_TSV": str(metadata),
                    "ECOLOGY_FIELD": "ecobac_primary",
                    "TARGET_GENOME": "Bac1",
                    "CLINKER_MODE": "both",
                    "PANEL_TARGET_SET": "both",
                    "AUTO_NORMALIZE_METADATA": "0",
                    "RUN_CLINKER": "0",
                }
            )
            completed = subprocess.run(
                ["bash", str(REPO_ROOT / "run_clinker.sh")],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("run_clinker.sh complete", completed.stdout)
            self.assertFalse(
                (summary_tables / "ecofun_metadata_normalized.tsv").exists()
            )
            for path in [
                summary / "targeted_candidate_ranking.tsv",
                summary / "priority_shortlist.tsv",
                summary / "bigscape_family_atlas.tsv",
                summary / "family_atlas_shortlist.tsv",
                summary / "bigscape_most_shared_ccs.tsv",
                summary / "shared_family_shortlist.tsv",
                results / "clinker" / "panels_manifest.atlas.tsv",
                results / "clinker" / "panels_manifest.priority.tsv",
                results / "clinker" / "panels_manifest.shared_family.tsv",
                results / "clinker" / "panels_manifest.tsv",
                results / "clinker" / "run_all_clinker_panels.sh",
            ]:
                self.assertTrue(path.is_file(), path)

    def test_zero_clustering_clears_stale_network_and_reaches_core_figures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            summary = results / "summary"
            summary_tables = results / "summary_tables"
            figures = results / "figures"
            phylogeny = figures / "phylogeny"
            (results / "big_scape" / "output_files").mkdir(parents=True)
            figures.mkdir(parents=True)

            manifest = summary_tables / "genome_taxon_manifest.tsv"
            exact = summary_tables / "antismash_product_types_exact.tsv"
            crosswalk = summary / "candidate_bgc_gcf_crosswalk.tsv"
            comparison = summary / "all_tools_bgc_comparison.csv"
            totals = summary / "all_tools_shared_unshared_summary.csv"
            taxonomy = summary_tables / "taxonomy_metadata_normalized.tsv"
            write_rows(
                manifest,
                [
                    "genome_id",
                    "taxon_group",
                    "taxon_source",
                    "taxid",
                    "organism_name",
                    "source_accession",
                    "prediction_method",
                    "detector_profile",
                    "route_status",
                ],
                [
                    {
                        "genome_id": "Bac1",
                        "taxon_group": "bacteria",
                        "taxon_source": "ncbi",
                        "taxid": "1",
                        "organism_name": "Bacterium fixture",
                        "source_accession": "GCA_000000001.1",
                        "prediction_method": "prodigal",
                        "detector_profile": "antismash",
                        "route_status": "routed",
                    }
                ],
            )
            write_rows(
                taxonomy,
                [
                    "genome_id",
                    "taxon_group",
                    "taxid",
                    "organism_name",
                    "lineage_superkingdom",
                    "lineage_phylum",
                ],
                [
                    {
                        "genome_id": "Bac1",
                        "taxon_group": "bacteria",
                        "taxid": "1",
                        "organism_name": "Bacterium fixture",
                        "lineage_superkingdom": "Bacteria",
                        "lineage_phylum": "Fixtureota",
                    }
                ],
            )
            write_rows(
                exact,
                [
                    "genome",
                    "taxon_group",
                    "bgc_id",
                    "exact_product_type",
                    "broad_display_class",
                ],
                [],
            )
            write_rows(
                crosswalk,
                ["genome", "taxon_group", "antismash_region", "gcf_id"],
                [],
            )
            write_rows(
                comparison,
                [
                    "genome",
                    "antismash_bgc_id",
                    "antismash_knowncluster_accession",
                    "antismash_knowncluster_product",
                    "antismash_clustercompare_compounds",
                ],
                [],
                delimiter=",",
            )
            write_rows(
                totals,
                ["genome", "taxon_group", "entity_type", "tool", "total"],
                [],
                delimiter=",",
            )
            stale = [
                figures / "bigscape_network.graphml",
                figures / "bigscape_network_node_attributes.tsv",
                figures / "big_scape_multipanel.svg",
                figures / "fungi_big_scape_multipanel.svg",
                figures / "bacteria_big_scape_multipanel.svg",
            ]
            for path in stale:
                path.write_text("stale\n", encoding="utf-8")

            env = os.environ.copy()
            env.update(
                {
                    "PROJECT_DIR": str(REPO_ROOT),
                    "PROJECT_NAME": "demo",
                    "RESULTS_ROOT": str(results),
                    "SUMMARY_TABLE": str(totals),
                    "GENOME_TAXON_MANIFEST": str(manifest),
                    "BACTERIAL_EXACT_PRODUCTS_TSV": str(exact),
                    "BACTERIAL_COMPARISON_CSV": str(comparison),
                    "BACTERIAL_CROSSWALK_TSV": str(crosswalk),
                    "TAXONOMY_METADATA_TSV": str(taxonomy),
                    "TAXON_TREE_OUTPUT_DIR": str(phylogeny),
                    "BIGSCAPE_OUTPUT_FILES": str(
                        results / "big_scape" / "output_files"
                    ),
                    "BIGSCAPE_NETWORK_OUTPUT_DIR": str(figures),
                    "ANALYSIS_SCOPE": "bacteria",
                    "RUN_SUMMARY_FIGURES": "0",
                    "RUN_BGC_OVERLAP_FIGURE": "0",
                    "RUN_BIGSCAPE_NETWORK_FIGURE": "1",
                    "RUN_BIGSCAPE_MULTIPANEL_FIGURE": "1",
                    "RUN_TAXON_TREE_FIGURE": "1",
                    "TAXON_TREE_REQUIRED": "1",
                }
            )
            completed = subprocess.run(
                ["bash", str(REPO_ROOT / "run_figures.sh")],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(
                "BIGSCAPE_FIGURE_RESULT status=insufficient_data families=0",
                completed.stdout,
            )
            for path in stale:
                self.assertFalse(path.exists(), path)
            self.assertFalse((figures / "bacteria_big_scape_multipanel.svg").exists())
            self.assertTrue((phylogeny / "clusterweave_taxon_tree.svg").is_file())
            self.assertTrue((phylogeny / "clusterweave_tree_bundle.zip").is_file())
            self.assertIn(
                "No shared GCF links",
                (phylogeny / "clusterweave_taxon_tree.svg").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
