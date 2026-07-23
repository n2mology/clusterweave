import csv
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class TaxonSummarySemanticsTests(unittest.TestCase):
    def test_bacterial_antismash_calls_are_not_reported_as_unshared_funbgcex_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = "demo"
            results = root / "data" / "results" / project
            antismash = results / "antismash" / "bacteria_demo"
            summary_tables = results / "summary_tables"
            antismash.mkdir(parents=True)
            summary_tables.mkdir(parents=True)

            (antismash / "bacteria_demo.antismash.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "id": "stale_contig",
                                "areas": [
                                    {
                                        "start": 0,
                                        "end": 500,
                                        "products": ["T1PKS"],
                                        "protoclusters": {},
                                    }
                                ],
                                "modules": {},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (antismash / "bacteria_demo.bacteria.antismash.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "id": "bacteria_demo_NC_000001",
                                "areas": [
                                    {
                                        "start": 0,
                                        "end": 1000,
                                        "products": ["NRPS-like"],
                                        "protoclusters": {},
                                    }
                                ],
                                "modules": {},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (summary_tables / "genome_taxon_manifest.tsv").write_text(
                "genome_id\ttaxon_group\tprediction_method\tdetector_profile\n"
                "bacteria_demo\tbacteria\tprodigal\tantismash\n",
                encoding="utf-8",
            )
            stub = root / "stub.py"
            stub.write_text("raise SystemExit(0)\n", encoding="utf-8")

            env = os.environ.copy()
            env.update(
                {
                    "PROJECT_DIR": str(REPO_ROOT),
                    "PROJECTS_ROOT": str(root),
                    "DATA_ROOT": str(root / "data"),
                    "RESULTS_ROOT": str(results),
                    "PROJECT_NAME": project,
                    "BGC_GCF_CROSSWALK_PY": str(stub),
                    "TARGETED_ANALYSIS_PY": str(stub),
                    "RUN_ECOLOGY_ANALYSIS": "0",
                }
            )
            subprocess.run(
                ["bash", str(REPO_ROOT / "summarize_clusterweave.sh")],
                cwd=REPO_ROOT,
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            with (results / "summary" / "all_tools_shared_unshared_summary.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                rows = list(csv.DictReader(handle))
            bgc_row = next(row for row in rows if row["entity_type"] == "BGC")
            self.assertEqual(bgc_row["taxon_group"], "bacteria")
            self.assertEqual(bgc_row["comparison_applicability"], "not_applicable_taxon")
            self.assertEqual(bgc_row["shared_count"], "0")
            self.assertEqual(bgc_row["unshared_count"], "0")
            self.assertEqual(bgc_row["not_applicable_count"], "1")
            self.assertEqual(bgc_row["total"], "1")

            with (results / "summary" / "all_tools_bgc_comparison.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                comparison = list(csv.DictReader(handle))
            self.assertNotIn("prediction_method", comparison[0])
            self.assertNotIn("funbgcex_applicability", comparison[0])
            self.assertEqual(comparison[0]["genome"], "bacteria_demo")
            self.assertEqual(comparison[0]["scaffold"], "bacteria_demo_NC_000001")
            self.assertEqual(
                comparison[0]["antismash_bgc_id"], "bacteria_demo_NC_000001.region001"
            )
            self.assertEqual(comparison[0]["detector_relation"], "antismash_only")

            with (summary_tables / "antismash_product_types_exact.tsv").open(
                newline="", encoding="utf-8"
            ) as handle:
                exact = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(exact), 1)
            self.assertEqual(exact[0]["exact_product_type"], "NRPS-like")
            self.assertEqual(exact[0]["display_ontology_version"], "clusterweave-bgc-broad-v1")

    def test_fungal_canonical_antismash_json_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = "fungal_demo"
            results = root / "data" / "results" / project
            antismash = results / "antismash" / "Fungus_demo"
            summary_tables = results / "summary_tables"
            antismash.mkdir(parents=True)
            summary_tables.mkdir(parents=True)

            (antismash / "Fungus_demo.antismash.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "id": "contig1",
                                "areas": [
                                    {
                                        "start": 0,
                                        "end": 1000,
                                        "products": ["T1PKS"],
                                        "protoclusters": {},
                                    }
                                ],
                                "modules": {},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (summary_tables / "genome_taxon_manifest.tsv").write_text(
                "genome_id\ttaxon_group\tprediction_method\tdetector_profile\n"
                "Fungus_demo\tfungi\tfunannotate\tantismash+funbgcex\n",
                encoding="utf-8",
            )
            stub = root / "stub.py"
            stub.write_text("raise SystemExit(0)\n", encoding="utf-8")

            env = os.environ.copy()
            env.update(
                {
                    "PROJECT_DIR": str(REPO_ROOT),
                    "PROJECTS_ROOT": str(root),
                    "DATA_ROOT": str(root / "data"),
                    "RESULTS_ROOT": str(results),
                    "PROJECT_NAME": project,
                    "BGC_GCF_CROSSWALK_PY": str(stub),
                    "TARGETED_ANALYSIS_PY": str(stub),
                    "RUN_ECOLOGY_ANALYSIS": "0",
                }
            )
            subprocess.run(
                ["bash", str(REPO_ROOT / "summarize_clusterweave.sh")],
                cwd=REPO_ROOT,
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            with (summary_tables / "antismash_product_types_exact.tsv").open(
                newline="", encoding="utf-8"
            ) as handle:
                exact = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(exact), 1)
            self.assertEqual(exact[0]["genome"], "Fungus_demo")
            self.assertEqual(exact[0]["taxon_group"], "fungi")
            self.assertEqual(exact[0]["exact_product_type"], "T1PKS")


if __name__ == "__main__":
    unittest.main()
