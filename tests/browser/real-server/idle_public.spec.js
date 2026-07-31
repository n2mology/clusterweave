const { test, expect } = require('@playwright/test');

const baseURL = 'http://127.0.0.1:4174';

test('real server initializes the empty public interface from live status', async ({ page }) => {
  const pageErrors = [];
  const failedResponses = [];
  const failedRequests = [];

  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('requestfailed', request => {
    if (new URL(request.url()).origin === baseURL) {
      failedRequests.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText || 'failed'}`);
    }
  });
  page.on('response', response => {
    if (new URL(response.url()).origin === baseURL && response.status() >= 400) {
      failedResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  const statusResponsePromise = page.waitForResponse(
    response => response.url() === `${baseURL}/api/system/status`
      && response.request().resourceType() === 'fetch'
  );
  const documentResponse = await page.goto('/');
  const statusResponse = await statusResponsePromise;

  expect(documentResponse).not.toBeNull();
  expect(documentResponse.status()).toBe(200);
  expect(await documentResponse.headerValue('cache-control')).toBe('no-store');
  expect(statusResponse.status()).toBe(200);
  expect(await statusResponse.headerValue('content-type')).toContain('application/json');

  const status = await statusResponse.json();
  expect(status).toMatchObject({
    online: true,
    service: 'online',
    submissions_open: false,
    submissions: 'paused',
    jobs_processed: 0,
    running_jobs: 0,
    queued_jobs: 0,
    smtp_enabled: false,
  });
  expect(status.public_quota).toMatchObject({
    max_accessions: expect.any(Number),
    max_genome_files: expect.any(Number),
    max_upload_file_mb: expect.any(Number),
    max_upload_total_mb: expect.any(Number),
  });
  expect(status).not.toHaveProperty('worker');
  expect(status).not.toHaveProperty('runtime');
  expect(status).not.toHaveProperty('capabilities');

  await expect(page.locator('#bootstrap-splash')).toHaveClass(/hidden/);
  await expect(page.locator('body')).toHaveAttribute('data-access', 'public');
  await expect(page.locator('body')).toHaveAttribute('data-workflow-state', 'idle');
  await expect(page.locator('body')).toHaveAttribute('data-job-state', 'idle');
  await expect(page.locator('#runtime-status-chip')).toContainText('Runtime: Submissions paused');
  await expect(page.locator('#runtime-server-status')).toHaveText('online');
  await expect(page.locator('#runtime-submissions-status')).toHaveText('paused');
  await expect(page.locator('#runtime-jobs-processed')).toHaveText('0');
  await expect(page.locator('#public-impact-server')).toHaveText('online');
  await expect(page.locator('#public-impact-running')).toHaveText('0');
  await expect(page.locator('#public-impact-queued')).toHaveText('0');
  await expect(page.locator('#public-impact-completed')).toHaveText('0');

  await page.waitForTimeout(250);
  expect(pageErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(failedResponses).toEqual([]);
});
