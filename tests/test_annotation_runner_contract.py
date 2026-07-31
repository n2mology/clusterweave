from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "run_annotation_and_detection.sh"
ROUTE_HEADER = (
    "input_key\tgenome_id\ttaxon_group\ttaxon_source\ttaxid\torganism_name\t"
    "source_accession\tprediction_method\tdetector_profile\tinput_path_key\t"
    "route_status\troute_reason\n"
)


class AnnotationRunnerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner_text = RUNNER.read_text(encoding="utf-8")
        route_tail = cls.runner_text.split(
            'GENOME_MAPPING_FILE="${GENOME_MAPPING_FILE:-', 1
        )[1]
        cls.input_boundary = (
            'GENOME_MAPPING_FILE="${GENOME_MAPPING_FILE:-'
            + route_tail.split(
                "###############################################################################\n"
                "# GBK checks",
                1,
            )[0]
        )
        cls.sync_logs = (
            "sync_logs_genome() {"
            + cls.runner_text.split("sync_logs_genome() {", 1)[1].split(
                "\n}", 1
            )[0]
            + "\n}\n"
        )

    @classmethod
    def shell_function(cls, name: str) -> str:
        marker = f"{name}() {{"
        return (
            marker
            + cls.runner_text.split(marker, 1)[1].split("\n}", 1)[0]
            + "\n}\n"
        )

    def run_input_boundary(
        self,
        *,
        fungi_root: Path,
        bacteria_root: Path,
        manifest: Path,
        mapping: Path,
        commands: str,
    ) -> subprocess.CompletedProcess[str]:
        shell = (
            "set -euo pipefail\n"
            + f"GENOME_ROOT={shlex.quote(str(fungi_root))}\n"
            + f"FUNGI_GENOME_ROOT={shlex.quote(str(fungi_root))}\n"
            + f"BACTERIA_GENOME_ROOT={shlex.quote(str(bacteria_root))}\n"
            + f"GENOME_TAXON_MANIFEST={shlex.quote(str(manifest))}\n"
            + f"GENOME_MAPPING_FILE={shlex.quote(str(mapping))}\n"
            + f"SCRIPT_DIR={shlex.quote(str(REPO_ROOT))}\n"
            + f"VENV_PY={shlex.quote(sys.executable)}\n"
            + 'warn(){ printf "%s\\n" "$*" >&2; }\n'
            + 'die(){ printf "%s\\n" "$*" >&2; return 1; }\n'
            + self.input_boundary
            + "\n"
            + commands
        )
        return subprocess.run(
            ["bash", "-c", shell],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_manifest_routes_are_frozen_filtered_and_sorted_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cluster weave r11a ") as tmp:
            root = Path(tmp)
            fungi_root = root / "fungal inputs"
            bacteria_root = root / "bacterial inputs"
            fungi_root.mkdir()
            bacteria_root.mkdir()
            manifest = root / "route manifest.tsv"
            manifest.write_text(
                ROUTE_HEADER
                + "z\tZeta_Fungus\tFUNGI\t\t\t\t\t\t\tz\taccepted\tok\n"
                + "ignored\tIgnored\tfungi\tuser\t\t\t\tfunannotate\t"
                "antismash+funbgcex\tignored\trejected\tbad\n"
                + "a\tAlpha_Bacterium\tBACTERIA\tncbi\t2\tAlpha bacterium\t"
                "GCF_1\tprodigal\tantismash\ta\taccepted\tok\n",
                encoding="utf-8",
            )
            result = self.run_input_boundary(
                fungi_root=fungi_root,
                bacteria_root=bacteria_root,
                manifest=manifest,
                mapping=fungi_root / "mapping.tsv",
                commands=(
                    "load_taxon_routes\n"
                    "discover_stems\n"
                    'printf "META|%s|%s|%s\\n" '
                    '"${ROUTE_MANIFEST_ACTIVE}" "${HAS_FUNGAL_ROUTES}" '
                    '"${HAS_BACTERIAL_ROUTES}"\n'
                    'printf "A|%s|%s|%s|%s|%s|%s\\n" '
                    '"$(route_taxon_for_genome Alpha_Bacterium)" '
                    '"$(route_root_for_genome Alpha_Bacterium)" '
                    '"$(route_prediction_for_genome Alpha_Bacterium)" '
                    '"$(route_detector_for_genome Alpha_Bacterium)" '
                    '"$(route_source_for_genome Alpha_Bacterium)" '
                    '"$(route_status_for_genome Alpha_Bacterium)"\n'
                    'printf "Z|%s|%s|%s|%s|%s|%s\\n" '
                    '"$(route_taxon_for_genome Zeta_Fungus)" '
                    '"$(route_root_for_genome Zeta_Fungus)" '
                    '"$(route_prediction_for_genome Zeta_Fungus)" '
                    '"$(route_detector_for_genome Zeta_Fungus)" '
                    '"$(route_source_for_genome Zeta_Fungus)" '
                    '"$(route_status_for_genome Zeta_Fungus)"\n'
                ),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.splitlines(),
                [
                    "Alpha_Bacterium",
                    "Zeta_Fungus",
                    "META|1|1|1",
                    f"A|bacteria|{bacteria_root}|prodigal|antismash|ncbi|accepted",
                    (
                        f"Z|fungi|{fungi_root}|funannotate|antismash+funbgcex|"
                        "legacy_default|accepted"
                    ),
                ],
            )

    def test_duplicate_frozen_genome_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fungi_root = root / "fungi"
            bacteria_root = root / "bacteria"
            fungi_root.mkdir()
            bacteria_root.mkdir()
            manifest = root / "manifest.tsv"
            manifest.write_text(
                ROUTE_HEADER
                + "a\tSame\tfungi\tuser\t\t\t\tfunannotate\t"
                "antismash+funbgcex\ta\taccepted\tok\n"
                + "b\tSame\tbacteria\tuser\t\t\t\tprodigal\t"
                "antismash\tb\taccepted\tok\n",
                encoding="utf-8",
            )
            result = self.run_input_boundary(
                fungi_root=fungi_root,
                bacteria_root=bacteria_root,
                manifest=manifest,
                mapping=fungi_root / "mapping.tsv",
                commands="load_taxon_routes\n",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "Duplicate genome_id in canonical taxon manifest: Same",
                result.stderr,
            )

    def test_legacy_discovery_filters_only_materialized_accession_aliases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cluster weave r11a ") as tmp:
            root = Path(tmp)
            fungi_root = root / "fungal inputs"
            bacteria_root = root / "bacterial inputs"
            fungi_root.mkdir()
            bacteria_root.mkdir()
            (fungi_root / "GCA_000001.1.fna").write_text(">a\nACGT\n")
            (fungi_root / "Canonical One.gbk").write_text("LOCUS\n//\n")
            (fungi_root / "GCA_000002.1.fa").write_text(">b\nACGT\n")
            (fungi_root / "ordinary.fasta").write_text(">c\nACGT\n")
            symlink_target = root / "linked target.fna"
            symlink_target.write_text(">linked\nACGT\n", encoding="utf-8")
            (fungi_root / "linked.fna").symlink_to(symlink_target)
            mapping = fungi_root / "mapping.tsv"
            mapping.write_text(
                "GCA_000001.1\tCanonical One\t1\n"
                "GCA_000002.1\tMissing Canonical\t2\n",
                encoding="utf-8",
            )
            result = self.run_input_boundary(
                fungi_root=fungi_root,
                bacteria_root=bacteria_root,
                manifest=root / "missing.tsv",
                mapping=mapping,
                commands=(
                    "load_taxon_routes\n"
                    "discover_stems\n"
                    'printf "META|%s|%s|%s\\n" '
                    '"${ROUTE_MANIFEST_ACTIVE}" "${HAS_FUNGAL_ROUTES}" '
                    '"${HAS_BACTERIAL_ROUTES}"\n'
                ),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.splitlines(),
                ["Canonical One", "GCA_000002.1", "ordinary", "META|0|1|0"],
            )
            self.assertIn(
                "skipping accession alias genome stem: GCA_000001.1 maps to "
                "existing Canonical One",
                result.stderr,
            )

    def test_zero_input_discovery_is_empty_and_resolution_order_is_stable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cluster weave r11a ") as tmp:
            root = Path(tmp)
            fungi_root = root / "fungal inputs"
            bacteria_root = root / "bacterial inputs"
            fungi_root.mkdir()
            bacteria_root.mkdir()
            empty = self.run_input_boundary(
                fungi_root=fungi_root,
                bacteria_root=bacteria_root,
                manifest=root / "missing.tsv",
                mapping=fungi_root / "missing.tsv",
                commands="load_taxon_routes\ndiscover_stems\n",
            )
            self.assertEqual(empty.returncode, 0, empty.stderr)
            self.assertEqual(empty.stdout, "")

            for filename in (
                "sample.fna",
                "sample.fa",
                "sample.fsa",
                "sample.fasta",
                "sample.gbk",
                "sample.gb",
                "sample.gbff",
            ):
                (fungi_root / filename).write_text("x\n", encoding="utf-8")
            resolved = self.run_input_boundary(
                fungi_root=fungi_root,
                bacteria_root=bacteria_root,
                manifest=root / "missing.tsv",
                mapping=fungi_root / "missing.tsv",
                commands=(
                    'printf "%s\\n" "$(resolve_fasta_for_stem sample)"\n'
                    'printf "%s\\n" "$(resolve_genbank_for_stem sample)"\n'
                ),
            )
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            self.assertEqual(
                resolved.stdout.splitlines(),
                [str(fungi_root / "sample.fna"), str(fungi_root / "sample.gbk")],
            )

    def test_detailed_logs_publish_under_private_results_logs_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cluster weave r11a ") as tmp:
            root = Path(tmp)
            work_root = root / "work"
            results_root = root / "results"
            (work_root / "logs").mkdir(parents=True)
            (work_root / "logs" / "Genome A.tool.log").write_text(
                "private detail\n", encoding="utf-8"
            )
            shell = (
                "set -euo pipefail\n"
                + f"WORK_ROOT={shlex.quote(str(work_root))}\n"
                + f"RESULTS_ROOT={shlex.quote(str(results_root))}\n"
                + self.sync_logs
                + "\nsync_logs_genome 'Genome A'\n"
            )
            result = subprocess.run(
                ["bash", "-c", shell],
                cwd=REPO_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (results_root / "logs" / "Genome A.tool.log").read_text(
                    encoding="utf-8"
                ),
                "private detail\n",
            )
            self.assertFalse((results_root / "summary_tables" / "logs").exists())

    def test_bacterial_runner_records_bounded_argv_and_order_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cluster weave r11c ") as tmp:
            root = Path(tmp)
            fake_bin = root / "fake tools"
            fungi_root = root / "fungal inputs"
            bacteria_root = root / "bacterial inputs"
            results_root = root / "results with spaces"
            work_root = root / "work with spaces"
            fake_bin.mkdir()
            fungi_root.mkdir()
            bacteria_root.mkdir()
            recorder = root / "recorded commands.jsonl"

            genome_ids = ["Alpha_Bacterium", "Beta_Bacterium"]
            for genome_id in genome_ids:
                (bacteria_root / f"{genome_id}.fna").write_text(
                    f">{genome_id}\n" + "A" * 1200 + "\n",
                    encoding="utf-8",
                )
            manifest = results_root / "summary_tables" / "genome_taxon_manifest.tsv"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                ROUTE_HEADER
                + "a\tAlpha_Bacterium\tbacteria\tuser\t2\tAlpha bacterium\t\t"
                "prodigal\tantismash\ta\taccepted\ttest\n"
                + "b\tBeta_Bacterium\tbacteria\tuser\t3\tBeta bacterium\t\t"
                "prodigal\tantismash\tb\taccepted\ttest\n",
                encoding="utf-8",
            )

            antismash = fake_bin / "antismash"
            antismash.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, pathlib, sys\n"
                "if '--help-showall' in sys.argv:\n"
                "    print('--allow-long-headers')\n"
                "    raise SystemExit(0)\n"
                "args = sys.argv[1:]\n"
                "out = pathlib.Path(args[args.index('--output-dir') + 1])\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                "(out / 'index.html').write_text('<html>ok</html>\\n')\n"
                "(out / 'result.antismash.json').write_text('{}\\n')\n"
                "record = {'argv': args, 'threads': {name: os.environ.get(name) for name in "
                "['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS']}}\n"
                "with open(os.environ['R11C_COMMAND_RECORDER'], 'a', encoding='utf-8') as handle:\n"
                "    handle.write(json.dumps(record, sort_keys=True) + '\\n')\n",
                encoding="utf-8",
            )
            antismash.chmod(0o755)
            docker = fake_bin / "docker"
            docker.write_text(
                "#!/usr/bin/env bash\nprintf 'unexpected docker invocation\\n' >&2\nexit 97\n",
                encoding="utf-8",
            )
            docker.chmod(0o755)

            env = dict(os.environ)
            env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
                    "ENGINE": "docker",
                    "PROJECT_DIR": str(REPO_ROOT),
                    "PROJECT_NAME": "r11c_contract",
                    "ANALYSIS_SCOPE": "bacteria",
                    "FUNGI_GENOME_ROOT": str(fungi_root),
                    "BACTERIA_GENOME_ROOT": str(bacteria_root),
                    "RESULTS_ROOT": str(results_root),
                    "WORK_ROOT": str(work_root),
                    "GENOME_TAXON_MANIFEST": str(manifest),
                    "AUTO_PULL_IMAGES": "never",
                    "CPUS": "4",
                    "GENOME_PARALLELISM": "2",
                    "ANNO_CPUS": "4",
                    "WORKERS": "4",
                    "ANTISMASH_RECORD_PARALLELISM": "1",
                    "TOOL_ACTIVITY_HEARTBEAT_SECONDS": "1",
                    "R11C_COMMAND_RECORDER": str(recorder),
                    "PYTHON_BIN": sys.executable,
                    "VENV_PY": sys.executable,
                }
            )
            result = subprocess.run(
                ["bash", str(RUNNER), "-g", ",".join(genome_ids)],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=15,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            records = [
                json.loads(line)
                for line in recorder.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(records), 2)
            for record in records:
                argv = record["argv"]
                self.assertEqual(argv[1:3], ["--minlength", "1000"])
                self.assertEqual(argv[3], "--output-dir")
                self.assertTrue(argv[4].startswith(str(results_root / "antismash")))
                self.assertEqual(
                    argv[5:],
                    [
                        "--cpus",
                        "2",
                        "--taxon",
                        "bacteria",
                        "--genefinding-tool",
                        "prodigal",
                        "--allow-long-headers",
                    ],
                )
                self.assertEqual(set(record["threads"].values()), {"1"})
            manifest_rows = (
                results_root / "summary_tables" / "run_manifest.tsv"
            ).read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                [line.split("\t", 1)[0] for line in manifest_rows[1:]],
                genome_ids,
            )

    def test_tool_activity_preserves_streams_and_child_exit_status(self) -> None:
        activity = "tool_activity_clean_line() {" + self.runner_text.split(
            "tool_activity_clean_line() {", 1
        )[1].split("resolve_python_cmd() {", 1)[0]
        with tempfile.TemporaryDirectory(prefix="cluster weave activity ") as tmp:
            root = Path(tmp)
            (root / "tmp").mkdir()
            tool = root / "fake child"
            stdout_log = root / "private stdout.log"
            stderr_log = root / "private stderr.log"
            tool.write_text(
                "#!/usr/bin/env bash\nprintf 'child stdout\\n'\nprintf 'child stderr\\n' >&2\nexit 23\n",
                encoding="utf-8",
            )
            tool.chmod(0o755)
            shell = (
                "set -euo pipefail\n"
                + f"WORK_ROOT={shlex.quote(str(root))}\n"
                + "TOOL_ACTIVITY_HEARTBEAT_SECONDS=1\nTOOL_ACTIVITY_RAW_LIMIT=1200\n"
                + "log(){ :; }\n"
                + activity
                + "\nrc=0\n"
                + "if run_tool_with_activity genome tool phase "
                + f"{shlex.quote(str(stdout_log))} {shlex.quote(str(stderr_log))} "
                + f"{shlex.quote(str(tool))}; then rc=0; else rc=$?; fi\n"
                + "printf '%s\\n' \"$rc\"\n"
            )
            result = subprocess.run(
                ["bash", "-c", shell],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )

            self.assertEqual(result.stdout, "23\n")
            self.assertEqual(stdout_log.read_text(encoding="utf-8"), "child stdout\n")
            self.assertEqual(stderr_log.read_text(encoding="utf-8"), "child stderr\n")

    def test_tool_activity_process_group_cancellation_reaches_child(self) -> None:
        activity = "tool_activity_clean_line() {" + self.runner_text.split(
            "tool_activity_clean_line() {", 1
        )[1].split("resolve_python_cmd() {", 1)[0]
        with tempfile.TemporaryDirectory(prefix="cluster weave cancel ") as tmp:
            root = Path(tmp)
            (root / "tmp").mkdir()
            tool = root / "long child"
            ready = root / "ready"
            terminated = root / "terminated"
            tool.write_text(
                "#!/usr/bin/env bash\n"
                "trap 'printf terminated > \"$R11C_TERMINATED\"; exit 143' TERM INT\n"
                "printf ready > \"$R11C_READY\"\n"
                "while :; do sleep 1; done\n",
                encoding="utf-8",
            )
            tool.chmod(0o755)
            shell = (
                "set -euo pipefail\n"
                + f"WORK_ROOT={shlex.quote(str(root))}\n"
                + "TOOL_ACTIVITY_HEARTBEAT_SECONDS=45\nTOOL_ACTIVITY_RAW_LIMIT=1200\n"
                + "log(){ :; }\n"
                + activity
                + "\nrun_tool_with_activity genome tool phase /dev/null /dev/null "
                + shlex.quote(str(tool))
                + "\n"
            )
            env = dict(os.environ, R11C_READY=str(ready), R11C_TERMINATED=str(terminated))
            process = subprocess.Popen(
                ["bash", "-c", shell],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "fake child did not start")
            os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=5)

            self.assertEqual(process.returncode, -signal.SIGTERM)
            self.assertEqual(terminated.read_text(encoding="utf-8"), "terminated")


    def test_repository_helpers_use_worker_in_docker_and_keep_external_backends(self) -> None:
        functions = "".join(
            self.shell_function(name)
            for name in (
                "funbgcex_python_exec",
                "repository_helper_python_exec",
                "antismash_input_python_exec",
                "run_funbgcex_cli",
                "backfill_gbk_translations_from_existing_cds",
                "normalize_gbk_record_headers",
                "remap_gbk_ids_from_fasta_hashes",
                "gbk_diag_summary",
                "filter_gbk_drop_gene_less_records",
                "list_genbank_record_ids",
            )
        )
        shell = (
            "set -uo pipefail\n"
            "ENGINE=docker\nFUNBGCEX_RUNTIME=docker\n"
            "FUNBGCEX_DOCKER_IMAGE=funbgcex-child:accepted-r16b\n"
            "FUNBGCEX_PYTHON_CMD=python3\n"
            "FUNBGCEX_SIF='/runtime with spaces/funbgcex.sif'\n"
            "ANNOTATION_GENBANK_HELPER=/clusterweave/bin/annotation_genbank.py\n"
            "WORKERS=3\n"
            "die(){ printf 'die|%s\\n' \"$*\"; return 99; }\n"
            "resolve_python_cmd(){ printf '%s\\n' worker_python; }\n"
            "worker_python(){ printf 'worker'; printf '|%s' \"$@\"; return 61; }\n"
            "docker_exec(){ printf 'docker'; printf '|%s' \"$@\"; return 73; }\n"
            "sing_exec(){ printf 'sif'; printf '|%s' \"$@\"; return 71; }\n"
            "configured_python(){ printf 'host-python'; printf '|%s' \"$@\"; return 69; }\n"
            "configured_funbgcex(){ printf 'host-cli'; printf '|%s' \"$@\"; return 67; }\n"
            "invoke(){ local label=$1 rc=0; shift; \"$@\" || rc=$?; printf '\\nrc|%s|%s\\n' \"$label\" \"$rc\"; }\n"
            + functions
            + "\ninvoke docker-backfill backfill_gbk_translations_from_existing_cds '/in one.gbk' '/out one.gbk'\n"
            "invoke docker-normalize normalize_gbk_record_headers '/in two.gbk' '/out two.gbk'\n"
            "invoke docker-remap remap_gbk_ids_from_fasta_hashes '/original.fa' '/renamed.fa' '/in three.gbk' '/out three.gbk' '/map.tsv'\n"
            "invoke docker-diagnose gbk_diag_summary '/in four.gbk' diagnostic\n"
            "invoke docker-filter filter_gbk_drop_gene_less_records '/in five.gbk' '/out five.gbk'\n"
            "invoke docker-list list_genbank_record_ids '/in six.gbk' 1200\n"
            "invoke docker-antismash-adapter antismash_input_python_exec '/clusterweave/bin/prepare_antismash_input.py' sanitize '/in seven.gbk' '/out seven.gbk'\n"
            "invoke docker-cli run_funbgcex_cli '/docker gbks' '/docker results'\n"
            "ENGINE=apptainer\nFUNBGCEX_RUNTIME=sif\n"
            "invoke sif-helper gbk_diag_summary '/sif input.gbk' diagnostic\n"
            "invoke sif-cli run_funbgcex_cli '/sif gbks' '/sif results'\n"
            "FUNBGCEX_RUNTIME=host\nFUNBGCEX_PYTHON_CMD=configured_python\nFUNBGCEX_CMD=configured_funbgcex\n"
            "invoke host-helper gbk_diag_summary '/host input.gbk' diagnostic\n"
            "invoke host-cli run_funbgcex_cli '/host gbks' '/host results'\n"
        )
        result = subprocess.run(
            ["bash", "-c", shell],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

        lines = result.stdout.splitlines()
        helper_prefix = "worker|/clusterweave/bin/annotation_genbank.py|"
        self.assertIn(helper_prefix + "backfill-translations|/in one.gbk|/out one.gbk", lines)
        self.assertIn(helper_prefix + "normalize-headers|/in two.gbk|/out two.gbk", lines)
        self.assertIn(
            helper_prefix
            + "remap-ids|/original.fa|/renamed.fa|/in three.gbk|/out three.gbk|/map.tsv",
            lines,
        )
        self.assertIn(helper_prefix + "diagnose|/in four.gbk|diagnostic", lines)
        self.assertIn(helper_prefix + "drop-gene-less|/in five.gbk|/out five.gbk", lines)
        self.assertIn(helper_prefix + "list-record-ids|/in six.gbk|1200", lines)
        self.assertIn(
            "worker|/clusterweave/bin/prepare_antismash_input.py|sanitize|/in seven.gbk|/out seven.gbk",
            lines,
        )
        for label in (
            "backfill",
            "normalize",
            "remap",
            "diagnose",
            "filter",
            "list",
            "antismash-adapter",
        ):
            self.assertIn(f"rc|docker-{label}|61", lines)
        self.assertNotIn("docker|funbgcex-child:accepted-r16b|python3|", result.stdout)
        self.assertIn(
            "docker|funbgcex-child:accepted-r16b|run_funbgcex|/docker gbks|/docker results|3",
            lines,
        )
        self.assertIn("rc|docker-cli|73", lines)
        external_helper = "/clusterweave/bin/annotation_genbank.py|diagnose"
        self.assertIn(
            "sif|/runtime with spaces/funbgcex.sif|python3|"
            + external_helper
            + "|/sif input.gbk|diagnostic",
            lines,
        )
        self.assertIn("rc|sif-helper|71", lines)
        self.assertIn("rc|sif-cli|71", lines)
        self.assertIn(
            "host-python|" + external_helper + "|/host input.gbk|diagnostic", lines
        )
        self.assertIn("rc|host-helper|69", lines)
        self.assertIn("host-cli|/host gbks|/host results|--workers|3", lines)
        self.assertIn("rc|host-cli|67", lines)

    def test_runtime_helper_preserves_exact_argv_with_spaces_and_retries(self) -> None:
        helper = REPO_ROOT / "bin" / "annotation_runtime.py"
        result = subprocess.run(
            [
                sys.executable,
                str(helper),
                "funannotate-predict",
                "--tool-command",
                "/venv/bin/funannotate",
                "--input",
                "/work with spaces/clean.fna",
                "--output-dir",
                "/work with spaces/predict",
                "--species",
                "Rhizopus delemar",
                "--busco-db",
                "fungi",
                "--cpus",
                "4",
                "--name",
                "Rhizopusdelemar_",
                "--temp-dir",
                "/work with spaces/tmp",
                "--",
                "--busco_seed_species",
                "rhizopus_oryzae",
                "--min_training_models",
                "150",
                "--protein_alignments",
                "/work with spaces/no proteins.gff3",
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        argv = [item.decode() for item in result.stdout.split(b"\0") if item]

        self.assertEqual(
            argv,
            [
                "/venv/bin/funannotate",
                "predict",
                "-i",
                "/work with spaces/clean.fna",
                "-o",
                "/work with spaces/predict",
                "--species",
                "Rhizopus delemar",
                "--organism",
                "fungus",
                "--busco_db",
                "fungi",
                "--busco_seed_species",
                "rhizopus_oryzae",
                "--min_training_models",
                "150",
                "--protein_alignments",
                "/work with spaces/no proteins.gff3",
                "--cpus",
                "4",
                "--name",
                "Rhizopusdelemar_",
                "--tmpdir",
                "/work with spaces/tmp",
                "--force",
            ],
        )

    def test_runtime_backend_adapters_preserve_prefix_argv_and_exit(self) -> None:
        adapters = "ANNOTATION_RUNTIME_ARGV=()" + self.runner_text.split(
            "ANNOTATION_RUNTIME_ARGV=()", 1
        )[1].split(
            "###############################################################################\n"
            "# Tracked GFF3-to-GenBank converter",
            1,
        )[0]
        shell = (
            "set -euo pipefail\n"
            "WORK_ROOT=/tmp\nVENV_PY=python3\nANNOTATION_RUNTIME_HELPER=/unused\n"
            "ANNO_CPUS=4\nFUNANNOTATE_IMAGE_URI=docker://fun/image:1\n"
            "FUNANNOTATE_SIF='/runtime with spaces/fun.sif'\n"
            "BRAKER_IMAGE_URI=docker://braker/image:1\nBRAKER_SIF=/missing\n"
            "die(){ printf 'die:%s\\n' \"$*\" >&2; return 99; }\n"
            "docker_image_from_uri(){ printf '%s\\n' \"${1#docker://}\"; }\n"
            "docker_exec(){ printf 'docker'; printf '|%s' \"$@\"; return 19; }\n"
            "sing_exec(){ printf 'sif'; printf '|%s' \"$@\"; return 17; }\n"
            "run_tool_with_activity(){ shift 5; \"$@\"; }\n"
            + adapters
            + "\nENGINE=docker\nrc=0\n"
            "if funannotate_exec 1 0 '/tool with spaces/funannotate' predict '--cpus' 4; "
            "then rc=0; else rc=$?; fi\nprintf '\\nrc=%s\\n' \"$rc\"\n"
            "ENGINE=apptainer\nBRAKER_SIF=/etc/hosts\n"
            "rc=0\nif braker3_exec braker.pl --genome '/input with spaces/a.fa'; "
            "then rc=0; else rc=$?; fi\nprintf '\\nrc=%s\\n' \"$rc\"\n"
        )
        result = subprocess.run(
            ["bash", "-c", shell],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

        self.assertEqual(
            result.stdout.splitlines(),
            [
                "docker|fun/image:1|/tool with spaces/funannotate|predict|--cpus|4",
                "rc=19",
                "sif|/etc/hosts|braker.pl|--genome|/input with spaces/a.fa",
                "rc=17",
            ],
        )


if __name__ == "__main__":
    unittest.main()
