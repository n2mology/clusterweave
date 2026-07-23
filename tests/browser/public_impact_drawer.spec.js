const { test, expect } = require('@playwright/test');

const baseUrl = 'http://127.0.0.1:4173';

test('public impact audit hydrates and the credit drawer separates web and local tools', async ({ page }) => {
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

  await page.getByRole('button', { name: 'Upstream Tool Credit' }).click();
  const drawer = page.getByRole('dialog', { name: 'Upstream tool credit' });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('tab', { name: 'Web workflow' })).toHaveAttribute('aria-selected', 'true');
  await expect(drawer.getByRole('link', { name: /NCBI Datasets \+ Dataformat/ })).toBeVisible();
  await expect(drawer.getByRole('link', { name: /MAFFT/ })).toBeHidden();
  await drawer.getByRole('tab', { name: 'Local options' }).click();
  await expect(drawer.getByRole('tab', { name: 'Local options' })).toHaveAttribute('aria-selected', 'true');
  await expect(drawer.getByRole('link', { name: /MAFFT/ })).toBeVisible();

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
});

test('accession intake matches upload height and verification opens beside Submit', async ({ page }) => {
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

  await presentedRows.first().locator('textarea').fill('not-an-accession');
  await page.locator('#project-name').focus();
  const log = page.locator('#input-log-drawer');
  await expect(log).toBeVisible();
  await expect(log).toContainText('not a current NCBI assembly accession');
  await expect(log.locator('xpath=..')).toHaveClass(/submit-feedback-rail/);
  const [buttonBox, logBox] = await Promise.all([page.locator('#run-btn').boundingBox(), log.boundingBox()]);
  expect(logBox.x).toBeGreaterThan(buttonBox.x + buttonBox.width - 1);
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

  const accessionList = page.locator('#brutal-accession-rows');
  const initialHeight = await accessionList.evaluate(node => node.clientHeight);
  await page.getByText('Both', { exact: true }).click();
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

  const panel = page.locator('#taxon-assignment-panel');
  await expect(panel).toBeVisible();
  await expect(panel.locator('#taxon-assignment-title')).toHaveText('Taxon assignments');
  await expect(panel.locator('.taxon-assignment-bulk')).toHaveCount(0);
  await expect(panel.locator('p')).toHaveCount(0);
  await expect(page.locator('#data-use-ack-panel')).toBeVisible();
  await expect(page.locator('#data-use-ack-panel')).toHaveText('PUBLIC DATA ONLY');
  await expect(page.locator('#upload-status')).not.toContainText('logical genome assignment');
  const panelBorder = await panel.evaluate(node => getComputedStyle(node).borderTopWidth);
  expect(panelBorder).toBe('0px');
  const expandedHeight = await accessionList.evaluate(node => node.clientHeight);
  expect(expandedHeight).toBeGreaterThan(initialHeight);

  await panel.getByRole('columnheader', { name: 'Assign every unresolved genome to fungi' }).click();
  const row = panel.locator('.taxon-assignment-row').first();
  await expect(row.locator('input[value="fungi"]')).toBeChecked();
  await expect(panel.locator('#taxon-assignment-status')).toHaveText('0 unresolved');
});
