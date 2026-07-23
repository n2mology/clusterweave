import csv
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "stage_clinker_panels.py"


def load_module():
    spec = importlib.util.spec_from_file_location("stage_clinker_panels_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


class StageClinkerPanelsTests(unittest.TestCase):
    def test_compound_slug_collision_uses_selected_gcf_not_region(self) -> None:
        module = load_module()
        shared = {
            "antismash_knowncluster_product": "BGC0002161.2 | scytalone/T3HN",
            "gcf_selected_category": "mix",
            "gcf_selected_threshold": "0.3",
            "gcf_selected_status": "assigned",
        }
        acephala = {
            **shared,
            "genome": "Acephala_macrosclerotiorum_EW76-UTF0540",
            "antismash_region": "MU119278.1.region001",
            "gcf_selected_id": "FAM_00004",
            "gcf_id": "FAM_00004;FAM_00210",
        }
        boeremia = {
            **shared,
            "genome": "Boeremia_exigua_MPI-SDFR-AT-0100",
            "antismash_region": "JAHBNH010000004.1.region001",
            "gcf_selected_id": "FAM_00001",
            "gcf_id": "FAM_00001;FAM_00209",
        }

        used_names: set[str] = set()
        acephala_id = module.panel_dir_name(acephala, used_names)
        boeremia_id = module.panel_dir_name(boeremia, used_names)

        self.assertEqual(acephala_id, "scytalone_t3hn")
        self.assertEqual(
            boeremia_id,
            "scytalone_t3hn__gcf_mix_c0_3_fam_00001",
        )
        self.assertNotIn("jahbnh", boeremia_id)
        self.assertEqual(
            module.panel_display_label(acephala, acephala_id),
            "scytalone/T3HN",
        )
        self.assertEqual(
            module.panel_display_label(boeremia, boeremia_id),
            "scytalone/T3HN [MIX c0.3 FAM_00001]",
        )

    def test_same_region_basename_in_another_genome_remains_a_comparator(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            antismash_root = Path(tmp) / "antismash"
            for genome in ["genome_a", "genome_b"]:
                region = antismash_root / genome / "region001.gbk"
                region.parent.mkdir(parents=True, exist_ok=True)
                region.write_text("LOCUS       region001\n", encoding="utf-8")

            target = {
                "genome": "genome_a",
                "antismash_region": "region001",
                "gcf_id": "GCF_1",
                "ecology_group": "UNLABELED",
            }
            ranking = [
                target,
                {
                    "genome": "genome_b",
                    "antismash_region": "region001",
                    "gcf_id": "GCF_1",
                    "ecology_group": "UNLABELED",
                },
            ]

            selected = module.choose_comparators(
                target,
                ranking,
                antismash_root,
                max_same_ecology=2,
                max_other_ecology=0,
                max_comparators=2,
            )

            self.assertEqual(
                [(row["genome"], row["antismash_region"]) for row in selected],
                [("genome_b", "region001")],
            )

    def test_existing_panel_migration_is_keyed_by_genome_and_region(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            panel_a = project_root / "old" / "genome_a"
            panel_b = project_root / "old" / "genome_b"
            panel_a.mkdir(parents=True)
            panel_b.mkdir(parents=True)
            (panel_a / "panel.html").write_text(
                "genome-a-panel", encoding="utf-8"
            )
            (panel_b / "panel.html").write_text(
                "genome-b-panel", encoding="utf-8"
            )
            manifest = project_root / "existing_panels.tsv"
            write_tsv(
                manifest,
                ["target_genome", "target_region", "panel_dir"],
                [
                    {
                        "target_genome": "genome_a",
                        "target_region": "region001",
                        "panel_dir": str(panel_a),
                    },
                    {
                        "target_genome": "genome_b",
                        "target_region": "region001",
                        "panel_dir": str(panel_b),
                    },
                ],
            )

            existing = module.load_existing_panel_dirs(project_root, [manifest])
            self.assertEqual(
                existing[("genome_a", "region001")], panel_a.resolve()
            )
            self.assertEqual(
                existing[("genome_b", "region001")], panel_b.resolve()
            )
            destination = project_root / "new" / "genome_b"
            module.migrate_existing_panel(
                existing.get(("genome_b", "region001")), destination
            )
            self.assertEqual(
                (destination / "panel.html").read_text(encoding="utf-8"),
                "genome-b-panel",
            )

    def test_candidate_genus_order_uses_canonical_organism_metadata(self) -> None:
        module = load_module()
        target_genus = "Bacillus"
        ecology = "UNLABELED"
        genera = {
            "opaque_target": "Bacillus",
            "misleading_name": "Bacillus",
            "Bacillus_filename": "Pseudomonas",
        }
        same_genus = {
            "genome": "misleading_name",
            "antismash_region": "region001",
            "ecology_group": ecology,
        }
        misleading_prefix = {
            "genome": "Bacillus_filename",
            "antismash_region": "region002",
            "ecology_group": ecology,
        }

        self.assertLess(
            module.candidate_sort_key(same_genus, target_genus, ecology, genera),
            module.candidate_sort_key(misleading_prefix, target_genus, ecology, genera),
        )

    def test_candidate_genus_never_falls_back_to_genome_id_prefix(self) -> None:
        module = load_module()
        ecology = "UNLABELED"
        misleading_prefix = {
            "genome": "Bacillus_filename",
            "antismash_region": "region001",
            "ecology_group": ecology,
        }
        canonical_match = {
            "genome": "opaque_genome_id",
            "antismash_region": "region002",
            "ecology_group": ecology,
        }

        self.assertFalse(hasattr(module, "genome_genus"))
        self.assertEqual(
            module.candidate_sort_key(
                misleading_prefix, "Bacillus", ecology, {}
            )[0],
            1,
        )
        self.assertEqual(
            module.candidate_sort_key(
                canonical_match,
                "BACILLUS",
                ecology,
                {"opaque_genome_id": "bacillus"},
            )[0],
            0,
        )
        self.assertEqual(
            module.candidate_sort_key(
                canonical_match,
                "",
                ecology,
                {"opaque_genome_id": "bacillus"},
            )[0],
            1,
        )

    def test_bacterial_record_map_restores_original_scaffold_id(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            maps = Path(tmp) / "bacterial_record_maps"
            write_tsv(
                maps / "bacteria_Streptomyces_demo.record_map.tsv",
                ["original_record_id", "sanitized_record_id"],
                [{
                    "original_record_id": "NC_010572.1",
                    "sanitized_record_id": (
                        "bacteria_Streptomyces_demo_NC_010572.1"
                    ),
                }],
            )
            original_ids = module.load_original_record_ids(maps)

            self.assertEqual(
                module.panel_scaffold_id(
                    {
                        "genome": "bacteria_Streptomyces_demo",
                        "antismash_region": (
                            "bacteria_Streptomyces_demo_"
                            "NC_010572.1.region009"
                        ),
                    },
                    original_ids,
                ),
                "NC_010572.1",
            )

    def test_atlas_staging_skips_exact_and_already_covered_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            results_root = project_root / "data" / "results" / "demo"
            summary_root = results_root / "summary"
            antismash_root = results_root / "antismash"
            write_tsv(
                results_root / "summary_tables" / "genome_taxon_manifest.tsv",
                ["genome_id", "taxon_group", "taxon_source", "organism_name"],
                [
                    {"genome_id": "genome_a", "taxon_group": "fungi", "taxon_source": "ncbi", "organism_name": "Aspergillus alpha A1"},
                    {"genome_id": "genome_b", "taxon_group": "fungi", "taxon_source": "ncbi", "organism_name": "Aspergillus beta B2"},
                    {"genome_id": "genome_c", "taxon_group": "bacteria", "taxon_source": "ncbi", "organism_name": "Bacillus gamma C3"},
                    {"genome_id": "genome_d", "taxon_group": "bacteria", "taxon_source": "ncbi", "organism_name": "Bacillus delta D4"},
                ],
            )

            for genome, region in [
                ("genome_a", "region001"),
                ("genome_b", "region002"),
                ("genome_c", "region003"),
                ("genome_d", "region004"),
            ]:
                gbk_path = antismash_root / genome / f"{region}.gbk"
                gbk_path.parent.mkdir(parents=True, exist_ok=True)
                gbk_path.write_text(f"LOCUS       {region}\n", encoding="utf-8")

            shortlist_fields = [
                "manual_review_bucket",
                "selection_track",
                "atlas_rank",
                "rank",
                "priority_score",
                "genome",
                "antismash_region",
                "gcf_id",
                "shared_cc_all_family_aliases",
                "ecology_group",
                "antismash_knowncluster_product",
            ]
            write_tsv(
                summary_root / "family_atlas_shortlist.tsv",
                shortlist_fields,
                [
                    {
                        "manual_review_bucket": "atlas_now",
                        "selection_track": "dataset_family_atlas",
                        "atlas_rank": "1",
                        "rank": "1",
                        "priority_score": "10",
                        "genome": "genome_a",
                        "antismash_region": "region001",
                        "gcf_id": "FAM_A",
                        "shared_cc_all_family_aliases": "FAM_A;FAM_B",
                        "ecology_group": "UNLABELED",
                        "antismash_knowncluster_product": "Product A",
                    },
                    {
                        "manual_review_bucket": "atlas_now",
                        "selection_track": "dataset_family_atlas",
                        "atlas_rank": "2",
                        "rank": "2",
                        "priority_score": "9",
                        "genome": "genome_a",
                        "antismash_region": "region001",
                        "gcf_id": "FAM_A",
                        "shared_cc_all_family_aliases": "FAM_A",
                        "ecology_group": "UNLABELED",
                        "antismash_knowncluster_product": "Product A",
                    },
                    {
                        "manual_review_bucket": "atlas_now",
                        "selection_track": "dataset_family_atlas",
                        "atlas_rank": "3",
                        "rank": "3",
                        "priority_score": "8",
                        "genome": "genome_b",
                        "antismash_region": "region002",
                        "gcf_id": "FAM_B",
                        "shared_cc_all_family_aliases": "FAM_B",
                        "ecology_group": "UNLABELED",
                        "antismash_knowncluster_product": "Product B",
                    },
                    {
                        "manual_review_bucket": "atlas_now",
                        "selection_track": "dataset_family_atlas",
                        "atlas_rank": "4",
                        "rank": "4",
                        "priority_score": "7",
                        "genome": "genome_c",
                        "antismash_region": "region003",
                        "gcf_id": "FAM_C",
                        "shared_cc_all_family_aliases": "FAM_C",
                        "ecology_group": "UNLABELED",
                        "antismash_knowncluster_product": "Product C",
                    },
                    {
                        "manual_review_bucket": "atlas_now",
                        "selection_track": "dataset_family_atlas",
                        "atlas_rank": "5",
                        "rank": "5",
                        "priority_score": "6",
                        "genome": "genome_d",
                        "antismash_region": "region004",
                        "gcf_id": "FAM_D",
                        "shared_cc_all_family_aliases": "FAM_D",
                        "ecology_group": "UNLABELED",
                        "antismash_knowncluster_product": "Product D",
                    },
                ],
            )

            ranking_fields = [
                "rank",
                "priority_score",
                "priority_tier",
                "genome",
                "antismash_region",
                "gcf_id",
                "ecology_group",
            ]
            write_tsv(
                summary_root / "targeted_candidate_ranking.tsv",
                ranking_fields,
                [
                    {
                        "rank": "1",
                        "priority_score": "10",
                        "priority_tier": "tier_1",
                        "genome": "genome_a",
                        "antismash_region": "region001",
                        "gcf_id": "FAM_A",
                        "ecology_group": "UNLABELED",
                    },
                    {
                        "rank": "2",
                        "priority_score": "9",
                        "priority_tier": "tier_1",
                        "genome": "genome_b",
                        "antismash_region": "region002",
                        "gcf_id": "FAM_B",
                        "ecology_group": "UNLABELED",
                    },
                    {
                        "rank": "3",
                        "priority_score": "8",
                        "priority_tier": "tier_1",
                        "genome": "genome_c",
                        "antismash_region": "region003",
                        "gcf_id": "FAM_C",
                        "ecology_group": "UNLABELED",
                    },
                    {
                        "rank": "4",
                        "priority_score": "7",
                        "priority_tier": "tier_1",
                        "genome": "genome_d",
                        "antismash_region": "region004",
                        "gcf_id": "FAM_D",
                        "ecology_group": "UNLABELED",
                    },
                ],
            )

            subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--project-root",
                    str(project_root),
                    "--repo-root",
                    str(REPO_ROOT),
                    "--project-name",
                    "demo",
                    "--shortlist",
                    str(summary_root / "family_atlas_shortlist.tsv"),
                    "--ranking",
                    str(summary_root / "targeted_candidate_ranking.tsv"),
                    "--bucket",
                    "atlas_now",
                    "--panels-subdir",
                    "panels/atlas",
                    "--manifest-name",
                    "panels_manifest.atlas.tsv",
                    "--master-script-name",
                    "run_all_clinker_panels.atlas.sh",
                    "--limit",
                    "3",
                    "--max-comparators",
                    "1",
                    "--max-same-ecology",
                    "1",
                    "--max-other-ecology",
                    "0",
                ],
                check=True,
                cwd=REPO_ROOT,
            )

            manifest_path = results_root / "clinker" / "panels_manifest.atlas.tsv"
            with manifest_path.open("r", newline="", encoding="utf-8") as handle:
                manifest_rows = list(csv.DictReader(handle, delimiter="\t"))

            self.assertEqual(
                [row["panel_id"] for row in manifest_rows],
                ["product_a", "product_c", "product_d"],
            )
            self.assertEqual(
                [row["target_region"] for row in manifest_rows],
                ["region001", "region003", "region004"],
            )
            self.assertEqual(
                [row["target_genome"] for row in manifest_rows],
                ["genome_a", "genome_c", "genome_d"],
            )
            self.assertEqual(
                [row["target_taxon"] for row in manifest_rows],
                ["fungi", "bacteria", "bacteria"],
            )
            self.assertEqual(
                [row["target_organism"] for row in manifest_rows],
                ["Aspergillus alpha A1", "Bacillus gamma C3", "Bacillus delta D4"],
            )
            self.assertEqual(
                [row["compound_label"] for row in manifest_rows],
                ["Product A", "Product C", "Product D"],
            )
            self.assertEqual(
                [row["panel_label"] for row in manifest_rows],
                ["Product A", "Product C", "Product D"],
            )
            run_panel = results_root / "clinker" / "panels" / "atlas" / "fungi" / "genome_a" / "product_a" / "run_panel.sh"
            run_panel_text = run_panel.read_text(encoding="utf-8")
            self.assertIn(f"PROJECT_ROOT={project_root.resolve().as_posix()}", run_panel_text)
            self.assertIn(f"REPO_ROOT={REPO_ROOT.resolve().as_posix()}", run_panel_text)
            self.assertIn('POSTPROCESS_PY="${PROJECT_ROOT}/bin/postprocess_clinker_html.py"', run_panel_text)
            self.assertIn(
                'POSTPROCESS_FALLBACK_PY="${REPO_ROOT}/bin/postprocess_clinker_html.py"',
                run_panel_text,
            )
            self.assertIn("resolve_postprocess_py()", run_panel_text)
            self.assertIn("helper not found under ${PROJECT_ROOT}/bin or ${REPO_ROOT}/bin", run_panel_text)
            self.assertIn('DOCKER_ARGS+=(--workdir "${SCRIPT_DIR}")', run_panel_text)
            self.assertIn('docker run "${DOCKER_ARGS[@]}"', run_panel_text)
            self.assertTrue((results_root / "clinker" / "panels" / "atlas" / "bacteria" / "genome_c" / "product_c" / "run_panel.sh").exists())
            self.assertTrue((results_root / "clinker" / "panels" / "atlas" / "bacteria" / "genome_d" / "product_d" / "run_panel.sh").exists())
            self.assertFalse((results_root / "clinker" / "panels" / "atlas" / "fungi" / "genome_b" / "product_b").exists())
            self.assertFalse((results_root / "clinker" / "panels" / "atlas" / "fungi" / "genome_a" / "product_a__region001").exists())


if __name__ == "__main__":
    unittest.main()
