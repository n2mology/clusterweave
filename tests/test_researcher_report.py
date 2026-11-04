from __future__ import annotations

import csv
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))
from canonical_pipeline import Job, ProjectLayout, _collect_result_files, _stream_cmd
from researcher_report import build_report, package_name, taxon_metadata
from resource_usage import StageSampler


class ResearcherReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / "job"
        self.result = self.base / "data/results/example"
        (self.result / "summary_tables").mkdir(parents=True)
        (self.result / "input_gbks").mkdir()
        for name in ("Bacterium", "Fungus", "Unknown"):
            (self.result / "input_gbks" / (name + ".gbk")).write_text("LOCUS staged genome\n")
        (self.result / "summary_tables/genome_taxon_manifest.tsv").write_text(
            "genome_id\ttaxon_group\tsource_accession\nBacterium\tbacteria\tGCF_999999999.1\nFungus\tfungi\tGCA_999999998.1\n")
        self.layout = ProjectLayout(project_name="example", repo_root=ROOT, data_root=self.base / "data",
            results_root=self.result, software_root=self.base / "software", work_root=self.base / "work", downloads_root=self.base / "downloads")

    def test_grouped_export_preserves_internal_files_and_both_checksum_manifests(self):
        original = {p.name: (p.stat().st_ino, p.read_bytes()) for p in (self.result / "input_gbks").iterdir()}
        job = Job(id="example", name="example")
        _collect_result_files(job, self.base, self.layout)
        with zipfile.ZipFile(self.base / "downloads/example_public_results.zip") as archive:
            for group, label in (("bacteria", "Bacterium"), ("fungi", "Fungus"), ("unclassified", "Unknown")):
                path = f"input_gbks/{group}/{label}.gbk"
                self.assertEqual(archive.read(path), original[label + ".gbk"][1])
                self.assertEqual((self.result / "input_gbks" / (label + ".gbk")).stat().st_ino, original[label + ".gbk"][0])
            manifest = list(csv.DictReader(io.StringIO(archive.read("downloads/public_results_manifest.tsv").decode()), delimiter="\t"))
            for row in manifest:
                raw = archive.read(row["path"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), row["sha256"])
                self.assertEqual(len(raw), int(row["bytes"]))
            evidence = list(csv.DictReader(io.StringIO(archive.read("evidence/clusterweave_evidence_manifest.tsv").decode()), delimiter="\t"))
            for row in evidence:
                self.assertEqual(hashlib.sha256(archive.read(row["package_path"])).hexdigest(), row["sha256"])
            self.assertTrue({"METHODS.md", "run_metadata.json", "resources.tsv", "CITATIONS.bib", "CITATION.cff"}.issubset(archive.namelist()))

    def test_historical_report_does_not_invent_versions_release_or_resources(self):
        (self.result / "antismash/Bacterium").mkdir(parents=True)
        (self.result / "antismash/Bacterium/index.html").write_text("old output")
        files = build_report(self.result, root=ROOT)
        value = json.loads(files["run_metadata.json"])
        self.assertIsNone(value["project"]["release_record"])
        self.assertIsNone(value["project"]["source_sha256"])
        self.assertIsNone(value["processing_wall_seconds_before_packaging"])
        self.assertEqual(value["resources"], [])
        self.assertIsNone(value["tools"][0]["version"])
        self.assertIsNone(value["tools"][0]["citation_doi"])
        self.assertIn(b"not recorded", files["METHODS.md"])

    def test_cache_producer_identity_is_retained_without_private_execution_context(self):
        from test_cached_accession import identity
        directory = self.result / "reproducibility/accession_cache"; directory.mkdir(parents=True)
        value = {"identity": identity(), "key": "a" * 64, "outcome": "hit", "population": "not-attempted",
            "producer_execution": {"worker_image": "b" * 64, "private_job": "private-owner"},
            "token": "private-token", "path": "/data/jobs/private-owner"}
        (directory / "Bacterium.detection.json").write_text(json.dumps(value))
        files = build_report(self.result, root=ROOT)
        metadata = json.loads(files["run_metadata.json"])
        self.assertEqual(metadata["cache"][0]["producer_execution"], {"worker_image": "b" * 64})
        self.assertEqual(metadata["cache"][0]["outcome"], "hit")
        for secret in (b"private-owner", b"private-token", b"/data/jobs"):
            self.assertNotIn(secret, b"".join(files.values()))

    def test_report_does_not_follow_input_or_taxon_links(self):
        outside = Path(self.tmp.name) / "private"; outside.write_text("secret")
        (self.result / "input_gbks/Linked.gbk").symlink_to(outside)
        route = self.result / "summary_tables/genome_taxon_manifest.tsv"
        route.unlink(); route.symlink_to(outside)
        self.assertEqual(taxon_metadata(self.result), {})
        files = build_report(self.result, root=ROOT)
        self.assertNotIn("Linked", json.dumps(json.loads(files["run_metadata.json"])["inputs"]))

    def test_cache_resource_records_keep_allocations_without_private_context(self):
        from test_cached_accession import identity
        directory = self.result / "reproducibility/accession_cache"; directory.mkdir(parents=True)
        record = {"identity": identity(), "outcome": "hit", "key": "a" * 64,
            "producer_execution": {"worker_image": "b" * 64,
                "scheduling": {"CPUS": "2", "WORKERS": "1", "secret": "private-token"}},
            "materializer_scheduling": {"CPUS": "12", "THREADS": "/data/jobs/private-owner"}}
        (directory / "Bacterium.detection.json").write_text(json.dumps(record))
        files = build_report(self.result, root=ROOT)
        value = json.loads(files["run_metadata.json"])["cache"][0]
        self.assertEqual(value["producer_execution"]["scheduling"], {"CPUS": "2", "WORKERS": "1"})
        self.assertEqual(value["materializer_scheduling"], {"CPUS": "12"})
        self.assertEqual(value["identity"]["parameters"]["partition_sha256"], identity()["parameters"]["partition_sha256"])
        for secret in (b"private-token", b"private-owner", b"/data/jobs"):
            self.assertNotIn(secret, b"".join(files.values()))

    def test_stage_accounting_preserves_failure_and_records_native_cpu_and_memory(self):
        metrics = Path(self.tmp.name) / "metrics.json"
        program = "import time; x=bytearray(2000000); end=time.process_time()+0.08\nwhile time.process_time()<end: pass\nprint('stage-output'); raise SystemExit(7)"
        result = subprocess.run([sys.executable, "-B", str(ROOT / "web/stage_runner.py"), "--metrics", str(metrics),
            "--job", "synthetic", "--", sys.executable, "-B", "-c", program], capture_output=True, start_new_session=True,
            env=dict(os.environ, CLUSTERWEAVE_RESOURCE_DOCKER_OBSERVATION="0", PYTHONDONTWRITEBYTECODE="1"), timeout=10)
        self.assertEqual(result.returncode, 7); self.assertIn(b"stage-output", result.stdout)
        record = json.loads(metrics.read_bytes())
        self.assertGreater(record["native_cpu_seconds"], 0.03)
        self.assertGreater(record["native_largest_process_peak_rss_bytes"], 0)
        self.assertGreater(record["wall_seconds"], 0.05)
        self.assertIsNone(record["container_sampled_cpu_seconds"])
        self.assertIn("not an exact", record["memory_method"])

    def test_container_observation_filters_other_jobs_and_keeps_image_identity(self):
        sampler = StageSampler("synthetic", os.getpgrp())
        container = {"Id": "a" * 64, "ImageID": "sha256:" + "b" * 64, "Created": int(sampler.started) + 1, "Labels": {"clusterweave.job_id": "synthetic"}}
        foreign = {**container, "Id": "c" * 64, "Labels": {"clusterweave.job_id": "other"}}
        stats = {"cpu_stats": {"cpu_usage": {"total_usage": 2_000_000_000}}, "memory_stats": {"usage": 1024}}
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_RESOURCE_DOCKER_OBSERVATION": "1"}), mock.patch("resource_usage.Path.exists", return_value=True), mock.patch("resource_usage.process_group_rss", return_value=512), mock.patch("resource_usage.docker_json", side_effect=[[container, foreign], stats]) as request:
            sampler.sample()
        self.assertEqual(len(request.call_args_list), 2)
        self.assertEqual(sampler.cpu, {"a" * 64: 2_000_000_000})
        self.assertEqual(sampler.images, {"b" * 64})
        self.assertEqual(sampler.combined_peak, 1536)

    def test_container_observation_subtracts_preexisting_cpu_without_double_counting(self):
        sampler = StageSampler("synthetic", os.getpgrp())
        container = {"Id": "a" * 64, "Created": int(sampler.started), "Labels": {"clusterweave.job_id": "synthetic"}}
        def stats(cpu): return {"cpu_stats": {"cpu_usage": {"total_usage": cpu}}, "memory_stats": {"usage": 1024}}
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_RESOURCE_DOCKER_OBSERVATION": "1"}), mock.patch("resource_usage.Path.exists", return_value=True), mock.patch("resource_usage.process_group_rss", return_value=512), mock.patch("resource_usage.docker_json", side_effect=[[container], stats(10), [container], stats(15)]):
            sampler.sample(); sampler.sample()
        self.assertEqual(sampler.cpu, {"a" * 64: 5})

    def test_pipeline_stage_preserves_stream_and_exit_status_and_publishes_measurements(self):
        job = Job(id="synthetic", name="example")
        job._researcher = {"metrics_dir": str(self.base / "work/resource_usage"), "resources": []}
        env = dict(os.environ, CLUSTERWEAVE_RESOURCE_DOCKER_OBSERVATION="0", PYTHONDONTWRITEBYTECODE="1")
        code = asyncio.run(_stream_cmd([sys.executable, "-B", "-c", "print('scientific-output'); raise SystemExit(4)"],
                                     cwd=ROOT, job=job, env=env))
        self.assertEqual(code, 4)
        self.assertTrue(any("scientific-output" in line for line in job.log_lines))
        self.assertEqual(job._researcher["resources"][0]["exit_code"], 4)
        files = build_report(self.result, state=job._researcher, root=ROOT)
        metadata = json.loads(files["run_metadata.json"])
        self.assertGreaterEqual(metadata["resources"][0]["native_cpu_seconds"], 0)
        self.assertNotIn(str(self.base), files["run_metadata.json"].decode())

    def test_reference_inventory_retains_hashes_without_paths_or_source_credentials(self):
        directory = self.result / "reproducibility"; directory.mkdir()
        (directory / "external_artifacts.tsv").write_text(
            "artifact\tsha256\tversion_or_tag\tlocal_path\tsource_uri\n"
            "pfam_hmm\t" + "a" * 64 + "\t35.0\t/private/reference\thttps://private.invalid/?token=secret-value\n")
        metadata = json.loads(build_report(self.result, root=ROOT)["run_metadata.json"])
        self.assertEqual(metadata["observed_external_artifacts"], [{"artifact": "pfam_hmm", "sha256": "a" * 64, "recorded_version_or_tag": "35.0"}])
        self.assertNotIn("private", json.dumps(metadata))
        self.assertNotIn("secret-value", json.dumps(metadata))

    def test_clinker_panel_versions_resolve_selected_container_without_worker_fallback(self):
        panel = self.result / "clinker/atlas/example"; panel.mkdir(parents=True)
        (panel / "panel.html").write_text("completed panel")
        directory = self.result / "reproducibility/tool_observations"; directory.mkdir(parents=True)
        record = {"tool": "clinker", "backend": "docker", "version": "0.0.32", "runtime_sha256": "a" * 64,
                  "configured_tag": "0.0.32--pyhdfd78af_0", "observation_run": "current", "path": "/private/job", "token": "secret"}
        (directory / "runtime.json").write_text(json.dumps(record))
        files = build_report(self.result, state={"observation_run": "current", "versions": {"clinker": "9.9.9"}}, root=ROOT)
        tool = json.loads(files["run_metadata.json"])["tools"][0]
        self.assertEqual(tool["name"], "clinker"); self.assertEqual(tool["version"], "0.0.32")
        self.assertEqual(tool["runtime_observations"][0]["runtime_sha256"], "a" * 64)
        self.assertIn(b"clinker", files["METHODS.md"])
        self.assertNotIn(b"/private/job", b"".join(files.values())); self.assertNotIn(b"secret", b"".join(files.values()))
        historical = json.loads(build_report(self.result, state={"observation_run": "another"}, root=ROOT)["run_metadata.json"])
        self.assertIsNone(historical["tools"][0]["version"])

    def test_cached_tools_keep_producer_version_and_do_not_use_current_executable(self):
        from test_cached_accession import identity
        from tool_runtime import safe_observation
        directory = self.result / "reproducibility/accession_cache"; directory.mkdir(parents=True)
        producer = safe_observation({"tool": "antiSMASH", "backend": "native", "version": "8.0.4", "executable_sha256": "c" * 64})
        record = {"identity": identity(), "outcome": "hit", "producer_execution": {"worker_image": "b" * 64, "tool_versions": [producer]}}
        (directory / "Bacterium.detection.json").write_text(json.dumps(record))
        (self.result / "summary_tables/run_manifest.tsv").write_text("genome_id\tprediction_method\tantismash_status\nBacterium\tprodigal\tskipped_done\n")
        state = {"versions": {"antiSMASH": "99.0.0"}, "annotation_observations": [{"tool": "antiSMASH", "backend": "native", "version": "99.0.0"}]}
        tools = {t["name"]: t for t in json.loads(build_report(self.result, state=state, root=ROOT)["run_metadata.json"])["tools"]}
        self.assertEqual(tools["antiSMASH"]["version"], "8.0.4")
        self.assertEqual(tools["antiSMASH"]["use"], "analysis reused from verified cache")
        self.assertEqual(tools["antiSMASH"]["runtime_observations"], [])
        self.assertIsNone(tools["Prodigal"]["version"])

    def _write_cache_identity(self, value, kind="detection", label="Bacterium", **extra):
        directory = self.result / "reproducibility/accession_cache"
        directory.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        record = {"identity": value, "key": key, "outcome": "hit", **extra}
        (directory / (label + "." + kind + ".json")).write_text(json.dumps(record))
        return record

    def test_original_producer_recovery_is_bound_to_cache_and_immutable_runtime(self):
        from test_cached_accession import identity
        from researcher_report import collect_run_versions
        value = identity()
        producer = {"worker_image": "b" * 64, "native_runtime_sha256": value["runtime_sha256"], "producer_source_sha256": value["source_sha256"]}
        record = self._write_cache_identity(value, producer_execution=producer)
        (self.result / "summary_tables/run_manifest.tsv").write_text("genome_id\tprediction_method\tantismash_status\nBacterium\tprodigal\tskipped_done\n")
        original = (self.result / "reproducibility/accession_cache/Bacterium.detection.json").read_bytes()
        def probe(tool, backend, runtime):
            self.assertEqual((backend, runtime), ("docker", "sha256:" + "b" * 64))
            return {"tool": tool, "backend": backend, "runtime_sha256": runtime, "version": "2.6.3" if tool == "Prodigal" else "8.0.4", "path": "/private/job", "token": "secret"}
        state = {}
        with mock.patch("researcher_report.observe", side_effect=probe) as calls:
            collect_run_versions(self.result, self.layout.work_root, {}, state)
        self.assertEqual(calls.call_count, 2)
        files = build_report(self.result, state=state, root=ROOT)
        metadata = json.loads(files["run_metadata.json"])
        tools = {row["name"]: row for row in metadata["tools"]}
        self.assertEqual(tools["Prodigal"]["version"], "2.6.3")
        self.assertEqual(tools["antiSMASH"]["version"], "8.0.4")
        self.assertEqual(tools["antiSMASH"]["version_observation"], "verified original producer runtime")
        self.assertEqual(metadata["cache"][0]["version_recovery"][0]["cache_key"], record["key"])
        self.assertEqual((self.result / "reproducibility/accession_cache/Bacterium.detection.json").read_bytes(), original)
        for forbidden in (b"; ;", b"Reuse does not", b"secret", b"/private/job", b"| Prodigal | not recorded |"):
            self.assertNotIn(forbidden, files["METHODS.md"])
        self.assertIn(b"Prodigal", files["CITATIONS.bib"])
        self.assertIn(b"analysis reused from verified cache", files["CITATIONS.bib"])
        for wrong in ("cache_key", "runtime_sha256"):
            invalid = {**state, "producer_version_recoveries": [{**r, wrong: "c" * 64} for r in state["producer_version_recoveries"]]}
            rows = json.loads(build_report(self.result, state=invalid, root=ROOT)["run_metadata.json"])["tools"]
            self.assertTrue(all(row["version"] is None for row in rows))

    def test_partial_cached_version_evidence_keeps_each_producer_gap_visible(self):
        from test_cached_accession import identity
        from tool_runtime import safe_observation
        first = identity()
        observed = safe_observation({"tool": "antiSMASH", "backend": "native", "version": "8.0.4", "executable_sha256": "c" * 64})
        self._write_cache_identity(first, producer_execution={"tool_versions": [observed]})
        second = identity(); second["accession"] = "GCF_999999998.1"
        self._write_cache_identity(second, label="Other", producer_execution={})
        (self.result / "summary_tables/run_manifest.tsv").write_text("genome_id\tprediction_method\tantismash_status\nBacterium\tprodigal\tskipped_done\nOther\tprodigal\tskipped_done\n")
        files = build_report(self.result, root=ROOT)
        tools = {r["name"]: r for r in json.loads(files["run_metadata.json"])["tools"]}
        self.assertEqual(sorted(r["status"] for r in tools["antiSMASH"]["producer_version_coverage"]), ["unavailable", "verified"])
        self.assertIn(b"producer versions verified for 1/2 cache entries", files["METHODS.md"])

    def test_retrieval_version_requires_exact_original_executable(self):
        from test_cached_accession import identity
        from researcher_report import collect_run_versions
        value = identity(); value["contract"] = "accession-snapshot-v2"; value["tools"] = {"datasets": "d" * 64, "unzip": "e" * 64}
        self._write_cache_identity(value, "snapshot")
        observation = {"tool": "NCBI Datasets", "backend": "native", "version": "18.12.0", "executable_sha256": "d" * 64}
        state = {}
        with mock.patch("researcher_report.observe", return_value=observation):
            collect_run_versions(self.result, self.layout.work_root, {}, state)
        files = build_report(self.result, state=state, root=ROOT)
        self.assertEqual(json.loads(files["run_metadata.json"])["tools"][0]["version"], "18.12.0")
        self.assertIn(b"NCBI Datasets", files["CITATIONS.bib"])
        with mock.patch("researcher_report.observe", return_value={**observation, "executable_sha256": "f" * 64}):
            collect_run_versions(self.result, self.layout.work_root, {}, state)
        self.assertIsNone(json.loads(build_report(self.result, state=state, root=ROOT)["run_metadata.json"])["tools"][0]["version"])

    def test_dependency_versions_require_annotation_use_and_execution_records(self):
        from researcher_report import collect_run_versions
        (self.result / "summary_tables/run_manifest.tsv").write_text("genome_id\tprediction_method\tgbk_status\nFungus\tfunannotate\tfunannotate_fixed\n")
        logs = self.layout.work_root / "logs"; logs.mkdir(parents=True)
        (logs / "Fungus.funannotate.log").write_text("Installed BUSCO: 5.0.0\nAUGUSTUS: 3.5.0\n[01/01/26 10:00:00]: /opt/bin/augustus --species=fixture sequence.fa\n[DEBUG] busco --version\n")
        state = {"annotation_observations": [{"tool": "funannotate", "backend": "docker", "version": "1.8.17", "runtime_sha256": "sha256:" + "a" * 64}]}
        with mock.patch("researcher_report.observe", return_value={"tool": "AUGUSTUS", "backend": "docker", "version": "3.5.0", "runtime_sha256": "sha256:" + "a" * 64}) as calls:
            collect_run_versions(self.result, self.layout.work_root, {}, state)
        self.assertEqual(calls.call_args.args, ("AUGUSTUS", "docker", "sha256:" + "a" * 64))
        rows = {r["name"]: r for r in json.loads(build_report(self.result, state=state, root=ROOT)["run_metadata.json"])["tools"]}
        self.assertEqual(rows["AUGUSTUS"]["version"], "3.5.0")
        self.assertNotIn("BUSCO", rows)
        with mock.patch("researcher_report.observe", return_value=None):
            collect_run_versions(self.result, self.layout.work_root, {}, state)
        missing = {r["name"]: r for r in json.loads(build_report(self.result, state=state, root=ROOT)["run_metadata.json"])["tools"]}
        self.assertIn("AUGUSTUS", missing)
        self.assertIsNone(missing["AUGUSTUS"]["version"])
        (self.result / "summary_tables/run_manifest.tsv").write_text("genome_id\tprediction_method\nFungus\texisting_cds\n")
        rows = json.loads(build_report(self.result, state=state, root=ROOT)["run_metadata.json"])["tools"]
        self.assertFalse(any(r["name"] in {"AUGUSTUS", "funannotate"} for r in rows))

    def test_mibig_version_requires_actual_bigscape_invocation_and_output(self):
        from researcher_report import collect_run_versions
        state = {}
        (self.result / "big_scape").mkdir(); (self.result / "big_scape/index.html").write_text("result")
        logs = ["[INFO] MiBIG cache detected; enabling --mibig-version 4.0", "[INFO] Running BiG-SCAPE (inside container) with FastTree on PATH"]
        collect_run_versions(self.result, self.layout.work_root, {}, state, logs[:1])
        self.assertEqual(json.loads(build_report(self.result, state=state, root=ROOT)["run_metadata.json"])["references"], [])
        collect_run_versions(self.result, self.layout.work_root, {}, state, logs)
        files = build_report(self.result, state=state, root=ROOT)
        self.assertEqual(json.loads(files["run_metadata.json"])["references"][0]["version"], "4.0")
        self.assertIn(b"@misc{mibig", files["CITATIONS.bib"])
        collect_run_versions(self.result, self.layout.work_root, {}, state, logs + ["Stage 2/4: running rerun", "running without MiBIG integration", logs[-1]])
        self.assertEqual(state["reference_observations"], [])

    def test_failed_current_annotation_keeps_versions_and_outcomes_in_package(self):
        from researcher_report import collect_run_versions
        (self.result / "summary_tables/run_manifest.tsv").write_text(
            "genome_id\ttaxon_group\tprediction_method\tgbk_status\tantismash_status\tfunbgcex_status\n"
            "Fungus\tfungi\tfunannotate\tfunannotate_busco_training_insufficient\tskipped\tskipped\n")
        (self.result / "input_gbks/Fungus.gbk").unlink()
        logs = self.layout.work_root / "logs"; logs.mkdir(parents=True)
        (logs / "Fungus.funannotate.log").write_text("[DEBUG] /opt/bin/augustus --species=fixture sequence.fa\n")
        runtime = "sha256:" + "a" * 64
        state = {"annotation_observations": [{"tool": "funannotate", "backend": "docker", "version": "1.8.17", "runtime_sha256": runtime}]}
        marker = '[12:00:00] [2026-01-01 12:00:00] [INFO] TOOL_PROGRESS genome=Fungus tool=funannotate phase=predict message="Started funannotate"'
        with mock.patch("researcher_report.observe", return_value={"tool": "AUGUSTUS", "backend": "docker", "version": "3.3.2", "runtime_sha256": runtime}):
            collect_run_versions(self.result, self.layout.work_root, {}, state, [marker])
        job = Job(id="example", name="example"); job._researcher = state
        _collect_result_files(job, self.base, self.layout)
        with zipfile.ZipFile(self.base / "downloads/example_public_results.zip") as archive:
            metadata = json.loads(archive.read("run_metadata.json"))
            tools = {row["name"]: row for row in metadata["tools"]}
            self.assertEqual(tools["funannotate"]["version"], "1.8.17")
            self.assertEqual(tools["AUGUSTUS"]["version"], "3.3.2")
            self.assertIn("current execution", tools["funannotate"]["use"])
            self.assertIn("annotation failed", tools["funannotate"]["use"])
            methods = archive.read("METHODS.md")
            self.assertIn(b"funannotate_busco_training_insufficient | skipped | skipped |", methods)
            self.assertIn(b"| funannotate | 1.8.17 |", methods)
            self.assertNotIn(b"existing outputs", methods)
            self.assertIn(b"1.8.17; current execution; annotation failed", archive.read("CITATIONS.bib"))
            self.assertNotIn("input_gbks/fungi/Fungus.gbk", archive.namelist())
            self.assertNotIn("antiSMASH", tools)
            self.assertNotIn("FunBGCeX", tools)

    def test_failed_annotation_preflight_and_prior_attempts_do_not_prove_current_use(self):
        from researcher_report import collect_run_versions
        (self.result / "summary_tables/run_manifest.tsv").write_text(
            "genome_id\tprediction_method\tgbk_status\nFungus\tfunannotate\tfunannotate_busco_training_insufficient\n")
        observation = {"tool": "funannotate", "backend": "docker", "version": "1.8.17", "runtime_sha256": "sha256:" + "a" * 64}
        marker = 'TOOL_PROGRESS genome=Fungus tool=funannotate phase=predict message="Started funannotate"'
        for lines in ([], [marker, "[12:00:01] === Stage: Preparing ClusterWeave project layout ==="],
                      ["[INFO] TOOL_RAW genome=Fungus tool=funannotate stream=stderr " + marker],
                      [marker.replace("genome=Fungus", "genome=Other")], [marker.replace("phase=predict", "phase=clean")]):
            with self.subTest(lines=lines):
                state = {"annotation_observations": [observation]}
                collect_run_versions(self.result, self.layout.work_root, {}, state, lines)
                tool = json.loads(build_report(self.result, state=state, root=ROOT)["run_metadata.json"])["tools"][0]
                self.assertIsNone(tool["version"])
                self.assertEqual(tool["runtime_observations"], [])
                self.assertIn("annotation failed", tool["use"])
                self.assertNotIn("current execution", tool["use"])
                self.assertNotIn("existing outputs", tool["use"])
        state = {}
        collect_run_versions(self.result, self.layout.work_root, {}, state, [marker])
        files = build_report(self.result, state=state, root=ROOT)
        self.assertIsNone(json.loads(files["run_metadata.json"])["tools"][0]["version"])
        self.assertIn(b"version evidence unavailable for current execution", files["METHODS.md"])

    def test_failed_fresh_annotation_preserves_other_cached_producer_version(self):
        from researcher_report import collect_run_versions
        from test_cached_accession import identity
        cached = {"tool": "funannotate", "backend": "docker", "version": "1.8.16", "runtime_sha256": "sha256:" + "b" * 64}
        record = self._write_cache_identity(identity(), label="Cached", producer_execution={"tool_versions": [cached]})
        path = self.result / "reproducibility/accession_cache/Cached.detection.json"; original = path.read_bytes()
        (self.result / "summary_tables/run_manifest.tsv").write_text(
            "genome_id\tprediction_method\tgbk_status\tantismash_status\n"
            "Cached\tfunannotate\tfunannotate_fixed\tskipped_done\n"
            "Fungus\tfunannotate\tfunannotate_busco_training_insufficient\tskipped\n")
        state = {"annotation_observations": [{"tool": "funannotate", "backend": "docker", "version": "1.8.17", "runtime_sha256": "sha256:" + "a" * 64}]}
        with mock.patch("researcher_report.observe", return_value=None):
            collect_run_versions(self.result, self.layout.work_root, {}, state,
                ['TOOL_PROGRESS genome=Fungus tool=funannotate phase=predict message="Started funannotate"'])
        tool = next(row for row in json.loads(build_report(self.result, state=state, root=ROOT)["run_metadata.json"])["tools"] if row["name"] == "funannotate")
        self.assertEqual(tool["verified_versions"], ["1.8.16", "1.8.17"])
        self.assertEqual(tool["producer_version"], "1.8.16")
        self.assertEqual(tool["producer_version_coverage"], [{"cache_key": record["key"], "versions": ["1.8.16"], "status": "verified"}])
        self.assertIn("annotation failed for 1", tool["use"])
        self.assertIn("reused from verified cache", tool["use"])
        self.assertEqual(path.read_bytes(), original)

    def test_resumed_outputs_without_cache_provenance_do_not_claim_cache_reuse(self):
        (self.result / "summary_tables/run_manifest.tsv").write_text("genome_id\tprediction_method\tantismash_status\nBacterium\tprodigal\tskipped_done\n")
        tools = json.loads(build_report(self.result, root=ROOT)["run_metadata.json"])["tools"]
        self.assertTrue(all(t["use"] == "existing outputs; original execution not recorded" for t in tools))
        self.assertTrue(all(t["version"] is None for t in tools))

    def test_optional_configuration_does_not_establish_use_but_outputs_do(self):
        state = {"configuration": {"RUN_PHYLOGENY": "1", "RUN_NPLINKER": "1"}, "versions": {"MAFFT": "7.5"}}
        self.assertEqual(json.loads(build_report(self.result, state=state, root=ROOT)["run_metadata.json"])["tools"], [])
        (self.result / "phylogeny").mkdir()
        (self.result / "phylogeny/phylogeny_run_manifest.json").write_text(json.dumps({"status": "insufficient_data"}))
        self.assertEqual(json.loads(build_report(self.result, state=state, root=ROOT)["run_metadata.json"])["tools"], [])
        (self.result / "phylogeny/phylogeny_run_manifest.json").write_text(json.dumps({"status": "success", "topology_comparison_count": 1}))
        (self.result / "nplinker/output").mkdir(parents=True)
        (self.result / "nplinker/output/links_example.tsv").write_text("links")
        tools = {t["name"]: t for t in json.loads(build_report(self.result, state=state, root=ROOT)["run_metadata.json"])["tools"]}
        self.assertEqual(set(tools), {"MAFFT", "trimAl", "IQ-TREE", "ETE4", "NPLinker"})
        self.assertTrue(all(t["version"] is None for t in tools.values()))

    def test_conflicting_taxon_assignments_export_as_unclassified_consistently(self):
        route = self.result / "summary_tables/genome_taxon_manifest.tsv"
        with route.open("a") as handle: handle.write("Bacterium\tfungi\tGCF_999999999.1\n")
        _collect_result_files(Job(id="example", name="example"), self.base, self.layout)
        with zipfile.ZipFile(self.base / "downloads/example_public_results.zip") as archive:
            self.assertIn("input_gbks/unclassified/Bacterium.gbk", archive.namelist())
            rows = list(csv.DictReader(io.StringIO(archive.read("evidence/clusterweave_evidence_manifest.tsv").decode()), delimiter="\t"))
            for row in rows:
                self.assertEqual(hashlib.sha256(archive.read(row["package_path"])).hexdigest(), row["sha256"])

    def test_sampler_start_failure_does_not_change_scientific_exit_status(self):
        import stage_runner
        path = Path(self.tmp.name) / "resource-failure.json"
        argv = ["stage_runner.py", "--metrics", str(path), "--job", "synthetic", "--", sys.executable, "-c", "raise SystemExit(0)"]
        with mock.patch.object(sys, "argv", argv), mock.patch("stage_runner.signal.signal"), mock.patch("stage_runner.StageSampler.start", side_effect=RuntimeError("No thread available")):
            self.assertEqual(stage_runner.main(), 0)
        self.assertTrue(json.loads(path.read_bytes())["sampling_incomplete"])


if __name__ == "__main__": unittest.main()
