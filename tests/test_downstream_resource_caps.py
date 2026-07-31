from __future__ import annotations

import hashlib
import importlib.util
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


class DownstreamResourceCapLayoutTests(unittest.TestCase):
    def assert_numeric_thread_env(self, text: str) -> None:
        for name in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
        ):
            self.assertIn(f"{name}=1", text)

    def test_bigscape_docker_is_bounded_by_normalized_threads(self) -> None:
        text = read_repo_file("run_bigscape.sh")
        self.assertIn("normalize_positive_integer THREADS 1", text)
        self.assertIn('BIGSCAPE_DOCKER_CPUS="$(bounded_docker_cpu_limit', text)
        self.assertIn('--cpus "${BIGSCAPE_DOCKER_CPUS}"', text)
        self.assertIn('--cores "${THREADS}"', text)
        self.assert_numeric_thread_env(text)
        self.assertIn('[[ -n "${BIGSCAPE_DOCKER_MEMORY}" ]]', text)
        self.assertIn('[[ -n "${BIGSCAPE_DOCKER_PIDS_LIMIT}" ]]', text)

    def test_nplinker_docker_is_bounded_by_normalized_cpus(self) -> None:
        text = read_repo_file("run_nplinker.sh")
        self.assertIn("normalize_positive_integer CPUS 1", text)
        self.assertIn('NPLINKER_DOCKER_CPUS="$(bounded_docker_cpu_limit', text)
        self.assertIn('--cpus "${NPLINKER_DOCKER_CPUS}"', text)
        self.assert_numeric_thread_env(text)
        self.assertIn('[[ -n "${NPLINKER_DOCKER_MEMORY}" ]]', text)
        self.assertIn('[[ -n "${NPLINKER_DOCKER_PIDS_LIMIT}" ]]', text)

    def test_clinker_sanity_check_uses_the_same_default_cap_as_panels(self) -> None:
        text = read_repo_file("run_clinker.sh")
        self.assertIn('CLINKER_DOCKER_CPUS="${CLINKER_DOCKER_CPUS:-1}"', text)
        self.assertIn("normalize_positive_integer CLINKER_DOCKER_CPUS 1", text)
        self.assertIn('CLINKER_DOCKER_CPUS="$(bounded_docker_cpu_limit', text)
        self.assertIn('--cpus "${CLINKER_DOCKER_CPUS}"', text)
        self.assertIn("export CLINKER_DOCKER_CPUS", text)
        self.assert_numeric_thread_env(text)


class RuntimePreparationBoundaryTests(unittest.TestCase):
    @staticmethod
    def write_executable(path: Path, script: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)

    def base_env(self, root: Path) -> dict[str, str]:
        env = os.environ.copy()
        for name in (
            "BIGSCAPE_SIF_PATH",
            "SIF_PATH",
            "R_BIN",
            "CLINKER_SIF_PATH",
            "NPLINKER_ROOT",
            "VENV_DIR",
        ):
            env.pop(name, None)
        env.update(
            {
                "PROJECT_DIR": str(REPO_ROOT),
                "PROJECT_NAME": "demo",
                "PROJECTS_ROOT": str(root),
                "DATA_ROOT": str(root / "data"),
                "RESULTS_ROOT": str(root / "results"),
                "SOFTWARE_ROOT": str(root / "software"),
                "TOOLS_ROOT": str(root / "software"),
                "WORK_ROOT": str(root / "work"),
                "LOGDIR": str(root / "results" / "logs"),
            }
        )
        return env

    def write_fake_docker(self, root: Path, *, ready: bool) -> tuple[Path, Path]:
        fake_bin = root / "fake-bin"
        calls = root / "docker.calls"
        self.write_executable(
            fake_bin / "docker",
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >> \"${DOCKER_CALLS:?}\"\n"
            f"if [[ {1 if ready else 0} -eq 1 && \"$1 $2\" == \"image inspect\" ]]; then exit 0; fi\n"
            f"if [[ {1 if ready else 0} -eq 1 && \"$1\" == \"run\" ]]; then exit 0; fi\n"
            "exit 1\n",
        )
        return fake_bin, calls

    def prepare_bigscape_inputs(self, root: Path) -> dict[str, str]:
        antismash = root / "results" / "antismash" / "genome_a"
        antismash.mkdir(parents=True, exist_ok=True)
        (antismash / "genome_a.region001.gbk").write_text(
            "LOCUS       region001 9 bp DNA\nSOURCE      demo\n  ORGANISM  demo\nORIGIN\n        1 atgaaaact\n//\n",
            encoding="utf-8",
        )
        pfam = root / "software" / "big_scape" / "resources" / "pfam" / "Pfam-A.hmm"
        pfam.parent.mkdir(parents=True, exist_ok=True)
        pfam.write_text("HMMER3/f fixture\n", encoding="utf-8")
        fasttree = root / "software" / "big_scape" / "bin" / "fasttree"
        payload = b"#!/usr/bin/env bash\nexit 0\n"
        fasttree.parent.mkdir(parents=True, exist_ok=True)
        fasttree.write_bytes(payload)
        fasttree.chmod(0o755)
        return {
            "ANTISMASH_ROOT": str(antismash.parent),
            "PFAM_HMM": str(pfam),
            "FASTTREE_HOST": str(fasttree),
            "FASTTREE_SHA256": hashlib.sha256(payload).hexdigest(),
        }

    def test_missing_docker_runtimes_fail_without_network_attempts(self) -> None:
        cases = (
            ("bigscape", REPO_ROOT / "run_bigscape.sh"),
            ("clinker", REPO_ROOT / "run_clinker.sh"),
            ("nplinker", REPO_ROOT / "run_nplinker.sh"),
        )
        for name, runner in cases:
            with self.subTest(runner=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fake_bin, calls = self.write_fake_docker(root, ready=False)
                env = self.base_env(root)
                env.update(
                    {
                        "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                        "DOCKER_CALLS": str(calls),
                        "ENGINE": "docker",
                    }
                )
                if name == "bigscape":
                    env.update(self.prepare_bigscape_inputs(root))
                    env.update({"BIGSCAPE_USE_DOCKER_IMAGE": "1", "AUTO_PULL_BIGSCAPE_SIF": "1"})
                elif name == "clinker":
                    env.update(
                        {
                            "CLINKER_MODE": "atlas",
                            "RUN_CLINKER": "1",
                            "CLINKER_USE_DOCKER_IMAGE": "1",
                            "PREFER_CLINKER_CONTAINER": "1",
                            "REFRESH_FAMILY_ATLAS": "0",
                            "REFRESH_REVIEWER_SHORTLIST": "0",
                            "REFRESH_PRIORITY_SHORTLIST": "0",
                            "REFRESH_SHARED_FAMILY_SHORTLIST": "0",
                            "STAGE_PANELS": "0",
                            "AUTO_NORMALIZE_METADATA": "0",
                        }
                    )
                else:
                    env.update(
                        {
                            "TARGET_STRAIN": "strain_a",
                            "NPLINKER_USE_DOCKER_IMAGE": "1",
                            "AUTO_PULL_NPLINKER_SIF": "1",
                        }
                    )
                completed = subprocess.run(
                    ["bash", str(runner)],
                    cwd=REPO_ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                call_lines = calls.read_text(encoding="utf-8").splitlines()
                combined = completed.stdout + completed.stderr
                self.assertNotEqual(completed.returncode, 0, combined)
                self.assertTrue(any(line.startswith("image inspect ") for line in call_lines), call_lines)
                self.assertFalse(any(line.startswith("pull ") for line in call_lines), call_lines)
                self.assertIn("prepare-runtime", combined)
                self.assertIn("check-runtime", combined)

    def test_bigscape_stage_sif_alias_uses_prepared_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "fake-bin"
            calls = root / "apptainer.calls"
            self.write_executable(
                fake_bin / "apptainer",
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"${ENGINE_CALLS:?}\"\n"
                "exit 0\n",
            )
            sif = root / "prepared" / "bigscape.sif"
            sif.parent.mkdir(parents=True)
            sif.write_text("prepared image\n", encoding="utf-8")
            env = self.base_env(root)
            env.update(self.prepare_bigscape_inputs(root))
            env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                    "ENGINE_CALLS": str(calls),
                    "ENGINE": "apptainer",
                    "BIGSCAPE_SIF_PATH": str(sif),
                    "BIGSCAPE_SIF_SOURCE": "docker://example.invalid/bigscape:pinned",
                    "AUTO_PULL_BIGSCAPE_SIF": "1",
                    "MIBIG_AUTO_DOWNLOAD": "1",
                }
            )
            completed = subprocess.run(
                ["bash", str(REPO_ROOT / "run_bigscape.sh")],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            call_lines = calls.read_text(encoding="utf-8").splitlines()

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(any(str(sif) in line and line.startswith("exec ") for line in call_lines), call_lines)
        self.assertFalse(any(line.startswith("pull ") for line in call_lines), call_lines)

    def test_figures_runner_resolves_rscript_from_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "fake-bin"
            calls = root / "rscript.calls"
            self.write_executable(
                fake_bin / "Rscript",
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"${RSCRIPT_CALLS:?}\"\n"
                "exit 0\n",
            )
            env = self.base_env(root)
            env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                    "RSCRIPT_CALLS": str(calls),
                    "RUN_SUMMARY_FIGURES": "1",
                    "RUN_BGC_OVERLAP_FIGURE": "0",
                    "RUN_BIGSCAPE_NETWORK_FIGURE": "0",
                    "RUN_BIGSCAPE_MULTIPANEL_FIGURE": "0",
                    "RUN_TAXON_TREE_FIGURE": "0",
                }
            )
            completed = subprocess.run(
                ["bash", str(REPO_ROOT / "run_figures.sh")],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            call_text = calls.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(str(REPO_ROOT / "bin" / "render_summary_figures.R"), call_text)
        self.assertIn("--project-root", call_text)
        self.assertIn("--project-name demo", call_text)

    def test_prepared_docker_runners_keep_job_cancellation_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin, calls = self.write_fake_docker(root, ready=True)
            env = self.base_env(root)
            env.update(self.prepare_bigscape_inputs(root))
            env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                    "DOCKER_CALLS": str(calls),
                    "ENGINE": "docker",
                    "BIGSCAPE_USE_DOCKER_IMAGE": "1",
                    "CLUSTERWEAVE_JOB_ID": "job-test",
                }
            )
            completed = subprocess.run(
                ["bash", str(REPO_ROOT / "run_bigscape.sh")],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            call_lines = calls.read_text(encoding="utf-8").splitlines()

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        docker_runs = [line for line in call_lines if line.startswith("run ")]
        self.assertTrue(docker_runs, call_lines)
        self.assertTrue(
            all(
                "--label clusterweave.job_id=job-test" in line
                and "--label clusterweave.project=demo" in line
                for line in docker_runs
            ),
            docker_runs,
        )

    def test_clinker_and_nplinker_keep_job_cancellation_labels(self) -> None:
        for name, runner in (
            ("clinker", REPO_ROOT / "run_clinker.sh"),
            ("nplinker", REPO_ROOT / "run_nplinker.sh"),
        ):
            with self.subTest(runner=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fake_bin, calls = self.write_fake_docker(root, ready=True)
                env = self.base_env(root)
                env.update(
                    {
                        "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                        "DOCKER_CALLS": str(calls),
                        "ENGINE": "docker",
                        "CLUSTERWEAVE_JOB_ID": "job-test",
                    }
                )
                if name == "clinker":
                    env.update(
                        {
                            "CLINKER_MODE": "atlas",
                            "RUN_CLINKER": "1",
                            "CLINKER_USE_DOCKER_IMAGE": "1",
                            "PREFER_CLINKER_CONTAINER": "1",
                            "REFRESH_FAMILY_ATLAS": "0",
                            "REFRESH_REVIEWER_SHORTLIST": "0",
                            "REFRESH_PRIORITY_SHORTLIST": "0",
                            "REFRESH_SHARED_FAMILY_SHORTLIST": "0",
                            "STAGE_PANELS": "0",
                            "AUTO_NORMALIZE_METADATA": "0",
                        }
                    )
                else:
                    antismash = root / "local-antismash"
                    antismash.mkdir()
                    (antismash / "strain_a.region001.gbk").write_text(
                        "LOCUS       region001 9 bp DNA\nORIGIN\n        1 atgaaaact\n//\n",
                        encoding="utf-8",
                    )
                    gnps = root / "gnps"
                    gnps.mkdir()
                    (gnps / "spectra.mgf").write_text("BEGIN IONS\nEND IONS\n", encoding="utf-8")
                    mapping = root / "strain_mappings.json"
                    mapping.write_text('{"strain_a": "strain_a"}\n', encoding="utf-8")
                    venv = root / "software" / "nplinker" / "venv"
                    (venv / "bin").mkdir(parents=True)
                    (venv / "bin" / "activate").write_text("# prepared fixture\n", encoding="utf-8")
                    env.update(
                        {
                            "TARGET_STRAIN": "strain_a",
                            "RUN_MODE": "local",
                            "NPLINKER_USE_DOCKER_IMAGE": "1",
                            "LOCAL_ANTISMASH_ROOT": str(antismash),
                            "LOCAL_GNPS_DIR": str(gnps),
                            "LOCAL_STRAIN_MAPPING": str(mapping),
                            "USE_LOCAL_GENOMICS_ONLY": "0",
                            "NPLINKER_USE_NATIVE": "0",
                            "NPLINKER_ROOT": str(root / "nplinker"),
                            "WINDOWS_NPLINKER_ROOT": str(root / "nplinker"),
                            "VENV_DIR": str(venv),
                        }
                    )
                subprocess.run(
                    ["bash", str(runner)],
                    cwd=REPO_ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                docker_runs = [
                    line
                    for line in calls.read_text(encoding="utf-8").splitlines()
                    if line.startswith("run ")
                ]
                self.assertTrue(docker_runs, calls.read_text(encoding="utf-8"))
                self.assertTrue(
                    all(
                        "--label clusterweave.job_id=job-test" in line
                        and "--label clusterweave.project=demo" in line
                        for line in docker_runs
                    ),
                    docker_runs,
                )

    def test_annotation_docker_args_keep_job_cancellation_labels(self) -> None:
        script = REPO_ROOT / "run_annotation_and_detection.sh"
        command = f"""
set -euo pipefail
PROJECT_NAME=demo
CLUSTERWEAVE_JOB_ID=job-test
CLUSTERWEAVE_CHILD_DOCKER_CPUS=1
CLUSTERWEAVE_CHILD_DOCKER_MEMORY=
CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT=
CLUSTERWEAVE_TOOL_DOCKER_CPUS=
CLUSTERWEAVE_TOOL_DOCKER_MEMORY=
CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT=
DOCKER_DATA_VOLUME=
DOCKER_ANTISMASH_DB_VOLUME=
PROJECT_DIR={shlex.quote(str(REPO_ROOT))}
FUNGI_GENOME_ROOT=/tmp/fungi
BACTERIA_GENOME_ROOT=/tmp/bacteria
RESULTS_ROOT=/tmp/results
ANTISMASH_DB_DIR=/tmp/antismash-db
WORK_ROOT=/tmp/work
CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS=1
bounded_docker_cpu_limit() {{ printf '%s\\n' "${{1:-}}"; }}
source <(awk '/^docker_run_args\\(\\)/{{flag=1}} /^docker_exec\\(\\)/{{flag=0}} flag{{print}}' {shlex.quote(str(script))})
docker_run_args | tr '\\0' '\\n'
"""
        completed = subprocess.run(
            ["bash", "-lc", command],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--label\nclusterweave.job_id=job-test\n", completed.stdout)
        self.assertIn("--label\nclusterweave.project=demo\n", completed.stdout)


class GeneratedClinkerPanelResourceCapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        module_path = REPO_ROOT / "bin" / "stage_clinker_panels.py"
        spec = importlib.util.spec_from_file_location("stage_clinker_panels_caps", module_path)
        assert spec is not None and spec.loader is not None
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_generated_docker_runner_has_default_and_optional_caps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            panel_dir = root / "panel"
            panel_dir.mkdir()
            staged = panel_dir / "region001.gbk"
            staged.write_text("LOCUS test\n//\n", encoding="utf-8")

            self.module.write_run_panel_script(panel_dir, [staged], root, REPO_ROOT)
            runner = panel_dir / "run_panel.sh"
            text = runner.read_text(encoding="utf-8")

            self.assertIn('CLINKER_DOCKER_CPUS="${CLINKER_DOCKER_CPUS:-1}"', text)
            self.assertIn('--cpus "${CLINKER_DOCKER_CPUS}"', text)
            self.assertIn('[[ -n "${CLINKER_DOCKER_MEMORY:-}" ]]', text)
            self.assertIn('[[ -n "${CLINKER_DOCKER_PIDS_LIMIT:-}" ]]', text)
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            ):
                self.assertIn(f"{name}=1", text)

            subprocess.run(["bash", "-n", str(runner)], check=True)

            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            docker_calls = root / "generated-panel-docker.calls"
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"${DOCKER_CALLS:?}\"\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                    "DOCKER_CALLS": str(docker_calls),
                    "PREFER_CLINKER_CONTAINER": "1",
                    "CLINKER_DOCKER_IMAGE": "prepared/clinker:1",
                    "CLUSTERWEAVE_JOB_ID": "job-test",
                    "PROJECT_NAME": "demo",
                }
            )
            completed = subprocess.run(
                ["bash", str(runner)],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            call_text = docker_calls.read_text(encoding="utf-8")
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("--label clusterweave.job_id=job-test", call_text)
            self.assertIn("--label clusterweave.project=demo", call_text)


if __name__ == "__main__":
    unittest.main()
