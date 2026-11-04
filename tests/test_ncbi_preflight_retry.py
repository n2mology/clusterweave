from __future__ import annotations

import ast
import io
import json
import math
from pathlib import Path
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


class NcbiPreflightRetryTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / "web/app.py").read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fetch_ncbi_datasets_json")
        namespace = {"urllib": __import__("urllib"), "json": json, "time": time, "math": math,
                     "NCBI_DATASETS_API_BASE": "https://example.invalid/datasets/v2", "NCBI_PREFLIGHT_TIMEOUT_SECONDS": 8}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), namespace)
        self.fetch = namespace["fetch_ncbi_datasets_json"]

    def error(self, code, delay=None):
        return urllib.error.HTTPError("https://example.invalid", code, "temporary", {} if delay is None else {"Retry-After": delay}, None)

    def test_rate_limit_waits_for_server_delay_then_returns_authoritative_payload(self):
        with mock.patch.object(urllib.request, "urlopen", side_effect=[self.error(429, "2"), io.BytesIO(b'{"reports":[{"public":"record"}]}')]) as get, mock.patch.object(time, "sleep") as sleep:
            self.assertEqual(self.fetch("genome/accession/GCF_999999999.1/dataset_report"), {"reports": [{"public": "record"}]})
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_permanent_errors_and_unbounded_retry_headers_are_not_retried(self):
        for error in (self.error(404), self.error(401), self.error(429, "60"), self.error(429, "nan"), self.error(503, "unrecognized")):
            with self.subTest(code=error.code), mock.patch.object(urllib.request, "urlopen", side_effect=error) as get, mock.patch.object(time, "sleep") as sleep:
                with self.assertRaises(urllib.error.HTTPError): self.fetch("taxonomy/taxon/2/dataset_report")
                self.assertEqual(get.call_count, 1)
                sleep.assert_not_called()

    def test_transient_errors_are_bounded_and_never_replace_missing_metadata(self):
        for error in (self.error(503), urllib.error.URLError("temporary"), TimeoutError()):
            with self.subTest(error=type(error).__name__), mock.patch.object(urllib.request, "urlopen", side_effect=error) as get, mock.patch.object(time, "sleep") as sleep:
                with self.assertRaises(type(error)): self.fetch("genome/accession/GCF_999999999.1/dataset_report")
                self.assertEqual(get.call_count, 3)
                self.assertEqual(sleep.call_args_list, [mock.call(1), mock.call(2)])


if __name__ == "__main__":
    unittest.main()
