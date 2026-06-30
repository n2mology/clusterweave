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


if __name__ == "__main__":
    unittest.main()
