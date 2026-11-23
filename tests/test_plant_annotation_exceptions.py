"""Exact RefSeq discrepancy and unmodified supplied-protein admission regressions."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'web'), str(ROOT / 'bin')]
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import CompoundLocation, SimpleLocation, SeqFeature
from Bio.SeqRecord import SeqRecord
from plant_annotation import check_translation, inspect_plant_annotation, PlantAnnotationError
import runtime_capabilities


def exact_record():
    data = json.loads((ROOT / 'tests/fixtures/plant_annotation/NC_037285.2_XP_024463069.1.json').read_text())
    origin = data['genomic_start']
    record = SeqRecord(Seq(data['genomic_sequence']), id=data['record'], name=data['record'],
                       description='Exact genomic locus crop; original coordinates retained in fixture')
    record.annotations['molecule_type'] = 'DNA'
    parts = [SimpleLocation(p['start'] - origin, p['end'] - origin, p['strand']) for p in data['parts']]
    record.features = [SeqFeature(CompoundLocation(parts), type='CDS', qualifiers=copy.deepcopy(data['qualifiers']))]
    return data, record


def genbank(record):
    handle = io.StringIO()
    SeqIO.write(record, handle, 'genbank')
    return handle.getvalue().encode()


class PlantExceptionTests(unittest.TestCase):
    def test_exact_refseq_exception_retains_genomic_bases_and_peptide(self):
        data, record = exact_record()
        self.assertEqual(hashlib.sha256(str(record.seq).encode()).hexdigest(), data['genomic_sequence_sha256'])
        self.assertEqual(str(record.features[0].extract(record.seq)), data['extracted_cds'])
        raw = genbank(record)
        admission = inspect_plant_annotation(io.BytesIO(raw))
        check = admission['cds_checks'][0]
        self.assertEqual(check['status'], 'SOURCE_EXCEPTION')
        self.assertFalse(check['independent_truth'])
        self.assertEqual(check['length_nt'], 1198)
        self.assertEqual(check['protein_id'], 'XP_024463069.1')
        self.assertEqual(check['gene'], 'LOC7487044')
        self.assertEqual(raw, genbank(record))
        self.assertEqual(check_translation(record.features[0], record.seq)['status'], 'SOURCE_EXCEPTION')
        self.assertEqual(hashlib.sha256(record.features[0].qualifiers['translation'][0].encode()).hexdigest(), data['translation_sha256'])

    def test_length_guard_requires_the_declared_indel_exception(self):
        for exception in (None, ['nonconsensus splice site'], ['source assertion'], [''],
                          ['unclassified translation discrepancy', 'duplicate']):
            with self.subTest(exception=exception):
                _, record = exact_record()
                if exception is None:
                    del record.features[0].qualifiers['exception']
                else:
                    record.features[0].qualifiers['exception'] = exception
                record.features[0].qualifiers['transl_except'] = ['(pos:1..3,aa:OTHER)']
                with self.assertRaisesRegex(PlantAnnotationError, 'NC_037285.2.*LOC7487044.*XP_024463069.1.*complete_cds_has_partial_codon') as caught:
                    inspect_plant_annotation(io.BytesIO(genbank(record)))
                self.assertEqual(caught.exception.receipt['state'], 'ANNOTATION_INCOMPATIBLE')

    def test_no_cds_scaffold_is_retained_and_explicitly_not_evaluated(self):
        from plantismash_native import original_inventory, crosswalk
        _, record = exact_record()
        scaffold = SeqRecord(Seq('ACGT' * 400), id='no_cds_scaffold', name='no_cds_scaffold')
        scaffold.annotations['molecule_type'] = 'DNA'
        raw = genbank(record) + genbank(scaffold)
        admission = inspect_plant_annotation(io.BytesIO(raw))
        self.assertEqual(len(admission['records']), 2)
        self.assertEqual(admission['records'][1]['analysis_state'], 'not_evaluated_no_cds')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.gbk';source.write_bytes(raw)
            original = original_inventory(source, 'plant')
        self.assertEqual(len(original['records']), 2)
        mapped = crosswalk(original, [record])
        self.assertTrue(mapped['bijective'])
        self.assertEqual(len(mapped['not_evaluated_records']), 1)
        self.assertIsNone(mapped['not_evaluated_records'][0]['calls'])
        self.assertFalse(crosswalk(original, [])['bijective'])
        self.assertFalse(crosswalk(original, [record, scaffold])['bijective'])
        self.assertEqual(raw, genbank(record) + genbank(scaffold))

    def test_exception_cannot_excuse_malformed_cds(self):
        for key, value in [('translation', ['MA*Q']), ('codon_start', ['4']), ('transl_table', ['9999'])]:
            _, record = exact_record()
            record.features[0].qualifiers[key] = value
            self.assertEqual(check_translation(record.features[0], record.seq)['status'], 'FAIL')
        _, record = exact_record()
        record.seq = Seq('!' + str(record.seq)[1:])
        self.assertEqual(check_translation(record.features[0], record.seq)['reason'], 'malformed_cds')
        _, record = exact_record()
        record.features[0].location = SimpleLocation(0, len(record) + 1, 1)
        self.assertEqual(check_translation(record.features[0], record.seq)['reason'], 'malformed_cds')

    def test_unexplained_in_frame_mismatch_and_malformed_codon_exceptions_fail(self):
        for qualifiers in ({'exception': ['unrelated source assertion']},
                           {'exception': ['nonconsensus splice site']},
                           {'transl_except': ['junk']},
                           {'transl_except': ['(pos:1..4,aa:OTHER)']},
                           {'transl_except': ['(pos:20..22,aa:OTHER)']},
                           {'transl_except': ['(pos:1..3,aa:invalid)']}):
            feature = SeqFeature(SimpleLocation(0, 9, 1), type='CDS',
                                 qualifiers={'translation': ['MV'], **qualifiers})
            self.assertEqual(check_translation(feature, Seq('ATGGCTTAA'))['status'], 'FAIL')
        for qualifiers in ({'exception': ['RNA editing']},
                           {'transl_except': ['(pos:4..6,aa:OTHER)']},
                           {'transl_except': ['(pos:join(4, 5..6), aa:OTHER)']}):
            feature = SeqFeature(SimpleLocation(0, 9, 1), type='CDS',
                                 qualifiers={'translation': ['MV'], **qualifiers})
            self.assertEqual(check_translation(feature, Seq('ATGGCTTAA'))['status'], 'SOURCE_EXCEPTION')

    def test_missing_translation_is_specific_incompatible_supplied_annotation(self):
        _, record = exact_record()
        del record.features[0].qualifiers['translation']
        with self.assertRaisesRegex(PlantAnnotationError, 'XP_024463069.1.*missing or nonunique translation') as caught:
            inspect_plant_annotation(io.BytesIO(genbank(record)))
        self.assertEqual(caught.exception.receipt['state'], 'ANNOTATION_INCOMPATIBLE')
        record.features = []
        with self.assertRaises(PlantAnnotationError) as caught:
            inspect_plant_annotation(io.BytesIO(genbank(record)))
        self.assertEqual(caught.exception.receipt['state'], 'ANNOTATION_REQUIRED')

    def test_api_keeps_record_protein_and_reason(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'DATA_DIR': directory}):
            import app
        _, record = exact_record()
        del record.features[0].qualifiers['exception']
        error, _ = app.build_submission_taxon_routing([{'filename': 'populus.gbk', 'content': genbank(record)}], {}, 'plants', '')
        for text in ['Supplied plant annotation incompatible', 'NC_037285.2', 'XP_024463069.1', 'complete_cds_has_partial_codon']:
            self.assertIn(text, error)
        self.assertNotIn('Annotation required', error)

    def test_cli_and_shell_preserve_incompatible_reason_and_null_count(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            _, record = exact_record()
            del record.features[0].qualifiers['exception']
            source = work / 'input.gbk';source.write_bytes(genbank(record))
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', SCRIPT_DIR=str(ROOT), per_tmp=directory,
                       RESULTS_ROOT=str(work / 'results'), PYTHON=sys.executable, SOURCE=str(source))
            script = '''
repository_helper_python_exec() { "$PYTHON" "$@"; }
genome_stage_progress() { printf '%s\\n' "$*"; }
write_genome_manifest_row() { printf '%s\\n' "$*"; }
source "$SCRIPT_DIR/detection_plantismash.sh"
run_plantismash_genome plant "$SOURCE" '' "$per_tmp/staged.gbk" row
'''
            result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('XP_024463069.1', result.stdout)
            self.assertIn('complete_cds_has_partial_codon', result.stdout)
            self.assertIn('annotation_incompatible', result.stdout)
            outcome = json.loads((work / 'results/plantismash/plant/outcome.json').read_text())
            self.assertEqual(outcome['state'], 'ANNOTATION_INCOMPATIBLE')
            self.assertIsNone(outcome['calls'])
            self.assertEqual(outcome['annotation_error']['protein_id'], 'XP_024463069.1')
            self.assertEqual(source.read_bytes(), genbank(record))


class ReadinessProbeTests(unittest.TestCase):
    def test_success_cache_expires_and_invalidates_on_asset_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            sif = Path(directory) / 'plant.sif';sif.write_bytes(b'old')
            engine = Path(directory) / 'apptainer';engine.write_bytes(b'engine')
            env = dict(PLANTISMASH_SIF=str(sif), PLANTISMASH_ENGINE=str(engine), CLUSTERWEAVE_ROOT=str(ROOT))
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(runtime_capabilities, '_PLANT_PROBE_CACHE', None), mock.patch.object(runtime_capabilities.time, 'monotonic', return_value=100) as clock, mock.patch.object(runtime_capabilities.shutil, 'which', return_value=str(engine)), mock.patch.object(runtime_capabilities.subprocess, 'run', return_value=mock.Mock(returncode=0, stderr='')) as run:
                first = runtime_capabilities.plantismash_capability()
                first['available'] = False
                self.assertTrue(runtime_capabilities.plantismash_capability()['available'])
                self.assertEqual(run.call_count, 1)
                sif.write_bytes(b'changed')
                runtime_capabilities.plantismash_capability();self.assertEqual(run.call_count, 2)
                clock.return_value = 161
                runtime_capabilities.plantismash_capability();self.assertEqual(run.call_count, 3)
                sif.unlink()
                self.assertFalse(runtime_capabilities.plantismash_capability()['available'])

    def test_failed_probe_is_rechecked_after_five_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            sif = Path(directory) / 'plant.sif';sif.write_bytes(b'sif')
            env = dict(PLANTISMASH_SIF=str(sif), PLANTISMASH_ENGINE='apptainer')
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(runtime_capabilities, '_PLANT_PROBE_CACHE', None), mock.patch.object(runtime_capabilities.time, 'monotonic', return_value=100) as clock, mock.patch.object(runtime_capabilities.shutil, 'which', return_value='/usr/bin/apptainer'), mock.patch.object(runtime_capabilities.subprocess, 'run', return_value=mock.Mock(returncode=1, stderr='isolation failed')) as run:
                self.assertFalse(runtime_capabilities.plantismash_capability()['available'])
                runtime_capabilities.plantismash_capability();self.assertEqual(run.call_count, 1)
                clock.return_value = 106
                runtime_capabilities.plantismash_capability();self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
