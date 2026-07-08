from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"


class JobStoreAtomicWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data_dir = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self.tmp.name
        self.inserted_web_path = False
        if str(WEB_DIR) not in sys.path:
            sys.path.insert(0, str(WEB_DIR))
            self.inserted_web_path = True
        sys.modules.pop("job_store", None)
        self.job_store = importlib.import_module("job_store")

    def tearDown(self) -> None:
        sys.modules.pop("job_store", None)
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

    def test_write_job_uses_unique_temp_file_for_each_save(self) -> None:
        created = self.job_store.now_iso()
        job = {
            "id": "atomicjob",
            "name": "atomic",
            "status": "pending",
            "stage": "queued",
            "created_at": created,
            "updated_at": created,
            "log_count": 0,
            "result_files": [],
            "error": None,
        }

        replace_calls: list[Path] = []
        path_class = type(self.job_store.job_meta_path("atomicjob"))
        original_replace = path_class.replace

        def record_replace(path_self: Path, target: Path) -> Path:
            replace_calls.append(path_self)
            return original_replace(path_self, target)

        with mock.patch.object(path_class, "replace", new=record_replace):
            self.job_store.write_job(dict(job, stage="first"))
            self.job_store.write_job(dict(job, stage="second"))

        names = [path.name for path in replace_calls]
        self.assertEqual(2, len(names))
        self.assertEqual(2, len(set(names)))
        self.assertNotIn("job.json.tmp", names)
        for name in names:
            self.assertTrue(name.startswith(".job.json."))
            self.assertTrue(name.endswith(".tmp"))

        stored = self.job_store.read_job("atomicjob")
        self.assertIsNotNone(stored)
        self.assertEqual("second", stored["stage"])


if __name__ == "__main__":
    unittest.main()
