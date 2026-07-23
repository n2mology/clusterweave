const { test, expect } = require('@playwright/test');

const baseUrl = 'http://127.0.0.1:4173';

function completedJob(id, projectName) {
  return {
    id,
    name: projectName,
    project_name: projectName,
    status: 'success',
    stage: 'complete',
    created_at: '2026-07-16T15:29:12',
    updated_at: '2026-07-22T18:27:55',
    rerun_count: 11,
    result_file_count: 12,
    rerun_stage_settings: {
      run_genome_prep: true,
      run_annotation: true,
      run_bigscape: true,
      run_summary: true,
      run_crosswalk: true,
      run_clinker: true,
      execute_clinker: true,
      run_figures: true,
      run_nplinker: false,
    },
    settings: {
      run_genome_prep: false,
      run_annotation: false,
      run_bigscape: false,
      run_summary: false,
      run_crosswalk: false,
      run_clinker: false,
      execute_clinker: false,
      run_figures: true,
      run_nplinker: false,
    },
  };
}

test('rerun opens as one normal-flow job disclosure and uses original stage eligibility', async ({ page }) => {
  const jobs = [
    completedJob('synthetic-fixture-job', 'Repeated rerun fixture'),
    completedJob('synthetic-neighbor-job', 'Neighboring completed run'),
  ];
  const reloadRequests = [];
  const rerunRequests = [];

  await page.route('**/api/system/status*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      online: true,
      ready: true,
      worker: { status: 'ready', running_count: 0, active_count: 0 },
      capabilities: { stages: {} },
      submissions_open: true,
      jobs_processed: 2,
      running_jobs: 0,
      queued_jobs: 0,
      public_quota: { max_accessions: 50, max_genome_files: 50 },
    }),
  }));
  await page.route('**/api/jobs', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(jobs),
  }));
  await page.route('**/api/results/*/artifacts', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ artifacts: [] }),
  }));
  await page.route('**/api/results/*/activity', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ public_events: [] }),
  }));
  await page.route(/\/api\/results\/([A-Za-z0-9_-]+)$/, route => {
    reloadRequests.push(route.request().url());
    const id = new URL(route.request().url()).pathname.split('/').pop();
    const job = jobs.find(item => item.id === id) || {};
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...job, status: 'pending', stage: 'queued', result_files: [] }),
    });
  });
  await page.route(/\/api\/jobs\/([A-Za-z0-9_-]+)$/, route => {
    const id = new URL(route.request().url()).pathname.split('/').pop();
    const job = jobs.find(item => item.id === id) || {};
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...job, status: 'pending', stage: 'queued', result_files: [] }),
    });
  });
  await page.route(/\/api\/jobs\/([A-Za-z0-9_-]+)\/rerun$/, route => {
    rerunRequests.push({
      url: route.request().url(),
      method: route.request().method(),
      payload: route.request().postDataJSON(),
    });
    return route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ id: 'synthetic-fixture-job', status: 'pending', stage: 'queued' }),
    });
  });

  await page.goto(baseUrl);
  await page.evaluate(() => openOpsPanel({ tab: 'jobs', focusPanel: false }));

  const firstItem = page.locator('[data-diagnostic-job-item][data-job-id="synthetic-fixture-job"]');
  const secondItem = page.locator('[data-diagnostic-job-item][data-job-id="synthetic-neighbor-job"]');
  await expect(firstItem).toBeVisible();
  await expect(secondItem).toBeVisible();

  await firstItem.getByRole('button', { name: 'Rerun' }).click();
  const firstDisclosure = firstItem.locator('details.rerun-disclosure');
  await expect(firstDisclosure).toHaveAttribute('open', '');
  await expect(firstItem.getByRole('button', { name: 'Rerun' })).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('details.rerun-disclosure[open]')).toHaveCount(1);

  for (const stage of ['prep', 'annotation', 'bigscape', 'summary', 'clinker', 'figures']) {
    await expect(firstDisclosure.locator(`[data-diagnostic-rerun-stage="${stage}"]`)).toBeEnabled();
  }
  await expect(firstDisclosure.locator('[data-diagnostic-rerun-stage="nplinker"]')).toBeDisabled();

  const boxes = await page.evaluate(() => {
    const item = document.querySelector('[data-diagnostic-job-item][data-job-id="synthetic-fixture-job"]');
    const card = item?.querySelector('.diagnostic-job-card')?.getBoundingClientRect();
    const disclosure = item?.querySelector('.rerun-disclosure')?.getBoundingClientRect();
    const neighbor = document.querySelector('[data-diagnostic-job-item][data-job-id="synthetic-neighbor-job"]')?.getBoundingClientRect();
    return {
      cardBottom: card?.bottom || 0,
      disclosureTop: disclosure?.top || 0,
      disclosureBottom: disclosure?.bottom || 0,
      neighborTop: neighbor?.top || 0,
      disclosurePosition: item?.querySelector('.rerun-disclosure')
        ? getComputedStyle(item.querySelector('.rerun-disclosure')).position : '',
    };
  });
  expect(boxes.disclosurePosition).toBe('static');
  expect(boxes.disclosureTop).toBeGreaterThanOrEqual(boxes.cardBottom);
  expect(boxes.neighborTop).toBeGreaterThanOrEqual(boxes.disclosureBottom);

  const queueButton = firstDisclosure.getByRole('button', { name: 'Queue selected stages' });
  expect(reloadRequests).toHaveLength(0);
  await expect(queueButton).toBeDisabled();
  await firstDisclosure.locator('[data-diagnostic-rerun-stage="annotation"]').check();
  await firstDisclosure.locator('[data-diagnostic-rerun-stage="clinker"]').check();
  await expect(queueButton).toBeEnabled();
  await queueButton.click();
  await expect.poll(() => rerunRequests.length).toBe(1);
  expect(rerunRequests[0]).toEqual({
    url: baseUrl + '/api/jobs/synthetic-fixture-job/rerun',
    method: 'POST',
    payload: {
      run_genome_prep: false,
      run_annotation: true,
      run_bigscape: false,
      run_summary: false,
      run_crosswalk: false,
      run_clinker: true,
      execute_clinker: true,
      run_figures: false,
      run_nplinker: false,
      force: false,
    },
  });
  await expect(page.locator('[data-diagnostic-job-item][data-job-id="synthetic-fixture-job"] details.rerun-disclosure')).toHaveCount(0);

  await secondItem.getByRole('button', { name: 'Rerun' }).click();
  const refreshedSecond = page.locator('[data-diagnostic-job-item][data-job-id="synthetic-neighbor-job"]');
  const secondDisclosure = refreshedSecond.locator('details.rerun-disclosure');
  await expect(secondDisclosure).toHaveAttribute('open', '');
  await expect(page.locator('details.rerun-disclosure[open]')).toHaveCount(1);
  await expect(page.locator('[data-diagnostic-job-item][data-job-id="synthetic-fixture-job"] details.rerun-disclosure')).toHaveCount(0);

  await secondDisclosure.locator('summary').click();
  await expect(secondDisclosure).not.toHaveAttribute('open', '');
  await expect(refreshedSecond.getByRole('button', { name: 'Rerun' })).toHaveAttribute('aria-expanded', 'false');
  expect(await page.evaluate(() => rerunScopeOpenJobId)).toBe('');
  expect(reloadRequests).toEqual([
    baseUrl + '/api/results/synthetic-fixture-job',
  ]);
});
