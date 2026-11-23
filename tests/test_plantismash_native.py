"""Extracted clusters must preserve the complete native parent feature slice."""
import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.SeqFeature import SeqFeature, SimpleLocation, CompoundLocation, BeforePosition

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import plantismash_native as native


class ExtractedNativeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / 'native'
        self.folder.mkdir()
        record = SeqRecord(Seq('A' * 1000), id='plant', name='plant', description='generic native fixture')
        record.annotations['molecule_type'] = 'DNA'
        location = CompoundLocation([SimpleLocation(400, 600, -1), SimpleLocation(BeforePosition(200), 300, -1)])
        cds = SeqFeature(location, type='CDS', qualifiers={
            'translation': ['MA'], 'protein_id': ['protein1'], 'codon_start': ['2'],
            'transl_table': ['1'], 'exception': ['source-declared exception'],
            'note': ['partial source annotation'], 'sec_met': ['Domain: example']})
        record.features = [SeqFeature(SimpleLocation(100, 900), type='cluster', qualifiers={'product': ['terpene']}),
                           cds, SeqFeature(SimpleLocation(410, 460, -1), type='aSDomain', qualifiers={'domain': ['example'], 'score': ['1.25']})]
        self.record = record
        self.original = {'records': [{'original_id': record.id, 'original_record_ordinal': 1,
            'sequence_sha256': native.sha(str(record.seq)), 'length': len(record),
            'CDS': [{'feature_key': 'plant:R1:F1', 'feature_ordinal': 1, 'location': native.loc(cds),
                     'tuple': native.feature_tuple(cds), 'qualifiers': copy.deepcopy(cds.qualifiers),
                     'translation_sha256': native.sha('MA')}]}]}
        SeqIO.write(record, self.folder / 'plant.final.gbk', 'genbank')
        self.cluster = record[100:900]
        (self.folder / 'index.html').write_text('<html>generic fixture</html>')
        completion = {'schema': 'plantismash-private-completion-v1', 'completed': True,
            'producer': native.PRODUCER, 'successful_hmm_searches': 93, 'evaluated_records': ['plant'],
            'records': [{'original_id': 'plant', 'native_id': 'plant', 'sequence_sha256': native.sha(str(record.seq)), 'CDS_count': 1}]}
        (self.folder / 'native-completion.json').write_text(json.dumps(completion))
        (self.root / 'native-exit.json').write_text(json.dumps({'exit_code': 0, 'producer': native.PRODUCER}))
        self.repack()

    def repack(self):
        SeqIO.write(self.cluster, self.folder / 'plant.cluster001.gbk', 'genbank')
        with zipfile.ZipFile(self.folder / 'plant.zip', 'w') as archive:
            for path in sorted(self.folder.iterdir()):
                if path.name in {'plant.zip', 'native-completion.json'}:
                    continue
                info = zipfile.ZipInfo(path.name, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
        native.validate_archive(self.folder)

    def test_relative_compound_partial_exception_is_preserved(self):
        result = native.read_native(self.original, self.folder)
        self.assertTrue(result['valid'], result)
        self.assertEqual(result['extracted_clusters'][0]['feature_parity']['expected_features'], 3)

    def test_self_consistent_archive_rejects_missing_duplicate_and_changed_features(self):
        original = copy.deepcopy(self.cluster)
        def missing(record): record.features.pop(1)
        def duplicate(record): record.features.append(copy.deepcopy(record.features[1]))
        def domain_missing(record): record.features.pop(2)
        def strand(record): record.features[1].location = record.features[1].location._flip(len(record))
        def shifted(record): record.features[1].location += 1
        def compound_order(record): record.features[1].location = CompoundLocation(list(reversed(record.features[1].location.parts)))
        changes = {'missing': missing, 'duplicate': duplicate, 'domain_missing': domain_missing,
                   'strand': strand, 'shifted': shifted, 'compound_order': compound_order}
        for key in ['translation', 'protein_id', 'codon_start', 'transl_table', 'exception', 'sec_met']:
            changes[key] = lambda record, key=key: record.features[1].qualifiers.update({key: ['changed']})
        changes['domain'] = lambda record: record.features[2].qualifiers.update({'domain': ['changed']})
        for name, change in changes.items():
            with self.subTest(name=name):
                self.cluster = copy.deepcopy(original)
                change(self.cluster)
                self.repack()
                result = native.read_native(self.original, self.folder)
                self.assertFalse(result['valid'])
                self.assertEqual(result['outcome'], 'FAILED_OUTPUT_CONTRACT')
                self.assertTrue(any('extracted_cluster_feature_mismatch' in reason for reason in result['reasons']), result)


if __name__ == '__main__':
    unittest.main()


class NativeRetryTests(unittest.TestCase):
    def test_failed_retry_quarantines_previous_comparison_inputs(self):
        import argparse
        import plantismash_runtime as runtime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native_root = root / 'plantismash' / 'plant'
            native_root.mkdir(parents=True)
            (native_root / 'outcome.json').write_text('{"calls": 1}')
            staged = root / 'native_bgc' / 'plant'
            staged.mkdir(parents=True)
            (staged / 'previous.gbk').write_bytes(b'previous accepted call')
            args = argparse.Namespace(results=root, genome='plant')
            runtime.mark_failed(args)
            self.assertFalse(staged.exists())
            attempt, = (root / 'plantismash_attempts' / 'plant').iterdir()
            self.assertEqual((attempt / 'comparison-inputs/previous.gbk').read_bytes(), b'previous accepted call')
            self.assertEqual(json.loads((attempt / 'outcome.json').read_text())['calls'], 1)
            self.assertIsNone(json.loads((native_root / 'outcome.json').read_text())['calls'])

class RuntimeIdentityTests(unittest.TestCase):
    def test_supported_identity_reports_actual_accepted_bytes(self):
        from unittest import mock
        import plantismash_runtime as runtime
        import plantismash_native as native
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            sif = Path(directory) / 'plant.sif'
            sif.write_bytes(b'unit identity fixture')
            for identity in native.ACCEPTED_SIF_SHA256:
                def digest(path):
                    return identity if Path(path) == sif else '69c11aff0651fbd446d3df9325d455b9bb1b5960b8333f21a9a4becdf9063836'
                with mock.patch.object(runtime, 'check_profile'), mock.patch.object(runtime, 'digest', side_effect=digest), mock.patch.object(runtime.shutil, 'which', return_value='/usr/bin/apptainer'), mock.patch.object(runtime.subprocess, 'run', return_value=mock.Mock(stdout='apptainer version 1.5.5\n')):
                    result = runtime.runtime_identity(sif, '/usr/bin/apptainer')
                self.assertEqual(result['sif_sha256'], identity)

    def test_reduced_profile_engines_cannot_execute_the_extras_profile(self):
        from unittest import mock
        import plantismash_runtime as runtime
        import plantismash_native as native
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            sif = Path(directory) / 'plant.sif'; sif.write_bytes(b'historical identity fixture')
            for identity in [native.REDUCED_PROFILE_SIF_SHA256, native.LEGACY_SIF_SHA256]:
                with mock.patch.object(runtime, 'check_profile'), mock.patch.object(runtime, 'digest', return_value=identity), mock.patch.object(runtime.subprocess, 'run') as execute:
                    with self.assertRaisesRegex(ValueError, 'different identity'): runtime.runtime_identity(sif, '/usr/bin/apptainer')
                    execute.assert_not_called()

    def test_unknown_identity_is_rejected_before_execution(self):
        from unittest import mock
        import plantismash_runtime as runtime
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            sif = Path(directory) / 'plant.sif'
            sif.write_bytes(b'unrecognized SIF')
            with mock.patch.object(runtime, 'check_profile'), mock.patch.object(runtime.subprocess, 'run') as execute:
                with self.assertRaisesRegex(ValueError, 'different identity'):
                    runtime.runtime_identity(sif, '/usr/bin/apptainer')
            execute.assert_not_called()

    def test_cli_accepts_pinned_absolute_engine_path(self):
        from unittest import mock
        import plantismash_runtime as runtime
        with mock.patch.object(runtime.sys, 'argv', ['plantismash_runtime.py', 'check', '--engine', '/usr/bin/apptainer', '--sif', '/prepared/plant.sif']), mock.patch.object(runtime, 'check_runtime') as check:
            self.assertEqual(runtime.main(), 0)
        check.assert_called_once_with(Path('/prepared/plant.sif'), '/usr/bin/apptainer')
