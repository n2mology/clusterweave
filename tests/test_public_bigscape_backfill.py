from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
SCRIPT_PATH = REPO_ROOT / "bin" / "backfill_public_bigscape_databases.py"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

SPEC = importlib.util.spec_from_file_location(
    "clusterweave_public_bigscape_backfill_test_subject",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
backfill = importlib.util.module_from_spec(SPEC)
_existing_job_store = sys.modules.get("job_store")
_job_store_stub = types.ModuleType("job_store")
_job_store_stub.JOBS_DIR = Path("/nonexistent-clusterweave-test-jobs")
_job_store_stub.append_log_lines = lambda *_args, **_kwargs: 0
_job_store_stub.job_delete_path = lambda job_id: _job_store_stub.JOBS_DIR / job_id / "delete.requested"
_job_store_stub.now_iso = lambda: "2026-01-01T00:00:00+00:00"
_job_store_stub.read_job = lambda _job_id: None
_job_store_stub.read_logs = lambda _job_id: []
_job_store_stub.write_job = lambda _job: None
sys.modules["job_store"] = _job_store_stub
try:
    SPEC.loader.exec_module(backfill)
finally:
    if _existing_job_store is None:
        sys.modules.pop("job_store", None)
    else:
        sys.modules["job_store"] = _existing_job_store


class PublicBigscapeBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.jobs_dir = self.root / "jobs"
        self.job_id = "historical01"
        self.job_dir = self.jobs_dir / self.job_id
        self.job_dir.mkdir(parents=True)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(backfill, "JOBS_DIR", self.jobs_dir))
        self.stack.enter_context(
            mock.patch.object(
                backfill,
                "job_delete_path",
                side_effect=lambda job_id: self.jobs_dir / job_id / "delete.requested",
            )
        )

    def metadata(self, project: str = "demo") -> dict[str, object]:
        return {
            "id": self.job_id,
            "name": project,
            "project_name": project,
            "status": "success",
            "stage": "complete",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-02T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "result_root": f"data/results/{project}",
            "result_files": [],
        }

    def public_preparation(
        self,
        results_root: Path,
        *,
        reused: bool = False,
        viewer: bool = True,
    ):
        public_path = (
            results_root
            / "big_scape"
            / "public"
            / "clusterweave_public.sqlite"
        )
        viewer_path = public_path.with_name("clusterweave_viewer.sqlite")
        return SimpleNamespace(
            errors=(),
            databases=(
                SimpleNamespace(
                    public_path=public_path,
                    public_bytes=4096,
                    viewer_path=viewer_path if viewer else None,
                    viewer_bytes=1024 if viewer else 0,
                    reused=reused,
                ),
            ),
        )

    def test_fallback_result_root_rejects_ancestor_symlink_escape(self) -> None:
        outside = self.root / "outside-results"
        (outside / "demo").mkdir(parents=True)
        (self.job_dir / "data").mkdir()
        (self.job_dir / "data" / "results").symlink_to(outside, target_is_directory=True)
        meta = self.metadata("demo")
        meta["result_root"] = ""

        self.assertIsNone(backfill._safe_result_root(meta, self.job_dir))

    def test_locked_snapshot_re_resolves_result_root_and_ignores_unsafe_project_metadata(
        self,
    ) -> None:
        old_meta = self.metadata("old_demo")
        old_root = self.job_dir / str(old_meta["result_root"])
        old_root.mkdir(parents=True)

        locked_meta = self.metadata("new_demo")
        locked_meta["project_name"] = "../../unsafe-archive-name"
        new_root = self.job_dir / str(locked_meta["result_root"])
        new_root.mkdir(parents=True)
        read_count = 0

        def read_job(_job_id: str) -> dict[str, object]:
            nonlocal read_count
            read_count += 1
            return copy.deepcopy(old_meta if read_count == 1 else locked_meta)

        find_sources = mock.Mock(return_value=[new_root / "big_scape" / "big_scape.db"])
        prepare = mock.Mock(return_value=self.public_preparation(new_root))

        def collect(job, job_dir, layout, **kwargs) -> None:
            self.assertEqual(job_dir, self.job_dir)
            self.assertEqual(layout.results_root, new_root)
            self.assertEqual(layout.project_name, "new_demo")
            kwargs["before_publish"]()
            job.result_files = [
                "downloads/new_demo_public_results.zip",
                "downloads/public_results_manifest.tsv",
                "data/results/new_demo/big_scape/public/clusterweave_public.sqlite",
            ]

        write_job = mock.Mock()
        self.stack.enter_context(mock.patch.object(backfill, "read_job", side_effect=read_job))
        self.stack.enter_context(
            mock.patch.object(backfill, "find_raw_bigscape_databases", find_sources)
        )
        self.stack.enter_context(
            mock.patch.object(backfill, "prepare_public_bigscape_databases", prepare)
        )
        self.stack.enter_context(mock.patch.object(backfill, "_collect_result_files", side_effect=collect))
        self.stack.enter_context(mock.patch.object(backfill, "append_log_lines"))
        self.stack.enter_context(mock.patch.object(backfill, "read_logs", return_value=[]))
        self.stack.enter_context(mock.patch.object(backfill, "write_job", write_job))
        self.stack.enter_context(mock.patch.object(backfill, "now_iso", return_value="2026-01-03T00:00:00+00:00"))

        self.assertEqual(backfill.backfill_one(self.job_id), "ok: created")
        find_sources.assert_called_once_with(new_root)
        prepare.assert_called_once_with(new_root, force=False)
        self.assertEqual(write_job.call_count, 1)
        self.assertIn(
            "data/results/new_demo/big_scape/public/clusterweave_public.sqlite",
            write_job.call_args.args[0]["result_files"],
        )
        self.assertEqual(
            write_job.call_args.args[0]["bigscape_viewer_database"],
            "data/results/new_demo/big_scape/public/clusterweave_viewer.sqlite",
        )
        self.assertNotIn(
            "data/results/new_demo/big_scape/public/clusterweave_viewer.sqlite",
            write_job.call_args.args[0]["result_files"],
        )

    def test_state_change_at_publication_precommit_vetoes_metadata_and_logs(self) -> None:
        state = {"meta": self.metadata("demo")}
        results_root = self.job_dir / str(state["meta"]["result_root"])
        results_root.mkdir(parents=True)

        def read_job(_job_id: str) -> dict[str, object]:
            return copy.deepcopy(state["meta"])

        def collect(_job, _job_dir, _layout, **kwargs) -> None:
            state["meta"]["updated_at"] = "2026-01-04T00:00:00+00:00"
            kwargs["before_publish"]()
            self.fail("the collector must stop when the precommit guard vetoes")

        append_logs = mock.Mock()
        write_job = mock.Mock()
        self.stack.enter_context(mock.patch.object(backfill, "read_job", side_effect=read_job))
        self.stack.enter_context(
            mock.patch.object(
                backfill,
                "find_raw_bigscape_databases",
                return_value=[results_root / "big_scape" / "big_scape.db"],
            )
        )
        self.stack.enter_context(
            mock.patch.object(
                backfill,
                "prepare_public_bigscape_databases",
                return_value=self.public_preparation(results_root),
            )
        )
        self.stack.enter_context(mock.patch.object(backfill, "_collect_result_files", side_effect=collect))
        self.stack.enter_context(mock.patch.object(backfill, "append_log_lines", append_logs))
        self.stack.enter_context(mock.patch.object(backfill, "write_job", write_job))

        self.assertEqual(backfill.backfill_one(self.job_id), "skip: job state changed")
        append_logs.assert_not_called()
        write_job.assert_not_called()

    def test_successful_backfill_clears_a_stale_viewer_pointer_when_unavailable(self) -> None:
        meta = self.metadata("demo")
        meta["bigscape_viewer_database"] = (
            "data/results/demo/big_scape/public/clusterweave_viewer.sqlite"
        )
        results_root = self.job_dir / str(meta["result_root"])
        results_root.mkdir(parents=True)

        def collect(job, _job_dir, _layout, **kwargs) -> None:
            kwargs["before_publish"]()
            job.result_files = [
                "downloads/demo_public_results.zip",
                "downloads/public_results_manifest.tsv",
                "data/results/demo/big_scape/public/clusterweave_public.sqlite",
            ]

        write_job = mock.Mock()
        self.stack.enter_context(
            mock.patch.object(backfill, "read_job", return_value=copy.deepcopy(meta))
        )
        self.stack.enter_context(
            mock.patch.object(
                backfill,
                "find_raw_bigscape_databases",
                return_value=[results_root / "big_scape" / "big_scape.db"],
            )
        )
        self.stack.enter_context(
            mock.patch.object(
                backfill,
                "prepare_public_bigscape_databases",
                return_value=self.public_preparation(results_root, viewer=False),
            )
        )
        self.stack.enter_context(
            mock.patch.object(backfill, "_collect_result_files", side_effect=collect)
        )
        self.stack.enter_context(mock.patch.object(backfill, "append_log_lines"))
        self.stack.enter_context(mock.patch.object(backfill, "read_logs", return_value=[]))
        self.stack.enter_context(mock.patch.object(backfill, "write_job", write_job))

        self.assertEqual(backfill.backfill_one(self.job_id), "ok: created")
        self.assertEqual(write_job.call_args.args[0]["bigscape_viewer_database"], "")

    def test_main_continues_after_one_corrupt_job_and_returns_failure(self) -> None:
        calls: list[str] = []

        def run_one(job_id: str, **_kwargs) -> str:
            calls.append(job_id)
            if job_id == "corrupt01":
                raise ValueError("private failure detail must not be emitted")
            return "ok: reused"

        output = io.StringIO()
        with (
            mock.patch.object(backfill, "_job_ids", return_value=["corrupt01", "healthy01"]),
            mock.patch.object(backfill, "backfill_one", side_effect=run_one),
            mock.patch.object(sys, "argv", [str(SCRIPT_PATH)]),
            contextlib.redirect_stdout(output),
        ):
            return_code = backfill.main()

        self.assertEqual(return_code, 1)
        self.assertEqual(calls, ["corrupt01", "healthy01"])
        self.assertEqual(
            output.getvalue().splitlines(),
            [
                "corrupt01\tfailed: unexpected ValueError",
                "healthy01\tok: reused",
            ],
        )
        self.assertNotIn("private failure detail", output.getvalue())


if __name__ == "__main__":
    unittest.main()
