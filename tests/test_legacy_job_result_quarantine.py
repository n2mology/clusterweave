from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
BACKFILL_PATH = REPO_ROOT / "bin" / "backfill_result_attestations.py"


class LegacyJobResultQuarantineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data_dir = os.environ.get("DATA_DIR")
        self.old_secret = os.environ.get("CLUSTERWEAVE_JOB_TOKEN_SECRET")
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ["CLUSTERWEAVE_JOB_TOKEN_SECRET"] = "r06-fixture-secret"
        self.inserted_web_path = False
        if str(WEB_DIR) not in sys.path:
            sys.path.insert(0, str(WEB_DIR))
            self.inserted_web_path = True
        for name in [
            "app",
            "job_store",
            "legacy_job_results",
            "public_result_backend",
            "public_results",
            "result_attestation",
        ]:
            sys.modules.pop(name, None)
        self.job_store = importlib.import_module("job_store")
        self.compat = importlib.import_module("legacy_job_results")
        self.public_results = importlib.import_module("public_results")

    def tearDown(self) -> None:
        for name in [
            "app",
            "job_store",
            "legacy_job_results",
            "public_result_backend",
            "public_results",
            "result_attestation",
        ]:
            sys.modules.pop(name, None)
        if self.inserted_web_path:
            try:
                sys.path.remove(str(WEB_DIR))
            except ValueError:
                pass
        if self.old_data_dir is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self.old_data_dir
        if self.old_secret is None:
            os.environ.pop("CLUSTERWEAVE_JOB_TOKEN_SECRET", None)
        else:
            os.environ["CLUSTERWEAVE_JOB_TOKEN_SECRET"] = self.old_secret
        self.tmp.cleanup()

    def _load_backfill(self):
        name = "r06_backfill_result_attestations"
        sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location(name, BACKFILL_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _write_job(self, job: dict[str, object]) -> Path:
        path = self.job_store.job_meta_path(str(job["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(job, indent=2), encoding="utf-8")
        return path

    def test_pre_public_transitional_and_canonical_formats_are_explicit(self) -> None:
        pre_public = {"id": "prepublic", "result_files": ["results/figure.svg"]}
        transitional = {
            "id": "transition",
            "read_token_hash": "a" * 64,
            "read_token_hashes": ["b" * 64],
            "result_files": ["data/results/demo/figures/figure.svg"],
        }
        canonical = {
            **transitional,
            "id": "canonical",
            "public_run_id": "A" * 22,
        }

        self.assertEqual(
            self.compat.legacy_job_result_format(pre_public), "pre-public"
        )
        self.assertEqual(
            self.compat.legacy_job_result_format(transitional), "transitional"
        )
        self.assertEqual(self.compat.legacy_job_result_format(canonical), "")
        self.assertEqual(
            self.compat.legacy_additional_read_token_hashes(transitional),
            ("b" * 64,),
        )
        self.assertEqual(
            self.compat.legacy_additional_read_token_hashes(canonical), ()
        )

    def test_legacy_alias_is_stable_but_canonical_identity_bypasses_it(self) -> None:
        legacy = {"id": "transition", "read_token_hash": "a" * 64}
        canonical = {
            "id": "canonical",
            "public_run_id": "C" * 22,
            "read_token_hash": "a" * 64,
        }
        first = self.public_results.public_run_id_for_job(legacy)
        second = self.public_results.public_run_id_for_job(legacy)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[A-Za-z0-9_-]{22}$")
        self.assertNotEqual(first, legacy["id"])

        original = self.compat.legacy_public_run_id
        self.compat.legacy_public_run_id = lambda _value: (_ for _ in ()).throw(
            AssertionError("canonical job selected legacy identity")
        )
        try:
            self.assertEqual(
                self.public_results.public_run_id_for_job(canonical), "C" * 22
            )
        finally:
            self.compat.legacy_public_run_id = original

    def test_legacy_result_path_and_internal_bookmark_are_narrow(self) -> None:
        legacy = {"id": "transition", "read_token_hash": "a" * 64}
        canonical = {**legacy, "public_run_id": "D" * 22}
        self.assertTrue(
            self.compat.legacy_result_path_public_shape("results/figure.svg")
        )
        self.assertTrue(
            self.compat.legacy_result_path_public_shape(
                "results/nested/figure.svg"
            )
        )
        for path in [
            "results/private.txt",
            "../results/figure.svg",
        ]:
            with self.subTest(path=path):
                self.assertFalse(
                    self.compat.legacy_result_path_public_shape(path)
                )

        self.assertEqual(
            self.compat.legacy_internal_metadata_job_id(
                "/api/jobs/transition", legacy
            ),
            "transition",
        )
        for route, job in [
            ("/api/jobs/transition/files", legacy),
            ("/api/jobs/transition/logs", legacy),
            ("/api/jobs/transition", canonical),
            ("/api/jobs/../transition", legacy),
        ]:
            with self.subTest(route=route, canonical=bool(job.get("public_run_id"))):
                self.assertEqual(
                    self.compat.legacy_internal_metadata_job_id(route, job), ""
                )

    def test_explicit_backfill_is_idempotent_for_transitional_fixture(self) -> None:
        job_id = "transition"
        now = self.job_store.now_iso()
        self._write_job(
            {
                "id": job_id,
                "name": "transitional fixture",
                "status": "success",
                "stage": "complete",
                "created_at": now,
                "updated_at": now,
                "result_files": ["results/figure.svg"],
                "read_token_hash": "a" * 64,
            }
        )
        root = self.job_store.job_dir(job_id)
        figure = root / "results" / "figure.svg"
        figure.parent.mkdir(parents=True, exist_ok=True)
        figure.write_bytes(b"<svg></svg>\n")
        manifest = root / "downloads" / "public_results_manifest.tsv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        content = figure.read_bytes()
        manifest.write_text(
            "path\tbytes\tsha256\n"
            f"results/figure.svg\t{len(content)}\t"
            f"{hashlib.sha256(content).hexdigest()}\n",
            encoding="utf-8",
        )

        backfill = self._load_backfill()
        first_out = io.StringIO()
        first_err = io.StringIO()
        with redirect_stdout(first_out), redirect_stderr(first_err):
            self.assertEqual(backfill.main([job_id]), 0)
        self.assertEqual(first_err.getvalue(), "")

        summary = self.job_store.job_summary_path(job_id)
        attestation = root / "downloads" / ".clusterweave_result_index.v1.json"
        first_bytes = (summary.read_bytes(), attestation.read_bytes())
        first_mtimes = (summary.stat().st_mtime_ns, attestation.stat().st_mtime_ns)

        second_out = io.StringIO()
        second_err = io.StringIO()
        with redirect_stdout(second_out), redirect_stderr(second_err):
            self.assertEqual(backfill.main([job_id]), 0)
        self.assertEqual(second_err.getvalue(), "")
        self.assertEqual(
            first_bytes, (summary.read_bytes(), attestation.read_bytes())
        )
        self.assertEqual(
            first_mtimes, (summary.stat().st_mtime_ns, attestation.stat().st_mtime_ns)
        )
        self.assertIn("summaries=0", second_out.getvalue())
        self.assertIn("attestations=0", second_out.getvalue())


if __name__ == "__main__":
    unittest.main()
