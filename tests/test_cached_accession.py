from __future__ import annotations

import argparse
import copy
from contextlib import redirect_stdout
import importlib.util
import io
import json
import multiprocessing
import os
import subprocess
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import accession_cache as cache
import cached_accession as adapter
from sanitize_bacterial_genbank import format_record


def identity(snapshot=False):
    containers = {}
    return {"schema": 1, "contract": adapter.CONTRACT_SNAPSHOT if snapshot else adapter.CONTRACT_DETECTION,
            "accession": "GCF_999999999.1", "genome_sha256": "1" * 64,
            "route": {"taxon": "bacteria", "annotation": "retrieval" if snapshot else "per-genome"},
            "source_sha256": "2" * 64, "runtime_sha256": "3" * 64,
            "tools": {"datasets": "4" * 64, "unzip": "8" * 64} if snapshot else {"pipeline": "2" * 64, "native": "3" * 64},
            "containers": "not-used",
            "databases": "not-used" if snapshot else {"antismash": "5" * 64},
            "models": "not-used" if snapshot else {"embedded": cache.sha256(cache.canonical({"native": "3" * 64, "images": containers}))},
            "parameters": {"configuration_sha256": "6" * 64, "genome_label_sha256": cache.sha256(b"Public"),
                           **({} if snapshot else {"partition_sha256": adapter.PARTITION_SHA256})}}


def detection_files():
    return {"input_gbks/Public.gbk": format_record("seq", "ATGAAA", "linear").encode(),
            "antismash/Public/index.html": b"public report",
            "antismash/Public/regions.js": b"var regions = [];",
            "antismash/Public/Public.gbk": format_record("seq", "ATGAAA", "linear").encode(),
            "summary_tables/bacterial_record_maps/Public.record_map.tsv": b"record map\n",
            "execution.json": cache.canonical({"worker_image": "9" * 64, "native_runtime_sha256": "3" * 64, "producer_source_sha256": "2" * 64,
                                                "scheduling": {"CPUS": "2"}}),
            "outcome.json": cache.canonical({"gbk_status": "bacterial_sequence_sanitized", "prediction_method": "prodigal",
                "antismash_status": "ran_ok", "funbgcex_status": "not_applicable_taxon", "taxon_group": "bacteria",
                "detector_profile": "antismash", "funbgcex_applicability": "not_applicable_taxon"})}


def claim_probe(root, output):
    with adapter.claim(cache.Store(Path(root)), "a" * 64):
        output.put("acquired")


class BundleSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_complete_identity_changes_for_each_dependency_and_parameter(self):
        original = identity()
        key = cache.identity_key(original)
        for field in ("genome_sha256", "source_sha256", "runtime_sha256"):
            value = copy.deepcopy(original)
            value[field] = "a" * 64
            if field == "source_sha256":
                value["tools"]["pipeline"] = value[field]
            if field == "runtime_sha256":
                value["tools"]["native"] = value[field]
                value["models"]["embedded"] = cache.sha256(cache.canonical({"native": value[field], "images": {}}))
            self.assertNotEqual(cache.identity_key(value), key)
        for section in ("databases", "parameters"):
            for name in original[section]:
                value = copy.deepcopy(original)
                value[section][name] = "a" * 64
                self.assertNotEqual(cache.identity_key(value), key)
        for section in ("tools", "containers", "databases", "models", "parameters"):
            value = copy.deepcopy(original)
            value[section] = {}
            with self.assertRaises(cache.Unavailable):
                cache.identity_key(value)

    def test_external_native_executables_and_python_modules_force_misses(self):
        directory = self.root / "custom_runtime"
        directory.mkdir()
        # The clean baseline must not inherit host Python, loader or shell overrides.
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:" + str(directory)}, clear=True):
            adapter.native_runtime_supported()
            (directory / "datasets").write_bytes(b"prepared retrieval only")
            (directory / "datasets").chmod(0o700)
            adapter.native_runtime_supported()
            (directory / "prodigal").write_bytes(b"unidentified native tool")
            (directory / "prodigal").chmod(0o700)
            with self.assertRaisesRegex(cache.Unavailable, "external_native_runtime"):
                adapter.native_runtime_supported()
        for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE", "LD_PRELOAD", "LD_LIBRARY_PATH", "BASH_ENV"):
            with self.subTest(variable=name), mock.patch.dict(os.environ, {name: str(directory)}, clear=True):
                with self.assertRaisesRegex(cache.Unavailable, "external_native_runtime"):
                    adapter.native_runtime_supported()

    def test_bundle_canonical_order_and_metadata(self):
        files = {"b/file.txt": b"second", "a.txt": b"first", "empty.txt": b""}
        data = adapter.pack(files)
        self.assertEqual(data, adapter.pack(dict(reversed(list(files.items())))))
        self.assertEqual(adapter.unpack(data), files)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            self.assertTrue(all(m.uid == m.gid == m.mtime == 0 and m.mode == 0o600 for m in archive))

    def test_native_fingerprint_tracks_bytes_and_modes_without_using_timestamps(self):
        native = self.root / "runtime"
        native.mkdir()
        tool = native / "tool"
        tool.write_bytes(b"pinned native program")
        tool.chmod(0o700)
        with mock.patch.object(adapter, "NATIVE_ROOTS", (native,)):
            original = adapter.native_digest(content=True)
            stamp = adapter.native_digest()
            os.utime(tool, (100, 100))
            self.assertEqual(adapter.native_digest(content=True), original)
            self.assertNotEqual(adapter.native_digest(), stamp)
            tool.write_bytes(b"different native program")
            self.assertNotEqual(adapter.native_digest(content=True), original)
            previous = adapter.native_digest(content=True)
            tool.chmod(0o600)
            self.assertNotEqual(adapter.native_digest(content=True), previous)

    def test_original_snapshot_identity_remains_readable_for_verified_preservation(self):
        original = identity(True)
        original["contract"] = "accession-snapshot-v1"
        original["tools"] = {"datasets": "4" * 64}
        self.assertEqual(len(cache.identity_key(original)), 64)
        malformed = copy.deepcopy(original)
        malformed["tools"]["unverified"] = "unknown"
        with self.assertRaises(cache.Unavailable):
            cache.identity_key(malformed)

    def test_original_detection_identity_does_not_alias_current_contract(self):
        original = identity()
        original["contract"] = "accession-detection-v1"
        original["parameters"].pop("partition_sha256")
        original["tools"] = {"pipeline": "2" * 64}
        original["containers"] = {"worker": "3" * 64}
        original["models"] = {"embedded": cache.sha256(cache.canonical(original["containers"]))}
        self.assertNotEqual(cache.identity_key(original), cache.identity_key(identity()))

    @unittest.skipUnless(importlib.util.find_spec("Bio"), "Biopython is required")
    def test_v2_remains_readable_without_aliasing_scheduling_independent_contract(self):
        original = identity()
        original["contract"] = "accession-detection-v2"
        original["parameters"].pop("partition_sha256")
        files = detection_files()
        execution = json.loads(files["execution.json"])
        execution.pop("scheduling")
        files["execution.json"] = cache.canonical(execution)
        adapter.validate_bundle({"bundle.tar": adapter.pack(files)}, original)
        self.assertNotEqual(cache.identity_key(original), cache.identity_key(identity()))
        with self.assertRaisesRegex(cache.Unavailable, "execution_provenance"):
            adapter.validate_bundle({"bundle.tar": adapter.pack(files)}, identity())

    @unittest.skipUnless(importlib.util.find_spec("Bio"), "Biopython is required")
    def test_resource_provenance_rejects_unknown_fields_and_private_values(self):
        for allocation in ({"CPUS": "/data/jobs/private"}, {"CPUS": "2", "token": "secret"}):
            files = detection_files()
            execution = json.loads(files["execution.json"])
            execution["scheduling"] = allocation
            files["execution.json"] = cache.canonical(execution)
            with self.assertRaises(cache.Unavailable):
                adapter.validate_bundle({"bundle.tar": adapter.pack(files)}, identity())

    @unittest.skipUnless(importlib.util.find_spec("Bio"), "Biopython is required")
    def test_optional_producer_versions_preserve_keys_and_reject_private_fields(self):
        from tool_runtime import safe_observation
        original = identity(); key = cache.identity_key(original)
        files = detection_files(); execution = json.loads(files["execution.json"])
        version = safe_observation({"tool": "Prodigal", "backend": "native", "version": "2.6.3", "executable_sha256": "a" * 64})
        execution["tool_versions"] = [version]; files["execution.json"] = cache.canonical(execution)
        adapter.validate_bundle({"bundle.tar": adapter.pack(files)}, original)
        self.assertEqual(key, cache.identity_key(original))
        execution["tool_versions"][0]["private_path"] = "/private/job"
        files["execution.json"] = cache.canonical(execution)
        with self.assertRaisesRegex(cache.Unavailable, "execution_provenance"):
            adapter.validate_bundle({"bundle.tar": adapter.pack(files)}, original)

    def test_producer_observations_require_the_executed_image_and_actual_tool(self):
        from tool_runtime import safe_observation
        path = self.root / "observations.json"
        native = safe_observation({"tool": "Prodigal", "backend": "native", "version": "2.6.3", "executable_sha256": "a" * 64})
        wrong = safe_observation({"tool": "FunBGCeX", "backend": "docker", "version": "1.0.1", "runtime_sha256": "b" * 64})
        path.write_text(json.dumps([native, wrong]))
        outcome = json.loads(detection_files()["outcome.json"])
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_ANNOTATION_OBSERVATIONS": str(path)}):
            self.assertEqual(adapter.producer_tool_versions(identity(), outcome), [native])
            fungal = identity(); fungal["containers"] = {"funbgcex": "c" * 64}
            outcome["taxon_group"] = "fungi"
            self.assertEqual(adapter.producer_tool_versions(fungal, outcome), [])
            fungal["containers"]["funbgcex"] = "b" * 64
            self.assertEqual(adapter.producer_tool_versions(fungal, outcome), [wrong])

    def test_annotation_dependency_versions_are_optional_metadata_with_stable_keys(self):
        from tool_runtime import safe_observation
        ident = identity(); ident["containers"] = {"funannotate": "f" * 64}
        before = cache.canonical(ident)
        path = self.root / "observations.json"
        parent = safe_observation({"tool": "funannotate", "backend": "docker", "version": "1.8.17", "runtime_sha256": "f" * 64})
        path.write_text(json.dumps([parent]))
        outcome = {"taxon_group": "fungi", "gbk_status": "funannotate_fixed"}
        args = argparse.Namespace(results=self.root, genome_id="Public")
        log = self.root / "logs/Public.funannotate.log"; log.parent.mkdir()
        log.write_text("[01/01/26 10:00:00]: /opt/bin/augustus --species=fixture sequence.fa\n")
        dependency = safe_observation({"tool": "AUGUSTUS", "backend": "docker", "version": "3.5.0", "runtime_sha256": "f" * 64})
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_ANNOTATION_OBSERVATIONS": str(path), "WORK_ROOT": str(self.root)}), mock.patch("tool_runtime.observe", return_value=dependency) as probe:
            self.assertEqual(adapter.producer_tool_versions(ident, outcome, args), [parent, dependency])
            self.assertEqual(probe.call_args.args, ("AUGUSTUS", "docker", "f" * 64))
            outcome["gbk_status"] = "existing_cds"
            probe.reset_mock()
            self.assertEqual(adapter.producer_tool_versions(ident, outcome, args), [])
            probe.assert_not_called()
        self.assertEqual(cache.canonical(ident), before)

    def test_snapshot_pins_a_packaged_hardlinked_unzip_binary(self):
        route = self.root / "route.tsv"
        route.write_text("genome_id\tinput_key\tsource_accession\ttaxon_source\ttaxon_group\troute_status\n"
                         "Public\tGCF_999999999.1\tGCF_999999999.1\tncbi\tbacteria\trouted\n")
        binary = self.root / "datasets"
        binary.write_bytes(b"pinned retrieval executable")
        unzip = self.root / "unzip"
        unzip.write_bytes(b"packaged native executable")
        os.link(unzip, self.root / "zipinfo")
        args = argparse.Namespace(accession="GCF_999999999.1", genome_id="Public", taxon="bacteria",
                                  route_manifest=route, datasets=str(binary))
        with mock.patch.object(adapter, "runtime_digest", return_value="3" * 64), mock.patch.object(adapter.shutil, "which", side_effect=lambda n: str(unzip) if n == "unzip" else None):
            value = adapter.snapshot_identity(args)
        self.assertEqual(value["tools"]["unzip"], cache.sha256(unzip.read_bytes()))
        self.assertEqual(len(cache.identity_key(value)), 64)

    def test_native_fingerprint_allows_packaged_links_and_ignores_derived_bytecode(self):
        native = self.root / "runtime"
        native.mkdir()
        (native / "module.py").write_bytes(b"known source")
        os.link(native / "module.py", native / "same-source")
        (native / "source-link").symlink_to("module.py")
        with mock.patch.object(adapter, "NATIVE_ROOTS", (native,)):
            original = adapter.native_digest(content=True)
            derived = native / "__pycache__"
            derived.mkdir()
            (derived / "module.cpython-311.pyc").write_bytes(b"derived cache")
            self.assertEqual(adapter.native_digest(content=True), original)
            (derived / "unknown.cpython-311.pyc").write_bytes(b"unidentified executable")
            with self.assertRaisesRegex(cache.Unavailable, "native_bytecode_without_source"):
                adapter.native_digest(content=True)

    def test_cache_implementation_changes_do_not_change_scientific_producer_identity(self):
        source = self.root / "source"
        (source / "bin").mkdir(parents=True)
        (source / "scripts").mkdir()
        for name in ("accession_cache.py", "cached_accession.py", "sanitize_bacterial_genbank.py",
                     "annotation_genbank.py", "annotation_runtime.py", "annotation_input.py", "prepare_antismash_input.py",
                     "compact_antismash_shard.py", "prepare_antismash_web_results.py", "gff3_to_gbk_with_translations.py", "cached_genbank.py"):
            (source / "bin" / name).write_text("original\n")
        (source / "web").mkdir()
        (source / "web/resource_policy.py").write_text("original policy\n")
        (source / "run_annotation_and_detection.sh").write_text("scientific runner\n")
        with mock.patch.object(adapter, "ROOT", source):
            original = adapter.source_digest()
            (source / "bin/accession_cache.py").write_text("new cache storage\n")
            (source / "bin/cached_accession.py").write_text("new cache validation\n")
            self.assertEqual(adapter.source_digest(), original)
            (source / "bin/sanitize_bacterial_genbank.py").write_text("different scientific algorithm\n")
            self.assertNotEqual(adapter.source_digest(), original)

    def test_archive_traversal_links_duplicates_and_bombs_rejected(self):
        for name, kind in [("../escape", "file"), ("/absolute", "file"), ("a/./b", "file"),
                           ("a\\b", "file"), ("link", "symlink"), ("hard", "hardlink"), ("repeat", "duplicate"), ("big", "big")]:
            with self.subTest(name=name):
                raw = io.BytesIO()
                with tarfile.open(fileobj=raw, mode="w:gz") as archive:
                    info = tarfile.TarInfo(name)
                    if kind == "symlink": info.type = tarfile.SYMTYPE
                    if kind == "hardlink": info.type = tarfile.LNKTYPE
                    info.size = 1 if kind == "big" else 0
                    archive.addfile(info, io.BytesIO(b"x"))
                    if kind == "duplicate": archive.addfile(info)
                with mock.patch.object(adapter, "MAX_FILE_BYTES", 0 if kind == "big" else 1024):
                    with self.assertRaises(cache.Unavailable): adapter.unpack(raw.getvalue())

    def test_install_failure_rolls_back_and_never_follows_links(self):
        target = self.root / "job"
        target.mkdir()
        original = os.replace
        count = 0
        def fail_second(source, dest):
            nonlocal count
            count += 1
            if count == 2: raise OSError("copy failure")
            return original(source, dest)
        with mock.patch.object(adapter.os, "replace", side_effect=fail_second):
            with self.assertRaises(OSError): adapter.install({"a": b"one", "b": b"two"}, target)
        self.assertFalse((target / "a").exists())
        (target / "link").symlink_to(self.root)
        with self.assertRaises(cache.Unavailable): adapter.install({"link/a": b"private"}, target)
        self.assertFalse((self.root / "a").exists())

    def test_volume_names_and_root_paths_do_not_affect_content_digest(self):
        for name in ("volume_one", "volume_two"):
            root = self.root / name
            root.mkdir()
            (root / "model").write_bytes(b"exact database bytes")
        self.assertEqual(adapter.content_tree(self.root / "volume_one"), adapter.content_tree(self.root / "volume_two"))
        (self.root / "volume_two/model").write_bytes(b"changed database bytes")
        self.assertNotEqual(adapter.content_tree(self.root / "volume_one"), adapter.content_tree(self.root / "volume_two"))

    def test_claim_serializes_processes_and_releases_after_exit(self):
        root = self.root / "store"
        root.mkdir(mode=0o700)
        ctx = multiprocessing.get_context("spawn")
        output = ctx.Queue()
        self.addCleanup(output.close)
        with adapter.claim(cache.Store(root), "a" * 64):
            process = ctx.Process(target=claim_probe, args=(str(root), output))
            process.start()
            self.addCleanup(lambda: process.terminate() if process.is_alive() else None)
            with self.assertRaises(Exception): output.get(timeout=0.2)
        self.assertEqual(output.get(timeout=5), "acquired")
        process.join(5)
        self.assertEqual(process.exitcode, 0)
        for n in range(600): adapter.claim_path(cache.Store(root), cache.sha256(str(n).encode()))
        self.assertLessEqual(len(list((root / "claims").iterdir())), 256)

    def test_forced_prepare_and_preexisting_job_outputs_cannot_populate(self):
        args = argparse.Namespace(results=self.root, genome_id="Public")
        with mock.patch.dict(os.environ, {"FORCE": "1"}):
            with self.assertRaisesRegex(cache.Unavailable, "forced"): adapter.prepare(args)
        path = self.root / "input_gbks/Public.gbk"
        path.parent.mkdir()
        path.write_bytes(b"manually modified")
        with self.assertRaisesRegex(cache.Unavailable, "existing_job_output"): adapter.prepare(args)

    def test_cache_wrapper_preserves_parallel_computation_failure(self):
        text = (ROOT / "run_annotation_and_detection.sh").read_text()
        wrapper = "process_genome() (" + text.split("process_genome() (", 1)[1].split("\n)\n\nidx=0", 1)[0] + "\n)\n"
        marker = self.root / "must_not_run"
        script = '''set -euo pipefail
route_taxon_for_genome() { echo bacteria; }
route_root_for_genome() { echo /unused; }
mapping_file_for_taxon() { echo /unused; }
resolve_python_cmd() { echo python3; }
compute_genome() { echo started > "$MARKER"; false; echo incorrect >> "$MARKER"; }
''' + wrapper + '\nprocess_genome Public 1 /unused 1 &\nwait "$!"\n'
        env = dict(os.environ, WORK_ROOT=str(self.root), RESULTS_ROOT=str(self.root), SCRIPT_DIR=str(ROOT),
                   ACCESSION_CONTEXT=str(self.root / "missing"), CLUSTERWEAVE_ACCESSION_CACHE_ROOT="", MARKER=str(marker),
                   GENOME_TAXON_MANIFEST="/unused")
        result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_text(), "started\n")


@unittest.skipUnless(importlib.util.find_spec("Bio"), "worker supplies Biopython")
class ScientificBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store_root = self.root / "cache"
        self.store_root.mkdir(mode=0o700)
        self.store = cache.Store(self.store_root)
        self.ident = identity()
        self.validate = lambda p: adapter.validate_bundle(p, self.ident)

    def test_full_bundle_hit_independent_files_and_normal_scientific_bytes(self):
        files = detection_files()
        payload = {"bundle.tar": adapter.pack(files)}
        self.assertEqual(self.store.publish(self.ident, payload, self.validate), "published")
        found, reason, _ = self.store.lookup(self.ident, self.validate)
        self.assertEqual(reason, "verified")
        for name in ("job_one", "job_two"):
            adapter.install(adapter.validate_bundle(found, self.ident), self.root / name)
        for name, data in files.items():
            if name in {"outcome.json", "execution.json"}: continue
            a, b = (self.root / job / name for job in ("job_one", "job_two"))
            self.assertEqual(a.read_bytes(), data)
            self.assertEqual(b.read_bytes(), data)
            self.assertNotEqual(a.stat().st_ino, b.stat().st_ino)
        (self.root / "job_one/input_gbks/Public.gbk").write_bytes(b"changed")
        self.assertEqual(self.store.lookup(self.ident, self.validate)[0], payload)

    def test_private_context_partial_failure_other_accessions_rejected(self):
        for change in ("private", "failed", "incomplete", "foreign", "resume"):
            files = detection_files()
            if change == "private": files["antismash/Public/index.html"] = b"/data/jobs/private/path"
            if change == "failed":
                row = json.loads(files["outcome.json"]); row["antismash_status"] = "failed"; files["outcome.json"] = cache.canonical(row)
            if change == "incomplete": del files["antismash/Public/regions.js"]
            if change == "foreign": files["antismash/Other/index.html"] = b"another accession"
            if change == "resume":
                row = json.loads(files["outcome.json"]); row["gbk_status"] = "staged_ok"; files["outcome.json"] = cache.canonical(row)
            with self.subTest(change=change), self.assertRaises(cache.Unavailable):
                self.validate({"bundle.tar": adapter.pack(files)})

    def test_corruption_quarantines_and_allows_normal_population(self):
        payload = {"bundle.tar": adapter.pack(detection_files())}
        self.store.publish(self.ident, payload, self.validate)
        (self.store_root / "entries" / cache.identity_key(self.ident) / "bundle.tar").write_bytes(b"interrupted")
        self.assertEqual(self.store.lookup(self.ident, self.validate)[1], "quarantined")
        self.assertEqual(self.store.publish(self.ident, payload, self.validate), "published")

    def test_relocation_rebuilds_paths_without_copying_old_job_context(self):
        args = argparse.Namespace(results=Path("/data/jobs/old/results"), work=Path("/data/jobs/old/work"), acquired_root=Path("/data/jobs/old/genomes"))
        neutral = adapter.portable(b"/data/jobs/old/results/report", adapter.replacements(args))
        self.assertNotIn(b"/data/jobs/old", neutral)
        args.results = Path("/different/volume/new/results")
        restored = adapter.portable(neutral, adapter.replacements(args), restore=True)
        self.assertEqual(restored, b"/different/volume/new/results/report")

    def test_normalized_shard_paths_validate_and_restore_without_masking_private_paths(self):
        args = argparse.Namespace(results=Path("/data/jobs/old/results"), work=Path("/data/jobs/old/work"), acquired_root=Path("/data/jobs/old/genomes"))
        files = detection_files()
        name = "antismash/Public/shard_manifest.tsv"
        raw = b"shard\t/data/jobs/old/work/tmp/Public/antismash_shards/000001_seq\n"
        files[name] = adapter.portable(raw, adapter.replacements(args))
        self.assertIn(b"__CW_WORK__/tmp/", files[name])
        self.validate({"bundle.tar": adapter.pack(files)})
        args.work = Path("/different/volume/new/work")
        restored = adapter.portable(files[name], adapter.replacements(args), restore=True)
        self.assertEqual(restored, raw.replace(b"/data/jobs/old/work", b"/different/volume/new/work"))
        for private in (b"/tmp/private/file", b"file://__CW_WORK__/tmp/file",
                        b"__CW_WORK__/tmp/../private", b"__CW_WORK__/tmp/file\t/home/private/file",
                        b"__CW_WORK__/tmp/private_job_123/file"):
            with self.subTest(private=private), mock.patch.dict(os.environ, {"CLUSTERWEAVE_JOB_ID": "private_job_123"}):
                files[name] = private
                with self.assertRaisesRegex(cache.Unavailable, "bundle_private_context"):
                    self.validate({"bundle.tar": adapter.pack(files)})
        with self.assertRaisesRegex(cache.Unavailable, "reserved_path_marker"):
            adapter.portable(b"__CW_WORK__/tmp/file", adapter.replacements(args))

    def test_population_rejection_retains_requested_identity_without_claiming_a_hit(self):
        state = self.root / "state.json"
        state.write_bytes(cache.canonical({"identity": self.ident}))
        report = self.root / "rejected.json"
        argv = ["cached_accession.py", "publish", "--state", str(state), "--provenance", str(report)]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(adapter, "detection", side_effect=cache.Unavailable("bundle_private_context")):
            self.assertEqual(adapter.main(), 1)
        value = json.loads(report.read_bytes())
        self.assertEqual(value["identity"], self.ident)
        self.assertEqual(value["key"], cache.identity_key(self.ident))
        self.assertEqual(value["outcome"], "miss")
        self.assertEqual(value["population"], "rejected")
        self.assertIsNone(value.get("manifest_sha256"))

    def test_public_library_uuid_is_allowed_and_actual_job_context_is_rejected(self):
        files = detection_files()
        public_id = "00000000-0000-4000-8000-000000000001"
        files["antismash/Public/js/jquery.js"] = public_id.encode()
        self.validate({"bundle.tar": adapter.pack(files)})
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_JOB_ID": public_id}):
            with self.assertRaisesRegex(cache.Unavailable, "bundle_private_context"):
                self.validate({"bundle.tar": adapter.pack(files)})
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_JOB_ID": "private_job_123"}):
            files["antismash/Public/index.html"] = b"private_job_123"
            with self.assertRaisesRegex(cache.Unavailable, "bundle_private_context"):
                self.validate({"bundle.tar": adapter.pack(files)})

    def test_snapshot_requires_exact_public_accession_and_never_contains_job_files(self):
        ident = identity(True)
        files = {"ncbi_dataset/data/GCF_999999999.1/genomic.fna": b">seq\nATGAAA\n",
                 "ncbi_dataset/data/assembly_data_report.jsonl": b'{"accession":"GCF_999999999.1"}\n'}
        adapter.validate_bundle({"bundle.tar": adapter.pack(files)}, ident)
        files["job.json"] = b"private"
        with self.assertRaises(cache.Unavailable): adapter.validate_bundle({"bundle.tar": adapter.pack(files)}, ident)
        del files["job.json"]
        ident["accession"] = "GCF_999999999.2"
        with self.assertRaises(cache.Unavailable): adapter.validate_bundle({"bundle.tar": adapter.pack(files)}, ident)

    def test_retrieval_hit_skips_downloader_and_force_preserves_existing_snapshot(self):
        ident = identity(True)
        count = self.root / "downloads"
        program = '''import pathlib,sys
p=pathlib.Path(sys.argv[1]); p.mkdir(parents=True,exist_ok=True)
(p/'genomic.fna').write_text('>seq\\nATGAAA\\n')
(p/'assembly_data_report.jsonl').write_text('{"accession":"GCF_999999999.1"}\\n')
q=pathlib.Path(sys.argv[2]);q.write_text(q.read_text()+'x' if q.exists() else 'x')
'''
        args = argparse.Namespace(provenance=self.root / "provenance.json", destination=self.root / "job_one")
        args.command = [sys.executable, "-c", program, str(args.destination / "ncbi_dataset/data"), str(count)]
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_ACCESSION_CACHE_ROOT": str(self.store_root)}), mock.patch.object(adapter, "snapshot_identity", return_value=ident):
            self.assertEqual(adapter.retrieve(args), 0)
            self.assertEqual(json.loads(args.provenance.read_bytes())["population"], "published")
            args.destination = self.root / "job_two"
            args.command = [sys.executable, "-c", "raise SystemExit(7)"]
            emitted = io.StringIO()
            with redirect_stdout(emitted):
                self.assertEqual(adapter.retrieve(args), 0)
            self.assertEqual(emitted.getvalue(), "ACCESSION_CACHE genome=GCF_999999999.1 stage=retrieval outcome=hit\n")
            self.assertEqual(json.loads(args.provenance.read_bytes())["outcome"], "hit")
            self.assertEqual(count.read_text(), "x")
            with mock.patch.dict(os.environ, {"FORCE": "1"}):
                args.command = [sys.executable, "-c", program, str(args.destination / "ncbi_dataset/data"), str(count)]
                self.assertEqual(adapter.retrieve(args), 0)
            self.assertEqual(count.read_text(), "xx")
            self.assertEqual(json.loads(args.provenance.read_bytes())["reason"], "forced")

    def test_scientific_identity_is_accession_local_across_volume_locations(self):
        identities = []
        for name in ("volume_a", "volume_b"):
            volume = self.root / name
            volume.mkdir()
            acquired = volume / "genomes"
            acquired.mkdir()
            (acquired / "Public.fna").write_bytes(b">seq\nATGAAA\n")
            db = volume / "database"
            db.mkdir()
            (db / "model").write_bytes(b"pinned model")
            route = volume / "routes.tsv"
            route.write_text("genome_id\tinput_key\tsource_accession\ttaxon_source\ttaxon_group\troute_status\tinput_path_key\n"
                             "Public\tGCF_999999999.1\tGCF_999999999.1\tncbi\tbacteria\trouted\t" + name + "\n")
            args = argparse.Namespace(genome_id="Public", acquired_root=acquired, route_manifest=route, taxon="bacteria", mapping=volume / "missing")
            mixed = name == "volume_b"
            ctx = {"source": "2" * 64, "images": {"funbgcex": "a" * 64} if mixed else {}, "native_runtime": "3" * 64, "native_stamp": "7" * 64,
                   "worker_image": ("9" if mixed else "8") * 64, "database": adapter.content_tree(db),
                   "database_stamp": adapter.tree_stamp(db), "settings": {"ANTISMASH_DB_DIR": str(db), "CPUS": "2",
                       "HAS_FUNGAL_ROUTES": "1" if mixed else "0", "FUNBGCEX_RUNTIME": "docker" if mixed else "unresolved",
                       "WORKERS": "2" if mixed else "1", "ANNO_CPUS": "4" if mixed else "2"}}
            with mock.patch.object(adapter, "source_digest", return_value="2" * 64), mock.patch.object(adapter, "native_digest", return_value="7" * 64):
                identities.append(adapter.detection_identity(args, ctx))
        self.assertEqual(identities[0], identities[1])
        self.assertEqual(cache.identity_key(identities[0]), cache.identity_key(identities[1]))

    def scheduling_case(self, taxon="bacteria"):
        base = self.root / taxon
        acquired = base / "acquired"; acquired.mkdir(parents=True)
        (acquired / "Public.fna").write_text(">seq\nATGAAA\n")
        database = base / "database"; database.mkdir()
        (database / "model").write_text("pinned model")
        route = base / "routes.tsv"
        route.write_text("genome_id\tinput_key\tsource_accession\ttaxon_source\ttaxon_group\troute_status\n"
                         f"Public\tGCF_999999999.1\tGCF_999999999.1\tncbi\t{taxon}\trouted\n")
        args = argparse.Namespace(genome_id="Public", acquired_root=acquired, route_manifest=route,
            taxon=taxon, mapping=base / "missing", results=base / "results", work=base / "work",
            context=base / "context.json", state=base / "state.json", row=base / "row.tsv",
            provenance=base / "provenance.json", action="restore")
        args.results.mkdir(); args.work.mkdir()
        settings = {"ANTISMASH_DB_DIR": str(database), "CPUS": "2", "THREADS": "2",
            "GENOME_PARALLELISM": "1", "ANTISMASH_RECORD_PARALLELISM": "1",
            "ANTISMASH_SHARD_CPUS": "1", "ANTISMASH_LEGACY_CPUS": "2",
            "CLUSTERWEAVE_TOOL_DOCKER_CPUS": "2", "CLUSTERWEAVE_TOOL_DOCKER_MEMORY": "4g",
            "CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT": "512", "ANTISMASH_MIN_RECORD_BP": "1000",
            "WORKERS": "2", "ANNO_CPUS": "4", "PYTHONHASHSEED": "0"}
        images = {"funbgcex": "a" * 64, "funannotate": "b" * 64} if taxon == "fungi" else {}
        ctx = {"source": "2" * 64, "native_runtime": "3" * 64, "native_stamp": "7" * 64,
            "worker_image": "9" * 64, "images": images, "database": adapter.content_tree(database),
            "database_stamp": adapter.tree_stamp(database), "settings": settings}
        return args, ctx

    def test_scheduling_changes_reuse_but_scientific_and_unvalidated_tool_settings_do_not(self):
        for taxon in ("bacteria", "fungi"):
            args, ctx = self.scheduling_case(taxon)
            with mock.patch.object(adapter, "source_digest", return_value=ctx["source"]), \
                    mock.patch.object(adapter, "native_digest", return_value=ctx["native_stamp"]):
                original = adapter.detection_identity(args, ctx)
                for key, value in {"CPUS": "12", "THREADS": "12", "GENOME_PARALLELISM": "3",
                        "ANTISMASH_RECORD_PARALLELISM": "3", "ANTISMASH_SHARD_CPUS": "4",
                        "ANTISMASH_LEGACY_CPUS": "12", "CLUSTERWEAVE_TOOL_DOCKER_CPUS": "12",
                        "CLUSTERWEAVE_TOOL_DOCKER_MEMORY": "32g", "CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT": "4096",
                        "WORKERS": "4"}.items():
                    changed = copy.deepcopy(ctx); changed["settings"][key] = value
                    self.assertEqual(adapter.detection_identity(args, changed), original, (taxon, key))
                for key, value in {"ANTISMASH_MIN_RECORD_BP": "2000", "PYTHONHASHSEED": "1",
                        **({"ANNO_CPUS": "8"} if taxon == "fungi" else {})}.items():
                    changed = copy.deepcopy(ctx); changed["settings"][key] = value
                    self.assertNotEqual(adapter.detection_identity(args, changed), original, (taxon, key))
                with mock.patch.object(adapter, "PARTITION_SHA256", "c" * 64):
                    self.assertNotEqual(adapter.detection_identity(args, ctx), original)

    def test_cross_allocation_hit_keeps_producer_resources_and_materializes_independent_files(self):
        args, ctx = self.scheduling_case()
        store = self.store
        with mock.patch.object(adapter, "source_digest", return_value=ctx["source"]), \
                mock.patch.object(adapter, "native_digest", return_value=ctx["native_stamp"]), \
                mock.patch.object(adapter, "store", return_value=store):
            original = adapter.detection_identity(args, ctx)
            payload = {"bundle.tar": adapter.pack(detection_files())}
            self.assertEqual(store.publish(original, payload, lambda p: adapter.validate_bundle(p, original)), "published")
            ctx["settings"].update({"CPUS": "12", "THREADS": "12", "ANTISMASH_RECORD_PARALLELISM": "3"})
            adapter.write_json(args.context, ctx)
            adapter.prepare(args)
            self.assertEqual(adapter.detection(args), 0)
            record = json.loads(args.provenance.read_bytes())
            self.assertEqual(record["outcome"], "hit")
            self.assertEqual(record["producer_execution"]["scheduling"], {"CPUS": "2"})
            self.assertEqual(record["materializer_scheduling"]["CPUS"], "12")
            materialized = args.results / "input_gbks/Public.gbk"
            self.assertEqual(materialized.read_bytes(), detection_files()["input_gbks/Public.gbk"])
            self.assertEqual(materialized.stat().st_nlink, 1)
            self.assertEqual(store.lookup(original, lambda p: adapter.validate_bundle(p, original))[0], payload)

    def test_existing_fungal_annotations_ignore_an_unused_annotation_cpu_budget(self):
        from Bio import SeqIO
        from Bio.Seq import Seq
        from Bio.SeqFeature import SeqFeature, FeatureLocation
        from Bio.SeqRecord import SeqRecord
        args, ctx = self.scheduling_case("fungi")
        (args.acquired_root / "Public.fna").write_text(">seq\nATGAAATAG\n")
        record = SeqRecord(Seq("ATGAAATAG"), id="seq", description="public")
        record.annotations["molecule_type"] = "DNA"
        record.features = [SeqFeature(FeatureLocation(0, 9), type="CDS", qualifiers={"translation": ["MK"]})]
        SeqIO.write([record], args.acquired_root / "Public.gbk", "genbank")
        with mock.patch.object(adapter, "source_digest", return_value=ctx["source"]), \
                mock.patch.object(adapter, "native_digest", return_value=ctx["native_stamp"]):
            original = adapter.detection_identity(args, ctx)
            ctx["settings"]["ANNO_CPUS"] = "8"
            self.assertEqual(adapter.detection_identity(args, ctx), original)
            self.assertEqual(adapter.scheduling_record(ctx["settings"])["ANNO_CPUS"], "8")

    def test_fungal_annotation_and_both_detectors_require_complete_translations(self):
        from Bio import SeqIO
        from Bio.Seq import Seq
        from Bio.SeqFeature import SeqFeature, FeatureLocation
        from Bio.SeqRecord import SeqRecord
        record = SeqRecord(Seq("ATGAAATAG"), id="seq", name="seq", description="public")
        record.annotations["molecule_type"] = "DNA"
        record.features = [SeqFeature(FeatureLocation(0, 9), type="CDS", qualifiers={"translation": ["MK"]})]
        output = io.StringIO()
        SeqIO.write([record], output, "genbank")
        files = detection_files()
        files["input_gbks/Public.gbk"] = output.getvalue().encode()
        files["funbgcex/Public/allBGCs.csv"] = b"BGC,product\n"
        files.pop("summary_tables/bacterial_record_maps/Public.record_map.tsv")
        outcome = json.loads(files["outcome.json"])
        outcome.update(gbk_status="funannotate_fixed", prediction_method="funannotate", funbgcex_status="ran_ok",
                       taxon_group="fungi", detector_profile="antismash+funbgcex", funbgcex_applicability="applicable")
        files["outcome.json"] = cache.canonical(outcome)
        ident = identity()
        ident["route"]["taxon"] = "fungi"
        ident["containers"] = {"funbgcex": "a" * 64, "funannotate": "b" * 64}
        ident["models"] = {"embedded": cache.sha256(cache.canonical({"native": ident["runtime_sha256"], "images": ident["containers"]}))}
        adapter.validate_bundle({"bundle.tar": adapter.pack(files)}, ident)
        files["input_gbks/Public.gbk"] = format_record("seq", "ATGAAATAG", "linear").encode()
        with self.assertRaisesRegex(cache.Unavailable, "annotation_incomplete"):
            adapter.validate_bundle({"bundle.tar": adapter.pack(files)}, ident)


if __name__ == "__main__":
    unittest.main()
