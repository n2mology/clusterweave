from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER = REPO_ROOT / "bin" / "build_cross_kingdom_evidence.py"
OUTPUT_NAMES = (
    "cross_kingdom_evidence.tsv",
    "cross_kingdom_evidence.json",
    "cross_kingdom_evidence_cards.txt",
)


class CrossKingdomEvidenceTests(unittest.TestCase):
    def make_workspace(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Path(temp.name)

    def write_candidates(self, path: Path, rows: list[dict[str, str]]) -> None:
        fieldnames: list[str] = []
        for row in rows:
            for field in row:
                if field not in fieldnames:
                    fieldnames.append(field)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def run_builder(
        self,
        candidates: Path,
        output_dir: Path,
        *,
        explicit: bool = True,
        max_candidates: int = 25,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(BUILDER)]
        if explicit:
            command.append("--explicit-request")
        command.extend(
            [
                "--candidates",
                str(candidates),
                "--output-dir",
                str(output_dir),
                "--max-candidates",
                str(max_candidates),
            ]
        )
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def read_output_tsv(self, output_dir: Path) -> list[dict[str, str]]:
        with (output_dir / OUTPUT_NAMES[0]).open("r", newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    def test_explicit_request_is_required_and_cross_domain_context_alone_is_exploratory(self) -> None:
        root = self.make_workspace()
        candidates = root / "candidates.tsv"
        row = {
            "candidate_id": "candidate-one",
            "gcf_id": "GCF_001",
            "cross_domain_gcf": "yes",
            "taxon_groups": "fungi;bacteria",
            "candidate_label": "bounded public candidate",
        }
        self.write_candidates(candidates, [row])

        implicit_output = root / "implicit"
        implicit = self.run_builder(candidates, implicit_output, explicit=False)
        self.assertNotEqual(implicit.returncode, 0)
        self.assertIn("--explicit-request is required", implicit.stderr)
        self.assertFalse(implicit_output.exists())

        output = root / "explicit"
        completed = self.run_builder(candidates, output)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual({path.name for path in output.iterdir()}, set(OUTPUT_NAMES))

        payload = json.loads((output / OUTPUT_NAMES[1]).read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "clusterweave-cross-kingdom-evidence-v1")
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["confidence_vocabulary"], ["exploratory", "supportive", "strong"])
        record = payload["records"][0]
        self.assertEqual(record["input"], row)
        self.assertEqual(record["confidence"], "exploratory")
        self.assertEqual(record["independent_signal_count"], 0)
        self.assertEqual(record["independent_signals"], [])
        self.assertFalse(record["supported_topology_discordance"])

        output_row = self.read_output_tsv(output)[0]
        for field, value in row.items():
            self.assertEqual(output_row[field], value)
        self.assertEqual(output_row["confidence"], "exploratory")
        self.assertTrue(output_row["evidence_id"].startswith("cke-candidate-one-"))

        public_text = "\n".join(path.read_text(encoding="utf-8") for path in sorted(output.iterdir()))
        self.assertIn("shared computational family context", public_text)
        self.assertIn(
            "Computational context does not establish an evolutionary event, mechanism, or direction.",
            public_text,
        )
        self.assertNotIn("putative-transfer", public_text)
        for caveat in (
            "contamination",
            "paralogy",
            "incomplete sampling",
            "conserved enzymes",
            "long-branch attraction",
            "assembly fragmentation",
        ):
            self.assertIn(caveat, public_text)
        self.assertNotIn("confirmed", public_text.casefold())

    def test_outputs_and_ids_are_deterministic_and_sorted(self) -> None:
        root = self.make_workspace()
        candidates = root / "candidates.tsv"
        rows = [
            {
                "candidate_id": "zeta-candidate",
                "gcf_id": "GCF_Z",
                "cross_domain_gcf": "true",
                "taxon_groups": "bacteria;fungi",
                "synteny_support": "supported",
            },
            {
                "candidate_id": "alpha-candidate",
                "gcf_id": "GCF_A",
                "cross_domain_gcf": "true",
                "taxon_groups": "fungi;bacteria",
                "mobile_element_context": "present",
            },
        ]
        self.write_candidates(candidates, rows)

        first = root / "first"
        second = root / "second"
        first_run = self.run_builder(candidates, first)
        second_run = self.run_builder(candidates, second)
        self.assertEqual(first_run.returncode, 0, first_run.stderr)
        self.assertEqual(second_run.returncode, 0, second_run.stderr)
        for name in OUTPUT_NAMES:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)

        payload = json.loads((first / OUTPUT_NAMES[1]).read_text(encoding="utf-8"))
        self.assertEqual([record["input"]["gcf_id"] for record in payload["records"]], ["GCF_A", "GCF_Z"])
        ids = [record["evidence_id"] for record in payload["records"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_strong_requires_supported_topology_passed_checks_and_multiple_signals(self) -> None:
        root = self.make_workspace()
        candidates = root / "candidates.tsv"
        common = {
            "cross_domain_gcf": "yes",
            "taxon_groups": "fungi;bacteria",
            "synteny_gene_order_matches": "8",
            "synteny_gene_count": "10",
            "characterized_reference_id": "BGC0000123",
            "characterized_reference_similarity_percent": "82",
            "mobile_element_context": "present",
            "composition_outlier": "yes",
            "assembly_check": "passed",
            "paralogy_check": "passed",
            "sampling_check": "adequate",
            "conserved_enzyme_risk": "no",
            "long_branch_attraction_risk": "no",
        }
        rows = [
            {
                **common,
                "candidate_id": "no-topology",
                "gcf_id": "GCF_A",
                "contamination_check": "passed",
                "topology_discordance": "not_supported",
                "topology_support": "95",
            },
            {
                **common,
                "candidate_id": "no-contamination-pass",
                "gcf_id": "GCF_B",
                "contamination_check": "not_run",
                "family_tree_id": "TREE_B",
                "topology_discordance": "yes",
                "topology_support": "95",
                "topology_support_method": "ultrafast bootstrap",
            },
            {
                **common,
                "candidate_id": "strong-candidate",
                "gcf_id": "GCF_C",
                "contamination_check": "passed",
                "family_tree_id": "TREE_C",
                "topology_discordance": "yes",
                "topology_support": "95",
                "topology_support_method": "ultrafast bootstrap",
            },
            {
                **common,
                "candidate_id": "contamination-concern",
                "gcf_id": "GCF_D",
                "contamination_check": "concern",
                "family_tree_id": "TREE_D",
                "topology_discordance": "supported",
                "topology_support": "95",
            },
        ]
        self.write_candidates(candidates, rows)
        output = root / "output"
        completed = self.run_builder(candidates, output)
        self.assertEqual(completed.returncode, 0, completed.stderr)

        payload = json.loads((output / OUTPUT_NAMES[1]).read_text(encoding="utf-8"))
        by_candidate = {record["input"]["candidate_id"]: record for record in payload["records"]}
        self.assertEqual(by_candidate["no-topology"]["confidence"], "supportive")
        self.assertFalse(by_candidate["no-topology"]["supported_topology_discordance"])
        self.assertEqual(by_candidate["no-contamination-pass"]["confidence"], "supportive")
        self.assertTrue(by_candidate["no-contamination-pass"]["supported_topology_discordance"])
        self.assertEqual(by_candidate["strong-candidate"]["confidence"], "strong")
        self.assertGreaterEqual(by_candidate["strong-candidate"]["independent_signal_count"], 3)
        self.assertEqual(by_candidate["strong-candidate"]["contamination_interpretation"], "passed")
        self.assertEqual(by_candidate["strong-candidate"]["assembly_interpretation"], "passed")
        self.assertEqual(by_candidate["strong-candidate"]["input"]["family_tree_id"], "TREE_C")
        self.assertEqual(by_candidate["contamination-concern"]["confidence"], "exploratory")

    def test_strong_is_blocked_when_any_required_confounder_is_not_tested(self) -> None:
        root = self.make_workspace()
        candidates = root / "candidates.tsv"
        baseline = {
            "cross_domain_gcf": "yes",
            "taxon_groups": "fungi;bacteria",
            "synteny_support": "yes",
            "characterized_reference_support": "yes",
            "characterized_reference_id": "BGC0000123",
            "topology_discordance": "supported",
            "topology_support": "95",
            "mobile_element_context": "present",
            "contamination_check": "passed",
            "assembly_check": "passed",
            "paralogy_check": "passed",
            "sampling_check": "passed",
            "conserved_enzyme_risk": "no",
            "long_branch_attraction_risk": "no",
        }
        confounders = (
            "contamination_check",
            "assembly_check",
            "paralogy_check",
            "sampling_check",
            "conserved_enzyme_risk",
            "long_branch_attraction_risk",
        )
        rows = []
        for index, field in enumerate(confounders):
            row = dict(baseline)
            row.update(
                {
                    "candidate_id": f"unknown-{index}",
                    "gcf_id": f"GCF_UNKNOWN_{index}",
                    field: "not_tested",
                }
            )
            rows.append(row)
        self.write_candidates(candidates, rows)

        output = root / "output"
        completed = self.run_builder(candidates, output)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output / OUTPUT_NAMES[1]).read_text(encoding="utf-8"))
        by_candidate = {
            record["input"]["candidate_id"]: record for record in payload["records"]
        }
        for index, field in enumerate(confounders):
            with self.subTest(confounder=field):
                record = by_candidate[f"unknown-{index}"]
                self.assertEqual(record["confidence"], "supportive")
                self.assertNotEqual(record["confidence"], "strong")

    def test_edge_concerns_and_named_conserved_families_dominate_conflicting_passes(self) -> None:
        root = self.make_workspace()
        candidates = root / "candidates.tsv"
        baseline = {
            "cross_domain_gcf": "yes",
            "taxon_groups": "fungi;bacteria",
            "synteny_support": "yes",
            "characterized_reference_support": "yes",
            "characterized_reference_id": "BGC0000123",
            "topology_discordance": "supported",
            "topology_support": "95",
            "mobile_element_context": "present",
            "contamination_check": "passed",
            "assembly_check": "passed",
            "paralogy_check": "passed",
            "sampling_check": "passed",
            "conserved_enzyme_risk": "no",
            "long_branch_attraction_risk": "no",
        }
        self.write_candidates(
            candidates,
            [
                {
                    **baseline,
                    "candidate_id": "edge-conflict",
                    "gcf_id": "GCF_EDGE",
                    "assembly_region_edge_context": "concern",
                },
                {
                    **baseline,
                    "candidate_id": "enzyme-conflict",
                    "gcf_id": "GCF_ENZYME",
                    "conserved_enzyme_family": "PF00001",
                },
            ],
        )

        output = root / "output"
        completed = self.run_builder(candidates, output)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output / OUTPUT_NAMES[1]).read_text(encoding="utf-8"))
        by_candidate = {
            record["input"]["candidate_id"]: record for record in payload["records"]
        }
        edge = by_candidate["edge-conflict"]
        self.assertEqual(edge["confidence"], "supportive")
        self.assertEqual(edge["assembly_interpretation"], "concern")
        self.assertNotEqual(edge["confidence"], "strong")
        enzyme = by_candidate["enzyme-conflict"]
        self.assertEqual(enzyme["confidence"], "supportive")
        self.assertEqual(
            enzyme["quality_context"]["conserved_enzyme_risk"], "present"
        )
        self.assertNotEqual(enzyme["confidence"], "strong")

    def test_fraction_and_percent_fields_have_unambiguous_units_and_aliases(self) -> None:
        root = self.make_workspace()
        candidates = root / "candidates.tsv"
        rows = [
            {
                "candidate_id": "fraction-point-zero-one",
                "gcf_id": "GCF_001",
                "cross_domain_gcf": "yes",
                "characterized_reference_id": "BGC0000001",
                "characterized_reference_similarity": ".01",
                "characterized_reference_similarity_percent": "1",
            },
            {
                "candidate_id": "explicit-one-percent",
                "gcf_id": "GCF_002",
                "cross_domain_gcf": "yes",
                "characterized_reference_id": "BGC0000002",
                "characterized_reference_similarity": "1%",
                "characterized_reference_similarity_percent": "1",
            },
            {
                "candidate_id": "fraction-one",
                "gcf_id": "GCF_003",
                "cross_domain_gcf": "yes",
                "characterized_reference_id": "BGC0000003",
                "characterized_reference_similarity": "1",
            },
            {
                "candidate_id": "half-aliases",
                "gcf_id": "GCF_004",
                "cross_domain_gcf": "yes",
                "characterized_reference_id": "BGC0000004",
                "characterized_reference_similarity": "0.5",
                "characterized_reference_similarity_percent": "50",
            },
        ]
        self.write_candidates(candidates, rows)

        output = root / "output"
        completed = self.run_builder(candidates, output)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output / OUTPUT_NAMES[1]).read_text(encoding="utf-8"))
        by_candidate = {
            record["input"]["candidate_id"]: record for record in payload["records"]
        }
        self.assertEqual(
            by_candidate["fraction-point-zero-one"]["independent_signals"], []
        )
        self.assertEqual(
            by_candidate["explicit-one-percent"]["independent_signals"], []
        )
        self.assertEqual(
            by_candidate["fraction-one"]["independent_signals"],
            ["characterized_reference"],
        )
        self.assertEqual(
            by_candidate["half-aliases"]["independent_signals"],
            ["characterized_reference"],
        )
        self.assertIn("100% similarity", by_candidate["fraction-one"]["evidence_summary"])
        self.assertIn("50% similarity", by_candidate["half-aliases"]["evidence_summary"])

    def test_knownclusterblast_metric_is_labeled_as_reference_gene_match_coverage(self) -> None:
        root = self.make_workspace()
        candidates = root / "candidates.tsv"
        self.write_candidates(
            candidates,
            [
                {
                    "candidate_id": "knownclusterblast",
                    "gcf_id": "GCF_KCB",
                    "cross_domain_gcf": "yes",
                    "characterized_reference_support": "yes",
                    "characterized_reference_id": "BGC0000123",
                    "characterized_reference_similarity_percent": "82",
                    "characterized_reference_method": "antiSMASH_KnownClusterBlast_reference_gene_match_coverage",
                }
            ],
        )

        output = root / "output"
        completed = self.run_builder(candidates, output)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        record = json.loads((output / OUTPUT_NAMES[1]).read_text(encoding="utf-8"))[
            "records"
        ][0]
        self.assertIn("82% reference-gene match coverage", record["evidence_summary"])
        self.assertNotIn("82% similarity", record["evidence_summary"])

    def test_candidate_tsv_symlink_is_rejected_and_composition_deviation_alias_is_valid(self) -> None:
        root = self.make_workspace()
        candidates = root / "candidates.tsv"
        self.write_candidates(
            candidates,
            [
                {
                    "candidate_id": "composition-alias",
                    "gcf_id": "GCF_COMPOSITION",
                    "cross_domain_gcf": "yes",
                    "composition_deviation": "yes",
                }
            ],
        )
        symlink = root / "candidate-link.tsv"
        symlink.symlink_to(candidates)
        rejected_output = root / "rejected"
        rejected = self.run_builder(symlink, rejected_output)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("non-symlink regular file", rejected.stderr)
        self.assertFalse(rejected_output.exists())

        output = root / "output"
        completed = self.run_builder(candidates, output)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        record = json.loads((output / OUTPUT_NAMES[1]).read_text(encoding="utf-8"))[
            "records"
        ][0]
        self.assertEqual(
            record["independent_signals"], ["mobile_or_composition_context"]
        )
        self.assertIn("GC-composition deviation heuristic", record["evidence_summary"])

    def test_candidate_count_and_json_are_hard_bounded(self) -> None:
        root = self.make_workspace()
        candidates = root / "candidates.tsv"
        self.write_candidates(
            candidates,
            [
                {
                    "candidate_id": f"candidate-{index}",
                    "gcf_id": f"GCF_{index:03d}",
                    "cross_domain_gcf": "yes",
                }
                for index in range(2)
            ],
        )

        too_many_output = root / "too-many"
        too_many = self.run_builder(candidates, too_many_output, max_candidates=1)
        self.assertNotEqual(too_many.returncode, 0)
        self.assertIn("more than the explicit --max-candidates bound", too_many.stderr)
        self.assertFalse(too_many_output.exists())

        above_hard_output = root / "above-hard"
        above_hard = self.run_builder(candidates, above_hard_output, max_candidates=101)
        self.assertNotEqual(above_hard.returncode, 0)
        self.assertIn("between 1 and 100", above_hard.stderr)
        self.assertFalse(above_hard_output.exists())

    def test_public_artifacts_reject_unsafe_fields_values_and_definitive_claims(self) -> None:
        unsafe_cases = [
            ("raw-sequence-column", {"raw_sequence": "ACGT"}),
            ("secret-column", {"secret_token": "redacted"}),
            ("path-column", {"result_path": "relative/value"}),
            ("unknown-column", {"unreviewed_note": "seemingly harmless"}),
            ("absolute-path", {"candidate_label": "/home/private/results/file.tsv"}),
            ("relative-path", {"candidate_label": "private/results.tsv"}),
            ("secret-value", {"candidate_label": "Bearer abcdefghijklmnop"}),
            ("credential-shape", {"candidate_label": "sk-" + "x" * 24}),
            ("raw-sequence-value", {"candidate_label": "ACGT" * 30}),
            ("definitive-claim", {"candidate_label": "confirmed HGT candidate"}),
            (
                "definitive-spelled-out-claim",
                {"candidate_label": "proven horizontal gene transfer candidate"},
            ),
        ]
        for name, unsafe in unsafe_cases:
            with self.subTest(case=name):
                root = self.make_workspace()
                candidates = root / "candidates.tsv"
                row = {"gcf_id": "GCF_001", "cross_domain_gcf": "yes", **unsafe}
                self.write_candidates(candidates, [row])
                output = root / "output"
                completed = self.run_builder(candidates, output)
                self.assertNotEqual(completed.returncode, 0)
                self.assertFalse(output.exists())

    def test_builder_has_no_download_or_install_surface(self) -> None:
        text = BUILDER.read_text(encoding="utf-8")
        for forbidden in (
            "import requests",
            "import urllib",
            "import subprocess",
            "pip install",
            "docker pull",
            "curl ",
            "wget ",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
