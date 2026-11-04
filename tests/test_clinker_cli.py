import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin/clinker_cli.py"
spec = importlib.util.spec_from_file_location("clinker_cli_test", HELPER)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
try:
    from Bio import SeqIO
    from Bio.Seq import Seq
    from Bio.SeqFeature import CompoundLocation, SeqFeature, SimpleLocation
    from Bio.SeqRecord import SeqRecord
except ImportError:
    SeqIO = None


class ClinkerDiagnosticsTests(unittest.TestCase):
    def test_counted_fallback_preserves_other_diagnostics_stdout_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = root / "clinker"
            command.write_text(
                f"#!{sys.executable}\nimport sys\n"
                "print('alignment output')\n"
                "for _ in range(2000):\n"
                " print('[12:34:56] WARNING - Could not find parent gene of <unknown id>. Using coding sequence coordinates instead.', file=sys.stderr)\n"
                "print('[12:34:56] WARNING - circular_test is circular, checking for genes spanning the origin', file=sys.stderr)\n"
                "print('[12:34:56] WARNING - To disable this behaviour, use --dont_set_origin', file=sys.stderr)\n"
                "print('WARNING - Found no CDS features', file=sys.stderr)\n"
                "print('ERROR - Invalid protein translation', file=sys.stderr)\n"
                "sys.exit(7)\n"
            )
            command.chmod(0o755)
            result = subprocess.run(
                [sys.executable, '-B', str(HELPER), str(root / 'unreadable.gbk'), '--', '-f'],
                env={**os.environ, 'PATH': str(root)}, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 7)
            self.assertEqual(result.stdout, 'alignment output\n')
            self.assertNotIn('Could not find parent gene', result.stderr)
            self.assertIn('[WARN] clinker used CDS coordinates for 2000 features', result.stderr)
            self.assertIn('[INFO] clinker checked circular origins for 1 records; origin correction remains enabled.', result.stderr)
            self.assertNotIn('To disable this behaviour', result.stderr)
            self.assertIn('WARNING - Found no CDS features', result.stderr)
            self.assertIn('ERROR - Invalid protein translation', result.stderr)

    def test_gff_parent_warnings_are_not_reclassified(self):
        warning = 'WARNING - Could not find parent gene of a. Using coding sequence coordinates instead.\n'
        child = mock.MagicMock()
        child.stderr.__enter__.return_value = None
        child.stderr.__iter__.return_value = iter([warning, warning])
        child.wait.return_value = -15
        with mock.patch.object(cli.subprocess, 'Popen', return_value=child), mock.patch('sys.stderr') as stderr:
            status = cli.main(['input.gff3', '--', '-f'])
        self.assertEqual(status, 143)
        self.assertEqual(stderr.write.call_args_list, [mock.call(warning), mock.call(warning)])

    def test_missing_executable_and_invalid_adapter_arguments(self):
        with mock.patch.object(cli.subprocess, 'Popen', side_effect=FileNotFoundError('clinker')), mock.patch('sys.stderr'):
            self.assertEqual(cli.main(['input.gbk', '--']), 127)
            self.assertEqual(cli.main(['input.gbk']), 2)
            self.assertEqual(cli.main(['--']), 2)


@unittest.skipIf(SeqIO is None, 'Biopython is required for input policy checks')
class ClinkerInputPolicyTests(unittest.TestCase):
    def fixture(self, root, name, *, wrapping=False, gene=False, reverse=False, circular=True):
        r = SeqRecord(Seq('ATG' * 400), id=name, name=name, description='synthetic panel')
        r.annotations = {'molecule_type': 'DNA', 'topology': 'circular' if circular else 'linear'}
        strand = -1 if reverse else 1
        parts = [SimpleLocation(1050, 1200, strand), SimpleLocation(0, 150, strand)]
        if reverse:
            parts.reverse()
        location = CompoundLocation(parts) if wrapping else SimpleLocation(90, 390, strand)
        r.features = [SeqFeature(location, type='gene' if gene else 'CDS', qualifiers={'locus_tag': [name]})]
        path = root / (name + '.gbk')
        SeqIO.write([r], path, 'genbank')
        return str(path)

    def test_origin_noop_only_for_all_verified_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plain = self.fixture(root, 'plain')
            forward = self.fixture(root, 'forward', wrapping=True)
            reverse = self.fixture(root, 'reverse', wrapping=True, reverse=True)
            gene = self.fixture(root, 'gene', wrapping=True, gene=True)
            self.assertEqual(cli.input_policy([plain]), (True, True))
            self.assertEqual(cli.input_policy([plain, forward]), (False, True))
            self.assertEqual(cli.input_policy([plain, gene]), (False, True))
            self.assertEqual(cli.input_policy([reverse]), (False, True))
            self.assertEqual(cli.input_policy([plain, str(root / 'absent.gbk')]), (False, False))
            self.assertEqual(cli.input_policy([plain, 'input.gff3']), (False, False))
            self.assertEqual(cli.input_policy([]), (False, False))

    def test_flags_and_informational_summary_for_cds_only_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = self.fixture(Path(tmp), 'plain')
            wrapped = self.fixture(Path(tmp), 'wrapped', wrapping=True)
            warning = 'WARNING - Could not find parent gene of a. Using coding sequence coordinates instead.\n'
            for path, expected in [(plain, True), (wrapped, False)]:
                with self.subTest(path=path):
                    child = mock.MagicMock()
                    child.stderr.__iter__.return_value = iter([warning])
                    child.wait.return_value = 0
                    with mock.patch.object(cli.subprocess, 'Popen', return_value=child) as popen, mock.patch('sys.stderr') as stderr:
                        self.assertEqual(cli.main([path, '--', '-f']), 0)
                    self.assertEqual('--dont_set_origin' in popen.call_args.args[0], expected)
                    self.assertIn('[INFO] clinker used CDS coordinates for 1 features', ''.join(str(c) for c in stderr.write.call_args_list))

    def test_existing_gene_annotations_keep_unmatched_fallback_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root, 'partial')
            r = SeqIO.read(path, 'genbank')
            r.features.append(SeqFeature(SimpleLocation(600, 900), type='gene'))
            SeqIO.write([r], path, 'genbank')
            self.assertEqual(cli.input_policy([path]), (True, False))


class GeneratedClinkerDiagnosticsTests(unittest.TestCase):
    def test_same_adapter_runs_in_all_generated_backends(self):
        spec = importlib.util.spec_from_file_location('clinker_staging_adapter_test', ROOT / 'bin/stage_clinker_panels.py')
        stage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stage)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            panel = root / "panel's space"
            panel.mkdir()
            gbk = panel / "input's space.gbk"
            gbk.write_text('LOCUS invalid\n//\n')
            stage.write_run_panel_script(panel, [gbk], root, ROOT)
            self.assertEqual((panel / 'clinker_cli.py').read_bytes(), HELPER.read_bytes())
            fake = root / 'fake'
            fake.mkdir()
            (fake / 'clinker').write_text(
                f'#!{sys.executable}\nimport json,os,sys\n'
                'open(os.environ["CLINKER_CALL"], "w").write(json.dumps(sys.argv[1:]))\n'
            )
            (fake / 'singularity').write_text('#!/bin/bash\nshift 4\nexec "$@"\n')
            (fake / 'docker').write_text('#!/bin/bash\nwhile [[ "$1" != python3 ]]; do shift; done\nexec "$@"\n')
            for name in ('clinker', 'singularity', 'docker'):
                (fake / name).chmod(0o755)
            sif = root / 'prepared.sif'
            sif.touch()
            base = {**os.environ, 'PATH': str(fake) + os.pathsep + os.environ['PATH'], 'CLINKER_CALL': str(root / 'call.json')}
            for backend, settings in [
                ('local', {'PREFER_CLINKER_CONTAINER': '0'}),
                ('singularity', {'PREFER_CLINKER_CONTAINER': '1', 'CLINKER_ENGINE': str(fake / 'singularity'), 'CLINKER_SIF_PATH': str(sif)}),
                ('docker', {'PREFER_CLINKER_CONTAINER': '1', 'CLINKER_DOCKER_IMAGE': 'prepared/clinker:1'}),
            ]:
                with self.subTest(backend=backend):
                    result = subprocess.run(['bash', str(panel / 'run_panel.sh')], env={**base, **settings}, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    args = json.loads((root / 'call.json').read_text())
                    self.assertEqual(args[0], str(gbk))
                    self.assertIn('-ufo', args)
                    self.assertIn('-f', args)


if __name__ == '__main__':
    unittest.main()
