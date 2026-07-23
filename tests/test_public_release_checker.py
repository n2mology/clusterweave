from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
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

    def test_safe_text_and_local_image_link_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "figure.svg"
            image.write_text("<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>", encoding="utf-8")
            readme = root / "README.md"
            readme.write_text("![figure](figure.svg)\n", encoding="utf-8")
            result, output = self.run_checker(root, [readme, image])
            self.assertEqual(result, 0, output)

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
