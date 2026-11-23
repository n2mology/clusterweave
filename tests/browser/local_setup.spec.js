const { test, expect } = require('@playwright/test');

for (const local of [false, true]) {
  test(`compact local setup respects ${local ? 'local' : 'hosted'} access`, async ({ page }, testInfo) => {
    await page.route('**/api/system/status*', route => route.fulfill({
      contentType: 'application/json', body: JSON.stringify(local ? {
        ready: true, worker: {}, capabilities: {}, online: true,
        local_setup: {url:'http://127.0.0.1:8092/', worker_cpus:3, job_cpus:2, worker_memory_gib:20,
          cache_enabled:false, cache_max_bytes:2147483648, cache_max_entries:16, cache_max_age_seconds:604800,
          automatic_startup:true, open_browser:false, job_retention:'Until manual deletion'},
      } : { online:true, submissions_open:true }),
    }));
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:4173/');
    await expect(page.locator('#bootstrap-splash')).toBeHidden();
    const guide = page.locator('#local-setup-guide');
    const launch = page.getByRole('tab', {name:'Local setup', exact:true});
    await expect(guide).toBeHidden();
    if (!local) {
      await expect(launch).toBeHidden();
    } else {
      await page.locator('#ops-panel-toggle').click();
      await launch.click();
      await expect(guide).toBeVisible();
      await expect(guide).toHaveAttribute('role', 'tabpanel');
      await expect(page.locator('#local-setup-open')).toHaveCount(0);
      await expect(page.locator('#local-setup-cpus')).toHaveText('3');
      await expect(page.locator('#local-setup-memory')).toHaveText('20 GiB');
      await expect(page.locator('#local-setup-url')).toHaveText('http://127.0.0.1:8092/');
      await expect(page.locator('#local-setup-cache')).toContainText('Off: 2 GiB / 16 entries / 7 days');
      await expect(page.locator('#local-setup-startup')).toContainText('After Docker starts: automatic');
      await expect(guide).toContainText('./bin/local_instance.sh scan');
      await expect(guide).toContainText('--reconfigure');
      await expect(guide.locator('input, select, textarea')).toHaveCount(0);
      for (const width of [1280, 390]) {
        await page.setViewportSize({width, height:844});
        expect(await guide.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
        await guide.getByRole('link', {name:'Setup and recovery instructions'}).scrollIntoViewIfNeeded();
        await expect(guide.getByRole('link', {name:'Setup and recovery instructions'})).toBeInViewport();
        await guide.screenshot({path:testInfo.outputPath(`local-setup-${width}.png`), animations:'disabled'});
      }
      await page.keyboard.press('Escape');
      await expect(page.locator('#ops-side-panel')).toHaveAttribute('aria-hidden', 'true');
      await expect(page.locator('#ops-panel-toggle')).toBeFocused();
      await page.locator('#ops-panel-toggle').press('Enter');
      await launch.press('Enter');
      await expect(guide).toBeVisible();
      await page.getByRole('button', {name:'Close diagnostics', exact:true}).click();
      await expect(page.locator('#ops-side-panel')).toHaveAttribute('aria-hidden', 'true');
      await page.evaluate(() => { document.body.dataset.jobState = 'running'; });
      await page.locator('#ops-panel-toggle').click();
      await expect(launch).toBeVisible();
      await launch.click();
      await expect(guide).toBeVisible();
      await launch.press('Home');
      await expect(page.getByRole('tab', {name:'Jobs', exact:true})).toBeFocused();
      await page.keyboard.press('End');
      await expect(launch).toBeFocused();
      await expect(guide).toBeVisible();
    }
    expect(errors).toEqual([]);
  });
}


test('initialization shows runtime preparation and failures before worker readiness', async ({ page }) => {
  let state = {ready:false, state:'bootstrapping', phase:'funannotate_image', progress:35,
    detail:'Preparing funannotate image', substep:'Building image', capabilities:{}};
  await page.route('**/api/system/status*', route => route.fulfill({contentType:'application/json', body:JSON.stringify(state)}));
  await page.goto('http://127.0.0.1:4173/');
  await expect(page.locator('#bootstrap-splash')).toBeVisible();
  await expect(page.locator('#bootstrap-phase-label')).toHaveText('Preparing funannotate image');
  await expect(page.locator('#bootstrap-steps .running')).toContainText('funannotate image');
  state = {...state, state:'error', phase:'error', detail:'Preparation stopped. Check the terminal, then run ./bin/local_instance.sh weave again.'};
  await expect(page.locator('#bootstrap-status')).toContainText('Preparation stopped');
  await expect(page.locator('#bootstrap-steps .done')).toHaveCount(0);
  await expect(page.locator('#bootstrap-splash')).toBeVisible();
  state = {...state, state:'ready', phase:'ready', ready:true};
  await expect(page.locator('#bootstrap-splash')).toBeHidden();
});
