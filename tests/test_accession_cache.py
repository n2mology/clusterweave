from __future__ import annotations

import io
import json
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import accession_cache as cache
import cached_genbank as adapter


def identity():
    return {
        "schema": 1, "contract": "bacterial-genbank-v1", "accession": "GCF_999999999.1",
        "genome_sha256": "1" * 64, "route": {"taxon": "bacteria", "annotation": "sequence-only"},
        "source_sha256": "2" * 64, "runtime_sha256": "3" * 64,
        "tools": {"python": "3" * 64, "preparation": "2" * 64},
        "containers": "not-used", "databases": "not-used", "models": "not-used",
        "parameters": {"genome_label_sha256": "4" * 64, "min_record_bp": 1, "max_record_bp": 10000},
    }


def payload():
    return {
        "prepared.gbk": adapter.bacterial.format_record("Public__seq", "ATGAAA", "linear").encode(),
        "record_ids.txt": b"Public__seq\n",
        "record_map.tsv": ("input_order\toriginal_record_id\tsanitized_record_id\tsequence_length_bp\t"
                           "topology\tstatus\treason\n1\tseq\tPublic__seq\t6\tlinear\teligible\t\n").encode(),
    }


def validate(value):
    adapter.validate_payload(value, "bacteria")


def concurrent_writer(root, barrier, result):
    barrier.wait()
    try:
        result.put(cache.Store(Path(root)).publish(identity(), payload(), validate))
    except (OSError, ValueError):
        result.put("busy")


def interrupted_writer(root):
    original = cache.Store._sync
    def crash(path):
        original(path)
        if path.name.startswith(".pending-"):
            os.kill(os.getpid(), signal.SIGKILL)
    cache.Store._sync = staticmethod(crash)
    cache.Store(Path(root)).publish(identity(), payload(), validate)


class AccessionCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "store"
        self.root.mkdir(mode=0o700)
        self.store = cache.Store(self.root)
        self.key = cache.identity_key(identity())

    def publish(self):
        self.assertEqual(self.store.publish(identity(), payload(), validate), "published")

    def test_exact_identity_hit_and_canonical_order(self):
        self.publish()
        data, reason, manifest = self.store.lookup(identity(), validate)
        self.assertEqual(data, payload())
        self.assertEqual(reason, "verified")
        self.assertEqual(manifest["key"], self.key)
        self.assertEqual(cache.identity_key(dict(reversed(list(identity().items())))), self.key)

    def test_each_identity_component_changes_key_or_is_ineligible(self):
        self.publish()
        cases = []
        for name, value in (("accession", "GCF_999999999.2"), ("genome_sha256", "a" * 64),
                            ("schema", 2), ("contract", "bacterial-genbank-v2"),
                            ("databases", "a" * 64), ("models", "a" * 64),
                            ("containers", "sha256:" + "a" * 64)):
            candidate = identity()
            candidate[name] = value
            cases.append((name, candidate))
        for name in ("source_sha256", "runtime_sha256"):
            candidate = identity()
            candidate[name] = "a" * 64
            candidate["tools"]["preparation" if name == "source_sha256" else "python"] = "a" * 64
            cases.append((name, candidate))
        for name, value in (("taxon", "fungi"), ("annotation", "funannotate")):
            candidate = identity()
            candidate["route"][name] = value
            cases.append((name, candidate))
        for name in identity()["parameters"]:
            candidate = identity()
            candidate["parameters"][name] = "a" * 64 if name.endswith("sha256") else candidate["parameters"][name] + 1
            cases.append((name, candidate))
        candidate = identity()
        candidate["tools"]["python"] = "latest"
        cases.append(("tool", candidate))
        for name, candidate in cases:
            with self.subTest(name=name):
                try:
                    key = cache.identity_key(candidate)
                except cache.Unavailable:
                    continue
                self.assertNotEqual(key, self.key)
                self.assertIsNone(self.store.lookup(candidate, validate)[0])

    def test_unknown_missing_extra_and_unversioned_identity_rejected(self):
        cases = []
        for field in identity():
            candidate = identity()
            candidate.pop(field)
            cases.append(candidate)
        for accession in ("GCF_999999999", "GCF_999999999.0", "uploaded", "", "gcf_999999999.1"):
            candidate = identity()
            candidate["accession"] = accession
            cases.append(candidate)
        candidate = identity()
        candidate["job_id"] = "private"
        cases.append(candidate)
        candidate = identity()
        candidate["parameters"]["unverified"] = True
        cases.append(candidate)
        for candidate in cases:
            with self.assertRaises((cache.Unavailable, TypeError)):
                cache.identity_key(candidate)

    def test_corrupt_manifest_files_inventory_and_links_quarantined(self):
        changes = ("manifest_json", "manifest_schema", "identity", "missing", "changed", "extra", "symlink", "hardlink", "structure")
        for change in changes:
            with self.subTest(change=change):
                self.publish()
                entry = self.root / "entries" / self.key
                target = entry / "prepared.gbk"
                if change == "manifest_json":
                    (entry / "manifest.json").write_text("[")
                elif change in {"manifest_schema", "identity", "structure"}:
                    manifest = json.loads((entry / "manifest.json").read_bytes())
                    if change == "manifest_schema":
                        manifest["unknown"] = "bad"
                    elif change == "identity":
                        manifest["identity"]["accession"] = "GCF_999999999.2"
                    else:
                        target.write_bytes(b"invalid GenBank\n")
                        manifest["files"]["prepared.gbk"] = {"bytes": target.stat().st_size, "sha256": cache.sha256(target.read_bytes())}
                    (entry / "manifest.json").write_bytes(cache.canonical(manifest))
                elif change == "missing":
                    target.unlink()
                elif change == "changed":
                    target.write_bytes(b"changed\n")
                elif change == "extra":
                    (entry / "job.json").write_text("private")
                elif change == "symlink":
                    target.unlink()
                    target.symlink_to(self.root / ".lock")
                else:
                    target.unlink()
                    os.link(entry / "record_ids.txt", target)
                data, reason, _ = self.store.lookup(identity(), validate)
                self.assertIsNone(data)
                self.assertEqual(reason, "quarantined")
                self.assertFalse(entry.exists())
        self.assertEqual(len(list((self.root / "quarantine").iterdir())), len(changes))

    def test_symlinked_entry_and_store_rejected_without_following_target(self):
        with self.store.locked():
            pass
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir(mode=0o700)
        (outside / "keep").write_text("untouched")
        (self.root / "entries" / self.key).symlink_to(outside, target_is_directory=True)
        self.assertIsNone(self.store.lookup(identity(), validate)[0])
        self.assertEqual((outside / "keep").read_text(), "untouched")
        alias = Path(self.temporary.name) / "alias"
        alias.symlink_to(self.root)
        with self.assertRaises(cache.Unavailable):
            cache.Store(alias).lookup(identity(), validate)

    def test_wrong_permissions_and_missing_store_are_misses(self):
        self.root.chmod(0o755)
        with self.assertRaises(cache.Unavailable):
            self.store.lookup(identity(), validate)
        missing = self.root / "missing"
        with self.assertRaises(cache.Unavailable):
            cache.Store(missing).lookup(identity(), validate)
        self.assertFalse(missing.exists())

    def test_duplicate_and_conflicting_writers(self):
        self.publish()
        self.assertEqual(self.store.publish(identity(), payload(), validate), "duplicate")
        different = payload()
        different["record_map.tsv"] = different["record_map.tsv"].replace(b"1\tseq\t", b"1\tother\t")
        self.assertEqual(self.store.publish(identity(), different, validate), "conflicting_outputs")
        self.assertIsNone(self.store.lookup(identity(), validate)[0])

    def test_real_concurrent_identical_writers_leave_one_complete_entry(self):
        context = multiprocessing.get_context("fork")
        barrier, result = context.Barrier(4), context.Queue()
        processes = [context.Process(target=concurrent_writer, args=(str(self.root), barrier, result)) for _ in range(4)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        outcomes = [result.get(timeout=2) for _ in processes]
        self.assertEqual(outcomes.count("published"), 1)
        self.assertTrue(set(outcomes) <= {"published", "busy", "duplicate"})
        self.assertEqual(self.store.lookup(identity(), validate)[0], payload())
        self.assertEqual(len(self.store.inspect()), 1)

    def test_interrupted_population_is_invisible_and_recovered(self):
        process = multiprocessing.get_context("fork").Process(target=interrupted_writer, args=(str(self.root),))
        process.start()
        process.join(10)
        self.assertEqual(process.exitcode, -signal.SIGKILL)
        self.assertTrue(list(self.root.glob(".pending-*")))
        self.assertIsNone(self.store.lookup(identity(), validate)[0])
        self.assertFalse(list(self.root.glob(".pending-*")))
        self.publish()

    def test_busy_store_never_blocks(self):
        with self.store.locked():
            started = time.monotonic()
            with self.assertRaises(cache.Unavailable):
                self.store.lookup(identity(), validate)
            self.assertLess(time.monotonic() - started, 1)

    def test_age_count_capacity_quarantine_eviction_and_deletion(self):
        self.publish()
        os.utime(self.root / "entries" / self.key, (1, 1))
        self.assertEqual(self.store.inspect(), [])
        limited = cache.Store(self.root, max_entries=1)
        self.assertEqual(limited.publish(identity(), payload(), validate), "published")
        changed = identity()
        changed["accession"] = "GCF_999999999.2"
        self.assertEqual(limited.publish(changed, payload(), validate), "published")
        self.assertIsNone(limited.lookup(identity(), validate)[0])
        self.assertEqual(cache.Store(self.root, max_bytes=1).inspect(), [])
        self.assertEqual(cache.Store(self.root, max_bytes=1).publish(identity(), payload(), validate), "capacity")
        self.publish()
        self.assertEqual(self.store.inspect(delete=self.key), [])
        with self.assertRaises(cache.Unavailable):
            self.store.inspect(delete="../escape")

    def test_payload_allowlist_and_privacy(self):
        for name in ("job.json", "pipeline.log", "upload.fna", "report.html", "rankings.csv"):
            value = payload()
            value[name] = b"private"
            with self.assertRaises(cache.Unavailable):
                self.store.publish(identity(), value, validate)
        for private in (b"file://private", b"/data/other/record", b"read_token", b"admin_token", b"api_key", b"password", b"job_id", b"secret"):
            value = payload()
            value["record_map.tsv"] += private
            with self.subTest(private=private), self.assertRaises(cache.Unavailable):
                self.store.publish(identity(), value, validate)

    def test_public_sgd_homepage_reference_preserves_privacy_checks(self):
        for scheme in (b"http", b"https"):
            public = scheme + b"://www.yeastgenome.org/"
            self.assertFalse(adapter.contains_private_context(b"COMMENT Reference " + public + b"\n"))
        for value in (b"http://www.yeastgenome.org/data/jobs/other",
                      b"http://www.yeastgenome.org/?read_token=synthetic",
                      b"http://www.yeastgenome.org.evil.invalid/",
                      b"file://www.yeastgenome.org/",
                      b"read_token=synthetic http://www.yeastgenome.org/",
                      b"http://www.yeastgenome.org/ \n/data/jobs/other",
                      b"http://localhost/internal/result"):
            with self.subTest(value=value):
                self.assertTrue(adapter.contains_private_context(value))

    def test_hit_materialization_is_independent_from_cache_and_other_job(self):
        self.publish()
        first = {name: Path(self.temporary.name) / "one" / name for name in payload()}
        second = {name: Path(self.temporary.name) / "two" / name for name in payload()}
        cache.materialize(self.store.lookup(identity(), validate)[0], first)
        cache.materialize(self.store.lookup(identity(), validate)[0], second)
        first["prepared.gbk"].write_bytes(b"job mutation")
        self.assertEqual(second["prepared.gbk"].read_bytes(), payload()["prepared.gbk"])
        self.assertEqual(self.store.lookup(identity(), validate)[0], payload())
        self.assertNotEqual(first["prepared.gbk"].stat().st_ino, second["prepared.gbk"].stat().st_ino)

    def test_copy_failure_rolls_back_and_symlink_destinations_are_rejected(self):
        paths = {name: Path(self.temporary.name) / "job" / name for name in payload()}
        cache.materialize(payload(), paths)
        original = os.replace
        calls = []
        def fail_second(source, destination):
            calls.append(source)
            if len(calls) == 2:
                raise OSError("synthetic failure")
            return original(source, destination)
        with mock.patch.object(cache.os, "replace", side_effect=fail_second), self.assertRaises(OSError):
            cache.materialize({name: value + b"changed" for name, value in payload().items()}, paths)
        self.assertEqual({name: p.read_bytes() for name, p in paths.items()}, payload())
        paths["prepared.gbk"].unlink()
        paths["prepared.gbk"].symlink_to(paths["record_ids.txt"])
        with self.assertRaises(cache.Unavailable):
            cache.materialize(payload(), paths)
        self.assertFalse(list(paths["record_ids.txt"].parent.glob(".accession-copy-*")))


class PreparationAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / "cache"
        self.store.mkdir(mode=0o700)
        self.input = self.root / "acquired" / "source.fna"
        self.input.parent.mkdir()
        self.input.write_text(">public_record\nATGAAATTT\n")
        self.manifest = self.root / "routes.tsv"
        self.route()
        self.environment = mock.patch.dict(os.environ, {"CLUSTERWEAVE_ACCESSION_CACHE_ROOT": str(self.store),
                                                       "CLUSTERWEAVE_ACCESSION_CACHE_FORCE_MISS": "0", "FORCE": "0"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def route(self, *, source="ncbi", accession="GCF_999999999.1", taxon="bacteria"):
        self.manifest.write_text("input_key\tgenome_id\ttaxon_group\ttaxon_source\tsource_accession\troute_status\n"
                                 f"{accession}\tPublic\t{taxon}\t{source}\t{accession}\taccepted\n")

    def args(self, job="job-a", operation="bacteria"):
        output = self.root / job
        output.mkdir(exist_ok=True)
        return argparse_namespace(operation=operation, input=self.input, output=output / "input.gbk",
                                  record_map=output / "map.tsv", record_ids=output / "ids.txt",
                                  genome_id="Public", min_record_bp=1, max_record_bp=10000,
                                  route_manifest=self.manifest, acquired_root=self.input.parent)

    def test_actual_identity_population_hit_forced_miss_and_equivalence(self):
        args = self.args()
        first = adapter.run(args)
        self.assertEqual(first["population"], "published")
        second_args = self.args("job-b")
        with mock.patch.object(adapter, "compute", side_effect=AssertionError("hit computed")):
            hit = adapter.run(second_args)
        self.assertEqual(hit["outcome"], "hit")
        self.assertEqual(hit["key"], first["key"])
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_ACCESSION_CACHE_FORCE_MISS": "1"}):
            forced_args = self.args("job-c")
            forced = adapter.run(forced_args)
        self.assertEqual(forced["reason"], "forced")
        self.assertEqual(forced["population"], "skipped")
        for name, path in adapter.destinations(args).items():
            self.assertEqual(path.read_bytes(), adapter.destinations(second_args)[name].read_bytes())
            self.assertEqual(path.read_bytes(), adapter.destinations(forced_args)[name].read_bytes())
        encoded = cache.canonical(hit)
        for private in (str(self.root).encode(), b"job-a", b"job-b", b"Public"):
            self.assertNotIn(private, encoded)

    def test_upload_unversioned_missing_and_duplicate_routes_compute_without_cache(self):
        for source, accession in (("genbank_source", "GCF_999999999.1"), ("user_declaration", "GCF_999999999.1"),
                                   ("ncbi", "GCF_999999999"), ("legacy_default", "GCF_999999999.1")):
            self.route(source=source, accession=accession)
            result = adapter.run(self.args())
            self.assertEqual(result["outcome"], "miss")
            self.assertEqual(result["population"], "skipped")
        self.route()
        self.manifest.write_text(self.manifest.read_text() + self.manifest.read_text().splitlines()[-1] + "\n")
        self.assertEqual(adapter.run(self.args())["population"], "skipped")
        self.manifest.unlink()
        self.assertEqual(adapter.run(self.args())["population"], "skipped")
        self.assertFalse((self.store / "entries").exists())

    def test_malformed_route_fields_fall_back_without_population(self):
        malformed = ["wrong_header\nvalue\n", "genome_id\tgenome_id\nPublic\tPublic\n",
                     self.manifest.read_text().replace("\taccepted\n", "\n"),
                     self.manifest.read_text() + "extra\tcolumns\twithout\ta\tvalid\troute\there\n"]
        for value in malformed:
            self.manifest.write_text(value)
            result = adapter.run(self.args())
            self.assertEqual(result["outcome"], "miss")
            self.assertEqual(result["population"], "skipped")

    def test_input_change_and_parameter_change_force_miss(self):
        first = adapter.run(self.args())
        self.input.write_text(">public_record\nATGAAATTTCCC\n")
        second = adapter.run(self.args("job-b"))
        self.assertNotEqual(first["key"], second["key"])
        self.assertEqual(second["outcome"], "miss")
        args = self.args("job-c")
        args.max_record_bp += 1
        third = adapter.run(args)
        self.assertNotEqual(second["key"], third["key"])

    def test_unknown_runtime_unwritable_cache_and_overlap_preserve_computation(self):
        with mock.patch.object(adapter, "runtime_digest", side_effect=cache.Unavailable("unknown")):
            self.assertEqual(adapter.run(self.args())["population"], "skipped")
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_ACCESSION_CACHE_ROOT": str(self.input.parent)}):
            self.assertEqual(adapter.run(self.args())["population"], "skipped")
        self.store.chmod(0o755)
        self.assertEqual(adapter.run(self.args())["population"], "skipped")

    def test_input_change_during_hit_recomputes_without_claiming_a_hit(self):
        adapter.run(self.args())
        original = adapter.materialize
        def change_after_copy(value, destinations):
            original(value, destinations)
            self.input.write_text(">public_record\nATGAAATTTCCC\n")
        args = self.args("job-b")
        with mock.patch.object(adapter, "materialize", side_effect=change_after_copy):
            result = adapter.run(args)
        self.assertEqual(result["outcome"], "miss")
        self.assertIsNone(result["entry_manifest"])
        self.assertEqual(result["population"], "skipped")
        self.assertIn(b"atgaaatttc cc", args.output.read_bytes())

    def test_corruption_falls_back_to_identical_clean_computation(self):
        args = self.args()
        first = adapter.run(args)
        expected = args.output.read_bytes()
        (self.store / "entries" / first["key"] / "prepared.gbk").write_bytes(b"damaged")
        next_args = self.args("job-b")
        result = adapter.run(next_args)
        self.assertEqual(result["outcome"], "miss")
        self.assertEqual(result["reason"], "quarantined")
        self.assertEqual(next_args.output.read_bytes(), expected)
        self.assertEqual(result["population"], "published")

    def test_failed_computation_and_identity_change_never_publish(self):
        self.input.write_text(">bad\ninvalid123\n")
        with self.assertRaises(ValueError):
            adapter.run(self.args())
        self.assertFalse(list((self.store / "entries").iterdir()))
        self.input.write_text(">public\nATGAAA\n")
        original = adapter.compute
        def changed(args):
            original(args)
            self.input.write_text(">public\nATGAAACCC\n")
        with mock.patch.object(adapter, "compute", side_effect=changed):
            self.assertEqual(adapter.run(self.args())["population"], "validation_or_store_failure")
        self.assertFalse(list((self.store / "entries").iterdir()))

    def test_force_bypasses_lookup_and_population_even_when_corrupt(self):
        first = adapter.run(self.args())
        entry = self.store / "entries" / first["key"] / "manifest.json"
        entry.write_text("corrupt")
        with mock.patch.dict(os.environ, {"FORCE": "1"}), mock.patch.object(cache.Store, "lookup", side_effect=AssertionError()):
            result = adapter.run(self.args("job-b"))
        self.assertEqual(result["reason"], "forced")
        self.assertEqual(entry.read_text(), "corrupt")

    def test_fungal_existing_cds_hit_and_downstream_readiness(self):
        try:
            import Bio
        except ImportError:
            self.skipTest("Biopython is required for the existing fungal normalization helper")
        self.route(taxon="fungi")
        self.input.write_text('LOCUS       public_seq                9 bp    DNA     linear   UNK 01-JAN-1980\n'
                              'DEFINITION  Public synthetic record.\nACCESSION   public_seq\nVERSION     public_seq.1\n'
                              'FEATURES             Location/Qualifiers\n     CDS             1..9\n'
                              '                     /translation="MKF"\nORIGIN\n        1 atgaaattt\n//\n')
        first = self.args(operation="fungi")
        result = adapter.run(first)
        self.assertEqual(result["population"], "published")
        second = self.args("job-b", "fungi")
        self.assertEqual(adapter.run(second)["outcome"], "hit")
        self.assertEqual(first.output.read_bytes(), second.output.read_bytes())
        self.assertTrue(adapter.inspect_genbank_translation_stream(io.BytesIO(second.output.read_bytes())).usable_translated_cds)

    def test_cancelled_and_late_cancelled_population_never_promote(self):
        marker = self.root / "cancel.requested"
        marker.write_text("cancel")
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_CANCEL_FILE": str(marker)}):
            with self.assertRaises(InterruptedError):
                adapter.run(self.args())
            marker.unlink()
            original = cache.Store._sync
            def cancel_before_promotion(path):
                original(path)
                if path.name.startswith(".pending-"):
                    marker.write_text("cancel")
            with mock.patch.object(cache.Store, "_sync", side_effect=cancel_before_promotion):
                result = adapter.run(self.args())
            self.assertEqual(result["population"], "cancelled_or_changed")
        self.assertFalse(list((self.store / "entries").iterdir()))
        self.assertFalse(list(self.store.glob(".pending-*")))

    def test_job_credentials_and_environment_do_not_enter_cache_or_provenance(self):
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_JOB_ID": "private-job-value",
                                         "CLUSTERWEAVE_ADMIN_TOKEN": "private-admin-value",
                                         "CLUSTERWEAVE_JOB_TOKEN_SECRET": "private-secret-value"}):
            result = adapter.run(self.args())
        combined = cache.canonical(result) + b"".join(p.read_bytes() for p in
                   (self.store / "entries" / result["key"]).iterdir())
        for value in (b"private-job-value", b"private-admin-value", b"private-secret-value"):
            self.assertNotIn(value, combined)
        from result_policy import is_public_analysis_relative_path
        self.assertFalse(is_public_analysis_relative_path("reproducibility/accession_cache/Public.bacteria.json"))

    def test_operator_settings_cannot_be_overridden_by_a_job(self):
        from canonical_pipeline import _parse_raw_env
        raw = "\n".join(f"CLUSTERWEAVE_ACCESSION_CACHE_{key}=untrusted" for key in
                        ("ROOT", "MAX_BYTES", "MAX_ENTRIES", "MAX_AGE_SECONDS", "FORCE_MISS"))
        self.assertEqual(_parse_raw_env(raw), {})
        self.assertEqual(_parse_raw_env("ordinary_parameter=valid"), {"ordinary_parameter": "valid"})

    def test_custom_helper_keeps_original_arguments(self):
        helper = self.root / "custom sanitizer.py"
        helper.write_text("import json, sys; print(json.dumps(sys.argv[1:]))\n")
        runner = (ROOT / "run_annotation_and_detection.sh").read_text()
        function = "bacterial_genbank_prepare() {" + runner.split("bacterial_genbank_prepare() {", 1)[1].split("\n}", 1)[0] + "\n}\n"
        command = (function + '\nbacterial_genbank_prepare "$1" "$2" ignored ignored ignored '
                   '--input "source with spaces" --output "destination with spaces" --genome-id Public\n')
        result = subprocess.run(["bash", "-c", command, "test", sys.executable, str(helper)],
                                env={**os.environ, "SCRIPT_DIR": str(ROOT)}, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), ["--input", "source with spaces", "--output", "destination with spaces", "--genome-id", "Public"])

    def test_shell_adapter_retains_bytes_and_summary_on_hit(self):
        runner = (ROOT / "run_annotation_and_detection.sh").read_text()
        function = "bacterial_genbank_prepare() {" + runner.split("bacterial_genbank_prepare() {", 1)[1].split("\n}", 1)[0] + "\n}\n"
        outputs = []
        for job in ("one", "two", "forced"):
            args = self.args(job)
            provenance = args.output.parent / "provenance.json"
            command = function + ("\nFORCE=1\n" if job == "forced" else "\n") + 'bacterial_genbank_prepare "$@"\n'
            argv = ["bash", "-c", command, "test", sys.executable, str(ROOT / "bin/sanitize_bacterial_genbank.py"),
                    str(self.manifest), str(self.input.parent), str(provenance),
                    "--input", str(self.input), "--output", str(args.output), "--record-map", str(args.record_map),
                    "--record-ids", str(args.record_ids), "--genome-id", args.genome_id,
                    "--min-record-bp", "1", "--max-record-bp", "10000"]
            completed = subprocess.run(argv, env={**os.environ, "SCRIPT_DIR": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
                                       capture_output=True, text=True, check=True)
            outputs.append(completed.stdout)
            result = json.loads(provenance.read_bytes())
            self.assertEqual(result["outcome"], "hit" if job == "two" else "miss")
            if job == "forced":
                self.assertEqual(result["reason"], "forced")
                self.assertEqual(result["population"], "skipped")
            else:
                self.assertIsNotNone(result["entry_manifest"])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])

    def test_original_sanitizer_and_adapter_downstream_bytes_match(self):
        original = self.args("original")
        adapter.bacterial.sanitize(original.input, original.output, original.record_map, original.record_ids,
                                   original.genome_id, original.min_record_bp, original.max_record_bp)
        changed = self.args("cached")
        adapter.run(changed)
        for name, path in adapter.destinations(original).items():
            self.assertEqual(path.read_bytes(), adapter.destinations(changed)[name].read_bytes())
        before = (self.store / "entries").iterdir()
        self.assertTrue(list(before))


def argparse_namespace(**kwargs):
    import argparse
    return argparse.Namespace(**kwargs)


if __name__ == "__main__":
    unittest.main()
