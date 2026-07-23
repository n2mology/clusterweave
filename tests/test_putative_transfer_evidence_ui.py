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
            "function isCrossKingdomEvidenceArtifact", 1
        )[0]
        self.assertIn(
            "normalized.match(/^data\\/results\\/[^/]+\\/integrated_evidence\\/([^/]+)$/i)",
            predicate,
        )
        self.assertIn("CROSS_KINGDOM_EVIDENCE_FILENAMES.includes(name)", predicate)
        self.assertNotIn("rglob", predicate)

    def test_optional_category_is_absent_until_exact_outputs_exist(self) -> None:
        tabs = self.text.split("const RESULT_FOLDER_TABS", 1)[1].split("function resultFolderTabs", 1)[0]
        self.assertIn("{ key: 'evidence', label: 'CROSS-KINGDOM', optionalWhenAvailable: true }", tabs)
        visibility = self.text.split("function resultFolderTabs(counts = {})", 1)[1].split(
            "function resultPathExt", 1
        )[0]
        self.assertIn("!tab.optionalWhenAvailable", visibility)
        self.assertIn("Number((counts || {})[resultCategoryKey(tab.key)] || 0) > 0", visibility)
        self.assertIn("return resultFolderTabs(counts).map(tab => tab.key)", self.text)
        self.assertIn("return resultFolderTabs(counts).map(tab => {", self.text)

        self.assertIn("evidence: normalized.filter(isCrossKingdomEvidenceArtifact)", self.text)
        self.assertIn("evidence: artifacts.evidence.length", self.text)
        self.assertIn("if (artifacts.evidence.length)", self.text)
        self.assertIn("if (key === 'evidence') return isCrossKingdomEvidenceArtifact(path);", self.text)
        self.assertIn("|| isCrossKingdomEvidenceArtifact(path)", self.text)

    def test_captions_preserve_cross_kingdom_scientific_boundary(self) -> None:
        labels = self.text.split("function crossKingdomEvidenceLabel(path)", 1)[1].split(
            "function isSyntenyArtifact", 1
        )[0]
        self.assertIn("Plain-language Cross-Kingdom evidence cards", labels)
        self.assertIn("Lossless Cross-Kingdom evidence table", labels)
        self.assertIn("Bounded Cross-Kingdom evidence JSON", labels)
        self.assertNotIn("confirmed", labels.casefold())

        category_copy = self.text.split("function resultCategoryCopy(category)", 1)[1].split(
            "function resultCategoryIcon", 1
        )[0]
        self.assertIn(
            "Optional Cross-Kingdom context profiles; no evolutionary event, mechanism, or direction is inferred.",
            category_copy,
        )
        self.assertNotIn("confirmed", category_copy.casefold())
        self.assertIn("if (isCrossKingdomEvidenceArtifact(normalized)) return crossKingdomEvidenceLabel(normalized);", self.text)
        self.assertIn("/^data\\/results\\/[^/]+\\/integrated_evidence$/i.test(normalized)", self.text)


if __name__ == "__main__":
    unittest.main()
