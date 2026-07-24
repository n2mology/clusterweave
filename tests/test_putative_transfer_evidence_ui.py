from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js"


class CrossKingdomEvidenceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = FRONTEND.read_text(encoding="utf-8")

    def test_discovery_is_exact_direct_child_allowlist(self) -> None:
        allowlist = self.text.split("const CROSS_KINGDOM_EVIDENCE_FILENAMES", 1)[1].split("]);", 1)[0]
        expected = [
            "cross_kingdom_evidence_cards.txt",
            "cross_kingdom_evidence.tsv",
            "cross_kingdom_evidence.json",
            "putative_transfer_evidence_cards.txt",
            "putative_transfer_evidence.tsv",
            "putative_transfer_evidence.json",
        ]
        for filename in expected:
            with self.subTest(filename=filename):
                self.assertIn(f"'{filename}'", allowlist)
        self.assertNotIn("integrated_evidence_run_manifest", allowlist)

        predicate = self.text.split("function crossKingdomEvidenceArtifact(path)", 1)[1].split(
            "function isPackageOnlyResultArtifact", 1
        )[0]
        self.assertIn(
            "normalized.match(/^data\\/results\\/[^/]+\\/integrated_evidence\\/([^/]+)$/i)",
            predicate,
        )
        self.assertIn("CROSS_KINGDOM_EVIDENCE_FILENAMES.includes(name)", predicate)
        self.assertNotIn("rglob", predicate)

    def test_evidence_artifacts_are_package_only_and_never_form_a_result_tab(self) -> None:
        tabs = self.text.split("const RESULT_FOLDER_TABS", 1)[1].split(
            "function resultFolderTabs", 1
        )[0]
        self.assertNotIn("key: 'evidence'", tabs)
        self.assertNotIn("label: 'EVIDENCE'", tabs)
        self.assertIn("function isPackageOnlyResultArtifact(path)", self.text)
        self.assertIn(
            "['evidence', 'integrated_evidence', 'cross_kingdom', 'putative_transfer']",
            self.text,
        )
        self.assertIn(
            "activeResultFiles = indexedFiles.filter(path => !isPackageOnlyResultArtifact(path))",
            self.text,
        )
        self.assertIn("if (isPackageOnlyResultArtifact(path)) return false;", self.text)
        self.assertNotIn("artifacts.evidence", self.text)
        self.assertNotIn("resultCategoryLabel('evidence')", self.text)
        self.assertNotIn("resultCategoryCopy('evidence')", self.text)
        self.assertNotIn("evidence: artifacts.evidence.length", self.text)

    def test_package_download_remains_available_for_hidden_artifacts(self) -> None:
        self.assertIn("let activeResultPackageFileCount = 0;", self.text)
        self.assertIn("activeResultPackageFileCount = indexedFiles.length;", self.text)
        self.assertIn("activeResultPackageFileCount < 1", self.text)
        self.assertIn("/archive`", self.text)


if __name__ == "__main__":
    unittest.main()
