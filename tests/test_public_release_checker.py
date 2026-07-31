from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "bin" / "check_public_release.py"
SPEC = importlib.util.spec_from_file_location("clusterweave_public_release_checker", CHECKER_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class PublicReleaseCheckerTests(unittest.TestCase):
    def run_checker(self, root: Path, paths: list[Path]) -> tuple[int, str]:
        output = io.StringIO()
        with (
            mock.patch.object(CHECKER, "ROOT", root),
            mock.patch.object(CHECKER, "tracked_files", return_value=paths),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(output),
        ):
            result = CHECKER.main()
        return result, output.getvalue()

    def test_git_discovery_is_nul_safe_and_omits_deleted_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            newline_name = "line\nbreak.txt"
            newline_path = root / newline_name
            newline_path.write_text("safe\n", encoding="utf-8")
            dangling = root / "dangling.txt"
            dangling.symlink_to("missing.txt")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"{newline_name}\0deleted.txt\0{dangling.name}\0",
            )
            with (
                mock.patch.object(CHECKER, "ROOT", root),
                mock.patch.object(CHECKER.subprocess, "run", return_value=completed) as run,
            ):
                paths = CHECKER.tracked_files()

            self.assertEqual(paths, [newline_path, dangling])
            self.assertIn("-z", run.call_args.args[0])

    def test_explicit_manifest_rejects_escaping_missing_duplicate_and_non_regular_members(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            safe = root / "safe.txt"
            safe.write_text("safe\n", encoding="utf-8")
            directory = root / "directory"
            directory.mkdir()
            missing = root / "missing.txt"
            escaping = root.parent / "outside.txt"
            escaping.write_text("safe\n", encoding="utf-8")

            result, output = self.run_checker(
                root,
                [safe, safe, missing, directory, escaping],
            )

            self.assertEqual(result, 1)
            self.assertIn("escaping public source manifest member", output)
            self.assertIn("duplicate public source manifest member: safe.txt", output)
            self.assertIn("missing public source manifest member: missing.txt", output)
            self.assertIn("non-regular public source manifest member: directory", output)

    def test_archive_discovery_rejects_dangling_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dangling = root / "dangling.txt"
            dangling.symlink_to("missing.txt")
            output = io.StringIO()
            with (
                mock.patch.object(CHECKER, "ROOT", root),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(output),
            ):
                result = CHECKER.main()

            self.assertEqual(result, 1)
            self.assertIn("public source symlink is not allowed: dangling.txt", output.getvalue())

    def test_list_files0_cli_emits_validated_sorted_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checker_copy = root / "bin" / "check_public_release.py"
            checker_copy.parent.mkdir()
            checker_copy.write_bytes(CHECKER_PATH.read_bytes())
            (root / "zeta.txt").write_text("zeta\n", encoding="utf-8")
            (root / "alpha.txt").write_text("alpha\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, "-B", str(checker_copy), "--list-files0"],
                cwd=root,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(
                result.stdout.split(b"\0")[:-1],
                [b"alpha.txt", b"bin/check_public_release.py", b"zeta.txt"],
            )
            self.assertEqual(result.stderr, b"")

    def test_safe_text_and_local_image_link_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "figure.svg"
            image.write_text("<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>", encoding="utf-8")
            readme = root / "README.md"
            readme.write_text("![figure](figure.svg)\n", encoding="utf-8")
            result, output = self.run_checker(root, [readme, image])
            self.assertEqual(result, 0, output)

    def test_root_browser_qa_manifests_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifests = [root / "package.json", root / "package-lock.json"]
            for manifest in manifests:
                manifest.write_text("{}\n", encoding="utf-8")
            result, output = self.run_checker(root, manifests)
            self.assertEqual(result, 1)
            self.assertIn("private browser QA manifest is not public source", output)

    def test_backup_suffix_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / "script.py.orig"
            backup.write_text("print('old')\n", encoding="utf-8")
            result, output = self.run_checker(root, [backup])
            self.assertEqual(result, 1)
            self.assertIn("forbidden public artifact type", output)
            self.assertNotIn("print('old')", output)

    def test_constructed_private_key_shape_fails_without_echoing_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = "-" * 5
            payload = marker + "BEGIN " + "PRIVATE" + " KEY" + marker + "\nsynthetic\n"
            fixture = root / "fixture.txt"
            fixture.write_text(payload, encoding="utf-8")
            result, output = self.run_checker(root, [fixture])
            self.assertEqual(result, 1)
            self.assertIn("private-key material", output)
            self.assertNotIn("synthetic", output)

    def test_symlink_and_broken_image_link_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.txt"
            target.write_text("safe\n", encoding="utf-8")
            link = root / "linked.txt"
            link.symlink_to(target.name)
            readme = root / "README.md"
            readme.write_text("![missing](missing.svg)\n", encoding="utf-8")
            result, output = self.run_checker(root, [link, readme])
            self.assertEqual(result, 1)
            self.assertIn("public source symlink is not allowed", output)
            self.assertIn("broken or escaping link", output)


if __name__ == "__main__":
    unittest.main()
