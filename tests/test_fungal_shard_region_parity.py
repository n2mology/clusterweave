from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class FungalShardRegionParityTests(unittest.TestCase):
    def test_real_shard_runner_passes_matching_minlength_to_antismash(self) -> None:
        pipeline = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(
            encoding="utf-8"
        )
        shard_function = "run_antismash_record_shard() {" + pipeline.split(
            "run_antismash_record_shard() {", 1
        )[1].split("\n}\n\nmerge_antismash_shard_jsons() {", 1)[0] + "\n}\n"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "argv.txt"
            row_file = root / "row.tsv"
            stdout_log = root / "stdout.log"
            stderr_log = root / "stderr.log"
            shard_dir = root / "shard"
            ant_input = root / "fungus.gbk"
            ant_input.write_text("fixture\n", encoding="utf-8")
            shell = (
                "set -euo pipefail\n"
                f"CAPTURE={str(capture)!r}\n"
                "ANTISMASH_SHARD_CPUS=3\n"
                "ANTISMASH_MIN_RECORD_BP=1000\n"
                "ANTISMASH_SHARD_COMPACTOR=/unused/compact_antismash_shard.py\n"
                "ANTISMASH_RETAIN_SHARD_WORK=0\n"
                "ANT_FLAGS_ARRAY=(--cb-general)\n"
                "antismash_record_progress(){ :; }\n"
                "run_tool_with_activity(){\n"
                "  printf 'ENV=%s\\n' \"${CLUSTERWEAVE_CHILD_DOCKER_CPUS:-}\" > \"${CAPTURE}\"\n"
                "  printf 'ARG=%s\\n' \"$@\" >> \"${CAPTURE}\"\n"
                "}\n"
                "resolve_python_cmd(){ printf '/bin/true\\n'; }\n"
                + shard_function
                + "\nrun_antismash_record_shard \"$@\"\n"
            )
            completed = subprocess.run(
                [
                    "bash",
                    "-c",
                    shell,
                    "fungal-shard-argv",
                    "Fungus_fixture",
                    str(ant_input),
                    "recordB",
                    "recordB",
                    "2",
                    "4",
                    str(shard_dir),
                    str(row_file),
                    str(stdout_log),
                    str(stderr_log),
                ],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            captured = capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(captured[0], "ENV=3")
            args = [line.removeprefix("ARG=") for line in captured[1:]]
            self.assertEqual(
                args,
                [
                    "Fungus_fixture",
                    "antismash",
                    "record_2",
                    str(stdout_log),
                    str(stderr_log),
                    "antismash_exec",
                    "antismash",
                    str(ant_input),
                    "--minlength",
                    "1000",
                    "--output-dir",
                    str(shard_dir),
                    "--output-basename",
                    "recordB",
                    "--cpus",
                    "3",
                    "--cb-general",
                ],
            )
            self.assertEqual(
                row_file.read_text(encoding="utf-8").split("\t")[:3],
                ["recordB", str(shard_dir), "ok"],
            )

    def test_sharded_assembly_matches_legacy_fungal_region_set_and_count(self) -> None:
        pipeline = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(
            encoding="utf-8"
        )
        record_list_function = "list_genbank_record_ids() {" + pipeline.split(
            "list_genbank_record_ids() {", 1
        )[1].split(
            "\nsafe_antismash_record_id() {", 1
        )[0]
        function = "run_antismash_sharded() {" + pipeline.split(
            "run_antismash_sharded() {", 1
        )[1].split(
            "\n}\n\n###############################################################################\n"
            "# Per-genome logging sync + manifest",
            1,
        )[0] + "\n}\n"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy"
            legacy.mkdir()
            expected = {
                "recordA.region001.gbk": b"legacy-compatible A1\n",
                "recordA.region002.gbk": b"legacy-compatible A2\n",
                "recordB.region001.gbk": b"legacy-compatible B1\n",
            }
            for name, content in expected.items():
                (legacy / name).write_bytes(content)
            record_ids = root / "record_ids.txt"
            ant_input = root / "Fungus_fixture.gbk"
            ant_input.write_text(
                "recordA\t1200\nrecordB\t1000\nshortRecord\t999\n",
                encoding="utf-8",
            )
            fake_bio = root / "fake_bio" / "Bio"
            fake_bio.mkdir(parents=True)
            (fake_bio / "__init__.py").write_text("", encoding="utf-8")
            (fake_bio / "SeqIO.py").write_text(
                "from types import SimpleNamespace\n"
                "def parse(path, format_name):\n"
                "    with open(path, encoding='utf-8') as handle:\n"
                "        for line in handle:\n"
                "            record_id, length = line.rstrip('\\n').split('\\t')\n"
                "            yield SimpleNamespace(id=record_id, name=record_id, seq='N' * int(length))\n",
                encoding="utf-8",
            )
            ant_out = root / "antismash" / "Fungus_fixture"
            ant_out.mkdir(parents=True)
            shard_root = root / "work" / "shards"
            stdout = root / "work" / "aggregate.stdout.log"
            stderr = root / "work" / "aggregate.stderr.log"

            shell = (
                "set -euo pipefail\n"
                f"WORK_ROOT={str(root / 'work')!r}\n"
                f"FAKE_BIO_ROOT={str(root / 'fake_bio')!r}\n"
                "ANTISMASH_MIN_RECORD_BP=1000\n"
                "ANTISMASH_RECORD_PARALLELISM=2\n"
                "mkdir -p \"${WORK_ROOT}/logs\"\n"
                "ANTISMASH_INPUT_PREPARER=/fake/prepare_antismash_input.py\n"
                "funbgcex_python_exec(){\n"
                "  if [[ \"$1\" == \"${ANTISMASH_INPUT_PREPARER}\" && \"$2\" == split-records ]]; then\n"
                "    while IFS=$'\\t' read -r record_id output; do\n"
                "      mkdir -p \"$(dirname \"$output\")\"\n"
                "      cp -f \"$3\" \"$output\"\n"
                "    done < \"$4\"\n"
                "    return 0\n"
                "  fi\n"
                "  PYTHONPATH=\"${FAKE_BIO_ROOT}\" python3 \"$@\"\n"
                "}\n"
                "antismash_input_python_exec(){ funbgcex_python_exec \"$@\"; }\n"
                "log(){ :; }\n"
                "warn(){ printf '%s\\n' \"$*\" >&2; }\n"
                "safe_antismash_record_id(){ printf '%s\\n' \"$1\"; }\n"
                "wait_for_antismash_shard_job(){ local rc=0; set +e; wait -n; rc=$?; set -e; [[ $rc -eq 0 || $rc -eq 127 ]]; }\n"
                "cleanup_antismash_assembled_outputs(){\n"
                "  find \"$1\" -maxdepth 1 -type f -name '*region*.gbk' -delete || true\n"
                "  rm -f \"$2\" \"$1/index.html\" \"$1/.done\"\n"
                "}\n"
                "merge_antismash_shard_jsons(){\n"
                "  local output=$1\n"
                "  printf '{\"records\":[],\"timings\":{}}\\n' > \"$output\"\n"
                "}\n"
                "write_antismash_shard_index(){\n"
                "  printf '<html>records=%s regions=%s</html>\\n' \"$3\" \"$4\" > \"$2/index.html\"\n"
                "}\n"
                "render_antismash_shard_web_bundle(){\n"
                "  printf '<html>rendered web bundle</html>\\n' > \"$3/index.html\"\n"
                "  printf 'window.regions = {};\\n' > \"$3/regions.js\"\n"
                "}\n"
                "run_antismash_record_shard(){\n"
                "  local record_id=$3 safe_id=$4 shard_dir=$7 row_file=$8\n"
                "  mkdir -p \"$shard_dir\"\n"
                "  printf '{\"records\":[{\"id\":\"%s\",\"areas\":[{}]}],\"timings\":{}}\\n' \"$record_id\" > \"$shard_dir/$safe_id.json\"\n"
                "  local count=1\n"
                "  case $record_id in\n"
                "    recordA)\n"
                "      printf 'legacy-compatible A1\\n' > \"$shard_dir/recordA.region001.gbk\"\n"
                "      printf 'legacy-compatible A2\\n' > \"$shard_dir/recordA.region002.gbk\"\n"
                "      count=2\n"
                "      ;;\n"
                "    recordB)\n"
                "      printf 'legacy-compatible B1\\n' > \"$shard_dir/recordB.region001.gbk\"\n"
                "      ;;\n"
                "    shortRecord)\n"
                "      printf '%s\\t%s\\tfailed\\t0\\t0\\n' \"$record_id\" \"$shard_dir\" > \"$row_file\"\n"
                "      return 1\n"
                "      ;;\n"
                "  esac\n"
                "  printf '%s\\t%s\\tok\\t0\\t%s\\n' \"$record_id\" \"$shard_dir\" \"$count\" > \"$row_file\"\n"
                "}\n"
                + record_list_function
                + function
                + "\nlist_genbank_record_ids \"$2\" \"${ANTISMASH_MIN_RECORD_BP}\" > \"$4\"\n"
                + "run_antismash_sharded \"$@\"\n"
            )
            completed = subprocess.run(
                [
                    "bash",
                    "-c",
                    shell,
                    "fungal-shard-parity",
                    "Fungus_fixture",
                    str(ant_input),
                    str(ant_out),
                    str(record_ids),
                    str(shard_root),
                    str(stdout),
                    str(stderr),
                ],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            assembled = {
                path.name: path.read_bytes()
                for path in ant_out.glob("*region*.gbk")
            }
            self.assertEqual(record_ids.read_text(encoding="utf-8"), "recordA\nrecordB\n")
            self.assertEqual(assembled, expected)
            self.assertEqual(len(assembled), len(list(legacy.glob("*region*.gbk"))))
            self.assertTrue((ant_out / ".done").is_file())
            self.assertTrue((ant_out / "Fungus_fixture.antismash.json").is_file())
            rows = (ant_out / "shard_manifest.tsv").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(rows), 3)
            self.assertNotIn("shortRecord", "\n".join(rows))
            self.assertEqual(sum(int(row.split("\t")[4]) for row in rows[1:]), 3)


if __name__ == "__main__":
    unittest.main()
