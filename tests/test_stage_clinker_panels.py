import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "stage_clinker_panels.py"


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


class StageClinkerPanelsTests(unittest.TestCase):
    def test_atlas_staging_skips_exact_and_already_covered_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            results_root = project_root / "data" / "results" / "demo"
            summary_root = results_root / "summary"
            antismash_root = results_root / "antismash"

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
            run_panel = results_root / "clinker" / "panels" / "atlas" / "product_a" / "run_panel.sh"
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
            self.assertFalse((results_root / "clinker" / "panels" / "atlas" / "product_b").exists())
            self.assertFalse((results_root / "clinker" / "panels" / "atlas" / "product_a__region001").exists())


if __name__ == "__main__":
    unittest.main()
