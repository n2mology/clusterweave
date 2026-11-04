const {test, expect} = require('@playwright/test');

for (const width of [1100, 360]) {
  test(`excluded genome notice persists with results and clears for a new attempt at ${width}px`, async ({page}, testInfo) => {
    await page.setViewportSize({width, height: 800});
    await page.goto('http://127.0.0.1:4173/assets/progress-tree-contract.json');
    await page.evaluate(async () => {
      const html = await (await fetch('/')).text();
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      document.body.innerHTML = '<link rel="stylesheet" href="/assets/clusterweave.css">'
        + parsed.getElementById('workflow-progress-panel').outerHTML
        + parsed.getElementById('results-card').outerHTML;
      document.body.dataset.jobState = 'complete';
      document.body.dataset.resultsAvailable = 'true';
      const {createJobLifecycleBoundary, createJobLifecycleControllerBoundary} = await import('/assets/job-lifecycle-boundary.js');
      const policy = createJobLifecycleBoundary({stages: [], escapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;')});
      const controller = createJobLifecycleControllerBoundary({state: {}, lifecyclePolicy: policy, capabilities: {}, stages: []});
      const genomes = [
        {genome_id: 'Good', percent: 100, status: 'complete', message: 'Genome workflow complete'},
        {genome_id: 'Excluded', percent: 100, status: 'warning', message: 'Dropped: funannotate_busco_training_insufficient'},
      ];
      const render = (id, rerun, rows, state = 'complete') => {
        const items = policy.normalizeGenomeProgressItems({id, rerun_count: rerun, genome_progress: rows});
        controller.renderGenomeProgressLayer({state, genomes: items});
      };
      globalThis.exclusionFixture = {render, genomes};
      render('first', 0, genomes);
    });
    const notice = page.locator('#genome-exclusion-notice');
    await expect(page.locator('#workflow-progress-panel')).toBeHidden();
    await expect(notice).toBeVisible();
    await expect(notice).toHaveText('1 of 2 genomes excluded from BGC detection and downstream analysis. No usable annotation was produced for these genomes.');
    expect(await notice.evaluate(node => node.scrollWidth <= node.clientWidth)).toBeTruthy();
    await page.screenshot({path: testInfo.outputPath(`excluded-genomes-${width}.png`), animations: 'disabled'});
    await page.evaluate(() => exclusionFixture.render('first', 0, [exclusionFixture.genomes[0]], 'running'));
    await expect(notice).toBeVisible();
    await page.evaluate(() => exclusionFixture.render('first', 1, [{genome_id: 'Excluded', percent: 0, status: 'queued'}], 'running'));
    await expect(notice).toBeHidden();
    await page.evaluate(() => exclusionFixture.render('second', 0, [{genome_id: 'Warning', percent: 100, status: 'complete_with_warning', warning_message: 'Detector warning'}]));
    await expect(notice).toBeHidden();
    await page.evaluate(() => exclusionFixture.render('third', 0, []));
    await expect(notice).toBeHidden();
  });
}
