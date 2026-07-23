from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
