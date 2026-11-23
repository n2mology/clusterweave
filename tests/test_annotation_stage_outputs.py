import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('annotation_stage_outputs', Path(__file__).resolve().parents[1] / 'bin/annotation_stage_outputs.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AnnotationStageOutputsTests(unittest.TestCase):
    def test_positive_and_genuine_empty_plants_require_bound_success_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gbk = root / 'plant.gbk'
            gbk.write_bytes(b'annotated unit fixture')
            native = root / 'plantismash/plant'
            (native / 'native').mkdir(parents=True)
            completion = native / 'native/native-completion.json'
            completion.write_text('{"complete":true}')
            (native / 'native-exit.json').write_text('{"exit_code":0}')
            manifest = root / 'run_manifest.tsv'
            fields = ['genome_id', 'gbk_used', 'gbk_status', 'antismash_status', 'taxon_group', 'detector_profile']
            with manifest.open('w') as stream:
                writer = csv.writer(stream, delimiter='\t')
                writer.writerow(fields)
                writer.writerow(['plant', str(gbk), 'original_ok', 'not_applicable_taxon', 'plants', 'plantismash'])
            outcome = dict(genome_id='plant', producer='plantismash-2.0.4-private-repeat2', source_sha256=hashlib.sha256(gbk.read_bytes()).hexdigest(), completion_sha256=hashlib.sha256(completion.read_bytes()).hexdigest())
            for calls, state, expected in [(1, 'SUCCESS_WITH_CALLS', 1), (0, 'SUCCESSFUL_EMPTY', 1), (None, 'FAILED_OR_PARTIAL', 0), (0, 'FAILED_OR_PARTIAL', 0), (0, 'SUCCESS_WITH_CALLS', 0), (False, 'SUCCESSFUL_EMPTY', 0)]:
                with self.subTest(calls=calls, state=state):
                    (native / 'outcome.json').write_text(json.dumps(dict(outcome, calls=calls, state=state)))
                    self.assertEqual(module.usable_count(manifest, root), expected)
            (native / 'outcome.json').write_text(json.dumps(dict(outcome, calls=0, state='SUCCESSFUL_EMPTY')))
            completion.write_text('corrupt receipt')
            self.assertEqual(module.usable_count(manifest, root), 0)
            (native / 'outcome.json').unlink()
            self.assertEqual(module.usable_count(manifest, root), 0)

    def test_existing_nonplant_acceptance_rules_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / 'run_manifest.tsv'
            manifest.write_text('genome_id\tgbk_used\tgbk_status\tantismash_status\nA\tinput.gbk\toriginal_ok\tran_ok\nB\tinput.gbk\toriginal_ok\tran_ok_sanitized\nC\tinput.gbk\toriginal_ok\tskipped_done\nD\t\tannotation_fallbacks_failed\tskipped\nE\tinput.gbk\toriginal_ok\tfailed\n')
            self.assertEqual(module.usable_count(manifest, tmp), 3)
