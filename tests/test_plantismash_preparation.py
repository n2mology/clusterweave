from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('plant_operator_preparation',ROOT/'bin/prepare_plantismash.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class OperatorPreparationTests(unittest.TestCase):
    def test_reserve_includes_prospective_working_space(self):
        with mock.patch.object(module.shutil,'disk_usage',return_value=SimpleNamespace(free=40*2**30)):
            module.require_space(Path('/tmp'),30*2**30,10*2**30)
            with self.assertRaises(ValueError):module.require_space(Path('/tmp'),30*2**30,11*2**30)

    def test_shared_or_retagged_stage_is_preserved(self):
        stage={'Id':'sha256:'+'a'*64,'RepoTags':['attempt-builder','retained-rollback'],'Parent':''}
        final={'Id':'sha256:'+'b'*64}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(module.subprocess,'check_output',side_effect=[json.dumps([stage]).encode(),json.dumps([final]).encode()]), mock.patch.object(module.subprocess,'run') as execute:
            with self.assertRaisesRegex(ValueError,'retained tag'):module.retire_preparation_stage('attempt-builder','attempt-final',Path(tmp))
            execute.assert_not_called()

    def test_referenced_stage_or_dependency_conflict_is_never_forced(self):
        stage={'Id':'sha256:'+'a'*64,'RepoTags':['attempt-builder'],'Parent':'sha256:'+'c'*64}
        final={'Id':'sha256:'+'b'*64}
        for referenced in [True,False]:
            def output(command,**kwargs):
                if command[:3]==['docker','image','inspect']:return json.dumps([stage if command[3]=='attempt-builder' else final]).encode()
                if command[:3]==['docker','ps','-aq']:return 'active-container' if referenced else ''
                return b'preserved stage history\n'
            def execute(command,**kwargs):
                if command[:3]==['docker','image','inspect']:return SimpleNamespace(returncode=0,stdout=json.dumps([stage]))
                return SimpleNamespace(returncode=1,stdout='',stderr='image has a retained dependent child')
            with tempfile.TemporaryDirectory() as tmp, mock.patch.object(module.subprocess,'check_output',side_effect=output), mock.patch.object(module.subprocess,'run',side_effect=execute) as run:
                root=Path(tmp);(root/'preparation.log').write_text(' ---> aaaaaaaaaaaa\n')
                module.retire_preparation_stage('attempt-builder','attempt-final',root)
                removals=[c.args[0] for c in run.call_args_list if c.args[0][:3]==['docker','image','rm']]
                self.assertEqual(len(removals),0 if referenced else 1)
                self.assertFalse(any('--force' in c or '-f' in c for c in removals))
                receipt=json.loads((root/'stage-retirement/receipt.json').read_text())
                self.assertEqual(receipt['final_image'],final['Id'])
                if not referenced:self.assertEqual(receipt['operations'][0]['returncode'],1)

if __name__=='__main__':unittest.main()
