"""Native report assembly retains data and distinguishes empty/unevaluated records."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'bin'),str(ROOT/'web')]
from plantismash_assembly import assemble, payload, Document
from plant_identity import PUBLIC_PRODUCER, LEGACY_PRODUCER, matching_producers

class NativeAssemblyTests(unittest.TestCase):
    def fixture(self, root):
        records=[];shards=[]
        for i, calls in [(1,1),(2,1),(3,0)]:
            rid=f'R{i}.1'; records.append({'original_record_ordinal':i,'original_id':rid,'CDS':[{}]})
            shards.append({'ordinal':i,'root':f'shards/{i:06d}'})
            native=root/'native'/shards[-1]['root']/'native';native.mkdir(parents=True)
            (native/'css').mkdir();(native/'css/style.css').write_text('body { color: black; }')
            (native/'svg').mkdir();(native/'svg/cluster.svg').write_text(f'<svg>record {i}</svg>')
            (native/'geneclusters.js').write_text('var geneclusters = '+json.dumps({'cluster-1':{'idx':1,'start':10,'end':20,'orfs':[],'domains':[],'substrates':[],'cdhitclusters':[]}} if calls else {})+'; var details_data = {};')
            (native/f'{rid}.cluster001.gbk').write_text(f'original cluster {i}')
            (native/'index.html').write_text('<html><head><title>native</title></head><body><ul id="downloadoptions"></ul><ul id="clusterbuttons"><li><a href="#">Overview</a></li>'+('<li><a href="#cluster-1">1</a></li>' if calls else '')+'</ul><div id="overview"><table id="cluster-overview"><tbody>'+('<tr class="separator-row"><td>from record '+rid+'</td></tr><tr><td><a href="#cluster-1">Cluster 1</a></td></tr>' if calls else '<tr><td colspan="2">No clusters</td></tr>')+'</tbody></table></div>'+('<div id="cluster-1" class="page"><a href="'+rid+'.cluster001.gbk">Download</a><select id="clusterblast-1-select"><option value="svg/cluster.svg">match</option></select></div>' if calls else '')+'<div id="footer"></div><script src="geneclusters.js"></script></body></html>')
        records.append({'original_record_ordinal':4,'original_id':'R4.1','CDS':[]})
        (root/'original-identity.json').write_text(json.dumps({'records':records,'source_file_sha256':'a'*64}))
        (root/'execution.json').write_text(json.dumps({'sif_sha256':'b'*64}))
        (root/'native/native-completion.json').write_text(json.dumps({'shards':shards}))
        (root/'native/records.final.gbk').write_text('unchanged combined records')

    def test_combined_navigation_scientific_parity_and_collisions(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'Plant';root.mkdir();self.fixture(root);out=Path(t)/'export'
            result=assemble(root,out);self.assertEqual((result['calls'],result['analyzed'],result['not_evaluated']),(2,3,1))
            data,_=payload(out/'geneclusters.js');self.assertEqual(data['cluster-2']['start'],10)
            doc=Document((out/'index.html').read_text()).root
            self.assertEqual(doc.byid('clusterblast-2-select').children[0].attrs['value'],'svg/R2.1/cluster.svg')
            self.assertEqual((out/'R2.1.cluster001.gbk').read_text(),'original cluster 2')
            self.assertEqual((out/'records.final.gbk').read_text(),'unchanged combined records')
            p=json.loads((out/'provenance.json').read_text());self.assertEqual(p['producer'],PUBLIC_PRODUCER)
            self.assertEqual([r['calls'] for r in p['records']],[1,1,0,None])
            self.assertFalse(list(out.rglob('*.zip')))
            self.assertEqual(len(p['shared_assets_exact_duplicates']),2)

    def test_nonidentical_shared_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'Plant';root.mkdir();self.fixture(root)
            (root/'native/shards/000002/native/css/style.css').write_text('changed template')
            with self.assertRaisesRegex(ValueError,'shared asset collision'):assemble(root,Path(t)/'export')

    def test_empty_analyzed_records_remain_distinct_from_no_cds(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'Plant';root.mkdir();self.fixture(root)
            for native in (root/'native/shards').glob('*/native'):
                (native/'geneclusters.js').write_text('var geneclusters = {}; var details_data = {};')
            out=Path(t)/'export';result=assemble(root,out)
            self.assertEqual((result['calls'],result['analyzed'],result['not_evaluated']),(0,3,1))
            records=json.loads((out/'provenance.json').read_text())['records']
            self.assertEqual([r['calls'] for r in records],[0,0,0,None])
            self.assertEqual(payload(out/'geneclusters.js'),({},{}))

    def test_single_native_report_uses_the_same_public_directory(self):
        import shutil
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'Plant';root.mkdir();self.fixture(root)
            identity=json.loads((root/'original-identity.json').read_text())
            identity['records']=[identity['records'][0],identity['records'][-1]]
            (root/'original-identity.json').write_text(json.dumps(identity))
            for item in (root/'native/shards/000001/native').iterdir():
                if item.is_dir():shutil.copytree(item,root/'native'/item.name)
                else:shutil.copyfile(item,root/'native'/item.name)
            shutil.rmtree(root/'native/shards')
            (root/'native/native-completion.json').write_text('{}')
            out=Path(t)/'export';result=assemble(root,out)
            self.assertEqual((result['calls'],result['analyzed'],result['not_evaluated']),(1,1,1))
            self.assertEqual(json.loads((out/'provenance.json').read_text())['cluster_mapping'][0]['record'],'R1.1')

    def test_clean_scientific_exports_keep_genome_evidence_mapping(self):
        from canonical_pipeline import _evidence_genome_id
        from result_policy import public_evidence_role
        for path in ['plantismash/Plant/records.final.gbk','plantismash/Plant/geneclusters.csv','plantismash/Plant/record-cluster-map.tsv','plantismash/Plant/provenance.json','plantismash/Plant/data/R1.1/record.geneclusters.xlsx']:
            role=public_evidence_role(path)
            self.assertEqual(role,'native_plant_scientific_export')
            self.assertEqual(_evidence_genome_id(path,role),'Plant')

    def test_native_receipt_compatibility_is_explicit(self):
        self.assertTrue(matching_producers(PUBLIC_PRODUCER,LEGACY_PRODUCER))
        self.assertFalse(matching_producers(PUBLIC_PRODUCER,'other'))
