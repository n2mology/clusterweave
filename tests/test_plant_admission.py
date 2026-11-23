"""Plant admission is content based and never changes source DNA/peptides."""
import io
import sys
import unittest
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
from plant_annotation import check_translation, inspect_plant_annotation
from scientific_profiles import default_prediction_method, default_detector_profile
from taxon_routing import build_taxon_routes
from canonical_pipeline import _normalize_taxon_routes
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation, CompoundLocation, BeforePosition, AfterPosition
from Bio.SeqRecord import SeqRecord
from Bio import SeqIO

class PlantAdmissionTests(unittest.TestCase):
    def feature(self, location, peptide='MA', **qualifiers):
        return SeqFeature(location, type='CDS', qualifiers={'translation':[peptide], **qualifiers})

    def test_native_outputs_without_route_manifest_cannot_report_empty(self):
        from plantismash_consumers import validated_results
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(validated_results(root), [])
            (root / "plantismash" / "sample").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "absent manifest is not an empty detection"):
                validated_results(root)

    def test_bounded_partial_semantics_and_original_identity(self):
        cases = [
            ('ATGGC', SimpleLocation(0,AfterPosition(5),1), 'MA', 'PARTIAL3_COMPATIBLE', {}),
            ('ATGGC', SimpleLocation(0,5,1), 'MA', 'FAIL', {}),
            ('ATGAT', SimpleLocation(0,AfterPosition(5),1), 'MI', 'FAIL', {}),
            ('ATGGC', SimpleLocation(BeforePosition(0),5,1), 'MA', 'FAIL', {}),
            ('GCCAT', SimpleLocation(BeforePosition(0),5,-1), 'MA', 'PARTIAL3_COMPATIBLE', {}),
            ('GCA AACAT'.replace(' ',''), CompoundLocation([SimpleLocation(5,8,-1), SimpleLocation(BeforePosition(0),2,-1)]), 'MA', 'PARTIAL3_COMPATIBLE', {}),
            ('AATGGC', SimpleLocation(0,AfterPosition(6),1), 'MA', 'PARTIAL3_COMPATIBLE', {'codon_start':['2']}),
            ('ATGGC', SimpleLocation(0,AfterPosition(5),1), 'MA', 'FAIL', {'transl_table':['9999']}),
            ('ATGGC', SimpleLocation(0,AfterPosition(5),1), 'MA', 'FAIL', {'codon_start':['0']}),
            ('ATGGCTTAA', SimpleLocation(0,9,1), 'MA', 'EXACT', {}),
            ('ATGGCTTAA', SimpleLocation(0,9,1), 'MV', 'SOURCE_EXCEPTION', {'exception':['unclassified translation discrepancy']}),
        ]
        for nt, loc, peptide, expected, qualifiers in cases:
            with self.subTest(nt=nt,loc=loc,qualifiers=qualifiers):
                f=self.feature(loc,peptide,**qualifiers); before=repr(f)
                self.assertEqual(check_translation(f,Seq(nt))['status'],expected)
                self.assertEqual(repr(f),before)

    def test_manual_pair_and_invalid_sequence_or_annotation(self):
        r=SeqRecord(Seq('ATGGCTTAA'+'A'*1100),id='plant1',name='plant1',description='supplied annotation')
        r.annotations['molecule_type']='DNA'
        r.features=[self.feature(SimpleLocation(0,9,1))]
        h=io.StringIO();SeqIO.write(r,h,'genbank');raw=h.getvalue().encode()
        value=inspect_plant_annotation(io.BytesIO(raw),io.StringIO('>plant1\n'+str(r.seq)+'\n'))
        self.assertEqual(value['annotation_state'],'ready')
        with self.assertRaisesRegex(ValueError,'does not match'):
            inspect_plant_annotation(io.BytesIO(raw),io.StringIO('>other\n'+str(r.seq)+'\n'))
        with self.assertRaises(ValueError):inspect_plant_annotation(io.BytesIO(raw.replace(b' /translation="MA"',b' /translation="MV"')))
        with self.assertRaises(ValueError):inspect_plant_annotation(io.BytesIO(raw[:-15]))

    def test_server_uses_annotation_content_and_manual_pair(self):
        import tempfile, os
        from unittest import mock
        with tempfile.TemporaryDirectory() as data, mock.patch.dict(os.environ, {'DATA_DIR':data}):
            import app
        record=SeqRecord(Seq('ATGGCTTAA'+'A'*1100),id='plant1',name='plant1',description='supplied')
        record.annotations['molecule_type']='DNA'
        record.features=[self.feature(SimpleLocation(0,9,1))]
        stream=io.StringIO();SeqIO.write(record,stream,'genbank');raw=stream.getvalue().encode()
        uploads=[{'filename':'plant1.gbk','content':raw}]
        error,settings=app.build_submission_taxon_routing(uploads,{},'plants','')
        self.assertIsNone(error,error)
        self.assertEqual(settings['taxon_routes'][0]['annotation_state'],'ready')
        error,_=app.build_submission_taxon_routing([{'filename':'plant1.fa','content':b'>plant1\n'+str(record.seq).encode()}],{},'plants','')
        self.assertIn('Annotation required',error)
        uploads.append({'filename':'plant1.fa','content':b'>different\n'+str(record.seq).encode()})
        error,_=app.build_submission_taxon_routing(uploads,{},'plants','')
        self.assertIn('does not match',error)

    def test_runtime_admission_uses_validated_detector_routes(self):
        import tempfile, os
        from unittest import mock
        with tempfile.TemporaryDirectory() as data, mock.patch.dict(os.environ, {'DATA_DIR':data}):
            import app
        settings={'run_annotation':True,'analysis_scope':'plants','taxon_routes':[{'taxon_group':'plants'}]}
        status={'ready':True,'capabilities':{'stages':{'annotation':{'available':False},'plantismash':{'available':True}}}}
        self.assertIsNone(app.validate_runtime_request(settings,status))
        status['capabilities']['stages']['plantismash']['available']=False
        self.assertIn('plantismash',app.validate_runtime_request(settings,status))
        del status['capabilities']['stages']['plantismash']
        self.assertIn('plantismash',app.validate_runtime_request(settings,status))
        self.assertIn('plantismash',app.validate_runtime_request(settings,{'ready':True}))
        status['capabilities']['stages']['plantismash']={'available':True}
        settings['analysis_scope']='mixed';settings['taxon_routes'].append({'taxon_group':'fungi'})
        self.assertIn('annotation',app.validate_runtime_request(settings,status))
        status['capabilities']['stages']['annotation']['available']=True
        self.assertIsNone(app.validate_runtime_request(settings,status))

    def test_failed_annotation_cannot_reuse_a_previous_success(self):
        import tempfile, argparse, json
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
        from plantismash_runtime import mark_failed
        from plantismash_consumers import validated_results
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);native=root/'plantismash'/'p';native.mkdir(parents=True)
            (native/'outcome.json').write_text(json.dumps({'state':'SUCCESSFUL_EMPTY','calls':0}))
            (native/'original.gbk').write_bytes(b'unchanged historical input')
            mark_failed(argparse.Namespace(results=root,genome='p'),'ANNOTATION_REQUIRED')
            current=json.loads((native/'outcome.json').read_text())
            self.assertEqual(current['state'],'ANNOTATION_REQUIRED');self.assertIsNone(current['calls'])
            old=list((root/'plantismash_attempts'/'p').glob('*/original.gbk'))
            self.assertEqual(len(old),1);self.assertEqual(old[0].read_bytes(),b'unchanged historical input')
            (root/'summary_tables').mkdir();(root/'summary_tables/genome_taxon_manifest.tsv').write_text('genome_id\ttaxon_group\n'+'p\tplants\n')
            with self.assertRaisesRegex(ValueError,'no successful current outcome'):validated_results(root)

    def test_route_policy_has_no_plant_prediction_fallback(self):
        self.assertEqual(default_prediction_method('plants'),'annotation_required')
        self.assertEqual(default_prediction_method('plants',has_annotated_genbank=True),'existing_cds')
        self.assertEqual(default_detector_profile('plants'),'plantismash')
        route={'input_key':'p','genome_id':'p','taxon_group':'plants','prediction_method':'funannotate'}
        with self.assertRaisesRegex(ValueError,'supplied CDS'):_normalize_taxon_routes({'taxon_routes':[route]})
        route['prediction_method']='existing_cds'
        with self.assertRaisesRegex(ValueError,'scope'):_normalize_taxon_routes({'analysis_scope':'both','taxon_routes':[route]})
        self.assertEqual(_normalize_taxon_routes({'analysis_scope':'mixed','taxon_routes':[route]})[0]['detector_profile'],'plantismash')

if __name__=='__main__':unittest.main()
