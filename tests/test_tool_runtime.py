"""Selected runtime version probes and public observation boundaries."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
from tool_runtime import observe, safe_observation, version_from_text, write_observation


class ToolRuntimeTests(unittest.TestCase):
    def test_versions_keep_v_prefixed_and_prerelease_components(self):
        for text, expected in (("Prodigal V2.6.3: February 2016", "2.6.3"),
                               ("BiG-SCAPE 2.0.0-beta.6", "2.0.0-beta.6"),
                               ("clinker 0.0.32", "0.0.32"),
                               ("HMMER 3.1b2 (February 2015)", "3.1b2"),
                               ("trimAl v1.5.rev0 build[2024-05-27]", "1.5.rev0")):
            self.assertEqual(version_from_text(text), expected)

    def test_docker_probe_uses_resolved_image_with_no_pulls_or_job_mounts(self):
        digest = "sha256:" + "a" * 64
        with mock.patch("tool_runtime.bounded_run", side_effect=[(0, digest), (0, "clinker 0.0.32")]) as run:
            record = observe("clinker", "docker", "registry.invalid/clinker:0.0.32--pyhdfd78af_0")
        command = run.call_args_list[-1].args[0]
        self.assertIn(digest, command)
        self.assertEqual(command[command.index("--pull") + 1], "never")
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertNotIn("-v", command)
        self.assertEqual(record["version"], "0.0.32")
        self.assertEqual(record["configured_tag"], "0.0.32--pyhdfd78af_0")
        self.assertNotIn("registry.invalid", json.dumps(record))

    def test_phylogeny_probe_preserves_the_runtime_activation_entrypoint(self):
        with mock.patch("tool_runtime.bounded_run", side_effect=[(0, "sha256:" + "a" * 64), (0, "v7.526")]) as run:
            record = observe("MAFFT", "docker", "phylogeny:1.0.0")
        self.assertNotIn("--entrypoint", run.call_args.args[0])
        self.assertEqual(record["version"], "7.526")

    def test_sif_observation_hashes_the_selected_file_and_checks_for_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sif"; path.write_bytes(b"selected runtime")
            with mock.patch("tool_runtime.bounded_run", return_value=(0, "BiG-SCAPE 2.0.0-beta.6")) as run:
                record = observe("BiG-SCAPE", "apptainer", str(path))
            self.assertEqual(run.call_args.args[0][:4], ["apptainer", "exec", "--cleanenv", str(path)])
            self.assertEqual(record["version"], "2.0.0-beta.6")
            self.assertNotIn(str(path), json.dumps(record))
            with mock.patch("tool_runtime.file_digest", side_effect=["a" * 64, "b" * 64]), mock.patch("tool_runtime.bounded_run", return_value=(0, "2.0.0")):
                changed = observe("BiG-SCAPE", "singularity", str(path))
            self.assertIsNone(changed["version"])
            self.assertNotIn("runtime_sha256", changed)

    def test_funannotate_sif_uses_the_runners_selected_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sif"; path.write_bytes(b"runtime")
            for available, expected in ((0, "/venv/bin/funannotate"), (1, "funannotate")):
                with mock.patch("tool_runtime.bounded_run", side_effect=[(available, ""), (0, "funannotate v1.8.17")]) as run:
                    record = observe("funannotate", "apptainer", str(path))
                self.assertEqual(run.call_args.args[0][-2:], [expected, "--version"])
                self.assertEqual(record["version"], "1.8.17")

    def test_prodigal_nonzero_version_status_is_recorded_but_probe_errors_are_not(self):
        with mock.patch("tool_runtime.shutil.which", return_value="/usr/bin/prodigal"), mock.patch("tool_runtime.file_digest", return_value="a" * 64), mock.patch("tool_runtime.bounded_run", return_value=(1, "Prodigal V2.6.3")):
            self.assertEqual(observe("Prodigal")["version"], "2.6.3")
        with mock.patch("tool_runtime.bounded_run", side_effect=subprocess.TimeoutExpired("docker", 8)):
            self.assertIsNone(observe("clinker", "docker", "unavailable:0.0.32")["version"])

    def test_funannotate_nonzero_version_status_requires_its_own_banner(self):
        with mock.patch("tool_runtime.bounded_run", side_effect=[(0, "sha256:" + "a" * 64), (1, "funannotate v1.8.17")]):
            self.assertEqual(observe("funannotate", "docker", "annotation:1.8.17")["version"], "1.8.17")
        with mock.patch("tool_runtime.bounded_run", side_effect=[(0, "sha256:" + "a" * 64), (1, "Error from Python 3.8.0")]):
            self.assertIsNone(observe("funannotate", "docker", "annotation:1.8.17")["version"])

    def test_snap_date_release_is_retained_from_its_version_banner(self):
        with mock.patch("tool_runtime.shutil.which", return_value="/usr/bin/snap"), mock.patch("tool_runtime.file_digest", return_value="a" * 64), mock.patch("tool_runtime.bounded_run", return_value=(1, "SNAP (version 2006-07-28)")):
            record = observe("SNAP")
        self.assertEqual(record["version"], "2006-07-28")

    def test_observations_drop_private_fields_and_refuse_links(self):
        record = safe_observation({"tool": "clinker", "backend": "native", "version": "0.0.32", "path": "/private/job", "token": "secret", "configured_tag": "secret-value"})
        self.assertNotIn("private", json.dumps(record)); self.assertNotIn("secret", json.dumps(record))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "outside").mkdir(); (root / "linked").symlink_to(root / "outside")
            write_observation(root / "linked", record)
            self.assertEqual(list((root / "outside").iterdir()), [])
