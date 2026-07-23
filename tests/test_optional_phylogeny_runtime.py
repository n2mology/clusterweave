import csv
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "run_phylogeny.sh"


class OptionalPhylogenyRuntimeTests(unittest.TestCase):
    def run_runner(
        self,
        *,
        requested: bool,
        required: bool,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        results = root / "results"
        env = os.environ.copy()
        env.update(
            {
                "PROJECT_NAME": "demo",
                "DATA_ROOT": str(root / "data"),
                "RESULTS_ROOT": str(results),
                "WORK_ROOT": str(root / "work"),
                "RUN_PHYLOGENY": "1" if requested else "0",
                "PHYLOGENY_REQUIRED": "1" if required else "0",
                "PHYLOGENY_RUNTIME": "docker",
                "PHYLOGENY_DOCKER_IMAGE": "definitely-missing-clusterweave-runtime:1.0.0",
                "CPUS": "2",
                "PHYLOGENY_CPUS": "9",
                "PHYLOGENY_PARALLELISM": "9",
            }
        )
        env.update(extra_env or {})
        completed = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        completed.manifest_path = results / "phylogeny" / "phylogeny_run_manifest.json"  # type: ignore[attr-defined]
        return completed

    def test_not_requested_writes_terminal_manifest_without_runtime(self) -> None:
        completed = self.run_runner(requested=False, required=False)
        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.manifest_path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
        self.assertEqual(payload["status"], "not_requested")
        self.assertEqual(payload["cpus"], 2)
        self.assertEqual(payload["parallelism"], 1)

    def test_direct_runner_hard_caps_untrusted_resource_values(self) -> None:
        completed = self.run_runner(
            requested=False,
            required=False,
            extra_env={
                "PHYLOGENY_MAX_FAMILIES": "999999",
                "PHYLOGENY_MAX_SEQUENCES_PER_FAMILY": "999999",
                "PHYLOGENY_MAX_ALIGNMENT_BYTES": "999999999999",
                "PHYLOGENY_TIMEOUT_SECONDS": "999999999",
                "PHYLOGENY_MAX_RETAINED_SCRATCH_BYTES": "999999999999",
            },
        )
        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.manifest_path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
        self.assertEqual(payload["max_families"], 100)
        self.assertEqual(payload["max_sequences_per_family"], 1000)
        self.assertEqual(payload["max_alignment_bytes"], 200_000_000)
        self.assertEqual(payload["timeout_seconds"], 86_400)
        self.assertEqual(payload["max_retained_scratch_bytes"], 1_000_000_000)
        self.assertRegex(payload["child_memory_limit"], r"^[1-9][0-9]*m$")

    def test_operator_child_cpu_ceiling_clamps_threads(self) -> None:
        completed = self.run_runner(
            requested=False,
            required=False,
            extra_env={
                "CPUS": "8",
                "PHYLOGENY_CPUS": "6",
                "PHYLOGENY_PARALLELISM": "2",
                "CLUSTERWEAVE_CHILD_DOCKER_CPUS": "1.5",
            },
        )
        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.manifest_path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
        self.assertEqual(payload["cpus"], 1)
        self.assertEqual(payload["parallelism"], 1)

    def test_missing_optional_runtime_is_nonfatal_unless_required(self) -> None:
        optional = self.run_runner(requested=True, required=False)
        self.assertEqual(optional.returncode, 0)
        optional_payload = json.loads(optional.manifest_path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
        self.assertEqual(optional_payload["status"], "tool_unavailable")

        required = self.run_runner(requested=True, required=True)
        self.assertNotEqual(required.returncode, 0)
        required_payload = json.loads(required.manifest_path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
        self.assertEqual(required_payload["status"], "tool_unavailable")

    def test_runner_never_uses_unbounded_iqtree_auto_threads_or_job_downloads(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn('iqtree2 -s trimmed.faa -nt "$1"', text)
        self.assertNotIn("-nt AUTO", text)
        self.assertNotIn("pip install", text)
        self.assertNotIn("docker pull", text)
        self.assertNotIn("micromamba install", text)
        self.assertIn('PHYLOGENY_RETAIN_ALIGNMENTS="${PHYLOGENY_RETAIN_ALIGNMENTS:-0}"', text)

    def fake_docker_environment(
        self, *, inference_mode: str
    ) -> tuple[Path, Path, dict[str, str], tempfile.TemporaryDirectory]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        fake_bin = root / "bin"
        fake_bin.mkdir()
        docker = fake_bin / "docker"
        docker.write_text(
            """#!/usr/bin/env bash
set -eu
if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then
  [[ "${3:-}" == "--format" ]] && printf 'sha256:fake-runtime\\n'
  exit 0
fi
if [[ "${1:-}" == "run" ]]; then
  case " $* " in
    *clusterweave-phylogeny-versions*)
      [[ "${FAKE_INFERENCE_MODE:-sleep}" == "preflight-fail" ]] && exit 42
      printf 'MAFFT v7.526; IQ-TREE 2.4.0; trimAl 1.5.0; ETE 4 4.3.0\\n'
      exit 0
      ;;
  esac
  if [[ "${FAKE_INFERENCE_MODE:-sleep}" == "success" || "${FAKE_INFERENCE_MODE:-sleep}" == "success-topology" ]]; then
    work=""
    previous=""
    for argument in "$@"; do
      if [[ "${previous}" == "-v" && "${argument}" == *:/work:rw ]]; then
        work="${argument%:/work:rw}"
      fi
      previous="${argument}"
    done
    printf '(a,b,c);\\n' > "${work}/family.treefile"
    printf 'fake report\\n' > "${work}/family.iqtree"
    printf '>a\\nA\\n>b\\nA\\n>c\\nA\\n' > "${work}/trimmed.faa"
    if [[ "${FAKE_INFERENCE_MODE:-sleep}" == "success-topology" ]]; then
      {
        echo 'gcf_id gene_family_id family_tree_id comparison_status topology_discordance topology_support topology_support_method tree_method alignment_method trimming_method model_selection model tree_sequence_count tree_taxon_count fungal_sequence_count bacterial_sequence_count outgroup_status tree_tool_version alignment_tool_version comparator_version schema_version'
        echo 'GCF_SHARED family_one tree_one supported_domain_topology_discordance supported 95 IQ-TREE_2_ultrafast_bootstrap_ETE4_unrooted_domain_split IQ-TREE_2_maximum_likelihood MAFFT_7.526 trimAl_automated1 MFP LG+F+G4 4 2 2 2 unrooted_no_directional_inference IQ-TREE_2.4.0 MAFFT_7.526 ETE_4_4.3.0 clusterweave-ete4-domain-topology-v1'
      } | tr ' ' '\t' > "${work}/topology_comparison.tsv"
    fi
    exit 0
  fi
  sleep 30
fi
""",
            encoding="utf-8",
        )
        docker.chmod(0o755)

        input_root = root / "inputs"
        input_root.mkdir()
        family = input_root / "family.faa"
        family.write_text(">a\nAAAA\n>b\nAAAA\n>c\nAAAA\n", encoding="utf-8")
        manifest = input_root / "families.tsv"
        manifest.write_text(
            f"family_id\ttaxon_group\tinput_path\nfamily one\tbacteria\t{family}\n",
            encoding="utf-8",
        )
        results = root / "results"
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fake_bin}:{env.get('PATH', '')}",
                "PROJECT_NAME": "demo",
                "DATA_ROOT": str(root / "data"),
                "RESULTS_ROOT": str(results),
                "WORK_ROOT": str(root / "work"),
                "PHYLOGENY_INPUT_ROOT": str(input_root),
                "PHYLOGENY_FAMILY_MANIFEST": str(manifest),
                "RUN_PHYLOGENY": "1",
                "PHYLOGENY_REQUIRED": "0",
                "PHYLOGENY_RUNTIME": "docker",
                "PHYLOGENY_DOCKER_IMAGE": "fake-runtime:1.0.0",
                # Keep the intentional sleep-mode timeout fast, while giving
                # successful fake runs enough headroom under full-suite load.
                "PHYLOGENY_TIMEOUT_SECONDS": (
                    "1" if inference_mode == "sleep" else "5"
                ),
                "CPUS": "2",
                "PHYLOGENY_CPUS": "1",
                "PHYLOGENY_PARALLELISM": "1",
                # This fixture supplies its own bounded families.tsv.
                "PHYLOGENY_AUTO_PREPARE": "0",
                "FAKE_INFERENCE_MODE": inference_mode,
            }
        )
        return root, results, env, temp

    def test_runtime_version_preflight_failure_has_terminal_state(self) -> None:
        _, results, env, _ = self.fake_docker_environment(inference_mode="preflight-fail")
        stale_topology = results / "phylogeny" / "topology_comparison.tsv"
        stale_topology.parent.mkdir(parents=True, exist_ok=True)
        stale_topology.write_text("stale topology must not survive\n", encoding="utf-8")
        completed = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0)
        payload = json.loads(
            (results / "phylogeny" / "phylogeny_run_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["status"], "tool_unavailable")
        self.assertIn("version preflight", payload["message"])
        self.assertFalse(stale_topology.exists())

    def test_family_timeout_is_distinct_and_optional(self) -> None:
        root, results, env, _ = self.fake_docker_environment(inference_mode="sleep")
        completed = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0)
        payload = json.loads(
            (results / "phylogeny" / "phylogeny_run_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["families"][0]["status"], "timeout")
        work_root = root / "work" / "phylogeny"
        self.assertEqual(
            [path.name for path in work_root.iterdir() if path.is_dir()],
            ["logs"],
        )

    def test_required_empty_manifest_and_missing_topology_fail(self) -> None:
        root, results, env, _ = self.fake_docker_environment(inference_mode="success")
        manifest = root / "inputs" / "families.tsv"
        manifest.write_text("family_id\ttaxon_group\tinput_path\n", encoding="utf-8")
        env["PHYLOGENY_REQUIRED"] = "1"
        env["PHYLOGENY_TIMEOUT_SECONDS"] = "10"
        empty = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        self.assertNotEqual(empty.returncode, 0)
        payload = json.loads(
            (results / "phylogeny" / "phylogeny_run_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["status"], "insufficient_data")

        family = root / "inputs" / "family.faa"
        mapping = root / "inputs" / "sequence_taxon_map.tsv"
        mapping.write_text(
            "sequence_id\tfamily_id\ttaxon_group\n"
            "a\tfamily_one\tfungi\n"
            "b\tfamily_one\tfungi\n"
            "c\tfamily_one\tbacteria\n",
            encoding="utf-8",
        )
        manifest.write_text(
            "family_id\ttaxon_group\tinput_path\tsequence_map_path\tgcf_id\tannotation_key\n"
            f"family_one\tboth\t{family}\t{mapping}\tGCF_SHARED\tsmcog:SMCOG1046\n",
            encoding="utf-8",
        )
        missing_topology = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        self.assertNotEqual(missing_topology.returncode, 0)
        payload = json.loads(
            (results / "phylogeny" / "phylogeny_run_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["status"], "success_with_optional_failures")
        self.assertEqual(payload["families"][0]["topology_status"], "unavailable")

    def test_cancel_file_terminates_active_process_group(self) -> None:
        root, results, env, _ = self.fake_docker_environment(inference_mode="sleep")
        cancel_file = root / "cancel"
        env["CLUSTERWEAVE_CANCEL_FILE"] = str(cancel_file)
        env["PHYLOGENY_TIMEOUT_SECONDS"] = "30"
        process = subprocess.Popen(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.5)
        cancel_file.touch()
        process.communicate(timeout=10)
        self.assertEqual(process.returncode, 130)
        payload = json.loads(
            (results / "phylogeny" / "phylogeny_run_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["status"], "cancelled")

    def test_success_keeps_alignment_private_by_default(self) -> None:
        _, results, env, _ = self.fake_docker_environment(inference_mode="success")
        completed = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0)
        payload = json.loads(
            (results / "phylogeny" / "phylogeny_run_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["status"], "success")
        result_files = [path.name for path in (results / "phylogeny").rglob("*") if path.is_file()]
        self.assertTrue(any(name.endswith(".treefile") for name in result_files))
        self.assertFalse(any(name.endswith(".faa") for name in result_files))

    def test_success_collects_only_scalar_topology_summary_from_fake_runtime(self) -> None:
        root, results, env, _ = self.fake_docker_environment(
            inference_mode="success-topology"
        )
        input_root = root / "inputs"
        mapping = input_root / "sequence_taxon_map.tsv"
        mapping.write_text(
            "sequence_id\tfamily_id\ttaxon_group\n"
            "a\tfamily_one\tfungi\n"
            "b\tfamily_one\tfungi\n"
            "c\tfamily_one\tbacteria\n",
            encoding="utf-8",
        )
        family = input_root / "family.faa"
        (input_root / "families.tsv").write_text(
            "family_id\ttaxon_group\tinput_path\tsequence_map_path\tgcf_id\tannotation_key\n"
            f"family_one\tboth\t{family}\t{mapping}\tGCF_SHARED\tsmcog:SMCOG1046\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("TOPOLOGY_COMPARISON family=", completed.stdout)
        topology = results / "phylogeny" / "topology_comparison.tsv"
        self.assertTrue(topology.is_file())
        with topology.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["topology_discordance"], "supported")
        payload = json.loads(
            (results / "phylogeny" / "phylogeny_run_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(payload["topology_comparison_count"], 1)

    def test_requested_run_auto_prepares_annotated_cross_domain_family_before_runtime(self) -> None:
        root, results, env, _ = self.fake_docker_environment(
            inference_mode="success-topology"
        )
        # Remove the explicit-manifest override: RUN_PHYLOGENY=1 must be enough
        # to trigger preparation for a normal eligible job.
        env.pop("PHYLOGENY_AUTO_PREPARE")
        candidates = root / "candidates.tsv"
        candidates.write_text(
            "candidate_id\tgcf_id\tcross_domain_gcf\n"
            "GCF_SHARED\tGCF_SHARED\tyes\n",
            encoding="utf-8",
        )
        crosswalk = root / "crosswalk.tsv"
        rows = [
            ("fungus_a", "fungi"),
            ("fungus_b", "fungi"),
            ("bacterium_a", "bacteria"),
            ("bacterium_b", "bacteria"),
        ]
        crosswalk.write_text(
            "genome\ttaxon_group\tantismash_region\tgcf_id\n"
            + "".join(
                f"{genome}\t{taxon}\tregion001\tGCF_SHARED\n"
                for genome, taxon in rows
            ),
            encoding="utf-8",
        )
        antismash = root / "antismash"
        for genome, _ in rows:
            region = antismash / genome / "region001.gbk"
            region.parent.mkdir(parents=True)
            region.write_text(
                "LOCUS       fixture 36 bp DNA linear UNK 01-JAN-2026\n"
                "FEATURES             Location/Qualifiers\n"
                "     CDS             1..36\n"
                f'                     /locus_tag="{genome}_core"\n'
                '                     /smCOG="SMCOG1046: aminotransferase (Score: 42)"\n'
                '                     /translation="MSTNPKPQRKTK"\n'
                "ORIGIN\n"
                "        1 atgagcacca acccaaaacc acaacgaaaa ccaaa\n"
                "//\n",
                encoding="utf-8",
            )
        env.update(
            {
                "PHYLOGENY_TIMEOUT_SECONDS": "10",
                "PHYLOGENY_AUTO_SELECT_CANDIDATES": "0",
                "PHYLOGENY_CANDIDATES_TSV": str(candidates),
                "PHYLOGENY_CROSSWALK_TSV": str(crosswalk),
                "PHYLOGENY_ANTISMASH_ROOT": str(antismash),
            }
        )
        completed = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("phase=prepare", completed.stdout)
        with (root / "inputs" / "families.tsv").open(
            newline="", encoding="utf-8"
        ) as handle:
            families = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(families), 1)
        self.assertEqual(families[0]["taxon_group"], "both")
        payload = json.loads(
            (results / "phylogeny" / "phylogeny_run_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(payload["auto_prepare"])
        self.assertEqual(payload["status"], "success")


if __name__ == "__main__":
    unittest.main()
