const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const baseline = process.env.CLUSTERWEAVE_LAYOUT_BASELINE === '1';
const evidence = process.env.CLUSTERWEAVE_LAYOUT_EVIDENCE;
test.beforeEach(async ({ page }) => {
  const source = process.env.CLUSTERWEAVE_LAYOUT_SOURCE;
  if (!source) return;
  for (const name of ['progress-tree.js', 'progress-tree.css']) {
    await page.route(`**/assets/${name}`, route => route.fulfill({status:200,
      contentType:name.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(path.join(source,name),'utf8')}));
  }
});
for (const width of [1440, 390]) {
  test(`progress layout and asynchronous identity at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto('http://127.0.0.1:4173/assets/progress-tree-contract.json');
    await page.setContent('<link rel="stylesheet" href="/assets/progress-tree.css"><style>body{margin:8px}#log-terminal{font:13px monospace;background:#15232b;padding:12px;box-sizing:border-box;width:100%}</style><div id="log-terminal" class="log-terminal"></div>');
    await page.evaluate(async () => {
      const module = await import('/assets/progress-tree.js');
      const contract = await (await fetch('/assets/progress-tree-contract.json')).json();
      globalThis.consoleView = module.createProgressTreeConsole({documentImpl:document,contract,createRawLineElement:text=>Object.assign(document.createElement('div'),{textContent:text})});
      globalThis.names = ['Short','Populus_trichocarpa_Nisqually_1_with_a_representative_very_long_readable_genome_name'];
      globalThis.progress = (g,p,m) => `GENOME_PROGRESS genome=${g} stage=annotation percent=${p} bar=[----------] message="${m}"`;
      consoleView.hydrate({jobId:'layout',logGeneration:'1',start:0,lines:['[INFO] Stage 1/4: running run_annotation_and_detection.sh','Reading native annotations',...names.map(n=>progress(n,0,'Queued genome'))]});
    });
    const geometry = () => page.locator('[data-tree-key]').evaluateAll(rows => rows.map(r=>({key:r.dataset.treeKey,x:r.querySelector('.progress-tree-meter').getBoundingClientRect().x,y:r.getBoundingClientRect().y,width:r.getBoundingClientRect().width,label:r.querySelector('.progress-tree-label').textContent})));
    const before = await geometry();
    await page.evaluate(() => {
      globalThis.originalRow = document.querySelector('[data-tree-key="genome:annotation:Short"]');
      consoleView.append({start:7,lines:[progress(names[0],40,'Detection active')]});
      consoleView.append({start:4,lines:[progress(names[1],1,'Validating supplied plant CDS annotations'),`ANTISMASH_RECORD_PROGRESS genome=${names[0]} record=r2 ordinal=2/3 percent=33 bar=[###-------] message="Starting antiSMASH record shard"`,`ANTISMASH_RECORD_PROGRESS genome=${names[0]} record=r2 ordinal=2/3 percent=66 bar=[######----] message="antiSMASH record shard complete"`]});
    });
    const after = await geometry();
    if (!baseline) await expect(page.locator('[data-tree-key]').filter({hasText:'Validating supplied plant CDS annotations'})).toHaveCount(1);
    expect(await page.evaluate(()=>document.querySelector('[data-tree-key="genome:annotation:Short"]')===originalRow)).toBe(true);
    await expect(page.locator('[data-tree-key="genome:annotation:Short"]')).toContainText('46%');
    const meters = after.filter(r=>r.key.startsWith('genome:'));
    const activityBefore = before.find(r=>r.key==='activity:annotation');
    const activityAfter = after.find(r=>r.key==='activity:annotation');
    if (evidence) {
      fs.mkdirSync(evidence,{recursive:true});
      fs.writeFileSync(path.join(evidence,`geometry-${width}.json`),JSON.stringify({before,after},null,2));
      await page.screenshot({path:path.join(evidence,`layout-${width}.png`),fullPage:true});
    }
    if (!baseline) {
      expect(Math.max(...meters.map(r=>r.x))-Math.min(...meters.map(r=>r.x))).toBeLessThan(1);
      expect(activityAfter.y).toBe(activityBefore.y);
      expect(await page.locator('#log-terminal').evaluate(e=>e.scrollWidth-e.clientWidth)).toBeLessThanOrEqual(1);
      await expect(page.locator('[data-tree-key="tool:annotation:Short:antiSMASH"]')).toContainText('46%');
    }
    await page.evaluate(()=>consoleView.append({start:8,lines:[progress(names[0],100,'Complete')]}));
    await expect(page.locator('[data-tree-key="genome:annotation:Short"]')).toHaveAttribute('data-tree-state','complete');
    await page.evaluate(()=>consoleView.append({jobId:'foreign',start:9,lines:[progress(names[0],1,'stale')]}));
    await expect(page.locator('[data-tree-key="genome:annotation:Short"]')).toHaveAttribute('data-tree-state','complete');
  });
}

test('retained production progress replay preserves separate genome updates', async ({page}) => {
  const file = process.env.CLUSTERWEAVE_RETAINED_PROGRESS;
  test.skip(!file, 'Private retained run supplied by repair validation');
  const events = JSON.parse(fs.readFileSync(file,'utf8'));
  await page.goto('http://127.0.0.1:4173/assets/progress-tree-contract.json');
  const result = await page.evaluate(async events => {
    const {buildProgressTree} = await import('/assets/progress-tree.js');
    const contract = await (await fetch('/assets/progress-tree-contract.json')).json();
    const early = events.filter(e=>e.index<180);
    return {early:buildProgressTree(contract,early),final:buildProgressTree(contract,events)};
  },events);
  expect(result.early.rows.filter(r=>r.level==='genome').length).toBeGreaterThanOrEqual(3);
  if(evidence) {
    fs.mkdirSync(evidence,{recursive:true});
    fs.writeFileSync(path.join(evidence,'retained-replay.json'),JSON.stringify(result,null,2));
    await page.setContent('<link rel="stylesheet" href="/assets/progress-tree.css"><style>body{margin:8px}#log-terminal{font:13px monospace;background:#15232b;padding:12px;box-sizing:border-box;width:100%}</style><div id="log-terminal" class="log-terminal"></div>');
    await page.evaluate(async events => {
      const {createProgressTreeConsole}=await import('/assets/progress-tree.js');
      const contract=await(await fetch('/assets/progress-tree-contract.json')).json();
      const consoleView=createProgressTreeConsole({documentImpl:document,contract,createRawLineElement:text=>Object.assign(document.createElement('div'),{textContent:text})});
      consoleView.hydrate({jobId:'retained',logGeneration:'original',start:0,lines:events.filter(e=>e.index<180).map(e=>e.line)});
    },events);
    for(const width of [1440,390]) {
      await page.setViewportSize({width,height:1000});
      await page.screenshot({path:path.join(evidence,`retained-${width}.png`),fullPage:true});
    }
  }
});
