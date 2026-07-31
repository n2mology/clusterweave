import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "bin" / "nplinker_run_and_export.py"


FAKE_NPLINKER = """
import os


class Strain:
    def __init__(self, strain_id):
        self.id = strain_id


class GCF:
    def __init__(self, object_id, strains, mibig_only=False):
        self.id = object_id
        self.strains = [Strain(value) for value in strains]
        self._mibig_only = mibig_only

    def has_mibig_only(self):
        return self._mibig_only


class Spectrum:
    def __init__(self, object_id, strains):
        self.id = object_id
        self.strains = [Strain(value) for value in strains]


class LinkGraph:
    def __init__(self):
        local = GCF("local_gcf", ["target_strain"])
        other = GCF("other_gcf", ["other_strain"])
        mibig = GCF("mibig_gcf", ["BGC000001"], mibig_only=True)
        self.links = [
            (mibig, Spectrum("mibig_spectrum", ["BGC000001"])),
            (other, Spectrum("other_spectrum", ["other_strain"])),
            (local, Spectrum("local_spectrum", ["target_strain"])),
        ]
        self._scores = {
            ("mibig_gcf", "mibig_spectrum"): 10.0,
            ("other_gcf", "other_spectrum"): 9.0,
            ("local_gcf", "local_spectrum"): 2.0,
        }

    def get_link_data(self, left, right):
        return {"metcalf": self._scores[(left.id, right.id)]}


class NPLinker:
    def __init__(self, config_file):
        expected = os.environ.get("TEST_EXPECT_MASSIVE_PASSWORD")
        if expected is not None and os.environ.get("MASSIVE_PASSWORD") != expected:
            raise RuntimeError("MassIVE password did not resolve to the expected value")
        self._graph = LinkGraph()
        self.gcfs = [pair[0] for pair in self._graph.links]

    def load_data(self):
        return True

    def get_links(self, sources, method, **kwargs):
        return self._graph
"""


class NPLinkerSingleImplementationTests(unittest.TestCase):
    def write_fake_modules(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "httpx.py").write_text(
            "def get(*args, **kwargs):\n    return None\n", encoding="utf-8"
        )
        (root / "nplinker.py").write_text(
            textwrap.dedent(FAKE_NPLINKER).lstrip(), encoding="utf-8"
        )

    def run_exporter(
        self,
        runner: Path,
        work: Path,
        name: str,
        *,
        target: str = "target_strain",
        filter_target_only: str = "0",
        allow_filter_fallback: str | None = None,
    ) -> tuple[bytes, bytes, subprocess.CompletedProcess[str]]:
        fake_modules = work / "fake_modules"
        self.write_fake_modules(fake_modules)
        config = work / "nplinker.toml"
        config.write_text("root_dir = '.'\n", encoding="utf-8")
        out_table = work / f"{name}.links.tsv"
        summary_table = work / f"{name}.summary.tsv"
        env = os.environ.copy()
        env.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(fake_modules),
                "NPLINKER_CONFIG": str(config),
                "OUT_TABLE": str(out_table),
                "SUMMARY_TABLE": str(summary_table),
                "TARGET_STRAIN": target,
                "NPLINKER_METHODS": "metcalf",
                "MAX_LINKS": "5000",
                "NPLINKER_LOAD_RETRIES": "1",
                "NPLINKER_RETRY_SLEEP": "0",
                "FILTER_TARGET_ONLY": filter_target_only,
                "MASSIVE_PASSWORD": "",
                "TEST_EXPECT_MASSIVE_PASSWORD": "",
            }
        )
        env.pop("ALLOW_FILTER_FALLBACK", None)
        if allow_filter_fallback is not None:
            env["ALLOW_FILTER_FALLBACK"] = allow_filter_fallback
        result = subprocess.run(
            [sys.executable, str(runner)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return out_table.read_bytes(), summary_table.read_bytes(), result

    def test_direct_and_copied_outputs_are_identical_and_stably_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            copied = work / RUNNER.name
            shutil.copyfile(RUNNER, copied)
            direct_links, direct_summary, _ = self.run_exporter(
                RUNNER, work, "direct"
            )
            copied_links, copied_summary, _ = self.run_exporter(
                copied, work, "copied"
            )

        self.assertEqual(copied_links, direct_links)
        self.assertEqual(copied_summary, direct_summary)
        link_rows = list(
            csv.DictReader(io.StringIO(direct_links.decode()), delimiter="\t")
        )
        self.assertEqual(
            [row["left_id"] for row in link_rows],
            ["other_gcf", "local_gcf", "mibig_gcf"],
        )
        summary_rows = list(
            csv.DictReader(io.StringIO(direct_summary.decode()), delimiter="\t")
        )
        self.assertEqual(
            [row["BGC"] for row in summary_rows],
            ["GCF:other_gcf", "GCF:local_gcf"],
        )

    def test_target_filter_is_strict_by_default_and_compatibility_is_explicit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            strict_links, strict_summary, strict_result = self.run_exporter(
                RUNNER,
                work,
                "strict",
                target="absent_target",
                filter_target_only="1",
            )
            compat_links, compat_summary, compat_result = self.run_exporter(
                RUNNER,
                work,
                "compat",
                target="absent_target",
                filter_target_only="1",
                allow_filter_fallback="1",
            )

        self.assertEqual(len(strict_links.decode().splitlines()), 1)
        self.assertEqual(len(strict_summary.decode().splitlines()), 1)
        self.assertNotIn("falling back to unfiltered links", strict_result.stdout)
        self.assertEqual(len(compat_links.decode().splitlines()), 4)
        self.assertEqual(len(compat_summary.decode().splitlines()), 3)
        self.assertIn("falling back to unfiltered links", compat_result.stdout)

    def test_docker_volume_path_copies_runner_and_preserves_shell_contracts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_modules = root / "fake_modules"
            self.write_fake_modules(fake_modules)
            fake_bin = root / "fake_bin"
            fake_bin.mkdir()
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                textwrap.dedent(
                    """
                    #!/usr/bin/env bash
                    set -euo pipefail
                    if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then exit 0; fi
                    [[ "${1:-}" == "run" ]] || exit 64
                    shift
                    while (( $# )); do
                      case "$1" in
                        --rm|-i) shift ;;
                        --user|--entrypoint|--cpus|--memory|--pids-limit|--label|-e|-v) shift 2 ;;
                        fake-nplinker-image) shift; exec "$@" ;;
                        *) exit 65 ;;
                      esac
                    done
                    exit 66
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)

            inputs = root / "inputs"
            antismash = inputs / "antismash"
            antismash.mkdir(parents=True)
            region = antismash / "target_strain.region001.gbk"
            region.write_text("LOCUS       target\n//\n", encoding="utf-8")
            gnps = inputs / "gnps"
            gnps.mkdir()
            (gnps / "spectra.mgf").write_text(
                "BEGIN IONS\nEND IONS\n", encoding="utf-8"
            )
            mapping = inputs / "strain_mappings.json"
            mapping.write_text("{}\n", encoding="utf-8")
            bigscape = inputs / "bigscape"
            bigscape.mkdir()
            (bigscape / "mix_clustering_c0.30.tsv").write_text(
                "# fixture\n", encoding="utf-8"
            )
            venv = root / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python").symlink_to(sys.executable)
            (venv / "bin" / "activate").write_text(
                f'export PATH="{venv / "bin"}:$PATH"\n', encoding="utf-8"
            )

            run_dir = root / "run"
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}:{env['PATH']}",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": str(fake_modules),
                    "TEST_EXPECT_MASSIVE_PASSWORD": "",
                    "ENGINE": "docker",
                    "NPLINKER_DOCKER_IMAGE": "fake-nplinker-image",
                    "NPLINKER_DOCKER_DATA_VOLUME": "fake-data-volume",
                    "AUTO_PULL_NPLINKER_SIF": "0",
                    "PROJECT_DIR": str(REPO_ROOT),
                    "PROJECT_NAME": "nplinker_docker_smoke",
                    "DATA_ROOT": str(root / "data"),
                    "RESULTS_ROOT": str(root / "results"),
                    "SOFTWARE_ROOT": str(root / "software"),
                    "NPLINKER_ROOT": str(root / "nplinker"),
                    "WINDOWS_NPLINKER_ROOT": str(root / "windows_nplinker"),
                    "RUN_DIR": str(run_dir),
                    "MIRROR_RUN_DIR": str(run_dir),
                    "WORK_ROOT": str(root / "work"),
                    "LOGDIR": str(root / "logs"),
                    "RUN_MODE": "local",
                    "TARGET_STRAIN": "target_strain",
                    "LOCAL_ANTISMASH_ROOT": str(antismash),
                    "LOCAL_GNPS_DIR": str(gnps),
                    "LOCAL_STRAIN_MAPPING": str(mapping),
                    "LOCAL_BIGSCAPE_ROOT": str(bigscape),
                    "USE_LOCAL_GENOMICS_ONLY": "1",
                    "NPLINKER_BOOTSTRAP_ENV": "0",
                    "VENV_DIR": str(venv),
                    "FILTER_TARGET_ONLY": "1",
                    "CPUS": "1",
                    "CLUSTERWEAVE_TOOL_DOCKER_CPUS": "1",
                }
            )
            env.pop("MASSIVE_PASSWORD", None)
            env.pop("ALLOW_FILTER_FALLBACK", None)
            result = subprocess.run(
                ["bash", str(REPO_ROOT / "run_nplinker.sh")],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            staged_runner = run_dir / RUNNER.name
            self.assertEqual(staged_runner.read_bytes(), RUNNER.read_bytes())
            self.assertEqual(
                (run_dir / "antismash" / "target_strain" / region.name).read_bytes(),
                region.read_bytes(),
            )
            direct_links, direct_summary, _ = self.run_exporter(
                RUNNER, root, "direct_docker_parity", filter_target_only="1"
            )
            self.assertEqual(
                (run_dir / "output" / "links_target_strain.tsv").read_bytes(),
                direct_links,
            )
            self.assertEqual(
                (run_dir / "output" / "summary_target_strain.tsv").read_bytes(),
                direct_summary,
            )


if __name__ == "__main__":
    unittest.main()
