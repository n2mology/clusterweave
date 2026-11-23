"""Scientific display vocabulary and completed-run reporting regressions."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'bin'), str(ROOT/'web')]
from bgc_display import classify, classes
from result_policy import result_path_public_shape, result_path_forbidden
from render_progress_tree import load_contract, build_progress_tree


class CompletedRunRepairs(unittest.TestCase):
    def test_native_product_labels_remain_distinct_and_generic_enzymes_do_not_imply_chemistry(self):
        expected = {'saccharide':'saccharide', 'cyclopeptide':'cyclopeptide',
                    'fatty_acid':'fatty_acid', 'alkaloid':'alkaloid', 'putative':'putative',
                    'arylpolyene':'arylpolyene', 'betalactone':'betalactone',
                    'resorcinol':'resorcinol', 'NI-siderophore':'NI-siderophore',
                    'triceptide':'triceptide', 'phosphonate-like':'phosphonate',
                    'hydrogen-cyanide':'hydrogen-cyanide', 'redox-cofactor':'redox-cofactor',
                    'other':'other', 'novel_future_label':'unclassified',
                    'protein synthase':'unclassified', 'generic cyclase':'unclassified',
                    'T1PKS':'PKS', 'NRPS-like':'NRPS', 'terpene-precursor':'terpene'}
        for native, category in expected.items():
            with self.subTest(native=native):self.assertEqual(classify(native),category)
        self.assertEqual(classes('alkaloid-fatty_acid'), {'alkaloid','fatty_acid'})
        self.assertEqual(classify('alkaloid-fatty_acid'), 'hybrid')
        self.assertEqual(classify('fatty_acid-saccharide'), 'hybrid')

    def test_exact_product_has_precedence_over_broad_native_category(self):
        from render_phylo_taxon_profile import Leaf, add_profiles
        import csv
        leaf=Leaf('genome','bacteria','','','Genome','Genome',(),(),False,'prodigal','antismash')
        with tempfile.TemporaryDirectory() as folder:
            exact=Path(folder)/'products.tsv'
            with exact.open('w') as handle:
                writer=csv.DictWriter(handle,fieldnames=['genome','bgc_id','exact_product_type','term_source','broad_display_class'],delimiter='\t');writer.writeheader()
                writer.writerows([
                    dict(genome='genome',bgc_id='region1',exact_product_type='triceptide',term_source='area_product',broad_display_class='other'),
                    dict(genome='genome',bgc_id='region1',exact_product_type='RiPP',term_source='protocluster_category',broad_display_class='other'),
                ])
            add_profiles([leaf],exact,None)
            self.assertEqual(dict(leaf.bgc_counts),{'triceptide':1})

    def test_only_exact_plant_native_web_assets_cross_the_shard_boundary(self):
        prefix='data/results/project/plantismash/Plant/native/shards/000001/native/'
        for name in ['index.html','geneclusters.js','css/style.css','js/jquery.js','svg/cluster1.svg','images/icon.png']:
            with self.subTest(name=name):
                self.assertTrue(result_path_public_shape(prefix+name))
                self.assertFalse(result_path_forbidden(prefix+name))
        for path in [prefix+'native-completion.json',prefix+'original.gbk',prefix+'work/debug.html',
                     prefix+'provenance.json',prefix+'native.log',prefix+'source.map',
                     prefix.replace('000001','unknown')+'index.html',
                     prefix.replace('/plantismash/','/antismash/')+'index.html',
                     prefix.replace('/native/shards/','/shards/')+'index.html',
                     'work/shards/000001/native/index.html']:
            with self.subTest(path=path):self.assertFalse(result_path_public_shape(path))

    def test_sparse_context_retains_independent_terminal_branches_and_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            old=os.environ.get('DATA_DIR');os.environ['DATA_DIR']=directory
            try:
                sys.modules.pop('job_store',None);store=importlib.import_module('job_store')
                lines=['Stage 1/4: running detection',
                       'GENOME_PROGRESS genome=Plant stage=annotation percent=0 bar=[----------] message="Queued genome 2/3"',
                       'GENOME_PROGRESS genome=Plant stage=annotation percent=1 bar=[----------] message="Validating supplied plant CDS annotations"',
                       'TOOL_PROGRESS genome=Plant tool=plantismash phase=detect message="Finding plant clusters"',
                       'GENOME_PROGRESS genome=Bacterium stage=annotation percent=100 bar=[##########] message="Genome workflow complete"',
                       'GENOME_PROGRESS genome=Plant stage=plantismash percent=100 bar=[##########] message="Completed plantiSMASH: 76 BGCs SUCCESS_WITH_CALLS"',
                       'TOOL_PROGRESS genome=Fungus tool=antismash phase=detect message="Writing antiSMASH outputs"',
                       'TOOL_HEARTBEAT genome=Fungus tool=antismash phase=detect elapsed=400s']
                context={}
                for index,line in enumerate(lines):store._remember_progress(context,line,index)
                records=sorted({r['index']:r for r in context.values()}.items())
                model=build_progress_tree(load_contract(),[(i,r['line']) for i,r in records])
                self.assertEqual(model.nodes['genome:annotation:Plant'].state,'complete')
                self.assertEqual(model.nodes['tool:annotation:Plant:plantiSMASH'].state,'complete')
                self.assertEqual(model.nodes['genome:annotation:Bacterium'].state,'complete')
                self.assertEqual(model.nodes['tool:annotation:Fungus:antiSMASH'].message,'Writing antiSMASH outputs')
                self.assertEqual(model.nodes['tool:annotation:Fungus:antiSMASH'].elapsed,400)
                raw='TOOL_RAW genome=Fungus tool=antismash stream=stdout TOOL_RAW genome=Fungus tool=antismash stream=stderr ERROR debug'
                model=build_progress_tree(load_contract(),enumerate(lines+[raw,"WARNING: Error changing the container working directory. Using '/' instead: chdir /nonexistent: no such file or directory"]))
                self.assertFalse(any(n.state=='failed' for n in model.ordered_nodes()))
                model=build_progress_tree(load_contract(),enumerate(lines+['FATAL: analysis exited with code 1']))
                self.assertEqual(model.nodes['stage:annotation'].state,'failed')
            finally:
                sys.modules.pop('job_store',None)
                if old is None:os.environ.pop('DATA_DIR',None)
                else:os.environ['DATA_DIR']=old

if __name__=='__main__':unittest.main()
