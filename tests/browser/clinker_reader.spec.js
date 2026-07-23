const { test, expect } = require('@playwright/test');

const baseUrl = 'http://127.0.0.1:4173';
const runId = 'CCCCCCCCCCCCCCCCCCCCCC';
const internalJobId = 'c1a2b3d4';

function jsonRoute(page, pattern, body) {
  return page.route(pattern, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  }));
}

test('clinker reader separates fungal and bacterial panels in a styled table', async ({ page }) => {
  await jsonRoute(page, '**/api/system/status*', {
    online: true,
    ready: true,
    worker: { status: 'ready', running_count: 0, active_count: 0 },
    capabilities: { stages: {} },
    submissions_open: true,
    jobs_processed: 1,
    running_jobs: 0,
    queued_jobs: 0,
    public_quota: { max_accessions: 50, max_genome_files: 50 },
  });
  await jsonRoute(page, '**/api/jobs', [{
    id: internalJobId,
    public_run_id: runId,
    name: 'Mixed clinker fixture',
    project_name: 'mixed_clinker',
    status: 'success',
    stage: 'complete',
    created_at: '2026-07-22T12:00:00',
    updated_at: '2026-07-22T12:10:00',
    log_count: 0,
    result_file_count: 2,
    analysis_scope: 'both',
    taxon_counts: { fungi: 1, bacteria: 1, total: 2 },
  }]);
  await jsonRoute(page, `**/api/jobs/${internalJobId}?compact=1`, {
    id: internalJobId,
    public_run_id: runId,
    name: 'Mixed clinker fixture',
    project_name: 'mixed_clinker',
    status: 'success',
    stage: 'complete',
    created_at: '2026-07-22T12:00:00',
    updated_at: '2026-07-22T12:10:00',
    log_count: 0,
    result_file_count: 2,
    result_files: [],
    analysis_scope: 'both',
    taxon_counts: { fungi: 1, bacteria: 1, total: 2 },
    genome_progress: [
      { genome_id: 'Fungus_alpha', display_label: 'Fungus alpha', taxon_group: 'fungi', percent: 100, status: 'complete', terminal: true },
      { genome_id: 'bacteria_Bacterium_beta', display_label: 'Bacterium beta', taxon_group: 'bacteria', percent: 100, status: 'complete', terminal: true },
    ],
  });
  await jsonRoute(page, `**/api/results/${runId}/artifacts`, {
    run_id: runId,
    public_run_id: runId,
    generation: 'clinker-generation',
    result_index_state: 'attested',
    artifacts: [
      {
        id: 'FFFFFFFFFFFFFFFFFFFFFF',
        category: 'synteny',
        kind: 'html',
        role: 'page',
        mime: 'text/html; charset=utf-8',
        filename: 'panel.html',
        label: 'Fungal terpene panel',
        taxon_group: 'fungi',
        genome_label: 'Fungus_alpha',
        track: 'atlas',
        bundle_id: 'fungalClinkerBundle01',
        previewable: true,
        downloadable: true,
      },
      {
        id: 'BBBBBBBBBBBBBBBBBBBBBB',
        category: 'synteny',
        kind: 'html',
        role: 'page',
        mime: 'text/html; charset=utf-8',
        filename: 'panel.html',
        label: 'Bacterial NRPS panel',
        taxon_group: 'bacteria',
        genome_label: 'bacteria_Bacterium_beta',
        track: 'priority',
        bundle_id: 'bacteriaClinkerBundle1',
        previewable: true,
        downloadable: true,
      },
    ],
  });
  await jsonRoute(page, `**/api/results/${runId}/activity`, { public_events: [], genome_progress: [] });

  await page.goto(baseUrl);
  await page.evaluate(() => openOpsPanel({ tab: 'jobs', focusPanel: false }));
  await page.locator(`.diagnostic-job-card[data-job-id="${internalJobId}"]`).click();
  await page.evaluate(() => closeOpsPanel({ returnFocus: false }));
  await page.getByRole('tab', { name: 'CLINKER' }).click();

  const reader = page.locator('.clinker-reader');
  await expect(reader).toBeVisible();
  await expect(reader.locator('table thead')).toContainText('Organism');
  await expect(reader.locator('table thead')).toContainText('Panel');
  await expect(page.getByRole('tab', { name: /FUNGAL PANELS/ })).toHaveAttribute('aria-selected', 'true');
  await expect(reader.locator('tbody tr')).toHaveCount(1);
  await expect(reader.locator('tbody tr')).toContainText('Fungus alpha');
  await expect(reader.locator('tbody tr')).toContainText('Fungal Terpene Panel');

  await page.getByRole('tab', { name: /BACTERIAL PANELS/ }).click();
  await expect(reader).toHaveAttribute('data-clinker-taxon', 'bacteria');
  await expect(reader.locator('tbody tr')).toHaveCount(1);
  await expect(reader.locator('tbody tr')).toContainText('Bacterium beta');
  await expect(reader.locator('tbody tr')).not.toContainText('bacteria Bacterium');
  await expect(reader.locator('tbody tr')).toContainText('Priority');
  const href = await reader.getByRole('link', { name: 'Open' }).getAttribute('href');
  expect(new URL(href, baseUrl).pathname).toBe(`/api/results/${runId}/artifacts/BBBBBBBBBBBBBBBBBBBBBB`);
  expect(href).not.toContain('data/results');
});
