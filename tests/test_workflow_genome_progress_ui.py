from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
JS_PATH = REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js"
CSS_PATH = REPO_ROOT / "web" / "static" / "assets" / "clusterweave.css"
INDEX_PATH = REPO_ROOT / "web" / "static" / "index.html"
NODE = shutil.which("node")


def genome_progress_helper_block() -> str:
    source = JS_PATH.read_text(encoding="utf-8")
    return source.split("// BEGIN GENOME_PROGRESS_PURE", 1)[1].split(
        "// END GENOME_PROGRESS_PURE", 1
    )[0]


def job_runtime_helper_block() -> str:
    source = JS_PATH.read_text(encoding="utf-8")
    return "function jobRuntimeBounds" + source.split(
        "function jobRuntimeBounds", 1
    )[1].split("function stageRuntimeHint", 1)[0]


def run_node_json(body: str) -> object:
    if NODE is None:
        raise unittest.SkipTest("Node.js is required for frontend progress tests")
    prelude = r"""
let activeJobId = 'job-a';
let genomeProgressSnapshotKey = '';
let genomeProgressSnapshot = new Map();
const GENOME_PROGRESS_TERMINAL_STATES = new Set([
  'complete', 'completed', 'done', 'success', 'succeeded',
  'complete_with_warning',
  'warning', 'dropped', 'failed', 'error', 'skipped',
  'not_applicable', 'not_applicable_taxon', 'not-applicable', 'not applicable',
]);
const GENOME_PROGRESS_WARNING_STATES = new Set([
  'complete_with_warning', 'warning', 'dropped', 'failed', 'error',
]);
const GENOME_PROGRESS_ACTIVE_STATES = new Set(['running', 'active', 'processing']);
function parseTimestampMs(value) {
  if (!value) return null;
  const raw = typeof value === 'string' ? value.trim() : value;
  const normalized = typeof raw === 'string'
    && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(raw)
    ? `${raw.replace(' ', 'T')}Z`
    : raw;
  const ms = new Date(normalized).getTime();
  return Number.isNaN(ms) ? null : ms;
}
function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}
"""
    completed = subprocess.run(
        [NODE, "-e", prelude + genome_progress_helper_block() + "\n" + body],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Genome progress Node probe failed\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


@unittest.skipUnless(NODE, "Node.js is required for frontend progress tests")
class WorkflowGenomeProgressBehaviorTests(unittest.TestCase):
    def test_workflow_title_matches_idle_rows_downstream_and_terminal_states(self) -> None:
        result = run_node_json(
            """
process.stdout.write(JSON.stringify({
  idle: bgcWorkflowTitle({state: 'idle'}, false),
  genomes: bgcWorkflowTitle({state: 'running', currentStepId: 'annotation'}, true),
  grouping: bgcWorkflowTitle({state: 'running', currentStepId: 'bigscape'}, false),
  complete: bgcWorkflowTitle({state: 'complete'}, false),
  failed: bgcWorkflowTitle({state: 'failed'}, false),
}));
"""
        )
        self.assertEqual(result["idle"], "Workflow waiting")
        self.assertEqual(result["genomes"], "Genome annotation / BGC detection")
        self.assertEqual(result["grouping"], "BiG-SCAPE grouping")
        self.assertEqual(result["complete"], "Workflow complete")
        self.assertEqual(result["failed"], "Workflow needs review")

    def test_region_ribbon_uses_processed_and_active_counts_without_visible_percent_or_timer(self) -> None:
        result = run_node_json(
            """
const item = normalizeGenomeProgressItem({
  genome_id: 'fungus-a',
  display_label: 'Fungus a',
  taxon_group: 'fungi',
  annotation_method: 'existing_cds',
  stage: 'antismash',
  tool: 'antiSMASH',
  percent: 45,
  status: 'running',
  message: 'Starting antiSMASH record shard',
  activity_message: 'Scanning protein domains',
  region_progress: {processed: 2, total: 7, active: 3, failed: 0},
  stage_states: {
    genome_acquired: {status: 'complete'},
    antismash: {status: 'running'},
  },
}, 0);
const stages = genomeProgressStageModel(item);
const ribbon = genomeProgressRibbonText(item, item.activityMessage, stages);
const html = renderGenomeProgressCard(item);
process.stdout.write(JSON.stringify({ribbon, html, stages}));
"""
        )
        self.assertEqual(
            result["ribbon"],
            "Region (2/7) · 3 active · Scanning protein domains",
        )
        self.assertNotIn("Still running", result["html"])
        self.assertNotIn('class="genome-progress-percent"', result["html"])
        self.assertIn("has-live-region-work", result["html"])
        self.assertEqual(result["stages"][1]["progress"], 29)

    def test_total_job_runtime_clock_uses_days_and_freezes_at_terminal_timestamp(self) -> None:
        result = run_node_json(
            job_runtime_helper_block()
            + """
const originalNow = Date.now;
Date.now = () => Date.parse('2026-07-24T00:42:46Z');
const naiveUtcActive = jobRuntimeBounds({
  status: 'running',
  created_at: '2026-07-24T00:34:24.525808',
});
Date.now = () => Date.parse('2026-07-24T03:04:05Z');
const active = jobRuntimeBounds({
  status: 'running',
  created_at: '2026-07-23T00:00:00Z',
});
const complete = jobRuntimeBounds({
  status: 'success',
  created_at: '2026-07-20T00:00:00Z',
  completed_at: '2026-07-21T02:03:04Z',
  updated_at: '2026-07-23T23:59:59Z',
});
const failed = jobRuntimeBounds({
  status: 'failed',
  created_at: '2026-07-20T00:00:00Z',
  failed_at: '2026-07-20T00:00:05Z',
});
Date.now = originalNow;
process.stdout.write(JSON.stringify({
  naiveUtc: formatJobRuntimeClock(naiveUtcActive.end - naiveUtcActive.start),
  naiveUtcStart: naiveUtcActive.start,
  explicitUtcStart: Date.parse('2026-07-24T00:34:24.525808Z'),
  active: formatJobRuntimeClock(active.end - active.start),
  activeFlag: active.active,
  complete: formatJobRuntimeClock(complete.end - complete.start),
  completeFlag: complete.active,
  failed: formatJobRuntimeClock(failed.end - failed.start),
}));
"""
        )
        self.assertEqual(result["naiveUtc"], "(00:00:08:21)")
        self.assertEqual(result["naiveUtcStart"], result["explicitUtcStart"])
        self.assertEqual(result["active"], "(01:03:04:05)")
        self.assertTrue(result["activeFlag"])
        self.assertEqual(result["complete"], "(01:02:03:04)")
        self.assertFalse(result["completeFlag"])
        self.assertEqual(result["failed"], "(00:00:00:05)")

    def test_same_attempt_progress_is_monotonic_across_timeout_older_and_zero_payloads(self) -> None:
        result = run_node_json(
            """
function item(percent, updatedAt, options = {}) {
  return {
    genome_id: 'fungus-a',
    display_label: 'Fungus a',
    taxon_group: 'fungi',
    stage: options.stage || 'annotation',
    tool: options.tool || 'funannotate',
    percent,
    status: options.status || 'running',
    message: options.message || 'Working',
    updated_at: updatedAt || '',
    terminal: options.terminal === true,
  };
}
function poll(progress, updatedAt, options = {}, rerunCount = 0) {
  return normalizeGenomeProgressItems({
    id: 'job-a',
    rerun_count: rerunCount,
    genome_progress: [item(progress, updatedAt, options)],
  })[0];
}
const sequence = [
  poll(8, '2026-07-13T10:00:01Z', {
    stage: 'download',
    tool: 'NCBI',
    status: 'queued',
    message: 'NCBI genome downloaded | queued',
  }).percent,
  poll(20, '2026-07-13T10:00:02Z').percent,
  poll(47, '2026-07-13T10:00:03Z', {stage: 'antismash', tool: 'antiSMASH'}).percent,
  poll(61, '2026-07-13T10:00:04Z', {stage: 'antismash', tool: 'antiSMASH'}).percent,
];
const afterTimeout = normalizeGenomeProgressItems({
  id: 'job-a',
  rerun_count: 0,
  genome_progress: [],
})[0];
const afterOlderPoll = poll(
  20,
  '2026-07-13T10:00:02Z',
  {stage: 'annotation', tool: 'funannotate', message: 'Older response'},
);
const afterTransientZero = poll(
  0,
  '',
  {stage: 'download', tool: 'NCBI', status: 'queued', message: 'Waiting to start'},
);
const terminal = poll(
  100,
  '2026-07-13T10:00:05Z',
  {stage: 'complete', tool: 'antiSMASH', status: 'complete', message: 'Genome complete', terminal: true},
);
const explicitSameAttemptRestart = poll(
  0,
  '2026-07-13T10:00:06Z',
  {stage: 'annotation', tool: 'funannotate', status: 'running', message: 'Starting annotation and BGC prediction'},
);
const newAttempt = poll(
  0,
  '2026-07-13T11:00:00Z',
  {stage: 'annotation', tool: 'funannotate', message: 'Starting annotation and BGC prediction'},
  1,
);
resetGenomeProgressSnapshot('job-b', 0);
const initialOrder = normalizeGenomeProgressItems({
  id: 'job-b',
  rerun_count: 0,
  genome_progress: [
    {...item(20, '2026-07-13T12:00:01Z'), genome_id: 'fungus-a'},
    {...item(20, '2026-07-13T12:00:01Z'), genome_id: 'fungus-b'},
  ],
}).map(row => row.id);
const partialOrder = normalizeGenomeProgressItems({
  id: 'job-b',
  rerun_count: 0,
  genome_progress: [
    {...item(47, '2026-07-13T12:00:02Z', {stage: 'antismash', tool: 'antiSMASH'}), genome_id: 'fungus-b'},
  ],
}).map(row => row.id);
resetGenomeProgressSnapshot('job-c', 0);
const bounded = normalizeGenomeProgressItems({
  id: 'job-c',
  rerun_count: 0,
  genome_progress: Array.from({length: 40}, (_, index) => ({
    ...item(20, '2026-07-13T12:01:00Z'),
    genome_id: `fungus-${index}`,
  })),
});
process.stdout.write(JSON.stringify({
  sequence,
  afterTimeout: afterTimeout.percent,
  afterOlderPoll: afterOlderPoll.percent,
  afterTransientZero: afterTransientZero.percent,
  terminal: terminal.percent,
  explicitSameAttemptRestart: explicitSameAttemptRestart.percent,
  newAttempt: newAttempt.percent,
  initialOrder,
  partialOrder,
  acceptedLength: bounded.length,
}));
"""
        )
        self.assertEqual(result["sequence"], [8, 20, 47, 61])
        self.assertEqual(result["afterTimeout"], 61)
        self.assertEqual(result["afterOlderPoll"], 61)
        self.assertEqual(result["afterTransientZero"], 61)
        self.assertEqual(result["terminal"], 100)
        self.assertEqual(result["explicitSameAttemptRestart"], 0)
        self.assertEqual(result["newAttempt"], 0)
        self.assertEqual(result["initialOrder"], ["fungus-a", "fungus-b"])
        self.assertEqual(result["partialOrder"], ["fungus-a", "fungus-b"])
        self.assertEqual(result["acceptedLength"], 40)

    def test_rows_use_taxon_specific_stages_and_exact_queued_copy(self) -> None:
        result = run_node_json(
            """
const queued = normalizeGenomeProgressItem({
  genome_id: 'fungus-a',
  display_label: 'Fungus a',
  taxon_group: 'fungi',
  stage: 'download',
  tool: 'NCBI',
  percent: 8,
  status: 'queued',
  message: 'NCBI genome downloaded | queued',
}, 0);
const bacteria = normalizeGenomeProgressItem({
  genome_id: 'bacteria_Bacillus_subtilis_168',
  display_label: 'Bacillus subtilis 168',
  taxon_group: 'bacteria',
  stage: 'antismash',
  tool: 'antiSMASH',
  percent: 47,
  status: 'running',
  message: 'Running whole-genome PFAM search',
}, 1);
const uploadedBacteria = normalizeGenomeProgressItem({
  genome_id: 'bacteria_isolate_7',
  taxon_group: 'bacteria',
  stage: 'antismash',
  tool: 'antiSMASH',
  percent: 47,
  status: 'running',
  message: 'Running whole-genome PFAM search',
}, 4);
const requiresFunannotate = normalizeGenomeProgressItem({
  genome_id: 'fungus-fallback',
  taxon_group: 'fungi',
  annotation_method: 'funannotate',
  stage: 'annotation',
  tool: 'funannotate',
  percent: 20,
  status: 'running',
  message: 'Predicting genes',
}, 2);
const existingCds = normalizeGenomeProgressItem({
  genome_id: 'fungus-existing',
  taxon_group: 'fungi',
  annotation_method: 'existing_cds',
  stage: 'antismash',
  tool: 'antiSMASH',
  percent: 35,
  status: 'running',
  message: 'Running antiSMASH',
}, 3);
const lateAntismash = normalizeGenomeProgressItem({
  genome_id: 'fungus-late-antismash',
  display_label: 'Boeremia exigua CU02',
  taxon_group: 'fungi',
  annotation_method: 'existing_cds',
  stage: 'antismash',
  tool: 'antiSMASH',
  percent: 66,
  status: 'running',
  message: 'Running whole-genome PFAM search',
  stage_states: {
    genome_acquired: {status: 'complete'},
    antismash: {status: 'running'},
  },
}, 5);
const queuedHtml = renderGenomeProgressCard(queued);
const bacteriaHtml = renderGenomeProgressCard(bacteria);
process.stdout.write(JSON.stringify({
  queuedHtml,
  bacteriaHtml,
  lateAntismashHtml: renderGenomeProgressCard(lateAntismash),
  lateAntismashMeter: genomeProgressMeterModel(lateAntismash),
  lateAntismashStages: genomeProgressStageModel(lateAntismash),
  uploadedBacteriaHtml: renderGenomeProgressCard(uploadedBacteria),
  fungiStages: genomeProgressStages(queued),
  fallbackStages: genomeProgressStages(requiresFunannotate),
  existingStages: genomeProgressStages(existingCds),
  bacteriaStages: genomeProgressStages(bacteria),
}));
"""
        )
        self.assertEqual(
            result["fungiStages"],
            ["Genome acquired", "antiSMASH", "FunBGCeX", "Complete"],
        )
        self.assertEqual(
            result["fallbackStages"],
            ["Genome acquired", "Funannotate", "antiSMASH", "FunBGCeX", "Complete"],
        )
        self.assertEqual(
            result["existingStages"],
            ["Genome acquired", "antiSMASH", "FunBGCeX", "Complete"],
        )
        self.assertEqual(
            result["bacteriaStages"],
            ["Genome acquired", "antiSMASH", "Complete"],
        )
        self.assertNotIn("Funannotate", result["bacteriaHtml"])
        self.assertNotIn("FunBGCeX", result["bacteriaHtml"])
        self.assertIn("Bacillus subtilis 168", result["bacteriaHtml"])
        self.assertNotIn("bacteria Bacillus", result["bacteriaHtml"])
        self.assertIn("bacteria isolate 7", result["uploadedBacteriaHtml"])
        self.assertIn('role="progressbar"', result["queuedHtml"])
        self.assertIn('aria-valuenow="0"', result["queuedHtml"])
        self.assertIn('class="genome-progress-segment is-complete"', result["queuedHtml"])
        self.assertNotIn("genome-progress-fill", result["queuedHtml"])
        self.assertEqual(
            result["lateAntismashMeter"],
            {"label": "antiSMASH", "percent": 89, "text": "antiSMASH 89%"},
        )
        self.assertEqual(
            [(stage["label"], stage["progress"]) for stage in result["lateAntismashStages"]],
            [("Genome acquired", 100), ("antiSMASH", 89), ("FunBGCeX", 0), ("Complete", 0)],
        )
        self.assertIn("antiSMASH 89%", result["lateAntismashHtml"])
        self.assertIn("FunBGCeX: 0%", result["lateAntismashHtml"])
        self.assertIn('class="genome-progress-meter-row"', result["queuedHtml"])
        header = result["queuedHtml"].split(
            '<div class="genome-progress-meter-row">', 1
        )[0]
        self.assertNotIn("genome-progress-percent", header)
        self.assertNotIn('class="genome-progress-percent"', result["queuedHtml"])
        self.assertIn(
            '<small title="NCBI genome downloaded | queued">'
            "NCBI genome downloaded | queued</small>",
            result["queuedHtml"],
        )
        self.assertNotIn('class="genome-progress-percent"', result["lateAntismashHtml"])
        self.assertNotIn("NCBI NCBI", result["queuedHtml"])
        self.assertNotIn("NCBI genome download complete", result["queuedHtml"])

    def test_fungal_and_bacterial_current_stage_states_remain_truthful(self) -> None:
        result = run_node_json(
            """
function progressItem(taxon, tool, stage, percent, status, message) {
  return normalizeGenomeProgressItem({
    genome_id: `${taxon}-demo`,
    taxon_group: taxon,
    tool,
    stage,
    percent,
    status,
    message,
    terminal: status === 'warning',
  }, 0);
}
const fungalAnnotate = progressItem('fungi', 'funannotate', 'annotation', 25, 'running', 'Predicting genes');
const fungalWarning = progressItem('fungi', 'antiSMASH', 'antismash', 70, 'warning', 'antiSMASH failed');
const bacterialProdigal = progressItem('bacteria', 'Prodigal', 'annotation', 25, 'running', 'Predicting bacterial genes');
const bacterialQueued = progressItem('bacteria', 'NCBI', 'download', 8, 'queued', 'NCBI genome downloaded | queued');
process.stdout.write(JSON.stringify({
  fungalAnnotate: renderGenomeProgressStages(fungalAnnotate),
  fungalWarning: renderGenomeProgressStages(fungalWarning),
  bacterialProdigal: renderGenomeProgressStages(bacterialProdigal),
  bacterialQueued: renderGenomeProgressStages(bacterialQueued),
}));
"""
        )
        self.assertRegex(
            result["fungalAnnotate"],
            r'is-complete[^>]*[^<]*<span[^>]*></span><b>Genome acquired</b>.*'
            r'is-active[^>]*[^<]*<span[^>]*></span><b>Funannotate</b>',
        )
        self.assertRegex(
            result["fungalWarning"],
            r'is-warning[^>]*[^<]*<span[^>]*></span><b>antiSMASH</b>',
        )
        self.assertRegex(
            result["bacterialProdigal"],
            r'is-complete[^>]*[^<]*<span[^>]*></span><b>Genome acquired</b>.*'
            r'is-active[^>]*[^<]*<span[^>]*></span><b>antiSMASH</b>',
        )
        self.assertRegex(
            result["bacterialQueued"],
            r'is-complete[^>]*[^<]*<span[^>]*></span><b>Genome acquired</b>.*'
            r'is-upcoming[^>]*[^<]*<span[^>]*></span><b>antiSMASH</b>',
        )

    def test_partial_failure_keeps_per_tool_truth_and_live_queue_counts(self) -> None:
        result = run_node_json(
            """
const warning = normalizeGenomeProgressItem({
  genome_id: 'fungus-warning',
  taxon_group: 'fungi',
  annotation_method: 'existing_cds',
  percent: 100,
  status: 'complete_with_warning',
  terminal: true,
  warning_tool: 'antiSMASH',
  warning_message: 'antiSMASH rejected record NC_TEST.1: overlapping exon coordinates in an annotated feature',
  message: 'FunBGCeX complete',
  stage_states: {
    genome_acquired: {status: 'complete'},
    antismash: {status: 'failed'},
    funbgcex: {status: 'complete'},
    complete: {status: 'complete'},
  },
}, 0);
const complete = normalizeGenomeProgressItem({
  genome_id: 'fungus-complete',
  taxon_group: 'fungi',
  percent: 100,
  status: 'complete',
  terminal: true,
  message: 'Genome workflow complete',
}, 1);
const active = normalizeGenomeProgressItem({
  genome_id: 'fungus-active',
  taxon_group: 'fungi',
  percent: 50,
  status: 'running',
  message: 'Running antiSMASH',
}, 2);
const queued = normalizeGenomeProgressItem({
  genome_id: 'fungus-queued',
  taxon_group: 'fungi',
  percent: 8,
  status: 'queued',
  message: 'NCBI genome downloaded | queued',
}, 3);
process.stdout.write(JSON.stringify({
  stages: renderGenomeProgressStages(warning),
  card: renderGenomeProgressCard(warning),
  summary: genomeProgressSummaryText([warning, complete, active, queued]),
}));
"""
        )
        self.assertRegex(
            result["stages"],
            r'is-warning[^>]*[^<]*<span[^>]*></span><b>antiSMASH</b>.*'
            r'is-complete[^>]*[^<]*<span[^>]*></span><b>FunBGCeX</b>.*'
            r'is-complete[^>]*[^<]*<span[^>]*></span><b>Complete</b>',
        )
        self.assertIn("overlapping exon coordinates", result["card"])
        self.assertIn("is-complete has-advisory", result["card"])
        self.assertNotIn("needs review", result["card"])
        self.assertEqual(
            result["summary"],
            "2 complete · 1 active · 1 queued · warnings: 1",
        )


class WorkflowGenomeProgressStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = JS_PATH.read_text(encoding="utf-8")
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.index = INDEX_PATH.read_text(encoding="utf-8")

    def test_results_header_has_one_collision_safe_persistent_job_timer(self) -> None:
        self.assertIn('id="results-job-runtime"', self.index)
        self.assertEqual(self.index.count('id="results-job-runtime"'), 1)
        self.assertIn("function formatJobRuntimeClock", self.js)
        self.assertIn("renderJobRuntime(activeJobMeta)", self.js)
        self.assertIn("job?.completed_at || job?.failed_at", self.js)
        self.assertIn(".results-run-state", self.css)
        self.assertIn("font-variant-numeric: tabular-nums", self.css)

    def test_pre_grouping_rows_are_the_only_visible_progress_presentation(self) -> None:
        self.assertIn(
            ".has-genome-progress:not(.is-genome-progress-handoff) > .workflow-tool-status",
            self.css,
        )
        self.assertIn(
            ".has-genome-progress:not(.is-genome-progress-handoff) > .workflow-caption",
            self.css,
        )
        self.assertIn("setBgcWorkflowAggregatePresentationSuspended(genomeLayerActive)", self.js)
        self.assertIn("nativeProgress.hidden = hidden", self.js)
        self.assertIn("node.inert = hidden", self.js)
        self.assertNotIn("genome-mini-dna", self.css + self.js)

    def test_handoff_requires_all_terminal_genomes_and_a_downstream_stage(self) -> None:
        payload = self.js.split("function bgcWorkflowPayload", 1)[1].split(
            "const ALT06_WORKFLOW_STEPS", 1
        )[0]
        self.assertIn("genomes.every(item => item.terminal)", payload)
        self.assertIn("'bigscape'", payload)
        self.assertIn(
            "const genomeProgressHandoff = genomeProgressAllTerminal && aggregateDownstreamStage",
            payload,
        )
        self.assertIn(
            ".is-aggregate-handoff.has-terminal-warning .genome-progress-row:not(.is-warning)",
            self.css,
        )


    def test_completed_state_keeps_dna_percent_and_stage_cards_visible(self) -> None:
        complete_visibility = self.css.split(
            'body[data-job-state="complete"] .genome-progress-layer,', 1
        )[1].split("}", 1)[0]
        for selector in [
            ".workflow-tool-status",
            ".tool-activity-chip",
            "#workflow-title",
            "#workflow-caption-label",
        ]:
            self.assertIn(selector, complete_visibility)
        self.assertNotIn(".bgc-stage-strip", complete_visibility)
        complete_stages = self.css.split(
            'body[data-job-state="complete"] .stage-stack {', 1
        )[1].split("}", 1)[0]
        self.assertIn("grid-template-columns: 1fr", complete_stages)
        self.assertIn("stageStrip.hidden = false", self.js)
        self.assertNotIn("stageStrip.hidden = completePresentation", self.js)

        self.assertIn("display: none !important", complete_visibility)
        complete_caption = self.css.split(
            'body[data-job-state="complete"] .workflow-caption {', 1
        )[1].split("}", 1)[0]
        self.assertIn("justify-content: flex-end", complete_caption)
        complete_panel = self.css.split(
            'body[data-job-state="complete"] .dna-panel {', 1
        )[1].split("}", 1)[0]
        self.assertIn("height: 156px", complete_panel)
        complete_grid = self.css.split(
            'body[data-job-state="complete"] .state-grid {', 1
        )[1].split("}", 1)[0]
        self.assertIn(
            "grid-template-columns: minmax(17rem, .24fr) minmax(0, 1.16fr)",
            complete_grid,
        )
        self.assertIn(
            'body[data-job-state="complete"] .workflow-panel { align-self: start; }',
            self.css,
        )

    def test_completed_funbgcex_tab_uses_neutral_tool_color_not_failure_color(self) -> None:
        complete_outputs = self.css.split(
            'body[data-job-state="complete"] .output:nth-child(2) {', 1
        )[1].split("}", 1)[0]
        self.assertIn("background: var(--pink-soft)", complete_outputs)
        self.assertIn("color: var(--ink)", complete_outputs)
        self.assertNotIn("background: var(--pink);", complete_outputs)
        self.assertNotIn("color: white", complete_outputs)
    def test_rows_are_complete_scrollable_and_cache_busted(self) -> None:
        self.assertNotIn("MAX_GENOME_PROGRESS_ITEMS", self.js)
        self.assertIn("source.forEach((item, index) => {", self.js)
        self.assertIn("const items = Array.from(reconciled.values());", self.js)
        self.assertIn("overflow: auto", self.css)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", self.css)
        self.assertIn(".genome-progress-meter-row", self.css)
        meter_rule = self.css.split(".genome-progress-meter-row {", 1)[1].split(
            "}", 1
        )[0]
        self.assertIn("display: grid", meter_rule)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", meter_rule)
        self.assertNotIn("auto", meter_rule.split("grid-template-columns:", 1)[1].split(";", 1)[0])
        self.assertIn("align-items: center", meter_rule)
        progress_grid = self.css.split(".genome-progress-grid {", 1)[1].split(
            "}", 1
        )[0]
        progress_row = self.css.split(".genome-progress-row {", 1)[1].split(
            "}", 1
        )[0]
        organism = self.css.split(".genome-progress-organism {", 1)[1].split(
            "}", 1
        )[0]
        organism_name = self.css.split(
            ".genome-progress-organism strong {", 1
        )[1].split("}", 1)[0]
        self.assertIn("--genome-card-row-height: 5.2rem", self.css)
        self.assertIn("grid-auto-rows: var(--genome-card-row-height)", progress_grid)
        self.assertIn("min-height: var(--genome-card-row-height)", progress_row)
        self.assertIn("width: 100%", organism)
        self.assertIn("max-width: 100%", organism)
        self.assertIn("display: flex", organism)
        self.assertIn("flex: 1 1 auto", organism_name)
        self.assertIn("min-width: 0", organism_name)
        self.assertNotIn("grid-auto-rows: minmax(5rem, auto)", self.css)
        self.assertIn(
            "title.textContent = bgcWorkflowTitle(payload, genomeLayerActive)",
            self.js,
        )
        self.assertIn("20260723-timer-utc1", self.index)


    def test_live_polling_uses_current_attempt_and_stable_result_surfaces(self) -> None:
        self.assertIn("if (Number(job?.rerun_count || 0) > 0) return;", self.js)
        self.assertIn(
            "!previousJob || previousJob.status !== job.status || previousJob.stage !== job.stage",
            self.js,
        )
        self.assertIn("?compact=1", self.js)
        self.assertIn("filePayload.artifacts", self.js)
        self.assertIn(
            "activeJobMeta?.bigscape_viewer_available === true",
            self.js,
        )
        self.assertIn("bigscapeViewerFetch(jobId)", self.js)
        self.assertIn(
            "api/results/${encodeURIComponent(runId)}/bigscape-viewer-database",
            self.js,
        )
        self.assertNotIn("filePayload.bigscape_viewer_database", self.js)
        self.assertNotIn("internal update", self.js)
        self.assertIn(
            "if (allBgcTableState?.path === path) { renderAllBgcTable(); return; }",
            self.js,
        )
        all_bgc_columns = self.js.split(
            "const ALL_BGC_COLUMNS", 1
        )[1].split("]);", 1)[0]
        self.assertNotIn("prediction_method", all_bgc_columns)
        for label in [
            "FUNGAL FAMILIES",
            "BACTERIAL FAMILIES",
            "FUNGAL TOOL OVERLAP",
            "TREE",
        ]:
            self.assertIn(label, self.js)
        for filename in [
            "fungi_big_scape_multipanel.svg",
            "bacteria_big_scape_multipanel.svg",
            "bgc_overlap.svg",
            "clusterweave_taxon_tree.svg",
        ]:
            self.assertIn(filename, self.js)


if __name__ == "__main__":
    unittest.main()
