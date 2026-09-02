const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const baseUrl = 'http://127.0.0.1:4173';
const evidenceDir = process.env.CLUSTERWEAVE_R13B_EVIDENCE_DIR || '';

async function captureEvidence(page, name, selectors) {
  if (!evidenceDir) return;
  fs.mkdirSync(evidenceDir, { recursive: true });
  const phase = process.env.CLUSTERWEAVE_R13B_PHASE || 'capture';
  await page.screenshot({
    path: path.join(evidenceDir, `${phase}-${name}.png`),
    fullPage: true,
    animations: 'disabled',
  });
  const snapshot = await page.evaluate(items => Object.fromEntries(items.map(selector => {
    const node = document.querySelector(selector);
    if (!node) return [selector, null];
    const style = getComputedStyle(node);
    const box = node.getBoundingClientRect();
    return [selector, {
      display: style.display,
      width: style.width,
      height: style.height,
      padding: style.padding,
      border: style.border,
      backgroundColor: style.backgroundColor,
      color: style.color,
      boxShadow: style.boxShadow,
      opacity: style.opacity,
      visibility: style.visibility,
      animationDuration: style.animationDuration,
      transitionDuration: style.transitionDuration,
      box: { x: box.x, y: box.y, width: box.width, height: box.height },
    }];
  })), selectors);
  fs.writeFileSync(
    path.join(evidenceDir, `${phase}-${name}.json`),
    `${JSON.stringify(snapshot, null, 2)}\n`,
  );
}

test('public impact audit hydrates and the credit drawer separates web and local tools', async ({ page }) => {
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('requestfailed', request => failedRequests.push(request.url()));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('**/api/system/status*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        online: true,
        service: 'online',
        submissions_open: true,
        submissions: 'open',
        jobs_processed: 137,
        running_jobs: 2,
        queued_jobs: 5,
        smtp_enabled: false,
        public_quota: { max_accessions: 50 },
      }),
    });
  });

  await page.goto(baseUrl);

  const audit = page.locator('.public-impact-audit');
  await expect(page.locator('#public-impact-server')).toHaveText('online');
  await expect(page.locator('#public-impact-running')).toHaveText('2');
  await expect(page.locator('#public-impact-queued')).toHaveText('5');
  await expect(page.locator('#public-impact-completed')).toHaveText('137');
  await expect(audit).toBeVisible();

  const auditStyle = await audit.evaluate(node => {
    const style = getComputedStyle(node);
    return {
      backgroundColor: style.backgroundColor,
      borderTopWidth: style.borderTopWidth,
      color: style.color,
    };
  });
  expect(auditStyle.backgroundColor).toBe('rgba(0, 0, 0, 0)');
  expect(auditStyle.borderTopWidth).toBe('0px');
  expect(auditStyle.color).toBe('rgb(5, 5, 5)');

  const rows = await audit.locator(':scope > div').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().top));
  expect(rows).toHaveLength(4);
  expect(rows[0]).toBeLessThan(rows[1]);
  expect(rows[1]).toBeLessThan(rows[2]);
  expect(rows[2]).toBeLessThan(rows[3]);

  const citationCard = page.locator('.summary');
  const creditButton = page.getByRole('button', { name: 'Credit', exact: true });
  await expect(citationCard).toHaveText('IF YOU HAVE FOUND CLUSTERWEAVE USEFUL, CITE US.');
  await expect(citationCard).toHaveCSS('text-transform', 'uppercase');
  await expect(creditButton).toHaveText('Credit');
  await expect(creditButton).toHaveCSS('background-color', 'rgb(87, 83, 78)');
  const joinedCardGeometry = await page.evaluate(() => {
    const citationNode = document.querySelector('.summary');
    const creditNode = document.getElementById('tool-credit-open');
    const row = document.querySelector('.citation-card-row').getBoundingClientRect();
    const citation = citationNode.getBoundingClientRect();
    const credit = creditNode.getBoundingClientRect();
    const citationContent = citationNode.firstElementChild.getBoundingClientRect();
    const creditContentRange = document.createRange();
    creditContentRange.selectNodeContents(creditNode);
    const creditContent = creditContentRange.getBoundingClientRect();
    const workflow = document.getElementById('workflow-progress-panel').getBoundingClientRect();
    const results = document.getElementById('results-card').getBoundingClientRect();
    const citationStyle = getComputedStyle(citationNode);
    const creditStyle = getComputedStyle(creditNode);
    return {
      seam: citation.right - credit.left,
      topDelta: Math.abs(citation.top - credit.top),
      bottomDelta: Math.abs(citation.bottom - credit.bottom),
      contentCenterDelta: Math.abs(
        ((citationContent.top + citationContent.bottom) / 2)
        - ((creditContent.top + creditContent.bottom) / 2)
      ),
      workflowBottomDelta: Math.abs(row.bottom - workflow.bottom),
      resultsBottomDelta: Math.abs(row.bottom - results.bottom),
      rowWidth: row.width,
      citationHeight: citation.height,
      citationSingleLine: citationNode.scrollWidth <= citationNode.clientWidth && citationStyle.whiteSpace === 'nowrap',
      citationFontSize: parseFloat(citationStyle.fontSize),
      citationCentered: citationStyle.textAlign === 'center',
      creditWidth: credit.width,
      creditPaddingInline: parseFloat(creditStyle.paddingLeft) + parseFloat(creditStyle.paddingRight),
    };
  });
  expect(joinedCardGeometry.seam).toBeGreaterThanOrEqual(0);
  expect(joinedCardGeometry.seam).toBeLessThanOrEqual(3);
  expect(joinedCardGeometry.topDelta).toBeLessThanOrEqual(1);
  expect(joinedCardGeometry.bottomDelta).toBeLessThanOrEqual(1);
  expect(joinedCardGeometry.contentCenterDelta).toBeLessThanOrEqual(1);
  expect(joinedCardGeometry.workflowBottomDelta).toBeLessThanOrEqual(1);
  expect(joinedCardGeometry.resultsBottomDelta).toBeLessThanOrEqual(1);
  expect(joinedCardGeometry.rowWidth).toBeLessThanOrEqual(496);
  expect(joinedCardGeometry.citationHeight).toBeLessThanOrEqual(46);
  expect(joinedCardGeometry.citationSingleLine).toBeTruthy();
  expect(joinedCardGeometry.citationFontSize).toBeLessThanOrEqual(11.52);
  expect(joinedCardGeometry.citationCentered).toBeTruthy();
  expect(joinedCardGeometry.creditWidth).toBeLessThanOrEqual(86);
  expect(joinedCardGeometry.creditPaddingInline).toBeLessThanOrEqual(13);
  await creditButton.focus();
  await page.keyboard.press('Enter');
  const drawer = page.getByRole('dialog', { name: 'Upstream tool credit' });
  await expect(drawer).toBeVisible();
  const supportTab = drawer.getByRole('tab', { name: 'Support' });
  const webTab = drawer.getByRole('tab', { name: 'Web workflow' });
  const localTab = drawer.getByRole('tab', { name: 'Local options' });
  const supportPanel = drawer.getByRole('tabpanel', { name: 'Support' });
  const pmiLink = drawer.getByRole('link', { name: 'Plant Microbe Interfaces (PMI)' });
  const pmiLogo = drawer.getByRole('img', { name: 'Plant Microbe Interfaces (PMI)' });
  await expect(supportTab).toHaveAttribute('aria-selected', 'true');
  await expect(webTab).toHaveAttribute('aria-selected', 'false');
  await expect(localTab).toHaveAttribute('aria-selected', 'false');
  await expect(supportPanel).toBeVisible();
  await expect(pmiLink).toHaveAttribute('href', 'https://pmiweb.ornl.gov/');
  await expect(pmiLink).toHaveAttribute('target', '_blank');
  await expect(pmiLink).toHaveAttribute('rel', 'noopener');
  await expect(pmiLogo).toBeVisible();
  await expect(pmiLogo).toHaveAttribute('src', 'assets/pmi-logo.png');
  await expect.poll(() => pmiLogo.evaluate(image => ({
    complete: image.complete,
    naturalWidth: image.naturalWidth,
    naturalHeight: image.naturalHeight,
  }))).toEqual({ complete: true, naturalWidth: 2079, naturalHeight: 1017 });
  await expect(drawer.getByRole('link', { name: /NCBI Datasets \+ Dataformat/ })).toBeHidden();
  await pmiLink.focus();
  await expect(pmiLink).toBeFocused();
  await supportTab.focus();
  await page.keyboard.press('Home');
  await expect(supportTab).toHaveAttribute('aria-selected', 'true');
  await expect(pmiLogo).toBeVisible();
  await page.keyboard.press('End');
  await expect(localTab).toHaveAttribute('aria-selected', 'true');
  await expect(drawer.getByRole('link', { name: /MAFFT/ })).toBeVisible();

  await supportTab.focus();
  await page.keyboard.press('ArrowRight');
  await expect(webTab).toHaveAttribute('aria-selected', 'true');
  await expect(drawer.getByRole('link', { name: /NCBI Datasets \+ Dataformat/ })).toBeVisible();
  await expect(pmiLogo).toBeHidden();

  await page.keyboard.press('ArrowRight');
  await expect(localTab).toHaveAttribute('aria-selected', 'true');
  await expect(drawer.getByRole('link', { name: /MAFFT/ })).toBeVisible();
  await expect(drawer.getByRole('link', { name: /NCBI Datasets \+ Dataformat/ })).toBeHidden();
  const creditNames = await drawer.locator('.tool-credit-link').evaluateAll(links => links.map(link => (
    link.childNodes[0]?.textContent || ''
  ).trim()));
  expect(creditNames).toEqual([
    'NCBI Datasets + Dataformat', 'NCBI GenBank + RefSeq', 'NCBI Taxonomy',
    'antiSMASH', 'Prodigal', 'FunBGCeX', 'funannotate', 'BUSCO', 'AUGUSTUS',
    'DIAMOND', 'HMMER', 'Biopython', 'BiG-SCAPE', 'FastTree', 'clinker',
    'MIBiG', 'Pfam', 'BRAKER3', 'GeneMark', 'NPLinker', 'GNPS', 'MassIVE',
    'PODP', 'MAFFT', 'IQ-TREE 2', 'ETE 4', 'trimAl', 'CairoSVG',
  ]);

  const cardBounds = await drawer.locator('.tool-credit-link:visible').evaluateAll(links => links.map(link => {
    const license = link.querySelector('sup');
    const box = link.getBoundingClientRect();
    const licenseBox = license.getBoundingClientRect();
    return {
      whiteSpace: getComputedStyle(link).whiteSpace,
      contained: licenseBox.right <= box.right && licenseBox.left >= box.left,
    };
  }));
  expect(cardBounds.every(card => card.whiteSpace === 'nowrap' && card.contained)).toBeTruthy();

  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  await expect(creditButton).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(drawer).toBeVisible();
  await expect(supportTab).toHaveAttribute('aria-selected', 'true');
  await expect(pmiLogo).toBeVisible();

  const surfaceContract = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    const moduleStyle = getComputedStyle(document.querySelector('.module'));
    return {
      tokens: Object.fromEntries([
        '--ink', '--paper', '--panel', '--cyan', '--pink', '--acid',
        '--lavender', '--line', '--shadow', '--shadow-small', '--radius',
      ].map(name => [name, root.getPropertyValue(name).trim()])),
      module: {
        backgroundColor: moduleStyle.backgroundColor,
        borderRadius: moduleStyle.borderRadius,
        boxShadow: moduleStyle.boxShadow,
      },
    };
  });
  expect(surfaceContract.tokens).toEqual({
    '--ink': '#050505',
    '--paper': '#fffdf7',
    '--panel': '#ffffff',
    '--cyan': '#00d9ff',
    '--pink': '#ff3ba7',
    '--acid': '#d7ff1f',
    '--lavender': '#c9b8ff',
    '--line': '#050505',
    '--shadow': '7px 7px 0 #050505',
    '--shadow-small': '5px 5px 0 #050505',
    '--radius': '4px',
  });
  expect(surfaceContract.module).toEqual({
    backgroundColor: 'rgb(255, 255, 255)',
    borderRadius: '4px',
    boxShadow: 'rgb(5, 5, 5) 7px 7px 0px 0px',
  });
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
  await captureEvidence(page, 'credits-desktop', [
    '.module',
    '.public-impact-audit',
    '.tool-credit-shell',
    '.tool-credit-link:not([hidden])',
  ]);
});

test('zoom-equivalent widths keep workflow status and caption separated', async ({ page }) => {
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('requestfailed', request => failedRequests.push(request.url()));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('**/api/system/status*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      online: true,
      service: 'online',
      submissions_open: true,
      submissions: 'open',
      jobs_processed: 0,
      running_jobs: 0,
      queued_jobs: 0,
      public_quota: { max_accessions: 50, max_genome_files: 50 },
    }),
  }));
  await page.setViewportSize({ width: 760, height: 900 });
  await page.goto(baseUrl);

  for (const width of [760, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const geometry = await page.evaluate(() => {
      const panel = document.getElementById('bgc-workflow-station').getBoundingClientRect();
      const status = document.querySelector('#bgc-workflow-station > .workflow-tool-status').getBoundingClientRect();
      const captionNode = document.querySelector('#bgc-workflow-station > .workflow-caption');
      const caption = captionNode.getBoundingClientRect();
      const label = document.getElementById('workflow-caption-label').getBoundingClientRect();
      const percent = document.getElementById('workflow-percent').getBoundingClientRect();
      const citationNode = document.querySelector('.summary');
      const creditNode = document.getElementById('tool-credit-open');
      const row = document.querySelector('.citation-card-row').getBoundingClientRect();
      const citation = citationNode.getBoundingClientRect();
      const credit = creditNode.getBoundingClientRect();
      const citationContent = citationNode.firstElementChild.getBoundingClientRect();
      const creditContentRange = document.createRange();
      creditContentRange.selectNodeContents(creditNode);
      const creditContent = creditContentRange.getBoundingClientRect();
      const citationStyle = getComputedStyle(citationNode);
      const creditStyle = getComputedStyle(creditNode);
      const overlap = !(status.right <= caption.left || status.left >= caption.right || status.bottom <= caption.top || status.top >= caption.bottom);
      return {
        overlap,
        captionPosition: getComputedStyle(captionNode).position,
        captionContained: caption.left >= panel.left && caption.right <= panel.right && caption.top >= panel.top && caption.bottom <= panel.bottom,
        captionOrder: status.bottom <= caption.top,
        labelContained: label.right <= percent.left,
        joinedSeam: citation.right - credit.left,
        joinedTopDelta: Math.abs(citation.top - credit.top),
        joinedBottomDelta: Math.abs(citation.bottom - credit.bottom),
        contentCenterDelta: Math.abs(
          ((citationContent.top + citationContent.bottom) / 2)
          - ((creditContent.top + creditContent.bottom) / 2)
        ),
        citationSingleLine: citationNode.scrollWidth <= citationNode.clientWidth && citationStyle.whiteSpace === 'nowrap',
        citationFontSize: parseFloat(citationStyle.fontSize),
        citationCentered: citationStyle.textAlign === 'center',
        rowWidth: row.width,
        creditWidth: credit.width,
        creditPaddingInline: parseFloat(creditStyle.paddingLeft) + parseFloat(creditStyle.paddingRight),
        transitionDuration: parseFloat(getComputedStyle(captionNode).transitionDuration),
      };
    });
    expect(geometry.overlap).toBeFalsy();
    expect(geometry.captionPosition).toBe('absolute');
    expect(geometry.captionContained).toBeTruthy();
    expect(geometry.captionOrder).toBeTruthy();
    expect(geometry.labelContained).toBeTruthy();
    expect(geometry.joinedSeam).toBeGreaterThanOrEqual(0);
    expect(geometry.joinedSeam).toBeLessThanOrEqual(3);
    expect(geometry.joinedTopDelta).toBeLessThanOrEqual(1);
    expect(geometry.joinedBottomDelta).toBeLessThanOrEqual(1);
    expect(geometry.contentCenterDelta).toBeLessThanOrEqual(1);
    expect(geometry.citationSingleLine).toBeTruthy();
    expect(geometry.citationFontSize).toBeLessThanOrEqual(11.52);
    expect(geometry.citationCentered).toBeTruthy();
    expect(geometry.rowWidth).toBeLessThanOrEqual(Math.min(496, width));
    expect(geometry.creditWidth).toBeLessThanOrEqual(86);
    expect(geometry.creditPaddingInline).toBeLessThanOrEqual(13);
    expect(geometry.transitionDuration).toBeLessThanOrEqual(0.001);
  }

  await expect(page.locator('.summary')).toHaveText('IF YOU HAVE FOUND CLUSTERWEAVE USEFUL, CITE US.');
  await expect(page.getByRole('button', { name: 'Credit', exact: true })).toHaveCSS('background-color', 'rgb(87, 83, 78)');
  await page.getByRole('button', { name: 'Credit', exact: true }).click();
  const supportPanel = page.getByRole('tabpanel', { name: 'Support' });
  const pmiLogo = page.getByRole('img', { name: 'Plant Microbe Interfaces (PMI)' });
  await expect(page.getByRole('tab', { name: 'Support' })).toHaveAttribute('aria-selected', 'true');
  await expect(supportPanel).toBeVisible();
  await expect(pmiLogo).toBeVisible();
  const supportGeometry = await page.evaluate(() => {
    const panel = document.getElementById('tool-credit-support-panel').getBoundingClientRect();
    const image = document.querySelector('.pmi-support-logo').getBoundingClientRect();
    return {
      contained: image.left >= panel.left && image.right <= panel.right && image.top >= panel.top && image.bottom <= panel.bottom,
      viewportContained: panel.left >= 0 && panel.right <= innerWidth,
      naturalWidth: document.querySelector('.pmi-support-logo').naturalWidth,
      naturalHeight: document.querySelector('.pmi-support-logo').naturalHeight,
    };
  });
  expect(supportGeometry).toEqual({ contained: true, viewportContained: true, naturalWidth: 2079, naturalHeight: 1017 });
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test('accession intake matches upload height and verification opens beside Submit', async ({ page }) => {
  let validationRequests = 0;
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/inputs/validate') validationRequests += 1;
  });
  await page.route('**/api/system/status*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ online: true, service: 'online', submissions_open: true, jobs_processed: 0, running_jobs: 0, queued_jobs: 0, public_quota: { max_accessions: 50 } }),
    });
  });
  await page.goto(baseUrl);

  const accessionCard = page.locator('#brutal-accession-card');
  const uploadCard = page.locator('#genome-upload-card');
  const [accessionBox, uploadBox] = await Promise.all([accessionCard.boundingBox(), uploadCard.boundingBox()]);
  expect(Math.abs(accessionBox.height - uploadBox.height)).toBeLessThanOrEqual(1);

  const presentedRows = page.locator('.brutal-accession-line:not(.is-concealed)');
  await expect(presentedRows).toHaveCount(6);
  await expect(presentedRows.locator('textarea:disabled')).toHaveCount(5);

  const firstAccession = presentedRows.first().locator('textarea');
  const log = page.locator('#input-log-drawer');
  await firstAccession.pressSequentially('not-an-accession');
  await expect(firstAccession).toHaveAttribute('aria-invalid', 'false');
  await expect(firstAccession.locator('xpath=.././/span[contains(@class, "status-icon")]')).toHaveAttribute('aria-label', 'Accession validation pending');
  await expect(log).toBeHidden();
  expect(validationRequests).toBe(0);
  await page.locator('#project-name').focus();
  await expect(log).toBeVisible();
  await expect(log).toContainText('not a current NCBI assembly accession');
  await expect(log.locator('xpath=..')).toHaveClass(/submit-feedback-rail/);
  const [buttonBox, logBox] = await Promise.all([page.locator('#run-btn').boundingBox(), log.boundingBox()]);
  expect(logBox.x).toBeGreaterThan(buttonBox.x + buttonBox.width - 1);

  await page.getByRole('button', { name: 'Close input verification' }).click();
  await expect(log).toBeHidden();
  await page.evaluate(() => {
    window.__inputLogMutationRecords = 0;
    new MutationObserver(records => {
      window.__inputLogMutationRecords += records.length;
    }).observe(document.getElementById('input-log-list'), {
      subtree: true,
      childList: true,
      characterData: true,
    });
  });

  const projectName = page.locator('#project-name');
  await projectName.fill('myproject');
  await projectName.evaluate(node => node.setSelectionRange(2, 2));
  await page.keyboard.insertText(' ');
  await expect(projectName).toHaveValue('my project');
  expect(await projectName.evaluate(node => node.selectionStart)).toBe(3);
  await projectName.evaluate(node => {
    node.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
    node.setRangeText('研究', node.value.length, node.value.length, 'end');
    node.dispatchEvent(new InputEvent('input', {
      bubbles: true,
      data: '研究',
      inputType: 'insertCompositionText',
      isComposing: true,
    }));
    node.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '研究' }));
  });
  await expect(projectName).toHaveValue('my project研究');
  await expect(log).toBeHidden();
  expect(await page.evaluate(() => window.__inputLogMutationRecords)).toBe(0);
  expect(validationRequests).toBe(0);

  await firstAccession.focus();
  await expect(projectName).toHaveValue('my_project');
  await expect(log).toBeHidden();
  expect(await page.evaluate(() => window.__inputLogMutationRecords)).toBe(0);
  await firstAccession.fill('also-invalid');
  await expect(firstAccession).toHaveAttribute('aria-invalid', 'false');
  await expect(log).toBeHidden();
  await projectName.focus();
  await expect(firstAccession).toHaveAttribute('aria-invalid', 'true');
  await expect(log).toBeVisible();
  await expect(log).toContainText('Row 1: ALSO-INVALID');
  await expect.poll(() => page.evaluate(() => window.__inputLogMutationRecords)).toBe(2);
  expect(validationRequests).toBe(0);
});

test('Both-mode upload uses a compact taxon table and expands the accession viewport', async ({ page }) => {
  await page.route('**/api/system/status*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ online: true, service: 'online', submissions_open: true, jobs_processed: 0, running_jobs: 0, queued_jobs: 0, public_quota: { max_accessions: 50, max_genome_files: 50 } }),
    });
  });
  await page.goto(baseUrl);

  const analysisScope = page.getByRole('group', { name: 'Analysis scope' });
  const panel = page.locator('#taxon-assignment-panel');
  await expect(analysisScope.getByRole('radio', { name: 'Fungi' })).toBeChecked();
  await expect(panel).toBeHidden();

  const accessionList = page.locator('#brutal-accession-rows');
  const initialHeight = await accessionList.evaluate(node => node.clientHeight);
  await page.getByText('Both', { exact: true }).click();
  await expect(analysisScope.getByRole('radio', { name: 'Both' })).toBeChecked();
  await page.locator('#file-input').setInputFiles({
    name: 'input.genome.fna',
    mimeType: 'text/plain',
    buffer: Buffer.from(`>input_genome\n${'A'.repeat(2000)}\n`),
  });
  const uploadedRow = page.locator('#file-list .file-item[data-target-genome]').first();
  await expect(uploadedRow.getByText('TARGET', { exact: true })).toHaveCount(0);
  await expect(uploadedRow.locator('.file-eco-button')).toHaveCount(2);
  await expect(uploadedRow.locator('.file-eco-button').first()).toBeHidden();

  await uploadedRow.locator('.file-name').click();
  await expect(uploadedRow).toHaveClass(/is-target/);
  await expect(page.locator('#target-genome')).toHaveValue('input.genome');

  await page.locator('#brutal-ecology-toggle').click();
  const primaryEcology = uploadedRow.locator('.file-eco-button[data-eco-field="primary"]');
  await expect(primaryEcology).toBeVisible();
  await primaryEcology.click();
  await expect(page.locator('#brutal-eco-picker')).toBeVisible();
  await page.locator('#brutal-eco-picker-options [data-eco-option="soil"]').click();
  await expect(primaryEcology).toHaveClass(/is-saved/);
  await expect(page.locator('#target-genome')).toHaveValue('input.genome');
  await expect.poll(() => page.evaluate(() => metadataProfileText())).toContain('input.genome\t');
  await expect.poll(() => page.evaluate(() => metadataProfileText())).toContain('\tsoil\t');

  await expect(panel).toBeVisible();
  await expect(panel.locator('#taxon-assignment-title')).toHaveText('Taxon assignments');
  await expect(panel.locator('.taxon-assignment-bulk')).toHaveCount(0);
  await expect(panel.locator('p')).toHaveCount(0);
  const columns = panel.locator('.taxon-assignment-columns');
  const rowgroup = panel.getByRole('rowgroup');
  const row = rowgroup.getByRole('row');
  const fungiBulk = panel.getByRole('columnheader', { name: 'Assign every unresolved genome to fungi' });
  const bacteriaBulk = panel.getByRole('columnheader', { name: 'Assign every unresolved genome to bacteria' });
  const fungiChoice = row.getByRole('radio', { name: 'Assign input.genome to fungi' });
  const bacteriaChoice = row.getByRole('radio', { name: 'Assign input.genome to bacteria' });
  await expect(columns).toHaveAttribute('role', 'row');
  await expect(rowgroup).toBeVisible();
  await expect(row).toHaveCount(1);
  await expect(row.getByRole('cell')).toHaveCount(3);
  await expect(row).toHaveClass(/is-unresolved/);
  await expect(fungiChoice).not.toBeChecked();
  await expect(bacteriaChoice).not.toBeChecked();
  await expect(panel.locator('#taxon-assignment-status')).toHaveText('1 unresolved');
  await expect(page.locator('#data-use-ack-panel')).toBeVisible();
  await expect(page.locator('#data-use-ack-panel')).toHaveText('PUBLIC DATA ONLY');
  await expect(page.locator('#upload-status')).not.toContainText('logical genome assignment');
  const panelStyle = await panel.evaluate(node => {
    const style = getComputedStyle(node);
    return { display: style.display, borderTopWidth: style.borderTopWidth };
  });
  expect(panelStyle).toEqual({ display: 'grid', borderTopWidth: '0px' });
  const choiceStyle = await fungiChoice.evaluate(node => {
    const style = getComputedStyle(node);
    return { width: style.width, height: style.height };
  });
  expect(choiceStyle).toEqual({ width: '17px', height: '17px' });
  const unresolvedBackground = await row.evaluate(node => getComputedStyle(node).backgroundColor);
  const expandedHeight = await accessionList.evaluate(node => node.clientHeight);
  expect(expandedHeight).toBeGreaterThan(initialHeight);

  await bacteriaBulk.focus();
  await page.keyboard.press('Enter');
  await expect(bacteriaChoice).toBeChecked();
  await expect(fungiChoice).not.toBeChecked();
  await expect(row).not.toHaveClass(/is-unresolved/);
  await expect(panel.locator('#taxon-assignment-status')).toHaveText('0 unresolved');
  await expect.poll(() => page.evaluate(() => taxonAssignmentsPayload())).toEqual({
    'input.genome': 'bacteria',
  });
  const resolvedBackground = await row.evaluate(node => getComputedStyle(node).backgroundColor);
  expect(resolvedBackground).not.toBe(unresolvedBackground);

  await fungiBulk.focus();
  await page.keyboard.press('Space');
  await expect(fungiChoice).toBeChecked();
  await expect(bacteriaChoice).not.toBeChecked();
  await expect(panel.locator('#taxon-assignment-status')).toHaveText('0 unresolved');
  await expect.poll(() => page.evaluate(() => taxonAssignmentsPayload())).toEqual({
    'input.genome': 'fungi',
  });
});

test('mobile reduced-motion intake preserves validation, accessibility, and submission payload', async ({ page }) => {
  const pageErrors = [];
  const failedRequests = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('requestfailed', request => failedRequests.push(`${request.method()} ${request.url()}`));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('**/api/system/status*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      online: true,
      service: 'online',
      submissions_open: true,
      jobs_processed: 0,
      running_jobs: 0,
      queued_jobs: 0,
      public_quota: { max_accessions: 50, max_genome_files: 50 },
    }),
  }));
  await page.goto(baseUrl);

  const adminDrawer = page.locator('#ops-side-panel');
  await expect(adminDrawer).toBeHidden();
  await expect(adminDrawer).toHaveAttribute('aria-hidden', 'true');
  await expect(page.locator('#rerun-panel')).toHaveAttribute('inert', '');

  const firstAccession = page.locator('.brutal-accession-line:not(.is-concealed) textarea').first();
  await firstAccession.fill('not-an-accession');
  await page.locator('#project-name').focus();
  await expect(firstAccession).toHaveAttribute('aria-invalid', 'true');
  await firstAccession.fill('');
  await page.locator('#project-name').focus();
  await expect(firstAccession).toHaveAttribute('aria-invalid', 'false');

  await page.getByText('Both', { exact: true }).click();
  await page.locator('#file-input').setInputFiles({
    name: 'mobile.input.fna',
    mimeType: 'text/plain',
    buffer: Buffer.from(`>mobile_input\n${'A'.repeat(2000)}\n`),
  });
  const uploadedRow = page.locator('#file-list .file-item[data-target-genome]').first();
  await uploadedRow.locator('.file-name').click();
  await page.locator('#brutal-ecology-toggle').click();
  await uploadedRow.locator('.file-eco-button[data-eco-field="primary"]').click();
  await page.locator('#brutal-eco-picker-options [data-eco-option="soil"]').click();
  await page.getByRole('columnheader', { name: 'Assign every unresolved genome to bacteria' }).focus();
  await page.keyboard.press('Enter');
  await page.locator('#data-use-ack').check();
  await page.locator('#project-name').fill('mobile_mixed');

  const panelBounds = await page.locator('#taxon-assignment-panel').boundingBox();
  expect(panelBounds.x).toBeGreaterThanOrEqual(0);
  expect(panelBounds.x + panelBounds.width).toBeLessThanOrEqual(390);
  await expect(page.locator('#taxon-assignment-status')).toHaveText('0 unresolved');

  await page.evaluate(() => {
    const originalFetch = window.fetch;
    window.__r12bSubmissionPayload = null;
    window.fetch = (input, init = {}) => {
      if (String(input).endsWith('/api/jobs') && init.method === 'POST' && init.body instanceof FormData) {
        window.__r12bSubmissionPayload = Array.from(init.body.entries(), ([key, value]) => [
          key,
          value instanceof File
            ? { name: value.name, size: value.size, type: value.type }
            : String(value),
        ]);
        return new Promise(() => {});
      }
      return originalFetch(input, init);
    };
  });

  const runButton = page.locator('#run-btn');
  await runButton.focus();
  await page.keyboard.press('Enter');
  await expect(runButton).toHaveText('Submit run');
  await expect(runButton).toBeEnabled();
  await runButton.focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => page.evaluate(() => window.__r12bSubmissionPayload)).not.toBeNull();
  const payload = Object.fromEntries(await page.evaluate(() => window.__r12bSubmissionPayload));
  expect(payload.project_name).toBe('mobile_mixed');
  expect(payload.analysis_scope).toBe('both');
  expect(JSON.parse(payload.taxon_assignments)).toEqual({ 'mobile.input': 'bacteria' });
  expect(payload.data_use_ack).toBe('1');
  expect(payload.target_genome).toBe('mobile.input');
  expect(payload.run_ecology_analysis).toBe('1');
  expect(await page.evaluate(() => window.__r12bSubmissionPayload
    .filter(([key]) => key === 'files')
    .map(([, value]) => value.name))).toEqual(['mobile.input.fna', 'ecofun_metadata_normalized.tsv']);
  expect(pageErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
  await captureEvidence(page, 'intake-mobile-reduced', [
    '#brutal-accession-card',
    '#genome-upload-card',
    '#taxon-assignment-panel',
    '#run-btn',
    '.sr-only',
  ]);
});
