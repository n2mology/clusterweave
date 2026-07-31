from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))


class CrossKingdomNamingAdapterTests(unittest.TestCase):
    def workspace(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def run_cli(self, script: str, *arguments: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(BIN_DIR / script),
                *(str(value) for value in arguments),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_cli_parity(
        self,
        canonical: subprocess.CompletedProcess[bytes],
        legacy: subprocess.CompletedProcess[bytes],
    ) -> None:
        self.assertEqual(canonical.returncode, 0, canonical.stderr.decode("utf-8", "replace"))
        self.assertEqual(legacy.returncode, canonical.returncode)
        self.assertEqual(legacy.stdout, canonical.stdout)
        self.assertEqual(legacy.stderr, canonical.stderr)

    def directory_bytes(self, root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_cross_kingdom_modules_own_the_implementations(self) -> None:
        for canonical_name, legacy_name in (
            ("build_cross_kingdom_evidence", "build_putative_transfer_evidence"),
            ("select_cross_kingdom_candidates", "select_putative_transfer_candidates"),
            ("enrich_cross_kingdom_context", "enrich_putative_transfer_context"),
        ):
            canonical = importlib.import_module(canonical_name)
            legacy = importlib.import_module(legacy_name)
            self.assertEqual(canonical.main.__module__, canonical_name)
            self.assertIs(legacy.main, canonical.main)

    def test_builder_cli_and_output_bytes_match_legacy_path(self) -> None:
        root = self.workspace()
        candidates = root / "candidates.tsv"
        candidates.write_text(
            "candidate_id\tgcf_id\tcross_domain_gcf\ttaxon_groups\n"
            "candidate-one\tGCF_001\tyes\tfungi;bacteria\n",
            encoding="utf-8",
        )
        canonical_output = root / "canonical-builder"
        legacy_output = root / "legacy-builder"
        arguments = (
            "--explicit-request",
            "--candidates",
            candidates,
            "--max-candidates",
            1,
        )
        canonical = self.run_cli(
            "build_cross_kingdom_evidence.py",
            *arguments,
            "--output-dir",
            canonical_output,
        )
        legacy = self.run_cli(
            "build_putative_transfer_evidence.py",
            *arguments,
            "--output-dir",
            legacy_output,
        )
        self.assert_cli_parity(canonical, legacy)
        self.assertEqual(
            self.directory_bytes(legacy_output),
            self.directory_bytes(canonical_output),
        )

    def test_selector_cli_and_output_bytes_match_legacy_path(self) -> None:
        root = self.workspace()
        crosswalk = root / "crosswalk.tsv"
        crosswalk.write_text(
            "genome\ttaxon_group\tgcf_id\n"
            "Fungus_one\tfungi\tGCF_001\n"
            "Bacterium_one\tbacteria\tGCF_001\n",
            encoding="utf-8",
        )
        canonical_output = root / "canonical-candidates.tsv"
        legacy_output = root / "legacy-candidates.tsv"
        arguments = (
            "--explicit-request",
            "--crosswalk",
            crosswalk,
            "--max-candidates",
            1,
        )
        canonical = self.run_cli(
            "select_cross_kingdom_candidates.py",
            *arguments,
            "--output",
            canonical_output,
        )
        legacy = self.run_cli(
            "select_putative_transfer_candidates.py",
            *arguments,
            "--output",
            legacy_output,
        )
        self.assert_cli_parity(canonical, legacy)
        self.assertEqual(legacy_output.read_bytes(), canonical_output.read_bytes())

    def test_context_cli_and_output_bytes_match_legacy_path(self) -> None:
        root = self.workspace()
        candidates = root / "candidates.tsv"
        candidates.write_text(
            "candidate_id\tgcf_id\tcross_domain_gcf\ttaxon_groups\n"
            "candidate-one\tGCF_001\tyes\tfungi;bacteria\n",
            encoding="utf-8",
        )
        crosswalk = root / "crosswalk.tsv"
        crosswalk.write_text(
            "genome\ttaxon_group\tantismash_region\tgcf_id\n"
            "Fungus_one\tfungi\tFungus_one.region001\tGCF_001\n"
            "Bacterium_one\tbacteria\tBacterium_one.region001\tGCF_001\n",
            encoding="utf-8",
        )
        ranking = root / "missing-ranking.tsv"
        taxon_manifest = root / "missing-taxon-manifest.tsv"
        canonical_output = root / "canonical-context.tsv"
        legacy_output = root / "legacy-context.tsv"
        arguments = (
            "--explicit-request",
            "--candidates",
            candidates,
            "--crosswalk",
            crosswalk,
            "--ranking",
            ranking,
            "--taxon-manifest",
            taxon_manifest,
            "--antismash-root",
            root / "missing-antismash",
            "--clinker-root",
            root / "missing-clinker",
            "--genomes-root",
            root / "missing-genomes",
            "--project-name",
            "demo",
            "--max-candidates",
            1,
        )
        canonical = self.run_cli(
            "enrich_cross_kingdom_context.py",
            *arguments,
            "--output",
            canonical_output,
        )
        legacy = self.run_cli(
            "enrich_putative_transfer_context.py",
            *arguments,
            "--output",
            legacy_output,
        )
        self.assert_cli_parity(canonical, legacy)
        self.assertEqual(legacy_output.read_bytes(), canonical_output.read_bytes())

    def test_crosswalk_join_ids_are_exact_first_with_narrow_legacy_fallback(self) -> None:
        crosswalk = importlib.import_module("build_bgc_gcf_crosswalk")
        self.assertEqual(
            crosswalk.join_id_pairs(
                "Bacillus_subtilis_168",
                "Bacillus_subtilis_168.region001",
                "bacteria",
            ),
            [
                ("Bacillus_subtilis_168", "Bacillus_subtilis_168.region001"),
                (
                    "bacteria_Bacillus_subtilis_168",
                    "bacteria_Bacillus_subtilis_168.region001",
                ),
            ],
        )
        self.assertEqual(
            crosswalk.join_id_pairs("Fungus_one", "Fungus_one.region001", "fungi"),
            [("Fungus_one", "Fungus_one.region001")],
        )


if __name__ == "__main__":
    unittest.main()
