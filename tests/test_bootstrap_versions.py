"""Configured and observed bootstrap versions, without acquiring runtime assets."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bin'))
import bootstrap_versions as display
from prepare_runtime import local_image_specs

class BootstrapVersionDisplayTests(unittest.TestCase):
    def test_release_and_citation_versions_agree(self):
        identity=display.project_identity(ROOT)
        self.assertEqual(identity['active'],'1.1.0')
        self.assertEqual(identity['citation'],'1.1.0')
        self.assertIn('v1.1.0',display.citation_lines(ROOT)[0])
        self.assertIn('released citation record v1.1.0',display.citation_lines(ROOT)[1])

    def test_missing_or_invalid_build_metadata_uses_the_citation_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'source';root.mkdir()
            (root/'CITATION.cff').write_text('cff-version: 1.2.0\nversion: 4.5.6\ndoi: "10.1234/test"\n')
            self.assertEqual(display.project_identity(root)['active'],'4.5.6')
            (root/'config').mkdir()
            (root/'config/project-version.txt').write_text('invalid\n')
            self.assertEqual(display.project_identity(root)['active'],'4.5.6')
            (root/'config/project-version.txt').write_text('4.6.0-dev\n')
            self.assertEqual(display.project_identity(root)['active'],'4.6.0-dev')
            self.assertEqual(display.project_identity(root)['citation'],'4.5.6')
            self.assertIn('v4.6.0-dev', display.citation_lines(root)[0])
            self.assertIn('released citation record v4.5.6', display.citation_lines(root)[1])

    def test_all_bootstrap_components_have_explicit_version_status(self):
        catalogue=display.bootstrap_catalogue(ROOT, {})
        phases={'worker_components','antismash','pfam','ncbi_cli','fasttree','mibig','nplinker_environment'}
        phases.update(spec.key for spec in local_image_specs({},ROOT))
        self.assertEqual(set(catalogue),phases)
        for rows in catalogue.values():
            self.assertTrue(rows)
            for row in rows:
                self.assertEqual(set(row),{'tool','version','basis'})
                self.assertTrue(row['tool'])
                self.assertTrue(row['basis'])
                if row['version']:
                    self.assertIn('configured pin',display.label(row))
                else:
                    self.assertIn('version not observed',display.label(row))
        self.assertEqual(catalogue['funbgcex_image'][0]['version'],'1.0.1')
        self.assertEqual(catalogue['funannotate_image'][0]['version'],'1.8.17')
        self.assertEqual(catalogue['bigscape_image'][0]['version'],'2.0.0-beta.6')
        self.assertEqual(catalogue['braker3_image'][0]['version'],'3.0.7.6')
        self.assertEqual(catalogue['clinker_image'][0]['version'],'0.0.32')
        self.assertIsNone(catalogue['ncbi_cli'][0]['version'])
        self.assertIsNone(catalogue['pfam'][0]['version'])
        self.assertIsNone(catalogue['fasttree'][0]['version'])

    def test_selected_images_override_default_recipe_versions(self):
        result=display.bootstrap_catalogue(ROOT, {'FUNBGCEX_DOCKER_IMAGE':'example/funbgcex:9.8.7',
            'FUNANNOTATE_IMAGE_URI':'docker://example/funannotate:4.5.6', 'MIBIG_VERSION':'5.0'})
        self.assertEqual(result['funbgcex_image'][0]['version'],'9.8.7')
        self.assertEqual(result['funannotate_image'][0]['version'],'4.5.6')
        self.assertEqual(result['mibig'][0]['version'],'5.0')

    def test_observations_use_selected_runtime_and_do_not_claim_missing_versions(self):
        sys.path.insert(0,str(ROOT/'web'))
        import tool_runtime
        result=display.bootstrap_catalogue(ROOT, {})
        with mock.patch.object(tool_runtime,'observe',return_value={'version':'9.8.7'}) as observe, \
                mock.patch.object(tool_runtime,'bounded_run',return_value=(1,'')):
            display.observe_catalogue(result,ROOT,{},scope='startup')
        self.assertEqual(result['antismash'][0]['basis'],'observed in selected runtime')
        self.assertEqual(result['antismash'][0]['version'],'9.8.7')
        self.assertIsNone(result['pfam'][0]['version'])
        self.assertIsNone(result['ncbi_cli'][1]['version'])
        docker_calls=[call for call in observe.call_args_list if call.kwargs.get('backend')=='docker']
        self.assertEqual({call.kwargs['runtime'] for call in docker_calls},
            {spec.reference for spec in local_image_specs({},ROOT) if spec.scope=='startup'})

    def test_final_owner_artwork_fits_only_without_reflow(self):
        import importlib.util,io,contextlib,os
        spec=importlib.util.spec_from_file_location('banner_art_test', ROOT/'bin/local_instance.py')
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        art=(ROOT/'visuals/ascii_clusterweave.txt').read_text()
        self.assertEqual(set(art)-set('ATGCatgc \n'),set())
        self.assertEqual((max(map(len,art.splitlines())),len(art.splitlines())),(153,26))
        for width in (120,152,153,160):
            output=io.StringIO()
            with mock.patch.object(cli.shutil,'get_terminal_size',return_value=os.terminal_size((width,40))),contextlib.redirect_stdout(output):
                cli.show_banner()
            self.assertEqual(output.getvalue().startswith(art),width>=153)
            self.assertEqual(output.getvalue().count('Please cite:'),1)

if __name__=='__main__':unittest.main()
