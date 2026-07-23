from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "bin" / "prepare_antismash_web_results.py"
spec = importlib.util.spec_from_file_location("prepare_antismash_web_results", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AntismashWebResultsTests(unittest.TestCase):
    def test_filters_only_region_bearing_records_without_mutating_source(self) -> None:
        document = {
            "records": [
                {"id": "with-region", "areas": [{"start": 1}], "seq": "AAAA"},
                {"id": "without-region", "areas": [], "seq": "CCCC"},
            ],
            "timings": {"with-region": {"a": 1}, "without-region": {"b": 2}},
            "version": "8.0.4",
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "merged.json"
            destination = Path(tmp) / "web.json"
            source.write_text(json.dumps(document), encoding="utf-8")
            original = source.read_bytes()

            count = module.prepare_web_results(source, destination)

            self.assertEqual(count, 1)
            self.assertEqual(source.read_bytes(), original)
            filtered = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual([row["id"] for row in filtered["records"]], ["with-region"])
            self.assertEqual(set(filtered["timings"]), {"with-region"})
            self.assertEqual(filtered["version"], "8.0.4")

    def test_rejects_invalid_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "invalid.json"
            source.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "records list"):
                module.prepare_web_results(source, Path(tmp) / "output.json")


if __name__ == "__main__":
    unittest.main()
