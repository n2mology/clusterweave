from __future__ import annotations

import importlib.util
import json
import os
import signal
import time
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def wait_for_process_group(pgid: int, timeout: float = 5) -> None:
    # Grandchildren may still write EXIT receipts after the parent is reaped.
    # Zombies cannot write and may await reaping by the runner's init process.
    deadline = time.monotonic() + timeout
    while True:
        listing = subprocess.run(["ps", "-eo", "pgid=,stat="],
                                 capture_output=True, text=True, check=True, timeout=3)
        active = [line for line in listing.stdout.splitlines()
                  if len(fields := line.split()) == 2 and fields[0] == str(pgid)
                  and not fields[1].startswith(("Z", "X"))]
        if not active:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Test process group {pgid} is still active: {active}")
        time.sleep(.02)


@unittest.skipUnless(importlib.util.find_spec("Bio"), "Biopython is required")
class AnnotationSchedulingTests(unittest.TestCase):
    def test_entrypoint_keeps_record_partition_and_scientific_results_across_allocations(self):
        # Exercise actual discovery, sanitizing, splitting, scheduling and merging.
        # The controlled detector enforces one-record inputs and records their content.
        with tempfile.TemporaryDirectory(prefix="annotation scheduling ") as tmp:
            root = Path(tmp)
            tools = root / "tools"; tools.mkdir()
            detector = tools / "antismash"
            detector.write_text("""#!/usr/bin/env python3
import json, os, pathlib, signal, sys, time
from Bio import SeqIO
args = sys.argv[1:]
if '--help-showall' in args:
    print('--allow-long-headers'); raise SystemExit(0)
if not os.environ.get('TEST_LEGACY_FAILURE'):
    assert '--output-basename' in args, 'expected record partitioning at every concurrency'
records = list(SeqIO.parse(args[0], 'genbank'))
assert len(records) == 1
record = records[0]
started = time.monotonic()
if os.environ.get('TEST_CANCEL') == '1':
    folder = pathlib.Path(os.environ['TEST_TIMING_DIR'])
    def stop(signum, frame):
        (folder / (record.id + '.stopped')).write_text('terminated')
        time.sleep(.2)  # Model output finalization after receiving cancellation.
        (folder / (record.id + '.finished')).write_text('finalized')
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, stop)
    (folder / (record.id + '.started')).write_text(str(os.getpid()))
    while True:
        time.sleep(.05)
time.sleep(1)
(pathlib.Path(os.environ['TEST_TIMING_DIR']) / (record.id + '.json')).write_text(json.dumps({'id':record.id, 'start':started, 'end':time.monotonic(), 'cpus':int(args[args.index('--cpus') + 1])}))
out = pathlib.Path(args[args.index('--output-dir') + 1]); out.mkdir(parents=True, exist_ok=True)
name = args[args.index('--output-basename') + 1] if '--output-basename' in args else 'partial'
document = {'version': '8.0.4', 'records': [{'id': record.id, 'seq': str(record.seq),
    'features': [{'type': f.type, 'location': str(f.location), 'qualifiers': f.qualifiers} for f in record.features],
    'areas': [], 'modules': {}}], 'timings': {}}
(out / (name + '.json')).write_text(json.dumps(document, sort_keys=True))
if os.environ.get('TEST_DETECTOR_FAILURE') == '1':
    print('synthetic native failure after partial output', file=sys.stderr)
    raise SystemExit(17)
""")
            detector.chmod(0o755)
            docker = tools / "docker"
            docker.write_text("#!/usr/bin/env bash\nexit 97\n"); docker.chmod(0o755)
            outputs = []
            for cpus, concurrency, shard_cpus in ((2, 1, 1), (6, 3, 2), (3, 1, 1), (4, 1, 1), (5, 2, 1)):
                base = root / f"allocation-{cpus}"
                genomes = base / "genomes"; genomes.mkdir(parents=True)
                timings = base / "timings"; timings.mkdir()
                (genomes / "Public.fna").write_text(">first\n" + "ATG" * 500 + "\n>second\n" + "GCT" * 500 + "\n")
                result = base / "results"
                manifest = result / "summary_tables/genome_taxon_manifest.tsv"
                manifest.parent.mkdir(parents=True)
                manifest.write_text("input_key\tgenome_id\ttaxon_group\ttaxon_source\tsource_accession\troute_status\n"
                                    "public\tPublic\tbacteria\tuser\t\taccepted\n")
                env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ.get("PATH", ""),
                    TEST_TIMING_DIR=str(timings), ENGINE="docker", PROJECT_DIR=str(ROOT), PROJECT_NAME="scheduling_contract",
                    ANALYSIS_SCOPE="bacteria", FUNGI_GENOME_ROOT=str(base / "fungi"),
                    BACTERIA_GENOME_ROOT=str(genomes), RESULTS_ROOT=str(result), WORK_ROOT=str(base / "work"),
                    GENOME_TAXON_MANIFEST=str(manifest), CLUSTERWEAVE_ACCESSION_CACHE_ROOT="", FORCE="0",
                    CPUS=str(cpus), THREADS=str(cpus), GENOME_PARALLELISM="1", ANNO_CPUS="1", WORKERS="1",
                    ANTISMASH_RECORD_PARALLELISM=str(concurrency), ANTISMASH_SHARD_CPUS=str(shard_cpus),
                    PIPELINE_RESOURCE_MODE="conservative", VENV_PY=sys.executable, PYTHON_BIN=sys.executable,
                    AUTO_PULL_IMAGES="never", TOOL_ACTIVITY_HEARTBEAT_SECONDS="1")
                env["TEST_DETECTOR_FAILURE"] = "1" if cpus in (3, 4) else "0"
                if cpus == 4:
                    env["TEST_LEGACY_FAILURE"] = "1"
                    (genomes / "Public.fna").write_text(">first\n" + "ATG" * 500 + "\n")
                if cpus == 5:
                    env['TEST_CANCEL'] = '1'
                    with (base / 'cancel.log').open('w') as log:
                        process = subprocess.Popen(['bash', str(ROOT / 'run_annotation_and_detection.sh'), '-g', 'Public'],
                            env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                        try:
                            deadline = time.monotonic() + 20
                            while len(list(timings.glob('*.started'))) < 2 and time.monotonic() < deadline and process.poll() is None:
                                time.sleep(.02)
                            self.assertEqual(len(list(timings.glob('*.started'))), 2, (base / 'cancel.log').read_text())
                            os.killpg(process.pid, signal.SIGTERM)
                            process.wait(timeout=5)
                            wait_for_process_group(process.pid)
                            self.assertEqual(len(list(timings.glob('*.stopped'))), 2)
                            self.assertEqual(len(list(timings.glob('*.finished'))), 2)
                            self.assertNotEqual(process.returncode, 0)
                            self.assertFalse((result / 'antismash/Public/.done').exists())
                            if os.environ.get('CLUSTERWEAVE_SCHEDULING_EVIDENCE'):
                                evidence = Path(os.environ['CLUSTERWEAVE_SCHEDULING_EVIDENCE'])
                                evidence.mkdir(parents=True, exist_ok=True)
                                (evidence / 'cancellation.json').write_text(json.dumps({
                                    'concurrent_detectors_started': 2, 'detectors_received_sigterm': 2,
                                    'exit': process.returncode, 'completion_marker': False,
                                    'log': (base / 'cancel.log').read_text()}, indent=2))
                        finally:
                            # The parent can exit before its descendants do.
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            process.wait(timeout=5)
                            wait_for_process_group(process.pid)
                    continue
                completed = subprocess.run(["bash", str(ROOT / "run_annotation_and_detection.sh"), "-g", "Public"],
                    env=env, cwd=ROOT, capture_output=True, text=True, timeout=60)
                if cpus in (3, 4):
                    self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                    self.assertIn("Required BGC detection failed", completed.stdout + completed.stderr)
                    self.assertIn("\tfailed\t", (result / "summary_tables/run_manifest.tsv").read_text())
                    self.assertFalse((result / "antismash/Public/.done").exists())
                    self.assertTrue(any((base / "work/logs").glob("*stderr.log")))
                    continue
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertIn("antiSMASH record sharding enabled", completed.stdout)
                document = json.loads((result / "antismash/Public/Public.antismash.json").read_text())
                self.assertEqual(len(document["records"]), 2)
                self.assertTrue((result / "antismash/Public/.done").is_file())
                intervals = [json.loads(p.read_text()) for p in timings.glob('*.json')]
                self.assertEqual(len(intervals), 2)
                overlap = min(row['end'] for row in intervals) - max(row['start'] for row in intervals)
                if concurrency == 1:
                    self.assertLessEqual(overlap, 0)
                else:
                    self.assertGreater(overlap, 0, intervals)
                events = sorted((row[key], delta * row['cpus']) for row in intervals
                                for key, delta in [('start', 1), ('end', -1)])
                used = peak = 0
                for _, delta in events:
                    used += delta; peak = max(peak, used)
                self.assertLessEqual(peak, cpus)
                if os.environ.get('CLUSTERWEAVE_SCHEDULING_EVIDENCE'):
                    evidence = Path(os.environ['CLUSTERWEAVE_SCHEDULING_EVIDENCE'])
                    evidence.mkdir(parents=True, exist_ok=True)
                    (evidence / f'allocation-{cpus}.json').write_text(json.dumps({
                        'intervals': intervals, 'overlap_seconds': overlap, 'peak_declared_cpu_slots': peak,
                        'job_cpus': cpus, 'records': document['records'],
                        'record_map': (result / 'summary_tables/bacterial_record_maps/Public.record_map.tsv').read_text(),
                        'stdout': completed.stdout, 'stderr': completed.stderr,
                        'scope': 'Actual orchestrator and controlled detector processes; no native scientific claim.'}, indent=2))
                outputs.append({"records": document["records"],
                    "staged": (result / "input_gbks/Public.gbk").read_bytes(),
                    "map": (result / "summary_tables/bacterial_record_maps/Public.record_map.tsv").read_bytes()})
            self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
