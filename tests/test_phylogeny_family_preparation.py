from __future__ import annotations

import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PREPARER = REPO_ROOT / "bin" / "prepare_phylogeny_families.py"


class PhylogenyFamilyPreparationTests(unittest.TestCase):
    def workspace(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def write_tsv(self, path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)

    def write_region(self, path: Path, prefix: str, *, annotated: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        annotation = (
            '                     /smCOG="SMCOG1046: aminotransferase (Score: 42.0)"\n'
            if annotated
            else '                     /product="generic protein without antiSMASH homology"\n'
        )
        path.write_text(
            "LOCUS       fixture                  36 bp    DNA     linear   UNK 01-JAN-2026\n"
            "FEATURES             Location/Qualifiers\n"
            "     CDS             1..36\n"
            f'                     /locus_tag="{prefix}_core"\n'
            f"{annotation}"
            '                     /translation="MSTNPKPQRKTK"\n'
            "     CDS             1..36\n"
            f'                     /locus_tag="{prefix}_unannotated"\n'
            '                     /product="ordinary protein"\n'
            '                     /translation="MAAAAAAAAAAA"\n'
            "ORIGIN\n"
            "        1 atgagcacca acccaaaacc acaacgaaaa ccaaa\n"
            "//\n",
            encoding="utf-8",
        )

    def run_preparer(
        self,
        root: Path,
        *,
        explicit: bool = True,
        crosswalk_rows: list[dict[str, str]] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        candidates = root / "candidates.tsv"
        crosswalk = root / "crosswalk.tsv"
        antismash = root / "antismash"
        output = root / "phylogeny_inputs"
        genomes = [
            ("fungus_a", "fungi"),
            ("fungus_b", "fungi"),
            ("bacterium_a", "bacteria"),
            ("bacterium_b", "bacteria"),
        ]
        for genome, _ in genomes:
            self.write_region(antismash / genome / "region001.gbk", genome)
        self.write_tsv(
            candidates,
            ["candidate_id", "gcf_id", "cross_domain_gcf"],
            [{"candidate_id": "GCF_SHARED", "gcf_id": "GCF_SHARED", "cross_domain_gcf": "yes"}],
        )
        rows = crosswalk_rows or [
            {
                "genome": genome,
                "taxon_group": taxon,
                "antismash_region": "region001",
                "gcf_id": "GCF_SHARED",
            }
            for genome, taxon in genomes
        ]
        self.write_tsv(
            crosswalk,
            ["genome", "taxon_group", "antismash_region", "gcf_id"],
            rows,
        )
        command = [sys.executable, str(PREPARER)]
        if explicit:
            command.append("--explicit-request")
        command.extend(
            [
                "--candidates",
                str(candidates),
                "--crosswalk",
                str(crosswalk),
                "--antismash-root",
                str(antismash),
                "--output-root",
                str(output),
                "--max-families",
                "3",
                "--max-sequences-per-family",
                "8",
            ]
        )
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_explicit_antismash_smcog_family_writes_fasta_manifest_and_mapping(self) -> None:
        root = self.workspace()
        completed = self.run_preparer(root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("status=success families=1 sequences=4", completed.stdout)
        output = root / "phylogeny_inputs"
        with (output / "families.tsv").open(newline="", encoding="utf-8") as handle:
            families = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(families), 1)
        family = families[0]
        self.assertEqual(family["taxon_group"], "both")
        self.assertEqual(family["gcf_id"], "GCF_SHARED")
        self.assertEqual(family["annotation_key"], "smcog:SMCOG1046")
        self.assertEqual(family["sequence_count"], "4")
        self.assertEqual(family["fungal_sequence_count"], "2")
        self.assertEqual(family["bacterial_sequence_count"], "2")
        fasta = Path(family["input_path"])
        self.assertTrue(fasta.is_file())
        fasta_text = fasta.read_text(encoding="utf-8")
        self.assertEqual(fasta_text.count(">cwseq_"), 4)
        self.assertNotIn("unannotated", fasta_text)
        with (output / "sequence_taxon_map.tsv").open(
            newline="", encoding="utf-8"
        ) as handle:
            mapping = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(mapping), 4)
        self.assertEqual({row["taxon_group"] for row in mapping}, {"fungi", "bacteria"})
        self.assertEqual({row["family_id"] for row in mapping}, {family["family_id"]})
        diagnostics = (output / "family_preparation_diagnostics.tsv").read_text(
            encoding="utf-8"
        )
        self.assertEqual(diagnostics.count("\tparsed\t"), 4)

        first = {
            path.relative_to(output).as_posix(): path.read_bytes()
            for path in output.rglob("*")
            if path.is_file()
        }
        repeated = self.run_preparer(root)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        second = {
            path.relative_to(output).as_posix(): path.read_bytes()
            for path in output.rglob("*")
            if path.is_file()
        }
        self.assertEqual(second, first)

    def test_requires_explicit_request_and_rejects_region_path_traversal(self) -> None:
        implicit_root = self.workspace()
        implicit = self.run_preparer(implicit_root, explicit=False)
        self.assertNotEqual(implicit.returncode, 0)
        self.assertIn("explicit-request", implicit.stderr)
        self.assertFalse((implicit_root / "phylogeny_inputs").exists())

        unsafe_root = self.workspace()
        unsafe = self.run_preparer(
            unsafe_root,
            crosswalk_rows=[
                {
                    "genome": "fungus_a",
                    "taxon_group": "fungi",
                    "antismash_region": "../region001",
                    "gcf_id": "GCF_SHARED",
                }
            ],
        )
        self.assertNotEqual(unsafe.returncode, 0)
        self.assertIn("unsafe_genome_or_region_identifier", unsafe.stderr)

    def test_unannotated_products_never_become_sequence_families(self) -> None:
        root = self.workspace()
        completed = self.run_preparer(root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        # Rewrite every region without smCOG/sec_met_domain/NRPS_PKS and rerun.
        for path in (root / "antismash").rglob("*.gbk"):
            self.write_region(path, path.parent.name, annotated=False)
        completed = subprocess.run(
            [
                sys.executable,
                str(PREPARER),
                "--explicit-request",
                "--candidates",
                str(root / "candidates.tsv"),
                "--crosswalk",
                str(root / "crosswalk.tsv"),
                "--antismash-root",
                str(root / "antismash"),
                "--output-root",
                str(root / "phylogeny_inputs"),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("status=insufficient_data families=0 sequences=0", completed.stdout)
        with (root / "phylogeny_inputs" / "families.tsv").open(
            newline="", encoding="utf-8"
        ) as handle:
            self.assertEqual(list(csv.DictReader(handle, delimiter="\t")), [])

    def test_explicit_sec_met_domain_is_a_bounded_fallback_when_smcog_is_absent(self) -> None:
        root = self.workspace()
        initial = self.run_preparer(root)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        for path in (root / "antismash").rglob("*.gbk"):
            text = path.read_text(encoding="utf-8")
            text = text.replace(
                '/smCOG="SMCOG1046: aminotransferase (Score: 42.0)"',
                '/sec_met_domain="AMP-binding (E-value: 1e-30)"',
            )
            path.write_text(text, encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(PREPARER),
                "--explicit-request",
                "--candidates",
                str(root / "candidates.tsv"),
                "--crosswalk",
                str(root / "crosswalk.tsv"),
                "--antismash-root",
                str(root / "antismash"),
                "--output-root",
                str(root / "phylogeny_inputs"),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        with (root / "phylogeny_inputs" / "families.tsv").open(
            newline="", encoding="utf-8"
        ) as handle:
            families = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(families), 1)
        self.assertEqual(families[0]["annotation_key"], "sec_met_domain:amp-binding")

    def test_helper_has_no_download_install_or_sequence_similarity_surface(self) -> None:
        text = PREPARER.read_text(encoding="utf-8")
        for forbidden in (
            "import requests",
            "import urllib",
            "import subprocess",
            "pip install",
            "docker pull",
            "curl ",
            "wget ",
            "blastp",
            "mmseqs",
        ):
            self.assertNotIn(forbidden, text)

    def test_aggregate_region_input_bytes_are_hard_bounded(self) -> None:
        root = self.workspace()
        initial = self.run_preparer(root)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        completed = subprocess.run(
            [
                sys.executable,
                str(PREPARER),
                "--explicit-request",
                "--candidates",
                str(root / "candidates.tsv"),
                "--crosswalk",
                str(root / "crosswalk.tsv"),
                "--antismash-root",
                str(root / "antismash"),
                "--output-root",
                str(root / "bounded_inputs"),
                "--max-total-input-bytes",
                "1",
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("aggregate_byte_bound", completed.stderr)
        self.assertFalse((root / "bounded_inputs" / "families.tsv").exists())


if __name__ == "__main__":
    unittest.main()
