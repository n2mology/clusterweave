from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "run_annotation_and_detection.sh"


class AnnotationLineagePolicyTests(unittest.TestCase):
    def resolve_policy(self, genome_id: str, mapping_text: str, env: dict[str, str] | None = None) -> tuple[str, str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            genome_root = Path(tmp)
            (genome_root / "accessions_fungusID_taxonomyID.txt").write_text(mapping_text, encoding="utf-8")
            run_env = dict(os.environ)
            run_env.update(env or {})
            run_env["GENOME_ROOT"] = str(genome_root)
            command = f"""
set -euo pipefail
source <(awk '/^GENOME_MAPPING_FILE=/{{flag=1}} /^funannotate_busco_db_available\\(\\)/{{flag=0}} flag{{print}}' {shlex.quote(str(SCRIPT_PATH))})
resolve_funannotate_policy {shlex.quote(genome_id)}
printf '%s\t%s\t%s\n' "$FUNANNOTATE_RESOLVED_BUSCO_DB" "$FUNANNOTATE_RESOLVED_SPECIES" "$FUNANNOTATE_RESOLVED_SOURCE"
"""
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=str(REPO_ROOT),
                env=run_env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return tuple(result.stdout.strip().split("\t"))  # type: ignore[return-value]

    def parse_funannotate_failure_status(self, log_text: str) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "funannotate.log"
            log_path.write_text(log_text, encoding="utf-8")
            command = f"""
set -euo pipefail
source <(awk '/^GENOME_MAPPING_FILE=/{{flag=1}} /^should_skip_discovered_stem\\(\\)/{{flag=0}} flag{{print}}' {shlex.quote(str(SCRIPT_PATH))})
funannotate_predict_failure_status {shlex.quote(str(log_path))}
"""
            run_env = dict(os.environ)
            run_env["GENOME_ROOT"] = tmp
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=str(REPO_ROOT),
                env=run_env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return tuple(result.stdout.strip().split("\t"))  # type: ignore[return-value]

    def eligible_training_fallback(
        self, log_text: str, configured_floor: str | None = None
    ) -> str | None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "funannotate.log"
            log_path.write_text(log_text, encoding="utf-8")
            command = f"""
set -euo pipefail
source <(awk '/^GENOME_MAPPING_FILE=/{{flag=1}} /^should_skip_discovered_stem\\(\\)/{{flag=0}} flag{{print}}' {shlex.quote(str(SCRIPT_PATH))})
funannotate_busco_training_fallback_threshold {shlex.quote(str(log_path))}
"""
            run_env = dict(os.environ)
            run_env["GENOME_ROOT"] = tmp
            if configured_floor is not None:
                run_env["FUNANNOTATE_MIN_TRAINING_MODELS_FALLBACK"] = configured_floor
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=str(REPO_ROOT),
                env=run_env,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip()

    def p2g_failure_detected(self, log_text: str) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "funannotate.log"
            log_path.write_text(log_text, encoding="utf-8")
            command = f"""
set -euo pipefail
source <(awk '/^GENOME_MAPPING_FILE=/{{flag=1}} /^should_skip_discovered_stem\\(\\)/{{flag=0}} flag{{print}}' {shlex.quote(str(SCRIPT_PATH))})
funannotate_predict_failed_in_p2g {shlex.quote(str(log_path))}
"""
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=str(REPO_ROOT),
                env=dict(os.environ, GENOME_ROOT=tmp),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return result.returncode == 0

    def public_tool_activity_message(self, tool: str, line: str) -> tuple[int, str]:
        command = f"""
set -euo pipefail
source <(awk '/^tool_activity_public_message\\(\\)/{{flag=1}} /^tool_activity_emit_progress\\(\\)/{{flag=0}} flag{{print}}' {shlex.quote(str(SCRIPT_PATH))})
if message="$(tool_activity_public_message {shlex.quote(tool)} {shlex.quote(line)})"; then
  printf '0\t%s\n' "$message"
else
  printf '1\t\n'
fi
"""
        result = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(REPO_ROOT),
            env=dict(os.environ),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        status, message = result.stdout.rstrip("\n").split("\t", 1)
        return int(status), message

    def test_ascomycota_lineage_uses_configured_dataset_and_binomial_species(self) -> None:
        policy = self.resolve_policy(
            "Aspergillus_nidulans_FGSC_A4",
            "GCA_000011425.1\tAspergillus_nidulans_FGSC_A4\t227321\t30.10\t"
            "Aspergillus nidulans FGSC A4\t1,131567,2759,33154,4751,451864,4890,227321\t"
            "cellular organisms|Eukaryota|Fungi|Dikarya|Ascomycota|Aspergillus nidulans\n",
            {
                "FUNANNOTATE_BUSCO_DB": "auto",
                "FUNANNOTATE_ORGANISM_NAME": "auto",
                "FUNANNOTATE_BUSCO_DB_ASCOMYCOTA": "ascomycota",
            },
        )

        self.assertEqual(policy, ("ascomycota", "Aspergillus nidulans", "taxonomy:ascomycota"))

    def test_ascomycota_lineage_prefers_funannotate_compatible_dataset_by_default(self) -> None:
        policy = self.resolve_policy(
            "Darksidea_phi_DS919",
            "GCA_030770425.1\tDarksidea_phi_DS919\t2704583\t52.17\t"
            "Darksidea phi\t1,131567,2759,33154,4751,451864,4890,2704583\t"
            "Eukaryota|Fungi|Ascomycota|Darksidea|Darksidea phi\n",
            {"FUNANNOTATE_BUSCO_DB": "auto", "FUNANNOTATE_ORGANISM_NAME": "auto"},
        )

        self.assertEqual(policy, ("ascomycota", "Darksidea phi", "taxonomy:ascomycota"))

    def test_mucorales_lineage_uses_broad_fungi_dataset_by_default(self) -> None:
        policy = self.resolve_policy(
            "Rhizopus_delemar_Type_I_NRRL_21789",
            "GCA_000149305.1\tRhizopus_delemar_Type_I_NRRL_21789\t246409\t45.28\t"
            "Rhizopus delemar Type I NRRL 21789\t1,131567,2759,33154,4751,1913637,4827,246409\t"
            "Eukaryota|Fungi|Mucoromycota|Mucorales|Rhizopus delemar\n",
            {"FUNANNOTATE_BUSCO_DB": "auto", "FUNANNOTATE_ORGANISM_NAME": "auto"},
        )

        self.assertEqual(policy, ("fungi", "Rhizopus delemar", "taxonomy:mucorales"))

    def test_mucoromycota_lineage_uses_broad_fungi_dataset_by_default(self) -> None:
        policy = self.resolve_policy(
            "Mucoromycota_upload",
            "GCA_000000002.1\tMucoromycota_upload\t1913637\t45.28\t"
            "Mucoromycota sp. isolate\t1,131567,2759,33154,4751,1913637\t"
            "Eukaryota|Fungi|Mucoromycota\n",
            {"FUNANNOTATE_BUSCO_DB": "auto", "FUNANNOTATE_ORGANISM_NAME": "auto"},
        )

        self.assertEqual(policy, ("fungi", "Mucoromycota sp", "taxonomy:mucoromycota"))


    def test_annotation_fallback_carries_specific_funannotate_failure_status(self) -> None:
        status, detail = self.run_annotation_fallback_probe()

        self.assertEqual(status, "funannotate_busco_training_insufficient")
        self.assertIn("validated_busco_models=153", detail)
        self.assertIn("policy=taxonomy:mucorales", detail)

    def test_no_taxonomy_ignores_auto_lineage_and_uses_broad_fallback(self) -> None:
        policy = self.resolve_policy(
            "Manual_upload_Af293",
            "",
            {
                "FUNANNOTATE_BUSCO_DB": "auto",
                "FUNANNOTATE_ORGANISM_NAME": "auto",
                "FUNANNOTATE_BUSCO_DB_NO_TAXONOMY": "auto-lineage",
            },
        )

        self.assertEqual(policy, ("dikarya", "Manual upload", "fallback:no-taxonomy"))

    def test_explicit_admin_values_are_preserved(self) -> None:
        policy = self.resolve_policy(
            "Cryptococcus_neoformans",
            "GCA_000000001.1\tCryptococcus_neoformans\t5207\t18.90\t"
            "Cryptococcus neoformans var. grubii\t1,131567,2759,33154,4751,451864,5204,5207\n",
            {
                "FUNANNOTATE_BUSCO_DB": "basidiomycota_odb10",
                "FUNANNOTATE_ORGANISM_NAME": "Cryptococcus neoformans",
            },
        )

        self.assertEqual(policy, ("basidiomycota_odb10", "Cryptococcus neoformans", "explicit"))

    def run_annotation_fallback_probe(self) -> tuple[str, str]:
        command = f"""
set -euo pipefail
source <(awk '/^GENOME_MAPPING_FILE=/{{flag=1}} /^ANTISMASH_FLAGS_CANDIDATES=/{{flag=0}} flag{{print}}' {shlex.quote(str(SCRIPT_PATH))})
run_funannotate_predict_to_gbk() {{
  FUNANNOTATE_LAST_FAILURE_STATUS="funannotate_busco_training_insufficient"
  FUNANNOTATE_LAST_FAILURE_DETAIL="validated_busco_models=153 required_training_models=200 busco_db=fungi policy=taxonomy:mucorales"
  return 2
}}
ANNOTATION_FALLBACK_ORDER=funannotate
if annotate_genome_with_fallbacks Rhizopus_delemar /tmp/rhizopus.fna /tmp/rhizopus.gbk; then
  exit 1
fi
printf '%s\t%s\n' "$ANNOTATION_FALLBACK_FAILURE_REASON" "$ANNOTATION_FALLBACK_FAILURE_DETAIL"
"""
        result = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(REPO_ROOT),
            env=dict(os.environ, GENOME_ROOT="/tmp"),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return tuple(result.stdout.strip().split("\t"))  # type: ignore[return-value]

    def test_funannotate_busco_training_failure_is_classified(self) -> None:
        status, detail = self.parse_funannotate_failure_status(
            "153 BUSCO predictions validated\n"
            "ERROR: Not enough gene models 153 to train Augustus (200 required), exiting\n"
        )

        self.assertEqual(status, "funannotate_busco_training_insufficient")
        self.assertEqual(detail, "validated_busco_models=153 required_training_models=200")

    def test_busco_training_fallback_accepts_qualified_186_of_200_models(self) -> None:
        threshold = self.eligible_training_fallback(
            "186 BUSCO predictions validated\n"
            "ERROR: Not enough gene models 186 to train Augustus (200 required), exiting\n"
        )

        self.assertEqual(threshold, "150")

    def test_busco_training_fallback_rejects_validated_count_below_floor(self) -> None:
        threshold = self.eligible_training_fallback(
            "149 BUSCO predictions validated\n"
            "ERROR: Not enough gene models 149 to train Augustus (200 required), exiting\n"
        )

        self.assertIsNone(threshold)

    def test_busco_training_fallback_floor_is_safely_clamped_below_default(self) -> None:
        threshold = self.eligible_training_fallback(
            "199 BUSCO predictions validated\n"
            "ERROR: Not enough gene models 199 to train Augustus (200 required), exiting\n",
            configured_floor="0200",
        )

        self.assertEqual(threshold, "199")

    def test_p2g_classifier_ignores_generic_protein_alignment_path(self) -> None:
        self.assertFalse(
            self.p2g_failure_detected(
                "Existing protein alignments: /work/predict_misc/protein_alignments.gff3\n"
                "186 BUSCO predictions validated\n"
            )
        )

    def test_p2g_classifier_accepts_actual_diamond_command_error(self) -> None:
        self.assertTrue(
            self.p2g_failure_detected(
                "CMD ERROR: diamond blastx --query proteins.fa --db uniprot.dmnd\n"
            )
        )

    def test_public_activity_does_not_report_zero_failed_counter_as_error(self) -> None:
        status, message = self.public_tool_activity_message(
            "funannotate",
            "Progress: 309221 complete, 0 failed, 6448 remaining",
        )

        self.assertEqual(status, 1)
        self.assertEqual(message, "")

    def test_public_activity_still_reports_actual_funannotate_error(self) -> None:
        status, message = self.public_tool_activity_message(
            "funannotate",
            "ERROR: command failed with an exception",
        )

        self.assertEqual(status, 0)
        self.assertEqual(message, "funannotate reported an error")

    def test_training_fallback_is_checked_before_p2g_retry(self) -> None:
        text = SCRIPT_PATH.read_text(encoding="utf-8")
        retry_block = text.split("local predict_succeeded=0", 1)[1].split(
            'pred_gbk="$(find', 1
        )[0]

        self.assertLess(
            retry_block.index("funannotate_busco_training_fallback_threshold"),
            retry_block.index("funannotate_predict_failed_in_p2g"),
        )
        self.assertIn('--min_training_models "${training_fallback_floor}"', retry_block)


if __name__ == "__main__":
    unittest.main()
