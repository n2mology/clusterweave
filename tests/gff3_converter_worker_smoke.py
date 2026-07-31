#!/usr/bin/env python3
"""Exercise the tracked GFF3 converter in the supported worker runtime."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

from Bio import SeqIO


def put(sequence: list[str], start: int, value: str) -> None:
    sequence[start - 1 : start - 1 + len(value)] = value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--converter",
        type=Path,
        default=Path("/clusterweave/bin/gff3_to_gbk_with_translations.py"),
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fasta = root / "fixture.fna"
        gff3 = root / "fixture.gff3"
        output = root / "fixture.gbk"

        plus = list("N" * 90)
        put(plus, 1, "CATG")
        put(plus, 11, "AAATGA")
        minus = list("N" * 90)
        put(minus, 31, "TTAGGGCAT")
        empty = list("A" * 30)
        fasta.write_text(
            ">contig_plus joined phase fixture\n"
            + "".join(plus)
            + "\n>contig_minus reverse fixture\n"
            + "".join(minus)
            + "\n>contig_empty no CDS fixture\n"
            + "".join(empty)
            + "\n",
            encoding="utf-8",
        )
        gff3.write_text(
            "##gff-version 3\n"
            "contig_plus\tfixture\tCDS\t1\t4\t.\t+\t1\tParent=plus_joined\n"
            "contig_plus\tfixture\tCDS\t11\t16\t.\t+\t0\tParent=plus_joined\n"
            "contig_minus\tfixture\tCDS\t31\t39\t.\t-\t0\tID=minus_single\n",
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(args.converter),
                "--fasta",
                str(fasta),
                "--gff3",
                str(gff3),
                "--out_gbk",
                str(output),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        expected_stdout = (
            f"WROTE {output}\n"
            "CDS features: 2\n"
            "/translation=: 2\n"
        )
        if completed.stdout != expected_stdout:
            raise AssertionError(f"unexpected converter stdout:\n{completed.stdout!r}")

        records = {record.id: record for record in SeqIO.parse(output, "genbank")}
        if list(records) != ["contig_plus", "contig_minus", "contig_empty"]:
            raise AssertionError(f"unexpected record order: {list(records)}")
        plus_cds = [feature for feature in records["contig_plus"].features if feature.type == "CDS"]
        minus_cds = [feature for feature in records["contig_minus"].features if feature.type == "CDS"]
        empty_cds = [feature for feature in records["contig_empty"].features if feature.type == "CDS"]
        if len(plus_cds) != 1 or len(minus_cds) != 1 or empty_cds:
            raise AssertionError("unexpected per-contig CDS counts")

        plus_feature = plus_cds[0]
        if len(plus_feature.location.parts) != 2:
            raise AssertionError(f"plus CDS is not joined: {plus_feature.location}")
        if [(int(part.start), int(part.end), part.strand) for part in plus_feature.location.parts] != [
            (0, 4, 1),
            (10, 16, 1),
        ]:
            raise AssertionError(f"unexpected plus location: {plus_feature.location}")
        if plus_feature.qualifiers.get("translation") != ["MK*"]:
            raise AssertionError(f"unexpected phased plus translation: {plus_feature.qualifiers}")

        minus_feature = minus_cds[0]
        if minus_feature.location.strand != -1:
            raise AssertionError(f"unexpected minus strand: {minus_feature.location}")
        if minus_feature.qualifiers.get("translation") != ["MP*"]:
            raise AssertionError(f"unexpected minus translation: {minus_feature.qualifiers}")

    print("GFF3 converter worker contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
