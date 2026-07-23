from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
JS_PATH = WEB_DIR / "static" / "assets" / "clusterweave.js"

if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from taxon_routing import TaxonRoutingError, parse_genbank_taxonomy  # noqa: E402


def pure_helper_block() -> str:
    source = JS_PATH.read_text(encoding="utf-8")
    return source.split("// BEGIN CLIENT_GENBANK_TAXONOMY_PURE", 1)[1].split(
        "// END CLIENT_GENBANK_TAXONOMY_PURE", 1
    )[0]


def server_status(text: str) -> tuple[str, str]:
    try:
        authority = parse_genbank_taxonomy(text)
    except TaxonRoutingError:
        return "conflicting", ""
    if authority is None:
        return "ambiguous", ""
    group = str(authority.get("taxon_group") or "")
    return ("unsupported" if group == "unsupported" else "resolved", group)


@unittest.skipUnless(shutil.which("node"), "Node.js is required for frontend behavior tests")
class FrontendTaxonAuthorityTests(unittest.TestCase):
    def run_node(self, body: str) -> object:
        script = pure_helper_block() + "\n" + body
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=REPO_ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_browser_genbank_authority_matches_server_lineage_markers(self) -> None:
        fixtures = {
            "bacteria_header": """LOCUS       Bacterium 24 bp DNA\n  ORGANISM  Escherichia demo\n            Bacteria; Pseudomonadota; Gammaproteobacteria.\nFEATURES             Location/Qualifiers\n     source          1..24\n                     /db_xref=\"taxon:511145\"\nORIGIN\n        1 atgc\n//\n""",
            "fungal_qualifier": """LOCUS       Fungus 24 bp DNA\nFEATURES             Location/Qualifiers\n     source          1..24\n                     /organism=\"Fixture fungus\"\n                     /db_xref=\"taxon:4751\"\n                     /lineage=\"Eukaryota; Fungi; Ascomycota\"\nORIGIN\n        1 atgc\n//\n""",
            "ambiguous_name_only": """LOCUS       Unknown 24 bp DNA\n  ORGANISM  Bacteria-looking filename organism\nFEATURES             Location/Qualifiers\n     source          1..24\nORIGIN\n        1 atgc\n//\n""",
            "unsupported_archaea": """LOCUS       Archaeon 24 bp DNA\n  ORGANISM  Archaeon demo\n            Archaea; Euryarchaeota.\nFEATURES             Location/Qualifiers\nORIGIN\n        1 atgc\n//\n""",
            "conflicting": """LOCUS       Conflict 24 bp DNA\n  ORGANISM  Conflict demo\n            Bacteria; Eukaryota.\nFEATURES             Location/Qualifiers\nORIGIN\n        1 atgc\n//\n""",
        }
        browser = self.run_node(
            f"const fixtures = {json.dumps(fixtures)};\n"
            "const result = Object.fromEntries(Object.entries(fixtures).map(([key, value]) => {\n"
            "  const authority = parseClientGenbankTaxonomy(value);\n"
            "  return [key, [authority.status, authority.taxonGroup || '']];\n"
            "}));\n"
            "process.stdout.write(JSON.stringify(result));\n"
        )
        expected = {key: list(server_status(text)) for key, text in fixtures.items()}
        self.assertEqual(browser, expected)

    def test_authority_omits_assignments_and_same_stem_pair_inherits_route(self) -> None:
        result = self.run_node(
            "const bacteria = {status:'resolved', taxonGroup:'bacteria', reason:'resolved'};\n"
            "const ambiguous = {status:'ambiguous', taxonGroup:'', reason:'ambiguous'};\n"
            "const unsupported = {status:'unsupported', taxonGroup:'unsupported', reason:'unsupported lineage'};\n"
            "const inherited = mergeClientGenbankAuthorities([ambiguous, bacteria]);\n"
            "const payload = {\n"
            "  inherited: clientTaxonAssignmentDecision(inherited, '', 'paired_genome'),\n"
            "  redundant: clientTaxonAssignmentDecision(bacteria, 'bacteria', 'paired_genome'),\n"
            "  conflict: clientTaxonAssignmentDecision(bacteria, 'fungi', 'paired_genome'),\n"
            "  raw: clientTaxonAssignmentDecision(ambiguous, '', 'raw_fasta'),\n"
            "  unsupported: clientTaxonAssignmentDecision(unsupported, '', 'archaeon'),\n"
            "};\n"
            "process.stdout.write(JSON.stringify(payload));\n"
        )
        self.assertFalse(result["inherited"]["requiresAssignment"])
        self.assertEqual(result["inherited"]["taxonGroup"], "bacteria")
        self.assertFalse(result["redundant"]["requiresAssignment"])
        self.assertEqual(result["redundant"]["issue"], "")
        self.assertFalse(result["conflict"]["requiresAssignment"])
        self.assertIn("conflicts with authoritative GenBank", result["conflict"]["issue"])
        self.assertTrue(result["raw"]["requiresAssignment"])
        self.assertFalse(result["unsupported"]["requiresAssignment"])
        self.assertIn("unsupported lineage", result["unsupported"]["issue"])


if __name__ == "__main__":
    unittest.main()
