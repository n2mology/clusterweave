from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from annotation_source import ROOT, annotation_source, shell_function


SCENARIOS = ('success', 'empty', 'corrupt', 'missing', 'empty-file', 'failed',
             'stale', 'skip-done', 'force')
CSV_HEADER = 'BGC no.,Scaffold,Start position,End position,Core enzymes\n'


def detection_fixture(root: Path, scenario: str, definitions: str | None = None):
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'source input.gbk'
    source.write_text('generic detector input\n')
    out = root / 'results with spaces'
    work = root / 'work with spaces'
    work.mkdir()
    if scenario in {'stale', 'skip-done', 'force'}:
        out.mkdir()
        (out / '.done').touch()
        if scenario != 'stale':
            (out / 'allBGCs.csv').write_text(CSV_HEADER)
    definitions = definitions if definitions is not None else (ROOT / 'detection_funbgcex.sh').read_text()
    script = 'set -euo pipefail\n' + definitions + '\n' + f'''
log() {{ printf 'LOG|%s\\n' "$*"; }}
warn() {{ printf 'WARN|%s\\n' "$*" >&2; }}
genome_stage_progress() {{ printf 'PROGRESS|%s\\n' "$*"; }}
SCENARIO={shlex.quote(scenario)}
run_funbgcex_cli() {{
  printf '%s\\n' "$*" >> {shlex.quote(str(root / 'calls'))}
  printf 'tool stdout\\n'
  printf 'tool stderr\\n' >&2
  case "$SCENARIO" in
    missing) return 0 ;;
    empty-file) : > "$2/allBGCs.csv" ;;
    corrupt) printf 'nonempty historical completion input\\n' > "$2/allBGCs.csv" ;;
    empty) printf '%s' {shlex.quote(CSV_HEADER)} > "$2/allBGCs.csv" ;;
    *) printf '%s' {shlex.quote(CSV_HEADER + '1,Public,1,100,PKS' + chr(10))} > "$2/allBGCs.csv" ;;
  esac
  [[ "$SCENARIO" != failed ]]
}}
fbx_done=0
if funbgcex_done {shlex.quote(str(out))}; then fbx_done=1; fi
if [[ "$SCENARIO" == force ]]; then rm -rf {shlex.quote(str(out))}; fbx_done=0; fi
observed=unset
run_funbgcex_detection Public "$fbx_done" {shlex.quote(str(source))} {shlex.quote(str(out))} \\
  {shlex.quote(str(work))} {shlex.quote(str(root / 'stdout'))} {shlex.quote(str(root / 'stderr'))} \\
  {shlex.quote(str(root / 'genome.log'))} observed
printf '%s\\n' "$observed" > {shlex.quote(str(root / 'status'))}
'''
    result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=10)
    return result, out


def cli_fixture(root: Path, scenario: str, source_root: Path = ROOT):
    from Bio import SeqIO
    from Bio.Seq import Seq
    from Bio.SeqFeature import FeatureLocation, SeqFeature
    from Bio.SeqRecord import SeqRecord

    root.mkdir(parents=True, exist_ok=True)
    tools = root / 'stub tools'; tools.mkdir()
    fungi = root / 'fungal inputs'; fungi.mkdir()
    bacteria = root / 'bacterial inputs'; bacteria.mkdir()
    result = root / 'results with spaces'
    work = root / 'work with spaces'
    group = 'bacteria' if scenario == 'bacteria' else 'fungi'
    record = SeqRecord(Seq('ATG' * 400), id='Public', name='Public', description='generic fixture')
    record.annotations = {'molecule_type': 'DNA', 'date': '01-JAN-2000'}
    record.features = [SeqFeature(FeatureLocation(0, 1200), type='CDS',
                                 qualifiers={'translation': ['M' * 400], 'locus_tag': ['Public_1']})]
    SeqIO.write(record, (bacteria if group == 'bacteria' else fungi) / 'Public.gbk', 'genbank')
    manifest = result / 'summary_tables/genome_taxon_manifest.tsv'
    manifest.parent.mkdir(parents=True)
    manifest.write_text('input_key\tgenome_id\ttaxon_group\ttaxon_source\ttaxid\torganism_name\t'
                        'source_accession\tprediction_method\tdetector_profile\tinput_path_key\troute_status\troute_reason\n'
                        f'x\tPublic\t{group}\tuser\t\t\t\texisting_cds\tantismash+funbgcex\tx\taccepted\tfixture\n')
    (tools / 'antismash').write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if '--help-showall' in args:
    print('--allow-long-headers'); raise SystemExit(0)
out = pathlib.Path(args[args.index('--output-dir') + 1]); out.mkdir(parents=True, exist_ok=True)
(out / 'index.html').write_text('complete\\n')
(out / 'Public.antismash.json').write_text('{"records":[{"areas":[]}]}\\n')
with open(os.environ['N1_CALLS'], 'a') as f: f.write(json.dumps({'tool':'antismash','argv':args})+'\\n')
''')
    (tools / 'docker').write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if args[:2] == ['image','inspect']: raise SystemExit(0)
assert args[0] == 'run', args
index = args.index('fixture-funbgcex:stub')
command = args[index + 1:]
assert command[0] == 'run_funbgcex', command
with open(os.environ['N1_CALLS'], 'a') as f: f.write(json.dumps({'tool':'funbgcex','argv':args})+'\\n')
out = pathlib.Path(command[2]); out.mkdir(parents=True, exist_ok=True)
scenario = os.environ['N1_SCENARIO']
print('stub detector stdout'); print('stub detector stderr',file=sys.stderr)
if scenario == 'cancel':
    import signal, time
    def stop(*unused):
        pathlib.Path(os.environ['N1_STOPPED']).write_text('terminated'); raise SystemExit(143)
    signal.signal(signal.SIGTERM,stop)
    pathlib.Path(os.environ['N1_STARTED']).write_text(str(os.getpid()))
    while True: time.sleep(.1)
if scenario == 'missing': raise SystemExit(0)
if scenario == 'empty-file': (out/'allBGCs.csv').write_text('')
elif scenario == 'corrupt': (out/'allBGCs.csv').write_text('nonempty historical completion input\\n')
else:
    header = 'BGC no.,Scaffold,Start position,End position,Core enzymes\\n'
    (out/'allBGCs.csv').write_text(header + ('' if scenario == 'empty' else '1,Public,1,100,PKS\\n'))
raise SystemExit(7 if scenario == 'failed' else 0)
''')
    for path in tools.iterdir(): path.chmod(0o755)
    if scenario in {'stale', 'skip-done', 'force'}:
        for tool in ('antismash', 'funbgcex'):
            out = result / tool / 'Public'; out.mkdir(parents=True)
            (out / '.done').touch()
            if scenario != 'stale':
                if tool == 'antismash':
                    (out / 'index.html').write_text('complete\n')
                    (out / 'Public.antismash.json').write_text('{"records":[{"areas":[]}]}\n')
                else: (out / 'allBGCs.csv').write_text(CSV_HEADER)
        staged = result / 'input_gbks'; staged.mkdir()
        SeqIO.write(record, staged / 'Public.gbk', 'genbank')
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ.get('PATH', ''),
               ENGINE='docker', ANALYSIS_SCOPE=group, PROJECT_DIR=str(source_root), PROJECT_NAME='funbgcex_fixture',
               FUNGI_GENOME_ROOT=str(fungi), BACTERIA_GENOME_ROOT=str(bacteria),
               GENOME_TAXON_MANIFEST=str(manifest), RESULTS_ROOT=str(result), WORK_ROOT=str(work),
               FUNBGCEX_DOCKER_IMAGE='fixture-funbgcex:stub', AUTO_PULL_IMAGES='never',
               CLUSTERWEAVE_ACCESSION_CACHE_ROOT='', FORCE='0', VENV_PY=sys.executable,
               PYTHON_BIN=sys.executable, CPUS='2', THREADS='2', WORKERS='2', ANNO_CPUS='1',
               GENOME_PARALLELISM='1', ANTISMASH_RECORD_PARALLELISM='1',
               CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS='1', TOOL_ACTIVITY_HEARTBEAT_SECONDS='1',
               N1_SCENARIO=scenario, N1_CALLS=str(root/'calls.jsonl'),
               N1_STARTED=str(root/'started'), N1_STOPPED=str(root/'stopped'))
    command = ['bash', str(source_root / 'run_annotation_and_detection.sh')]
    if scenario == 'force': command.append('-f')
    command += ['-g', 'Public']
    return command, env, result


class FunbgcexExtractionTests(unittest.TestCase):
    def test_detection_outcome_streams_markers_and_historical_completion(self):
        expected = {'missing': 'failed', 'empty-file': 'failed', 'failed': 'failed',
                    'skip-done': 'skipped_done'}
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(prefix='FunBGCeX inputs ') as tmp:
                root = Path(tmp)
                completed, out = detection_fixture(root, scenario)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                status = expected.get(scenario, 'ran_ok')
                self.assertEqual((root/'status').read_text().strip(), status)
                self.assertEqual((out/'.done').exists(), status != 'failed')
                self.assertEqual((root/'calls').exists(), scenario != 'skip-done')
                if scenario != 'skip-done':
                    self.assertEqual((root/'stdout').read_text(), 'tool stdout\n')
                    self.assertEqual((root/'stderr').read_text(), 'tool stderr\n')
                    self.assertEqual((root/'work with spaces/funbgcex_in/source input.gbk').read_text(),
                                     'generic detector input\n')
                if status == 'failed': self.assertIn('FunBGCeX failed', completed.stdout)

    def test_prepared_runtime_selection_does_not_acquire_assets(self):
        definitions = (ROOT/'detection_funbgcex.sh').read_text()
        for case, runtime, code in [('docker','docker',0), ('docker-missing','',1),
                                    ('sif','sif',0), ('docker-optional','docker',0),
                                    ('docker-optional-missing','sif',0), ('venv','host',0), ('host','host',0),
                                    ('missing','',1), ('incomplete','',1)]:
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix='runtime paths ') as tmp:
                root = Path(tmp)
                python = root/'python'; python.write_text('#!/bin/sh\nexit 0\n'); python.chmod(0o755)
                command = root/'funbgcex'; command.write_text('#!/bin/sh\nexit 0\n'); command.chmod(0o755)
                sif = root/'prepared.sif'
                if case in {'sif','docker-missing','docker-optional-missing'}: sif.write_text('prepared fixture\n')
                venv = root/'venv/bin'
                if case in {'venv','incomplete'}:
                    venv.mkdir(parents=True)
                    for name in ('python','funbgcex'):
                        p=venv/name; p.write_text('#!/bin/sh\nexit 0\n'); p.chmod(0o755)
                script = 'set -eu\n'+definitions+f'''
CASE={shlex.quote(case)}
PATH={shlex.quote(str(root))}:"$PATH"
ENGINE=apptainer
[[ "$CASE" != docker && "$CASE" != docker-missing ]] || ENGINE=docker
FUNBGCEX_USE_DOCKER_IMAGE=0
[[ "$CASE" != docker-optional* ]] || FUNBGCEX_USE_DOCKER_IMAGE=1
FUNBGCEX_DOCKER_IMAGE=fixture-image
FUNBGCEX_SIF={shlex.quote(str(sif))}
FUNBGCEX_VENV_DIR={shlex.quote(str(root/'venv'))}
FUNBGCEX_RUNTIME=
FUNBGCEX_CMD=
FUNBGCEX_PYTHON_CMD=
AUTO_BUILD_FUNBGCEX_SIF=1
AUTO_BUILD_FUNBGCEX_DOCKER=1
FUNBGCEX_BOOTSTRAP=1
FUNBGCEX_IMAGE_URI=docker://fixture/source
log() {{ printf 'LOG|%s\\n' "$*"; }}
warn() {{ printf 'WARN|%s\\n' "$*" >&2; }}
die() {{ printf 'DIE|%s\\n' "$*" >&2; exit 19; }}
have() {{
  case "$1" in
    hmmscan|hmmfetch|hmmpress|diamond) [[ "$CASE" != incomplete && "$CASE" != missing ]] ;;
    funbgcex) [[ "$CASE" == host ]] ;;
    *) command -v "$1" >/dev/null ;;
  esac
}}
join_by() {{ local IFS="$1"; shift; printf '%s' "$*"; }}
docker() {{ [[ "$*" == 'image inspect fixture-image' && ( "$CASE" == docker || "$CASE" == docker-optional ) ]]; }}
resolve_python_cmd() {{ printf '%s\\n' {shlex.quote(str(python))}; }}
runtime_preparation_hint() {{ printf 'PREPARE_ONLY\\n' >&2; }}
rc=0
ensure_funbgcex_runtime || rc=$?
printf 'RESULT|%s|%s|%s|%s\\n' "$rc" "$FUNBGCEX_RUNTIME" "$FUNBGCEX_CMD" "$FUNBGCEX_PYTHON_CMD"
'''
                result = subprocess.run(['bash','-c',script], capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn(f'RESULT|{code}|{runtime}|',result.stdout)
                if case in {'missing','incomplete'}:
                    self.assertIn('accepted compatibility inputs',result.stderr)
                    self.assertIn('do not acquire runtimes',result.stderr)
                if case == 'docker-missing': self.assertIn('PREPARE_ONLY',result.stderr)

    def test_unconfigured_runtime_dispatch_fails_without_execution(self):
        definitions = (ROOT/'detection_funbgcex.sh').read_text()
        for name in ('funbgcex_python_exec', 'run_funbgcex_cli'):
            with self.subTest(function=name):
                script = 'set -eu\n' + definitions + '\nFUNBGCEX_RUNTIME=unconfigured\n' + \
                         'die(){ printf "%s\\n" "$*" >&2; exit 19; }\n' + name + ' /input /output\n'
                completed = subprocess.run(['bash','-c',script],capture_output=True,text=True,timeout=5)
                self.assertEqual(completed.returncode,19)
                self.assertIn('runtime not configured',completed.stderr)

    @unittest.skipUnless(importlib.util.find_spec('Bio'), 'copied worker supplies Biopython')
    def test_actual_cli_routes_resume_force_and_output_statuses(self):
        for scenario in (*SCENARIOS, 'bacteria'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(prefix='full detector CLI ') as tmp:
                root = Path(tmp)
                command, env, result = cli_fixture(root,scenario)
                completed = subprocess.run(command,env=env,cwd='/',capture_output=True,text=True,timeout=20)
                if scenario in {'failed', 'missing', 'empty-file'}:
                    self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                    self.assertIn('Required BGC detection failed', completed.stderr)
                else:
                    self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                rows = list(csv.DictReader((result/'summary_tables/run_manifest.tsv').read_text().splitlines(),delimiter='\t'))
                self.assertEqual(len(rows),1)
                expected = ('not_applicable_taxon' if scenario=='bacteria' else 'skipped_done' if scenario=='skip-done'
                            else 'failed' if scenario in {'failed','missing','empty-file'} else 'ran_ok')
                self.assertEqual(rows[0]['funbgcex_status'],expected)
                self.assertEqual(rows[0]['prediction_method'],'prodigal' if scenario=='bacteria' else 'existing_cds')
                calls = [json.loads(line) for line in (root/'calls.jsonl').read_text().splitlines()] if (root/'calls.jsonl').exists() else []
                self.assertEqual(sum(call['tool']=='funbgcex' for call in calls),0 if scenario in {'skip-done','bacteria'} else 1)
                if scenario=='force': self.assertEqual(rows[0]['gbk_status'],'original_ok')
                if scenario!='bacteria': self.assertEqual((result/'funbgcex/Public/.done').exists(),expected!='failed')

    @unittest.skipUnless(importlib.util.find_spec('Bio'), 'copied worker supplies Biopython')
    def test_actual_cli_cancellation_reaches_detector(self):
        with tempfile.TemporaryDirectory(prefix='cancel detector CLI ') as tmp:
            root = Path(tmp)
            command, env, result = cli_fixture(root,'cancel')
            with (root/'process.log').open('w') as log:
                process = subprocess.Popen(command,env=env,cwd='/',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    deadline=time.monotonic()+10
                    while not (root/'started').exists() and time.monotonic()<deadline and process.poll() is None:
                        time.sleep(.02)
                    self.assertTrue((root/'started').exists(),(root/'process.log').read_text())
                    os.killpg(process.pid,signal.SIGTERM)
                    process.wait(timeout=5)
                    deadline=time.monotonic()+2
                    while not (root/'stopped').exists() and time.monotonic()<deadline: time.sleep(.02)
                    self.assertEqual((root/'stopped').read_text(),'terminated')
                    self.assertNotEqual(process.returncode,0)
                    self.assertFalse((result/'funbgcex/Public/.done').exists())
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
