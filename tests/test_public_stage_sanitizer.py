from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from canonical_pipeline import _public_stage_from_stream_line  # noqa: E402


class PublicStageSanitizerTests(unittest.TestCase):
    def test_canonical_script_stage_markers_become_public_safe_stage_labels(self) -> None:
        cases = {
            "[INFO] Stage 1/4: running run_annotation_and_detection.sh": "Running annotation / BGC detection",
            "[INFO] Stage 2/4: running run_bigscape.sh": "Running BiG-SCAPE family graph",
            "[INFO] Stage 3/4: running summarize_clusterweave.sh": "Building summary tables",
            "[INFO] Stage 4/4: running run_clinker.sh": "Staging synteny panels",
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                self.assertEqual(_public_stage_from_stream_line(line), expected)

    def test_non_stage_lines_are_not_exposed_as_public_stage_labels(self) -> None:
        self.assertIsNone(_public_stage_from_stream_line("Downloading private/path/to/raw/output.gbk"))


if __name__ == "__main__":
    unittest.main()
