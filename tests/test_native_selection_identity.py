"""Engine ordinal identities retain legitimate isoforms and reject conflicts."""
import copy
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from native_comparison_selection import record_selection
from native_reporting_view import bind_public_records


class NativeSelectionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'summary').mkdir()
        folder = self.root / 'native_bgc/genome'; folder.mkdir(parents=True)
        self.native = folder / 'cluster.gbk'
        record = SeqRecord(Seq('ATG' * 100), id='record', name='record', description='identity fixture')
        record.annotations['molecule_type'] = 'DNA'
        # Same coordinates/protein and repeated locus identifier; distinct source
        # features. Ordinal 2, not first-hit sequence matching, identifies selection.
        record.features = [SeqFeature(SimpleLocation(0, 90, 1), type='CDS', qualifiers={
            'translation': ['M' * 30], 'protein_id': [p], 'locus_tag': ['repeated']}) for p in ['isoform1', 'isoform2']]
        SeqIO.write(record, self.native, 'genbank')
        self.row = dict(genome_id='genome', region_id='cluster', raw_gbk='genome__cluster',
                        original_record_id='record', native_sha256=hashlib.sha256(self.native.read_bytes()).hexdigest(), stage_sha256='staged')
        self.database = self.root / 'engine.db'
        with sqlite3.connect(self.database) as db:
            db.executescript('CREATE TABLE gbk(id INTEGER,path TEXT,hash TEXT); CREATE TABLE cds(id INTEGER,gbk_id INTEGER,nt_start INTEGER,nt_stop INTEGER,strand INTEGER,aa_seq TEXT,orf_num INTEGER); CREATE TABLE hsp(id INTEGER,cds_id INTEGER,accession TEXT,env_start INTEGER,env_stop INTEGER,bit_score REAL); CREATE TABLE run(label TEXT,end_time TEXT,min_bgc_length INTEGER);')
            db.execute('INSERT INTO gbk VALUES(1,?,?)', ('inputs/genome__cluster.gbk','staged'))
            db.execute('INSERT INTO cds VALUES(1,1,0,90,1,?,2)', ('M'*30,))
        with sqlite3.connect(self.database) as db:db.execute('INSERT INTO run VALUES("run1","completed",0)')
        (self.root/'run1.log').write_text('Starting BiG-SCAPE 2.0.0-beta.6 Cluster run\nAll tasks done\n')
        self.save()

    def save(self):
        (self.root/'summary/native_reporting_keys.json').write_text(json.dumps({'records':[self.row]}))

    def test_identical_isoforms_are_distinct_and_later_selected_ordinal_wins(self):
        row = record_selection(self.root,self.database)['records'][0]
        self.assertEqual([False,True],[f['selected'] for f in row['features']])
        self.assertEqual([2,1,1],[row[k] for k in ['native_cds','selected_cds','excluded_cds']])
        view = bind_public_records({'records':[self.row]},self.database,self.database,self.root)
        self.assertEqual(1,view['records'][0]['runtime_gbk_id'])

    def test_repeated_protein_identifiers_do_not_replace_ordinal_identity(self):
        r=SeqIO.read(self.native,'genbank');r.features[1].qualifiers['protein_id']=['isoform1'];SeqIO.write(r,self.native,'genbank')
        self.row['native_sha256']=hashlib.sha256(self.native.read_bytes()).hexdigest();self.save()
        self.assertTrue(record_selection(self.root,self.database)['records'][0]['features'][1]['selected'])

    def test_conflicting_content_rejected_with_record_and_candidate(self):
        with sqlite3.connect(self.database) as db:db.execute('UPDATE cds SET nt_start=1')
        with self.assertRaisesRegex(ValueError,'record=record.*cluster=cluster.*ordinal/content conflict'):
            record_selection(self.root,self.database)

    def test_duplicate_selected_ordinal_rejected(self):
        with sqlite3.connect(self.database) as db:db.execute('INSERT INTO cds SELECT 2,gbk_id,nt_start,nt_stop,strand,aa_seq,orf_num FROM cds')
        with self.assertRaisesRegex(ValueError,'ambiguous selected CDS ordinal'):record_selection(self.root,self.database)

    def test_missing_or_out_of_range_ordinal_rejected(self):
        for value in [None,0,3]:
            with self.subTest(value=value):
                with sqlite3.connect(self.database) as db:db.execute('UPDATE cds SET orf_num=?',(value,))
                with self.assertRaisesRegex(ValueError,'CDS ordinal'):record_selection(self.root,self.database)

    def test_duplicate_gbk_rejected(self):
        with sqlite3.connect(self.database) as db:db.execute('INSERT INTO gbk VALUES(2,?,?)',('elsewhere/genome__cluster.gbk','staged'))
        with self.assertRaisesRegex(ValueError,'ambiguous engine GBK'):record_selection(self.root,self.database)

    def test_stale_stage_hash_rejected(self):
        with sqlite3.connect(self.database) as db:db.execute('UPDATE gbk SET hash="wrong"')
        with self.assertRaisesRegex(ValueError,'staged input'):record_selection(self.root,self.database)

    def excluded(self,maximum):
        with sqlite3.connect(self.database) as db:
            db.execute('DELETE FROM gbk')
        (self.root/'run1.config.log').write_text(f'MIN_BGC_LENGTH: 0\nMAX_BGC_LENGTH: {maximum}\n')
        (self.root/'run1.log').write_text(f'Starting BiG-SCAPE 2.0.0-beta.6 Cluster run\nAll tasks done\nGBKs remain after length constraint of min 0 to max {maximum} bp')

    def test_length_exclusion_preserves_all_native_features_and_no_public_id(self):
        self.excluded(300)  # strict upper boundary, as in the actual engine
        result=record_selection(self.root,self.database)['records'][0]
        self.assertEqual('excluded_length',result['comparison_status']);self.assertEqual(2,result['native_cds'])
        self.assertIsNone(result['raw_gbk_id'])
        result=bind_public_records({'records':[self.row]},self.database,self.database,self.root)['records'][0]
        self.assertIsNone(result['public_gbk']);self.assertEqual(300,result['comparison_exclusion']['length_bp'])

    def test_unexplained_missing_record_still_rejected(self):
        self.excluded(301)
        with self.assertRaisesRegex(ValueError,'inside admitted length range'):record_selection(self.root,self.database)

    def test_unproven_exclusion_rejected(self):
        self.excluded(300);(self.root/'run1.log').write_text('Starting BiG-SCAPE 2.0.0-beta.6 Cluster run\nAll tasks done\nunrelated')
        with self.assertRaisesRegex(ValueError,'not corroborated'):record_selection(self.root,self.database)

    def test_unknown_engine_contract_rejected(self):
        (self.root/'run1.log').write_text('Starting BiG-SCAPE unknown Cluster run\nAll tasks done\n')
        with self.assertRaisesRegex(ValueError,'Unproven native CDS ordinal contract'):record_selection(self.root,self.database)

    def test_missing_translation_rejects_ordinal_inference(self):
        r=SeqIO.read(self.native,'genbank');del r.features[0].qualifiers['translation'];SeqIO.write(r,self.native,'genbank')
        self.row['native_sha256']=hashlib.sha256(self.native.read_bytes()).hexdigest();self.save()
        with self.assertRaisesRegex(ValueError,'ordinal contract unavailable'):record_selection(self.root,self.database)


if __name__=='__main__':unittest.main()
