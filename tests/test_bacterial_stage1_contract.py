from __future__ import annotations

import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class BacterialStageOneContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(
            encoding="utf-8"
        )

    def test_exact_bacteria_prodigal_flags_are_mandatory(self) -> None:
        self.assertIn(
            'local out=(--taxon "${taxon_group}" --genefinding-tool "${genefinding_tool}")',
            self.text,
        )
        self.assertIn(
            'antismash_supported_flags bacteria prodigal',
            self.text,
        )
        self.assertNotIn("out+=(-prodigal)", self.text)
        self.assertNotIn('"${ant_input}" -prodigal', self.text)

    def test_bacterial_route_sanitizes_input_and_skips_funbgcex(self) -> None:
        process = self.text.split("process_genome() {", 1)[1]
        self.assertIn('"${BACTERIAL_GENBANK_SANITIZER}"', process)
        self.assertIn('--record-map "${bacterial_record_map}"', process)
        self.assertIn('bacterial_stage_temp="${staged_gbk}.tmp.${BASHPID:-$$}"', process)
        self.assertIn('mv -f "${bacterial_stage_temp}" "${staged_gbk}"', process)
        self.assertIn('gbk_used="${staged_gbk}"', process)
        self.assertIn('funbgcex_status="not_applicable_taxon"', process)
        funbgcex = process.split("# ---------------- FunBGCeX ----------------", 1)[1]
        self.assertIn('if [[ "${taxon_group}" == "bacteria" ]]', funbgcex)
        self.assertIn("FunBGCeX not applicable to bacterial route", funbgcex)
        self.assertIn(
            'case "${antismash_status}" in',
            funbgcex,
        )
        self.assertIn(
            'ran_ok|ran_ok_sanitized|skipped_done)',
            funbgcex,
        )
        self.assertIn(
            'genome_stage_progress "${genome_id}" "antismash" 100 "BGC detection complete"',
            funbgcex,
        )
        self.assertIn('failed)', funbgcex)
        self.assertIn(
            'genome_stage_progress "${genome_id}" "antismash" 100 "antiSMASH failed"',
            funbgcex,
        )
        self.assertNotIn(
            'genome_stage_progress "${genome_id}" "complete" 100 "BGC detection complete"',
            funbgcex,
        )
        self.assertNotIn(
            'genome_stage_progress "${genome_id}" "funbgcex" 100 '
            '"FunBGCeX not applicable to bacterial taxon"',
            funbgcex,
        )

    def test_record_shards_receive_only_their_isolated_record(self) -> None:
        shard = self.text.split("run_antismash_record_shard() {", 1)[1].split(
            "wait_for_antismash_shard_job() {", 1
        )[0]
        sharded = self.text.split("run_antismash_sharded() {", 1)[1].split(
            "# Per-genome logging sync + manifest", 1
        )[0]
        self.assertIn('"${ant_input}"', shard)
        self.assertNotIn("--limit-to-record", shard)
        self.assertIn('"${ANTISMASH_INPUT_PREPARER}" split-records', sharded)
        self.assertIn('"${shard_inputs[${index}]}"', sharded)
        self.assertNotIn("--start", shard)
        self.assertNotIn("--end", shard)

    def test_private_run_manifest_records_route_and_applicability(self) -> None:
        self.assertIn(
            "funbgcex_status\\ttaxon_group\\tprediction_method\\tdetector_profile"
            "\\tfunbgcex_applicability",
            self.text,
        )

    def test_conflicting_root_region_outputs_fail_instead_of_duplication(self) -> None:
        assembler = self.text.split("run_antismash_sharded() {", 1)[1].split(
            "write_antismash_shard_index()", 1
        )[0]
        self.assertIn('if cmp -s "${region_file}" "${destination}"; then', assembler)
        self.assertIn("conflicting antiSMASH region collision", assembler)

    def test_route_loader_preserves_empty_tsv_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "genome_taxon_manifest.tsv"
            manifest.write_text(
                "input_key\tgenome_id\ttaxon_group\ttaxon_source\ttaxid\t"
                "organism_name\tsource_accession\tprediction_method\t"
                "detector_profile\tinput_path_key\troute_status\troute_reason\n"
                "sample\tBacterium_A\tbacteria\tuser_declaration\t\t\t\t"
                "prodigal\tantismash\tsample\taccepted\ttest_route\n",
                encoding="utf-8",
            )
            route_section = self.text.split(
                'GENOME_MAPPING_FILE="${GENOME_MAPPING_FILE:-', 1
            )[1]
            route_section = (
                'GENOME_MAPPING_FILE="${GENOME_MAPPING_FILE:-'
                + route_section.split("genome_stem_has_file() {", 1)[0]
            )
            shell = (
                "set -euo pipefail\n"
                + f"GENOME_ROOT={shlex.quote(str(root / 'fungi'))}\n"
                + f"FUNGI_GENOME_ROOT={shlex.quote(str(root / 'fungi'))}\n"
                + f"BACTERIA_GENOME_ROOT={shlex.quote(str(root / 'bacteria'))}\n"
                + f"GENOME_TAXON_MANIFEST={shlex.quote(str(manifest))}\n"
                + 'die(){ printf "%s\\n" "$*" >&2; return 1; }\n'
                + route_section
                + "\nload_taxon_routes\n"
                + 'printf "%s|%s|%s|%s|%s\\n" '
                + '"${ROUTE_TAXON_BY_GENOME[Bacterium_A]}" '
                + '"${ROUTE_PREDICTION_BY_GENOME[Bacterium_A]}" '
                + '"${ROUTE_DETECTOR_BY_GENOME[Bacterium_A]}" '
                + '"${ROUTE_SOURCE_BY_GENOME[Bacterium_A]}" '
                + '"${ROUTE_STATUS_BY_GENOME[Bacterium_A]}"\n'
            )
            result = subprocess.run(
                ["bash", "-c", shell],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                "bacteria|prodigal|antismash|user_declaration|accepted",
            )


if __name__ == "__main__":
    unittest.main()
