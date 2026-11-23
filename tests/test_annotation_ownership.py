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
from test_funbgcex_extraction import cli_fixture


PREPARATION_CASES = ('staged', 'original', 'original-copy', 'missing', 'untranslated',
                     'funannotate', 'braker3', 'fallback-failed', 'bad-fallback',
                     'bacteria', 'bacteria-fasta', 'bacteria-missing', 'sanitize-failed', 'stage-failed')
TOOL_CASES = ('funannotate', 'clean-fails', 'fun-gff', 'fun-fails', 'fun-bad-output',
              'retry', 'braker3', 'braker-no-gff', 'braker-bad-gff', 'fallback-braker-fun',
              'disabled-braker', 'missing-evidence')


def preparation_fixture(root: Path, case: str, definitions: str | None = None):
    root.mkdir(parents=True, exist_ok=True)
    source=root/'source.gbk'; fasta=root/'input.fa'; staged=root/'staged.gbk'; work=root/'work'; work.mkdir()
    if case not in {'missing','bacteria-missing'}: fasta.write_text('>Public\nATG\n')
    if case in {'staged','original','original-copy','bacteria','stage-failed','sanitize-failed'}: source.write_text('translated\n')
    if case=='staged': staged.write_text('translated\n')
    if case=='untranslated': source.write_text('no translation\n');fasta.unlink()
    definitions=definitions if definitions is not None else (ROOT/'annotation_prepare.sh').read_text()
    script='set -euo pipefail\n'+definitions+'\n'+f'''
CASE={shlex.quote(case)}
RESULTS_ROOT={shlex.quote(str(root/'results'))}
SCRIPT_DIR={shlex.quote(str(ROOT))}
GENOME_TAXON_MANIFEST=/unused
BACTERIAL_GENBANK_SANITIZER=/unused
ANTISMASH_MIN_RECORD_BP=1
ANTISMASH_MAX_RECORD_BP=10000
FORCE=0
ANNOTATION_FALLBACK_ORDER=braker3,funannotate
ANNOTATION_FALLBACK_FAILURE_REASON=
ANNOTATION_FALLBACK_FAILURE_DETAIL=
log() {{ printf 'LOG|%s\\n' "$*"; }}
warn() {{ printf 'WARN|%s\\n' "$*" >&2; }}
genome_stage_progress() {{ printf 'PROGRESS|%s\\n' "$*"; }}
genome_annotation_decision() {{ printf 'DECISION|%s\\n' "$*"; }}
gbk_has_cds_and_translation() {{ [[ -s "$1" && "$(cat "$1")" == translated ]]; }}
normalize_gbk_record_headers_in_place() {{ :; }}
prepare_original_fungal_genbank() {{ [[ "$CASE" != original-copy ]] && command cp -f "$1" "$2"; }}
resolve_python_cmd() {{ printf python; }}
bacterial_genbank_prepare() {{
  [[ "$CASE" != sanitize-failed ]] || return 7
  shift 5
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --output|--record-map|--record-ids) mkdir -p "$(dirname "$2")"; printf 'prepared\\n' > "$2" ;;
    esac
    shift 2
  done
  printf 'sanitized\\n'
}}
cp() {{ [[ "$CASE" != stage-failed ]] && command cp "$@"; }}
annotate_genome_with_fallbacks() {{
  case "$CASE" in
    fallback-failed) ANNOTATION_FALLBACK_FAILURE_REASON=funannotate_busco_training_insufficient; ANNOTATION_FALLBACK_FAILURE_DETAIL='145 below 150'; return 1 ;;
    bad-fallback) ANNOTATION_FALLBACK_METHOD=funannotate; printf 'no translation\\n' > "$3" ;;
    *) ANNOTATION_FALLBACK_METHOD="$CASE"; printf 'translated\\n' > "$3" ;;
  esac
}}
run_case() {{
  local gbk_used= gbk_status= prediction_method=custom ant_input= antismash_record_ids_file= antismash_input_sanitized=0
  local group=fungi
  [[ "$CASE" != bacteria* && "$CASE" != sanitize-failed && "$CASE" != stage-failed ]] || group=bacteria
  local src={shlex.quote(str(source))} fa={shlex.quote(str(fasta))}
  [[ -f "$src" ]] || src=
  [[ -f "$fa" ]] || fa=
  prepare_genome_genbank Public "$group" {shlex.quote(str(root))} "$fa" "$src" \\
    {shlex.quote(str(staged))} {shlex.quote(str(work))} {shlex.quote(str(root/'genome.log'))}
  printf '%s\\t%s\\t%s\\t%s\\t%s\\t%s\\n' "$gbk_used" "$gbk_status" "$prediction_method" \\
    "$ant_input" "$antismash_record_ids_file" "$antismash_input_sanitized" > {shlex.quote(str(root/'state.tsv'))}
}}
run_case
'''
    return subprocess.run(['bash','-c',script],capture_output=True,text=True,timeout=10)


def annotation_cli_fixture(root: Path, case: str, source_root: Path=ROOT):
    command,env,result=cli_fixture(root,'success',source_root)
    original=root/'fungal inputs/Public.gbk'
    (root/'fixture.gbk').write_bytes(original.read_bytes());original.unlink()
    (root/'fungal inputs/Public.fa').write_text('>Public\n'+'ATG'*400+'\n')
    manifest=result/'summary_tables/genome_taxon_manifest.tsv'
    manifest.write_text(manifest.read_text().replace('\texisting_cds\t','\tfunannotate\t'))
    protein=root/'proteins.fa';protein.write_text('>protein\n'+'M'*400+'\n')
    order='braker3' if case in {'braker3','braker-no-gff','braker-bad-gff','missing-evidence'} else 'braker3,funannotate' if case in {'fallback-braker-fun','disabled-braker'} else 'funannotate'
    env.update(ANNOTATION_FALLBACK_ORDER=order,BRAKER3_ENABLED='0' if case=='disabled-braker' else '1',
               BRAKER_PROT_SEQ='' if case=='missing-evidence' else str(protein),BRAKER_BAM='',
               FUNANNOTATE_IMAGE_URI='docker://fixture-funannotate:stub',BRAKER_IMAGE_URI='docker://fixture-braker:stub',
               FUNANNOTATE_BUSCO_DB='fungi',FUNANNOTATE_BUSCO_SEED_SPECIES='rhizopus_oryzae',
               FUNANNOTATE_ORGANISM_NAME='Fixture fungus',FUNANNOTATE_RETRY_WITHOUT_PROTEIN_EVIDENCE='1',
               FUNANNOTATE_MIN_TRAINING_MODELS_FALLBACK='150',OWNERSHIP_CASE=case,OWNERSHIP_ROOT=str(root))
    docker=root/'stub tools/docker'
    docker.write_text('''#!/usr/bin/env python3
import json, os, pathlib, shutil, signal, sys, time
args=sys.argv[1:]
if args[:2]==['image','inspect']:raise SystemExit(0)
assert args[0]=='run',args
images={'fixture-funbgcex:stub':'funbgcex','fixture-funannotate:stub':'funannotate','fixture-braker:stub':'braker3'}
index=next(i for i,a in enumerate(args) if a in images)
tool=images[args[index]]; command=args[index+1:];root=pathlib.Path(os.environ['OWNERSHIP_ROOT']);case=os.environ['OWNERSHIP_CASE']
with open(os.environ['N1_CALLS'],'a') as f:f.write(json.dumps({'tool':tool,'argv':args})+'\\n')
gff='##gff-version 3\\nPublic\\tstub\\tgene\\t1\\t1200\\t.\\t+\\t.\\tID=gene1\\nPublic\\tstub\\tmRNA\\t1\\t1200\\t.\\t+\\t.\\tID=mrna1;Parent=gene1\\nPublic\\tstub\\tCDS\\t1\\t1200\\t.\\t+\\t0\\tID=cds1;Parent=mrna1\\n'
if tool=='funbgcex':
 out=pathlib.Path(command[2]);out.mkdir(parents=True,exist_ok=True)
 (out/'allBGCs.csv').write_text('BGC no.,Scaffold,Start position,End position,Core enzymes\\n');raise SystemExit(0)
if tool=='funannotate':
 if command[0]=='sh':raise SystemExit(0)
 operation=command[1];output=pathlib.Path(command[command.index('-o')+1])
 if operation in {'sort','clean'}:
  if operation=='clean' and case=='clean-fails':raise SystemExit(2)
  shutil.copyfile(command[command.index('-i')+1],output);raise SystemExit(0)
 assert operation=='predict',command
 if case=='cancel':
  def stop(*unused):
   pathlib.Path(os.environ['N1_STOPPED']).write_text('terminated');raise SystemExit(143)
  signal.signal(signal.SIGTERM,stop);pathlib.Path(os.environ['N1_STARTED']).write_text(str(os.getpid()))
  while True:time.sleep(.1)
 counter=root/'attempt';n=int(counter.read_text())+1 if counter.exists() else 1;counter.write_text(str(n))
 if case=='fun-fails' or case=='retry' and n==1:
  count=145 if case=='fun-fails' else 186
  print(f'{count} BUSCO predictions validated',flush=True);print(f'ERROR: Not enough gene models {count} to train Augustus (200 required), exiting',flush=True);time.sleep(.1);raise SystemExit(2)
 if case=='retry' and n==2:
  print('CMD ERROR: diamond blastx --query proteins.fa --db uniprot.dmnd',flush=True);time.sleep(.1);raise SystemExit(2)
 out=output/'predict_results';out.mkdir(parents=True,exist_ok=True)
 if case=='fun-gff':(out/'Public.gff3').write_text(gff)
 elif case=='fun-bad-output':(out/'Public.gbk').write_text('LOCUS broken\\n//\\n')
 else:shutil.copyfile(root/'fixture.gbk',out/'Public.gbk')
 raise SystemExit(0)
assert tool=='braker3',tool
if case=='fallback-braker-fun':raise SystemExit(2)
out=pathlib.Path(command[command.index('--workingdir')+1]);out.mkdir(parents=True,exist_ok=True)
if case!='braker-no-gff':(out/'braker.gff3').write_text('invalid GFF\\n' if case=='braker-bad-gff' else gff)
''')
    docker.chmod(0o755)
    return command,env,result


class AnnotationOwnershipTests(unittest.TestCase):
    def test_preparation_updates_existing_caller_outputs(self):
        statuses={'staged':'staged_ok','original':'original_ok','original-copy':'original_ok',
                  'missing':'no_fasta_for_annotation','untranslated':'no_fasta_for_annotation',
                  'funannotate':'funannotate_fixed','braker3':'braker3_fixed',
                  'fallback-failed':'funannotate_busco_training_insufficient','bad-fallback':'funannotate_no_translations',
                  'bacteria':'bacterial_sequence_sanitized','bacteria-fasta':'bacterial_sequence_sanitized',
                  'bacteria-missing':'no_bacterial_sequence_input','sanitize-failed':'bacterial_sanitizer_failed',
                  'stage-failed':'bacterial_staging_failed'}
        for case in PREPARATION_CASES:
            with self.subTest(case=case),tempfile.TemporaryDirectory(prefix='prepare inputs ') as tmp:
                root=Path(tmp);completed=preparation_fixture(root,case)
                self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
                fields=(root/'state.tsv').read_text().strip('\n').split('\t')
                self.assertEqual(fields[1],statuses[case])
                if case in {'staged','original','original-copy'}:self.assertEqual(fields[2],'existing_cds')
                if case=='bad-fallback':self.assertFalse((root/'staged.gbk').exists())
                if case in {'bacteria','bacteria-fasta'}:self.assertEqual(fields[-1],'1')

    def test_annotation_adapters_preserve_environment_and_exit_status(self):
        text=annotation_source();definitions='\n'.join(shell_function(text,n) for n in ('funannotate_exec','funannotate_exec_with_activity','braker3_exec'))
        script='set -eu\n'+definitions+'''
ANNO_CPUS=4
FUNANNOTATE_IMAGE_URI=docker://fixture/fun
BRAKER_IMAGE_URI=docker://fixture/braker
FUNANNOTATE_SIF=/etc/hosts
BRAKER_SIF=/etc/hosts
docker_image_from_uri(){ printf '%s' "${1#docker://}"; }
docker_exec(){ printf 'docker|%s' "$CLUSTERWEAVE_CHILD_DOCKER_CPUS"; printf '|%s' "$@"; return 71; }
sing_exec(){ printf 'sif'; printf '|%s' "$@"; return 73; }
native_tool(){ printf 'host'; printf '|%s' "$@"; return 75; }
run_tool_with_activity(){ shift 5; "$@"; }
probe(){ local rc=0; "$@" || rc=$?; printf '|rc=%s\\n' "$rc"; }
ENGINE=docker
probe funannotate_exec 1 0 native_tool predict 'path with spaces'
probe braker3_exec native_tool 'path with spaces'
probe funannotate_exec_with_activity 1 0 Public /log native_tool predict
ENGINE=apptainer
probe funannotate_exec 0 1 native_tool predict
probe braker3_exec native_tool predict
probe funannotate_exec_with_activity 0 1 Public /log native_tool predict
BRAKER_SIF=/missing
probe funannotate_exec 0 0 native_tool predict
probe braker3_exec native_tool predict
probe funannotate_exec_with_activity 0 0 Public /log native_tool predict
'''
        completed=subprocess.run(['bash','-c',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(completed.returncode,0,completed.stderr)
        rows=completed.stdout.splitlines();self.assertEqual(len(rows),9)
        for row in rows[:3]:self.assertTrue(row.startswith('docker|4|'));self.assertTrue(row.endswith('rc=71'))
        for row in rows[3:6]:self.assertTrue(row.startswith('sif|'));self.assertTrue(row.endswith('rc=73'))
        for row in rows[6:]:self.assertTrue(row.startswith('host|'));self.assertTrue(row.endswith('rc=75'))

    @unittest.skipUnless(importlib.util.find_spec('Bio'),'copied worker supplies Biopython')
    def test_actual_annotation_tools_fallback_retries_and_conversion(self):
        successful={'funannotate','clean-fails','fun-gff','retry','braker3','fallback-braker-fun','disabled-braker'}
        for case in TOOL_CASES:
            with self.subTest(case=case),tempfile.TemporaryDirectory(prefix='annotation tools ') as tmp:
                root=Path(tmp);command,env,result=annotation_cli_fixture(root,case)
                completed=subprocess.run(command,env=env,cwd='/',capture_output=True,text=True,timeout=30)
                self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
                rows=list(csv.DictReader((result/'summary_tables/run_manifest.tsv').read_text().splitlines(),delimiter='\t'))
                self.assertEqual(len(rows),1)
                if case in successful:
                    self.assertEqual(rows[0]['gbk_status'],'braker3_fixed' if case=='braker3' else 'funannotate_fixed')
                    self.assertTrue((result/'input_gbks/Public.gbk').is_file())
                    self.assertEqual(rows[0]['funbgcex_status'],'ran_ok')
                else:self.assertEqual(rows[0]['funbgcex_status'],'skipped')
                calls=[json.loads(line) for line in (root/'calls.jsonl').read_text().splitlines()] if (root/'calls.jsonl').exists() else []
                if case=='retry':
                    predict=[c for c in calls if c['tool']=='funannotate' and 'predict' in c['argv']]
                    self.assertEqual(len(predict),3)
                    self.assertNotIn('--min_training_models',predict[0]['argv'])
                    self.assertIn('--min_training_models',predict[1]['argv'])
                    self.assertIn('--protein_alignments',predict[2]['argv'])
                if case=='disabled-braker':self.assertFalse(any(c['tool']=='braker3' for c in calls))

    @unittest.skipUnless(importlib.util.find_spec('Bio'),'copied worker supplies Biopython')
    def test_annotation_prediction_cancellation_reaches_tool(self):
        with tempfile.TemporaryDirectory(prefix='cancel annotation ') as tmp:
            root=Path(tmp);command,env,result=annotation_cli_fixture(root,'cancel')
            with (root/'process.log').open('w') as log:
                process=subprocess.Popen(command,env=env,cwd='/',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    deadline=time.monotonic()+10
                    while not (root/'started').exists() and time.monotonic()<deadline and process.poll() is None:time.sleep(.02)
                    self.assertTrue((root/'started').exists(),(root/'process.log').read_text())
                    os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=5)
                    deadline=time.monotonic()+2
                    while not (root/'stopped').exists() and time.monotonic()<deadline:time.sleep(.02)
                    self.assertEqual((root/'stopped').read_text(),'terminated')
                    self.assertNotEqual(process.returncode,0)
                    self.assertFalse((result/'input_gbks/Public.gbk').exists())
                finally:
                    if process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)


if __name__=='__main__':unittest.main()
