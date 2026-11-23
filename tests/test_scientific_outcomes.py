"""D1 reporting tests use synthetic metadata and detector output only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web'))
from researcher_report import build_report, begin_scientific_stage, finish_scientific_stage


class ScientificOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.result = Path(self.tmp.name) / 'results'; self.result.mkdir()
        (self.result / 'summary_tables').mkdir()
        self.routes = self.result / 'summary_tables/genome_taxon_manifest.tsv'
        self.manifest = self.result / 'summary_tables/run_manifest.tsv'
        self.routes.write_text('genome_id\ttaxon_group\tsource_accession\tprediction_method\tdetector_profile\troute_status\n'
            'Fungus\tfungi\tGCA_999999998.1\texisting_cds\tfungal\trouted\n'
            'Bacterium\tbacteria\tGCF_999999999.1\tprodigal\tbacterial\trouted\n'
            'Rejected\tfungi\t\texisting_cds\tfungal\trejected\n')
        self.state = {'scientific_attempt': {'annotation_selected': True, 'stage_outcome': 'not_started'}}

    def manifest_row(self, anti='ran_ok', fbx='ran_ok', gbk='original_ok', label='Fungus', method='existing_cds'):
        pending = self.manifest.with_suffix('.pending')
        pending.write_text('genome_id\ttaxon_group\tprediction_method\tdetector_profile\tgbk_status\tantismash_status\tfunbgcex_status\n'
            f'{label}\t{ "bacteria" if label == "Bacterium" else "fungi"}\t{method}\tfungal\t{gbk}\t{anti}\t{fbx}\n')
        pending.replace(self.manifest)

    def outputs(self, count=0, label='Fungus'):
        anti = self.result / 'antismash' / label; anti.mkdir(parents=True, exist_ok=True)
        (anti / '.done').touch(); (anti / 'index.html').write_text('complete')
        (anti / f'{label}.antismash.json').write_text(json.dumps({'records': [{'areas': [{}] * count}]}))
        fbx = self.result / 'funbgcex' / label; fbx.mkdir(parents=True, exist_ok=True)
        (fbx / '.done').touch()
        (fbx / 'allBGCs.csv').write_text('BGC no.,Scaffold,Start position,End position,Core enzymes\n' + '1,contig,1,100,PKS\n' * count)

    def project(self, state=None):
        return json.loads(build_report(self.result, root=ROOT, state=self.state if state is None else state)['run_metadata.json'])['scientific_outcomes']

    def genome(self, label='Fungus', state=None):
        return next(g for g in self.project(state)['genomes'] if g['genome_id'] == label)

    def current(self, anti='ran_ok', fbx='ran_ok', gbk='original_ok', count=0):
        begin_scientific_stage(self.result, self.state)
        self.manifest_row(anti, fbx, gbk); self.outputs(count)
        finish_scientific_stage(self.result, self.state, 'complete')

    def test_complete_inventory_includes_zero_and_missing_excludes_inactive(self):
        self.current()
        projection = self.project()
        self.assertTrue(projection['cohort_complete'])
        self.assertEqual([g['genome_id'] for g in projection['genomes']], ['Fungus', 'Bacterium'])
        g = self.genome()
        for detector in ('antismash', 'funbgcex'):
            self.assertEqual(g[detector]['current_outcome'], 'zero_reported')
            self.assertEqual(g[detector]['current_use'], 'execution')
            self.assertEqual(g[detector]['finding_count'], 0)
        self.assertEqual(self.genome('Bacterium')['antismash']['current_outcome'], 'unknown')
        self.assertEqual(self.genome('Bacterium')['funbgcex']['current_outcome'], 'not_applicable')
        self.assertEqual(g['annotation']['current_use'], 'input_reuse')

    def test_findings_are_native_reported_counts(self):
        self.current(count=2)
        for detector in ('antismash', 'funbgcex'):
            self.assertEqual(self.genome()[detector]['current_outcome'], 'findings_reported')
            self.assertEqual(self.genome()[detector]['finding_count'], 2)

    def test_historical_success_is_not_current_execution(self):
        self.manifest_row(); self.outputs()
        g = self.genome(state={})
        self.assertEqual(g['antismash']['current_outcome'], 'unknown')
        self.assertEqual(g['antismash']['recorded_outcome'], 'zero_reported')
        self.assertEqual(g['antismash']['record_scope'], 'retained')
        self.assertIsNone(g['antismash']['finding_count'])
        tools = json.loads(build_report(self.result, root=ROOT)['run_metadata.json'])['tools']
        self.assertTrue(all('current execution' not in t['use'] and 'verified cache' not in t['use'] for t in tools))

    def test_disabled_rerun_preserves_retained_result(self):
        self.manifest_row(); self.outputs()
        self.state['scientific_attempt']['annotation_selected'] = False
        begin_scientific_stage(self.result, self.state)
        self.manifest_row()
        finish_scientific_stage(self.result, self.state, 'complete')
        g = self.genome()
        self.assertEqual(g['antismash']['current_outcome'], 'not_run')
        self.assertEqual(g['antismash']['recorded_outcome'], 'zero_reported')
        self.assertEqual(g['antismash']['record_scope'], 'retained')

    def test_unchanged_manifest_on_failed_attempt_cannot_borrow_success(self):
        self.manifest_row(); self.outputs()
        begin_scientific_stage(self.result, self.state)
        finish_scientific_stage(self.result, self.state, 'failed')
        self.assertEqual(self.genome()['antismash']['current_outcome'], 'unknown')
        self.assertEqual(self.project()['canonical_stage_outcome'], 'failed')

    def test_identical_manifest_rewrite_is_current_but_skipped_done_is_reuse(self):
        self.manifest_row('skipped_done', 'skipped_done'); self.outputs()
        begin_scientific_stage(self.result, self.state)
        self.manifest_row('skipped_done', 'skipped_done')
        finish_scientific_stage(self.result, self.state, 'complete')
        g = self.genome()
        self.assertEqual(g['antismash']['current_use'], 'retained_reuse')
        self.assertEqual(g['antismash']['recorded_outcome'], 'zero_reported')
        self.assertEqual(g['antismash']['record_scope'], 'retained')

    def test_manifest_mutation_after_finalization_invalidates_binding(self):
        self.current(); self.manifest_row('failed')
        self.assertEqual(self.genome()['antismash']['current_outcome'], 'unknown')

    def test_explicit_failure_wins_over_empty_outputs(self):
        self.current('failed', 'failed', 'annotation_fallbacks_failed')
        g = self.genome()
        for name in ('annotation', 'antismash', 'funbgcex'):
            self.assertEqual(g[name]['current_outcome'], 'failed')
        self.assertIsNone(g['antismash']['finding_count'])

    def test_skipped_after_annotation_failure_is_blocked(self):
        self.current('skipped', 'skipped', 'funannotate_busco_training_insufficient')
        self.assertEqual(self.genome()['antismash']['current_outcome'], 'blocked')
        self.assertIsNone(self.genome()['antismash']['finding_count'])

    def test_skip_without_failure_is_not_run(self):
        self.current('skipped', 'skipped')
        self.assertEqual(self.genome()['antismash']['current_outcome'], 'not_run')

    def test_missing_success_output_is_not_zero(self):
        self.current(); (self.result / 'antismash/Fungus/.done').unlink()
        g = self.genome()
        self.assertEqual(g['antismash']['current_outcome'], 'incomplete_output')
        self.assertIsNone(g['antismash']['finding_count'])

    def test_unsupported_antismash_shapes_never_imply_zero(self):
        self.current()
        path = self.result / 'antismash/Fungus/Fungus.antismash.json'
        for value in ({}, {'records': []}, {'records': [{}]}, {'records': [{'areas': None}]}, {'records': [{'areas': [None]}]}, [], 'bad'):
            with self.subTest(value=value):
                path.write_text(json.dumps(value))
                self.assertEqual(self.genome()['antismash']['current_outcome'], 'unavailable_evidence')
                self.assertIsNone(self.genome()['antismash']['finding_count'])

    def test_bacterial_canonical_json_preference(self):
        begin_scientific_stage(self.result, self.state)
        self.manifest_row('ran_ok_sanitized', 'not_applicable_taxon', label='Bacterium', method='prodigal')
        self.outputs(2, label='Bacterium')
        (self.result / 'antismash/Bacterium/Bacterium.bacteria.antismash.json').write_text(json.dumps({'records': [{'areas': []}]}))
        finish_scientific_stage(self.result, self.state, 'complete')
        g = self.genome('Bacterium')
        self.assertEqual(g['antismash']['finding_count'], 0)
        self.assertEqual(g['funbgcex']['current_outcome'], 'not_applicable')
        self.assertNotEqual(g['annotation']['current_use'], 'execution')

    def test_malformed_truncated_csv_is_not_zero(self):
        self.current()
        path = self.result / 'funbgcex/Fungus/allBGCs.csv'
        for text in ('', 'arbitrary\n', 'BGC no.,Scaffold,Start position,End position\n1,contig\n', 'BGC no.,Scaffold,Start position,End position\n"unterminated'):
            with self.subTest(text=text):
                path.write_text(text)
                self.assertEqual(self.genome()['funbgcex']['current_outcome'], 'unavailable_evidence')

    def test_bounded_link_and_hardlink_output_rejected(self):
        self.current()
        path = self.result / 'antismash/Fungus/Fungus.antismash.json'
        outside = Path(self.tmp.name) / 'outside'; outside.write_bytes(path.read_bytes()); path.unlink()
        path.symlink_to(outside)
        self.assertEqual(self.genome()['antismash']['current_outcome'], 'unavailable_evidence')
        path.unlink(); os.link(outside, path)
        self.assertEqual(self.genome()['antismash']['current_outcome'], 'unavailable_evidence')
        path.unlink(); path.write_bytes(b' ' * (16 * 1024 * 1024 + 1))
        self.assertEqual(self.genome()['antismash']['current_outcome'], 'unavailable_evidence')

    def test_parent_links_and_fifo_rejected(self):
        self.current()
        path = self.result / 'funbgcex/Fungus/allBGCs.csv'; path.unlink(); os.mkfifo(path)
        self.assertEqual(self.genome()['funbgcex']['current_outcome'], 'unavailable_evidence')
        path.unlink(); path.parent.rename(path.parent.with_name('hidden'))
        path.parent.symlink_to(path.parent.with_name('hidden'), target_is_directory=True)
        self.assertEqual(self.genome()['funbgcex']['current_outcome'], 'unavailable_evidence')

    def test_missing_cohort_is_partial_manifest_only(self):
        self.routes.unlink(); self.manifest_row()
        projection = self.project()
        self.assertFalse(projection['cohort_complete'])
        self.assertEqual(projection['cohort_source'], 'run_manifest_partial')
        self.assertEqual(len(projection['genomes']), 1)

    def test_invalid_authoritative_cohort_does_not_fall_back(self):
        self.manifest_row()
        self.routes.write_text('wrong\theader\nFungus\tfungi\n')
        self.assertEqual(self.project()['genomes'], [])
        self.assertFalse(self.project()['cohort_complete'])

    def test_duplicate_cohort_rows_and_manifest_rows_are_ambiguous(self):
        self.current()
        self.routes.write_text(self.routes.read_text() + self.routes.read_text().splitlines()[1] + '\n')
        self.assertFalse(self.project()['cohort_complete'])
        self.assertEqual(self.genome()['antismash']['current_outcome'], 'unknown')
        self.routes.write_text(self.routes.read_text().rsplit('\n', 2)[0] + '\n')
        begin_scientific_stage(self.result, self.state)
        self.manifest.write_text(self.manifest.read_text() + self.manifest.read_text().splitlines()[1] + '\n')
        finish_scientific_stage(self.result, self.state, 'complete')
        self.assertEqual(self.genome()['antismash']['current_outcome'], 'unknown')

    def cache(self, outcome='hit', mutate=None):
        from test_cached_accession import identity
        value = identity(); value['accession'] = 'GCA_999999998.1'; value['route']['taxon'] = 'fungi'; value['containers'] = {'funbgcex': '7' * 64}
        value['models']['embedded'] = hashlib.sha256(json.dumps({'native': value['runtime_sha256'], 'images': value['containers']}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        key = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
        record = {'identity': value, 'key': key, 'outcome': outcome}
        if mutate: mutate(record)
        path = self.result / 'reproducibility/accession_cache/Fungus.detection.json'; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record)); return path

    def test_new_verified_cache_hit_is_current_use_of_original_computation(self):
        begin_scientific_stage(self.result, self.state)
        self.manifest_row(); self.outputs(); self.cache()
        finish_scientific_stage(self.result, self.state, 'complete')
        g = self.genome()
        self.assertEqual(g['antismash']['current_use'], 'cache_reuse')
        self.assertEqual(g['antismash']['record_scope'], 'original_cache_producer')
        self.assertEqual(g['antismash']['finding_count'], 0)

    def test_stale_hit_is_not_current_cache_reuse_or_execution(self):
        self.cache()
        self.current()
        self.assertEqual(self.genome()['antismash']['current_use'], 'unknown')
        tools = json.loads(build_report(self.result, state=self.state, root=ROOT)['run_metadata.json'])['tools']
        self.assertTrue(all('verified cache' not in t['use'] and 'current execution' not in t['use'] for t in tools))

    def test_invalid_cache_hit_cannot_prove_execution_or_reuse(self):
        for mutate in (lambda r: r.update(key='a' * 64), lambda r: r['identity'].update(accession='GCA_123456789.1'),
                       lambda r: r['identity']['route'].update(taxon='bacteria'), lambda r: r['identity'].pop('runtime_sha256')):
            with self.subTest(mutate=mutate):
                begin_scientific_stage(self.result, self.state)
                self.manifest_row(); self.outputs(); self.cache(mutate=mutate)
                finish_scientific_stage(self.result, self.state, 'complete')
                self.assertEqual(self.genome()['antismash']['current_use'], 'unknown')

    def test_post_stage_cache_mutation_invalidates_reuse(self):
        begin_scientific_stage(self.result, self.state)
        self.manifest_row(); self.outputs(); path = self.cache()
        finish_scientific_stage(self.result, self.state, 'complete')
        pending = path.with_suffix('.pending'); pending.write_bytes(path.read_bytes()); pending.replace(path)
        self.assertEqual(self.genome()['antismash']['current_use'], 'unknown')

    def test_unknown_annotation_status_does_not_invent_failure(self):
        self.current('skipped', 'skipped', 'future_status')
        self.assertEqual(self.genome()['annotation']['current_outcome'], 'unknown')
        self.assertEqual(self.genome()['annotation']['recorded_outcome'], 'unavailable_evidence')

    def test_unknown_taxon_and_mismatched_record_are_ambiguous(self):
        self.current()
        self.routes.write_text(self.routes.read_text().replace('Fungus\tfungi', 'Fungus\tbacteria'))
        self.assertEqual(self.genome()['antismash']['current_outcome'], 'unknown')
        self.assertEqual(self.genome()['antismash']['record_scope'], 'ambiguous')

    def test_truncated_and_linked_manifest_do_not_establish_current_rows(self):
        self.current()
        for text in ('genome_id\tgbk_status\tantismash_status\tfunbgcex_status\nFungus\toriginal_ok\tran_ok\n',
                     'genome_id\tgbk_status\tantismash_status\tantismash_status\tfunbgcex_status\n'):
            with self.subTest(text=text):
                begin_scientific_stage(self.result, self.state)
                self.manifest.write_text(text)
                finish_scientific_stage(self.result, self.state, 'failed')
                self.assertEqual(self.genome()['antismash']['current_outcome'], 'unknown')
        outside = Path(self.tmp.name) / 'manifest'; outside.write_bytes(self.manifest.read_bytes())
        self.manifest.unlink(); self.manifest.symlink_to(outside)
        self.assertEqual(self.genome()['antismash']['current_outcome'], 'unknown')

    def test_authoritative_cohort_bounds_and_unsafe_labels_are_not_discovered(self):
        self.current()
        self.routes.write_text('genome_id\ttaxon_group\n' + 'Fungus\tfungi\n' * 4097)
        self.assertEqual(self.project()['genomes'], [])
        self.routes.write_text('genome_id\ttaxon_group\n../private\tfungi\n..\tfungi\n')
        self.assertFalse(self.project()['cohort_complete'])
        self.assertEqual(self.project()['genomes'], [])

    def test_current_verified_miss_and_malformed_provenance_are_distinct(self):
        begin_scientific_stage(self.result, self.state)
        self.manifest_row(); self.outputs(); path = self.cache(outcome='miss')
        finish_scientific_stage(self.result, self.state, 'complete')
        self.assertEqual(self.genome()['antismash']['current_use'], 'execution')
        begin_scientific_stage(self.result, self.state)
        self.manifest_row(); path.write_text('{broken')
        finish_scientific_stage(self.result, self.state, 'complete')
        self.assertEqual(self.genome()['antismash']['current_use'], 'unknown')
        self.assertIsNone(self.genome()['antismash']['finding_count'])

    def test_provenance_replaced_during_report_read_is_not_bound(self):
        from unittest import mock
        import researcher_report as report
        begin_scientific_stage(self.result, self.state)
        self.manifest_row(); self.outputs(); path = self.cache()
        finish_scientific_stage(self.result, self.state, 'complete')
        original = report.read_record
        changed = False
        def read(candidate, base, limit=65536):
            nonlocal changed
            raw = original(candidate, base, limit)
            if candidate == path and not changed:
                changed = True
                pending = path.with_suffix('.pending'); pending.write_bytes(raw); pending.replace(path)
            return raw
        with mock.patch.object(report, 'read_record', side_effect=read):
            self.assertEqual(self.genome()['antismash']['current_use'], 'unknown')

    def test_report_addition_preserves_scientific_files_and_raw_statuses(self):
        self.current(count=1)
        path = self.result / 'summary_tables/shared.csv'; path.write_bytes(b'genome,BGC\nFungus,1\n')
        before = {str(p.relative_to(self.result)): p.read_bytes() for p in self.result.rglob('*') if p.is_file()}
        files = build_report(self.result, state=self.state, root=ROOT)
        after = {str(p.relative_to(self.result)): p.read_bytes() for p in self.result.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        metadata = json.loads(files['run_metadata.json'])
        self.assertEqual(metadata['analysis_outcomes'][0]['antismash_status'], 'ran_ok')
        self.assertIn(b'## Scientific outcomes', files['METHODS.md'])
        for private in (str(self.result), 'st_mtime', 'st_ino'):
            self.assertNotIn(private.encode(), b''.join(files.values()))


if __name__ == '__main__':
    unittest.main()
