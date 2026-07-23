import json
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class NPLinkerTargetSelectionTests(unittest.TestCase):
    def extracted_function(self, name: str, next_name: str) -> str:
        text = (REPO_ROOT / "run_nplinker.sh").read_text(encoding="utf-8")
        start = text.index(f"{name}()")
        end = text.index(f"\n{next_name}()", start)
        return text[start:end]

    def extracted_resolver(self) -> str:
        return self.extracted_function(
            "resolve_local_antismash_root", "get_podp_genome_ids"
        )

    def run_status_writer(self, manifest: Path) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmp:
            results_root = Path(tmp) / "results"
            run_dir = Path(tmp) / "run"
            script = "\n".join(
                [
                    "set -euo pipefail",
                    'RESULTS_ROOT="$1"',
                    'RUN_DIR="$2"',
                    'GENOME_TAXON_MANIFEST="$3"',
                    'TARGET_STRAIN="opaque_target"',
                    'get_podp_genome_ids(){ printf "%s\\n" "GCA_123456789.1"; }',
                    'log(){ :; }',
                    self.extracted_function(
                        "target_taxon_provenance_json",
                        "write_genome_status_for_local_antismash",
                    ),
                    self.extracted_function(
                        "write_genome_status_for_local_antismash",
                        "seed_antismash_for_podp",
                    ),
                    "write_genome_status_for_local_antismash",
                ]
            )
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    script,
                    "status-test",
                    str(results_root),
                    str(run_dir),
                    str(manifest),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(
                (run_dir / "downloads" / "genome_status.json").read_text(
                    encoding="utf-8"
                )
            )

    def test_target_selection_never_falls_back_to_another_root(self) -> None:
        function = self.extracted_resolver()

        self.assertIn("discovered_roots", function)
        self.assertIn("exact target root is required", function)
        self.assertNotIn("Using the only discovered", function)
        self.assertNotIn("head -n 1", function)

    def test_single_mismatched_root_fails_for_explicit_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results_root = Path(tmp) / "results"
            (results_root / "antismash" / "different_genome").mkdir(parents=True)
            script = "\n".join(
                [
                    "set -u",
                    'RESULTS_ROOT="$1"',
                    'TARGET_STRAIN="expected_genome"',
                    'LOCAL_ANTISMASH_ROOT="${RESULTS_ROOT}/antismash/${TARGET_STRAIN}"',
                    'die(){ printf "ERROR: %s\\n" "$*" >&2; exit 1; }',
                    self.extracted_resolver(),
                    "resolve_local_antismash_root",
                ]
            )
            result = subprocess.run(
                ["bash", "-c", script, "resolver-test", str(results_root)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("TARGET_STRAIN='expected_genome'", result.stderr)
            self.assertIn("discovered 1 other genome result root", result.stderr)

    def test_seeded_status_keeps_official_records_and_adds_target_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "genome_taxon_manifest.tsv"
            manifest.write_text(
                "genome_id\ttaxon_group\tprediction_method\n"
                "opaque_target\tBacteria\tProdigal\n",
                encoding="utf-8",
            )
            payload = self.run_status_writer(manifest)

        self.assertEqual(
            set(payload["genome_status"][0]),
            {
                "original_id",
                "resolved_refseq_id",
                "resolve_attempted",
                "bgc_path",
            },
        )
        self.assertEqual(
            payload["clusterweave_provenance"],
            {
                "prediction_method": "prodigal",
                "source": "genome_taxon_manifest.tsv",
                "target_genome_id": "opaque_target",
                "taxon_group": "bacteria",
            },
        )

    def test_seeded_status_is_legacy_compatible_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.run_status_writer(Path(tmp) / "missing.tsv")

        self.assertEqual(payload["version"], "1.0")
        self.assertEqual(
            payload["clusterweave_provenance"],
            {
                "prediction_method": "",
                "source": "genome_taxon_manifest.tsv",
                "target_genome_id": "opaque_target",
                "taxon_group": "",
            },
        )

if __name__ == "__main__":
    unittest.main()
