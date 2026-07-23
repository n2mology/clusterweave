from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import runtime_capabilities  # noqa: E402


class RuntimeCapabilityTests(unittest.TestCase):
    def test_dependency_light_taxon_tree_is_independent_of_optional_runtime(self) -> None:
        env = {
            "CLUSTERWEAVE_ROOT": str(REPO_ROOT),
            "CLUSTERWEAVE_EXECUTOR": "local",
            "ENGINE": "docker",
            "CLUSTERWEAVE_ENABLE_DOCKER_SOCKET": "0",
            "PHYLOGENY_RUNTIME": "docker",
            "PHYLOGENY_DOCKER_IMAGE": "clusterweave-phylogeny:1.0.0",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            health = runtime_capabilities.runtime_health()

        taxon_tree = health["stages"]["taxon_tree_figure"]
        sequence_tree = health["stages"]["sequence_phylogeny"]
        self.assertTrue(taxon_tree["available"])
        self.assertIn("Dependency-light", taxon_tree["detail"])
        self.assertFalse(sequence_tree["available"])
        self.assertIn("core taxonomy figure remains available", sequence_tree["detail"])

    def test_prebuilt_sif_enables_only_optional_sequence_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sif = Path(tmp) / "clusterweave_phylogeny_1.0.0.sif"
            sif.write_bytes(b"pinned fixture")
            missing_renderer = Path(tmp) / "missing_renderer.py"
            env = {
                "CLUSTERWEAVE_ROOT": str(REPO_ROOT),
                "CLUSTERWEAVE_EXECUTOR": "local",
                "ENGINE": "apptainer",
                "TAXON_TREE_RENDERER": str(missing_renderer),
                "PHYLOGENY_RUNTIME": "sif",
                "PHYLOGENY_SIF_PATH": str(sif),
            }

            def which(name: str) -> str | None:
                return "/usr/bin/apptainer" if name == "apptainer" else None

            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(runtime_capabilities.shutil, "which", side_effect=which),
            ):
                health = runtime_capabilities.runtime_health()

        self.assertFalse(health["stages"]["taxon_tree_figure"]["available"])
        sequence_tree = health["stages"]["sequence_phylogeny"]
        self.assertTrue(sequence_tree["available"])
        self.assertEqual(sequence_tree["runtime"], "apptainer")
        self.assertTrue(sequence_tree["sif_available"])

    def test_docker_capability_inspects_prebuilt_image_without_acquiring_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = Path(tmp) / "docker.sock"
            socket_path.touch()
            env = {
                "CLUSTERWEAVE_ROOT": str(REPO_ROOT),
                "CLUSTERWEAVE_EXECUTOR": "local",
                "ENGINE": "docker",
                "CLUSTERWEAVE_ENABLE_DOCKER_SOCKET": "1",
                "DOCKER_HOST_SOCKET": str(socket_path),
                "PHYLOGENY_RUNTIME": "docker",
                "PHYLOGENY_DOCKER_IMAGE": "clusterweave-phylogeny:1.0.0",
            }

            def which(name: str) -> str | None:
                return "/usr/bin/docker" if name == "docker" else None

            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(runtime_capabilities.shutil, "which", side_effect=which),
                mock.patch.object(
                    runtime_capabilities,
                    "_docker_image_available",
                    return_value=True,
                ) as inspect_image,
            ):
                health = runtime_capabilities.runtime_health()

        sequence_tree = health["stages"]["sequence_phylogeny"]
        self.assertTrue(sequence_tree["available"])
        self.assertEqual(sequence_tree["runtime"], "docker")
        inspect_image.assert_called_once_with("clusterweave-phylogeny:1.0.0")

    def test_deployment_defaults_keep_optional_inference_and_cross_kingdom_evidence_disabled(self) -> None:
        for filename in ["docker-compose.yml", "clusterweave.yml"]:
            text = (REPO_ROOT / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertIn('RUN_TAXON_TREE_FIGURE: "${RUN_TAXON_TREE_FIGURE:-1}"', text)
                self.assertIn('RUN_PHYLOGENY: "${RUN_PHYLOGENY:-0}"', text)
                self.assertIn(
                    'RUN_CROSS_KINGDOM_EVIDENCE: "${RUN_CROSS_KINGDOM_EVIDENCE:-${RUN_HGT_EVIDENCE:-0}}"',
                    text,
                )
                self.assertIn(
                    'WORKER_MEMORY_PHYLOGENY_BASE_MB: "${WORKER_MEMORY_PHYLOGENY_BASE_MB:-1024}"',
                    text,
                )
                self.assertIn(
                    'WORKER_MEMORY_PER_PHYLOGENY_CPU_MB: "${WORKER_MEMORY_PER_PHYLOGENY_CPU_MB:-2048}"',
                    text,
                )

        dockerfile = (REPO_ROOT / "Dockerfile.worker").read_text(encoding="utf-8")
        entrypoint = (REPO_ROOT / "web" / "entrypoint-worker.sh").read_text(
            encoding="utf-8"
        )
        app = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        self.assertIn(
            "COPY software/phylogeny/ /clusterweave/software/phylogeny/",
            dockerfile,
        )
        self.assertNotIn("PREPULL_PHYLOGENY", entrypoint)
        self.assertNotIn("AUTO_BUILD_PHYLOGENY", entrypoint)
        for protected in ["RUN_PHYLOGENY", "PHYLOGENY_CPUS", "PHYLOGENY_PARALLELISM"]:
            self.assertIn(f'"{protected}",', app)


if __name__ == "__main__":
    unittest.main()
