from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PREPARE = REPO_ROOT / "prepare_genomes_from_accessions.sh"
ROUTE_HEADER = (
    "input_key\tgenome_id\ttaxon_group\ttaxon_source\ttaxid\torganism_name\t"
    "source_accession\tprediction_method\tdetector_profile\tinput_path_key\t"
    "route_status\troute_reason\n"
)


class TaxonAccessionPartitionTests(unittest.TestCase):
    def test_mixed_accessions_run_once_per_nonempty_taxon_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accessions = root / "accessions.txt"
            accessions.write_text("GCA_000001.1\nGCF_000002.2\n", encoding="utf-8")
            results = root / "data" / "results" / "demo"
            manifest = results / "summary_tables" / "genome_taxon_manifest.tsv"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                ROUTE_HEADER
                + "GCA_000001.1\tFungus_A\tfungi\tncbi\t4751\tFungus A\t"
                "GCA_000001.1\tfunannotate\tantismash+funbgcex\tGCA_000001.1\t"
                "accepted\tauthoritative_ncbi_taxonomy\n"
                + "GCF_000002.2\tBacterium_A\tbacteria\tncbi\t2\tBacterium A\t"
                "GCF_000002.2\tprodigal\tantismash\tGCF_000002.2\t"
                "accepted\tauthoritative_ncbi_taxonomy\n",
                encoding="utf-8",
            )
            helpers = root / "helpers"
            helpers.mkdir()
            call_log = root / "calls.tsv"
            stub = """#!/usr/bin/env bash
set -euo pipefail
joined=""
while IFS= read -r accession || [[ -n "${accession}" ]]; do
  [[ -n "${accession}" ]] || continue
  if [[ -n "${joined}" ]]; then joined="${joined},"; fi
  joined="${joined}${accession}"
done < "${ACCESSIONS_FILE}"
printf '%s\\t%s\\t%s\\t%s\\t%s\\n' \
  "$(basename "$0")" "${TAXON_GROUP}" "${joined}" "${GENOME_ROOT}" "${MAPPING_FILE}" \
  >> "${CALL_LOG}"
"""
            for name in (
                "download_ncbi_genomes.sh",
                "rename_ncbi_genomes.sh",
                "flatten_ncbi_genomes.sh",
            ):
                path = helpers / name
                path.write_text(stub, encoding="utf-8")
                path.chmod(0o755)

            fungi_root = root / "data" / "genomes" / "fungi" / "demo"
            bacteria_root = root / "data" / "genomes" / "bacteria" / "demo"
            env = {
                **os.environ,
                "PROJECT_ROOT": str(root),
                "PROJECT_NAME": "demo",
                "DATA_ROOT": str(root / "data"),
                "RESULTS_ROOT": str(results),
                "ACCESSIONS_FILE": str(accessions),
                "FUNGI_GENOME_ROOT": str(fungi_root),
                "BACTERIA_GENOME_ROOT": str(bacteria_root),
                "GENOME_TAXON_MANIFEST": str(manifest),
                "WORK_ROOT": str(root / "work"),
                "NCBI_SCRIPTS_ROOT": str(helpers),
                "CALL_LOG": str(call_log),
                "RUN_DOWNLOAD": "1",
                "RUN_RENAME": "1",
                "RUN_FLATTEN": "1",
            }
            result = subprocess.run(
                ["bash", str(PREPARE)],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [
                line.split("\t")
                for line in call_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 6)
            fungal_rows = [row for row in rows if row[1] == "fungi"]
            bacterial_rows = [row for row in rows if row[1] == "bacteria"]
            self.assertEqual(len(fungal_rows), 3)
            self.assertEqual(len(bacterial_rows), 3)
            self.assertTrue(
                all(row[2] == "GCA_000001.1" for row in fungal_rows)
            )
            self.assertTrue(
                all(row[2] == "GCF_000002.2" for row in bacterial_rows)
            )
            self.assertTrue(all(row[3] == str(fungi_root) for row in fungal_rows))
            self.assertTrue(
                all(row[3] == str(bacteria_root) for row in bacterial_rows)
            )
            self.assertTrue(
                all(
                    row[4].endswith("accessions_fungusID_taxonomyID.txt")
                    for row in fungal_rows
                )
            )
            self.assertTrue(
                all(
                    row[4].endswith("accessions_bacteriaID_taxonomyID.txt")
                    for row in bacterial_rows
                )
            )

    def write_ncbi_fixture(
        self,
        genome_root: Path,
        accession: str,
        organism_name: str,
        taxid: int,
    ) -> None:
        package = (
            genome_root
            / accession
            / "ncbi_dataset"
            / "data"
            / accession
        )
        package.mkdir(parents=True)
        report = {
            "organism": {
                "organismName": organism_name,
                "taxId": taxid,
            },
            "assemblyStats": {"totalSequenceLength": 4},
        }
        (
            genome_root
            / accession
            / "ncbi_dataset"
            / "data"
            / "assembly_data_report.jsonl"
        ).write_text(json.dumps(report) + "\n", encoding="utf-8")
        (package / f"{accession}.fna").write_text(
            ">contig\nACGT\n", encoding="utf-8"
        )

    def test_ncbi_rename_honors_frozen_final_route_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accession = "GCA_000001.1"
            genome_root = root / "fungi"
            self.write_ncbi_fixture(
                genome_root,
                accession,
                "Aspergillus nidulans strain FGSC_A4",
                162425,
            )
            manifest = root / "genome_taxon_manifest.tsv"
            manifest.write_text(
                ROUTE_HEADER
                + f"{accession}\tFrozen_Fungus_ID\tfungi\tncbi\t162425\t"
                f"Aspergillus nidulans\t{accession}\tfunannotate\t"
                "antismash+funbgcex\tGCA_000001.1\taccepted\t"
                "authoritative_ncbi_taxonomy\n",
                encoding="utf-8",
            )
            mapping = genome_root / "accessions_fungusID_taxonomyID.txt"
            env = {
                **os.environ,
                "GENOME_ROOT": str(genome_root),
                "TAXON_GROUP": "fungi",
                "GENOME_TAXON_MANIFEST": str(manifest),
                "MAPPING_FILE": str(mapping),
                "PYTHON_BIN": os.sys.executable,
                "DATASETS_CMD": str(root / "missing-datasets"),
            }

            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "scripts" / "ncbi" / "rename_ncbi_genomes.sh"),
                ],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((genome_root / "Frozen_Fungus_ID").is_dir())
            self.assertFalse((genome_root / accession).exists())
            fields = mapping.read_text(encoding="utf-8").splitlines()[0].split("\t")
            self.assertEqual(fields[0], accession)
            self.assertEqual(fields[1], "Frozen_Fungus_ID")

    def test_ncbi_rename_without_routes_preserves_legacy_fungal_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accession = "GCA_000003.1"
            genome_root = root / "fungi"
            self.write_ncbi_fixture(
                genome_root,
                accession,
                "Amanita muscaria strain 2016PMI152",
                41956,
            )
            missing_manifest = root / "missing_manifest.tsv"
            env = {
                **os.environ,
                "GENOME_ROOT": str(genome_root),
                "TAXON_GROUP": "fungi",
                "GENOME_TAXON_MANIFEST": str(missing_manifest),
                "PYTHON_BIN": os.sys.executable,
                "DATASETS_CMD": str(root / "missing-datasets"),
            }

            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "scripts" / "ncbi" / "rename_ncbi_genomes.sh"),
                ],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            legacy_id = "Amanita_muscaria_2016PMI152"
            self.assertTrue((genome_root / legacy_id).is_dir())
            mapping = genome_root / "accessions_fungusID_taxonomyID.txt"
            fields = mapping.read_text(encoding="utf-8").splitlines()[0].split("\t")
            self.assertEqual(fields[:2], [accession, legacy_id])


    def test_ncbi_rename_without_routes_uses_taxon_neutral_bacterial_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accession = "GCF_000009045.1"
            genome_root = root / "bacteria"
            self.write_ncbi_fixture(
                genome_root,
                accession,
                "Bacillus subtilis strain 168",
                224308,
            )
            mapping = genome_root / "accessions_bacteriaID_taxonomyID.txt"
            env = {
                **os.environ,
                "GENOME_ROOT": str(genome_root),
                "TAXON_GROUP": "bacteria",
                "GENOME_TAXON_MANIFEST": str(root / "missing_manifest.tsv"),
                "MAPPING_FILE": str(mapping),
                "PYTHON_BIN": os.sys.executable,
                "DATASETS_CMD": str(root / "missing-datasets"),
            }

            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "scripts" / "ncbi" / "rename_ncbi_genomes.sh"),
                ],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            genome_id = "Bacillus_subtilis_168"
            self.assertTrue((genome_root / genome_id).is_dir())
            fields = mapping.read_text(encoding="utf-8").splitlines()[0].split("\t")
            self.assertEqual(fields[:2], [accession, genome_id])
            self.assertFalse(fields[1].startswith("bacteria_"))


if __name__ == "__main__":
    unittest.main()
