from __future__ import annotations

from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "run_annotation_and_detection.sh"


class ToolActivityLogCompactionTests(unittest.TestCase):
    def test_private_log_preserves_sanitized_lines_while_each_central_stream_is_bounded(self) -> None:
        script_text = SCRIPT_PATH.read_text(encoding="utf-8")
        match = re.search(
            r"^tool_activity_stream\(\) \{\n.*?^\}\n",
            script_text,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None

        raw_lines = [
            "startup one",
            "startup two",
            "routine three",
            "routine four",
            "Running whole-genome PFAM search",
            "routine six",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            private_path = Path(tmp) / "private.log"
            central_path = Path(tmp) / "central.log"
            shell = f"""
set -euo pipefail
{match.group(0)}
tool_activity_limit_line() {{ printf '%s\\n' "${{1:-}}"; }}
tool_activity_public_message() {{
  if [[ "${{2:-}}" == *"PFAM search"* ]]; then
    printf '%s\\n' "Running whole-genome PFAM search"
    return 0
  fi
  return 1
}}
tool_activity_emit_progress() {{
  printf 'TOOL_PROGRESS genome=%s tool=%s phase=%s message="%s"\\n' "$1" "$2" "$3" "$4" >> {shlex.quote(str(central_path))}
}}
log() {{ printf '%s\\n' "$*" >> {shlex.quote(str(central_path))}; }}
TOOL_ACTIVITY_CENTRAL_RAW_LIMIT=2 tool_activity_stream \
  demo antismash stderr {shlex.quote(str(private_path))} detect
"""
            completed = subprocess.run(
                ["bash", "-c", shell],
                input="\n".join(raw_lines) + "\n",
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)

            self.assertEqual(raw_lines, private_path.read_text(encoding="utf-8").splitlines())
            central = central_path.read_text(encoding="utf-8").splitlines()
            central_raw = [line for line in central if line.startswith("TOOL_RAW ")]
            self.assertEqual(2, len(central_raw))
            self.assertIn(
                "TOOL_RAW_SUMMARY genome=demo tool=antismash stream=stderr total=6 central_emitted=2 private_retained=6",
                central,
            )
            self.assertTrue(
                any("TOOL_PROGRESS" in line and "PFAM search" in line for line in central),
                "structured progress must still be emitted after the raw-line cap",
            )


if __name__ == "__main__":
    unittest.main()
