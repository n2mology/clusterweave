const { test, expect } = require('@playwright/test');

const baseUrl = 'http://127.0.0.1:4173';
const runId = 'treeLayoutFixtureRun001';
const token = 'tree-layout-fixture-read-token';
const figureId = 'TTTTTTTTTTTTTTTTTTTTTT';
const treeLeaves = Array.from(
  { length: 75 },
  (_, index) => `<metadata class="synthetic-leaf" data-genome-index="${index + 1}" data-genome-label="genome_${String(index + 1).padStart(2, '0')}"></metadata>`,
).join('');
const treeSvg = `
  <svg xmlns="http://www.w3.org/2000/svg" width="2200" height="2200" viewBox="0 0 2200 2200" role="img">
    <title>Taxon tree fixture</title>
    <desc>Wide synthetic 75-genome taxonomy tree used to verify complete preview geometry.</desc>
    <rect width="2200" height="2200" fill="#ffffff"/>
    <path d="M40 40H2160V2160H40Z" fill="none" stroke="#050505" stroke-width="8"/>
    <circle cx="1100" cy="2160" r="22" fill="#00bfa5"/>
    ${treeLeaves}
  </svg>`;

const descriptor = {
  id: figureId,
  filename: 'clusterweave_taxon_tree.svg',
  label: 'clusterweave_taxon_tree.svg',
  bytes: Buffer.byteLength(treeSvg),
  mime: 'image/svg+xml; charset=utf-8',
  category: 'figures',
  kind: 'svg',
  role: 'figure',
  previewable: true,
  downloadable: true,
};

async function routeSystemStatus(page) {
  await page.route('**/api/system/status*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      online: true,
      ready: true,
      service: 'online',
      submissions_open: true,
      worker: { status: 'ready', running_count: 0, active_count: 0 },
      capabilities: { stages: {} },
      jobs_processed: 0,
      running_jobs: 0,
      queued_jobs: 0,
    }),
  }));
}

function observeBrowser(page) {
  const state = {
    consoleErrors: [],
    pageErrors: [],
    failedRequests: [],
    failedResponses: [],
    artifactRequests: 0,
    artifactAuthorized: true,
    requestUrls: [],
  };
  page.on('console', message => {
    if (message.type() === 'error') state.consoleErrors.push(message.text());
  });
  page.on('pageerror', error => state.pageErrors.push(String(error)));
  page.on('request', request => state.requestUrls.push(request.url()));
  page.on('requestfailed', request => state.failedRequests.push(request.url()));
  page.on('response', response => {
    if (response.status() >= 400) state.failedResponses.push(response.status());
  });
  return state;
}

async function openTreeFixture(page, state) {
  await routeSystemStatus(page);
  await page.route('**/api/jobs*', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route(`**/api/results/${runId}/artifacts/${figureId}`, route => {
    const request = route.request();
    state.artifactRequests += 1;
    state.artifactAuthorized = state.artifactAuthorized
      && request.headers().authorization === `Bearer ${token}`;
    return route.fulfill({
      status: 200,
      contentType: 'image/svg+xml; charset=utf-8',
      body: treeSvg,
    });
  });
  const initializationRequest = page.waitForResponse(response => new URL(response.url()).pathname === '/api/jobs');
  await page.goto(baseUrl);
  await initializationRequest;
  await page.evaluate(({ publicRunId, readToken, artifact }) => {
    accessMode = 'public';
    activeJobId = publicRunId;
    activePublicRunId = publicRunId;
    activeJobMeta = {
      id: publicRunId,
      job_id: publicRunId,
      public_run_id: publicRunId,
      status: 'success',
      analysis_scope: 'mixed',
      input_summary: { taxon_counts: { fungi: 38, bacteria: 37, total: 75 } },
    };
    document.body.dataset.jobState = 'complete';
    publicResultRunIds.add(publicRunId);
    rememberOpenedRun(publicRunId, readToken, activeJobMeta);
    const files = installResultArtifactDescriptors([artifact]);
    activeResultFiles = files;
    showResultDashboard();
  }, { publicRunId: runId, readToken: token, artifact: descriptor });
  const preview = page.locator('.figure-preview-wrap.is-taxon-tree .figure-svg-preview');
  await preview.waitFor({ state: 'attached' });
  await page.evaluate(() => {
    document.getElementById('result-dashboard-section')?.classList.remove('hidden');
    document.getElementById('result-focus-panel')?.classList.remove('hidden');
    const viz = document.getElementById('viz-container');
    if (viz) viz.hidden = false;
  });
  await preview.waitFor({ state: 'visible' });
}

async function treeGeometry(wrap) {
  return wrap.evaluate(element => {
    const svg = element.querySelector('.figure-svg-preview');
    const stage = element.querySelector('.figure-svg-stage');
    const wrapRect = element.getBoundingClientRect();
    const svgRect = svg.getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    const viewBox = svg.viewBox.baseVal;
    return {
      wrapHeight: wrapRect.height,
      svgHeight: svgRect.height,
      svgWidth: svgRect.width,
      stageHeight: stageRect.height,
      whiteSpaceBelow: wrapRect.bottom - svgRect.bottom,
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      scrollLeft: element.scrollLeft,
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      scrollTop: element.scrollTop,
      minHeight: getComputedStyle(element).minHeight,
      viewBox: [viewBox.x, viewBox.y, viewBox.width, viewBox.height],
    };
  });
}

for (const viewport of [
  { width: 1280, height: 900, label: 'desktop' },
  { width: 390, height: 900, label: 'mobile' },
]) {
  test(`TREE preview fits its SVG and keeps the full image reachable when zoomed on ${viewport.label}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const state = observeBrowser(page);
    await openTreeFixture(page, state);

    const treeTab = page.getByRole('tab', { name: 'TREE', exact: true });
    await expect(treeTab).toHaveAttribute('aria-selected', 'true');
    const wrap = page.locator('.figure-preview-wrap.is-taxon-tree');
    await expect(wrap.locator('.synthetic-leaf')).toHaveCount(75);
    const base = await treeGeometry(wrap);
    expect(base.minHeight).toBe('0px');
    expect(Math.abs(base.stageHeight - base.svgHeight)).toBeLessThanOrEqual(1);
    expect(base.whiteSpaceBelow).toBeLessThanOrEqual(4);
    expect(base.wrapHeight - base.svgHeight).toBeLessThanOrEqual(8);

    await wrap.focus();
    await expect(wrap).toBeFocused();
    await page.keyboard.press('+');
    await expect(wrap.locator('.figure-zoom-reset')).toHaveText('120%');
    const zoomed = await treeGeometry(wrap);
    expect(zoomed.svgWidth).toBeGreaterThan(base.svgWidth * 1.15);
    expect(zoomed.svgHeight).toBeGreaterThan(base.svgHeight * 1.15);
    expect(zoomed.viewBox).toEqual(base.viewBox);

    for (let index = 0; index < 12; index += 1) await page.keyboard.press('+');
    await expect(wrap.locator('.figure-zoom-reset')).toHaveText('800%');
    const maximumZoom = await treeGeometry(wrap);
    expect(maximumZoom.scrollWidth).toBeGreaterThan(maximumZoom.clientWidth);
    expect(maximumZoom.scrollHeight).toBeGreaterThan(maximumZoom.clientHeight);
    await wrap.evaluate(element => { element.scrollTop = element.scrollHeight; });
    const zoomedBottom = await treeGeometry(wrap);
    expect(zoomedBottom.scrollHeight - zoomedBottom.clientHeight - zoomedBottom.scrollTop)
      .toBeLessThanOrEqual(1);
    await wrap.scrollIntoViewIfNeeded();
    const bounds = await wrap.boundingBox();
    await wrap.hover({ position: { x: maximumZoom.clientWidth * 0.72, y: maximumZoom.clientHeight / 2 } });
    await page.mouse.down();
    await expect(wrap).toHaveClass(/is-panning/);
    await page.mouse.move(bounds.x + bounds.width * 0.18, bounds.y + bounds.height / 2, { steps: 5 });
    await page.mouse.up();
    const panned = await treeGeometry(wrap);
    expect(panned.scrollLeft).toBeGreaterThan(maximumZoom.scrollLeft);
    await wrap.focus();
    await page.keyboard.press('Escape');
    await expect(wrap.locator('.figure-zoom-reset')).toHaveText('100%');
    const reset = await treeGeometry(wrap);
    expect(Math.abs(reset.svgWidth - base.svgWidth)).toBeLessThanOrEqual(1);
    expect(reset.scrollTop).toBe(0);
    expect(reset.scrollLeft).toBe(0);
    expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
    expect(state.artifactRequests).toBe(1);
    expect(state.artifactAuthorized).toBe(true);
    expect(state.requestUrls.every(url => !url.includes(token))).toBe(true);
    expect(page.url()).not.toContain(token);
    expect(state.consoleErrors).toEqual([]);
    expect(state.pageErrors).toEqual([]);
    expect(state.failedRequests).toEqual([]);
    expect(state.failedResponses).toEqual([]);
  });
}
