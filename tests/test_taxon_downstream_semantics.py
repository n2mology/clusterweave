import csv
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TaxonDownstreamSemanticsTests(unittest.TestCase):
    def test_bacteria_are_not_scored_as_missing_a_fungal_only_detector(self) -> None:
        module = load_module("candidate_tables_under_test", "bin/build_candidate_tables.py")

        fungal_missing = module.parse_consensus("region001", "", "applicable")
        bacterial_complete = module.parse_consensus(
            "region001", "", "not_applicable_taxon"
        )

        self.assertEqual(fungal_missing, ("antiSMASH-only", 2))
        self.assertEqual(
            bacterial_complete,
            ("antiSMASH (complete applicable detector set)", 4),
        )

    def test_crosswalk_notes_distinguish_not_applicable_from_unshared(self) -> None:
        module = load_module("crosswalk_under_test", "bin/build_bgc_gcf_crosswalk.py")
        notes = module.build_notes(
            {
                "antismash_bgc_id": "region001",
                "funbgcex_bgc_id": "",
                "taxon_group": "bacteria",
            },
            "genome__region001",
            "GCF_1",
            "exact_record",
            1,
        )

        self.assertIn("consensus=applicable-detectors-complete", notes)
        self.assertIn("funbgcex=not_applicable_taxon", notes)
        self.assertNotIn("consensus=antiSMASH-only", notes)

    def test_integrated_ranking_gives_equivalent_complete_detector_sets_tier_parity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            summary = project_root / "data" / "results" / "demo" / "summary"
            summary_tables = (
                project_root / "data" / "results" / "demo" / "summary_tables"
            )
            summary.mkdir(parents=True)
            summary_tables.mkdir(parents=True)

            metadata = summary_tables / "taxonomy_ecology.tsv"
            metadata.write_text(
                "genome_id_current\tecofun_primary\n"
                "Fungus_A\tsoil\n"
                "Bacterium_A\tsoil\n"
                "Fungus_B\tsoil\n"
                "Bacterium_B\tsoil\n",
                encoding="utf-8",
            )
            (summary / "all_tools_shared_unshared_summary.csv").write_text(
                "genome,tool,entity_type,class_norm,shared_count,unshared_count,total\n",
                encoding="utf-8",
            )
            (summary / "candidate_bgc_gcf_crosswalk.tsv").write_text(
                "genome\ttaxon_group\tprediction_method\tfunbgcex_applicability\t"
                "antismash_region\tfunbgcex_cluster\tantismash_class\tgcf_id\t"
                "nearest_mibig_or_annotation_if_available\tnotes\n"
                "Fungus_A\tfungi\texisting_cds\tapplicable\tregion001\tFBG_1\tNRPS\tGCF_1\t\t\n"
                "Bacterium_A\tbacteria\tprodigal\tnot_applicable_taxon\tregion001\t\tNRPS\tGCF_1\t\t\n"
                "Fungus_B\tfungi\tfunannotate\tapplicable\tregion002\tFBG_2\tNRPS\tGCF_1\t\t\n"
                "Bacterium_B\tbacteria\tprodigal\tnot_applicable_taxon\tregion002\t\tNRPS\tGCF_1\t\t\n",
                encoding="utf-8",
            )
            (summary / "all_tools_bgc_comparison.csv").write_text(
                "genome,antismash_bgc_id,funbgcex_bgc_id,funbgcex_applicability,"
                "antismash_knowncluster_similarity_score\n"
                "Fungus_A,region001,FBG_1,applicable,50\n"
                "Bacterium_A,region001,,not_applicable_taxon,50\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "build_candidate_tables.py"),
                    "--project-root",
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--metadata",
                    str(metadata),
                    "--focus-ecology-label",
                    "soil",
                ],
                cwd=REPO_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            with (summary / "targeted_candidate_ranking.tsv").open(
                newline="", encoding="utf-8"
            ) as handle:
                ranked = {
                    (row["genome"], row["antismash_region"]): row
                    for row in csv.DictReader(handle, delimiter="\t")
                }
            fungal = ranked[("Fungus_A", "region001")]
            bacterial = ranked[("Bacterium_A", "region001")]
            self.assertEqual(fungal["priority_score"], "11")
            self.assertEqual(bacterial["priority_score"], "11")
            self.assertEqual(fungal["priority_tier"], "tier_1")
            self.assertEqual(bacterial["priority_tier"], "tier_1")
            self.assertEqual(
                bacterial["consensus_support"],
                "antiSMASH (complete applicable detector set)",
            )

            with (summary / "gcf_ecology_distribution.tsv").open(
                newline="", encoding="utf-8"
            ) as handle:
                gcf_row = next(csv.DictReader(handle, delimiter="\t"))
            self.assertIn(
                "antiSMASH+FunBGCeX:2", gcf_row["consensus_profile"]
            )
            self.assertIn(
                "antiSMASH (complete applicable detector set):2",
                gcf_row["consensus_profile"],
            )
            self.assertNotIn(
                "antiSMASH-only", gcf_row["consensus_profile"]
            )


if __name__ == "__main__":
    unittest.main()
