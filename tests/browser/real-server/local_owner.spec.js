const { test, expect } = require('@playwright/test');

const baseURL = 'http://127.0.0.1:4177';

test('fresh local browser opens retained jobs and remembers access across tabs and contexts', async ({ browser, page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(baseURL);
  await expect(page.locator('body')).toHaveAttribute('data-access', 'local');
  await expect(page.locator('#bootstrap-splash')).toBeHidden();
  await expect(page.locator('#local-setup-guide')).toBeHidden();
  await page.locator('#ops-panel-toggle').click();
  await page.getByRole('tab', {name:'Local setup', exact:true}).click();
  await expect(page.locator('#local-setup-guide')).toBeVisible();
  await expect(page.locator('#local-setup-readiness')).toContainText('Worker ready');
  await expect(page.locator('#local-setup-choices')).toContainText('http://127.0.0.1:4177/');
  await expect(page.locator('#local-setup-cache')).toContainText('10 GiB / 256 entries / 30 days');
  await expect(page.locator('#local-setup-guide')).toContainText('disable-autostart');
  const setupResponse = await page.request.get(`${baseURL}/api/system/status`);
  expect((await setupResponse.json()).local_setup.cache_enabled).toBe(true);
  await page.getByRole('button', {name:'Close diagnostics', exact:true}).click();
  await expect(page.locator('#ops-side-panel')).toHaveAttribute('aria-hidden', 'true');
  await page.locator('#entry-tab-existing').click();
  await expect(page.locator('#local-jobs-panel')).toBeVisible();
  await expect(page.locator('#local-jobs-select option')).toHaveCount(4);
  await page.locator('#local-jobs-select').selectOption('r01edone');
  await expect(page.locator('body')).toHaveAttribute('data-existing-run-loaded', 'true');
  await expect.poll(() => page.evaluate(() => activeJobMeta?.id)).toBe('r01edone');
  const cookies = await page.context().cookies(baseURL);
  const owner = cookies.find(cookie => cookie.name === 'clusterweave_local_owner');
  expect(owner.httpOnly).toBe(true);
  expect(owner.sameSite).toBe('Strict');
  expect(owner.expires).toBeGreaterThan(Date.now() / 1000 + 86400);
  expect(await page.evaluate(() => document.cookie)).not.toContain('clusterweave_local_owner');
  expect(await page.evaluate(() => sessionStorage.getItem('clusterweave.adminToken'))).toBeNull();
  const tab = await page.context().newPage();
  await tab.goto(baseURL);
  await expect(tab.locator('body')).toHaveAttribute('data-access', 'local');
  const context = await browser.newContext({ storageState: await page.context().storageState() });
  try {
    const reopened = await context.newPage();
    await reopened.goto(baseURL);
    await expect(reopened.locator('body')).toHaveAttribute('data-access', 'local');
    const response = await reopened.request.get(`${baseURL}/api/jobs`);
    expect(response.status()).toBe(200);
    expect((await response.json()).length).toBe(3);
    await reopened.locator('#entry-tab-existing').click();
    await expect(reopened.locator('#local-jobs-panel')).toBeVisible();
    await reopened.getByRole('button', { name: 'Forget browser access' }).click();
    await expect(reopened.locator('#local-jobs-panel')).toBeHidden();
    expect((await reopened.request.get(`${baseURL}/api/jobs`)).status()).toBe(401);
  } finally {
    await context.close();
  }
  expect(errors).toEqual([]);
});
