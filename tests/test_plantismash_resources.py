from pathlib import Path
import hashlib
import ast
import importlib.util
import io
import json
import tempfile
import unittest
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('plant_resources',ROOT/'software/plantismash/install_resources.py')
resources=importlib.util.module_from_spec(spec);spec.loader.exec_module(resources)

class PreparedResourcesTests(unittest.TestCase):
    def test_subgroup_uses_labelled_domains_and_accepts_flanking_annotations(self):
        import logging
        import os
        source=ROOT/'software/plantismash/modifications/antismash/generic_modules/subgroup/__init__.py'
        node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='fam_aa_fas')
        features=[SimpleNamespace(id=name,qualifiers=qualifiers) for name,qualifiers in [
            ('flank',{'sec_met':['Type: none'],'translation':['AAAA']}),
            ('empty',{'sec_met':[],'translation':['CCCC']}),
            ('ordinary',{'sec_met':['Type: saccharide','Domains detected: UDPGT_2 (E-value: 1e-20);p450 (E-value: 1e-10)'],'translation':['DEFG']}),
            ('reordered',{'sec_met':['Domains detected: UDPGT_2 (E-value: 1e-20)','Type: saccharide'],'translation':['HIKL']})]]
        namespace={'utils':SimpleNamespace(get_withincluster_cds_features=lambda record:features,get_gene_id=lambda f:f.id),'logging':logging,'os':os}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        with tempfile.TemporaryDirectory() as folder:
            names,paths=namespace['fam_aa_fas']([object()],[{'UDPGT_2':['UDPGT']},{}],[],folder,None)
            self.assertEqual(names,['UDPGT'])
            self.assertEqual(Path(paths['UDPGT']).read_text(),'>plantismash_ordinary\nDEFG\n>plantismash_reordered\nHIKL\n')

    def test_pfam_intervals_follow_splice_order_strand_and_codon_start(self):
        from Bio.Seq import Seq
        from Bio.SeqFeature import SeqFeature, FeatureLocation, CompoundLocation
        source=ROOT/'software/plantismash/modifications/antismash/generic_modules/fullhmmer/__init__.py'
        node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='_domain_location')
        namespace={'FeatureLocation':FeatureLocation,'CompoundLocation':CompoundLocation}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        domain=namespace['_domain_location'];sequence=Seq('ACGT'*40)
        for strand in [1,-1]:
            parts=[FeatureLocation(3,12,strand=strand),FeatureLocation(100,112,strand=strand)]
            if strand==-1:parts.reverse()
            for codon_start in [1,2,3]:
                feature=SeqFeature(CompoundLocation(parts),type='CDS',qualifiers={'codon_start':[str(codon_start)]})
                hsp=SimpleNamespace(query_start=1,query_end=5)
                location=domain(feature,hsp);start=3+codon_start-1;end=15+codon_start-1
                self.assertEqual(list(location),list(feature.location)[start:end])
                self.assertEqual(location.extract(sequence),feature.extract(sequence)[start:end])
                self.assertEqual(len(location),12)
                with self.assertRaises(ValueError):domain(feature,SimpleNamespace(query_start=0,query_end=20))

    def test_asf_feeds_sequences_and_does_not_hide_tool_or_parser_failure(self):
        import logging
        import xml.etree.ElementTree as ET
        from unittest.mock import Mock
        source=ROOT/'software/plantismash/modifications/antismash/generic_modules/active_site_finder/__init__.py'
        cls=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.ClassDef))
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_execute_tool')
        execute=Mock(return_value=('native output','',0));parse=Mock(return_value=iter([]))
        namespace={'utils':SimpleNamespace(execute=execute,locate_file=lambda p:p),
                   'logging':logging,'path':__import__('os').path,'StringIO':io.StringIO,
                   'SearchIO':SimpleNamespace(parse=parse)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        run=namespace['_execute_tool'];obj=SimpleNamespace(options=SimpleNamespace(activeSiteFinderHMMDir='/pinned'))
        resource=ET.fromstring('<analysis name="ASF"><Execute program="hmmscan" STDINprefix="-"><parameters/><database>p450.hmm3</database><BioPythonParser>hmmer3-text</BioPythonParser></Execute></analysis>')
        self.assertEqual(run(obj,resource,stdin_data='>domain\nACDE\n'),[])
        self.assertEqual(execute.call_args.kwargs,{'input_data':'>domain\nACDE\n'})
        resource.find('./Execute').attrib['program']='hmmpfam2'
        ET.SubElement(resource.find('./Execute/parameters'),'parameter',{'prefix':'--cpu'}).text='2'
        parse.return_value=[]
        self.assertEqual(run(obj,resource,stdin_data='query'),[])
        self.assertNotIn('--cpu',execute.call_args.args[0])
        self.assertIn('/pinned/p450.hmm3',execute.call_args.args[0])
        execute.return_value=('', 'native failure', 2)
        with self.assertRaisesRegex(RuntimeError,'native failure'):run(obj,resource,stdin_data='query')
        execute.return_value=('malformed','',0);parse.side_effect=ValueError('invalid HMMER')
        with self.assertRaisesRegex(ValueError,'could not parse'):run(obj,resource,stdin_data='query')
        execute.side_effect=OSError('missing executable')
        with self.assertRaises(OSError):run(obj,resource,stdin_data='query')

    def test_full_pfam_keeps_isoforms_with_the_same_gene_name_distinct(self):
        from collections import defaultdict
        from Bio.Seq import Seq
        from Bio.SeqRecord import SeqRecord
        from Bio.SeqFeature import SeqFeature, FeatureLocation, CompoundLocation
        source=ROOT/'software/plantismash/modifications/antismash/generic_modules/fullhmmer/__init__.py'
        names={'_parent_key','_protein_queries','_domain_location','_annotate'}
        nodes=[n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name in names]
        features=[SeqFeature(CompoundLocation([FeatureLocation(1,4,strand=1),FeatureLocation(end,end+9,strand=1)]),type='CDS',qualifiers={'gene':['Shared'],'protein_id':[protein],'translation':[peptide]}) for end,protein,peptide in [(100,'isoform1','ACDE'),(120,'isoform2','WXYZ')]]
        record=SeqRecord(Seq('A'*200),features=features)
        namespace={'hashlib':hashlib,'utils':SimpleNamespace(get_cds_features=lambda r:[f for f in r.features if f.type=='CDS'],get_gene_id=lambda f:f.qualifiers['gene'][0]),
                   'logging':__import__('logging'),'_min_score':lambda o:0,'_max_evalue':lambda o:0.01,
                   'FeatureLocation':FeatureLocation,'CompoundLocation':CompoundLocation,'SeqFeature':SeqFeature,
                   'defaultdict':defaultdict,'path':__import__('os').path,'name_to_pfamid':{}}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),namespace)
        query,mapping=namespace['_protein_queries'](record)
        self.assertEqual(len(mapping),2);self.assertEqual(len(set(mapping)),2)
        self.assertIn('ACDE',query);self.assertIn('WXYZ',query)
        results=[]
        for key in mapping:
            hit=SimpleNamespace(query_id=key,query_start=0,query_end=2,hit_id='p450',hit_start=0,hit_end=2,bitscore=20,evalue=1e-20,hit_description='p450')
            results.append(SimpleNamespace(id=key,hsps=[hit],target='Pfam-A.hmm'))
        namespace['_annotate'](record,SimpleNamespace(FeatureTags=SimpleNamespace(fullhmmer_tag='PFAM_domain')),results,mapping)
        domains=record.features[2:]
        self.assertEqual([f.qualifiers['translation'][0] for f in domains],['AC','WX'])
        self.assertEqual(len({f.qualifiers['asDomain_id'][0] for f in domains}),2)
        self.assertEqual(len({f.qualifiers['aSParentCDS'][0] for f in domains}),2)
        for domain,parent in zip(domains,features):
            self.assertEqual(list(domain.location),list(parent.location)[:6])
            self.assertEqual(domain.qualifiers['protein_id'],parent.qualifiers['protein_id'])

    def test_hmmscan_rejects_failed_truncated_or_missing_query_results(self):
        from unittest.mock import Mock
        source=ROOT/'software/plantismash/modifications/antismash/utils.py'
        node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='run_hmmscan')
        execute=Mock(return_value=('native output\n[ok]\n','',0));parse=Mock(return_value=[object(),object()])
        namespace={'get_config':lambda:SimpleNamespace(cpus=2),'execute':execute,'StringIO':io.StringIO,'SearchIO':SimpleNamespace(parse=parse)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        run=namespace['run_hmmscan'];query='>one\nACDE\n>two\nACDE\n'
        self.assertEqual(len(run('model',query)),2)
        parse.return_value=[object()]
        with self.assertRaisesRegex(ValueError,'coverage'):run('model',query)
        execute.return_value=('truncated','',0)
        with self.assertRaisesRegex(ValueError,'Incomplete'):run('model',query)
        execute.return_value=('', 'broken index',1)
        with self.assertRaisesRegex(RuntimeError,'broken index'):run('model',query)
        execute.side_effect=OSError('not executable')
        with self.assertRaisesRegex(RuntimeError,'could not execute'):run('model',query)

    def test_smcog_python3_sort_keeps_coordinate_order_and_best_overlap(self):
        spec=importlib.util.spec_from_file_location('smcog_parser',ROOT/'software/plantismash/modifications/antismash/lib/hmmscanparser.py')
        parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
        def hit(name,start,end,score):
            return SimpleNamespace(query_id='supplied_CDS',hit_id=name,query_start=start,query_end=end,evalue=1e-12,bitscore=score)
        result=parser.parse_hmmscan_results([SimpleNamespace(hsps=[hit('A',100,190,20),hit('B',0,90,50)])],{'A':100,'B':100})
        self.assertEqual([h[0] for h in result['supplied_CDS']],['B','A'])
        result=parser.parse_hmmscan_results([SimpleNamespace(hsps=[hit('B',10,90,20),hit('A',0,80,10)])],{'A':100,'B':100})
        self.assertEqual(result['supplied_CDS'],[['B',10,90,1e-12,20]])

    def test_resource_destinations_are_confined_and_reject_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'modules';root.mkdir()
            for name in ['/escape','../escape','clusterblast/../../escape']:
                with self.assertRaises(ValueError):resources.destination(root,name)
            (root/'linked').symlink_to(Path(tmp),target_is_directory=True)
            with self.assertRaises(ValueError):resources.destination(root,'linked/output')
            self.assertFalse((Path(tmp)/'output').exists())

    def test_expanded_identity_bound_and_existing_science_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'resource';payload=b'locked scientific reference';sha=hashlib.sha256(payload).hexdigest()
            resources.write_resource(io.BytesIO(payload),p,sha,len(payload))
            resources.write_resource(io.BytesIO(payload),p,sha,len(payload))
            with self.assertRaisesRegex(ValueError,'replace different'):
                resources.write_resource(io.BytesIO(b'changed'),p,hashlib.sha256(b'changed').hexdigest(),7)
            self.assertEqual(p.read_bytes(),payload)
            with self.assertRaisesRegex(ValueError,'exceeds'):
                resources.write_resource(io.BytesIO(payload),Path(tmp)/'oversize',sha,len(payload)-1)
            with self.assertRaisesRegex(ValueError,'identity differs'):
                resources.write_resource(io.BytesIO(payload),Path(tmp)/'bad','0'*64,len(payload))

    def test_resources_pin_versions_and_keep_database_generation_offline(self):
        lock=json.loads((ROOT/'software/plantismash/resources.lock.json').read_text())
        self.assertEqual(lock['profile_sha256'],hashlib.sha256((ROOT/'config/plantismash-profile.json').read_bytes()).hexdigest())
        for row in lock['assets']:
            self.assertTrue(row['url'].startswith('https://'))
            self.assertNotIn('/latest',row['url']);self.assertNotIn('/master/',row['url'])
            self.assertEqual(len(row['sha256']),64);self.assertGreater(row['bytes'],0)
        targets={r['target'] for r in lock['assets'] if 'target' in r}
        self.assertTrue({'knownclusterblast/knownclusterprots.fasta','subclusterblast/subclusterprots.fasta.psq','fullhmmer/Pfam-A.hmm','tfbs_finder/data/connectTF_validated.csv'} <= targets)
        dependency=json.loads((ROOT/'software/plantismash/sources.lock.json').read_text())
        graphlan=next(r for r in dependency['python'] if r['name']=='graphlan')
        self.assertIn(graphlan['git_commit'],graphlan['url'])

if __name__=='__main__':unittest.main()
