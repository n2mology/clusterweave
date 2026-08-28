const { test, expect } = require('@playwright/test');
const fs = require('node:fs');

const liveBaseUrl = String(process.env.CLUSTERWEAVE_LIVE_BASE_URL || '').replace(/\/$/, '');
const liveUiBaseUrl = String(process.env.CLUSTERWEAVE_LIVE_UI_BASE_URL || 'http://127.0.0.1:4173').replace(/\/$/, '');
const tokenFile = process.env.CLUSTERWEAVE_LIVE_TOKEN_FILE || '';
const manifestFile = process.env.CLUSTERWEAVE_LIVE_MANIFEST_FILE || '';
const publicRunId = process.env.CLUSTERWEAVE_LIVE_PUBLIC_RUN_ID || '';
const representativeOnly = process.env.CLUSTERWEAVE_LIVE_REPRESENTATIVE_ONLY === '1';
const requireBigscapeViewer = process.env.CLUSTERWEAVE_LIVE_REQUIRE_BIGSCAPE === '1';
const enabled = Boolean(liveBaseUrl && tokenFile && manifestFile && publicRunId);

function nestedReferencesByGenome(manifestText) {
  const anti = new Map();
  const funbgcex = new Map();
  for (const line of manifestText.split(/\r?\n/).slice(1)) {
    const path = line.split('\t', 1)[0] || '';
    let match = path.match(/\/antismash\/([^/]+)\/(.+\.html)$/i);
    if (match && match[2].toLowerCase() !== 'index.html' && !anti.has(match[1])) {
      anti.set(match[1], match[2]);
    }
    match = path.match(/\/funbgcex\/([^/]+)\/results\/[^/]+\.funbgcex_results\/(HTMLs\/BGC[0-9]+\.html)$/i);
    if (match && !funbgcex.has(match[1])) funbgcex.set(match[1], match[2]);
  }
  return { anti, funbgcex };
}

test('all signed tool-result root views and one nested detail per genome smoke cleanly', async ({ page }, testInfo) => {
  test.skip(!enabled, 'Live tool-result smoke requires explicit endpoint, token-file, manifest, and run-id settings.');
  test.setTimeout(30 * 60 * 1000);
  page.setDefaultTimeout(30 * 1000);

  const token = fs.readFileSync(tokenFile, 'utf8').trim();
  expect(token.length).toBeGreaterThan(20);
  const references = nestedReferencesByGenome(fs.readFileSync(manifestFile, 'utf8'));
  const catalogResponse = await fetch(`${liveBaseUrl}/api/results/${encodeURIComponent(publicRunId)}/artifacts`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(catalogResponse.ok).toBeTruthy();
  const catalog = await catalogResponse.json();
  expect(catalog.generation).toBeTruthy();
  if (requireBigscapeViewer) expect(catalog.bigscape_viewer_available).toBe(true);

  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  const sandboxNetworkRequests = [];
  const watchPage = candidate => {
    candidate.on('console', message => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    candidate.on('pageerror', error => pageErrors.push(String(error)));
    candidate.on('requestfailed', request => failedRequests.push(request.url()));
    candidate.on('request', request => {
      const url = request.url();
      if (candidate !== page && /^https?:/i.test(url) && !url.startsWith(liveBaseUrl)) {
        sandboxNetworkRequests.push(url);
      }
    });
  };
  watchPage(page);
  page.context().on('page', watchPage);

  await page.route('**/api/**', async route => {
    const source = new URL(route.request().url());
    if (source.pathname === '/api/system/status') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ online: true, submissions_open: true, jobs_processed: 1 }),
      });
      return;
    }
    if (source.pathname === '/api/jobs') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
      return;
    }
    if (!source.pathname.startsWith(`/api/results/${publicRunId}/`)) {
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
      return;
    }
    const target = `${liveBaseUrl}${source.pathname}${source.search}`;
    const headers = { ...route.request().headers(), Authorization: `Bearer ${token}` };
    delete headers.host;
    const response = await route.fetch({ url: target, headers });
    await route.fulfill({ response });
  });
  await page.goto(liveUiBaseUrl);
  await page.evaluate(({ runId, readToken, artifacts, bigscapeViewerAvailable }) => {
    accessMode = 'public';
    activeJobId = runId;
    activePublicRunId = runId;
    activeJobMeta = {
      id: runId,
      public_run_id: runId,
      status: 'success',
      bigscape_viewer_available: bigscapeViewerAvailable,
    };
    rememberOpenedRun(runId, readToken, activeJobMeta);
    const keys = installResultArtifactDescriptors(artifacts);
    window.__liveArtifactKeys = Object.fromEntries(keys.map(key => [resultArtifactId(key), key]));
  }, {
    runId: publicRunId,
    readToken: token,
    artifacts: catalog.artifacts,
    bigscapeViewerAvailable: catalog.bigscape_viewer_available === true,
  });

  const descriptors = catalog.artifacts;
  const antiRoots = descriptors.filter(item => item.category === 'antismash' && item.kind === 'html' && item.role === 'index');
  const funRoots = descriptors.filter(item => item.category === 'funbgcex' && item.kind === 'html' && item.filename === 'results.html');
  const clinkerRoots = descriptors.filter(item => item.category === 'synteny' && item.kind === 'html' && item.filename === 'panel.html');
  const bigscapeRoots = descriptors.filter(item => item.category === 'bigscape' && item.kind === 'html' && item.filename === 'index.html');
  expect({ anti: antiRoots.length, funbgcex: funRoots.length, clinker: clinkerRoots.length, bigscape: bigscapeRoots.length })
    .toEqual({ anti: 19, funbgcex: 19, clinker: 20, bigscape: 1 });
  expect(references.anti.size).toBe(19);
  expect(references.funbgcex.size).toBe(19);
  const canonicalFunViews = await page.evaluate(() => uniqueToolHtmlArtifacts(
    Object.values(window.__liveArtifactKeys),
    'funbgcex',
  ).map(item => resultArtifactDescriptor(item.path)?.filename));
  expect(canonicalFunViews).toHaveLength(19);
  expect(new Set(canonicalFunViews)).toEqual(new Set(['results.html']));

  async function openHtmlRoot(descriptor) {
    const popupPromise = page.waitForEvent('popup');
    await page.evaluate(({ runId, id }) => openHtmlResultWithAssets(
      null,
      runId,
      window.__liveArtifactKeys[id],
    ), { runId: publicRunId, id: descriptor.id });
    const popup = await popupPromise;
    const frameLocator = popup.locator('#clusterweave-tool-result-preview');
    await frameLocator.waitFor({ timeout: 60000 });
    await expect(frameLocator).toHaveAttribute('sandbox', 'allow-scripts allow-downloads');
    await expect.poll(() => popup.frames().length, { timeout: 60000 }).toBe(2);
    const frame = popup.frames()[1];
    await frame.waitForLoadState('domcontentloaded');
    expect(await popup.evaluate(() => window.opener)).toBeNull();
    expect(await frame.locator('html').textContent()).not.toContain(token);
    await popup.evaluate(() => {
      window.__clusterweaveClipboardWrites = [];
      window.__clusterweaveExternalOpens = [];
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: async value => { window.__clusterweaveClipboardWrites.push(String(value)); },
          readText: async () => window.__clusterweaveClipboardWrites.at(-1) || '',
        },
      });
      window.open = (url, target, features) => {
        window.__clusterweaveExternalOpens.push({ url: String(url), target, features });
        return null;
      };
    });
    return { popup, frame };
  }

  async function navigateSynthetic(bundle, reference, expectedTitle) {
    await bundle.frame.evaluate(value => {
      const link = document.createElement('a');
      link.id = 'clusterweave-live-nested-smoke';
      link.href = value;
      link.textContent = 'Nested result smoke';
      document.body.appendChild(link);
    }, reference);
    const link = bundle.frame.locator('#clusterweave-live-nested-smoke');
    await expect(link).toHaveAttribute('data-clusterweave-result-pending', '');
    await link.click({ force: true });
    await expect.poll(() => bundle.popup.title(), { timeout: 60000 }).toBe(expectedTitle);
    await expect(bundle.frame.locator('body')).not.toBeEmpty();
    expect(await bundle.frame.locator('html').textContent()).not.toContain(token);
  }

  const antiSmokeRoots = representativeOnly ? antiRoots.slice(0, 1) : antiRoots;
  const funSmokeRoots = representativeOnly ? funRoots.slice(0, 1) : funRoots;
  const clinkerSmokeRoots = representativeOnly ? clinkerRoots.slice(0, 1) : clinkerRoots;

  for (const [index, descriptor] of antiSmokeRoots.entries()) {
    const bundle = await openHtmlRoot(descriptor);
    const nested = references.anti.get(descriptor.genome_label);
    expect(nested, `antiSMASH nested reference for ${descriptor.genome_label}`).toBeTruthy();
    if (index === 0) {
      const regionControl = bundle.frame.locator('a[href="#r1c1"]').first();
      await regionControl.click();
      const region = bundle.frame.locator('#r1c1');
      await expect(region).toBeVisible();
      const gene = region.locator('.svgene-orf').first();
      await expect(gene).toBeVisible({ timeout: 60000 });
      await gene.click();
      const copy = bundle.frame.locator('.clipboard-copy[data-seq]').first();
      await expect(copy).toBeVisible({ timeout: 60000 });
      await copy.click();
      await expect.poll(() => bundle.popup.evaluate(() => window.__clusterweaveClipboardWrites.length)).toBe(1);
      await expect(bundle.frame.locator('[data-clusterweave-result-status]')).toHaveText('Sequence copied to the clipboard.');

      const svgDownloadPromise = bundle.popup.waitForEvent('download');
      await bundle.frame.locator('.download-svg:visible').first().click();
      expect((await svgDownloadPromise).suggestedFilename()).toMatch(/\.svg$/i);

      const gbk = bundle.frame.getByRole('link', { name: 'Download region GenBank file' });
      await expect(gbk).toBeVisible();
      await gbk.hover();
      await expect(gbk).toHaveAttribute('data-clusterweave-result-mode', 'download');
      const gbkDownloadPromise = bundle.popup.waitForEvent('download');
      await gbk.click();
      expect((await gbkDownloadPromise).suggestedFilename()).toMatch(/\.gbk$/i);

      const external = bundle.frame.getByRole('link', { name: /NCBI BlastP on this gene/i });
      await expect(external).toBeVisible();
      await expect(external).toHaveAttribute('data-clusterweave-result-external', /^https?:\/\//);
      await external.click();
      await expect.poll(() => bundle.popup.evaluate(() => window.__clusterweaveExternalOpens.length)).toBe(1);
      const opened = await bundle.popup.evaluate(() => window.__clusterweaveExternalOpens[0]);
      expect(opened.url).toMatch(/^https?:\/\//);
      expect(opened.target).toBe('_blank');
      expect(opened.features).toContain('noopener');
      expect(opened.features).toContain('noreferrer');
    }
    await navigateSynthetic(bundle, nested, nested.split('/').at(-1));
    await bundle.popup.close();
  }

  for (const [index, descriptor] of funSmokeRoots.entries()) {
    const bundle = await openHtmlRoot(descriptor);
    const nested = references.funbgcex.get(descriptor.genome_label);
    expect(nested, `FunBGCeX nested reference for ${descriptor.genome_label}`).toBeTruthy();
    await navigateSynthetic(bundle, nested, nested.split('/').at(-1));
    await expect(bundle.frame.locator('#canvas')).toBeVisible();
    const copy = bundle.frame.locator('[data-clusterweave-copy-source="#aaseq"]');
    await expect(copy).toHaveAttribute('aria-disabled', 'true');
    if (index === 0) {
      const canvas = bundle.frame.locator('#canvas');
      const bounds = await canvas.boundingBox();
      expect(bounds).toBeTruthy();
      for (let step = 1; step < 20; step += 1) {
        await canvas.click({ position: { x: bounds.width * step / 20, y: bounds.height / 2 } });
        if ((await bundle.frame.locator('#position').textContent()).trim()) break;
      }
      await expect.poll(async () => (await bundle.frame.locator('#position').textContent()).trim()).not.toBe('');
      await expect.poll(async () => (await bundle.frame.locator('#aaseq').textContent()).trim()).not.toBe('');
      await expect(copy).toHaveAttribute('aria-disabled', 'false');
      const aaSequence = (await bundle.frame.locator('#aaseq').textContent()).trim();
      await copy.click();
      await expect.poll(() => bundle.popup.evaluate(() => window.__clusterweaveClipboardWrites.at(-1) || '')).toBe(aaSequence);
      await expect(bundle.frame.locator('[data-clusterweave-result-status]')).toHaveText('Sequence copied to the clipboard.');

      const gbk = bundle.frame.getByRole('link', { name: /Download BGC GenBank file/i });
      await gbk.hover();
      await expect(gbk).toHaveAttribute('data-clusterweave-result-mode', 'download');
      const gbkDownloadPromise = bundle.popup.waitForEvent('download');
      await gbk.click();
      expect((await gbkDownloadPromise).suggestedFilename()).toMatch(/\.gbk$/i);

      const externalLinks = [
        bundle.frame.locator('a.funbgcs[data-clusterweave-result-external]').first(),
        bundle.frame.locator('#pfam a[data-clusterweave-result-external]').first(),
        bundle.frame.locator('#blast[data-clusterweave-result-external]'),
      ];
      for (const external of externalLinks) {
        await expect(external).toBeVisible();
        await external.click();
      }
      const opened = await bundle.popup.evaluate(() => window.__clusterweaveExternalOpens);
      expect(opened).toHaveLength(3);
      for (const item of opened) {
        expect(item.url).toMatch(/^https?:\/\//);
        expect(item.target).toBe('_blank');
        expect(item.features).toContain('noopener');
        expect(item.features).toContain('noreferrer');
      }
    }
    await bundle.popup.close();
  }

  for (const [index, descriptor] of clinkerSmokeRoots.entries()) {
    const popupPromise = page.waitForEvent('popup');
    await page.evaluate(({ runId, id }) => openHtmlResultWithAssets(
      null,
      runId,
      window.__liveArtifactKeys[id],
    ), { runId: publicRunId, id: descriptor.id });
    const popup = await popupPromise;
    const preview = popup.locator('#clusterweave-clinker-preview');
    await preview.waitFor({ timeout: 60000 });
    await expect(preview).toHaveAttribute('sandbox', 'allow-scripts allow-downloads');
    await expect.poll(() => popup.frames().length, { timeout: 60000 }).toBe(2);
    await expect(popup.frames()[1].locator('#btn-save-svg')).toBeVisible();
    expect(await popup.evaluate(() => window.opener)).toBeNull();
    if (index === 0) {
      for (const [selector, filename] of [
        ['#btn-save-svg', 'clinker.svg'],
        ['#btn-save-data', 'clinker.json'],
      ]) {
        const downloadPromise = popup.waitForEvent('download');
        await popup.frames()[1].locator(selector).click();
        expect((await downloadPromise).suggestedFilename()).toBe(filename);
      }
    }
    await popup.close();
  }

  const bigscape = bigscapeRoots[0];
  if (catalog.bigscape_viewer_available === true) {
    const bigscapePopupPromise = page.waitForEvent('popup');
    await page.evaluate(({ runId, id }) => openBigscapeResult(
      null,
      runId,
      window.__liveArtifactKeys[id],
      'clusterweave_viewer.sqlite',
    ), { runId: publicRunId, id: bigscape.id });
    const bigscapePopup = await bigscapePopupPromise;
    const bigscapePreview = bigscapePopup.locator('#clusterweave-bigscape-preview');
    await bigscapePreview.waitFor({ timeout: 120000 });
    await expect(bigscapePreview).toHaveAttribute('sandbox', 'allow-scripts allow-downloads');
    await expect.poll(() => bigscapePopup.frames().length, { timeout: 120000 }).toBe(2);
    await expect.poll(
      () => bigscapePopup.frames()[1].evaluate(() => window.CLUSTERWEAVE_BIGSCAPE_DATABASE_LOADED === true),
      { timeout: 120000 },
    ).toBe(true);
    const bigscapeFrame = bigscapePopup.frames()[1];
    await bigscapeFrame.locator('#load-all').click({ timeout: 120000 });
    const firstNetworkNode = bigscapeFrame.locator('.network-layer svg circle').first();
    await expect(firstNetworkNode).toBeVisible({ timeout: 120000 });
    await firstNetworkNode.click({ timeout: 120000 });
    const firstFamily = bigscapeFrame.locator(
      '.bs-desc_ui-list > li:visible > a.li-opendetail',
    ).first();
    await expect(firstFamily).toBeVisible({ timeout: 120000 });
    await expect(firstFamily).toHaveAttribute('data-clusterweave-bigscape-control', '');
    await expect(firstFamily).toHaveAttribute('role', 'button');
    await expect(firstFamily).toHaveAttribute('tabindex', '0');
    expect(await firstFamily.getAttribute('href')).toBeNull();
    expect(await bigscapeFrame.locator('a[href="##"]').count()).toBe(0);
    expect(await firstFamily.locator('xpath=following-sibling::ul[1]/li').count()).toBe(1);
    const selectedFamily = (await firstFamily.textContent()).trim();
    await firstFamily.click({ timeout: 120000 });
    await expect(bigscapeFrame.locator('.detail-container')).not.toHaveClass(/\bhidden\b/);
    await expect(bigscapeFrame.locator('.detail-container h2').first()).toHaveText(selectedFamily);
    await expect(bigscapeFrame.locator('#det_fam_tree')).toBeVisible();
    expect(await bigscapeFrame.locator('#det_fam_tree').evaluate(svg => svg.childElementCount)).toBeGreaterThan(0);
    expect(bigscapeFrame.url()).toBe('about:srcdoc');
    expect(await bigscapeFrame.locator('#bootstrap-splash').count()).toBe(0);
    const malformedFamilyTreeAttributes = await bigscapeFrame.locator('#det_fam_tree').evaluate(svg => (
      Array.from(svg.querySelectorAll('*')).flatMap(element => (
        Array.from(element.attributes)
          .map(attribute => `${attribute.name}=${attribute.value}`)
          .filter(value => /(?:NaN|Infinity)/.test(value))
      ))
    ));
    expect(malformedFamilyTreeAttributes).toEqual([]);
    expect(await bigscapePopup.evaluate(() => window.opener)).toBeNull();
    await bigscapePopup.close();
  } else {
    expect(catalog.bigscape_viewer_available).toBe(false);
  }

  expect(sandboxNetworkRequests).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
  await testInfo.attach('tool-result-smoke-summary.json', {
    body: JSON.stringify({
      generation: catalog.generation,
      antiSMASHRoots: antiRoots.length,
      antiSMASHNested: references.anti.size,
      funbgcexRoots: funRoots.length,
      funbgcexNested: references.funbgcex.size,
      clinkerRoots: clinkerRoots.length,
      bigscapeRoots: bigscapeRoots.length,
      bigscapeViewerAvailable: catalog.bigscape_viewer_available === true,
      representativeOnly,
      antiSMASHRootsSmoked: antiSmokeRoots.length,
      funbgcexRootsSmoked: funSmokeRoots.length,
      clinkerRootsSmoked: clinkerSmokeRoots.length,
      representativeActions: {
        antiSMASH: ['sequence-copy', 'svg-export', 'gbk-download', 'external-open'],
        funbgcex: ['gene-selection', 'aa-copy', 'gbk-download', 'funbgcs', 'pfam', 'blast'],
        clinker: ['svg-export', 'json-export'],
        bigscape: ['database-autoload', 'visualize-all', 'singleton-family-detail', 'finite-tree-svg'],
      },
    }, null, 2),
    contentType: 'application/json',
  });
});
