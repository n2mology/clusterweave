from __future__ import annotations

import gzip
import io
import json
import os
import tarfile
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
WEB_DIR = REPO_ROOT / "web"
for module_dir in (BIN_DIR, WEB_DIR):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

import canonical_pipeline  # noqa: E402
import prepare_runtime  # noqa: E402


class RecordingExecutor:
    def __init__(self, available: set[str] | None = None) -> None:
        self.available = available or set()
        self.commands: list[tuple[str, ...]] = []
        self.images: dict[str, str] = {}
        self.on_run = None

    def which(self, command: str) -> str | None:
        return f"/fake/{command}" if command in self.available else None

    def run(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        capture: bool = True,
    ) -> prepare_runtime.CommandResult:
        command = tuple(str(part) for part in args)
        self.commands.append(command)
        if self.on_run is not None:
            result = self.on_run(command, env or {}, cwd)
            if result is not None:
                return result
        if command[:3] == ("docker", "image", "inspect"):
            image = command[-1]
            identity = self.images.get(image)
            if identity is None:
                return prepare_runtime.CommandResult(1, "", "missing")
            return prepare_runtime.CommandResult(0, identity + "\n", "")
        return prepare_runtime.CommandResult(0, "", "")


class RecordingStatus:
    def __init__(self) -> None:
        self.path = None
        self.updates: list[tuple[str, int, str, str]] = []

    def update(self, phase: str, progress: int, detail: str, substep: str) -> None:
        self.updates.append((phase, progress, detail, substep))


class RuntimePreparationTests(unittest.TestCase):
    def local_env(self, root: Path) -> dict[str, str]:
        root.mkdir(parents=True, exist_ok=True)
        software = root / "software"
        socket_path = root / "docker.sock"
        socket_path.touch()
        return {
            "CLUSTERWEAVE_ROOT": str(REPO_ROOT),
            "CLUSTERWEAVE_SOFTWARE_ROOT": str(software),
            "CLUSTERWEAVE_RUNTIME_MODE": "lab-docker",
            "CLUSTERWEAVE_ENABLE_DOCKER_SOCKET": "1",
            "DOCKER_HOST_SOCKET": str(socket_path),
            "ENGINE": "docker",
            "ANTISMASH_DB_DIR": str(root / "antismash"),
            "PFAM_DIR": str(root / "pfam"),
            "NCBI_CLI_ROOT": str(software / "ncbi_cli"),
            "RUNTIME_PREPARATION_MANIFEST": str(software / "runtime-preparation.v1.json"),
            "BIGSCAPE_SOFTDIR": str(software / "big_scape"),
            "MIBIG_CACHE": str(software / "big_scape" / "resources" / "mibig_cache"),
            "FASTTREE_HOST": str(software / "big_scape" / "bin" / "fasttree"),
            "DOCKER_DATA_VOLUME": "test_job_data",
            "NPLINKER_DOCKER_DATA_VOLUME": "test_job_data",
        }

    @staticmethod
    def write_executable(path: Path, payload: bytes = b"fixture\n") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def populate_local_assets(
        self,
        root: Path,
        env: dict[str, str],
        executor: RecordingExecutor,
    ) -> None:
        antismash = Path(env["ANTISMASH_DB_DIR"])
        antismash.mkdir(parents=True)
        (antismash / ".databases_downloaded").write_text("ready\n", encoding="utf-8")
        (antismash / "clusterblast" / "fixture.dmnd").parent.mkdir(parents=True)
        (antismash / "clusterblast" / "fixture.dmnd").write_bytes(b"antiSMASH fixture")

        pfam = Path(env["PFAM_DIR"])
        pfam.mkdir(parents=True)
        (pfam / "Pfam-A.hmm").write_bytes(b"Pfam fixture")
        for suffix in ("h3f", "h3i", "h3m", "h3p"):
            (pfam / f"Pfam-A.hmm.{suffix}").write_bytes(suffix.encode("ascii"))

        ncbi = Path(env["NCBI_CLI_ROOT"])
        self.write_executable(ncbi / "datasets")
        self.write_executable(ncbi / "dataformat")

        fasttree = Path(env["FASTTREE_HOST"])
        self.write_executable(fasttree, b"fasttree fixture")
        env["FASTTREE_SHA256"] = prepare_runtime.sha256_file(fasttree)

        mibig = Path(env["MIBIG_CACHE"]) / "mibig_antismash_4.0_gbk"
        mibig.mkdir(parents=True)
        (mibig / "BGC0000001.gbk").write_bytes(b"LOCUS fixture\n//\n")

        for image in prepare_runtime.local_image_specs(env, REPO_ROOT):
            executor.images[image.reference] = f"sha256:{image.key}"

        nplinker = Path(env["CLUSTERWEAVE_SOFTWARE_ROOT"]) / "nplinker" / "venv"
        self.write_executable(nplinker / "bin" / "python")
        (nplinker / ".clusterweave-nplinker-version").write_text(
            prepare_runtime.NPLINKER_VERSION + "\n", encoding="utf-8"
        )

    def test_local_profile_requires_the_explicit_socket_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self.local_env(Path(tmp))
            env["CLUSTERWEAVE_ENABLE_DOCKER_SOCKET"] = "0"
            preparer = prepare_runtime.RuntimePreparer(
                env=env,
                executor=RecordingExecutor({"docker", "Rscript", "antismash", "python3"}),
            )
            with self.assertRaisesRegex(prepare_runtime.PreparationError, "socket gate"):
                preparer.check(scope="startup")

    def test_external_profile_is_check_only_and_never_calls_docker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "CLUSTERWEAVE_ROOT": str(REPO_ROOT),
                "CLUSTERWEAVE_RUNTIME_MODE": "public-queue",
                "CLUSTERWEAVE_EXECUTOR": "slurm",
                "CLUSTERWEAVE_ENABLE_DOCKER_SOCKET": "0",
                "ENGINE": "apptainer",
                "ANTISMASH_SIF": str(root / "antismash.sif"),
                "FUNBGCEX_SIF": str(root / "funbgcex.sif"),
                "FUNANNOTATE_SIF": str(root / "funannotate.sif"),
                "BIGSCAPE_SIF_PATH": str(root / "bigscape.sif"),
                "CLINKER_SIF_PATH": str(root / "clinker.sif"),
                "NPLINKER_SIF_PATH": str(root / "nplinker.sif"),
            }
            for name in (
                "ANTISMASH_SIF",
                "FUNBGCEX_SIF",
                "FUNANNOTATE_SIF",
                "BIGSCAPE_SIF_PATH",
                "CLINKER_SIF_PATH",
                "NPLINKER_SIF_PATH",
            ):
                Path(env[name]).write_bytes(name.encode("ascii"))
            executor = RecordingExecutor(
                {"apptainer", "sbatch", "squeue", "sacct", "scancel", "Rscript", "python3", "antismash"}
            )
            ncbi = root / "ncbi_cli"
            self.write_executable(ncbi / "datasets")
            self.write_executable(ncbi / "dataformat")
            env["NCBI_CLI_ROOT"] = str(ncbi)
            preparer = prepare_runtime.RuntimePreparer(env=env, executor=executor)
            report = preparer.prepare(scope="all")

        self.assertTrue(report.ready, report.errors)
        self.assertFalse(report.changed)
        self.assertFalse(any(command and command[0] == "docker" for command in executor.commands))
        self.assertFalse((root / "runtime-preparation.v1.json").exists())

    def test_cold_local_prepare_acquires_all_missing_assets_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.local_env(root)
            fasttree_payload = b"pinned fasttree fixture"
            env["FASTTREE_SHA256"] = prepare_runtime.sha256_bytes(fasttree_payload)
            executor = RecordingExecutor(
                {"docker", "curl", "hmmpress", "Rscript", "antismash", "python3", "bash", "download-antismash-databases"}
            )

            def on_run(command, command_env, cwd):
                if command[:2] == ("docker", "pull"):
                    image = command[-1]
                    executor.images[image] = f"sha256:{image}"
                    return prepare_runtime.CommandResult(0, "pulled\n", "")
                if command[:2] == ("docker", "build"):
                    image = command[command.index("-t") + 1]
                    executor.images[image] = f"sha256:{image}"
                    return prepare_runtime.CommandResult(0, "built\n", "")
                if command and command[0] == "curl":
                    destination = Path(command[command.index("-o") + 1])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    url = command[-1]
                    if "Pfam-A.hmm.gz" in url:
                        destination.write_bytes(gzip.compress(b"Pfam cold fixture"))
                    elif "FastTree" in url:
                        destination.write_bytes(fasttree_payload)
                    elif "mibig" in url:
                        data = io.BytesIO()
                        with tarfile.open(fileobj=data, mode="w:bz2") as archive:
                            payload = b"LOCUS cold\n//\n"
                            info = tarfile.TarInfo("mibig_antismash_4.0_gbk/BGC0000001.gbk")
                            info.size = len(payload)
                            archive.addfile(info, io.BytesIO(payload))
                        destination.write_bytes(data.getvalue())
                    return prepare_runtime.CommandResult(0, "downloaded\n", "")
                if command and command[0] == "hmmpress":
                    hmm = Path(command[-1])
                    for suffix in ("h3f", "h3i", "h3m", "h3p"):
                        hmm.with_name(f"{hmm.name}.{suffix}").write_bytes(suffix.encode("ascii"))
                    return prepare_runtime.CommandResult(0, "indexed\n", "")
                if command and command[0] == "bash" and command[-1].endswith("install_ncbi_cli.sh"):
                    install = Path(command_env["INSTALL_DIR"])
                    RuntimePreparationTests.write_executable(install / "datasets")
                    RuntimePreparationTests.write_executable(install / "dataformat")
                    return prepare_runtime.CommandResult(0, "installed\n", "")
                if command and command[0] == "bash" and "build_funannotate_sif.sh" in command[1]:
                    image = command_env["IMAGE_TAG"]
                    executor.images[image] = f"sha256:{image}"
                    return prepare_runtime.CommandResult(0, "built and validated\n", "")
                if command[:2] == ("docker", "run") and "nplinker==2.0.0" in " ".join(command):
                    venv = Path(env["CLUSTERWEAVE_SOFTWARE_ROOT"]) / "nplinker" / "venv"
                    RuntimePreparationTests.write_executable(venv / "bin" / "python")
                    (venv / ".clusterweave-nplinker-version").write_text("2.0.0\n", encoding="utf-8")
                    return prepare_runtime.CommandResult(0, "installed\n", "")
                return None

            executor.on_run = on_run
            report = prepare_runtime.RuntimePreparer(env=env, executor=executor).prepare(scope="all")

        self.assertTrue(report.ready, report.errors)
        self.assertTrue(report.changed)
        self.assertTrue(any(command[:2] == ("docker", "pull") for command in executor.commands))
        self.assertTrue(any(command[:2] == ("docker", "build") for command in executor.commands))
        self.assertTrue(any(command and command[0] == "curl" for command in executor.commands))
        self.assertTrue(
            any(command and command[0] == "bash" and command[-1] == "validate" for command in executor.commands),
            executor.commands,
        )

    def test_safe_mibig_extraction_rejects_traversal_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "unsafe.tar"
            destination = root / "destination"
            destination.mkdir()
            with tarfile.open(archive, "w") as handle:
                payload = b"escape"
                traversal = tarfile.TarInfo("../escape.gbk")
                traversal.size = len(payload)
                handle.addfile(traversal, io.BytesIO(payload))
            with self.assertRaisesRegex(
                prepare_runtime.PreparationError, "escapes destination"
            ):
                prepare_runtime.RuntimePreparer._safe_extract(archive, destination)
            self.assertFalse((root / "escape.gbk").exists())

            with tarfile.open(archive, "w") as handle:
                link = tarfile.TarInfo("linked.gbk")
                link.type = tarfile.SYMTYPE
                link.linkname = "../escape.gbk"
                handle.addfile(link)
            with self.assertRaisesRegex(
                prepare_runtime.PreparationError, "unsupported member"
            ):
                prepare_runtime.RuntimePreparer._safe_extract(archive, destination)

    def test_startup_scope_preserves_disabled_legacy_acquisition_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.local_env(root)
            executor = RecordingExecutor({"docker", "Rscript", "antismash", "python3"})
            self.populate_local_assets(root, env, executor)
            for name in ("datasets", "dataformat"):
                (Path(env["NCBI_CLI_ROOT"]) / name).unlink()
            executor.images.clear()
            env.update(
                {
                    "AUTO_INSTALL_NCBI_CLI": "0",
                    "PREPULL_CLINKER_IMAGE": "0",
                    "PREPULL_BIGSCAPE_IMAGE": "0",
                    "PREPULL_FUNBGCEX_IMAGE": "0",
                    "AUTO_BUILD_FUNBGCEX_DOCKER": "0",
                }
            )
            preparer = prepare_runtime.RuntimePreparer(env=env, executor=executor)
            prepared = preparer.prepare(scope="startup")
            executor.commands.clear()
            report = preparer.check(scope="startup")

        self.assertTrue(prepared.ready, prepared.errors)
        self.assertTrue(report.ready, report.errors)
        for key in ("ncbi_cli", "clinker_image", "bigscape_image", "funbgcex_image"):
            self.assertTrue(report.assets[key]["skipped"], key)
        self.assertFalse(
            any(len(command) > 1 and command[0] == "docker" and command[1] in {"pull", "build"} for command in executor.commands)
        )

    def test_prepared_image_identity_change_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.local_env(root)
            executor = RecordingExecutor({"docker", "Rscript", "antismash", "python3"})
            self.populate_local_assets(root, env, executor)
            preparer = prepare_runtime.RuntimePreparer(env=env, executor=executor)
            first = preparer.prepare(scope="all")
            self.assertTrue(first.ready, first.errors)
            image = "ghcr.io/medema-group/big-scape:2.0.0-beta.6"
            executor.images[image] = "sha256:unexpected-replacement"
            with self.assertRaisesRegex(
                prepare_runtime.PreparationError, "asset identity changed"
            ):
                preparer.check(scope="all")

    def test_warm_local_prepare_is_non_mutating_and_checksum_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.local_env(root)
            executor = RecordingExecutor({"docker", "Rscript", "antismash", "python3"})
            self.populate_local_assets(root, env, executor)
            nplinker_python = (
                Path(env["CLUSTERWEAVE_SOFTWARE_ROOT"])
                / "nplinker"
                / "venv"
                / "bin"
                / "python"
            )
            nplinker_python.unlink()
            nplinker_python.symlink_to("python3")
            preparer = prepare_runtime.RuntimePreparer(env=env, executor=executor)

            first = preparer.prepare(scope="all")
            manifest = Path(env["RUNTIME_PREPARATION_MANIFEST"])
            before_bytes = manifest.read_bytes()
            before_mtime = manifest.stat().st_mtime_ns
            command_count = len(executor.commands)
            second = preparer.prepare(scope="all")

            self.assertTrue(first.ready, first.errors)
            self.assertTrue(second.ready, second.errors)
            self.assertFalse(second.changed)
            self.assertEqual(manifest.read_bytes(), before_bytes)
            self.assertEqual(manifest.stat().st_mtime_ns, before_mtime)
            warm_commands = executor.commands[command_count:]
            forbidden = {"pull", "build"}
            self.assertFalse(
                any(len(command) > 1 and command[0] == "docker" and command[1] in forbidden for command in warm_commands),
                warm_commands,
            )
            probes = [
                command
                for command in warm_commands
                if command[:2] == ("docker", "run")
                and str(nplinker_python) in command
            ]
            self.assertEqual(len(probes), 1, warm_commands)
            self.assertIn("--network", probes[0])
            self.assertIn("none", probes[0])
            self.assertIn("--read-only", probes[0])
            self.assertFalse(any(command and command[0] == "curl" for command in warm_commands))
            payload = json.loads(before_bytes)
            self.assertEqual(payload["schema"], "clusterweave.runtime-preparation.v1")
            self.assertEqual(payload["assets"]["fasttree"]["sha256"], env["FASTTREE_SHA256"])
            self.assertIn("pfam", payload["assets"])
            self.assertIn("ncbi_datasets", payload["assets"])

    def test_check_requires_a_manifest_even_when_assets_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.local_env(root)
            executor = RecordingExecutor({"docker", "Rscript", "antismash", "python3"})
            self.populate_local_assets(root, env, executor)
            preparer = prepare_runtime.RuntimePreparer(env=env, executor=executor)
            with self.assertRaisesRegex(
                prepare_runtime.PreparationError, "preparation manifest is unavailable"
            ):
                preparer.check(scope="all")

    def test_startup_status_preserves_the_established_phase_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.local_env(root)
            executor = RecordingExecutor({"docker", "Rscript", "antismash", "python3"})
            self.populate_local_assets(root, env, executor)
            preparer = prepare_runtime.RuntimePreparer(env=env, executor=executor)
            status = RecordingStatus()
            preparer.status = status
            report = preparer.prepare(scope="startup")

        self.assertTrue(report.ready, report.errors)
        final_by_phase = {update[0]: update for update in status.updates}
        self.assertEqual(
            [update[0] for update in status.updates],
            [
                "prepare",
                "antismash",
                "pfam",
                "ncbi_cli",
                "clinker_image",
                "bigscape_image",
                "funbgcex_image",
            ],
        )
        self.assertEqual(
            final_by_phase["prepare"][2:],
            ("Preparing worker bootstrap", "Worker bootstrap plan created"),
        )
        self.assertEqual(
            final_by_phase["antismash"][2:],
            ("antiSMASH databases already present", "Using cached antiSMASH databases"),
        )
        self.assertEqual(
            final_by_phase["pfam"][2:],
            ("Pfam-A database already present", "Using cached Pfam database"),
        )
        self.assertEqual(
            final_by_phase["ncbi_cli"][2:],
            ("NCBI Datasets CLI ready", "Using cached datasets/dataformat"),
        )

    def test_real_executor_publishes_progress_while_a_command_runs(self) -> None:
        progress: list[int] = []
        result = prepare_runtime.Executor().run_with_progress(
            [sys.executable, "-B", "-c", "import time; time.sleep(2.1); print('ready')"],
            env=os.environ.copy(),
            cwd=REPO_ROOT,
            callback=progress.append,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "ready")
        self.assertEqual(progress, [1])

    def test_missing_asset_check_fails_without_trying_to_acquire_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self.local_env(Path(tmp))
            executor = RecordingExecutor({"docker", "Rscript", "antismash", "python3"})
            preparer = prepare_runtime.RuntimePreparer(env=env, executor=executor)
            report = preparer.check(scope="all", keep_going=True)

        self.assertFalse(report.ready)
        self.assertTrue(report.errors)
        self.assertFalse(report.changed)
        self.assertFalse(any(command and command[0] in {"curl", "bash"} for command in executor.commands))
        self.assertFalse(
            any(len(command) > 1 and command[0] == "docker" and command[1] in {"pull", "build"} for command in executor.commands)
        )

    def test_image_references_are_versioned_and_funannotate_validates_busco(self) -> None:
        env = self.local_env(Path(tempfile.gettempdir()) / "cw-runtime-pins")
        specs = prepare_runtime.local_image_specs(env, REPO_ROOT)
        references = {spec.key: spec.reference for spec in specs}
        self.assertEqual(references["bigscape_image"], "ghcr.io/medema-group/big-scape:2.0.0-beta.6")
        self.assertEqual(references["clinker_image"], "quay.io/biocontainers/clinker-py:0.0.32--pyhdfd78af_0")
        self.assertEqual(references["nplinker_image"], "python:3.11-slim")
        self.assertEqual(references["funannotate_image"], "clusterweave-funannotate:v1.8.17-busco")
        self.assertTrue(all(reference and not reference.endswith(":latest") for key, reference in references.items() if key != "funbgcex_image"))
        self.assertIn("validate", prepare_runtime.funannotate_validation_command(env, REPO_ROOT))

    def test_canonical_bridge_forwards_prepared_runtime_compatibility_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = canonical_pipeline.ProjectLayout(
                project_name="demo",
                repo_root=REPO_ROOT,
                data_root=root / "data",
                results_root=root / "data" / "results" / "demo",
                software_root=root / "software",
                work_root=root / "work",
                downloads_root=root / "downloads",
            )
            inherited = {
                "DOCKER_DATA_VOLUME": "prepared-data",
                "FUNBGCEX_DOCKER_IMAGE": "prepared/funbgcex:1",
                "NPLINKER_DOCKER_IMAGE": "prepared/nplinker:1",
            }
            settings = {
                "analysis_scope": "bacteria",
                "engine": "apptainer",
                "auto_pull_images": "never",
                "auto_build_funbgcex_sif": False,
                "auto_pull_bigscape_sif": False,
                "clinker_use_docker_image": True,
            }
            with mock.patch.dict(os.environ, inherited, clear=False):
                env = canonical_pipeline._base_env(layout, settings, cpus=4)

        self.assertEqual(env["ENGINE"], "apptainer")
        self.assertEqual(env["AUTO_PULL_IMAGES"], "never")
        self.assertEqual(env["AUTO_BUILD_FUNBGCEX_SIF"], "0")
        self.assertEqual(env["AUTO_PULL_BIGSCAPE_SIF"], "0")
        self.assertEqual(env["DOCKER_DATA_VOLUME"], "prepared-data")
        self.assertEqual(env["FUNBGCEX_DOCKER_IMAGE"], "prepared/funbgcex:1")
        self.assertEqual(env["NPLINKER_DOCKER_IMAGE"], "prepared/nplinker:1")
        self.assertEqual(env["CLINKER_USE_DOCKER_IMAGE"], "1")

    def test_cli_exposes_prepare_and_check_without_environment_dump(self) -> None:
        parser = prepare_runtime.build_parser()
        prepare_args = parser.parse_args(["prepare", "--profile", "local-docker"])
        check_args = parser.parse_args(["check", "--profile", "external"])
        self.assertEqual(prepare_args.command, "prepare")
        self.assertEqual(check_args.command, "check")
        self.assertNotIn("env", {action.dest for action in parser._actions})


if __name__ == "__main__":
    unittest.main()
