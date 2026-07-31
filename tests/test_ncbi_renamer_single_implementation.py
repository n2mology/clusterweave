from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RENAMER = REPO_ROOT / "scripts" / "ncbi" / "rename_ncbi_genomes.sh"
PREPARE = REPO_ROOT / "prepare_genomes_from_accessions.sh"
ROUTE_HEADER = (
    "input_key\tgenome_id\ttaxon_group\ttaxon_source\ttaxid\torganism_name\t"
    "source_accession\tprediction_method\tdetector_profile\tinput_path_key\t"
    "route_status\troute_reason\n"
)


def write_ncbi_fixture(
    genome_root: Path,
    accession: str,
    organism_name: str,
    taxid: int,
) -> None:
    package = genome_root / accession / "ncbi_dataset" / "data" / accession
    package.mkdir(parents=True)
    report = {
        "organism": {"organismName": organism_name, "taxId": taxid},
        "assemblyStats": {"totalSequenceLength": 4},
    }
    report_path = (
        genome_root
        / accession
        / "ncbi_dataset"
        / "data"
        / "assembly_data_report.jsonl"
    )
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    (package / f"{accession}.fna").write_text(">contig\nACGT\n", encoding="utf-8")
    (package / "genomic.gff").write_text("##gff-version 3\n", encoding="utf-8")
    (package / "genomic.gbff").write_text(
        "LOCUS       contig 4 bp DNA\n", encoding="utf-8"
    )


def run_renamer(
    genome_root: Path,
    taxon_group: str,
    *,
    extra_args: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        {
            "GENOME_ROOT": str(genome_root),
            "TAXON_GROUP": taxon_group,
            "GENOME_TAXON_MANIFEST": str(
                genome_root.parent / "missing_manifest.tsv"
            ),
            "PYTHON_BIN": sys.executable,
            "DATASETS_CMD": str(genome_root.parent / "missing-datasets"),
        }
    )
    return subprocess.run(
        ["bash", str(RENAMER), *extra_args],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


class NcbiRenamerExtractionContractTests(unittest.TestCase):
    maxDiff = None

    def test_shell_uses_one_tracked_mapping_implementation(self) -> None:
        shell_text = RENAMER.read_text(encoding="utf-8")
        helper = REPO_ROOT / "scripts" / "ncbi" / "rename_ncbi_genomes.py"
        helper_text = helper.read_text(encoding="utf-8")

        self.assertNotIn("<<'PY'", shell_text)
        self.assertIn(
            'RENAME_HELPER_PY="${SCRIPT_DIR}/rename_ncbi_genomes.py"',
            shell_text,
        )
        self.assertIn(
            '"${PYTHON_CMD}" "${RENAME_HELPER_PY}" "${GENOME_ROOT}" '
            '"${MAPPING_FILE}" "${DATASETS_CMD_RESOLVED}" "${TAXON_GROUP}" '
            '"${GENOME_TAXON_MANIFEST}"',
            shell_text,
        )
        self.assertEqual(shell_text.count("RENAME_HELPER_PY"), 4)
        self.assertIn("def taxonomy_summary(taxid):", helper_text)

    def test_shell_passes_the_original_helper_argv_order(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="clusterweave-r10b-helper-argv-"
        ) as tmp:
            root = Path(tmp)
            genome_root = root / "genomes with spaces"
            genome_root.mkdir()
            mapping = root / "mapping with spaces.tsv"
            manifest = root / "manifest with spaces.tsv"
            argv_log = root / "argv.bin"
            fake_python = root / "python recorder"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "if [[ \"${1:-}\" == \"-c\" ]]; then exit 0; fi\n"
                "printf '%s\\0' \"$@\" > \"${ARGV_LOG}\"\n"
                ": > \"$3\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            env = dict(os.environ)
            env.update(
                {
                    "GENOME_ROOT": str(genome_root),
                    "MAPPING_FILE": str(mapping),
                    "GENOME_TAXON_MANIFEST": str(manifest),
                    "TAXON_GROUP": "bacteria",
                    "PYTHON_BIN": str(fake_python),
                    "DATASETS_CMD": str(root / "missing-datasets"),
                    "ARGV_LOG": str(argv_log),
                }
            )

            result = subprocess.run(
                ["bash", str(RENAMER)],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                argv_log.read_bytes().rstrip(b"\0").split(b"\0"),
                [
                    str(
                        REPO_ROOT
                        / "scripts"
                        / "ncbi"
                        / "rename_ncbi_genomes.py"
                    ).encode(),
                    str(genome_root).encode(),
                    str(mapping).encode(),
                    b"",
                    b"bacteria",
                    str(manifest).encode(),
                ],
            )

    def test_fungal_bacterial_mixed_and_zero_output_goldens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clusterweave-r10b-") as tmp:
            root = Path(tmp)

            fungal_root = root / "fungal genomes"
            write_ncbi_fixture(
                fungal_root,
                "GCA_000003.1",
                "Amanita muscaria strain 2016PMI152",
                41956,
            )
            fungal = run_renamer(fungal_root, "fungi")
            self.assertEqual(fungal.returncode, 0, fungal.stderr)
            self.assertEqual(fungal.stdout, "")
            self.assertEqual(fungal.stderr, "")
            self.assertEqual(
                (fungal_root / "accessions_fungusID_taxonomyID.txt").read_bytes(),
                b"GCA_000003.1\tAmanita_muscaria_2016PMI152\t41956\t0.00\t"
                b"Amanita muscaria strain 2016PMI152\t\t\n",
            )

            bacterial_root = root / "bacterial genomes"
            write_ncbi_fixture(
                bacterial_root,
                "GCF_000009045.1",
                "Bacillus subtilis strain 168",
                224308,
            )
            bacterial = run_renamer(bacterial_root, "bacteria")
            self.assertEqual(bacterial.returncode, 0, bacterial.stderr)
            self.assertEqual(bacterial.stdout, "")
            self.assertEqual(bacterial.stderr, "")
            self.assertEqual(
                (
                    bacterial_root / "accessions_bacteriaID_taxonomyID.txt"
                ).read_bytes(),
                b"GCF_000009045.1\tBacillus_subtilis_168\t224308\t0.00\t"
                b"Bacillus subtilis strain 168\t\t\n",
            )

            mixed_root = root / "mixed project"
            fungi_root = mixed_root / "data" / "genomes" / "fungi" / "demo"
            bacteria_root = (
                mixed_root / "data" / "genomes" / "bacteria" / "demo"
            )
            write_ncbi_fixture(
                fungi_root,
                "GCA_000001.1",
                "Aspergillus nidulans strain FGSC_A4",
                162425,
            )
            write_ncbi_fixture(
                bacteria_root,
                "GCF_000002.2",
                "Streptomyces coelicolor strain A3",
                100226,
            )
            accessions = mixed_root / "accessions.txt"
            accessions.write_text(
                "GCA_000001.1\nGCF_000002.2\n", encoding="utf-8"
            )
            manifest = (
                mixed_root
                / "data"
                / "results"
                / "demo"
                / "summary_tables"
                / "genome_taxon_manifest.tsv"
            )
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                ROUTE_HEADER
                + "GCA_000001.1\tFrozen_Fungus\tfungi\tncbi\t162425\t"
                "Aspergillus nidulans\tGCA_000001.1\tfunannotate\t"
                "antismash+funbgcex\tGCA_000001.1\taccepted\tauthoritative\n"
                + "GCF_000002.2\tFrozen_Bacterium\tbacteria\tncbi\t100226\t"
                "Streptomyces coelicolor\tGCF_000002.2\tprodigal\tantismash\t"
                "GCF_000002.2\taccepted\tauthoritative\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env.update(
                {
                    "PROJECT_ROOT": str(mixed_root),
                    "PROJECT_NAME": "demo",
                    "DATA_ROOT": str(mixed_root / "data"),
                    "RESULTS_ROOT": str(
                        mixed_root / "data" / "results" / "demo"
                    ),
                    "ACCESSIONS_FILE": str(accessions),
                    "FUNGI_GENOME_ROOT": str(fungi_root),
                    "BACTERIA_GENOME_ROOT": str(bacteria_root),
                    "GENOME_TAXON_MANIFEST": str(manifest),
                    "WORK_ROOT": str(mixed_root / "work"),
                    "NCBI_SCRIPTS_ROOT": str(REPO_ROOT / "scripts" / "ncbi"),
                    "PYTHON_BIN": sys.executable,
                    "DATASETS_CMD": str(root / "missing-datasets"),
                    "RUN_DOWNLOAD": "0",
                    "RUN_RENAME": "1",
                    "RUN_FLATTEN": "0",
                }
            )
            mixed = subprocess.run(
                ["bash", str(PREPARE)],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(mixed.returncode, 0, mixed.stdout + mixed.stderr)
            self.assertEqual(
                (
                    fungi_root / "accessions_fungusID_taxonomyID.txt"
                ).read_bytes(),
                b"GCA_000001.1\tFrozen_Fungus\t162425\t0.00\t"
                b"Aspergillus nidulans\t\t\n",
            )
            self.assertEqual(
                (
                    bacteria_root / "accessions_bacteriaID_taxonomyID.txt"
                ).read_bytes(),
                b"GCF_000002.2\tFrozen_Bacterium\t100226\t0.00\t"
                b"Streptomyces coelicolor\t\t\n",
            )

            empty_root = root / "empty genomes"
            empty_root.mkdir()
            zero = run_renamer(empty_root, "fungi")
            self.assertEqual(zero.returncode, 0, zero.stderr)
            self.assertEqual(zero.stdout, "")
            self.assertEqual(zero.stderr, "")
            self.assertEqual(
                (empty_root / "accessions_fungusID_taxonomyID.txt").read_bytes(),
                b"",
            )

    def test_collision_fails_before_mapping_or_rename(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clusterweave-r10b-collision-") as tmp:
            root = Path(tmp)
            genome_root = root / "genomes"
            for accession in ("GCA_000010.1", "GCA_000011.1"):
                write_ncbi_fixture(
                    genome_root,
                    accession,
                    "Duplicatus species strain Same",
                    123,
                )

            result = run_renamer(genome_root, "fungi")

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertIn(
                "Genome ID collision after taxonomy rename: GCA_000010.1 and "
                "GCA_000011.1 both map to Duplicatus_species_Same",
                result.stderr,
            )
            self.assertFalse(
                (genome_root / "accessions_fungusID_taxonomyID.txt").exists()
            )
            self.assertTrue((genome_root / "GCA_000010.1").is_dir())
            self.assertTrue((genome_root / "GCA_000011.1").is_dir())

    def test_shell_ignores_positional_arguments_as_before(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clusterweave-r10b-argv-") as tmp:
            root = Path(tmp)
            plain_root = root / "plain"
            extra_root = root / "extra"
            for genome_root in (plain_root, extra_root):
                write_ncbi_fixture(
                    genome_root,
                    "GCA_000012.1",
                    "Fungus example isolate ISO-1",
                    456,
                )

            plain = run_renamer(plain_root, "fungi")
            extra = run_renamer(
                extra_root,
                "fungi",
                extra_args=("--ignored", "value"),
            )

            self.assertEqual(plain.returncode, extra.returncode)
            self.assertEqual(plain.stdout, extra.stdout)
            self.assertEqual(plain.stderr, extra.stderr)
            self.assertEqual(
                (
                    plain_root / "accessions_fungusID_taxonomyID.txt"
                ).read_bytes(),
                (
                    extra_root / "accessions_fungusID_taxonomyID.txt"
                ).read_bytes(),
            )

    def test_missing_tracked_helper_fails_without_an_embedded_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clusterweave-r10b-missing-") as tmp:
            root = Path(tmp)
            copied_script = root / "scripts" / "ncbi" / RENAMER.name
            copied_script.parent.mkdir(parents=True)
            copied_script.write_bytes(RENAMER.read_bytes())
            genome_root = root / "genomes"
            genome_root.mkdir()
            env = dict(os.environ)
            env.update(
                {
                    "GENOME_ROOT": str(genome_root),
                    "PYTHON_BIN": sys.executable,
                    "DATASETS_CMD": str(root / "missing-datasets"),
                }
            )

            result = subprocess.run(
                ["bash", str(copied_script)],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            expected = copied_script.with_suffix(".py")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertEqual(
                result.stderr,
                f"ERROR: Missing NCBI genome renamer helper: {expected}\n",
            )
            self.assertFalse(expected.exists())


if __name__ == "__main__":
    unittest.main()
