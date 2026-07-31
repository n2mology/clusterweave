const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const baseUrl = 'http://127.0.0.1:4173';
const gameAssetNames = [
  'clusterweave-game.css',
  'clusterweave-game-content.js',
  'clusterweave-game-core.js',
  'clusterweave-game.js',
];

function systemStatus(ready = true) {
  return {
    online: true,
    ready,
    worker: { status: ready ? 'ready' : 'starting', running_count: 0, active_count: 0 },
    capabilities: { stages: {} },
    service: 'online',
    submissions_open: true,
    jobs_processed: 0,
    running_jobs: 0,
    queued_jobs: 0,
    public_quota: { max_accessions: 50, max_genome_files: 50 },
  };
}

async function preparePage(page, options = {}) {
  const assetRequests = [];
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (gameAssetNames.some(name => url.pathname.endsWith(`/assets/${name}`))) {
      assetRequests.push(url);
    }
  });
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('requestfailed', request => failedRequests.push(`${request.method()} ${request.url()}`));
  await page.route('**/api/jobs*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }));
  await page.route('**/api/system/status*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(systemStatus(options.ready !== false)),
  }));
  await page.goto(`${baseUrl}/?gameQa=1`);
  return { assetRequests, consoleErrors, pageErrors, failedRequests };
}

function expectOneRequestPerAsset(assetRequests) {
  expect(assetRequests).toHaveLength(gameAssetNames.length);
  for (const name of gameAssetNames) {
    const requests = assetRequests.filter(url => url.pathname.endsWith(`/assets/${name}`));
    expect(requests, name).toHaveLength(1);
    expect(requests[0].origin).toBe(baseUrl);
    expect(requests[0].search).toMatch(/^\?v=202607/);
  }
}

async function capture(page, name) {
  const evidenceDir = process.env.CLUSTERWEAVE_R13A_EVIDENCE_DIR;
  if (!evidenceDir) return;
  fs.mkdirSync(evidenceDir, { recursive: true });
  await page.screenshot({ path: path.join(evidenceDir, `${name}.png`), fullPage: true });
}

async function expectCleanRuntime(runtime) {
  await expect.poll(() => runtime.pageErrors).toEqual([]);
  expect(runtime.consoleErrors).toEqual([]);
  expect(runtime.failedRequests).toEqual([]);
}

test('desktop requests no game assets before eligibility and preserves pointer and keyboard play', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const runtime = await preparePage(page);
  await expect(page.locator('body')).toHaveAttribute('data-clusterweave-game-bootstrap-eligible', 'false');
  expect(runtime.assetRequests).toEqual([]);
  expect(await page.evaluate(() => typeof window.ClusterWeaveGame)).toBe('undefined');

  await page.evaluate(() => syncClusterweaveGameHost({ lifecycle: 'running', job: null }));
  await expect.poll(() => runtime.assetRequests.length).toBe(gameAssetNames.length);
  await expect.poll(() => page.evaluate(() => typeof window.ClusterWeaveGame)).toBe('object');
  expectOneRequestPerAsset(runtime.assetRequests);
  const launcher = page.locator('#clusterweave-game-launcher');
  const start = page.locator('#clusterweave-game-start');
  const shell = page.locator('#clusterweave-game');
  await expect(launcher).toBeVisible();
  const waitPrompt = launcher.locator('.clusterweave-game-wait-prompt');
  await expect(waitPrompt).toBeVisible();
  await expect(waitPrompt.locator('span')).toHaveText(['PLAY WHILE', 'YOU WAIT']);
  const waitPromptGeometry = await launcher.evaluate(node => {
    const prompt = node.querySelector('.clusterweave-game-wait-prompt');
    const button = node.querySelector('#clusterweave-game-start');
    const promptBox = prompt.getBoundingClientRect();
    const buttonBox = button.getBoundingClientRect();
    const style = getComputedStyle(prompt);
    const runtimeStyle = getComputedStyle(document.getElementById('results-job-runtime'));
    const headingBox = document.querySelector('.clusterweave-results-heading').getBoundingClientRect();
    const lineBoxes = Array.from(prompt.children).map(line => line.getBoundingClientRect());
    return {
      leftOfPlay: promptBox.right <= buttonBox.left,
      centeredStack: style.display === 'grid' && style.justifyItems === 'center' && style.textAlign === 'center',
      hardBreak: lineBoxes.length === 2 && lineBoxes[0].bottom <= lineBoxes[1].top,
      runtimeSize: style.fontSize === runtimeStyle.fontSize,
      launcherContained: buttonBox.right <= headingBox.right,
    };
  });
  expect(waitPromptGeometry).toEqual({
    leftOfPlay: true,
    centeredStack: true,
    hardBreak: true,
    runtimeSize: true,
    launcherContained: true,
  });
  await start.click();
  await expect(shell).toBeVisible();
  await expect(shell).toHaveAttribute('role', 'region');
  await expect(page.locator('#clusterweave-game-canvas')).toBeFocused();
  const firstStyle = await shell.evaluate(node => {
    const style = getComputedStyle(node);
    const canvas = node.querySelector('canvas');
    const canvasStyle = getComputedStyle(canvas);
    return {
      display: style.display,
      gridArea: style.gridArea,
      canvasTouchAction: canvasStyle.touchAction,
      canvasWidth: canvas.getBoundingClientRect().width,
      canvasHeight: canvas.getBoundingClientRect().height,
    };
  });
  expect(firstStyle.display).toBe('block');
  expect(firstStyle.gridArea).toBe('game');
  expect(firstStyle.canvasTouchAction).toBe('none');
  expect(firstStyle.canvasWidth).toBeGreaterThan(0);
  expect(firstStyle.canvasHeight).toBeGreaterThan(0);
  await capture(page, 'desktop-pointer');

  await page.keyboard.press('Escape');
  await expect(shell).toBeHidden();
  await start.focus();
  await page.keyboard.press('Enter');
  await expect(shell).toBeVisible();
  await expect(page.locator('#clusterweave-game-overlay-title')).toHaveText('Run held');
  expect(await page.evaluate(() => document.getElementById('clusterweave-game').contains(document.activeElement))).toBeTruthy();
  expectOneRequestPerAsset(runtime.assetRequests);
  await capture(page, 'desktop-keyboard');
  await expectCleanRuntime(runtime);
});

test('eligible bootstrap play preserves fullscreen focus and accessibility', async ({ page }) => {
  test.setTimeout(40_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  const runtime = await preparePage(page, { ready: false });
  await expect.poll(() => runtime.assetRequests.length).toBe(gameAssetNames.length);
  expectOneRequestPerAsset(runtime.assetRequests);

  const bootstrap = page.locator('#clusterweave-game-bootstrap');
  await expect(bootstrap).toBeVisible({ timeout: 8_000 });
  const play = page.locator('#clusterweave-game-bootstrap-open');
  await play.focus();
  await page.keyboard.press('Enter');
  const shell = page.locator('#clusterweave-game');
  await expect(shell).toBeVisible();
  await expect(shell).toHaveAttribute('role', 'dialog');
  await expect(shell).toHaveAttribute('aria-modal', 'true');
  await expect(page.locator('body')).toHaveAttribute('data-clusterweave-game-bootstrap', 'true');
  await expect(page.locator('#clusterweave-game-canvas')).toBeFocused();
  await capture(page, 'bootstrap-desktop');
  expectOneRequestPerAsset(runtime.assetRequests);
  await expectCleanRuntime(runtime);
});

test('mobile reduced-motion touch play hands focus back on workflow completion without WebGL', async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function patchedGetContext(kind, ...args) {
      if (kind === 'webgl' || kind === 'webgl2' || kind === 'experimental-webgl') return null;
      return original.call(this, kind, ...args);
    };
  });
  const runtime = await preparePage(page);
  await expect(page.locator('body')).toHaveAttribute('data-clusterweave-game-bootstrap-eligible', 'false');
  expect(runtime.assetRequests).toEqual([]);
  await page.evaluate(() => syncClusterweaveGameHost({ lifecycle: 'running', job: null }));
  await expect.poll(() => runtime.assetRequests.length).toBe(gameAssetNames.length);
  await expect.poll(() => page.evaluate(() => typeof window.ClusterWeaveGame)).toBe('object');
  expectOneRequestPerAsset(runtime.assetRequests);
  const start = page.locator('#clusterweave-game-start');
  const waitPrompt = page.locator('.clusterweave-game-wait-prompt');
  await expect(waitPrompt).toBeVisible();
  await expect(waitPrompt.locator('span')).toHaveText(['PLAY WHILE', 'YOU WAIT']);
  const mobilePromptGeometry = await waitPrompt.evaluate(prompt => {
    const promptBox = prompt.getBoundingClientRect();
    const buttonBox = document.getElementById('clusterweave-game-start').getBoundingClientRect();
    const lineBoxes = Array.from(prompt.children).map(line => line.getBoundingClientRect());
    return {
      leftOfPlay: promptBox.right <= buttonBox.left,
      viewportContained: promptBox.left >= 0 && buttonBox.right <= innerWidth,
      hardBreak: lineBoxes.length === 2 && lineBoxes[0].bottom <= lineBoxes[1].top,
      runtimeSize: getComputedStyle(prompt).fontSize === getComputedStyle(document.getElementById('results-job-runtime')).fontSize,
      transitionDuration: parseFloat(getComputedStyle(prompt).transitionDuration || '0'),
    };
  });
  expect(mobilePromptGeometry.leftOfPlay).toBeTruthy();
  expect(mobilePromptGeometry.viewportContained).toBeTruthy();
  expect(mobilePromptGeometry.hardBreak).toBeTruthy();
  expect(mobilePromptGeometry.runtimeSize).toBeTruthy();
  expect(mobilePromptGeometry.transitionDuration).toBeLessThanOrEqual(0.001);
  await start.tap();
  const shell = page.locator('#clusterweave-game');
  await expect(shell).toBeVisible();
  await expect(shell).toHaveAttribute('role', 'dialog');
  await expect(shell).toHaveAttribute('data-motion', 'reduced');
  await expect(page.locator('#disable-rich-motion')).toHaveCount(0);
  await expect(page.locator('#enable-three-weavemap')).toHaveCount(0);
  await expect(page.locator('body')).toHaveAttribute('data-three-weavemap', 'disabled');
  const motionStyle = await shell.evaluate(node => {
    const style = getComputedStyle(node);
    const canvasStyle = getComputedStyle(node.querySelector('canvas'));
    return {
      position: style.position,
      width: style.width,
      height: style.height,
      animationDuration: style.animationDuration,
      canvasTouchAction: canvasStyle.touchAction,
    };
  });
  expect(motionStyle.position).toBe('fixed');
  expect(motionStyle.canvasTouchAction).toBe('none');
  await capture(page, 'mobile-reduced-touch');

  await page.evaluate(() => window.ClusterWeaveGame.setHostState({
    epoch: 2,
    lifecycle: 'success',
    phase: 'contextualize',
  }));
  await expect(shell).toBeHidden();
  await expect(page.locator('#clusterweave-game-handoff')).toContainText('Results ready');
  await expect(page.locator('#results-card')).toBeFocused();
  expectOneRequestPerAsset(runtime.assetRequests);
  expect(runtime.consoleErrors).toEqual([
    'THREE.WebGLRenderer: Error creating WebGL context.',
    'THREE.WebGLRenderer: Error creating WebGL context.',
  ]);
  runtime.consoleErrors.length = 0;
  await expectCleanRuntime(runtime);
  await context.close();
});
