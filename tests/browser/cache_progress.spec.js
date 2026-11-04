const {test, expect} = require('@playwright/test');
for (const width of [1100, 360]) {
  test(`cache progress chips explain genome completion at ${width}px`, async ({page}, testInfo) => {
    await page.setViewportSize({width, height: 700});
    await page.goto('http://127.0.0.1:4173/assets/progress-tree-contract.json');
    await page.setContent('<link rel="stylesheet" href="/assets/clusterweave.css"><div class="genome-progress-grid" style="width:280px;height:400px" id="cards"></div><div id="tree"></div>');
    await page.evaluate(async () => {
      const {createJobLifecycleBoundary} = await import('/assets/job-lifecycle-boundary.js');
      const {buildProgressTree,progressTreeStatus} = await import('/assets/progress-tree.js');
      const contract = await (await fetch('/assets/progress-tree-contract.json')).json();
      const boundary = createJobLifecycleBoundary({escapeHtml:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),getActiveJobId:()=> 'fixture',getCurrentJobSequence:()=>1,documentImpl:document,stages:[]});
      const items = [
        {genome_id:'Cached',taxon_group:'bacteria',percent:100,status:'complete',progress_status:'cached',progress_label:'CACHED',progress_detail:contract.progress_statuses.cached.detail},
        {genome_id:'Fresh',taxon_group:'bacteria',percent:8,status:'queued',stage:'download',progress_label:'GENOME DOWNLOADED',progress_detail:contract.progress_statuses.genome_downloaded.detail},
        {genome_id:'Input',taxon_group:'fungi',percent:8,status:'queued',stage:'download',progress_label:'GENOME READY',progress_detail:contract.progress_statuses.genome_ready.detail},
      ];
      document.getElementById('cards').innerHTML = boundary.normalizeGenomeProgressItems({id:'fixture',genome_progress:items}).map(boundary.renderGenomeProgressCard).join('');
      const lines = ['ACCESSION_CACHE genome=Cached stage=annotation_detection outcome=hit','GENOME_PROGRESS genome=Cached stage=annotation percent=100 bar=[##########] message="Reused verified annotation and BGC detection"','Stage 2/4: running run_bigscape.sh'];
      const tree=buildProgressTree(contract,lines.map((line,index)=>({line,index})));
      document.getElementById('tree').textContent=tree.rows.map(row=>`${row.label}: ${progressTreeStatus(row)}`).join('\n');
    });
    await expect(page.locator('.genome-progress-chip')).toHaveText(['CACHED','GENOME DOWNLOADED','GENOME READY']);
    await expect(page.locator('[data-genome-progress-id="Cached"]')).toHaveAttribute('aria-label', /CACHED/);
    await expect(page.locator('#tree')).toContainText('100% - CACHED');
    await expect(page.locator('#tree')).toContainText('BiG-SCAPE: [          ]  --% - Running');
    expect(await page.locator('#cards').evaluate(node => node.scrollWidth <= node.clientWidth)).toBeTruthy();
    for (const row of await page.locator('.genome-progress-row').all()) {
      expect(await row.evaluate(node=>node.scrollHeight <= node.clientHeight)).toBeTruthy();
    }
    await page.screenshot({path:testInfo.outputPath(`cache-progress-${width}.png`),animations:'disabled'});
  });
}
