from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys
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
        classifiers = "funannotate_predict_failed_in_p2g() {" + text.split(
            "funannotate_predict_failed_in_p2g() {", 1
        )[1].split("should_skip_discovered_stem() {", 1)[0]
        predict = "run_funannotate_predict_to_gbk() {" + text.split(
            "run_funannotate_predict_to_gbk() {", 1
        )[1].split("annotate_genome_with_fallbacks() {", 1)[0]
        with tempfile.TemporaryDirectory(prefix="cluster weave retries ") as tmp:
            root = Path(tmp)
            work = root / "work with spaces"
            results = root / "results with spaces"
            fake_bin = root / "fake bin"
            fake_bin.mkdir()
            (work / "tmp").mkdir(parents=True)
            (work / "logs").mkdir()
            results.mkdir()
            fasta = root / "input with spaces.fna"
            output = root / "output with spaces.gbk"
            recorder = root / "attempts.txt"
            fasta.write_text(">record\n" + "A" * 1200 + "\n", encoding="utf-8")
            funannotate = fake_bin / "funannotate"
            funannotate.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            funannotate.chmod(0o755)
            shell = f"""
set -euo pipefail
WORK_ROOT={shlex.quote(str(work))}
RESULTS_ROOT={shlex.quote(str(results))}
VENV_PY={shlex.quote(sys.executable)}
ANNOTATION_RUNTIME_HELPER={shlex.quote(str(REPO_ROOT / 'bin' / 'annotation_runtime.py'))}
ENGINE=apptainer
FUNANNOTATE_SIF={shlex.quote(str(root / 'missing.sif'))}
FUNANNOTATE_IMAGE_URI=docker://funannotate/test
ANNO_CPUS=4
FUNANNOTATE_BUSCO_SEED_SPECIES=rhizopus_oryzae
FUNANNOTATE_RETRY_WITHOUT_PROTEIN_EVIDENCE=1
FUNANNOTATE_MIN_TRAINING_MODELS_FALLBACK=150
FUNANNOTATE_LAST_FAILURE_STATUS=
FUNANNOTATE_LAST_FAILURE_DETAIL=
ATTEMPT_COUNT=0
ATTEMPT_RECORDER={shlex.quote(str(recorder))}
log() {{ :; }}
warn() {{ :; }}
tool_activity_emit_progress() {{ :; }}
resolve_funannotate_policy() {{
  FUNANNOTATE_RESOLVED_BUSCO_DB=fungi
  FUNANNOTATE_RESOLVED_SPECIES='Rhizopus delemar'
  FUNANNOTATE_RESOLVED_SOURCE=taxonomy:mucorales
}}
validate_funannotate_busco_db() {{ printf '%s\n' "$1"; }}
annotation_runtime_argv() {{
  local argv_file="$WORK_ROOT/tmp/argv"
  "$VENV_PY" "$ANNOTATION_RUNTIME_HELPER" "$@" > "$argv_file"
  mapfile -d '' -t ANNOTATION_RUNTIME_ARGV < "$argv_file"
}}
funannotate_exec() {{
  shift 2
  local input= output= token=
  while [[ "$#" -gt 0 ]]; do
    token="$1"; shift
    case "$token" in
      -i) input="$1"; shift ;;
      -o) output="$1"; shift ;;
    esac
  done
  cp -f "$input" "$output"
}}
funannotate_exec_with_activity() {{
  local fun_log="$4"
  shift 4
  ATTEMPT_COUNT=$((ATTEMPT_COUNT + 1))
  printf '%s\t' "$@" >> "$ATTEMPT_RECORDER"
  printf '\n' >> "$ATTEMPT_RECORDER"
  if [[ "$ATTEMPT_COUNT" -eq 1 ]]; then
    printf '%s\n' \
      '186 BUSCO predictions validated' \
      'ERROR: Not enough gene models 186 to train Augustus (200 required), exiting' \
      'CMD ERROR: diamond blastx --query proteins.fa --db uniprot.dmnd' > "$fun_log"
    return 2
  fi
  if [[ "$ATTEMPT_COUNT" -eq 2 ]]; then
    printf '%s\n' 'CMD ERROR: diamond blastx --query proteins.fa --db uniprot.dmnd' >> "$fun_log"
    return 2
  fi
  local output_dir= token=
  while [[ "$#" -gt 0 ]]; do
    token="$1"; shift
    if [[ "$token" == -o ]]; then output_dir="$1"; shift; else :; fi
  done
  mkdir -p "$output_dir/predict_results"
  printf 'LOCUS fake\n//\n' > "$output_dir/predict_results/result.gbk"
}}
gbk_has_cds_and_translation() {{ return 0; }}
remap_gbk_ids_from_fasta_hashes() {{ return 1; }}
rsync() {{ return 0; }}
{classifiers}
{predict}
run_funannotate_predict_to_gbk {shlex.quote(str('Genome with spaces'))} {shlex.quote(str(fasta))} {shlex.quote(str(output))}
"""
            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
            result = subprocess.run(
                ["bash", "-c", shell],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            attempts = [
                [token for token in line.split("\t") if token]
                for line in recorder.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(attempts), 3)
            self.assertNotIn("--min_training_models", attempts[0])
            self.assertNotIn("--protein_alignments", attempts[0])
            self.assertIn("--min_training_models", attempts[1])
            self.assertNotIn("--protein_alignments", attempts[1])
            self.assertIn("--min_training_models", attempts[2])
            self.assertIn("--protein_alignments", attempts[2])


    def test_missing_funannotate_sif_never_invokes_job_time_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "builder-called"
            builder = root / "build_funannotate.sh"
            builder.write_text(
                "#!/usr/bin/env bash\n"
                f"touch {shlex.quote(str(marker))}\n",
                encoding="utf-8",
            )
            builder.chmod(0o755)
            missing_sif = root / "missing" / "funannotate.sif"
            command = f"""
set -u
log() {{ :; }}
warn() {{ printf '%s\\n' "$*" >&2; }}
ENGINE=apptainer
FUNANNOTATE_SIF={shlex.quote(str(missing_sif))}
FUNANNOTATE_BUILD_SCRIPT={shlex.quote(str(builder))}
AUTO_BUILD_FUNANNOTATE_SIF=1
source <(awk '/^runtime_preparation_hint\\(\\)/{{flag=1}} /^ensure_primary_tooling\\(\\)/{{flag=0}} flag{{print}}' {shlex.quote(str(SCRIPT_PATH))})
ensure_funannotate_sif_runtime
"""
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=str(REPO_ROOT),
                env=dict(os.environ),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            builder_called = marker.exists()

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(builder_called)
        self.assertIn("prepare-runtime", result.stderr)
        self.assertIn("accepted for compatibility", result.stderr)


if __name__ == "__main__":
    unittest.main()
