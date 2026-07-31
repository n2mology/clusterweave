const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const baseURL = 'http://127.0.0.1:4176';
const adminToken = 'r01f-admin-browser-token';
const adminJobId = 'f01a11ce';
const evidenceDir = process.env.CLUSTERWEAVE_R12D_EVIDENCE_DIR || '';

function observeBrowser(page) {
  const state = {
    requests: [],
    failedRequests: [],
    failedResponses: [],
    consoleErrors: [],
    pageErrors: [],
  };
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.origin === baseURL && url.pathname.startsWith('/api/')) {
      state.requests.push({
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
  page.on('console', message => {
    if (message.type() === 'error') state.consoleErrors.push(message.text());
  });
  page.on('pageerror', error => state.pageErrors.push(error.message));
  return state;
}

async function assertResponsiveElement(page, selector, widths) {
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    const geometry = await page.locator(selector).evaluate(node => {
      const rect = node.getBoundingClientRect();
      return {
        viewportWidth: innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        left: rect.left,
        right: rect.right,
        width: rect.width,
      };
    });
    expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth + 1);
    expect(geometry.left).toBeGreaterThanOrEqual(-2);
    expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth + 2);
    expect(geometry.width).toBeGreaterThan(0);
  }
}

async function assertCredentialAbsent(page, token) {
  const surface = await page.evaluate(() => ({
    url: location.href,
    html: document.documentElement.outerHTML,
    values: [...document.querySelectorAll('input, textarea')].map(node => node.value),
  }));
  expect(surface.url).not.toContain(token);
  expect(surface.html).not.toContain(token);
  expect(surface.values.join('\n')).not.toContain(token);
}

async function captureDiagnosticsEvidence(page, stateName, selector) {
  if (!evidenceDir) return;
  const phase = process.env.CLUSTERWEAVE_R12D_PHASE || 'capture';
  fs.mkdirSync(evidenceDir, { recursive: true });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => {
      document.getAnimations().forEach(animation => {
        try { animation.finish(); } catch (error) {}
      });
    });
    await page.locator(selector).screenshot({
      path: path.join(evidenceDir, `${phase}-${stateName}-${width}.png`),
      animations: 'disabled',
    });
    const snapshot = await page.evaluate(() => {
      const elementState = id => {
        const node = document.getElementById(id);
        const style = getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return {
          hidden: node.hidden,
          ariaHidden: node.getAttribute('aria-hidden'),
          ariaExpanded: node.getAttribute('aria-expanded'),
          ariaSelected: node.getAttribute('aria-selected'),
          tabIndex: node.tabIndex,
          display: style.display,
          visibility: style.visibility,
          opacity: style.opacity,
          transform: style.transform,
          position: style.position,
          width: rect.width,
          height: rect.height,
          left: rect.left,
          top: rect.top,
          color: style.color,
          backgroundColor: style.backgroundColor,
          borderColor: style.borderColor,
          outlineStyle: style.outlineStyle,
          outlineWidth: style.outlineWidth,
        };
      };
      return {
        viewport: { width: innerWidth, height: innerHeight },
        body: {
          access: document.body.dataset.access,
          opsPanel: document.body.dataset.opsPanel,
          opsTab: document.body.dataset.opsTab,
        },
        activeElement: document.activeElement?.id || '',
        drawer: elementState('ops-side-panel'),
        toggle: elementState('ops-panel-toggle'),
        jobsTab: elementState('ops-tab-jobs'),
        qaTab: elementState('ops-tab-qa'),
        jobsPanel: elementState('jobs-card'),
        qaPanel: elementState('progress-card'),
      };
    });
    fs.writeFileSync(
      path.join(evidenceDir, `${phase}-${stateName}-${width}.json`),
      `${JSON.stringify(snapshot, null, 2)}\n`,
      'utf8',
    );
  }
}

test('real server keeps anonymous and rejected access outside diagnostics', async ({ page }) => {
  const state = observeBrowser(page);
  const rejectedToken = 'r01f-rejected-admin-token';
  await page.setViewportSize({ width: 1280, height: 900 });
  const documentResponse = await page.goto(baseURL);
  expect(documentResponse.status()).toBe(200);
  expect(await page.evaluate(() => '__clusterweaveInstallDiagnosticsAccessBoundary' in window)).toBe(false);

  await expect(page.locator('body')).toHaveAttribute('data-access', 'public');
  await expect(page.locator('body')).toHaveAttribute('data-ops-panel', 'collapsed');
  await expect(page.locator('#ops-panel-toggle')).toHaveCount(0);
  await expect(page.locator('#ops-side-panel')).toBeHidden();
  await expect(page.locator('#ops-side-panel')).toHaveAttribute('aria-hidden', 'true');
  await page.evaluate(() => openOpsPanel({ tab: 'jobs', focusPanel: true }));
  await expect(page.locator('body')).toHaveAttribute('data-ops-panel', 'collapsed');
  expect(state.requests.filter(request => request.path === '/api/jobs')).toHaveLength(0);

  const denial = await page.evaluate(async ({ origin, jobId }) => {
    const jobs = await fetch(`${origin}/api/jobs`, { cache: 'no-store' });
    const logs = await fetch(`${origin}/api/jobs/${jobId}/logs?tail=500`, { cache: 'no-store' });
    return { jobs: jobs.status, logs: logs.status };
  }, { origin: baseURL, jobId: adminJobId });
  expect(denial).toEqual({ jobs: 401, logs: 404 });

  await page.getByRole('tab', { name: 'Existing results' }).click();
  const accessInput = page.locator('#access-code-input');
  await accessInput.fill(rejectedToken);
  await page.locator('#apply-access-code').click();
  await expect(page.locator('#access-code-status')).toHaveText(
    'Access code was not accepted. Check the code and try again.',
  );
  await expect(page.locator('body')).toHaveAttribute('data-access', 'public');
  await expect(page.locator('#ops-panel-toggle')).toHaveCount(0);
  await accessInput.fill('');
  expect(await page.evaluate(() => ({
    admin: sessionStorage.getItem('clusterweave.adminToken'),
    submit: sessionStorage.getItem('clusterweave.submitToken'),
  }))).toEqual({ admin: null, submit: null });

  await assertResponsiveElement(page, '#access-panel', [1280, 390]);
  if (evidenceDir) {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    fs.mkdirSync(evidenceDir, { recursive: true });
    const phase = process.env.CLUSTERWEAVE_R12D_PHASE || 'capture';
    await page.locator('#access-panel').screenshot({ path: path.join(evidenceDir, `${phase}-rejected-mobile.png`) });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.locator('#access-panel').screenshot({ path: path.join(evidenceDir, `${phase}-rejected-desktop.png`) });
  }
  await assertCredentialAbsent(page, rejectedToken);
  await page.waitForTimeout(250);
  expect(state.failedResponses.sort()).toEqual([
    '403 /api/access/validate',
    '401 /api/jobs',
    `404 /api/jobs/${adminJobId}/logs`,
  ].sort());
  expect(state.failedRequests).toEqual([]);
  expect(state.consoleErrors.sort()).toEqual([
    'Failed to load resource: the server responded with a status of 403 (Forbidden)',
    'Failed to load resource: the server responded with a status of 401 (Unauthorized)',
    'Failed to load resource: the server responded with a status of 404 (Not Found)',
  ].sort());
  expect(state.pageErrors).toEqual([]);
});

test('diagnostics focus transitions resolve within the initiating keyboard action', async ({ page }) => {
  await page.goto(baseURL);
  await page.getByRole('tab', { name: 'Existing results' }).click();
  const accessInput = page.locator('#access-code-input');
  await accessInput.fill(adminToken);
  await page.locator('#apply-access-code').click();
  await expect(page.locator('body')).toHaveAttribute('data-access', 'admin');

  const focusState = await page.evaluate(() => {
    const accessCodeInput = document.getElementById('access-code-input');
    const jobsTab = document.getElementById('ops-tab-jobs');
    const qaTab = document.getElementById('ops-tab-qa');
    const qaPanel = document.getElementById('progress-card');
    let prevented = false;

    accessCodeInput.focus();
    openOpsPanel({ tab: 'jobs', returnFocus: accessCodeInput });
    const afterOpen = document.activeElement?.id;
    closeOpsPanel();
    const afterClose = document.activeElement?.id;

    openOpsPanel({ tab: 'jobs', returnFocus: accessCodeInput });
    jobsTab.focus();
    handleOpsTabKeydown({
      key: 'End',
      preventDefault() {
        prevented = true;
      },
    });

    return {
      afterOpen,
      afterClose,
      afterEnd: document.activeElement?.id,
      prevented,
      qaSelected: qaTab.getAttribute('aria-selected'),
      qaPanelHidden: qaPanel.hidden,
      panelState: document.body.dataset.opsPanel,
    };
  });

  expect(focusState).toEqual({
    afterOpen: 'ops-tab-jobs',
    afterClose: 'access-code-input',
    afterEnd: 'ops-tab-qa',
    prevented: true,
    qaSelected: 'true',
    qaPanelHidden: false,
    panelState: 'open',
  });
});

test('real server grants keyboard-accessible diagnostics without exposing the token', async ({ page }) => {
  const state = observeBrowser(page);
  await page.setViewportSize({ width: 390, height: 900 });
  if (evidenceDir) await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(baseURL);

  await page.getByRole('tab', { name: 'Existing results' }).click();
  const accessInput = page.locator('#access-code-input');
  await accessInput.fill(adminToken);
  await page.locator('#apply-access-code').click();
  await expect(page.locator('body')).toHaveAttribute('data-access', 'admin');
  await expect(page.locator('body')).toHaveAttribute('data-ops-panel', 'open');

  const drawer = page.locator('#ops-side-panel');
  const toggle = page.locator('#ops-panel-toggle');
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute('aria-label', 'Diagnostics drawer');
  await expect(drawer).toHaveAttribute('aria-hidden', 'false');
  await expect(toggle).toBeVisible();
  await expect(toggle).toHaveAttribute('aria-controls', 'ops-side-panel');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('#jobs-card')).toBeFocused();
  await captureDiagnosticsEvidence(page, 'jobs', '#ops-side-panel .admin-shell');
  await accessInput.fill('');
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveAttribute('aria-hidden', 'true');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(accessInput).toBeFocused();
  await captureDiagnosticsEvidence(page, 'closed', '#ops-panel-toggle');
  await toggle.press('Enter');
  await expect(drawer).toHaveAttribute('aria-hidden', 'false');

  const jobCard = page.locator(`.diagnostic-job-card[data-job-id="${adminJobId}"]`);
  await expect(jobCard).toBeVisible();
  if (evidenceDir) await jobCard.click();
  else await jobCard.press('Enter');
  await expect.poll(() => page.evaluate(() => activeJobMeta?.id || '')).toBe(adminJobId);
  await expect(jobCard).toHaveClass(/is-selected/);

  const jobsTab = page.locator('#ops-tab-jobs');
  await jobsTab.focus();
  await page.keyboard.press('End');
  const qaTab = page.locator('#ops-tab-qa');
  await expect(qaTab).toBeFocused();
  await expect(qaTab).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#progress-card')).toBeVisible();
  await expect(page.locator('#qa-job-id')).toHaveText(adminJobId);
  await expect(page.locator('#log-terminal')).toHaveAttribute('role', 'log');
  await expect(page.locator('#log-terminal')).toHaveAttribute('aria-label', 'Selected run progress tree');
  await expect(page.locator('#log-terminal')).toHaveAttribute('data-log-view', 'tree');
  await expect(page.locator('#log-terminal .progress-tree-row')).not.toHaveCount(0);
  await expect(page.locator('#log-terminal')).toContainText('Calling genes');

  await assertResponsiveElement(page, '#ops-side-panel', [390, 1280]);
  await captureDiagnosticsEvidence(page, 'qa', '#ops-side-panel .admin-shell');
  await page.setViewportSize({ width: 1280, height: 900 });
  await jobsTab.click();
  await expect(jobsTab).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#jobs-card')).toBeVisible();
  await qaTab.click();
  await expect(qaTab).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#progress-card')).toBeVisible();
  await qaTab.focus();
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveAttribute('aria-hidden', 'true');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toBeFocused();
  await toggle.press('Enter');
  await expect(drawer).toHaveAttribute('aria-hidden', 'false');
  await page.getByRole('button', { name: 'Close diagnostics', exact: true }).click();
  await expect(drawer).toHaveAttribute('aria-hidden', 'true');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await toggle.click();
  await expect(drawer).toHaveAttribute('aria-hidden', 'false');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');

  const protectedRequests = state.requests.filter(request =>
    request.path === '/api/access/validate'
      || request.path === '/api/jobs'
      || request.path.startsWith('/api/jobs/')
      || request.path.startsWith('/api/results/'));
  expect(protectedRequests.length).toBeGreaterThan(0);
  for (const request of protectedRequests) {
    expect(request.authorization).toBe(`Bearer ${adminToken}`);
  }
  expect(state.requests.some(request =>
    request.path === '/api/system/status'
      && request.authorization === `Bearer ${adminToken}`)).toBe(true);
  expect(await page.evaluate(() => sessionStorage.getItem('clusterweave.adminToken'))).toBe(adminToken);
  await assertCredentialAbsent(page, adminToken);
  await page.waitForTimeout(250);
  expect(state.failedResponses).toEqual([]);
  expect(state.failedRequests).toEqual([]);
  expect(state.consoleErrors).toEqual([]);
  expect(state.pageErrors).toEqual([]);
});
