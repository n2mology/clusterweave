"""Reporting boundaries reproduced by completed mixed production outputs."""
import ast
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'bin'), str(ROOT / 'web')]
from gcf_view import clustering_view
from bgc_display import COLORS, classify, family_class
from result_policy import result_path_public_shape
from public_results import _clinker_descriptor_context
from export_dataset_family_atlas import include_reference_panels
from render_bigscape_multipanel import count_legend


class FinalQaReporting(unittest.TestCase):
    def test_selected_family_view_and_native_class_precedence(self):
        # Actual producer vocabulary: native saccharide, broad Categoryless.
        tree = ast.parse((ROOT/'bin/summarize_clusterweave.py').read_text())
        definitions = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'clean','parse_bigscape'}]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'output_files/2026-11-17_21-31-21_c0.3';run.mkdir(parents=True)
            (run/'record_annotations.tsv').write_text('Record\tGBK\tClass\tCategory\nPlant__r1.gbk_region_1\tPlant__r1\tsaccharide\tCategoryless\n')
            for category,threshold,family in [('mix','0.3','correct'),('Categoryless','0.3','wrong-view'),('mix','0.5','wrong-threshold')]:
                folder=run/category;folder.mkdir(exist_ok=True)
                (folder/f'{category}_clustering_c{threshold}.tsv').write_text('Record\tFamily\nPlant__r1.gbk_region_1\t'+family+'\n')
            scope={'os':os,'csv':csv,'glob':__import__('glob'),'BIGSCAPE_ROOT':str(root)}
            exec(compile(ast.Module(body=definitions,type_ignores=[]),'<summary-functions>','exec'),scope)
            ann,memberships=scope['parse_bigscape']()
            self.assertEqual(memberships,{'Plant__r1.gbk_region_1':'correct'})
            self.assertEqual(ann['Plant__r1.gbk_region_1']['class'],'saccharide')

    def test_historical_and_current_clustering_names_select_same_view(self):
        for name in ['mix_clustering_0.3.tsv','mix_clustering_c0.30.tsv']:
            self.assertEqual(clustering_view(Path('mix')/name),('mix','0.3'))

    def test_family_composition_preserves_mixed_and_unknown(self):
        self.assertEqual(family_class(['saccharide']*3),'saccharide')
        self.assertEqual(family_class(['saccharide']*3+['fatty_acid']),'hybrid')
        self.assertEqual(family_class(['putative']),'putative')
        self.assertEqual(family_class(['saccharide','unclassified']),'unclassified')
        for left,right in [('saccharide','fatty_acid'),('putative','unclassified')]:
            a=tuple(int(COLORS[left][i:i+2],16) for i in (1,3,5));b=tuple(int(COLORS[right][i:i+2],16) for i in (1,3,5))
            self.assertGreater(sum((x-y)**2 for x,y in zip(a,b))**.5,100)

    def test_network_fill_uses_native_crosswalk_without_rewriting_engine_label(self):
        from render_bigscape_network import load_nodes, apply_native_classes
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); cluster=root/'mix_clustering_c0.3.tsv'
            cluster.write_text('Record\tGBK\tFamily\nPlant__r1\tPlant__r1\t1\nBGC0001248.3\tBGC0001248.3\t1\n')
            nodes,_=load_nodes(cluster,{'Plant__r1':{'Class':'','Category':'Categoryless'},'BGC0001248.3':{'Class':'terpene'}})
            crosswalk=root/'native.tsv';crosswalk.write_text('bigscape_record\tantismash_class\nPlant__r1\tfatty_acid;saccharide\nBGC0001248.3\tNRPS\n')
            apply_native_classes(nodes,crosswalk)
            self.assertEqual(nodes['Plant__r1'].bgc_class,'hybrid')
            self.assertEqual(nodes['Plant__r1'].raw_class,'')
            self.assertEqual(nodes['Plant__r1'].fill_color,COLORS['hybrid'])
            self.assertEqual(nodes['BGC0001248.3'].bgc_class,'terpene')

    def test_count_legend_includes_classes_absent_from_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'counts.csv';p.write_text('genome,taxon_group,entity_type,tool,class_norm,total\nB,bacteria,GCF,antismash,other,6\nB,bacteria,BGC,antismash,resorcinol,1\n')
            legend,_=count_legend(p,'bacteria',0,0,500);text=''.join(legend)
            self.assertIn(COLORS['other'],text);self.assertIn('Other (native label)',text);self.assertIn('Resorcinol',text)

    def test_native_download_exception_does_not_open_private_shards(self):
        prefix='data/results/project/plantismash/Plant/native/shards/000001/native/'
        for suffix in ['cluster001.gbk','final.gbk','geneclusters.xlsx','zip']:
            self.assertTrue(result_path_public_shape(prefix+'NC_037285.2.'+suffix))
        for name in ['native-completion.json','original.gbk','credentials.zip','NC_037285.2.env','../NC_037285.2.zip','inputs/NC_037285.2.zip','command_logs/index.html']:
            self.assertFalse(result_path_public_shape(prefix+name),name)

    def test_plant_clinker_descriptor_and_honest_context(self):
        self.assertEqual(_clinker_descriptor_context('data/results/p/clinker/panels/atlas/plants/Plant/locus/panel.html'),('plants','Plant','atlas'))
        rows=[{'genome':'F','taxon_group':'fungi','manual_review_bucket':'atlas_now','shared_cc_record_count':'2'},
              {'genome':'P','taxon_group':'plants','manual_review_bucket':'atlas_context','shared_cc_record_count':'1'},
              {'genome':'B','nearest_mibig_or_annotation_if_available':'BGC0002416.3','taxon_group':'bacteria','manual_review_bucket':'atlas_context','shared_cc_record_count':'1'}]
        include_reference_panels(rows,3)
        self.assertEqual([r['manual_review_bucket'] for r in rows], ['atlas_now','atlas_context','atlas_now'])
        self.assertIn('MIBiG',rows[2]['recommended_followup'])

if __name__ == '__main__': unittest.main()
