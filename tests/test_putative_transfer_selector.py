from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SELECTOR = REPO_ROOT / "bin" / "select_cross_kingdom_candidates.py"
BUILDER = REPO_ROOT / "bin" / "build_cross_kingdom_evidence.py"


class CrossKingdomSelectorTests(unittest.TestCase):
    def workspace(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def write_crosswalk(self, path: Path, rows: list[dict[str, str]]) -> None:
        fields: list[str] = []
        for row in rows:
            for field in row:
                if field not in fields:
                    fields.append(field)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def run_selector(
        self,
        crosswalk: Path,
        output: Path,
        *,
        max_candidates: int = 25,
        explicit: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(SELECTOR)]
        if explicit:
            command.append("--explicit-request")
        command.extend(
            [
                "--crosswalk",
                str(crosswalk),
                "--output",
                str(output),
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

    def read_rows(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    def test_zero_cross_domain_families_writes_no_candidate_rows(self) -> None:
        root = self.workspace()
        crosswalk = root / "crosswalk.tsv"
        output = root / "candidates.tsv"
        self.write_crosswalk(
            crosswalk,
            [
                {"genome": "fungus_1", "taxon_group": "fungi", "gcf_id": "GCF_FUNGI"},
                {"genome": "fungus_2", "taxon_group": "fungi", "gcf_id": "GCF_FUNGI"},
                {"genome": "bacterium_1", "taxon_group": "bacteria", "gcf_id": "GCF_BACTERIA"},
            ],
        )
        completed = self.run_selector(crosswalk, output)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("count=0 eligible=0", completed.stdout)
        self.assertEqual(self.read_rows(output), [])
        self.assertIn("cross_domain_gcf", output.read_text(encoding="utf-8").splitlines()[0])

    def test_one_cross_domain_family_is_unique_counted_and_remains_exploratory(self) -> None:
        root = self.workspace()
        crosswalk = root / "crosswalk.tsv"
        candidates = root / "candidates.tsv"
        self.write_crosswalk(
            crosswalk,
            [
                {"genome": "fungus_1", "taxon_group": "fungi", "gcf_id": "GCF_SHARED"},
                {"genome": "fungus_1", "taxon_group": "fungi", "gcf_id": "GCF_SHARED"},
                {"genome": "bacterium_1", "taxon_group": "bacteria", "gcf_id": "GCF_SHARED"},
                {"genome": "bacterium_2", "taxon_group": "bacteria", "gcf_id": "GCF_PRIVATE"},
            ],
        )
        completed = self.run_selector(crosswalk, candidates)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        rows = self.read_rows(candidates)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0],
            {
                "candidate_id": "GCF_SHARED",
                "gcf_id": "GCF_SHARED",
                "cross_domain_gcf": "yes",
                "taxon_groups": "fungi;bacteria",
                "fungal_member_count": "1",
                "bacterial_member_count": "1",
                "member_count": "2",
            },
        )

        evidence = root / "evidence"
        built = subprocess.run(
            [
                sys.executable,
                str(BUILDER),
                "--explicit-request",
                "--candidates",
                str(candidates),
                "--output-dir",
                str(evidence),
                "--max-candidates",
                "25",
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(built.returncode, 0, built.stderr)
        payload = json.loads((evidence / "cross_kingdom_evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["records"][0]["confidence"], "exploratory")
        self.assertEqual(payload["records"][0]["independent_signal_count"], 0)

    def test_many_families_are_deterministic_and_only_safe_unambiguous_fields_are_carried(self) -> None:
        root = self.workspace()
        rows = [
            {
                "genome": "fungus_b",
                "taxon_group": "fungi",
                "gcf_id": "GCF_B;GCF_A",
                "topology_discordance": "supported",
                "topology_support": "95",
                "mobile_element_context": "present",
                "family_tree_id": "/private/tree.file",
                "raw_sequence": "ACGT" * 30,
                "notes": "not an allowlisted public evidence field",
            },
            {
                "genome": "bacterium_b",
                "taxon_group": "bacteria",
                "gcf_id": "GCF_B",
                "topology_discordance": "supported",
                "topology_support": "95",
                "mobile_element_context": "absent",
                "family_tree_id": "/private/tree.file",
                "raw_sequence": "TGCA" * 30,
                "notes": "different private note",
            },
            {
                "genome": "bacterium_a",
                "taxon_group": "bacteria",
                "gcf_id": "GCF_A",
                "topology_discordance": "supported",
                "topology_support": "95",
                "mobile_element_context": "present",
                "family_tree_id": "/private/tree.file",
                "raw_sequence": "TGCA" * 30,
                "notes": "private",
            },
        ]
        first_crosswalk = root / "first.tsv"
        second_crosswalk = root / "second.tsv"
        first_output = root / "first_candidates.tsv"
        second_output = root / "second_candidates.tsv"
        self.write_crosswalk(first_crosswalk, rows)
        self.write_crosswalk(second_crosswalk, list(reversed(rows)))
        first = self.run_selector(first_crosswalk, first_output)
        second = self.run_selector(second_crosswalk, second_output)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first_output.read_bytes(), second_output.read_bytes())

        selected = self.read_rows(first_output)
        self.assertEqual([row["gcf_id"] for row in selected], ["GCF_A", "GCF_B"])
        self.assertTrue(all(row["topology_discordance"] == "supported" for row in selected))
        self.assertTrue(all(row["topology_support"] == "95" for row in selected))
        by_gcf = {row["gcf_id"]: row for row in selected}
        self.assertEqual(by_gcf["GCF_A"]["mobile_element_context"], "present")
        self.assertEqual(by_gcf["GCF_B"]["mobile_element_context"], "")
        self.assertTrue(all(row["family_tree_id"] == "" for row in selected))
        header = first_output.read_text(encoding="utf-8").splitlines()[0].split("\t")
        self.assertNotIn("raw_sequence", header)
        self.assertNotIn("notes", header)

    def test_bound_prefers_broader_families_then_stable_gcf_id(self) -> None:
        root = self.workspace()
        crosswalk = root / "crosswalk.tsv"
        output = root / "candidates.tsv"
        rows: list[dict[str, str]] = []
        for genome in ("fungus_1", "fungus_2", "fungus_3"):
            rows.append({"genome": genome, "taxon_group": "fungi", "gcf_id": "GCF_LARGE"})
        for genome in ("bacterium_1", "bacterium_2"):
            rows.append({"genome": genome, "taxon_group": "bacteria", "gcf_id": "GCF_LARGE"})
        for family in ("GCF_B", "GCF_A"):
            rows.extend(
                [
                    {"genome": f"fungus_{family}", "taxon_group": "fungi", "gcf_id": family},
                    {"genome": f"bacterium_{family}", "taxon_group": "bacteria", "gcf_id": family},
                ]
            )
        self.write_crosswalk(crosswalk, rows)
        completed = self.run_selector(crosswalk, output, max_candidates=2)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("count=2 eligible=3 limit=2", completed.stdout)
        selected = self.read_rows(output)
        self.assertEqual([row["gcf_id"] for row in selected], ["GCF_LARGE", "GCF_A"])
        self.assertEqual(selected[0]["member_count"], "5")

        implicit_output = root / "implicit.tsv"
        implicit = self.run_selector(crosswalk, implicit_output, explicit=False)
        self.assertNotEqual(implicit.returncode, 0)
        self.assertFalse(implicit_output.exists())


if __name__ == "__main__":
    unittest.main()
