from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "run_integrated_evidence.sh"
PUBLIC_OUTPUT_NAMES = {
    "cross_kingdom_evidence.tsv",
    "cross_kingdom_evidence.json",
    "cross_kingdom_evidence_cards.txt",
}
LEGACY_PUBLIC_OUTPUT_NAMES = {
    "putative_transfer_evidence.tsv",
    "putative_transfer_evidence.json",
    "putative_transfer_evidence_cards.txt",
}


class IntegratedEvidenceRunnerTests(unittest.TestCase):
    def workspace(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def write_candidates(self, path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fields: list[str] = []
        for row in rows:
            for field in row:
                if field not in fields:
                    fields.append(field)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def run_runner(
        self,
        root: Path,
        *,
        requested: bool,
        candidates: Path | None = None,
        max_candidates: int = 25,
        extra_env: dict[str, str] | None = None,
        legacy_keys: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        results = root / "results" / "demo"
        env = os.environ.copy()
        for key in (
            "RUN_CROSS_KINGDOM_EVIDENCE",
            "CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES",
            "CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV",
            "RUN_HGT_EVIDENCE",
            "HGT_EVIDENCE_MAX_CANDIDATES",
            "HGT_EVIDENCE_CANDIDATES_TSV",
        ):
            env.pop(key, None)
        env.update(
            {
                "PROJECT_DIR": str(REPO_ROOT),
                "PROJECT_NAME": "demo",
                "DATA_ROOT": str(root / "data"),
                "RESULTS_ROOT": str(results),
                "WORK_ROOT": str(root / "work"),
            }
        )
        prefix = "HGT_EVIDENCE" if legacy_keys else "CROSS_KINGDOM_EVIDENCE"
        env[f"RUN_{prefix}"] = "1" if requested else "0"
        env[f"{prefix}_MAX_CANDIDATES"] = str(max_candidates)
        if candidates is not None:
            env[f"{prefix}_CANDIDATES_TSV"] = str(candidates)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_not_requested_is_a_true_noop(self) -> None:
        root = self.workspace()
        candidates = root / "safe_candidates.tsv"
        self.write_candidates(candidates, [{"gcf_id": "GCF_001", "cross_domain_gcf": "yes"}])
        completed = self.run_runner(root, requested=False, candidates=candidates)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("phase=not_requested", completed.stdout)
        self.assertFalse((root / "results" / "demo" / "integrated_evidence").exists())
        self.assertFalse((root / "results" / "demo" / "logs" / "cross_kingdom_evidence_run_manifest.json").exists())

    def test_requested_eligible_candidates_publish_exact_bounded_artifacts(self) -> None:
        root = self.workspace()
        candidates = root / "results" / "demo" / "summary" / "candidate_bgc_gcf_crosswalk.tsv"
        evidence_fields = {
            "synteny_gene_order_matches": "8",
            "synteny_gene_count": "10",
            "characterized_reference_id": "BGC0000001",
            "characterized_reference_similarity_percent": "80",
            "family_tree_id": "TREE_001",
            "topology_discordance": "yes",
            "topology_support": "95",
            "mobile_element_context": "present",
            "contamination_check": "passed",
            "assembly_check": "passed",
            "paralogy_check": "passed",
            "sampling_check": "adequate",
            "conserved_enzyme_risk": "no",
            "long_branch_attraction_risk": "no",
        }
        self.write_candidates(
            candidates,
            [
                {
                    "genome": "fungus_1",
                    "taxon_group": "fungi",
                    "gcf_id": "GCF_001",
                    **evidence_fields,
                },
                {
                    "genome": "bacterium_1",
                    "taxon_group": "bacteria",
                    "gcf_id": "GCF_001",
                    **evidence_fields,
                },
            ],
        )
        completed = self.run_runner(root, requested=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("phase=select", completed.stdout)
        self.assertIn("phase=success", completed.stdout)
        self.assertIn(
            "CROSS_KINGDOM_EVIDENCE candidate=GCF_001 status=success evidence_tier=strong",
            completed.stdout,
        )
        self.assertIn(
            "Computational context does not establish an evolutionary event, mechanism, or direction.",
            completed.stdout,
        )

        results = root / "results" / "demo"
        output = results / "integrated_evidence"
        self.assertEqual({path.name for path in output.iterdir()}, PUBLIC_OUTPUT_NAMES)
        payload = json.loads((output / "cross_kingdom_evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["records"][0]["confidence"], "strong")
        selected = results / "summary" / "cross_kingdom_candidates.tsv"
        self.assertTrue(selected.is_file())
        self.assertIn("fungal_member_count", selected.read_text(encoding="utf-8"))
        public_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
        self.assertIn("cross-domain gcf", public_text.casefold())
        self.assertIn(
            "Computational context does not establish an evolutionary event, mechanism, or direction.",
            public_text,
        )
        self.assertNotIn("putative-transfer", public_text)
        self.assertNotIn("confirmed", public_text.casefold())

        status_path = results / "logs" / "cross_kingdom_evidence_run_manifest.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(status["status"], "success")
        self.assertTrue(status["requested"])
        self.assertEqual(status["candidate_count"], 1)
        self.assertEqual(set(status["outputs"]), PUBLIC_OUTPUT_NAMES)
        self.assertEqual(
            status["schema_version"], "clusterweave-cross-kingdom-evidence-run-v1"
        )
        self.assertFalse((output / status_path.name).exists())

    def test_legacy_environment_keys_are_fallback_only(self) -> None:
        root = self.workspace()
        candidates = root / "legacy_candidates.tsv"
        self.write_candidates(
            candidates,
            [{"gcf_id": "GCF_LEGACY", "cross_domain_gcf": "yes"}],
        )
        completed = self.run_runner(
            root,
            requested=True,
            candidates=candidates,
            legacy_keys=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = root / "results" / "demo" / "integrated_evidence"
        self.assertEqual({path.name for path in output.iterdir()}, PUBLIC_OUTPUT_NAMES)
        self.assertTrue((output / "cross_kingdom_evidence.json").is_file())
        self.assertFalse(any((output / name).exists() for name in LEGACY_PUBLIC_OUTPUT_NAMES))

    def test_missing_candidates_is_nonfatal_and_quarantines_stale_public_evidence(self) -> None:
        root = self.workspace()
        results = root / "results" / "demo"
        output = results / "integrated_evidence"
        output.mkdir(parents=True)
        for name in PUBLIC_OUTPUT_NAMES | LEGACY_PUBLIC_OUTPUT_NAMES:
            (output / name).write_text("stale evidence\n", encoding="utf-8")
        missing = root / "does-not-exist.tsv"

        completed = self.run_runner(root, requested=True, candidates=missing)
        self.assertEqual(completed.returncode, 0)
        self.assertIn("phase=insufficient_data", completed.stdout)
        self.assertIn("core outputs remain valid", completed.stderr.casefold())
        self.assertFalse(
            any(
                (output / name).exists()
                for name in PUBLIC_OUTPUT_NAMES | LEGACY_PUBLIC_OUTPUT_NAMES
            )
        )
        previous = root / "work" / "integrated_evidence" / "previous_public"
        self.assertEqual(
            {path.name for path in previous.iterdir()},
            PUBLIC_OUTPUT_NAMES | LEGACY_PUBLIC_OUTPUT_NAMES,
        )

        status_path = results / "logs" / "cross_kingdom_evidence_run_manifest.json"
        status_text = status_path.read_text(encoding="utf-8")
        status = json.loads(status_text)
        self.assertEqual(status["status"], "insufficient_data")
        self.assertEqual(status["outputs"], [])
        self.assertNotIn(str(root), status_text)

    def test_default_selector_with_no_cross_domain_family_emits_no_public_evidence(self) -> None:
        root = self.workspace()
        crosswalk = root / "results" / "demo" / "summary" / "candidate_bgc_gcf_crosswalk.tsv"
        self.write_candidates(
            crosswalk,
            [
                {"genome": "fungus_1", "taxon_group": "fungi", "gcf_id": "GCF_FUNGI"},
                {"genome": "fungus_2", "taxon_group": "fungi", "gcf_id": "GCF_FUNGI"},
                {"genome": "bacterium_1", "taxon_group": "bacteria", "gcf_id": "GCF_BACTERIA"},
            ],
        )
        completed = self.run_runner(root, requested=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("phase=select", completed.stdout)
        self.assertIn("phase=insufficient_data", completed.stdout)
        results = root / "results" / "demo"
        output = results / "integrated_evidence"
        self.assertFalse(any((output / name).exists() for name in PUBLIC_OUTPUT_NAMES))
        status = json.loads(
            (results / "logs" / "cross_kingdom_evidence_run_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(status["status"], "insufficient_data")
        self.assertEqual(status["outputs"], [])

    def test_builder_rejection_and_candidate_bound_never_fail_core(self) -> None:
        root = self.workspace()
        candidates = root / "too_many.tsv"
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
        completed = self.run_runner(root, requested=True, candidates=candidates, max_candidates=1)
        self.assertEqual(completed.returncode, 0)
        self.assertIn("phase=failed", completed.stdout)
        results = root / "results" / "demo"
        status = json.loads(
            (results / "logs" / "cross_kingdom_evidence_run_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["candidate_limit"], 1)
        self.assertEqual(status["outputs"], [])
        output = results / "integrated_evidence"
        self.assertFalse(any((output / name).exists() for name in PUBLIC_OUTPUT_NAMES))

    def test_oversized_candidate_tsv_is_a_nonfatal_optional_failure(self) -> None:
        root = self.workspace()
        candidates = root / "oversized.tsv"
        candidates.write_bytes(
            b"gcf_id\tcross_domain_gcf\tcandidate_label\n"
            b"GCF_001\tyes\t"
            + b"x" * (2 * 1024 * 1024 + 1)
            + b"\n"
        )

        completed = self.run_runner(root, requested=True, candidates=candidates)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("phase=failed", completed.stdout)
        self.assertIn("core outputs remain valid", completed.stderr)
        results = root / "results" / "demo"
        status = json.loads(
            (results / "logs" / "cross_kingdom_evidence_run_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["outputs"], [])
        output = results / "integrated_evidence"
        self.assertFalse(any((output / name).exists() for name in PUBLIC_OUTPUT_NAMES))

    def test_identical_staging_and_publication_directory_fails_nonfatally(self) -> None:
        root = self.workspace()
        candidates = root / "candidates.tsv"
        self.write_candidates(
            candidates,
            [{"gcf_id": "GCF_001", "cross_domain_gcf": "yes"}],
        )
        shared = root / "results" / "demo" / "integrated_evidence"

        completed = self.run_runner(
            root,
            requested=True,
            candidates=candidates,
            extra_env={
                "CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR": str(shared),
                "CROSS_KINGDOM_EVIDENCE_STAGING_DIR": str(shared),
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("phase=failed", completed.stdout)
        self.assertIn("must be distinct", completed.stderr)
        status = json.loads(
            (root / "results" / "demo" / "logs" / "cross_kingdom_evidence_run_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["outputs"], [])
        self.assertFalse(any((shared / name).exists() for name in PUBLIC_OUTPUT_NAMES))

    def test_unwritable_initialization_path_is_nonfatal_without_a_manifest(self) -> None:
        root = self.workspace()
        candidates = root / "candidates.tsv"
        self.write_candidates(
            candidates,
            [{"gcf_id": "GCF_001", "cross_domain_gcf": "yes"}],
        )
        blocked_parent = root / "blocked-parent"
        blocked_parent.write_text("not a directory\n", encoding="utf-8")

        completed = self.run_runner(
            root,
            requested=True,
            candidates=candidates,
            extra_env={
                "CROSS_KINGDOM_EVIDENCE_LOG_ROOT": str(blocked_parent / "logs"),
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("phase=failed", completed.stdout)
        self.assertIn("core outputs remain valid", completed.stderr)
        self.assertFalse(
            (blocked_parent / "logs" / "cross_kingdom_evidence_run_manifest.json").exists()
        )
        output = root / "results" / "demo" / "integrated_evidence"
        self.assertFalse(any((output / name).exists() for name in PUBLIC_OUTPUT_NAMES))

    def test_runner_is_explicit_bounded_and_has_no_installer_or_download(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "fallback_value RUN_CROSS_KINGDOM_EVIDENCE RUN_HGT_EVIDENCE 0",
            text,
        )
        self.assertIn('if [[ "${RUN_CROSS_KINGDOM_EVIDENCE}" != "1" ]]', text)
        self.assertIn("CROSS_KINGDOM_EVIDENCE_HARD_MAX_CANDIDATES=100", text)
        self.assertIn("select_cross_kingdom_candidates.py", text)
        self.assertIn("putative_transfer_evidence.tsv", text)
        self.assertIn("--explicit-request", text)
        for forbidden in ("pip install", "docker pull", "curl ", "wget ", "git clone"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
