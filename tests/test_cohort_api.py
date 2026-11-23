"""Real authenticated HTTP continuation requests, without scientific submission."""
import json
from pathlib import Path
import unittest
from unittest import mock
from test_web_api_auth import WebApiAuthTests
from test_cohort_continuation import fixture, persist
import cohort_gate as gate


class CohortApiTests(WebApiAuthTests):
    def setUp(self):
        super().setUp()
        self.root = self.job_store.job_dir('cohort-test'); self.root.mkdir(parents=True)
        self.result, self.values = fixture(self.root)
        self.control = self.root / 'cohort/current.json'
        self.identity = {'job_id': 'cohort-test', 'rerun_count': 0, 'source_sha256': 'a'*64}
        self.gate = gate.build_gate(self.result, self.control, self.identity, {}, 1)
        job = {'id': 'cohort-test', 'name': 'cohort fixture', 'status': 'awaiting_decision',
               'stage': 'awaiting_decision', 'cpus': 1, 'settings': {}, 'cohort_decision': gate.public_gate(self.gate)}
        self.read_token = self.app.attach_job_read_token(job)
        self.job_store.write_job(job)
        self.run = self.fixture_public_run_id('cohort-test')
        self.path = f'/api/results/{self.run}/continue'
        self.body = {k:self.gate[k] for k in ('decision_id','included','excluded')}
        patcher = mock.patch.object(self.app, 'validate_runtime_request', return_value=None)
        patcher.start(); self.addCleanup(patcher.stop)

    def post(self, token=None, body=None):
        headers={'Content-Type':'application/json'}
        if token: headers.update(self.auth(token))
        return self.request('POST', self.path, json.dumps(body if body is not None else self.body).encode(), headers)

    def test_cohort_http_requires_owner_credential(self):
        self.assertEqual(self.post()[0], 404)
        self.assertEqual(self.post('wrong')[0], 404)
        self.assertEqual(self.job_store.read_job('cohort-test')['status'], 'awaiting_decision')

    def test_cohort_http_public_acceptance_and_duplicate(self):
        self.assertEqual(self.post(self.read_token)[0], 202)
        status, value, _ = self.post(self.read_token)
        self.assertEqual(status, 200); self.assertTrue(value['duplicate'])
        self.assertEqual(len(list(self.job_store.QUEUE_DIR.glob('*.json'))), 1)

    def test_cohort_http_all_fail_cannot_be_forged(self):
        persist(self.result, self.values[1:])
        value=gate.build_gate(self.result,self.control,self.identity,{},1)
        body={k:value[k] for k in ('decision_id','included','excluded')}
        self.assertEqual(self.post(self.read_token,body)[0],409)
        self.assertFalse(list(self.job_store.QUEUE_DIR.glob('*.json')))

    def test_cohort_http_stale_and_changed_lists_refused(self):
        for body in [{**self.body,'decision_id':'a'*64},{**self.body,'included':['plant','bacterium']}]:
            self.assertEqual(self.post(self.read_token,body)[0],409)

    def test_cohort_http_sparse_projection_retains_failures(self):
        job=self.job_store.read_job('cohort-test')
        payload=self.app.job_payload(job,admin=False,include_public_events=True)
        outcomes=payload['cohort_decision']['outcomes']
        self.assertEqual([r['state'] for r in outcomes],['success','failed','failed'])
        rows=payload['genome_progress']
        self.assertEqual({r['genome_id']:r['status'] for r in rows},{'bacterium':'complete','plant':'failed','fungus':'failed'})


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(CohortApiTests(name) for name in loader.getTestCaseNames(CohortApiTests) if name.startswith('test_cohort_'))
