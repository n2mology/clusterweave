"""Final presentation/export and retrieval validation regressions."""
from pathlib import Path
import copy
import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'bin'), str(ROOT/'web')]
import cached_accession as adapter
from test_cached_accession import identity


class RetrievalStartupTests(unittest.TestCase):
    def test_snapshot_validation_reuses_only_exact_bytes_and_identity(self):
        ident = identity(snapshot=True)
        payload = {'bundle.tar': b'first'}
        verify = adapter.snapshot_validator(ident)
        with mock.patch.object(adapter, 'validate_bundle', side_effect=[{'v': 1}, {'v': 2}, {'v': 3}]) as check:
            self.assertEqual(verify(payload), {'v': 1})
            self.assertEqual(verify(dict(payload)), {'v': 1})
            payload['bundle.tar'] = b'second'
            self.assertEqual(verify(payload), {'v': 2})
            ident['source_sha256'] = 'a'*64
            self.assertEqual(verify(payload), {'v': 3})
            self.assertEqual(check.call_count, 3)
        with mock.patch.object(adapter, 'validate_bundle') as check:
            adapter.snapshot_validator(ident)(payload)
            self.assertEqual(check.call_count, 1)

    def test_failed_validation_is_never_reused(self):
        verify = adapter.snapshot_validator(identity(snapshot=True))
        with mock.patch.object(adapter, 'validate_bundle', side_effect=ValueError('bad')) as check:
            for _ in range(2):
                with self.assertRaises(ValueError): verify({'bundle.tar': b'invalid'})
            self.assertEqual(check.call_count, 2)
        with self.assertRaises(adapter.Unavailable): verify({'bundle.tar': bytearray(b'mutable')})

    def test_fast_snapshot_compression_preserves_all_members(self):
        files = {'ncbi_dataset/data/genome.fna': b'>chr\n'+b'ACGT'*10000+b'\n',
                 'ncbi_dataset/data/record.gbff': b'LOCUS public\n'+b'annotations\n'*10000}
        slow = adapter.pack(files)
        fast = adapter.pack(files, compression_level=1)
        self.assertNotEqual(slow, fast)
        self.assertEqual(adapter.unpack(slow), files)
        self.assertEqual(adapter.unpack(fast), files)
        self.assertEqual(adapter.pack(dict(reversed(list(files.items()))), compression_level=1), fast)


class ClinkerExportTests(unittest.TestCase):
    def test_reprocessed_export_removes_heading_and_redundancy_preserving_science(self):
        payload = {'clusters': [{'name': str(i), 'loci': [{'name': 'scaffold', 'genes': []}], 'sequence': 'ACGT'} for i in range(2)], 'links': [], 'groups': []}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);html=root/'panel.html';manifest=root/'panel_manifest.tsv'
            html.write_text('<body><section id="clusterweave-panel-provenance"><strong>Locus comparison.</strong><ul><li>private identity</li></ul></section><style></style><script>const data='+json.dumps(payload)+';function serialise(){}\n  d3.select("#btn-save-svg")</script></body>')
            rows=[{'order':str(i+1),'role':'target' if i==0 else 'comparator','genome':'Fungus_strain','organism_name':'Fungus strain','antismash_region':f'NW_001.region00{i+1}','scaffold_id':'NW_001'} for i in range(2)]
            with manifest.open('w') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter='\t');writer.writeheader();writer.writerows(rows)
            for _ in range(2):
                subprocess.run([sys.executable,'-B',str(ROOT/'bin/postprocess_clinker_html.py'),'--html',str(html),'--manifest',str(manifest)],check=True,capture_output=True)
            text=html.read_text();self.assertNotIn('clusterweave-panel-provenance',text)
            result=json.loads(text.split('const data=',1)[1].split(';function serialise',1)[0])
            self.assertEqual([c['name'] for c in result['clusters']],['Fungus strain']*2)
            self.assertEqual([c['loci'][0]['name'] for c in result['clusters']],['NW 001.region001','NW 001.region002'])
            self.assertEqual([c['sequence'] for c in result['clusters']],['ACGT']*2)
            self.assertEqual(result['links'],payload['links'])
            self.assertEqual(text.count('function layoutClusterWeaveLabels()'),1)
            self.assertIn('drawing.x + drawing.width + 60 - box.x',text)
            self.assertNotIn('drawing.y + drawing.height + 48',text)



class FunannotateWorkingDirectoryTests(unittest.TestCase):
    def test_sif_dispatch_explicitly_passes_working_directory_with_exact_argv(self):
        from annotation_source import annotation_source, shell_function
        helper=shell_function(annotation_source(),'sing_exec')
        script="""set -euo pipefail
ENGINE=probe_engine
BIND_ARGS=(--bind '/bound source:/bound target')
probe_engine(){ printf '%s\\n' "$@"; return 17; }
"""+helper+"""
rc=0
CLUSTERWEAVE_CHILD_SIF_WORKDIR='/work with spaces/genome' sing_exec '/prepared image.sif' /venv/bin/python -c pass || rc=$?
[[ "$rc" == 17 ]]
"""
        result=subprocess.run(['bash','-c',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.splitlines(),['exec','--pwd','/work with spaces/genome','--bind','/bound source:/bound target','/prepared image.sif','/venv/bin/python','-c','pass'])

    def test_all_backend_dispatches_use_genome_workdir_keep_argv_and_exit(self):
        from annotation_source import annotation_source, shell_function
        source=annotation_source()
        with tempfile.TemporaryDirectory(prefix='funannotate cwd ') as temporary:
            folder=Path(temporary)/'genome work';folder.mkdir()
            helper=shell_function(source,'funannotate_exec')+'\n'+shell_function(source,'funannotate_exec_with_activity')
            script=r'''set -euo pipefail
fun_work_cwd="$1"
ANNO_CPUS=2
FUNANNOTATE_SIF=/prepared/fun.sif
FUNANNOTATE_IMAGE_URI=docker://prepared/fun:1
probe(){ [[ "$PWD" == "$fun_work_cwd" ]] || exit 90; mkdir relative_scratch; rmdir relative_scratch; printf '%s\n' "$@"; return 17; }
sing_exec(){ shift; probe "$@"; }
docker_exec(){ shift; [[ "$CLUSTERWEAVE_CHILD_DOCKER_WORKDIR" == "$fun_work_cwd" ]] || exit 91; probe "$@"; }
docker_image_from_uri(){ printf '%s' "${1#docker://}"; }
run_tool_with_activity(){ shift 5; "$@"; }
'''+helper+r'''
for backend in '0 0' '0 1' '1 0'; do
 set -- $backend
 rc=0; funannotate_exec_with_activity "$1" "$2" Genome /unused/log probe 'input with spaces' --cpus 2 || rc=$?
 [[ "$rc" == 17 ]] || exit 92
done
'''
            result=subprocess.run(['bash','-c',script,'test',str(folder)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.splitlines(),['input with spaces','--cpus','2']+['probe','input with spaces','--cpus','2']*2)

if __name__ == '__main__': unittest.main()
