const {test, expect} = require('@playwright/test');

for (const [timezoneId, winterClock, summerClock] of [
  ['America/New_York', '1:45 AM EST', '2:45 AM EDT'],
  ['Asia/Kolkata', '12:15 PM GMT+5:30', '12:15 PM GMT+5:30'],
  ['Pacific/Auckland', '7:45 PM GMT+13', '6:45 PM GMT+12'],
]) {
  test.describe(timezoneId, () => {
    test.use({timezoneId, locale: 'en-US'});
    test('Jobs and QA interpret stored UTC and explicit offsets in the browser timezone', async ({page}) => {
      await page.route('**/api/system/status*', route => route.fulfill({json: {
        online: true, service: 'online', submissions_open: true,
      }}));
      await page.goto('http://127.0.0.1:4173/');
      await expect(page.locator('#bootstrap-splash')).toHaveClass(/hidden/);
      const render = async timestamp => page.evaluate(timestamp => {
        const job = {id: 'clock-fixture', project_name: 'Clock fixture', status: 'success',
          stage: 'complete', updated_at: timestamp, completed_at: timestamp};
        renderJobHistory([job]);
        renderQaDrawer(job, []);
      }, timestamp);
      for (const timestamp of ['2026-11-23T06:45:57.123456', '2026-11-23 06:45:57',
        '2026-11-23T06:45:57Z', '2026-11-23T12:15:57+05:30']) {
        await render(timestamp);
        await expect(page.locator('.diagnostic-job-line')).toContainText(`Nov 23, ${winterClock}`);
        await expect(page.locator('#qa-log-detail')).toHaveText(`Updated Nov 23, ${winterClock}.`);
      }
      await render('2026-07-23T06:45:57.123456');
      await expect(page.locator('.diagnostic-job-line')).toContainText(`Jul 23, ${summerClock}`);
      await expect(page.locator('#qa-log-detail')).toHaveText(`Updated Jul 23, ${summerClock}.`);
      await render('not-a-timestamp');
      await expect(page.locator('.diagnostic-job-line')).toContainText('updated unknown');
      await expect(page.locator('#qa-log-detail')).toHaveText('Updated No timestamp yet.');
      await page.evaluate(() => {
        const job = {id: 'clock-fallback', status: 'pending', created_at: '2026-11-23T06:45:57'};
        renderJobHistory([job]);
        renderQaDrawer(job, []);
      });
      await expect(page.locator('.diagnostic-job-line')).toContainText(`Nov 23, ${winterClock}`);
      await expect(page.locator('#qa-log-detail')).toHaveText(`Updated Nov 23, ${winterClock}.`);
    });
  });
}
