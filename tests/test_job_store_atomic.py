from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
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
        self.assertEqual(4, len(names))
        self.assertEqual(4, len(set(names)))
        self.assertNotIn("job.json.tmp", names)
        self.assertEqual(2, sum(name.startswith(".job.json.") for name in names))
        self.assertEqual(
            2,
            sum(name.startswith(".job_summary.v1.json.") for name in names),
        )
        for name in names:
            self.assertTrue(name.endswith(".tmp"))

        stored = self.job_store.read_job("atomicjob")
        self.assertIsNotNone(stored)
        self.assertEqual("second", stored["stage"])

        summaries = self.job_store.list_job_summaries()
        self.assertEqual(1, len(summaries))
        self.assertEqual("atomicjob", summaries[0]["id"])
        self.assertNotIn("result_files", summaries[0])
        self.assertEqual(0, summaries[0]["result_file_count"])

    def test_compact_summary_keeps_current_attempt_and_safe_original_rerun_mask(self) -> None:
        created = self.job_store.now_iso()
        job = {
            "id": "rerunmask",
            "name": "rerun-mask",
            "status": "success",
            "stage": "complete",
            "created_at": created,
            "updated_at": created,
            "result_files": [],
            "settings": {
                "run_genome_prep": False,
                "run_annotation": False,
                "run_bigscape": False,
                "run_summary": False,
                "run_crosswalk": False,
                "run_clinker": False,
                "execute_clinker": False,
                "run_figures": True,
                "run_nplinker": False,
            },
            "submission_settings": {
                "run_genome_prep": True,
                "run_annotation": True,
                "run_bigscape": True,
                "run_summary": True,
                "run_crosswalk": True,
                "run_clinker": True,
                "execute_clinker": True,
                "run_figures": True,
                "run_nplinker": False,
                "env_overrides": "SECRET_TOKEN=1",
                "taxonomy_metadata": [{"private": "value"}],
                "target_genome": "/private/input.gbk",
            },
        }

        self.job_store.write_job(job)
        summary = self.job_store.list_job_summaries()[0]

        self.assertFalse(summary["settings"]["run_annotation"])
        self.assertTrue(summary["settings"]["run_figures"])
        self.assertEqual(
            {
                "run_genome_prep": True,
                "run_annotation": True,
                "run_bigscape": True,
                "run_summary": True,
                "run_crosswalk": True,
                "run_clinker": True,
                "execute_clinker": True,
                "run_figures": True,
                "run_nplinker": False,
            },
            summary["rerun_stage_settings"],
        )
        serialized = json.dumps(summary)
        self.assertNotIn("env_overrides", serialized)
        self.assertNotIn("taxonomy_metadata", serialized)
        self.assertNotIn("target_genome", serialized)
        self.assertNotIn("submission_settings", serialized)

    def test_legacy_summary_sidecar_self_heals_safe_rerun_mask(self) -> None:
        created = self.job_store.now_iso()
        job = {
            "id": "legacyrerun",
            "name": "legacy-rerun",
            "status": "success",
            "stage": "complete",
            "created_at": created,
            "updated_at": created,
            "result_files": [],
            "settings": {"run_annotation": False, "run_figures": True},
            "submission_settings": {
                "run_annotation": True,
                "run_figures": True,
                "env_overrides": "DO_NOT_COPY=1",
            },
        }
        self.job_store.write_job(job)
        summary_path = self.job_store.job_summary_path("legacyrerun")
        legacy = json.loads(summary_path.read_text(encoding="utf-8"))
        legacy.pop("rerun_stage_settings")
        summary_path.write_text(json.dumps(legacy), encoding="utf-8")

        summary = self.job_store.list_job_summaries()[0]
        refreshed = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(
            {"run_annotation": True, "run_figures": True},
            summary["rerun_stage_settings"],
        )
        self.assertEqual(summary["rerun_stage_settings"], refreshed["rerun_stage_settings"])
        self.assertNotIn("env_overrides", json.dumps(refreshed))
        self.assertNotIn("submission_settings", refreshed)

    def test_log_window_returns_tail_and_earlier_pages(self) -> None:
        path = self.job_store.job_logs_path("windowjob")
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"line {index}" for index in range(5000)]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        tail = self.job_store.read_log_window("windowjob", tail=True, limit=500)
        self.assertEqual((4500, 5000, 5000), (tail.start, tail.end, tail.total))
        self.assertEqual(lines[4500:], tail.lines)

        earlier = self.job_store.read_log_window(
            "windowjob", before=tail.start, limit=500
        )
        self.assertEqual((4000, 4500, 5000), (earlier.start, earlier.end, earlier.total))
        self.assertEqual(lines[4000:4500], earlier.lines)
        self.assertEqual(tail.generation, earlier.generation)

    def test_sparse_log_slice_preserves_incremental_admin_cursor_semantics(self) -> None:
        path = self.job_store.job_logs_path("longjob")
        path.parent.mkdir(parents=True, exist_ok=True)
        original = [f"line {index}" for index in range(5000)]
        path.write_text("\n".join(original) + "\n", encoding="utf-8")

        initial = self.job_store.read_log_slice("longjob", 0)
        self.assertEqual(5000, initial.total)
        self.assertEqual(original, initial.lines)

        with path.open("a", encoding="utf-8") as handle:
            handle.write("line 5000\nline 5001\n")
        incremental = self.job_store.read_log_slice("longjob", 5000)
        self.assertEqual(5002, incremental.total)
        self.assertEqual(["line 5000", "line 5001"], incremental.lines)
        self.assertEqual(initial.generation, incremental.generation)

        arbitrary = self.job_store.read_log_slice("longjob", 4095)
        self.assertEqual(original[4095:] + ["line 5000", "line 5001"], arbitrary.lines)

    def test_log_slice_generation_resets_after_atomic_replacement(self) -> None:
        path = self.job_store.job_logs_path("replacedjob")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old one\nold two\n", encoding="utf-8")
        before = self.job_store.read_log_slice("replacedjob", 0)

        self.job_store.atomic_write_text(path, "new one\n")
        after = self.job_store.read_log_slice("replacedjob", 0)
        self.assertNotEqual(before.generation, after.generation)
        self.assertEqual(1, after.total)
        self.assertEqual(["new one"], after.lines)

    def test_log_slice_waits_for_complete_newline(self) -> None:
        path = self.job_store.job_logs_path("partialjob")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"complete\npartial")
        first = self.job_store.read_log_slice("partialjob", 0)
        self.assertEqual(["complete"], first.lines)
        self.assertEqual(1, first.total)

        with path.open("ab") as handle:
            handle.write(b" line\n")
        second = self.job_store.read_log_slice("partialjob", 1)
        self.assertEqual(["partial line"], second.lines)
        self.assertEqual(2, second.total)

    def test_same_inode_larger_replacement_resets_generation(self) -> None:
        path = self.job_store.job_logs_path("sameinode")
        path.parent.mkdir(parents=True, exist_ok=True)
        old_lines = [f"old-{index:03d}-aaaaaaaa" for index in range(64)]
        path.write_text("\n".join(old_lines) + "\n", encoding="utf-8")
        before_inode = path.stat().st_ino
        before = self.job_store.read_log_slice("sameinode", 0)

        new_lines = [f"new-{index:03d}-bbbbbbbbbbbb" for index in range(96)]
        with path.open("w", encoding="utf-8") as handle:
            handle.write("\n".join(new_lines) + "\n")

        self.assertEqual(before_inode, path.stat().st_ino)
        after = self.job_store.read_log_slice("sameinode", 0)
        self.assertNotEqual(before.generation, after.generation)
        self.assertEqual(new_lines, after.lines)
        self.assertEqual(len(new_lines), after.total)

    def test_minimum_total_withholds_legacy_partial_rewrite(self) -> None:
        path = self.job_store.job_logs_path("legacyrewrite")
        path.parent.mkdir(parents=True, exist_ok=True)
        old_lines = [f"historical-{index:03d}" for index in range(80)]
        path.write_text("\n".join(old_lines) + "\n", encoding="utf-8")
        before_inode = path.stat().st_ino
        before = self.job_store.read_log_slice(
            "legacyrewrite", 0, minimum_total=len(old_lines)
        )

        with path.open("wb") as handle:
            handle.write(b"replacement-000\nreplacement-partial")
        withheld = self.job_store.read_log_slice(
            "legacyrewrite", 0, minimum_total=len(old_lines)
        )
        self.assertEqual(before_inode, path.stat().st_ino)
        self.assertEqual([], withheld.lines)
        self.assertEqual(0, withheld.total)
        self.assertEqual(before.generation, withheld.generation)

        new_lines = [f"replacement-{index:03d}" for index in range(100)]
        with path.open("w", encoding="utf-8") as handle:
            handle.write("\n".join(new_lines) + "\n")
        complete = self.job_store.read_log_slice(
            "legacyrewrite", 0, minimum_total=len(old_lines)
        )
        self.assertNotEqual(before.generation, complete.generation)
        self.assertEqual(new_lines, complete.lines)

    def test_write_logs_replacement_never_exposes_staged_prefix(self) -> None:
        old_lines = [f"old {index}" for index in range(40)]
        new_lines = [f"new {index}" for index in range(120)]
        self.job_store.write_logs("atomiclogs", old_lines)
        path = self.job_store.job_logs_path("atomiclogs")
        before = self.job_store.read_log_slice("atomiclogs", 0)
        staged = threading.Event()
        release = threading.Event()
        failures: list[BaseException] = []

        def delayed_atomic_write(target: Path, data: str) -> None:
            temp = target.with_name(".logs.txt.delayed.tmp")
            try:
                temp.write_text(data[: max(1, len(data) // 3)], encoding="utf-8")
                staged.set()
                if not release.wait(2):
                    raise TimeoutError("test did not release staged log replacement")
                temp.write_text(data, encoding="utf-8")
                temp.replace(target)
            finally:
                temp.unlink(missing_ok=True)

        def replace_logs() -> None:
            try:
                with mock.patch.object(
                    self.job_store, "atomic_write_text", side_effect=delayed_atomic_write
                ):
                    self.job_store.write_logs("atomiclogs", new_lines)
            except BaseException as exc:  # pragma: no cover - assertion reports it
                failures.append(exc)

        writer = threading.Thread(target=replace_logs)
        writer.start()
        self.assertTrue(staged.wait(2))
        self.assertEqual(old_lines, path.read_text(encoding="utf-8").splitlines())
        release.set()
        writer.join(2)
        self.assertFalse(writer.is_alive())
        self.assertEqual([], failures)

        after = self.job_store.read_log_slice("atomiclogs", 0)
        self.assertNotEqual(before.generation, after.generation)
        self.assertEqual(new_lines, after.lines)

    def test_append_log_lines_separates_partial_legacy_tail(self) -> None:
        path = self.job_store.job_logs_path("partialtail")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("legacy tail without newline", encoding="utf-8")
        appended = self.job_store.append_log_lines(
            "partialtail", ["new one", "new two"]
        )
        self.assertEqual(2, appended)
        self.assertEqual(
            ["legacy tail without newline", "new one", "new two"],
            self.job_store.read_logs("partialtail"),
        )


if __name__ == "__main__":
    unittest.main()
