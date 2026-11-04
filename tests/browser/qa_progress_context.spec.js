const { test, expect } = require('@playwright/test');
const baseUrl = 'http://127.0.0.1:4173';

test('marker-free QA pages retain stage context across appends, pagination and generations', async ({ page }) => {
  await page.goto(`${baseUrl}/assets/progress-tree-contract.json`);
  await page.setContent('<div id="log-terminal"></div><button data-qa-log-view="tree"></button><button data-qa-log-view="raw"></button>');
  await page.evaluate(async () => {
    const module = await import('/assets/progress-tree.js');
    const contract = await (await fetch('/assets/progress-tree-contract.json')).json();
    globalThis.qaConsole = module.createProgressTreeConsole({ documentImpl: document, contract,
      createRawLineElement: text => { const node = document.createElement('div'); node.className = 'log-line'; node.textContent = text; return node; } });
    globalThis.qaClassify = line => module.classifyProgressTreeLine(contract, line, 0);
    qaConsole.hydrate({jobId: 'first', logGeneration: 'one', start: 4500,
      lines: Array.from({length: 500}, (_, i) => `distance ${i}`),
      context: [{index: 4, line: '[INFO] Stage 1/4: complete'}, {index: 5, line: '[INFO] Stage 2/4: running run_bigscape.sh'}]});
  });
  const bigscape = page.locator('[data-tree-key="stage:bigscape"]');
  await expect(bigscape).toHaveAttribute('data-tree-state', 'running');
  await expect(page.locator('[data-tree-key="stage:annotation"]')).toHaveAttribute('data-tree-state', 'complete');
  await expect(bigscape).toContainText('--%');
  await page.evaluate(() => qaConsole.append({jobId: 'first', logGeneration: 'one', start: 5000, lines: ['more distances']}));
  await expect(page.locator('[data-tree-key="activity:bigscape"]')).toContainText('more distances');
  await page.evaluate(() => qaConsole.hydrate({jobId: 'first', logGeneration: 'one', start: 4000, prepend: true,
    lines: Array.from({length: 500}, (_, i) => `earlier distance ${i}`),
    context: [{index: 4, line: '[INFO] Stage 1/4: complete'}, {index: 5, line: '[INFO] Stage 2/4: running run_bigscape.sh'}]}));
  await expect(bigscape).toHaveAttribute('data-tree-state', 'running');
  await page.evaluate(() => qaConsole.append({jobId: 'first', logGeneration: 'one', start: 5001,
    lines: ['[INFO] Stage 2/4: complete', '[INFO] Stage 2/4: running run_bigscape.sh', 'distance batch 2']}));
  await expect(bigscape).toHaveAttribute('data-tree-state', 'running');
  await expect(bigscape).toContainText('--%');
  await expect(page.locator('[data-tree-key="activity:bigscape"]')).toContainText('distance batch 2');
  await page.evaluate(() => qaConsole.setMode('raw'));
  await expect(page.locator('.log-line')).toHaveCount(1004);
  await expect(page.locator('.log-line').first()).toHaveText('earlier distance 0');
  expect(await page.evaluate(() => qaConsole.canonicalRecords()[0].index)).toBe(4000);
  await page.evaluate(() => {
    qaConsole.setMode('tree');
    qaConsole.hydrate({jobId: 'first', logGeneration: 'rerun', start: 700, lines: ['GENOME_PROGRESS genome=Public stage=annotation percent=100 bar=[##########] message="Cached annotation/detection complete"'],
      context: [{index: 1, line: '[INFO] Stage 1/4: running rerun'}]});
    qaConsole.append({jobId: 'first', logGeneration: 'one', start: 5001, lines: ['[ERROR] stale request']});
  });
  await expect(bigscape).toHaveAttribute('data-tree-state', 'waiting');
  await expect(page.locator('[data-tree-key="genome:annotation:Public"]')).toHaveAttribute('data-tree-state', 'complete');
  expect(await page.evaluate(() => qaConsole.canonicalRecords().length)).toBe(1);
  await page.evaluate(() => {
    qaConsole.hydrate({jobId: 'second', logGeneration: 'another', start: 50, stage: 'clinker', lines: ['aligning loci']});
    qaConsole.append({jobId: 'first', logGeneration: 'rerun', start: 701, lines: ['[ERROR] foreign job']});
  });
  await expect(page.locator('[data-tree-key="stage:clinker"]')).toHaveAttribute('data-tree-state', 'running');
  await expect(page.locator('[data-tree-key="stage:annotation"]')).toHaveAttribute('data-tree-state', 'waiting');
  await expect(page.locator('[data-tree-state="failed"]')).toHaveCount(0);
  await page.evaluate(() => qaConsole.reset());
  expect(await page.evaluate(() => qaConsole.canonicalRecords().length)).toBe(0);
});

test('structured zero failures preserve success and genuine errors remain visible', async ({ page }) => {
  await page.goto(`${baseUrl}/assets/progress-tree-contract.json`);
  const states = await page.evaluate(async () => {
    const { classifyProgressTreeLine } = await import('/assets/progress-tree.js');
    const contract = await (await fetch('/assets/progress-tree-contract.json')).json();
    return [
      'NCBI_DOWNLOAD_SUMMARY requested=3 downloaded=3 failed=0',
      'NCBI_DOWNLOAD_SUMMARY requested=3 downloaded=2 failed=1',
      '[ERROR] NCBI_DOWNLOAD_SUMMARY failed=0: connection failed',
      '[ERROR] genuine failure',
    ].map(line => classifyProgressTreeLine(contract, line, 10).state);
  });
  expect(states[0]).not.toBe('failed');
  expect(states.slice(1)).toEqual(['failed', 'failed', 'failed']);
});

for (const mode of ['raw', 'tree']) {
  test(`QA ${mode} polling holds a reader's position and resumes following at the bottom`, async ({ page }) => {
    await page.goto(`${baseUrl}/assets/progress-tree-contract.json`);
    await page.setContent('<style>#log-terminal{height:180px;overflow:auto;overflow-anchor:none}.log-line,[data-tree-key]{min-height:24px}</style><div id="log-terminal"></div>');
    await page.evaluate(async mode => {
      const { createProgressTreeConsole } = await import('/assets/progress-tree.js');
      const contract = await (await fetch('/assets/progress-tree-contract.json')).json();
      globalThis.qaConsole = createProgressTreeConsole({documentImpl: document, contract,
        createRawLineElement: text => { const node = document.createElement('div'); node.className = 'log-line'; node.textContent = text; return node; }});
      globalThis.progressLine = i => `GENOME_PROGRESS genome=fixture${i} stage=annotation percent=20 bar=[##--------] message="working"`;
      qaConsole.hydrate({jobId: 'scroll', logGeneration: 'one', start: 0, autoScroll: true,
        lines: Array.from({length: 80}, (_, i) => progressLine(i))});
      qaConsole.setMode(mode);
      document.getElementById('log-terminal').scrollTop = 100;
    }, mode);
    const top = () => page.locator('#log-terminal').evaluate(term => term.scrollTop);
    await page.evaluate(() => {
      qaConsole.append({start: 80, lines: [], autoScroll: true});
      qaConsole.append({start: 80, lines: [progressLine(80)], autoScroll: true});
      qaConsole.append({start: 81, lines: [progressLine(81)], autoScroll: true});
    });
    expect(await top()).toBe(100);
    await page.evaluate(() => {
      const term = document.getElementById('log-terminal');
      term.scrollTop = term.scrollHeight;
      qaConsole.append({start: 82, lines: [progressLine(82)], autoScroll: true});
    });
    expect(await page.locator('#log-terminal').evaluate(term => term.scrollHeight - term.clientHeight - term.scrollTop)).toBeLessThanOrEqual(1);
    if (mode === 'raw') {
      const previous = await page.locator('#log-terminal').evaluate(term => {term.scrollTop = 100; return {top: term.scrollTop, height: term.scrollHeight};});
      await page.evaluate(() => qaConsole.hydrate({jobId: 'scroll', logGeneration: 'one', start: 0, prepend: true, lines: ['earlier replacement']}));
      expect(await top()).toBe(previous.top);
    }
  });
}

test('zero dropped summaries are informational and real annotation warnings survive', async ({ page }) => {
  await page.goto(`${baseUrl}/assets/progress-tree-contract.json`);
  const states = await page.evaluate(async () => {
    const { classifyProgressTreeLine } = await import('/assets/progress-tree.js');
    const contract = await (await fetch('/assets/progress-tree-contract.json')).json();
    return ['[INFO] total=3 processed=3 dropped=0', '[INFO] total=3 processed=2 dropped=1',
      '[WARN] dropped=0 but annotation incomplete', '[ERROR] failed=0 dropped=0: genuine error',
      'Genome dropped: no usable annotation'].map(line => classifyProgressTreeLine(contract, line, 0, 'annotation').state);
  });
  expect(states).toEqual(['running', 'warning_terminal', 'warning', 'failed', 'warning_terminal']);
});
