import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'bin'), str(ROOT / 'web')]
import plantismash_native as native
import plantismash_runtime as runtime
import plantismash_prereqs as prerequisites


class PlantExtrasTests(unittest.TestCase):
    def test_runtime_prerequisite_failure_uses_stable_public_producer(self):
        from types import SimpleNamespace
        from plant_identity import PUBLIC_PRODUCER
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'input.gbk';source.write_text('fixture')
            args=SimpleNamespace(results=root/'results',genome='Plant',input=source,fasta=None,force=False,sif=root/'runtime.sif',engine='apptainer')
            with mock.patch.object(runtime,'original_inventory',return_value={'source_file_sha256':'a'*64,'records':[]}), mock.patch.object(runtime,'runtime_identity',return_value={'sif_sha256':'b'*64}), mock.patch.object(runtime,'check_runtime',side_effect=OSError('fixture unavailable')):
                with self.assertRaisesRegex(OSError,'fixture unavailable'):runtime.run(args)
            outcome=json.loads((args.results/'plantismash/Plant/outcome.json').read_text())
            self.assertEqual(outcome['producer'],PUBLIC_PRODUCER)
            self.assertEqual(outcome['state'],'FAILED_OR_PARTIAL')
            self.assertIsNone(outcome['calls'])

    def test_smcog_additions_preserve_original_notes_and_require_extras_profile(self):
        import copy
        import test_plantismash_native as fixtures
        fixture=fixtures.ExtractedNativeTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        record=copy.deepcopy(fixture.record)
        notes=record.features[1].qualifiers['note']
        notes.extend(['smCOG: SMCOG1034:cytochrome_P450 (Score: 252.4; E-value: 1.4e-76);',
                      'smCOG tree PNG image: smcogs/protein1.png'])
        self.assertTrue(native.crosswalk(fixture.original,[record],profile=native.PROFILE)['bijective'])
        self.assertFalse(native.crosswalk(fixture.original,[record],profile=native.LEGACY_PROFILE)['bijective'])
        for changed in [['changed original',*notes[1:]],notes[1:],list(reversed(notes)),[*notes,'unexplained annotation']]:
            altered=copy.deepcopy(record);altered.features[1].qualifiers['note']=changed
            self.assertFalse(native.crosswalk(fixture.original,[altered],profile=native.PROFILE)['bijective'])

    def test_default_enables_all_supported_genome_extras_and_preserves_detection(self):
        profile = runtime.check_profile()
        args = profile['arguments']
        for flag in ['--cdhit', '--clusterblast', '--subclusterblast', '--knownclusterblast', '--tfbs', '--smcogs', '--full-hmmer', '--asf']:
            self.assertIn(flag, args)
        for flag in ['--disable_subgroup', '--disable_treesvg', '--disable_specific_modules', '--update_clusterblast', '--inclusive', '--borderpredict', '--coexpress']:
            self.assertNotIn(flag, args)
        self.assertEqual(args[args.index('--genefinding')+1], 'none')
        self.assertEqual(args[args.index('--taxon')+1], 'plants')
        self.assertEqual(profile['profile_id'], native.PROFILE)
        self.assertEqual(hashlib.sha256((ROOT/'config/plantismash-profile.json').read_bytes()).hexdigest(), native.PROFILE_SHA256)
        # The accepted engine/resource locks bind the new profile; history stays distinct.
        lock = json.loads((ROOT/'software/plantismash/runtime.lock.json').read_text())
        self.assertEqual(lock['profile_sha256'], native.PROFILE_SHA256)
        self.assertEqual(lock['preferred_sif_sha256'], native.SIF_SHA256)
        self.assertEqual(lock['historical_reduced_profile_sif_sha256'], native.REDUCED_PROFILE_SIF_SHA256)
        self.assertEqual(lock['resources_lock_sha256'], hashlib.sha256((ROOT/'software/plantismash/resources.lock.json').read_bytes()).hexdigest())

    def test_old_outputs_keep_their_profile_and_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = root/'native';folder.mkdir()
            old = {'producer':native.PRODUCER,'profile_id':native.LEGACY_PROFILE,'sif_sha256':native.REDUCED_PROFILE_SIF_SHA256}
            (root/'execution.json').write_text(json.dumps(old))
            self.assertEqual(native.recorded_profile(folder), native.LEGACY_PROFILE)
            with mock.patch.object(runtime,'digest',return_value=native.SIF_SHA256):
                self.assertFalse(runtime.retained_profile_matches(root, root/'runtime.sif'))
                new = dict(old, profile_id=native.PROFILE, profile_sha256=native.PROFILE_SHA256)
                (root/'execution.json').write_text(json.dumps(new))
                self.assertFalse(runtime.retained_profile_matches(root, root/'runtime.sif'))
                new['sif_sha256'] = native.SIF_SHA256
                (root/'execution.json').write_text(json.dumps(new))
                self.assertEqual(native.recorded_profile(folder), native.PROFILE)
                self.assertTrue(runtime.retained_profile_matches(root, root/'runtime.sif'))
                new['profile_sha256']='wrong'
                (root/'execution.json').write_text(json.dumps(new))
                self.assertFalse(runtime.retained_profile_matches(root,root/'runtime.sif'))
                with self.assertRaises(ValueError):native.recorded_profile(folder)
            new['profile_sha256']=native.PROFILE_SHA256
            (root/'execution.json').write_text(json.dumps(new))
            with mock.patch.object(runtime,'digest',return_value='different engine'):
                self.assertFalse(runtime.retained_profile_matches(root,root/'runtime.sif'))

    def test_full_profile_download_remains_verifiable_without_raw_root_execution(self):
        import zipfile
        import test_plantismash_native as fixtures
        from Bio import SeqIO
        from verify_native_download import verify
        fixture=fixtures.ExtractedNativeTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        root=fixture.root
        SeqIO.write(fixture.record,root/'original.gbk','genbank')
        original=dict(fixture.original,source_file_sha256=hashlib.sha256((root/'original.gbk').read_bytes()).hexdigest())
        (root/'original-identity.json').write_text(json.dumps(original))
        (root/'execution.json').write_text(json.dumps({'producer':native.PRODUCER,'profile_id':native.PROFILE,'profile_sha256':native.PROFILE_SHA256,'argv':['/private/operator/path']}))
        (root/'validation.json').write_text('{}');(root/'outcome.json').write_text('{}')
        archive=native.complete_native_archive(root)
        unpacked=root/'unpacked'
        with zipfile.ZipFile(archive) as z:
            self.assertIn('run-profile.json',z.namelist());self.assertNotIn('execution.json',z.namelist())
            self.assertNotIn('/private/operator/path',z.read('run-profile.json').decode())
            z.extractall(unpacked)
        self.assertEqual(native.recorded_profile(unpacked/'native'),native.PROFILE)
        self.assertEqual(verify(unpacked)['calls'],1)

    def test_missing_extras_fail_without_acquisition_or_native_side_effects(self):
        args=runtime.check_profile()['arguments']
        with tempfile.TemporaryDirectory() as tmp:
            result=prerequisites.audit(args,Path(tmp),which=lambda *a,**kw:None)
            self.assertFalse(result['ready_for_native_check'])
            self.assertIn('resource:knownclusterblast/knownclusterprots.dmnd',result['missing'])
            self.assertIn('resource:fullhmmer/Pfam-A.hmm',result['missing'])
            self.assertIn('resource:tfbs_finder/data/connectTF_validated.csv',result['missing'])
            self.assertIn('executable:graphlan.py',result['missing'])
            self.assertEqual(list(Path(tmp).iterdir()),[])
        with mock.patch.object(prerequisites,'audit',return_value=result), mock.patch.object(prerequisites.sys,'argv',['probe',json.dumps(args)]), mock.patch.object(prerequisites.subprocess,'run') as execute:
            self.assertEqual(prerequisites.main(),2)
            execute.assert_not_called()

    def test_prepared_audit_requires_nonempty_indexes_and_valid_tfbs_checksum(self):
        args=runtime.check_profile()['arguments']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in prerequisites.required_resources(args)[0]:
                p=root/str(prerequisites.MODULES/name).lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
            result=prerequisites.audit(args,root,which=lambda *a,**kw:'/prepared/tool')
            self.assertEqual(result['missing'],['checksum:tfbs_finder/data/connectTF_validated.csv'])
            with mock.patch.object(prerequisites,'CONNECT_TF_MD5',hashlib.md5(b'fixture').hexdigest()):
                self.assertTrue(prerequisites.audit(args,root,which=lambda *a,**kw:'/prepared/tool')['ready_for_native_check'])
                p=root/str(prerequisites.MODULES/'fullhmmer/Pfam-A.hmm.h3m').lstrip('/');p.write_bytes(b'')
                self.assertIn('resource:fullhmmer/Pfam-A.hmm.h3m',prerequisites.audit(args,root,which=lambda *a,**kw:'/prepared/tool')['missing'])

    def test_native_preflight_receives_the_exact_enabled_profile(self):
        args=runtime.check_profile()['arguments']
        with mock.patch.object(prerequisites,'audit',return_value={'missing':[]}), mock.patch.object(prerequisites.sys,'argv',['probe',json.dumps(args)]), mock.patch.object(prerequisites.subprocess,'run',return_value=mock.Mock(returncode=0)) as execute:
            self.assertEqual(prerequisites.main(),0)
            self.assertEqual(execute.call_args.args[0],['/usr/local/bin/plantismash',*args,'--check-prereqs'])

if __name__ == '__main__':unittest.main()
