"""Record collector regressions; native scientific equivalence is exercised separately."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'bin'), str(Path(__file__).parent)]
from Bio import SeqIO
import plantismash_native as native
import plantismash_shards as shards
import test_plantismash_native as fixtures


class PlantRecordMergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name);self.results = {};records=[];raw=[]
        for ordinal in [1,2]:
            fixture=fixtures.ExtractedNativeTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
            record=fixture.record;record.id=record.name='plant_'+str(ordinal)
            fixture.record=record;fixture.cluster=record[100:900]
            SeqIO.write(record,fixture.folder/'plant.final.gbk','genbank')
            old=fixture.original['records'][0];old['original_id']=record.id;old['original_record_ordinal']=ordinal
            old['CDS'][0]['feature_key']=f'genome:R{ordinal}:F1'
            c=json.loads((fixture.folder/'native-completion.json').read_text());c['records'][0].update(original_id=record.id,native_id=record.id);c['evaluated_records']=[record.id]
            (fixture.folder/'native-completion.json').write_text(json.dumps(c));fixture.repack()
            child=self.root/'shards'/f'{ordinal:06d}';shutil.copytree(fixture.root,child)
            source=record.format('genbank').encode();raw.append(source);(child/'original.gbk').write_bytes(source)
            inventory={'records':[old],'source_file_sha256':hashlib.sha256(source).hexdigest()}
            (child/'original-identity.json').write_text(json.dumps(inventory));(child/'execution.json').write_text(json.dumps({'producer':native.PRODUCER,'profile_id':native.LEGACY_PROFILE}))
            self.results[ordinal]=native.read_native(inventory,child/'native');self.assertTrue(self.results[ordinal]['valid'])
            records.append(old)
        (self.root/'original.gbk').write_bytes(b''.join(raw))
        self.original={'records':records,'source_file_sha256':shards.sha(self.root/'original.gbk')}
        (self.root/'original-identity.json').write_text(json.dumps(self.original))
        shards.merge(self.original,self.root,self.results)
    def check(self):return native.read_native(self.original,self.root/'native')
    def test_complete_ordered_join_retains_both_native_outputs(self):
        result=self.check();self.assertTrue(result['valid'],result);self.assertEqual(len(result['calls']),2)
        self.assertEqual([r['original_id'] for r in result['identity']['records']],['plant_1','plant_2'])
        self.assertTrue(all(c['native_cluster_gbk'].startswith('r00000') for c in result['calls']))
        self.assertEqual(len(list((self.root/'native/shards').glob('*/native/native-completion.json'))),2)
    def test_mixed_profile_children_refuse_genome_even_with_updated_hashes(self):
        folder=self.root/'native';p=folder/'shards/000001/execution.json'
        p.write_text(json.dumps({'producer':native.PRODUCER,'profile_id':native.PROFILE,'profile_sha256':native.PROFILE_SHA256}))
        receipt=json.loads((folder/'native-completion.json').read_text())
        receipt['shards'][0]['evidence']['execution.json']=shards.sha(p)
        (folder/'native-completion.json').write_text(json.dumps(receipt));shards.pack(folder)
        self.assertFalse(self.check()['valid'])

    def test_failed_native_child_refuses_genome_even_with_repacked_outer_archive(self):
        p=self.root/'native/shards/000001/native-exit.json';p.write_text(json.dumps({'exit_code':17,'producer':native.PRODUCER}))
        self.assertFalse(self.check()['valid'])
    def test_missing_native_child_refuses_genome(self):
        shutil.rmtree(self.root/'native/shards/000002');self.assertFalse(self.check()['valid'])
    def test_reordered_shards_refuse_genome(self):
        p=self.root/'native/native-completion.json';r=json.loads(p.read_text());r['shards'].reverse();p.write_text(json.dumps(r));self.assertFalse(self.check()['valid'])
    def test_original_record_substitution_is_rejected(self):
        p=self.root/'original.gbk';p.write_bytes(p.read_bytes().replace(b'aaaaaaaaaa',b'cccccccccc',1));self.assertFalse(self.check()['valid'])
    def test_merged_cluster_substitution_is_rejected(self):
        p=next((self.root/'native').glob('r*.cluster*.gbk'));p.write_bytes(p.read_bytes()+b'corrupt');self.assertFalse(self.check()['valid'])
    def test_successful_empty_child_is_retained_and_not_missing(self):
        # The original native contract already distinguishes zero calls from
        # missing output; all children, including empty ones, must have receipts.
        receipt=json.loads((self.root/'native/native-completion.json').read_text())
        receipt['shards'].pop();(self.root/'native/native-completion.json').write_text(json.dumps(receipt));self.assertFalse(self.check()['valid'])


class ShardSchedulerFailureTests(unittest.TestCase):
    def test_failed_record_terminates_and_reaps_active_native_process_group(self):
        import argparse,os,time
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'input.gbk';source.write_bytes(b'one\n//\ntwo\n//\n')
            original={'records':[{'original_record_ordinal':i,'CDS':[{}]} for i in [1,2]],'source_file_sha256':shards.sha(source)}
            args=argparse.Namespace(input=source,record_parallelism=2,cpus=1)
            def factory(child,source,inventory):
                if child.name=='000001':code='import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);Path('+repr(str(root/'descendant.pid'))+').write_text(str(p.pid));time.sleep(30)'
                else:code='import time;time.sleep(.3);raise SystemExit(17)'
                return [sys.executable,'-c',code],os.environ.copy()
            start=time.monotonic()
            with self.assertRaisesRegex(ValueError,'exited 17'):
                shards.execute(args,original,root,factory)
            self.assertLess(time.monotonic()-start,5)
            state=json.loads((root/'shard-execution.json').read_text());pids=[r['pid'] for r in state['events'] if r['state']=='running']
            for pid in pids:
                with self.assertRaises(ProcessLookupError):os.kill(pid,0)
            child_pid=int((root/'descendant.pid').read_text())
            deadline=time.monotonic()+3
            while Path('/proc/'+str(child_pid)).exists() and time.monotonic()<deadline:time.sleep(.05)
            self.assertFalse(Path('/proc/'+str(child_pid)).exists(), 'Native descendant survived cancellation')
            self.assertFalse((root/'native').exists())
