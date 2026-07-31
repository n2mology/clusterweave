const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const baseUrl = 'http://127.0.0.1:4173';
const evidenceDir = process.env.CLUSTERWEAVE_R13B_EVIDENCE_DIR || '';

async function captureQaEvidence(page, name) {
  if (!evidenceDir) return;
  fs.mkdirSync(evidenceDir, { recursive: true });
  const phase = process.env.CLUSTERWEAVE_R13B_PHASE || 'capture';
  await page.screenshot({
    path: path.join(evidenceDir, `${phase}-${name}.png`),
    fullPage: true,
    animations: 'disabled',
  });
  const snapshot = await page.evaluate(() => Object.fromEntries([
    '#ops-side-panel',
    '.drawer-panels',
    '#results-card',
    '#results-job-runtime',
    '.sr-only',
  ].map(selector => {
    const node = document.querySelector(selector);
    if (!node) return [selector, null];
    const style = getComputedStyle(node);
    const box = node.getBoundingClientRect();
    return [selector, {
      display: style.display,
      width: style.width,
      height: style.height,
      padding: style.padding,
      overflow: style.overflow,
      clip: style.clip,
      opacity: style.opacity,
      visibility: style.visibility,
      animationDuration: style.animationDuration,
      transitionDuration: style.transitionDuration,
      box: { x: box.x, y: box.y, width: box.width, height: box.height },
    }];
  })));
  fs.writeFileSync(
    path.join(evidenceDir, `${phase}-${name}.json`),
    `${JSON.stringify(snapshot, null, 2)}\n`,
  );
}
const publicRunId = 'lazyPublicRunId123456x';
const completedInternalId = '1a2b3c4d';
const runningInternalId = 'efb9c36c';

test('admin job selection is metadata-only and QA lazily pages logs', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const logRequests = [];
  const catalogRequests = [];
  const wrongCatalogRequests = [];
  await page.route('**/api/system/status*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      online: true,
      ready: true,
      worker: { status: 'ready', running_count: 0, active_count: 0 },
      capabilities: { stages: {} },
      service: 'online',
      submissions_open: true,
      jobs_processed: 1,
      running_jobs: 0,
      queued_jobs: 0,
      public_quota: { max_accessions: 50, max_genome_files: 50 },
    }),
  }));
  await page.route('**/api/jobs', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: completedInternalId,
      name: 'Lazy QA fixture',
      project_name: 'lazy_project',
      status: 'success',
      stage: 'complete',
      created_at: '2026-07-21T08:00:00',
      updated_at: '2026-07-21T08:01:00',
      log_count: 1000,
      result_file_count: 0,
      analysis_scope: 'fungi',
    }]),
  }));
  await page.route(`**/api/jobs/${completedInternalId}?compact=1`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: completedInternalId,
      public_run_id: publicRunId,
      name: 'Lazy QA fixture',
      project_name: 'lazy_project',
      status: 'success',
      stage: 'complete',
      created_at: '2026-07-21T08:00:00',
      updated_at: '2026-07-21T08:01:00',
      log_count: 1000,
      result_file_count: 1,
      result_files: [],
      analysis_scope: 'fungi',
    }),
  }));
  await page.route(`**/api/results/${publicRunId}/artifacts`, route => {
    catalogRequests.push(new URL(route.request().url()).pathname);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_id: publicRunId,
        public_run_id: publicRunId,
        generation: 'lazy-generation',
        result_index_state: 'attested',
        artifacts: [{
          id: 'AAAAAAAAAAAAAAAAAAAAAA',
          category: 'antismash',
          kind: 'html',
          role: 'index',
          mime: 'text/html; charset=utf-8',
          filename: 'index.html',
          label: 'Fixture genome antiSMASH',
          genome_label: 'Fixture genome',
          bundle_id: 'fixtureAntismashBundle1',
          previewable: true,
          downloadable: true,
        }],
      }),
    });
  });
  await page.route(`**/api/results/${completedInternalId}/artifacts`, route => {
    wrongCatalogRequests.push(new URL(route.request().url()).pathname);
    return route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Not found' }),
    });
  });
  await page.route(`**/api/jobs/${completedInternalId}/logs?*`, async route => {
    const url = new URL(route.request().url());
    logRequests.push(url.search);
    let payload;
    if (url.searchParams.has('tail')) {
      const lines = Array.from({ length: 500 }, (_, index) => `line ${index + 500}`);
      for (let index = 0; index < 30; index += 1) {
        lines[460 + index] = `[WARN] fixture warning ${index + 1}`;
      }
      lines[489] = '[WARN] literal <img src=x onerror="globalThis.qaInjected=true"> text';
      lines[496] = '[INFO] Stage 1/4: running run_annotation_and_detection.sh';
      lines[497] = '[INFO] [1/1] genome=fungus_one taxon=fungi prediction=funannotate';
      lines[498] = '[INFO] ANTISMASH_RECORD_PROGRESS genome=fungus_one record=record_a ordinal=1/2 percent=60 bar=[############--------] message="Record analysis in progress"';
      lines[499] = '[INFO] TOOL_PROGRESS genome=fungus_one tool=antismash phase=detect message="Scanning protein domains"';
      payload = {
        lines,
        start: 500,
        end: 1000,
        total: 1000,
        generation: 'generation-one',
        has_earlier: true,
      };
    } else if (url.searchParams.has('before')) {
      payload = {
        lines: Array.from({ length: 500 }, (_, index) => `line ${index}`),
        start: 0,
        end: 500,
        total: 1000,
        generation: 'generation-one',
        has_earlier: false,
      };
    } else {
      payload = {
        lines: ['[INFO] TOOL_HEARTBEAT genome=fungus_one tool=antismash phase=detect elapsed=1200s'],
        total: 1001,
        generation: 'generation-one',
      };
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });
  });

  await page.goto(baseUrl);
  await expect(page.locator('body')).toHaveAttribute('data-access', 'local');
  await page.evaluate(() => {
    openOpsPanel({ tab: 'jobs', focusPanel: false });
  });
  const card = page.locator(`.diagnostic-job-card[data-job-id="${completedInternalId}"]`);
  await expect(card).toBeVisible();
  await card.click();
  await expect(page.locator('#qa-job-id')).toHaveText(completedInternalId);
  await expect.poll(() => catalogRequests.length).toBe(1);
  expect(catalogRequests).toEqual([`/api/results/${publicRunId}/artifacts`]);
  expect(wrongCatalogRequests).toHaveLength(0);
  expect(logRequests).toHaveLength(0);
  const antismashTab = page.locator('[role="tab"][data-output-key="antismash"]');
  await expect(antismashTab).toBeEnabled();
  await expect(antismashTab).toBeVisible();
  await expect(page.locator('#files-container .artifact-reader-title')).toHaveText('ANTISMASH');
  await expect(page.locator('#files-container .result-tool-row')).toHaveCount(1);
  await expect(page.locator('#files-container .result-tool-row')).toContainText('Fixture genome');
  const openHref = await page.locator('#files-container .result-tool-row a', { hasText: 'Open' }).getAttribute('href');
  expect(new URL(openHref, baseUrl).pathname).toBe(
    `/api/results/${publicRunId}/artifacts/AAAAAAAAAAAAAAAAAAAAAA`,
  );
  expect(openHref).not.toContain(completedInternalId);
  expect(openHref).not.toContain('data/results');
  expect(await page.evaluate(() => ({
    activePublicRunId,
    resultFileCount: activeJobMeta?.result_file_count,
    transportedResultFiles: activeJobMeta?.result_files?.length,
    artifactCount: activeResultArtifactById.size,
    activeResultCount: activeResultFiles.length,
    dashboard: document.body.dataset.resultsDashboard,
  }))).toEqual({
    activePublicRunId: publicRunId,
    resultFileCount: 1,
    transportedResultFiles: 0,
    artifactCount: 1,
    activeResultCount: 1,
    dashboard: 'open',
  });
  await expect(page.locator('body')).toHaveAttribute('data-results-available', 'true');
  await expect(page.locator('#workflow-progress-panel')).toBeHidden();
  await expect(page.locator('#results-render-switch, #results-render-workbench, #results-render-molecular, #molecular-renderer-panel, #molecular-canvas-host')).toHaveCount(0);
  await expect(page.locator('[data-results-render-mode="molecular"]')).toHaveCount(0);
  await expect(page.locator('.diagnostic-job-card .job-stage-pips')).toHaveCount(0);
  const compatibilityStyles = await page.evaluate(() => {
    const panels = getComputedStyle(document.querySelector('.drawer-panels'));
    const hiddenText = getComputedStyle(document.querySelector('.sr-only'));
    return {
      panels: { overflow: panels.overflow, padding: panels.padding },
      hiddenText: {
        width: hiddenText.width,
        height: hiddenText.height,
        clip: hiddenText.clip,
        overflow: hiddenText.overflow,
      },
    };
  });
  expect(compatibilityStyles).toEqual({
    panels: { overflow: 'auto', padding: '12px' },
    hiddenText: { width: '1px', height: '1px', clip: 'rect(0px, 0px, 0px, 0px)', overflow: 'hidden' },
  });
  await captureQaEvidence(page, 'results-admin-desktop-reduced');
  const completedPanelWidths = await page.evaluate(() => ({
    setup: document.getElementById('upload-card')?.getBoundingClientRect().width || 0,
    results: document.getElementById('results-card')?.getBoundingClientRect().width || 0,
  }));
  expect(completedPanelWidths.setup).toBeGreaterThan(0);
  expect(Math.abs(completedPanelWidths.setup - completedPanelWidths.results)).toBeLessThanOrEqual(1);
  const totalRuntime = page.locator('#results-job-runtime');
  await expect(totalRuntime).toBeVisible();
  await expect(totalRuntime).toHaveText('(00:00:01:00)');
  await expect(totalRuntime).toHaveAttribute('title', 'Final total job runtime');
  for (const width of [1280, 760, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const geometry = await page.evaluate(() => {
      const header = document.querySelector('#results-card > .module-head')?.getBoundingClientRect();
      const timer = document.getElementById('results-job-runtime')?.getBoundingClientRect();
      const status = document.getElementById('results-status')?.getBoundingClientRect();
      return header && timer && status ? {
        header: { left: header.left, right: header.right },
        timer: { left: timer.left, right: timer.right },
        status: { left: status.left, right: status.right },
      } : null;
    });
    expect(geometry).not.toBeNull();
    expect(geometry.timer.left).toBeGreaterThanOrEqual(geometry.header.left);
    expect(geometry.timer.right).toBeLessThanOrEqual(geometry.status.left + 0.5);
    expect(geometry.status.right).toBeLessThanOrEqual(geometry.header.right + 0.5);
  }

  await page.getByRole('tab', { name: 'QA Console' }).click();
  await expect.poll(() => logRequests.length).toBe(1);
  await expect(page.locator('[data-qa-log-view="tree"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#log-terminal .progress-tree-row')).toHaveCount(40);
  expect(logRequests[0]).toContain('tail=500');
  await expect(page.locator('#load-earlier-logs')).toBeVisible();
  const treeScrollBefore = await page.locator('#log-terminal').evaluate(term => { term.scrollTop = 80; return term.scrollTop; });
  expect(treeScrollBefore).toBeGreaterThan(0);

  await page.locator('#load-earlier-logs').click();
  await expect(page.locator('#log-terminal .progress-tree-row')).toHaveCount(40);
  const treeScrollAfter = await page.locator('#log-terminal').evaluate(term => term.scrollTop);
  expect(Math.abs(treeScrollAfter - treeScrollBefore)).toBeLessThanOrEqual(1);
  await page.locator('[data-qa-log-view="raw"]').click();
  await expect(page.locator('#log-terminal')).toHaveAttribute('aria-label', 'Selected run raw log');
  await expect(page.locator('#log-terminal .log-line')).toHaveCount(1000);
  await expect(page.locator('#log-terminal .log-line').first()).toHaveText('line 0');
  await expect(page.locator('#load-earlier-logs')).toBeHidden();
  expect(logRequests.some(query => query.includes('before=500'))).toBeTruthy();
  await expect(totalRuntime).toHaveText('(00:00:01:00)');

  await page.evaluate(() => syncActiveAdminLogs(false));
  await expect.poll(() => logRequests.length).toBe(3);
  expect(logRequests[2]).toContain('since=1000');
  await expect(page.locator('#log-terminal .log-line')).toHaveCount(1001);
  await expect(page.locator('#log-terminal .log-line').last()).toHaveText('[INFO] TOOL_HEARTBEAT genome=fungus_one tool=antismash phase=detect elapsed=1200s');
  const rawViewButton = page.locator('[data-qa-log-view="raw"]');
  await rawViewButton.press('ArrowLeft');
  await expect(page.locator('[data-qa-log-view="tree"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#log-terminal')).toHaveAttribute('aria-label', 'Selected run progress tree');
  const antiSmashBranch = page.locator('#log-terminal [data-tree-key="tool:annotation:fungus_one:antiSMASH"]');
  await expect(antiSmashBranch).toHaveCount(1);
  await expect(antiSmashBranch.locator('.progress-tree-meter')).toContainText('[######----]  60% - Scanning protein domains · 20m 00s active');
  await expect(page.locator('#log-terminal [data-tree-state="warning"]')).toHaveCount(30);
  await expect(page.locator('#log-terminal img')).toHaveCount(0);
  expect(await page.evaluate(() => globalThis.qaInjected)).toBeUndefined();
  await page.locator('[data-qa-log-view="tree"]').press('ArrowRight');
  await expect(rawViewButton).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#log-terminal .log-line')).toHaveCount(1001);
  expect(catalogRequests).toHaveLength(1);
  await captureQaEvidence(page, 'qa-console-mobile-reduced');
});

test('running admin job hydrates sanitized genome progress without QA logs', async ({ page }) => {
  const runId = 'BBBBBBBBBBBBBBBBBBBBBB';
  const activityRequests = [];
  const logRequests = [];
  const genomes = [
    {
      genome_id: 'Fungi_A',
      organism_name: 'Fungal genome A',
      taxon_group: 'fungi',
      percent: 66,
      status: 'running',
      stage: 'antismash',
      tool: 'antiSMASH',
      annotation_method: 'funannotate',
      message: 'antiSMASH record analysis in progress',
      activity_message: 'Scanning protein domains',
      region_progress: { processed: 2, total: 7, active: 3, failed: 0 },
      stage_states: {
        genome_acquired: { status: 'complete' },
        funannotate: { status: 'complete' },
        antismash: { status: 'running' },
      },
    },
    {
      genome_id: 'Fungi_B',
      organism_name: 'Fungal genome B',
      taxon_group: 'fungi',
      percent: 35,
      status: 'running',
      stage: 'antismash',
      tool: 'antiSMASH',
      annotation_method: 'funannotate',
      message: 'antiSMASH record analysis in progress',
    },
    {
      genome_id: 'Fungi_C',
      organism_name: 'Fungal genome C',
      taxon_group: 'fungi',
      percent: 36,
      status: 'running',
      stage: 'antismash',
      tool: 'antiSMASH',
      annotation_method: 'funannotate',
      message: 'antiSMASH record analysis in progress',
    },
    {
      genome_id: 'Fungi_D',
      organism_name: 'Fungal genome D',
      taxon_group: 'fungi',
      percent: 8,
      status: 'queued',
      stage: 'annotation',
      annotation_method: 'funannotate',
      message: 'Waiting for an annotation worker',
    },
    {
      genome_id: 'Bacteria_A',
      organism_name: 'Bacterial genome A',
      taxon_group: 'bacteria',
      percent: 8,
      status: 'queued',
      stage: 'annotation',
      tool: 'prodigal',
      annotation_method: 'prodigal',
      message: 'Waiting for antiSMASH and Prodigal',
    },
    {
      genome_id: 'Bacteria_B',
      organism_name: 'Bacterial genome B',
      taxon_group: 'bacteria',
      percent: 8,
      status: 'queued',
      stage: 'annotation',
      tool: 'prodigal',
      annotation_method: 'prodigal',
      message: 'Waiting for antiSMASH and Prodigal',
    },
  ];

  await page.route('**/api/system/status*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      online: true,
      ready: true,
      worker: { status: 'busy', running_count: 1, active_count: 1 },
      capabilities: { stages: {} },
      service: 'online',
      submissions_open: true,
      jobs_processed: 1,
      running_jobs: 1,
      queued_jobs: 0,
      public_quota: { max_accessions: 50, max_genome_files: 50 },
    }),
  }));
  await page.route('**/api/jobs', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: runningInternalId,
      public_run_id: runId,
      name: 'Mixed progress fixture',
      project_name: 'mixed_progress',
      status: 'running',
      stage: 'annotation',
      created_at: '2026-07-22T08:00:00',
      updated_at: '2026-07-22T08:01:00',
      log_count: 32,
      result_file_count: 0,
      analysis_scope: 'both',
      taxon_counts: { fungi: 4, bacteria: 2, total: 6 },
    }]),
  }));
  await page.route(`**/api/jobs/${runningInternalId}?compact=1`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: runningInternalId,
      public_run_id: runId,
      name: 'Mixed progress fixture',
      project_name: 'mixed_progress',
      status: 'running',
      stage: 'annotation',
      created_at: '2026-07-22T08:00:00',
      updated_at: '2026-07-22T08:01:00',
      log_count: 32,
      result_file_count: 0,
      result_files: [],
      analysis_scope: 'both',
      taxon_counts: { fungi: 4, bacteria: 2, total: 6 },
    }),
  }));
  await page.route(`**/api/results/${runId}/activity`, route => {
    activityRequests.push(new URL(route.request().url()).pathname);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ public_events: [], genome_progress: genomes }),
    });
  });
  await page.route(`**/api/results/${runId}/artifacts`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      run_id: runId,
      public_run_id: runId,
      generation: 'running-generation',
      result_index_state: 'attested',
      artifacts: [],
    }),
  }));
  await page.route(`**/api/jobs/${runningInternalId}/logs?*`, route => {
    logRequests.push(new URL(route.request().url()).search);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ lines: [], total: 32, generation: 'running-generation' }),
    });
  });

  await page.goto(baseUrl);
  await expect(page.locator('body')).toHaveAttribute('data-access', 'local');
  await page.evaluate(() => openOpsPanel({ tab: 'jobs', focusPanel: false }));
  const card = page.locator(`.diagnostic-job-card[data-job-id="${runningInternalId}"]`);
  await expect(card).toBeVisible();
  await card.click();

  await expect.poll(() => activityRequests.length).toBe(1);
  await expect(page.locator('#bgc-workflow-station')).toHaveClass(/has-genome-progress/);
  await expect(page.locator('body')).toHaveAttribute('data-results-available', 'false');
  await expect(page.locator('#workflow-progress-panel')).toBeVisible();
  await expect(page.locator('#bgc-genome-progress-layer')).toBeVisible();
  await expect(page.locator('#bgc-genome-progress-grid .genome-progress-row')).toHaveCount(6);
  const semanticStages = await page.locator('#bgc-stage-strip .bgc-stage-card').evaluateAll(cards => cards.map(card => ({
    stage: card.dataset.bgcStage || '',
    semanticState: ['complete', 'running', 'error', 'failed', 'pending', 'waiting', 'blocked', 'skipped']
      .concat('done').find(state => card.classList.contains(state)) || '',
  })));
  expect(semanticStages.length).toBeGreaterThan(0);
  expect(semanticStages.every(stage => stage.stage && stage.semanticState)).toBeTruthy();
  const lateAntismash = page.locator('#bgc-genome-progress-grid .genome-progress-row').first();
  await expect(lateAntismash.locator('.genome-progress-percent')).toHaveCount(0);
  await expect(lateAntismash.locator('.genome-progress-status')).toHaveText(
    'Region (2/7) · 3 active · Scanning protein domains',
  );
  await expect(lateAntismash.locator('[role="progressbar"]')).toHaveAttribute('aria-valuenow', '29');
  await expect(lateAntismash.locator('.genome-progress-segment')).toHaveCount(5);
  const runningRuntime = page.locator('#results-job-runtime');
  await expect(runningRuntime).toBeVisible();
  await expect(runningRuntime).toHaveText(/^\(\d{2,}:\d{2}:\d{2}:\d{2}\)$/);
  await expect(runningRuntime).toHaveAttribute('title', 'Total job runtime');
  const initialRuntimeText = await runningRuntime.textContent();
  await expect.poll(() => runningRuntime.textContent(), { timeout: 2500 }).not.toBe(initialRuntimeText);
  await expect(lateAntismash.locator('.genome-progress-segment[title="FunBGCeX: 0%"]')).toHaveCount(1);
  await expect(page.locator('#bgc-dna-progress-region')).toBeHidden();
  expect(logRequests).toHaveLength(0);
  expect(await page.evaluate(() => {
    const payload = bgcWorkflowPayload(activeJobMeta);
    return {
      metaGenomeCount: activeJobMeta?.genome_progress?.length || 0,
      payloadGenomeCount: payload.genomes.length,
      currentStepId: payload.currentStepId,
      genomeProgressHandoff: payload.genomeProgressHandoff,
    };
  })).toEqual({
    metaGenomeCount: 6,
    payloadGenomeCount: 6,
    currentStepId: 'annotation',
    genomeProgressHandoff: false,
  });
});

test('late metadata from an earlier admin selection cannot replace the active job', async ({ page }) => {
  const firstId = 'aaaa1111';
  const secondId = 'bbbb2222';
  const firstPublicId = 'R01fStaleFirstRun0001';
  const secondPublicId = 'R01fStaleSecondRun001';
  const jobs = [
    {
      id: firstId,
      public_run_id: firstPublicId,
      name: 'Delayed first selection',
      project_name: 'delayed_first',
      status: 'running',
      stage: 'annotation',
      created_at: '2026-07-24T13:00:00',
      updated_at: '2026-07-24T13:01:00',
      log_count: 0,
      result_file_count: 0,
      analysis_scope: 'fungi',
    },
    {
      id: secondId,
      public_run_id: secondPublicId,
      name: 'Current second selection',
      project_name: 'current_second',
      status: 'running',
      stage: 'annotation',
      created_at: '2026-07-24T13:02:00',
      updated_at: '2026-07-24T13:03:00',
      log_count: 0,
      result_file_count: 0,
      analysis_scope: 'bacteria',
    },
  ];
  let releaseFirst;
  const firstGate = new Promise(resolve => { releaseFirst = resolve; });
  let firstRequests = 0;
  let firstResponses = 0;
  const activityRequests = [];

  await page.route('**/api/system/status*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      online: true,
      ready: true,
      worker: { status: 'busy', running_count: 2, active_count: 2 },
      capabilities: { stages: {} },
      service: 'online',
      submissions_open: true,
      jobs_processed: 2,
      running_jobs: 2,
      queued_jobs: 0,
      public_quota: { max_accessions: 50, max_genome_files: 50 },
    }),
  }));
  await page.route('**/api/jobs', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(jobs),
  }));
  await page.route(`**/api/jobs/${firstId}?compact=1`, async route => {
    firstRequests += 1;
    await firstGate;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobs[0]) });
    firstResponses += 1;
  });
  await page.route(`**/api/jobs/${secondId}?compact=1`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(jobs[1]),
  }));
  await page.route('**/api/results/*/activity', route => {
    activityRequests.push(new URL(route.request().url()).pathname);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ public_events: [], genome_progress: [] }),
    });
  });
  await page.route('**/api/results/*/artifacts', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ result_index_state: 'pending', artifacts: [] }),
  }));

  await page.goto(baseUrl);
  await page.evaluate(() => openOpsPanel({ tab: 'jobs', focusPanel: false }));
  const firstCard = page.locator(`.diagnostic-job-card[data-job-id="${firstId}"]`);
  const secondCard = page.locator(`.diagnostic-job-card[data-job-id="${secondId}"]`);
  await expect(firstCard).toBeVisible();
  await expect(secondCard).toBeVisible();

  await firstCard.dispatchEvent('click');
  await expect.poll(() => firstRequests).toBe(1);
  await secondCard.dispatchEvent('click');
  await expect.poll(() => page.evaluate(() => activeJobMeta?.id || '')).toBe(secondId);
  await expect(page.locator('#qa-job-id')).toHaveText(secondId);
  await expect(secondCard).toHaveClass(/is-selected/);
  await expect(firstCard).not.toHaveClass(/is-selected/);

  releaseFirst();
  await expect.poll(() => firstResponses).toBe(1);
  await page.waitForTimeout(250);
  expect(await page.evaluate(() => ({
    activeJobId,
    activeMetaId: activeJobMeta?.id || '',
    activePublicRunId,
  }))).toEqual({
    activeJobId: secondId,
    activeMetaId: secondId,
    activePublicRunId: secondPublicId,
  });
  expect(activityRequests).not.toContain(`/api/results/${firstPublicId}/activity`);
  await expect(secondCard).toHaveClass(/is-selected/);
  await expect(firstCard).not.toHaveClass(/is-selected/);
});
