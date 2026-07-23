from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"


class WorkerLogPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data_dir = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self.tmp.name
        self.inserted_web_path = False
        if str(WEB_DIR) not in sys.path:
            sys.path.insert(0, str(WEB_DIR))
            self.inserted_web_path = True
        for name in ["job_store", "canonical_pipeline", "worker"]:
            sys.modules.pop(name, None)
        self.job_store = importlib.import_module("job_store")
        self.worker = importlib.import_module("worker")

    def tearDown(self) -> None:
        for name in ["job_store", "canonical_pipeline", "worker"]:
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
        self.tmp.cleanup()

    def test_repeated_persist_appends_only_new_job_lines(self) -> None:
        created = self.job_store.now_iso()
        meta = {
            "id": "appendworker",
            "name": "append worker",
            "status": "running",
            "stage": "annotation",
            "created_at": created,
            "updated_at": created,
            "log_count": 2,
            "result_files": [],
            "bigscape_viewer_database": (
                "data/results/append_worker/big_scape/public/"
                "clusterweave_viewer.sqlite"
            ),
            "error": None,
            "project_name": "append_worker",
            "result_root": "",
        }
        initial = ["[00:00:01] existing one", "[00:00:02] existing two"]
        self.job_store.write_job(meta)
        self.job_store.write_logs("appendworker", initial)
        path = self.job_store.job_logs_path("appendworker")
        original_inode = path.stat().st_ino

        job = self.worker.build_job_from_meta(meta)
        self.assertEqual(2, job._synced_log_count)
        self.assertEqual(
            job.bigscape_viewer_database,
            meta["bigscape_viewer_database"],
        )
        job.log_lines.extend(
            ["[00:00:03] appended three", "[00:00:04] appended four"]
        )
        self.worker.persist_job(job, 4, {"project_name": "append_worker"})
        self.worker.persist_job(job, 4, {"project_name": "append_worker"})
        job.log_lines.append("[00:00:05] appended five")
        self.worker.persist_job(job, 4, {"project_name": "append_worker"})
        self.worker.persist_job(job, 4, {"project_name": "append_worker"})

        expected = initial + [
            "[00:00:03] appended three",
            "[00:00:04] appended four",
            "[00:00:05] appended five",
        ]
        self.assertEqual(original_inode, path.stat().st_ino)
        self.assertEqual(expected, self.job_store.read_logs("appendworker"))
        stored = self.job_store.read_job("appendworker")
        assert stored is not None
        self.assertEqual(len(expected), stored["log_count"])
        self.assertEqual(
            stored["bigscape_viewer_database"],
            meta["bigscape_viewer_database"],
        )
        self.assertEqual(len(expected), job._synced_log_count)


if __name__ == "__main__":
    unittest.main()
