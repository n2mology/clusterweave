from __future__ import annotations

import csv
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SANITIZER = REPO_ROOT / "bin" / "sanitize_bacterial_genbank.py"


class BacterialGenbankSanitizerTests(unittest.TestCase):
    def run_sanitizer(
        self,
        source: Path,
        output: Path,
        record_map: Path,
        record_ids: Path,
        *,
        minimum: int = 1000,
        maximum: int = 50_000_000,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SANITIZER),
                "--input",
                str(source),
                "--output",
                str(output),
                "--record-map",
                str(record_map),
                "--record-ids",
                str(record_ids),
                "--genome-id",
                "Bacterium_A",
                "--min-record-bp",
                str(minimum),
                "--max-record-bp",
                str(maximum),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
        )

    def test_annotated_genbank_becomes_feature_free_and_preserves_sequence_topology(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "annotated.gbk"
            output = root / "sanitized.gbk"
            record_map = root / "record_map.tsv"
            record_ids = root / "record_ids.txt"
            sequence = "ACGT" * 300
            source.write_text(
                "\n".join(
                    [
                        "LOCUS       circular_record        1200 bp    DNA     circular BCT 01-JAN-2000",
                        "DEFINITION  annotated bacterial record.",
                        "ACCESSION   CIRC0001",
                        "VERSION     CIRC0001.1",
                        "FEATURES             Location/Qualifiers",
                        "     source          1..1200",
                        '                     /organism="Example bacterium"',
                        "     CDS             1..300",
                        '                     /translation="MPEPTIDE"',
                        "ORIGIN",
                        f"        1 {sequence.lower()}",
                        "//",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            result = self.run_sanitizer(source, output, record_map, record_ids)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("BACTERIAL_SANITIZE genome=Bacterium_A", result.stdout)
            sanitized = output.read_text(encoding="utf-8")
            feature_section = sanitized.split(
                "FEATURES             Location/Qualifiers", 1
            )[1].split("ORIGIN", 1)[0]
            self.assertNotIn("CDS", feature_section)
            self.assertNotIn("source", feature_section)
            self.assertIn("circular", sanitized.splitlines()[0])
            output_sequence = "".join(
                re.findall(
                    r"[a-z]+",
                    sanitized.split("ORIGIN", 1)[1].split("//", 1)[0],
                )
            ).upper()
            self.assertEqual(output_sequence, sequence)

            with record_map.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["original_record_id"], "CIRC0001.1")
            self.assertEqual(rows[0]["topology"], "circular")
            self.assertEqual(rows[0]["status"], "eligible")
            self.assertEqual(
                record_ids.read_text(encoding="utf-8").strip(),
                rows[0]["sanitized_record_id"],
            )

    def test_fasta_filters_short_records_and_keeps_exact_original_id_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "assembly.fna"
            output = root / "sanitized.gbk"
            record_map = root / "record_map.tsv"
            record_ids = root / "record_ids.txt"
            source.write_text(
                ">short|record description\n"
                + ("A" * 999)
                + "\n>long|record description\n"
                + ("C" * 1000)
                + "\n",
                encoding="utf-8",
            )

            result = self.run_sanitizer(source, output, record_map, record_ids)

            self.assertEqual(result.returncode, 0, result.stderr)
            with record_map.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(
                [row["original_record_id"] for row in rows],
                ["short|record", "long|record"],
            )
            self.assertEqual(rows[0]["status"], "excluded_below_minimum")
            self.assertEqual(rows[1]["status"], "eligible")
            eligible_id = rows[1]["sanitized_record_id"]
            self.assertEqual(record_ids.read_text(encoding="utf-8"), f"{eligible_id}\n")
            self.assertIn(f"LOCUS       {eligible_id}", output.read_text(encoding="utf-8"))

    def test_oversized_record_fails_with_diagnostic_map_and_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "oversized.fna"
            output = root / "sanitized.gbk"
            record_map = root / "record_map.tsv"
            record_ids = root / "record_ids.txt"
            source.write_text(">large\n" + ("A" * 1001) + "\n", encoding="utf-8")

            result = self.run_sanitizer(
                source,
                output,
                record_map,
                record_ids,
                minimum=1,
                maximum=1000,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("exceed the configured maximum size", result.stderr)
            self.assertFalse(output.exists())
            with record_map.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(row["status"], "rejected_above_maximum")
            self.assertIn("1000 bp", row["reason"])


if __name__ == "__main__":
    unittest.main()
