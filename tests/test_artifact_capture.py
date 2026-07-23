import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "capture_external_artifacts.py"


def load_module():
    spec = importlib.util.spec_from_file_location("capture_external_artifacts", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ArtifactCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_sha256_file_reports_digest_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "artifact.txt"
            path.write_bytes(b"clusterweave\n")
            digest, size = self.module.sha256_file(path)
        self.assertEqual(digest, hashlib.sha256(b"clusterweave\n").hexdigest())
        self.assertEqual(size, len(b"clusterweave\n"))

    def test_digest_and_tag_parse_container_sources(self) -> None:
        source = "docker://example/tool:1.2.3@sha256:abc123"
        self.assertEqual(self.module.tag_from_source(source), "1.2.3")
        self.assertEqual(self.module.digest_from_source(source), "sha256:abc123")

    def run_capture(self, tmpdir: Path, env: dict[str, str], docker_identifier: str = "") -> list[dict[str, str]]:
        output = tmpdir / "external_artifacts.tsv"
        old_argv = sys.argv[:]
        argv = [
            "capture_external_artifacts.py",
            "--project-root",
            str(tmpdir),
            "--project-name",
            "demo",
            "--output",
            str(output),
        ]
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            self.module, "docker_image_identifier", return_value=docker_identifier
        ):
            sys.argv = argv
            try:
                self.module.main()
            finally:
                sys.argv = old_argv
        with output.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    def funannotate_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        return [row for row in rows if row["artifact"].startswith("funannotate")]

    def test_docker_funannotate_provenance_uses_baked_runtime_image(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            rows = self.run_capture(
                Path(raw_tmpdir),
                {"ENGINE": "docker", "CLUSTERWEAVE_RUNTIME_MODE": "lab-docker"},
                docker_identifier="sha256:baked-image-id",
            )

        fun_rows = self.funannotate_rows(rows)
        self.assertEqual(len(fun_rows), 1)
        row = fun_rows[0]
        self.assertEqual(row["artifact"], "funannotate_docker_image")
        self.assertEqual(row["source_uri"], "docker://clusterweave-funannotate:v1.8.17-busco")
        self.assertEqual(row["local_path"], "docker-image://clusterweave-funannotate:v1.8.17-busco")
        self.assertEqual(row["version_or_tag"], "v1.8.17-busco")
        self.assertEqual(row["resolved_digest"], "sha256:baked-image-id")
        self.assertEqual(row["sha256"], "")
        self.assertEqual(row["size_bytes"], "")
        self.assertNotEqual(row["source_uri"], "docker://nextgenusfs/funannotate:v1.8.17")

    def test_sif_funannotate_provenance_keeps_sif_path_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            tmpdir = Path(raw_tmpdir)
            sif = tmpdir / "software" / "funannotate" / "funannotate_v1.8.17.sif"
            sif.parent.mkdir(parents=True)
            sif.write_bytes(b"sif-runtime\n")
            rows = self.run_capture(
                tmpdir,
                {
                    "ENGINE": "apptainer",
                    "FUNANNOTATE_BASE_IMAGE_URI": "docker://nextgenusfs/funannotate:v1.8.17",
                },
            )

        fun_rows = self.funannotate_rows(rows)
        self.assertEqual(len(fun_rows), 1)
        row = fun_rows[0]
        self.assertEqual(row["artifact"], "funannotate_sif")
        self.assertEqual(row["source_uri"], "docker://nextgenusfs/funannotate:v1.8.17")
        self.assertEqual(row["local_path"], str(sif))
        self.assertEqual(row["version_or_tag"], "v1.8.17")
        self.assertEqual(row["sha256"], hashlib.sha256(b"sif-runtime\n").hexdigest())
        self.assertEqual(row["size_bytes"], str(len(b"sif-runtime\n")))

    def test_optional_phylogeny_docker_identity_and_versions_are_captured(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            tmpdir = Path(raw_tmpdir)
            manifest = tmpdir / "phylogeny_run_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "runtime": "docker",
                        "runtime_identity": "sha256:pinned-image-id",
                        "tool_versions": "MAFFT 7.526; IQ-TREE 2.4.0; ETE 4.3.0; trimAl 1.5.0",
                    }
                ),
                encoding="utf-8",
            )
            rows = self.run_capture(
                tmpdir,
                {
                    "ENGINE": "docker",
                    "PHYLOGENY_MANIFEST_JSON": str(manifest),
                    "PHYLOGENY_DOCKER_IMAGE": "clusterweave-phylogeny:1.0.0",
                },
            )

        phylogeny = [row for row in rows if row["stage"] == "optional_sequence_phylogeny"]
        self.assertEqual(len(phylogeny), 1)
        row = phylogeny[0]
        self.assertEqual(row["artifact"], "phylogeny_docker_image")
        self.assertEqual(row["source_uri"], "docker://clusterweave-phylogeny:1.0.0")
        self.assertEqual(row["resolved_digest"], "sha256:pinned-image-id")
        self.assertIn("IQ-TREE 2.4.0", row["tool_versions"])
        self.assertEqual(row["sha256"], "")

    def test_optional_phylogeny_sif_sha_and_versions_are_captured(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            tmpdir = Path(raw_tmpdir)
            sif = tmpdir / "phylogeny.sif"
            sif.write_bytes(b"pinned phylogeny sif\n")
            manifest = tmpdir / "phylogeny_run_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "runtime": "apptainer",
                        "runtime_identity": "sha256:manifest-sif-id",
                        "tool_versions": "MAFFT 7.526; IQ-TREE 2.4.0",
                    }
                ),
                encoding="utf-8",
            )
            rows = self.run_capture(
                tmpdir,
                {
                    "ENGINE": "apptainer",
                    "PHYLOGENY_MANIFEST_JSON": str(manifest),
                    "PHYLOGENY_SIF_PATH": str(sif),
                },
            )

        phylogeny = [row for row in rows if row["stage"] == "optional_sequence_phylogeny"]
        self.assertEqual(len(phylogeny), 1)
        row = phylogeny[0]
        self.assertEqual(row["artifact"], "phylogeny_sif")
        self.assertEqual(row["resolved_digest"], "sha256:manifest-sif-id")
        self.assertEqual(row["sha256"], hashlib.sha256(b"pinned phylogeny sif\n").hexdigest())
        self.assertEqual(row["size_bytes"], str(len(b"pinned phylogeny sif\n")))
        self.assertIn("MAFFT 7.526", row["tool_versions"])


if __name__ == "__main__":
    unittest.main()
