import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPACTOR = REPO_ROOT / "bin" / "compact_antismash_shard.py"


def load_compactor_module():
    spec = importlib.util.spec_from_file_location("compact_antismash_shard", COMPACTOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load antiSMASH shard compactor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shard_document(record_id: str, other_id: str = "other") -> dict:
    return {
        "version": "8.0.4",
        "input_file": "/work/input.gbk",
        "schema": 4,
        "taxon": "fungi",
        "records": [
            {
                "id": other_id,
                "seq": "AAAA",
                "features": [],
                "areas": [],
                "modules": [],
            },
            {
                "id": record_id,
                "seq": "CCCC",
                "features": [{"type": "CDS"}],
                "areas": [{"start": 1, "end": 4}],
                "modules": [],
            },
        ],
        "timings": {
            other_id: {"ignored": 99.0},
            record_id: {"detector": 1.25},
        },
    }


def write_raw_shard(root: Path, record_id: str, *, json_name: str | None = None) -> Path:
    shard = root / f"shard_{record_id}"
    shard.mkdir()
    name = json_name or f"{record_id}.json"
    (shard / name).write_text(
        json.dumps(shard_document(record_id)) + "\n", encoding="utf-8"
    )
    (shard / "index.html").write_text("large HTML\n", encoding="utf-8")
    (shard / "regions.js").write_text("large JS\n", encoding="utf-8")
    (shard / "data").mkdir()
    (shard / "data" / "payload.js").write_text("repeated payload\n", encoding="utf-8")
    (shard / f"{record_id}.region001.gbk").write_text("root region\n", encoding="utf-8")
    (shard / "nested").mkdir()
    # The duplicate basename proves compaction preserves relative paths rather
    # than flattening and silently overwriting a region.
    (shard / "nested" / f"{record_id}.region001.gbk").write_text(
        "nested region\n", encoding="utf-8"
    )
    return shard


def tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class AntismashShardCompactionTests(unittest.TestCase):
    def run_compactor(
        self, shard: Path, record_id: str, json_name: str, *, retain: str = "0"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(COMPACTOR),
                "--shard-dir",
                str(shard),
                "--record-id",
                record_id,
                "--json-name",
                json_name,
                "--retain",
                retain,
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_compacts_to_target_json_regions_and_marker_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_id = "recordA"
            shard = write_raw_shard(root, record_id)

            result = self.run_compactor(shard, record_id, f"{record_id}.json")
            self.assertEqual(result.returncode, 0, result.stderr)

            files = set(tree_snapshot(shard))
            self.assertEqual(
                files,
                {
                    ".compacted",
                    f"{record_id}.json",
                    f"{record_id}.region001.gbk",
                    f"nested/{record_id}.region001.gbk",
                },
            )
            compact = json.loads((shard / f"{record_id}.json").read_text(encoding="utf-8"))
            self.assertEqual([record["id"] for record in compact["records"]], [record_id])
            self.assertEqual(compact["timings"], {record_id: {"detector": 1.25}})
            self.assertEqual(compact["version"], "8.0.4")
            self.assertEqual(compact["schema"], 4)
            self.assertEqual(compact["taxon"], "fungi")
            marker = json.loads((shard / ".compacted").read_text(encoding="utf-8"))
            self.assertEqual(marker["record_id"], record_id)
            self.assertEqual(marker["region_count"], 2)

    def test_fallback_json_is_compacted_at_expected_json_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_id = "recordB"
            shard = write_raw_shard(root, record_id, json_name="result.antismash.json")

            result = self.run_compactor(shard, record_id, f"{record_id}.json")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((shard / f"{record_id}.json").is_file())
            self.assertFalse((shard / "result.antismash.json").exists())

    def test_analyzed_record_and_single_timing_fallback_match_merger_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shard = Path(tmp) / "shard"
            shard.mkdir()
            document = shard_document("normalized-id")
            document["timings"] = {"normalized-timing-id": {"detector": 2.5}}
            (shard / "expected.json").write_text(json.dumps(document), encoding="utf-8")

            result = self.run_compactor(shard, "requested-id", "expected.json")
            self.assertEqual(result.returncode, 0, result.stderr)
            compact = json.loads((shard / "expected.json").read_text(encoding="utf-8"))
            self.assertEqual(compact["records"][0]["id"], "normalized-id")
            self.assertEqual(
                compact["timings"], {"normalized-timing-id": {"detector": 2.5}}
            )

    def test_invalid_json_failure_retains_raw_diagnostics_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shard = write_raw_shard(Path(tmp), "broken")
            (shard / "broken.json").write_text("{not-json", encoding="utf-8")
            before = tree_snapshot(shard)

            result = self.run_compactor(shard, "broken", "broken.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("compaction failed", result.stderr)
            self.assertEqual(tree_snapshot(shard), before)
            self.assertFalse((shard / ".compacted").exists())

    def test_activation_failure_is_transactional(self) -> None:
        module = load_compactor_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shard = write_raw_shard(root, "recordC")
            before = tree_snapshot(shard)

            with mock.patch.object(
                module,
                "_activate_compacted_directory",
                side_effect=OSError("simulated activation failure"),
            ):
                with self.assertRaises(OSError):
                    module.compact_shard(shard, "recordC", "recordC.json")

            self.assertEqual(tree_snapshot(shard), before)
            self.assertEqual(list(root.glob(".shard_recordC.compact.*")), [])

    def test_retain_toggle_preserves_complete_raw_shard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shard = write_raw_shard(Path(tmp), "recordD")
            before = tree_snapshot(shard)

            result = self.run_compactor(shard, "recordD", "recordD.json", retain="1")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(tree_snapshot(shard), before)
            self.assertFalse((shard / ".compacted").exists())

    def test_compacted_shards_remain_compatible_with_pipeline_merger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shard_one = write_raw_shard(root, "record1")
            shard_two = write_raw_shard(root, "record2")
            for shard, record_id in ((shard_one, "record1"), (shard_two, "record2")):
                result = self.run_compactor(shard, record_id, f"{record_id}.json")
                self.assertEqual(result.returncode, 0, result.stderr)

            pipeline = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(
                encoding="utf-8"
            )
            function_body = pipeline.split("merge_antismash_shard_jsons() {", 1)[1].split(
                "\n}\n\nhtml_escape()", 1
            )[0]
            merge_function = "merge_antismash_shard_jsons() {" + function_body + "\n}\n"
            output = root / "merged.antismash.json"
            shell = (
                'funbgcex_python_exec() { python3 "$@"; }\n'
                + merge_function
                + '\nmerge_antismash_shard_jsons "$@"\n'
            )
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    shell,
                    "merge-test",
                    str(output),
                    "record1",
                    str(shard_one / "record1.json"),
                    "record2",
                    str(shard_two / "record2.json"),
                ],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([record["id"] for record in merged["records"]], ["record1", "record2"])
            self.assertEqual(set(merged["timings"]), {"record1", "record2"})
            self.assertEqual(merged["version"], "8.0.4")
            self.assertFalse((shard_one / "index.html").exists())
            self.assertFalse((shard_two / "data").exists())


if __name__ == "__main__":
    unittest.main()
