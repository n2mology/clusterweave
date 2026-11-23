"""Structured execution and authoritative overall completion regressions."""
import base64,json,unittest
from test_progress_tree_presentation import TREE, BROWSER_TREE_PATH, run_node_json

class TreeRepairTests(unittest.TestCase):
    def setUp(self):self.contract=TREE.load_contract()
    def tree(self,lines,status=''):
        uri='data:text/javascript;base64,'+base64.b64encode(BROWSER_TREE_PATH.read_bytes()).decode()
        return run_node_json(f"import {{buildProgressTree}} from {json.dumps(uri)};console.log(JSON.stringify(buildProgressTree({json.dumps(self.contract)},{json.dumps(lines)}.map((line,index)=>({{line,index}})),{{jobStatus:{json.dumps(status)}}})))")
    def test_decision_json_and_finished_native_tool(self):
        lines=['GENOME_ANNOTATION_DECISION genome=F required=yes method=funannotate message="Funannotate annotation required"',
               'COHORT_OUTCOME {"plan":{"nplinker":"disabled"},"annotation":"failed is a category"}',
               'TOOL_PROGRESS genome=F tool=funannotate phase=predict message="funannotate finished"',
               'Canonical ClusterWeave workflow finished successfully.']
        events=[TREE.classify_progress_line(self.contract,l,i) for i,l in enumerate(lines)]
        self.assertEqual(events[0]['state'],'running');self.assertEqual(events[1]['kind'],'diagnostic');self.assertEqual(events[2]['state'],'complete')
        rows=self.tree(lines)['rows'];self.assertFalse(any(r['stage']=='nplinker' for r in rows));self.assertEqual(rows[-1]['label'],'ClusterWeave');self.assertEqual(rows[-1]['state'],'complete')
        self.assertEqual(next(r for r in rows if r['label']=='funannotate')['state'],'complete')
    def test_sparse_authoritative_success_preserves_real_failure(self):
        rows=self.tree(['TOOL_EXECUTION genome=F tool=funannotate state=failed exit_code=17'],'success')['rows']
        self.assertEqual(next(r for r in rows if r['level']=='tool')['state'],'failed');self.assertEqual(rows[-1]['state'],'complete')
    def test_waiting_is_not_terminal_success(self):
        rows=self.tree(['GENOME_ANNOTATION_DECISION genome=F required=yes method=funannotate message="Annotation required"'],'awaiting_decision')['rows']
        self.assertEqual(rows[-1]['state'],'waiting');self.assertFalse(any(r['state'] in {'failed','running'} for r in rows))
    def test_skipped_followup_and_new_attempt(self):
        lines=['Stage 1/4: running detector','TOOL_EXECUTION genome=F tool=funannotate state=failed exit_code=17','Stage 1/4: complete','Stage 1/4: running detector','TOOL_EXECUTION genome=F tool=funannotate state=complete exit_code=0','Stage 2/4: skipped']
        rows=self.tree(lines)['rows'];self.assertEqual(next(r for r in rows if r['level']=='tool')['state'],'complete');self.assertEqual(next(r for r in rows if r['stage']=='bigscape')['state'],'skipped')

    def test_ncbi_failure_summaries_preserve_cli_browser_parity(self):
        lines = [
            'NCBI_DOWNLOAD_SUMMARY requested=3 downloaded=3 failed=0',
            'NCBI_DOWNLOAD_SUMMARY requested=3 downloaded=2 failed=1',
            '[ERROR] NCBI_DOWNLOAD_SUMMARY failed=0: connection failed',
            'UNKNOWN_SUMMARY {"failed": "a category, not a workflow error"}',
        ]
        cli = [TREE.classify_progress_line(self.contract, line, i) for i, line in enumerate(lines)]
        uri = 'data:text/javascript;base64,' + base64.b64encode(BROWSER_TREE_PATH.read_bytes()).decode()
        browser = run_node_json(
            f"import {{classifyProgressTreeLine}} from {json.dumps(uri)};"
            f"console.log(JSON.stringify({json.dumps(lines)}.map((line, i) => "
            f"classifyProgressTreeLine({json.dumps(self.contract)}, line, i))))"
        )
        self.assertEqual([event['state'] for event in cli], ['running', 'failed', 'failed', 'running'])
        self.assertEqual([event['state'] for event in browser], [event['state'] for event in cli])
        self.assertEqual(cli[-1]['kind'], 'diagnostic')
        self.assertEqual(browser[-1]['kind'], 'diagnostic')
