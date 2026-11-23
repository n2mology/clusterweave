"""Explicit exclusion, scientific validation and durable queue regression cases."""
import concurrent.futures
import csv
import importlib
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
import cohort_gate as gate

FIELDS = ['genome_id', 'fasta', 'gbk_used', 'gbk_status', 'antismash_status', 'funbgcex_status',
          'taxon_group', 'prediction_method', 'detector_profile', 'funbgcex_applicability']


def fixture(root, calls=1):
    from Bio import SeqIO
    from Bio.Seq import Seq
    from Bio.SeqRecord import SeqRecord
    from Bio.SeqFeature import SeqFeature, FeatureLocation
    result = root / 'data/results/cohort'
    native = result / 'antismash/bacterium'
    native.mkdir(parents=True)
    record = SeqRecord(Seq('ATG' * 100), id='chr', name='chr', description='fixture')
    record.annotations['molecule_type'] = 'DNA'
    if calls:
        record.features = [SeqFeature(FeatureLocation(0, 90), type='region')]
    SeqIO.write([record], native / 'bacterium.bacteria.antismash.gbk', 'genbank')
    if calls:
        SeqIO.write([record[:90]], native / 'chr.region001.gbk', 'genbank')
    (native / 'bacterium.bacteria.antismash.json').write_text(json.dumps({'records': [{'id': 'chr', 'areas': [{'start': 0, 'end': 90}] if calls else []}]}))
    (native / 'index.html').write_text('<html>Native fixture</html>')
    (native / '.done').touch()
    (result / 'input_gbks').mkdir()
    SeqIO.write([record], result / 'input_gbks/bacterium.gbk', 'genbank')
    values = [dict(zip(FIELDS, ['bacterium', '', str(result / 'input_gbks/bacterium.gbk'), 'bacterial_sequence_sanitized', 'ran_ok_sanitized', 'not_applicable_taxon', 'bacteria', 'prodigal', 'antismash', 'not_applicable_taxon'])),
              dict(zip(FIELDS, ['plant', '', '', 'annotation_incompatible', 'not_applicable_taxon', 'not_applicable_taxon', 'plants', 'annotation_incompatible', 'plantismash', 'not_applicable_taxon'])),
              dict(zip(FIELDS, ['fungus', '', '', 'annotation_fallbacks_failed', 'skipped', 'skipped', 'fungi', 'funannotate', 'antismash+funbgcex', 'applicable']))]
    persist(result, values)
    return result, values


def persist(result, values):
    gate.write_rows(result / 'summary_tables/run_manifest.tsv', FIELDS, values)
    gate.write_rows(result / 'summary_tables/genome_taxon_manifest.tsv', ['genome_id', 'taxon_group', 'route_status'],
                    [{'genome_id': r['genome_id'], 'taxon_group': r['taxon_group'], 'route_status': 'accepted'} for r in values])
    directory = result / 'reproducibility/genome_attempts'
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.glob('*'):
        path.unlink()
    for i, row in enumerate(values):
        receipt = directory / (str(i) + '.tsv')
        receipt.write_text('\t'.join(row[k] for k in FIELDS) + '\n')
        receipt.with_suffix('.tsv.exit').write_text('0' if row['gbk_used'] else '1')


class CohortGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.result, self.values = fixture(self.root)
        self.control = self.root / 'cohort/current.json'
        self.identity = {'job_id': 'testjob', 'rerun_count': 0, 'source_sha256': 'a' * 64, 'runtime': 'b' * 64}

    def build(self):
        return gate.build_gate(self.result, self.control, self.identity, {}, 1)

    def accept(self, value=None):
        value = value or self.build()
        return gate.accept(self.control, value['decision_id'], value['included'], value['excluded'], attempt_identity=self.identity)

    def add_zero_record(self, areas=None):
        from Bio import SeqIO
        from Bio.Seq import Seq
        record = next(SeqIO.parse(self.result / 'input_gbks/bacterium.gbk', 'genbank'))
        record.id = record.name = 'empty_chr'; record.seq = Seq('GCC' * 100); record.features = []
        with (self.result / 'input_gbks/bacterium.gbk').open('a') as stream:
            SeqIO.write(record, stream, 'genbank')
        path = self.result / 'antismash/bacterium/bacterium.bacteria.antismash.json'
        value = json.loads(path.read_text())
        value['records'].append({'id':'empty_chr', 'seq':{'data':str(record.seq)}, 'features':[], 'areas':areas or []})
        path.write_text(json.dumps(value))
        return path

    def test_compacted_zero_record_is_successful(self):
        self.add_zero_record()
        value = self.build()
        self.assertEqual(value['included'], ['bacterium'])
        self.assertEqual(value['outcomes'][0]['counts'], {'antismash':1})

    def test_missing_called_record_is_not_excludable(self):
        self.add_zero_record([{'start':0,'end':90}])
        value = self.build()
        self.assertFalse(value['eligible'])
        self.assertIn('Called native record missing', value['outcomes'][0]['reason'])
        self.assertTrue(value['plan']['summary'].startswith('blocked:'))

    def test_corrupt_zero_record_dna_is_refused(self):
        path = self.add_zero_record(); value = json.loads(path.read_text())
        value['records'][-1]['seq']['data'] = 'TTT' * 100
        path.write_text(json.dumps(value))
        self.assertFalse(self.build()['eligible'])

    def test_foreign_zero_record_identity_is_refused(self):
        path = self.add_zero_record(); value = json.loads(path.read_text())
        value['records'][-1]['id'] = 'foreign'
        path.write_text(json.dumps(value))
        self.assertFalse(self.build()['eligible'])

    def test_json_record_order_does_not_change_outcome(self):
        path = self.add_zero_record(); value = json.loads(path.read_text())
        value['records'].reverse(); path.write_text(json.dumps(value))
        self.assertEqual(self.build()['outcomes'][0]['counts'], {'antismash':1})

    def test_duplicate_json_identity_is_refused(self):
        path = self.add_zero_record(); value = json.loads(path.read_text())
        value['records'].append(value['records'][0]); path.write_text(json.dumps(value))
        self.assertFalse(self.build()['eligible'])

    def test_partial_failure_requires_explicit_acceptance(self):
        value = self.build()
        self.assertEqual(value['included'], ['bacterium'])
        self.assertEqual(value['excluded'], ['fungus', 'plant'])
        self.assertEqual(value['state'], 'awaiting_decision')
        with self.assertRaises(gate.GateError): gate.materialize(value, self.root / 'continued')
        accepted = self.accept(value)
        self.assertEqual([r['state'] for r in accepted['outcomes']], ['success', 'failed', 'failed'])

    def test_surviving_outputs_only_and_original_unchanged(self):
        # A failed producer may leave apparently usable partial files. They must
        # never enter the materialized cohort, even when their names look valid.
        partial = self.result / 'antismash/fungus'
        partial.mkdir(); (partial / 'region.gbk').write_text('rejected')
        before = gate.inventory(self.result, ['antismash', 'summary_tables'])
        accepted = self.accept()
        dest = self.root / 'continued'
        gate.materialize(accepted, dest)
        self.assertFalse((dest / 'antismash/fungus').exists())
        self.assertEqual([r['genome_id'] for r in gate.rows(dest / 'summary_tables/run_manifest.tsv')[1]], ['bacterium'])
        self.assertEqual(gate.inventory(self.result, ['antismash', 'summary_tables']), before)
        gate.materialize(accepted, dest)  # restart reuses the exact same workspace
        self.assertEqual(json.loads((dest / 'summary/cohort_outcomes.json').read_text())['excluded'], ['fungus', 'plant'])

    def test_all_failed_direct_acceptance_refused(self):
        persist(self.result, self.values[1:])
        value = self.build()
        self.assertEqual(value['state'], 'failed')
        with self.assertRaises(gate.GateError): self.accept(value)

    def test_successful_zero_is_eligible(self):
        other = self.root / 'zero'; other.mkdir()
        result, _ = fixture(other, calls=0)
        value = gate.build_gate(result, other / 'control.json', self.identity, {}, 1)
        self.assertEqual(value['outcomes'][0]['state'], 'successful_empty')
        self.assertEqual(value['included'], ['bacterium'])
        self.assertTrue(value['plan']['bigscape'].startswith('skipped'))
        self.assertTrue(value['plan']['summary'].startswith('will run'))

    def test_foreign_native_sequence_disallows_override(self):
        from Bio import SeqIO
        from Bio.Seq import Seq
        path = self.result / 'input_gbks/bacterium.gbk'
        record = next(SeqIO.parse(path, 'genbank')); record.seq = Seq('CCC' * 100)
        SeqIO.write(record, path, 'genbank')
        self.assertFalse(self.build()['eligible'])

    def test_incomplete_binding_is_not_published(self):
        value = gate.build_gate(self.result, self.control, self.identity, {}, 1, publish=False)
        self.assertFalse(self.control.exists())
        gate.publish_gate(self.control, value)
        self.assertEqual(gate.load_gate(self.control)['decision_id'], value['decision_id'])

    def test_corrupt_output_disallows_override(self):
        (self.result / 'antismash/bacterium/chr.region001.gbk').write_text('corrupt')
        value = self.build()
        self.assertFalse(value['eligible'])
        with self.assertRaises(gate.GateError): self.accept(value)

    def test_incomplete_output_disallows_override(self):
        (self.result / 'antismash/bacterium/.done').unlink()
        self.assertFalse(self.build()['eligible'])

    def test_stale_output_refuses_decision(self):
        value = self.build()
        (self.result / 'antismash/bacterium/index.html').write_text('changed')
        with self.assertRaises(gate.GateError): self.accept(value)

    def test_stale_receipt_refuses_decision(self):
        value = self.build()
        (self.result / 'reproducibility/genome_attempts/1.tsv.exit').write_text('0')
        with self.assertRaises(gate.GateError): self.accept(value)

    def test_stale_attempt_refuses_decision(self):
        value = self.build(); self.identity = {**self.identity, 'rerun_count': 1}
        with self.assertRaises(gate.GateError): self.accept(value)

    def test_forged_cohort_refused(self):
        value = self.build()
        with self.assertRaises(gate.GateError): gate.accept(self.control, value['decision_id'], ['bacterium', 'plant'], ['fungus'], attempt_identity=self.identity)

    def test_changed_decision_body_refused(self):
        value = self.build(); value['included'].append('plant'); gate.atomic_json(self.control, value)
        with self.assertRaises(gate.GateError): gate.load_gate(self.control)

    def test_unknown_failure_cannot_be_overridden(self):
        self.values[1]['gbk_status'] = 'unclassified_failure'; persist(self.result, self.values)
        self.assertFalse(self.build()['eligible'])

    def test_missing_genome_row_refused(self):
        gate.write_rows(self.result / 'summary_tables/run_manifest.tsv', FIELDS, self.values[:1])
        with self.assertRaises(gate.GateError): self.build()

    def test_duplicate_genome_row_refused(self):
        gate.write_rows(self.result / 'summary_tables/run_manifest.tsv', FIELDS, self.values + self.values[:1])
        with self.assertRaises(gate.GateError): self.build()

    def test_missing_exit_receipt_refused(self):
        (self.result / 'reproducibility/genome_attempts/1.tsv.exit').unlink()
        with self.assertRaises(OSError): self.build()

    def test_symlink_output_refused(self):
        (self.result / 'antismash/bacterium/escape').symlink_to('/etc/passwd')
        with self.assertRaises(gate.GateError): self.build()

    def test_taxon_mismatch_refused(self):
        fields, values = gate.rows(self.result / 'summary_tables/genome_taxon_manifest.tsv')
        values[0]['taxon_group'] = 'fungi'; gate.write_rows(self.result / 'summary_tables/genome_taxon_manifest.tsv', fields, values)
        with self.assertRaises(gate.GateError): self.build()

    def test_duplicate_acceptance_is_identical(self):
        value = self.build()
        self.assertEqual(self.accept(value), self.accept(value))
        self.assertEqual(len(list(self.control.parent.glob('accepted-*.json'))), 1)

    def test_nonzero_success_receipt_is_failure(self):
        (self.result / 'reproducibility/genome_attempts/0.tsv.exit').write_text('1')
        self.assertFalse(self.build()['eligible'])

    def test_shared_failure_never_becomes_complete(self):
        persist(self.result, self.values[:1])
        with self.assertRaises(gate.GateError): self.build()

    def test_no_approved_target_blocks_nplinker(self):
        value = gate.build_gate(self.result, self.control, self.identity, {'run_nplinker': True, 'target_genome': 'fungus'}, 1)
        self.assertTrue(value['plan']['nplinker'].startswith('blocked'))

    def test_restart_load_preserves_exact_decision(self):
        value = self.build()
        self.assertEqual(gate.load_gate(self.control), value)
        self.assertEqual(gate.public_gate(value)['outcomes'], value['outcomes'])


class QueueContinuationTests(CohortGateTests):
    # This class inherits no scientific tests in accounting; the test loader
    # below limits it to explicitly named queue cases.
    def setUp(self):
        super().setUp()
        with mock.patch.dict(os.environ, {'DATA_DIR': str(self.root)}):
            import job_store
            import cohort_resume
        self.store, self.resume = job_store, cohort_resume
        self.jobs = self.root / 'jobs'; self.jobs.mkdir(exist_ok=True)
        self.queue = self.root / 'queue'; self.queue.mkdir(exist_ok=True)
        self.jobroot = self.jobs / 'testjob'; self.jobroot.mkdir()
        self.control = self.jobroot / 'cohort/current.json'
        for module, key, value in [(job_store, 'DATA_DIR', self.root), (job_store, 'JOBS_DIR', self.jobs),
                                   (job_store, 'QUEUE_DIR', self.queue)]:
            patcher = mock.patch.object(module, key, value); patcher.start(); self.addCleanup(patcher.stop)
        self.value = self.build()
        self.store.write_job({'id': 'testjob', 'name': 'fixture', 'status': 'awaiting_decision', 'stage': 'awaiting_decision', 'cpus': 1, 'settings': {}, 'rerun_count': 0})
        self.payload = {k: self.value[k] for k in ['decision_id', 'included', 'excluded']}

    def test_queue_duplicate_concurrent_clicks_publish_once(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.resume.resume_job('testjob', self.payload), range(4)))
        self.assertEqual(sum(not r['duplicate'] for r in results), 1)
        self.assertEqual(len(list(self.queue.glob('*.json'))), 1)
        self.assertEqual(self.store.read_job('testjob')['status'], 'pending')

    def test_queue_recovery_after_acceptance_before_metadata(self):
        self.accept(self.value)
        self.assertTrue(self.resume.recover_accepted_decision(self.store.read_job('testjob')))
        self.assertEqual(self.store.read_job('testjob')['status'], 'pending')
        self.assertFalse(self.resume.recover_accepted_decision(self.store.read_job('testjob')))

    def test_queue_no_automatic_acceptance(self):
        self.assertFalse(self.resume.recover_accepted_decision(self.store.read_job('testjob')))
        self.assertFalse(list(self.queue.glob('*.json')))

    def test_queue_forged_all_fail_request_refused(self):
        persist(self.result, self.values[1:]); self.value = self.build()
        payload = {k: self.value[k] for k in ['decision_id', 'included', 'excluded']}
        with self.assertRaises(gate.GateError): self.resume.resume_job('testjob', payload)
        self.assertFalse(list(self.queue.glob('*.json')))

    def test_queue_rerun_invalidates_approval(self):
        meta = self.store.read_job('testjob'); meta['rerun_count'] = 1; self.store.write_job(meta)
        with self.assertRaises(gate.GateError): self.resume.resume_job('testjob', self.payload)


def load_tests(loader, tests, pattern):
    result = unittest.TestSuite(loader.loadTestsFromTestCase(CohortGateTests))
    result.addTests(QueueContinuationTests(name) for name in loader.getTestCaseNames(QueueContinuationTests) if name.startswith('test_queue_'))
    result.addTests(loader.loadTestsFromTestCase(LocalContinuationTests))
    return result

class LocalContinuationTests(unittest.TestCase):
    def test_local_identity_and_idempotent_completion(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('local_cohort_control', ROOT / 'bin/cohort_control.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'DATA_ROOT': directory, 'PROJECT_NAME': 'cohort'}, clear=True):
            root = Path(directory); result, _ = fixture(root)
            control = root / 'control/current.json'; context = root / 'control/context.json'
            identity = module.context(result)['identity']
            value = gate.build_gate(result, control, identity, {}, 1)
            args = ['cohort_control.py', 'continue', '--results', str(result), '--control', str(control), '--context', str(context), '--decision', value['decision_id']]
            import io
            with mock.patch.object(sys, 'argv', args), mock.patch('sys.stdout', new_callable=io.StringIO) as output:
                module.main(); self.assertIn('RUN_STAGE_ANNOTATION=0', output.getvalue())
            gate.atomic_json(control.parent / 'local-completed.json', {'decision_id':value['decision_id']})
            with mock.patch.object(sys, 'argv', args), self.assertRaises(SystemExit) as exc:
                module.main()
            self.assertEqual(exc.exception.code, 76)

    def test_local_changed_input_refuses_acceptance(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('local_cohort_control', ROOT / 'bin/cohort_control.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'DATA_ROOT': directory, 'PROJECT_NAME': 'cohort'}, clear=True):
            root = Path(directory); result, _ = fixture(root)
            control = root / 'control/current.json'
            value = gate.build_gate(result, control, module.context(result)['identity'], {}, 1)
            source = root / 'genomes/bacteria/cohort/bacterium.fna'; source.parent.mkdir(parents=True); source.write_text('>new\nACGT\n')
            with mock.patch.object(sys, 'argv', ['cohort_control.py', 'continue', '--results', str(result), '--control', str(control), '--context', str(root/'context.json'), '--decision', value['decision_id']]), self.assertRaises(gate.GateError):
                module.main()
