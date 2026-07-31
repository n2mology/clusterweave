const { test, expect } = require('@playwright/test');

const baseUrl = 'http://127.0.0.1:4173/';

test('public resource guidance and canonical CPU fields use the server limit', async ({ page }) => {
  const consoleErrors = [];
  const failedRequests = [];
  const failedResponses = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', error => consoleErrors.push(error.message));
  page.on('requestfailed', request => failedRequests.push(request.url()));
  page.on('response', response => {
    if (response.url().startsWith(baseUrl) && response.status() >= 400) {
      failedResponses.push(`${response.status()} ${response.url()}`);
    }
  });
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
      smtp_enabled: false,
      public_quota: {
        max_accessions: 7,
        max_genome_files: 9,
        max_upload_file_mb: 11,
        max_upload_total_mb: 13,
        max_cpus_per_job: 3,
      },
    }),
  }));

  await page.goto(baseUrl);
  await expect(page.locator('#bootstrap-splash')).toBeHidden();
  const note = page.locator('#upload-limit-note');
  await expect(note).toHaveAttribute('role', 'note');
  await expect(note).not.toContainText('hosted runs use up to');
  await expect(page.locator('#cpus')).toHaveValue('3');
  await expect(page.locator('#anno-cpus')).toHaveValue('3');
  expect(await page.evaluate(() => effectiveCpuCount())).toBe(3);
  expect(await page.evaluate(() => reducedMotionPreferred())).toBe(true);

  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: width === 1280 ? 900 : 844 });
    const geometry = await note.evaluate(node => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return {
        display: style.display,
        fontSize: style.fontSize,
        lineHeight: style.lineHeight,
        left: rect.left,
        right: rect.right,
        width: rect.width,
        scrollWidth: node.scrollWidth,
        clientWidth: node.clientWidth,
      };
    });
    expect(geometry.display).toBe('block');
    expect(geometry.fontSize).toBe('10.24px');
    expect(geometry.lineHeight).toBe('13.1072px');
    expect(geometry.left).toBeGreaterThanOrEqual(-1);
    expect(geometry.right).toBeLessThanOrEqual(width + 1);
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth + 1);
    expect(geometry.width).toBeGreaterThan(0);
  }

  const faq = note.getByRole('link', { name: 'FAQ / local workflow' });
  await faq.focus();
  await expect(faq).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(faq).not.toBeFocused();
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(failedResponses).toEqual([]);
});

test('configured 75-input quotas hydrate every browser intake path', async ({ page }) => {
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
      smtp_enabled: false,
      public_quota: {
        max_accessions: 75,
        max_genome_files: 75,
        max_upload_file_mb: 500,
        max_upload_total_mb: 1024,
        max_cpus_per_job: 4,
      },
    }),
  }));

  await page.goto(baseUrl);
  await expect(page.locator('#bootstrap-splash')).toBeHidden();
  const note = page.locator('#upload-limit-note');
  await expect(note).toContainText('75 genome files');
  await expect(note).toContainText('75 NCBI accessions');
  const rows = page.locator('.brutal-accession-line');
  await expect(rows).toHaveCount(75);
  await expect(page.locator('#brutal-accession-rows')).not.toHaveAttribute('data-max-accessions', /.+/);

  const accessions = Array.from(
    { length: 51 },
    (_, index) => `GCF_${String(300000001 + index).padStart(9, '0')}.1`,
  );
  const lifecycle = await page.evaluate((values) => {
    const manual = document.getElementById('manual-accessions');
    manual.value = values.join('\n');
    normalizeManualAccessions();
    const entered = manualAccessionLines();
    resetBrutalAccessionDrafts();
    syncBrutalRowsFromAccepted();
    const afterReset = manualAccessionLines();
    removeBrutalAccession(0);
    const afterRemoval = manualAccessionLines();
    return {
      enteredCount: entered.length,
      entered51: entered.includes(values[50]),
      reset51: afterReset.includes(values[50]),
      removal51: afterRemoval.includes(values[50]),
      rowFifty: document.querySelector('[data-accession-index="49"] textarea')?.value || '',
    };
  }, accessions);
  expect(lifecycle.enteredCount).toBe(51);
  expect(lifecycle.entered51).toBe(true);
  expect(lifecycle.reset51).toBe(true);
  expect(lifecycle.removal51).toBe(true);
  expect(lifecycle.rowFifty).toBe(accessions[50]);
  await expect(rows).toHaveCount(75);

  const importResult = await page.evaluate(async (values) => {
    clearAcceptedAccessions();
    const overLimitValues = [...values, ...Array.from({ length: 25 }, (_, index) => `GCF_${String(400000001 + index).padStart(9, '0')}.1`)];
    const rejected = await addAccessionFileSource(
      new File([overLimitValues.join('\n')], 'over-limit-accessions.txt', { type: 'text/plain' }),
    );
    const afterRejected = manualAccessionLines();
    const imported = await addAccessionFileSource(
      new File([values.join('\n')], 'configured-accessions.txt', { type: 'text/plain' }),
    );
    const afterImported = manualAccessionLines();
    return {
      rejected,
      afterRejected: afterRejected.length,
      imported,
      importedCount: afterImported.length,
      imported51: afterImported.includes(values[50]),
    };
  }, accessions);
  expect(importResult.rejected).toBe(false);
  expect(importResult.afterRejected).toBe(0);
  expect(importResult.imported).toBe(true);
  expect(importResult.importedCount).toBe(51);
  expect(importResult.imported51).toBe(true);

  const fileQuota = await page.evaluate(async () => {
    clearAcceptedAccessions();
    const files = Array.from(
      { length: 76 },
      (_, index) => new File([`>seq${index}\nATGC\n`], `configured_upload_${index}.fna`, { type: 'text/plain' }),
    );
    await addFiles(files);
    const checker = renderInputChecker();
    return { selected: intakeControllerState.selectedFiles.length, blocked: checker.blocked };
  });
  expect(fileQuota.selected).toBe(76);
  expect(fileQuota.blocked).toBeGreaterThan(0);
  await expect(page.locator('#input-checker-list')).toContainText('at most 75 genome files');
});
