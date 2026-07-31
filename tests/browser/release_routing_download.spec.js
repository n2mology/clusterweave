const { test, expect } = require('@playwright/test');

const baseUrl = 'http://127.0.0.1:4173';

async function routeSystemStatus(page) {
  await page.route('**/api/system/status*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      online: true,
      ready: true,
      service: 'online',
      submissions_open: true,
      submissions: 'open',
      smtp_enabled: false,
      worker: { status: 'ready', running_count: 0, active_count: 0 },
      capabilities: { stages: {} },
      jobs_processed: 0,
      running_jobs: 0,
      queued_jobs: 0,
      public_quota: { max_accessions: 50, max_genome_files: 50 },
    }),
  }));
}

test('input CTA validates first and submits only after the chartreuse state', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseUrl });
  await routeSystemStatus(page);
  let postCount = 0;
  await page.route('**/api/jobs', route => {
    if (route.request().method() !== 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    }
    postCount += 1;
    return route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'validatedRunFixture',
        public_run_id: 'validatedRunFixture',
        read_token: 'fixture-read-token',
        result_url: '/results/validatedRunFixture',
        input_summary: { taxon_counts: { fungi: 1, bacteria: 0, total: 1 } },
      }),
    });
  });
  await page.route('**/api/results/validatedRunFixture**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/artifacts')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ run_id: 'validatedRunFixture', artifacts: [] }),
      });
    }
    if (path.endsWith('/activity')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ public_events: [], genome_progress: [] }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'validatedRunFixture',
        public_run_id: 'validatedRunFixture',
        project_name: 'validation_fixture',
        status: 'pending',
        stage: 'queued',
        created_at: '2026-07-23T12:00:00',
        updated_at: '2026-07-23T12:00:00',
        result_file_count: 0,
        analysis_scope: 'fungi',
      }),
    });
  });

  await page.goto(baseUrl);
  await page.locator('#project-name').fill('validation_fixture');
  await page.locator('#file-input').setInputFiles({
    name: 'fixture.fna',
    mimeType: 'text/plain',
    buffer: Buffer.from(`>fixture_contig\n${'ACGT'.repeat(600)}\n`),
  });

  const button = page.locator('#run-btn');
  await expect(button).toBeEnabled();
  await expect(button).toHaveText('Validate');
  await expect(button).toHaveClass(/is-validation-pending/);
  await expect(button).toHaveCSS('background-color', 'rgb(255, 122, 24)');

  await button.click();
  await expect(button).toHaveText('Submit run');
  await expect(button).toHaveClass(/is-submit-ready/);
  await expect(button).toHaveCSS('background-color', 'rgb(215, 255, 31)');
  await expect(page.locator('#upload-status')).toContainText('Validation passed');
  expect(postCount).toBe(0);

  await button.click();
  await expect.poll(() => postCount).toBe(1);
  const credentialCard = page.locator('#run-setup-credentials-card');
  const privateLink = page.locator('#run-setup-result-link');
  const accessCode = page.locator('#run-setup-access-code');
  const runId = page.locator('#run-setup-public-id');
  const copyCredentials = page.locator('#copy-run-setup-credentials');
  const expectedPrivateLink = `${baseUrl}/#/results/validatedRunFixture/fixture-read-token`;
  await expect(credentialCard).toBeVisible();
  await expect(credentialCard.locator('.run-setup-credential-row')).toHaveCount(3);
  await expect(privateLink).toHaveText(expectedPrivateLink);
  await expect(privateLink).toHaveAttribute('href', expectedPrivateLink);
  await expect(accessCode).toHaveText('fixture-read-token');
  await expect(runId).toHaveText('validatedRunFixture');
  await expect(credentialCard.locator('.run-setup-credential-note')).toHaveText('SAVE/COPY YOUR JOB CREDENTIALS. ANYONE WITH THESE CAN READ THE RESULTS.');
  await expect(copyCredentials).toHaveText('COPY');
  await expect(copyCredentials).not.toHaveAttribute('aria-label');
  await expect(copyCredentials).toHaveCSS('background-color', 'rgb(255, 122, 24)');
  const desktopGeometry = await credentialCard.evaluate(card => {
    const copyButton = card.querySelector('.run-setup-copy-button');
    const buttonBox = copyButton.getBoundingClientRect();
    const titleNode = card.querySelector('.run-setup-credential-head > small');
    const title = titleNode.getBoundingClientRect();
    const rows = Array.from(card.querySelectorAll('.run-setup-credential-row'));
    const note = card.querySelector('.run-setup-credential-note');
    const credentialList = card.querySelector('.run-setup-credential-list');
    const standardCard = card.parentElement.querySelector('.access-card');
    const standardLabel = standardCard.querySelector('small');
    const standardValue = standardCard.querySelector('b');
    const textStyle = node => {
      const css = getComputedStyle(node);
      return [css.fontFamily, css.fontSize, css.fontWeight, css.lineHeight, css.textTransform];
    };
    const withoutWeight = style => style.filter((_, index) => index !== 2);
    return {
      inlineTitle: Math.abs(title.top - buttonBox.top) <= 4 && title.right <= buttonBox.left,
      titleMatches: JSON.stringify(textStyle(titleNode)) === JSON.stringify(textStyle(standardLabel)),
      labelsMatch: Array.from(card.querySelectorAll('dt')).every(node => JSON.stringify(withoutWeight(textStyle(node))) === JSON.stringify(withoutWeight(textStyle(standardLabel)))),
      labelsBold: Array.from(card.querySelectorAll('dt')).every(node => Number.parseInt(getComputedStyle(node).fontWeight, 10) >= 1000),
      valuesMatch: Array.from(card.querySelectorAll('dd :is(a, code)')).every(node => JSON.stringify(textStyle(node)) === JSON.stringify(textStyle(standardValue))),
      copyMatches: JSON.stringify(textStyle(copyButton)) === JSON.stringify(textStyle(standardLabel)),
      arrowRemoved: !card.querySelector('.run-setup-copy-arrow'),
      oneCardRows: rows.every(row => getComputedStyle(row).borderTopWidth === '0px' && getComputedStyle(row).backgroundColor === 'rgba(0, 0, 0, 0)'),
      noteSingleLine: note.scrollWidth <= note.clientWidth && getComputedStyle(note).whiteSpace === 'nowrap',
      credentialBox: getComputedStyle(credentialList).borderTopWidth === '3px' && getComputedStyle(credentialList).backgroundColor === 'rgb(255, 210, 173)',
      noteChartreuse: getComputedStyle(note).backgroundColor === 'rgb(215, 255, 31)',
      noteFontSize: parseFloat(getComputedStyle(note).fontSize),
    };
  });
  expect(desktopGeometry).toEqual({
    inlineTitle: true,
    titleMatches: true,
    labelsMatch: true,
    labelsBold: true,
    valuesMatch: true,
    copyMatches: true,
    arrowRemoved: true,
    oneCardRows: true,
    noteSingleLine: true,
    credentialBox: true,
    noteChartreuse: true,
    noteFontSize: 7.68,
  });
  await page.evaluate(() => {
    window.__nativeClipboard = navigator.clipboard;
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
    document.addEventListener('copy', () => {
      window.__legacyCopiedCredentialShape = String(document.activeElement?.value || '').split('\n').length;
    }, { once: true });
  });
  await copyCredentials.click();
  await expect(copyCredentials).toHaveText('COPIED');
  await expect(copyCredentials).toHaveCSS('background-color', 'rgb(255, 59, 167)');
  await expect.poll(() => page.evaluate(() => window.__legacyCopiedCredentialShape)).toBe(3);
  const legacyCopiedCredentials = await page.evaluate(async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: window.__nativeClipboard });
    return navigator.clipboard.readText();
  });
  expect(legacyCopiedCredentials).toBe(
    `PRIVATE LINK: ${expectedPrivateLink}\nACCESS CODE: fixture-read-token\nRUN ID: validatedRunFixture`,
  );
  await page.evaluate(() => {
    accessMode = 'admin';
    renderActiveRunAccessPanel({
      id: 'validatedRunFixture',
      public_run_id: 'validatedRunFixture',
      project_name: 'validation_fixture',
      status: 'pending',
    });
  });
  await expect(copyCredentials).toHaveText('COPIED');
  await page.evaluate(() => { accessMode = 'public'; });
  const receiptBeforeLink = await page.locator('#run-setup-input-list').innerHTML();
  await privateLink.click();
  await expect(page).toHaveURL(`${baseUrl}/#/results/validatedRunFixture`);
  expect(await page.locator('#run-setup-input-list').innerHTML()).toBe(receiptBeforeLink);
  await page.evaluate(() => {
    renderRunSetupAccessPanel({
      id: 'internalAcceptedFixture',
      public_run_id: 'validatedRunFixture',
      project_name: 'validation_fixture',
      status: 'pending',
      receipt: {
        projectName: 'validation_fixture',
        inputNotes: ['Stored run input'],
        inputSummary: {
          accession_count: 0,
          upload_count: 1,
          taxon_counts: { fungi: 1, bacteria: 0, total: 1 },
        },
      },
      input_summary: {
        accession_count: 0,
        upload_count: 1,
        taxon_counts: { fungi: 1, bacteria: 0, total: 1 },
      },
    }, 'fixture-read-token');
  });
  expect(await page.locator('#run-setup-input-list').innerHTML()).toBe(receiptBeforeLink);
});

test('Validate batches accession taxonomy errors and revalidation leaves one-click Submit', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseUrl });
  await routeSystemStatus(page);
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  const httpErrors = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('requestfailed', request => failedRequests.push(request.url()));
  page.on('response', response => {
    if (response.status() >= 400) httpErrors.push(`${response.status()} ${response.url()}`);
  });

  const submittedAccessions = [
    'GCA_014904845.1',
    'GCA_029590635.1',
    'GCA_020726555.1',
    'GCA_000009045.1',
    'GCA_002355435.1',
    'GCA_030572435.1',
    'GCA_011100685.1',
    'GCA_000002775.4',
  ];
  let validationCount = 0;
  let jobPostCount = 0;
  const validationRequests = [];
  await page.route('**/api/inputs/validate', async route => {
    validationCount += 1;
    const request = route.request();
    const payload = request.postDataJSON();
    validationRequests.push({
      pathname: new URL(request.url()).pathname,
      search: new URL(request.url()).search,
      authorization: request.headers().authorization || '',
      accessions: payload.accessions,
    });
    const results = payload.accessions.map(accession => {
      const unsupported = validationCount === 1 && accession === 'GCA_000002775.4';
      return unsupported
        ? {
            accession,
            accepted: false,
            organism_name: 'Populus trichocarpa',
            taxon_group: 'unsupported',
            detail: "NCBI accession 'GCA_000002775.4' is Populus trichocarpa with unsupported taxonomy; ClusterWeave accepts fungal and bacterial assemblies only.",
          }
        : {
            accession,
            accepted: true,
            organism_name: `Fixture organism ${accession}`,
            taxon_group: 'fungi',
          };
    });
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ valid: results.every(result => result.accepted), results }),
    });
  });
  await page.route('**/api/jobs', route => {
    if (route.request().method() !== 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    }
    jobPostCount += 1;
    return route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'batchValidationFixture',
        public_run_id: 'batchValidationFixture',
        read_token: 'fixture-read-token',
        result_url: '/results/batchValidationFixture',
        input_summary: { taxon_counts: { fungi: 8, bacteria: 0, total: 8 } },
      }),
    });
  });
  await page.route('**/api/results/batchValidationFixture**', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith('/artifacts')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ run_id: 'batchValidationFixture', artifacts: [] }),
      });
    }
    if (pathname.endsWith('/activity')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ public_events: [], genome_progress: [] }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'batchValidationFixture',
        public_run_id: 'batchValidationFixture',
        project_name: 'batch_validation',
        status: 'pending',
        stage: 'queued',
        created_at: '2026-07-29T12:00:00',
        updated_at: '2026-07-29T12:00:00',
        result_file_count: 0,
        analysis_scope: 'fungi',
      }),
    });
  });

  await page.goto(baseUrl);
  await page.locator('#project-name').fill('batch_validation');
  const accessionInputs = page.locator('.brutal-accession-input');
  for (let index = 0; index < submittedAccessions.length; index += 1) {
    await accessionInputs.nth(index).fill(submittedAccessions[index]);
  }

  const button = page.locator('#run-btn');
  await expect(button).toHaveText('Validate');
  await expect(page.locator('#upload-status')).not.toContainText('ready for workflow');
  await button.focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => validationCount).toBe(1);

  const unsupportedRow = page.locator('.brutal-accession-line').filter({ hasText: 'GCA_000002775.4' });
  await expect(unsupportedRow).toHaveClass(/has-accession-verification-error/);
  await expect(unsupportedRow.locator('.accession-target')).toHaveCSS('background-color', 'rgb(255, 122, 24)');
  await expect(unsupportedRow.locator('.status-icon')).toHaveClass(/bad/);
  await expect(unsupportedRow.locator('.status-icon')).toHaveCSS('background-color', 'rgb(255, 59, 48)');
  await expect(unsupportedRow.locator('.accession-target')).toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('.brutal-accession-line .status-icon.ok')).toHaveCount(7);
  await expect(page.locator('#input-log-drawer')).toBeVisible();
  await expect(page.locator('#input-log-list')).toContainText('Populus trichocarpa');
  await expect(page.locator('#upload-status')).toContainText('1 blocked input source');
  await expect(page.locator('#upload-status')).not.toContainText('ready for workflow');
  await expect(button).toBeDisabled();
  expect(validationRequests[0].accessions).toEqual(submittedAccessions);
  expect(validationRequests[0]).toMatchObject({ pathname: '/api/inputs/validate', search: '', authorization: '' });
  expect(jobPostCount).toBe(0);

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileGeometry = await unsupportedRow.locator('.accession-target').evaluate(node => {
    const box = node.getBoundingClientRect();
    return { left: box.left, right: box.right, viewportWidth: innerWidth };
  });
  expect(mobileGeometry.left).toBeGreaterThanOrEqual(0);
  expect(mobileGeometry.right).toBeLessThanOrEqual(mobileGeometry.viewportWidth);
  const mobileLogGeometry = await page.locator('#input-log-drawer').evaluate(node => {
    const box = node.getBoundingClientRect();
    return { left: box.left, right: box.right, viewportWidth: innerWidth };
  });
  expect(mobileLogGeometry.left).toBeGreaterThanOrEqual(0);
  expect(mobileLogGeometry.right).toBeLessThanOrEqual(mobileLogGeometry.viewportWidth);
  const reducedMotionDuration = await unsupportedRow.locator('.accession-target').evaluate(node => (
    parseFloat(getComputedStyle(node).transitionDuration)
  ));
  expect(reducedMotionDuration).toBeLessThanOrEqual(0.001);

  await unsupportedRow.locator('.accession-target').fill('GCA_030770425.1');
  await expect(button).toBeEnabled();
  await button.focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => validationCount).toBe(2);
  await expect(button).toHaveText('Submit run');
  await expect(button).toBeEnabled();
  await expect(page.locator('.brutal-accession-line.has-accession-verification-error')).toHaveCount(0);
  await expect(page.locator('.brutal-accession-line .status-icon.ok')).toHaveCount(8);
  await expect(page.locator('#input-log-drawer')).toBeHidden();
  await expect(page.locator('#upload-status')).toContainText('Validation passed');
  expect(jobPostCount).toBe(0);

  await button.focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => jobPostCount).toBe(1);
  await expect.poll(() => page.evaluate(() => activeJobId)).toBe('batchValidationFixture');
  const credentialCard = page.locator('#run-setup-credentials-card');
  const expectedPrivateLink = `${baseUrl}/#/results/batchValidationFixture/fixture-read-token`;
  await expect(credentialCard).toBeVisible();
  await expect(page.locator('#run-setup-result-link')).toHaveText(expectedPrivateLink);
  await expect(page.locator('#run-setup-access-code')).toHaveText('fixture-read-token');
  await expect(page.locator('#run-setup-public-id')).toHaveText('batchValidationFixture');
  const copyCredentials = page.locator('#copy-run-setup-credentials');
  await expect(copyCredentials).toHaveText('COPY');
  const credentialGeometry = await credentialCard.evaluate(card => {
    const cardBox = card.getBoundingClientRect();
    const rows = Array.from(card.querySelectorAll('.run-setup-credential-row')).map(row => row.getBoundingClientRect());
    const copyButton = card.querySelector('.run-setup-copy-button');
    const buttonBox = copyButton.getBoundingClientRect();
    const titleNode = card.querySelector('.run-setup-credential-head > small');
    const title = titleNode.getBoundingClientRect();
    const note = card.querySelector('.run-setup-credential-note');
    const credentialList = card.querySelector('.run-setup-credential-list');
    const standardCard = card.parentElement.querySelector('.access-card');
    const standardLabel = standardCard.querySelector('small');
    const standardValue = standardCard.querySelector('b');
    const textStyle = node => {
      const css = getComputedStyle(node);
      return [css.fontFamily, css.fontSize, css.fontWeight, css.lineHeight, css.textTransform];
    };
    const withoutWeight = style => style.filter((_, index) => index !== 2);
    return {
      contained: rows.every(row => row.left >= cardBox.left && row.right <= cardBox.right),
      viewportContained: cardBox.left >= 0 && cardBox.right <= innerWidth,
      inlineTitle: Math.abs(title.top - buttonBox.top) <= 4 && title.right <= buttonBox.left,
      titleMatches: JSON.stringify(textStyle(titleNode)) === JSON.stringify(textStyle(standardLabel)),
      labelsMatch: Array.from(card.querySelectorAll('dt')).every(node => JSON.stringify(withoutWeight(textStyle(node))) === JSON.stringify(withoutWeight(textStyle(standardLabel)))),
      labelsBold: Array.from(card.querySelectorAll('dt')).every(node => Number.parseInt(getComputedStyle(node).fontWeight, 10) >= 1000),
      valuesMatch: Array.from(card.querySelectorAll('dd :is(a, code)')).every(node => JSON.stringify(textStyle(node)) === JSON.stringify(textStyle(standardValue))),
      copyMatches: JSON.stringify(textStyle(copyButton)) === JSON.stringify(textStyle(standardLabel)),
      arrowRemoved: !card.querySelector('.run-setup-copy-arrow'),
      noteSingleLine: note.scrollWidth <= note.clientWidth && getComputedStyle(note).whiteSpace === 'nowrap',
      noteClientWidth: note.clientWidth,
      noteScrollWidth: note.scrollWidth,
      credentialBox: getComputedStyle(credentialList).borderTopWidth === '3px' && getComputedStyle(credentialList).backgroundColor === 'rgb(255, 210, 173)',
      noteChartreuse: getComputedStyle(note).backgroundColor === 'rgb(215, 255, 31)',
      noteFontSize: parseFloat(getComputedStyle(note).fontSize),
      transitionDuration: parseFloat(getComputedStyle(copyButton).transitionDuration || '0'),
    };
  });
  expect(credentialGeometry.contained).toBeTruthy();
  expect(credentialGeometry.viewportContained).toBeTruthy();
  expect(credentialGeometry.inlineTitle).toBeTruthy();
  expect(credentialGeometry.titleMatches).toBeTruthy();
  expect(credentialGeometry.labelsMatch).toBeTruthy();
  expect(credentialGeometry.labelsBold).toBeTruthy();
  expect(credentialGeometry.valuesMatch).toBeTruthy();
  expect(credentialGeometry.copyMatches).toBeTruthy();
  expect(credentialGeometry.arrowRemoved).toBeTruthy();
  expect(credentialGeometry.noteSingleLine, JSON.stringify(credentialGeometry)).toBeTruthy();
  expect(credentialGeometry.credentialBox).toBeTruthy();
  expect(credentialGeometry.noteChartreuse).toBeTruthy();
  expect(credentialGeometry.noteFontSize).toBeGreaterThanOrEqual(7.04);
  expect(credentialGeometry.transitionDuration).toBeLessThanOrEqual(0.001);
  await copyCredentials.focus();
  await page.keyboard.press('Enter');
  await expect(copyCredentials).toHaveText('COPIED');
  await expect(copyCredentials).toHaveCSS('background-color', 'rgb(255, 59, 167)');
  const copiedCredentials = await page.evaluate(() => navigator.clipboard.readText());
  expect(copiedCredentials).toBe(`PRIVATE LINK: ${expectedPrivateLink}\nACCESS CODE: fixture-read-token\nRUN ID: batchValidationFixture`);

  const reentryPage = await page.context().newPage();
  reentryPage.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  reentryPage.on('pageerror', error => pageErrors.push(error.message));
  reentryPage.on('requestfailed', request => failedRequests.push(request.url()));
  reentryPage.on('response', response => {
    if (response.status() >= 400) httpErrors.push(`${response.status()} ${response.url()}`);
  });
  await routeSystemStatus(reentryPage);
  await reentryPage.route('**/api/jobs*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }));
  await reentryPage.goto(baseUrl);
  await reentryPage.getByRole('tab', { name: 'Existing results' }).click();
  await reentryPage.locator('#result-link-input').fill(copiedCredentials);
  const parsedCredentials = await reentryPage.evaluate(() => parseExistingRunInput());
  expect(parsedCredentials).toEqual({
    jobId: 'batchValidationFixture',
    token: 'fixture-read-token',
    publicResult: true,
  });
  await reentryPage.close();
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(httpErrors).toEqual([]);
});


test('run stack restores the bounded detailed accession receipt after another job replaces memory', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await routeSystemStatus(page);
  await page.route('**/api/jobs*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }));
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  const httpErrors = [];
  const authorization = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('requestfailed', request => failedRequests.push(request.url()));
  page.on('response', response => {
    if (response.status() >= 400) httpErrors.push(`${response.status()} ${response.url()}`);
  });

  const jobs = {
    stackRestoreA: {
      id: 'stackRestoreA',
      job_id: 'stackRestoreA',
      public_run_id: 'stackRestoreA',
      project_name: 'Stack restore A',
      status: 'success',
      stage: 'complete',
      input_summary: {
        accession_count: 6,
        analysis_scope: 'both',
        taxon_counts: { fungi: 2, bacteria: 4, total: 6 },
      },
      analysis_scope: 'both',
      taxon_counts: { fungi: 2, bacteria: 4, total: 6 },
    },
    stackRestoreB: {
      id: 'stackRestoreB',
      job_id: 'stackRestoreB',
      public_run_id: 'stackRestoreB',
      project_name: 'Stack restore B',
      status: 'success',
      stage: 'complete',
      input_summary: {
        accession_count: 1,
        analysis_scope: 'fungi',
        taxon_counts: { fungi: 1, bacteria: 0, total: 1 },
      },
      analysis_scope: 'fungi',
      taxon_counts: { fungi: 1, bacteria: 0, total: 1 },
    },
  };
  await page.route('**/api/results/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const parts = url.pathname.split('/').filter(Boolean);
    const runId = parts[2] || '';
    const suffix = parts[3] || '';
    authorization.push({ runId, suffix, value: request.headers().authorization || '' });
    if (suffix === 'artifacts') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ run_id: runId, artifacts: [] }),
      });
    }
    if (suffix === 'activity') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ run_id: runId, public_events: [], genome_progress: [] }),
      });
    }
    const job = jobs[runId];
    return route.fulfill({
      status: job ? 200 : 404,
      contentType: 'application/json',
      body: JSON.stringify(job || { detail: 'Not found' }),
    });
  });

  const accessionMetadata = [
    ['GCA_000011425.1', 'Fixture fungus one', 101, 'fungi'],
    ['GCA_000146045.2', 'Fixture fungus two', 102, 'fungi'],
    ['GCA_000009045.1', 'Fixture bacterium one', 201, 'bacteria'],
    ['GCA_000006765.1', 'Fixture bacterium two', 202, 'bacteria'],
    ['GCA_000195955.2', 'Fixture bacterium three', 203, 'bacteria'],
    ['GCA_000013425.1', 'Fixture bacterium four', 204, 'bacteria'],
  ].map(([accession, organism_name, tax_id, taxon_group], index) => ({
    accession,
    organism_name,
    tax_id,
    taxon_group,
    taxa: `NCBI taxon ${tax_id} / ${taxon_group}`,
    order_name: `Fixture order ${index + 1}`,
    family_name: `Fixture family ${index + 1}`,
    class_name: `Fixture class ${index + 1}`,
    order_family: `Fixture order ${index + 1}:Fixture family ${index + 1}`,
    genome_id: `private-genome-${index + 1}`,
    lineage_names: 'private-lineage-sentinel',
  }));

  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(baseUrl);
    await page.evaluate(({ metadata, jobB }) => {
      sessionStorage.clear();
      const receiptA = {
        projectName: 'Stack restore A',
        accessions: metadata.map(record => record.accession),
        accessionMetadata: metadata,
        analysisScope: 'both',
        taxonCounts: { fungi: 2, bacteria: 4, total: 6 },
      };
      const receiptB = {
        projectName: 'Stack restore B',
        accessions: ['GCA_000011425.1'],
        accessionMetadata: [metadata[0]],
        analysisScope: 'fungi',
        taxonCounts: { fungi: 1, bacteria: 0, total: 1 },
      };
      rememberOpenedRun('stackRestoreA', 'stack-token-a', {
        name: 'Stack restore A',
        status: 'success',
        receipt: receiptA,
      });
      rememberOpenedRun('stackRestoreB', 'stack-token-b', {
        name: 'Stack restore B',
        status: 'success',
        receipt: receiptB,
      });
      renderActiveRunAccessPanel(jobB);
    }, { metadata: accessionMetadata, jobB: jobs.stackRestoreB });

    await expect(page.locator('#run-setup-input-list .receipt-row')).toHaveCount(1);
    const toggle = page.locator('#run-stack-toggle');
    await toggle.focus();
    await page.keyboard.press('Enter');
    const restoreButton = page.locator('[data-run-stack-job="stackRestoreA"]');
    await expect(restoreButton).toBeVisible();
    await restoreButton.focus();
    await page.keyboard.press('Enter');

    const acceptedRows = page.locator('#run-setup-input-list .receipt-row');
    await expect(acceptedRows).toHaveCount(accessionMetadata.length);
    await expect(page.locator('#run-setup-input-list')).toContainText('Fixture fungus one');
    await expect(page.locator('#run-setup-input-list')).toContainText('NCBI taxon 204');
    await expect(page.locator('#run-setup-input-list')).not.toContainText('stored run input');
    await expect(page.locator('#run-setup-project')).toHaveText('Stack restore A');
    await expect(page.locator('body')).toHaveAttribute('data-existing-run-loaded', 'true');

    const storedReceipt = await page.evaluate(() => {
      const runs = JSON.parse(sessionStorage.getItem(STORAGE_KEYS.openedRuns) || '[]');
      const run = runs.find(item => item.id === 'stackRestoreA');
      return {
        receipt: run?.receipt || null,
        serialized: JSON.stringify(run?.receipt || {}),
      };
    });
    expect(storedReceipt.receipt.acceptedInputs).toHaveLength(accessionMetadata.length);
    expect(storedReceipt.receipt).not.toHaveProperty('inputSummary');
    expect(storedReceipt.serialized).not.toContain('private-lineage-sentinel');
    expect(storedReceipt.serialized).not.toContain('private-genome-');
    expect(authorization.some(item => item.runId === 'stackRestoreA' && item.value === 'Bearer stack-token-a')).toBeTruthy();
  }

  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(httpErrors).toEqual([]);
});
test('package transfer survives a new run and its progress tray does not collide', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await routeSystemStatus(page);
  await page.route('**/api/jobs', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }));
  await page.route('**/api/results/nextRunFixture*', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/artifacts')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ run_id: 'nextRunFixture', artifacts: [] }),
      });
    }
    if (path.endsWith('/activity')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ public_events: [], genome_progress: [] }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'nextRunFixture',
        public_run_id: 'nextRunFixture',
        project_name: 'next_run',
        status: 'pending',
        stage: 'queued',
        created_at: '2026-07-23T12:10:00',
        updated_at: '2026-07-23T12:10:00',
        result_file_count: 0,
        analysis_scope: 'fungi',
      }),
    });
  });

  await page.goto(baseUrl);
  await page.evaluate(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, options) => {
      const url = String(input instanceof Request ? input.url : input);
      if (!url.includes('/api/results/archiveRunFixture/archive')) {
        return originalFetch(input, options);
      }
      const chunkSize = 256 * 1024;
      const chunks = [
        new Uint8Array(chunkSize).fill(1),
        new Uint8Array(chunkSize).fill(2),
        new Uint8Array(chunkSize).fill(3),
      ];
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(chunks[0]);
          setTimeout(() => controller.enqueue(chunks[1]), 350);
          setTimeout(() => {
            controller.enqueue(chunks[2]);
            controller.close();
          }, 700);
        },
      });
      return Promise.resolve(new Response(stream, {
        status: 200,
        headers: {
          'content-type': 'application/zip',
          'content-length': String(chunkSize * chunks.length),
        },
      }));
    };
    setAccessMode('public');
    activeJobId = 'archiveRunFixture';
    activePublicRunId = 'archiveRunFixture';
    publicResultRunIds.add('archiveRunFixture');
    activeResultPackageFileCount = 1;
    activeResultFiles = ['artifact/figures/AAAAAAAAAAAAAAAAAAAAAA/fixture.svg'];
    document.body.dataset.jobState = 'complete';
    updateArchiveButton();
  });

  const downloadEvent = page.waitForEvent('download');
  await page.locator('#download-package-btn').focus();
  await page.keyboard.press('Enter');
  const tray = page.locator('#archive-download-tray');
  await expect(tray).toBeVisible();
  await expect(tray).toHaveAttribute('aria-busy', 'true');
  await expect.poll(() => page.locator('#archive-download-progress').getAttribute('aria-valuenow')).toBe('33');

  await page.evaluate(() => {
    void loadJob('nextRunFixture', false, { publicResult: true, source: 'submit' });
  });
  await expect.poll(() => page.evaluate(() => activeJobId)).toBe('nextRunFixture');
  await expect(tray).toBeVisible();
  await expect(tray).toHaveAttribute('aria-busy', 'true');

  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe('archiveRunFixture_clusterweave_results.zip');
  await expect(page.locator('#archive-download-title')).toHaveText('PACKAGE READY');
  await expect(page.locator('#archive-download-percent')).toHaveText('100%');
  const reducedMotionStyles = await page.evaluate(() => {
    const spinner = getComputedStyle(document.querySelector('.archive-download-spinner'));
    const progress = getComputedStyle(document.querySelector('.archive-download-progress > span'));
    return {
      spinnerAnimation: spinner.animationName,
      spinnerDuration: spinner.animationDuration,
      progressTransition: progress.transitionDuration,
    };
  });
  expect(reducedMotionStyles.spinnerAnimation).toBe('none');
  expect(parseFloat(reducedMotionStyles.spinnerDuration)).toBeLessThanOrEqual(0.001);
  expect(parseFloat(reducedMotionStyles.progressTransition)).toBeLessThanOrEqual(0.001);

  await page.evaluate(() => {
    document.body.dataset.jobState = 'complete';
    document.getElementById('completion-callout').classList.remove('hidden');
  });
  for (const width of [1280, 760, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const geometry = await page.evaluate(() => {
      const trayBox = document.getElementById('archive-download-tray').getBoundingClientRect();
      const calloutBox = document.getElementById('completion-callout').getBoundingClientRect();
      const overlap = !(
        trayBox.right <= calloutBox.left
        || trayBox.left >= calloutBox.right
        || trayBox.bottom <= calloutBox.top
        || trayBox.top >= calloutBox.bottom
      );
      return {
        tray: { left: trayBox.left, right: trayBox.right, top: trayBox.top, bottom: trayBox.bottom },
        overlap,
        viewport: { width: innerWidth, height: innerHeight },
      };
    });
    expect(geometry.tray.left).toBeGreaterThanOrEqual(0);
    expect(geometry.tray.right).toBeLessThanOrEqual(geometry.viewport.width);
    expect(geometry.tray.top).toBeGreaterThanOrEqual(0);
    expect(geometry.tray.bottom).toBeLessThanOrEqual(geometry.viewport.height);
    expect(geometry.overlap).toBeFalsy();
  }
});
