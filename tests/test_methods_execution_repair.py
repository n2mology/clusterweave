"""Native-sized records and cache-unavailable executions retain version evidence."""
import json
from pathlib import Path
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'web'))
import researcher_report as report
from tool_runtime import observe
from unittest import mock

class MethodsExecutionRepair(unittest.TestCase):
    def test_cache_unavailable_and_large_native_record(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'summary_tables').mkdir();(r/'reproducibility/accession_cache').mkdir(parents=True)
            (r/'summary_tables/genome_taxon_manifest.tsv').write_text('genome_id\ttaxon_group\tsource_accession\tprediction_method\tdetector_profile\nB\tbacteria\tGCF_999999999.1\tprodigal\tantismash\n')
            state={'scientific_attempt':{'annotation_selected':True},'annotation_observations':[{'tool':'antiSMASH','backend':'apptainer','runtime_sha256':'a'*64,'version':'8.0.4'},{'tool':'Prodigal','backend':'apptainer','runtime_sha256':'a'*64,'version':'2.6.3'}]}
            report.begin_scientific_stage(r,state)
            (r/'summary_tables/run_manifest.tsv').write_text('genome_id\ttaxon_group\tprediction_method\tgbk_status\tantismash_status\tfunbgcex_status\nB\tbacteria\tprodigal\tbacterial_sequence_sanitized\tran_ok\tnot_applicable_taxon\n')
            (r/'reproducibility/accession_cache/B.detection.json').write_text(json.dumps({'schema':1,'outcome':'miss','reason':'cache_unavailable','population':'rejected','identity':None,'key':None,'entry_manifest':None}))
            d=r/'antismash/B';d.mkdir(parents=True);(d/'.done').touch();(d/'index.html').write_text('native')
            (d/'B.bacteria.antismash.json').write_text(json.dumps({'version':'8.0.4','records':[{'areas':[{}],'sequence':'A'*(17*1024*1024)}]}))
            report.finish_scientific_stage(r,state,'complete');files=report.build_report(r,state=state,root=ROOT);m=json.loads(files['run_metadata.json']);g=m['scientific_outcomes']['genomes'][0]
            self.assertEqual(g['antismash']['current_use'],'execution');self.assertEqual(g['antismash']['finding_count'],1)
            tools={x['name']:x for x in m['tools']};self.assertEqual(tools['antiSMASH']['version'],'8.0.4');self.assertEqual(tools['Prodigal']['version'],'2.6.3');self.assertNotIn('NPLinker',tools)
            recovered=json.loads(report.build_report(r,root=ROOT)['run_metadata.json']);self.assertEqual(recovered['scientific_outcomes'],m['scientific_outcomes']);self.assertEqual(recovered['tools'],m['tools'])
    def test_exact_exonerate_exit_one_banner(self):
        with mock.patch('tool_runtime.shutil.which',return_value='/exact/exonerate'),mock.patch('tool_runtime.file_digest',return_value='a'*64),mock.patch('tool_runtime.bounded_run',return_value=(1,'exonerate from exonerate version 2.4.0\nUsing glib version 2.76.2\n')):
            self.assertEqual(observe('Exonerate')['version'],'2.4.0')
        with mock.patch('tool_runtime.shutil.which',return_value='/exact/exonerate'),mock.patch('tool_runtime.file_digest',return_value='a'*64),mock.patch('tool_runtime.bounded_run',return_value=(1,'could not run; glib 2.76.2')):
            self.assertIsNone(observe('Exonerate')['version'])

    def test_active_site_product_recovers_hmmer2_from_exact_producer_lock(self):
        from plant_versions import native_helper_versions
        runtime=json.loads((ROOT/'software/plantismash/runtime.lock.json').read_text())['preferred_sif_sha256']
        with tempfile.TemporaryDirectory() as t:
            native=Path(t)
            (native/'native-completion.json').write_text('{"successful_hmm_searches":1}')
            (native/'geneclusters.js').write_text('var geneclusters = '+json.dumps({'cluster-1':{'orfs':[{'description':'<b>Active Site Finder results:</b> p450 active site cystein present'}]}})+'; var details_data = {};')
            observations=native_helper_versions(native,runtime,ROOT)
            self.assertEqual({r['version'] for r in observations if r['tool']=='HMMER'},{'2.3.2','3.3.2'})
            self.assertEqual(native_helper_versions(native,'0'*64,ROOT),[])
