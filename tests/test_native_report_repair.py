import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'bin'),str(ROOT/'web')]
from plantismash_report import call_report_fields,read_report

class NativeReportRepairTests(unittest.TestCase):
    def test_native_fields_are_concise_and_missing_matches_stay_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'native/geneclusters.js';p.parent.mkdir()
            row={'start':10,'end':20,'domains':['UDPGT_2','p450'],'substrates':['-'],'cdhitclusters':[{}, {}, {}],'knowncluster':'-','BGCid':'-'}
            p.write_text('var geneclusters = '+json.dumps({'cluster-1':row})+';\nvar details_data = {};')
            call={'original_record_ordinal':7,'original_record_id':'NC_037291.2','native_cluster_gbk':'r000007_NC_037291.2.cluster001.gbk','start_1':10,'end_1':20}
            r=call_report_fields(root,call,{})
            self.assertEqual(r['bgc_record'],'NC_037291.2.cluster001');self.assertEqual(r['predictor_core_domains'],'UDPGT_2, p450');self.assertEqual(r['plantismash_cdhit_count'],3)
            self.assertEqual(r['plantismash_subgroup_prediction'],'');self.assertEqual(r['plantismash_knowncluster_similarity_score'],'')
            row.update(cdhitclusters=[],knowncluster='example product (0% of genes show similarity)',BGCid='BGC0001315.3_c1')
            p.write_text('var geneclusters = '+json.dumps({'cluster-1':row})+';\nvar details_data = {};')
            r=call_report_fields(root,call,{});self.assertEqual(r['plantismash_cdhit_count'],0);self.assertEqual(r['plantismash_knowncluster_similarity_score'],'0');self.assertEqual(r['plantismash_knowncluster_accession'],'BGC0001315.3_c1')
            call['end_1']=21
            with self.assertRaises(ValueError):call_report_fields(root,call,{})
            p.write_text('var geneclusters = evil(); var details_data = {};')
            with self.assertRaises(ValueError):read_report(p)

    def test_exact_native_tfbs_and_single_record_downloads_preserve_private_boundary(self):
        from result_policy import result_path_public_shape, public_evidence_role
        for native in ['plantismash/Plant/native/', 'plantismash/Plant/native/shards/000007/native/']:
            for name in ['tfbs_hits_all_bgcs.csv','tfbs/tfbs_hits_cluster1_NC_037291.2.tsv.gz',
                         'NC_037291.2.cluster001.gbk','NC_037291.2.geneclusters.xlsx','NC_037291.2.zip']:
                path='data/results/P/'+native+name
                self.assertTrue(result_path_public_shape(path),path)
                self.assertTrue(public_evidence_role(path),path)
            for name in ['arbitrary.csv','tfbs/arbitrary.tsv.gz','tfbs/../execution.json','inputs/NC_037291.2.final.gbk','original.gbk','native.log','provenance.json']:
                self.assertFalse(result_path_public_shape('data/results/P/'+native+name),name)
        for path in ['plantismash/Plant/shards/000007/native/tfbs_hits_all_bgcs.csv',
                     'plantismash/Plant/native/shards/7/native/tfbs_hits_all_bgcs.csv']:
            self.assertFalse(result_path_public_shape('data/results/P/'+path),path)

    def test_single_locus_is_not_a_public_panel_but_real_comparator_is(self):
        from canonical_pipeline import _is_public_result_file
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'clinker/panels/atlas/plants/Plant/cluster/panel.html';p.parent.mkdir(parents=True);p.write_text('<html></html>');m=p.parent/'panel_manifest.tsv';m.write_text('role\tgenome\nantismash\tunused\ntarget\tPlant\n')
            self.assertFalse(_is_public_result_file(p,SimpleNamespace(results_root=root)))
            m.write_text('role\tgenome\ntarget\tPlant\nmibig_reference\tBGC0000001\n');self.assertTrue(_is_public_result_file(p,SimpleNamespace(results_root=root)))
