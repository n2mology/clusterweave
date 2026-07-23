from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "capture_external_artifacts.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "capture_external_artifacts_phylogeny", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PhylogenyProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def write_manifest(
        self,
        results: Path,
        *,
        runtime: str,
        runtime_identity: str,
        tool_versions: str,
    ) -> None:
        path = results / "phylogeny" / "phylogeny_run_manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "status": "success",
                    "runtime": runtime,
                    "runtime_identity": runtime_identity,
                    "tool_versions": tool_versions,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_docker_runtime_identity_and_tool_versions_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / "results"
            self.write_manifest(
                results,
                runtime="docker",
                runtime_identity="sha256:pinned-image-id",
                tool_versions="MAFFT v7.526; trimAl 1.4; IQ-TREE 2.3",
            )
            rows: list[dict[str, str]] = []
            with mock.patch.dict(
                os.environ,
                {
                    "PHYLOGENY_DOCKER_IMAGE": "clusterweave-phylogeny:1.0.0",
                },
                clear=True,
            ):
                self.module.add_phylogeny_runtime_row(
                    rows,
                    results_root=results,
                    captured_at="2026-07-11T00:00:00+00:00",
                )

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["stage"], "optional_sequence_phylogeny")
            self.assertEqual(row["artifact"], "phylogeny_docker_image")
            self.assertEqual(
                row["source_uri"],
                "docker://clusterweave-phylogeny:1.0.0",
            )
            self.assertEqual(row["resolved_digest"], "sha256:pinned-image-id")
            self.assertIn("IQ-TREE 2.3", row["tool_versions"])
            self.assertEqual(row["sha256"], "")

    def test_sif_runtime_records_file_sha_identity_and_tool_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            sif = root / "clusterweave_phylogeny_1.0.0.sif"
            sif.write_bytes(b"pinned phylogeny sif\n")
            digest = hashlib.sha256(sif.read_bytes()).hexdigest()
            self.write_manifest(
                results,
                runtime="apptainer",
                runtime_identity=f"sha256:{digest}",
                tool_versions="MAFFT v7.526; trimAl 1.4; IQ-TREE 2.3",
            )
            rows: list[dict[str, str]] = []
            with mock.patch.dict(
                os.environ,
                {
                    "PHYLOGENY_SIF_PATH": str(sif),
                    "PHYLOGENY_SIF_SOURCE": "local-pinned-sif:test",
                },
                clear=True,
            ):
                self.module.add_phylogeny_runtime_row(
                    rows,
                    results_root=results,
                    captured_at="2026-07-11T00:00:00+00:00",
                )

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["artifact"], "phylogeny_sif")
            self.assertEqual(row["resolved_digest"], f"sha256:{digest}")
            self.assertEqual(row["sha256"], digest)
            self.assertEqual(row["size_bytes"], str(sif.stat().st_size))
            self.assertIn("MAFFT v7.526", row["tool_versions"])

    def test_unavailable_runtime_manifest_does_not_claim_an_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / "results"
            self.write_manifest(
                results,
                runtime="none",
                runtime_identity="",
                tool_versions="",
            )
            rows: list[dict[str, str]] = []
            self.module.add_phylogeny_runtime_row(
                rows,
                results_root=results,
                captured_at="2026-07-11T00:00:00+00:00",
            )
            self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
