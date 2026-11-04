from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


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
import json, pathlib, sys
from Bio import SeqIO
args = sys.argv[1:]
if '--help-showall' in args:
    print('--allow-long-headers'); raise SystemExit(0)
assert '--output-basename' in args, 'expected record partitioning at every concurrency'
records = list(SeqIO.parse(args[0], 'genbank'))
assert len(records) == 1
record = records[0]
out = pathlib.Path(args[args.index('--output-dir') + 1]); out.mkdir(parents=True, exist_ok=True)
name = args[args.index('--output-basename') + 1]
document = {'version': '8.0.4', 'records': [{'id': record.id, 'seq': str(record.seq),
    'features': [{'type': f.type, 'location': str(f.location), 'qualifiers': f.qualifiers} for f in record.features],
    'areas': [], 'modules': {}}], 'timings': {}}
(out / (name + '.json')).write_text(json.dumps(document, sort_keys=True))
""")
            detector.chmod(0o755)
            docker = tools / "docker"
            docker.write_text("#!/usr/bin/env bash\nexit 97\n"); docker.chmod(0o755)
            outputs = []
            for cpus, concurrency, shard_cpus in ((2, 1, 1), (6, 3, 2)):
                base = root / f"allocation-{cpus}"
                genomes = base / "genomes"; genomes.mkdir(parents=True)
                (genomes / "Public.fna").write_text(">first\n" + "ATG" * 500 + "\n>second\n" + "GCT" * 500 + "\n")
                result = base / "results"
                manifest = result / "summary_tables/genome_taxon_manifest.tsv"
                manifest.parent.mkdir(parents=True)
                manifest.write_text("input_key\tgenome_id\ttaxon_group\ttaxon_source\tsource_accession\troute_status\n"
                                    "public\tPublic\tbacteria\tuser\t\taccepted\n")
                env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ.get("PATH", ""),
                    ENGINE="docker", PROJECT_DIR=str(ROOT), PROJECT_NAME="scheduling_contract",
                    ANALYSIS_SCOPE="bacteria", FUNGI_GENOME_ROOT=str(base / "fungi"),
                    BACTERIA_GENOME_ROOT=str(genomes), RESULTS_ROOT=str(result), WORK_ROOT=str(base / "work"),
                    GENOME_TAXON_MANIFEST=str(manifest), CLUSTERWEAVE_ACCESSION_CACHE_ROOT="", FORCE="0",
                    CPUS=str(cpus), THREADS=str(cpus), GENOME_PARALLELISM="1", ANNO_CPUS="1", WORKERS="1",
                    ANTISMASH_RECORD_PARALLELISM=str(concurrency), ANTISMASH_SHARD_CPUS=str(shard_cpus),
                    PIPELINE_RESOURCE_MODE="conservative", VENV_PY=sys.executable, PYTHON_BIN=sys.executable,
                    AUTO_PULL_IMAGES="never", TOOL_ACTIVITY_HEARTBEAT_SECONDS="1")
                completed = subprocess.run(["bash", str(ROOT / "run_annotation_and_detection.sh"), "-g", "Public"],
                    env=env, cwd=ROOT, capture_output=True, text=True, timeout=30)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertIn("antiSMASH record sharding enabled", completed.stdout)
                document = json.loads((result / "antismash/Public/Public.antismash.json").read_text())
                self.assertEqual(len(document["records"]), 2)
                self.assertTrue((result / "antismash/Public/.done").is_file())
                outputs.append({"records": document["records"],
                    "staged": (result / "input_gbks/Public.gbk").read_bytes(),
                    "map": (result / "summary_tables/bacterial_record_maps/Public.record_map.tsv").read_bytes()})
            self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
