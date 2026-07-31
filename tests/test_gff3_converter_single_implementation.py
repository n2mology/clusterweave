from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE = REPO_ROOT / "run_annotation_and_detection.sh"
TRACKED_CONVERTER = REPO_ROOT / "bin" / "gff3_to_gbk_with_translations.py"


def setup_converter_function() -> str:
    text = PIPELINE.read_text(encoding="utf-8")
    return "setup_converter() {" + text.split("setup_converter() {", 1)[1].split(
        "\n}\n\n###############################################################################\n"
        "# Input discovery/resolution",
        1,
    )[0] + "\n}\n"


class Gff3ConverterSingleImplementationTests(unittest.TestCase):
    def run_setup(self, converter: Path) -> subprocess.CompletedProcess[str]:
        shell = (
            "set -euo pipefail\n"
            "log(){ printf 'LOG:%s\\n' \"$*\"; }\n"
            "die(){ printf 'ERROR:%s\\n' \"$*\" >&2; exit 73; }\n"
            "CONVERT_PY=$1\n"
            "VENV_PY=$2\n"
            + setup_converter_function()
            + "\nsetup_converter\n"
        )
        return subprocess.run(
            ["bash", "-c", shell, "converter-setup", str(converter), "python3"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )

    def test_existing_tracked_or_custom_converter_is_used_without_mutation(self) -> None:
        before = TRACKED_CONVERTER.read_bytes()
        completed = self.run_setup(TRACKED_CONVERTER)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"Using existing converter: {TRACKED_CONVERTER}", completed.stdout)
        self.assertEqual(TRACKED_CONVERTER.read_bytes(), before)

        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "custom converter.py"
            custom.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            before = custom.read_bytes()
            completed = self.run_setup(custom)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(f"Using existing converter: {custom}", completed.stdout)
            self.assertEqual(custom.read_bytes(), before)

    def test_missing_converter_fails_actionably_without_creating_a_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing" / "gff3_to_gbk_with_translations.py"
            completed = self.run_setup(missing)

            self.assertEqual(completed.returncode, 73)
            self.assertIn("GFF3-to-GenBank converter", completed.stderr)
            self.assertIn(str(missing), completed.stderr)
            self.assertIn("CONVERT_PY", completed.stderr)
            self.assertFalse(missing.exists())
            self.assertFalse(missing.parent.exists())


if __name__ == "__main__":
    unittest.main()
