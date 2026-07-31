const { test, expect } = require('@playwright/test');

const baseURL = 'http://127.0.0.1:4175';
const fixtures = {
  queued: {
    runId: 'R01eQueuedRunFixture01',
    token: 'r01e-queued-read-token',
    internalId: 'r01equeued',
  },
  running: {
    runId: 'R01eRunningRunFixture1',
    token: 'r01e-running-read-token',
    internalId: 'r01erunning',
  },
  completed: {
    runId: 'R01eDoneRunFixture0001',
    token: 'r01e-completed-read-token',
    internalId: 'r01edone',
  },
};

function observeBrowser(page) {
  const state = {
    apiRequests: [],
    consoleErrors: [],
    failedRequests: [],
    failedResponses: [],
    pageErrors: [],
  };
  page.on('console', message => {
    if (message.type() === 'error') state.consoleErrors.push(message.text());
  });
  page.on('pageerror', error => state.pageErrors.push(error.message));
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.origin === baseURL && url.pathname.startsWith('/api/')) {
      state.apiRequests.push({
        method: request.method(),
        path: url.pathname,
        authorization: request.headers().authorization || '',
      });
    }
  });
  page.on('requestfailed', request => {
    const url = new URL(request.url());
    if (url.origin === baseURL) {
      state.failedRequests.push(`${request.method()} ${url.pathname}: ${request.failure()?.errorText || 'failed'}`);
    }
  });
  page.on('response', response => {
    const url = new URL(response.url());
    if (url.origin === baseURL && response.status() >= 400) {
      state.failedResponses.push(`${response.status()} ${url.pathname}`);
    }
  });
  return state;
}

async function openPublicRun(page, fixture) {
  const documentResponse = await page.goto(`${baseURL}/#/results/${fixture.runId}/${fixture.token}`);
  expect(documentResponse).not.toBeNull();
  expect(documentResponse.status()).toBe(200);
  await expect.poll(() => page.url()).toBe(`${baseURL}/#/results/${fixture.runId}`);
  await expect(page.locator('body')).toHaveAttribute('data-access', 'public');
  await expect(page.locator('body')).toHaveAttribute('data-existing-run-loaded', 'true');
  await expect.poll(() => page.evaluate(() => activeJobMeta?.public_run_id || '')).toBe(fixture.runId);
}

async function assertResponsiveResults(page, widths) {
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    const geometry = await page.evaluate(() => {
      const card = document.getElementById('results-card')?.getBoundingClientRect();
      return {
        viewportWidth: innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        card: card ? { left: card.left, right: card.right, width: card.width } : null,
      };
    });
    expect(geometry.card).not.toBeNull();
    expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth + 1);
    expect(geometry.card.left).toBeGreaterThanOrEqual(-1);
    expect(geometry.card.right).toBeLessThanOrEqual(geometry.viewportWidth + 1);
    expect(geometry.card.width).toBeGreaterThan(0);
  }
}

async function assertPrivateSurfaceClean(page, state, fixture) {
  await page.waitForTimeout(250);
  expect(state.apiRequests.length).toBeGreaterThan(0);
  for (const request of state.apiRequests) {
    if (request.path.startsWith('/api/results/')) expect(request.authorization).toBe(`Bearer ${fixture.token}`);
    expect(request.path).not.toContain('/api/jobs/');
    expect(request.path).not.toContain(fixture.internalId);
    expect(request.path).not.toContain(fixture.token);
  }
  const credentialState = await page.evaluate(() => ({
    accessCode: document.getElementById('run-setup-access-code')?.textContent || '',
    privateLink: document.getElementById('run-setup-result-link')?.getAttribute('href') || '',
  }));
  expect(credentialState.accessCode).toBe(fixture.token);
  expect(credentialState.privateLink).toContain(fixture.token);
  const serialized = await page.locator('html').evaluate(node => {
    const clone = node.cloneNode(true);
    clone.querySelector('#run-setup-credentials-card')?.remove();
    return clone.outerHTML;
  });
  const hrefs = await page.locator('[href]:not(#run-setup-result-link)').evaluateAll(
    nodes => nodes.map(node => node.getAttribute('href') || ''),
  );
  for (const value of [page.url(), serialized, ...hrefs]) {
    expect(value).not.toContain(fixture.internalId);
    expect(value).not.toContain(fixture.token);
    expect(value).not.toContain('data/results');
  }
  expect(state.consoleErrors).toEqual([]);
  expect(state.failedRequests).toEqual([]);
  expect(state.failedResponses).toEqual([]);
  expect(state.pageErrors).toEqual([]);
}

test('real server projects an opaque queued public run at desktop and mobile widths', async ({ page }) => {
  const fixture = fixtures.queued;
  const state = observeBrowser(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await openPublicRun(page, fixture);

  await expect(page.locator('body')).toHaveAttribute('data-workflow-state', 'launched');
  await expect(page.locator('body')).toHaveAttribute('data-job-state', 'running');
  await expect(page.locator('body')).toHaveAttribute('data-results-available', 'false');
  await expect(page.locator('#results-status')).toContainText('Queued #1');
  await expect(page.locator('#bgc-genome-progress-summary')).toHaveText('0 complete · 0 active · 1 queued');
  const queuedRow = page.locator('#bgc-genome-progress-grid .genome-progress-row');
  await expect(queuedRow).toHaveCount(1);
  await expect(queuedRow).toHaveAttribute('role', 'listitem');
  await expect(queuedRow.locator('[role="progressbar"]')).toHaveAttribute('aria-valuenow', '0');
  expect(await page.evaluate(() => activeJobMeta?.queue_status || null)).toMatchObject({
    state: 'queued',
    position: 1,
    queue_depth: 1,
    detail: 'Waiting for worker slot; this run is next.',
  });

  await assertResponsiveResults(page, [1280, 390]);
  await assertPrivateSurfaceClean(page, state, fixture);
});

test('real server renders sanitized running progress under reduced motion', async ({ page }) => {
  const fixture = fixtures.running;
  const state = observeBrowser(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 390, height: 844 });
  const activityResponse = page.waitForResponse(
    response => response.url() === `${baseURL}/api/results/${fixture.runId}/activity`,
  );
  await openPublicRun(page, fixture);
  const activity = await (await activityResponse).json();

  await expect(page.locator('body')).toHaveAttribute('data-workflow-state', 'running');
  await expect(page.locator('body')).toHaveAttribute('data-job-state', 'running');
  await expect(page.locator('body')).toHaveAttribute('data-results-available', 'false');
  await expect(page.locator('#results-status')).toContainText('Running');
  await expect(page.locator('#bgc-genome-progress-grid .genome-progress-row')).toHaveCount(2);
  const runningRow = page.locator('#bgc-genome-progress-grid .genome-progress-row').first();
  await expect(runningRow).toContainText('running fungus');
  await expect(runningRow).toContainText('Scanning protein domains');
  await expect(runningRow.locator('[role="progressbar"]')).toHaveAttribute('aria-valuenow', '20');
  expect(JSON.stringify(activity)).not.toContain('private_record');
  expect(JSON.stringify(activity)).not.toContain('/data/jobs');
  expect(await page.evaluate(() => reducedMotionPreferred())).toBe(true);
  const motion = await runningRow.evaluate(node => {
    const style = getComputedStyle(node);
    const segment = node.querySelector('.genome-progress-segment.has-live-region-work');
    const after = segment ? getComputedStyle(segment, '::after') : null;
    return {
      transitionDelay: style.transitionDelay,
      animationName: after?.animationName || '',
    };
  });
  expect(motion.transitionDelay).toBe('0s');
  expect(['', 'none']).toContain(motion.animationName);

  await assertResponsiveResults(page, [390, 1280]);
  await assertPrivateSurfaceClean(page, state, fixture);
});

test('real server opens an attested completed result reader with keyboard controls', async ({ page }) => {
  const fixture = fixtures.completed;
  const state = observeBrowser(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  const catalogResponse = page.waitForResponse(
    response => response.url() === `${baseURL}/api/results/${fixture.runId}/artifacts`,
  );
  await openPublicRun(page, fixture);
  const catalog = await (await catalogResponse).json();

  expect(catalog.result_index_state).toBe('attested');
  expect(catalog.artifacts).toHaveLength(2);
  const figureArtifact = catalog.artifacts.find(artifact => artifact.category === 'figures');
  expect(figureArtifact).toBeDefined();
  expect(figureArtifact.id).toMatch(/^[A-Za-z0-9_-]{22}$/);
  await expect(page.locator('body')).toHaveAttribute('data-workflow-state', 'complete');
  await expect(page.locator('body')).toHaveAttribute('data-job-state', 'complete');
  await expect(page.locator('body')).toHaveAttribute('data-results-available', 'true');
  await expect(page.locator('body')).toHaveAttribute('data-results-dashboard', 'open');
  await expect(page.locator('#results-status')).toContainText('Complete');
  const figure = page.locator('#viz-container .figure-preview-wrap');
  await expect(figure).toBeVisible();
  await expect(figure).toHaveAttribute('role', 'group');
  await expect(figure).toHaveAttribute('aria-keyshortcuts', '+ - 0 Escape');
  await expect(figure.locator('.figure-svg-stage svg title')).toHaveText('R01e lifecycle overview');
  await figure.focus();
  await expect(figure).toBeFocused();
  await page.keyboard.press('+');
  await expect(figure.locator('.figure-zoom-reset')).toHaveText('120%');
  await page.keyboard.press('-');
  await expect(figure.locator('.figure-zoom-reset')).toHaveText('100%');
  await page.keyboard.press('+');
  await expect(figure.locator('.figure-zoom-reset')).toHaveText('120%');
  await page.keyboard.press('Escape');
  await expect(figure.locator('.figure-zoom-reset')).toHaveText('100%');
  const openHref = await page.locator('#viz-container .figure-actions a', { hasText: 'Open' }).getAttribute('href');
  expect(new URL(openHref).pathname).toBe(`/api/results/${fixture.runId}/artifacts/${figureArtifact.id}`);
  expect(openHref).not.toContain(fixture.token);
  expect(openHref).not.toContain(fixture.internalId);

  await assertResponsiveResults(page, [1280, 390]);
  await assertPrivateSurfaceClean(page, state, fixture);
});
