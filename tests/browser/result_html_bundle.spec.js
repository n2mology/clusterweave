const { test, expect } = require('@playwright/test');

const baseUrl = 'http://127.0.0.1:4173';
const runId = 'bundlePublicRun123456x';
const otherRunId = 'bundlePublicRun654321y';
const internalJobId = 'f6ad164d';
const token = 'fixture-read-token';

const ids = Object.freeze({
  fungalRoot: 'AAAAAAAAAAAAAAAAAAAAAA',
  fungalRegion: 'EEEEEEEEEEEEEEEEEEEEEE',
  bacterialRoot: 'BBBBBBBBBBBBBBBBBBBBBB',
  bacterialRegion: 'FFFFFFFFFFFFFFFFFFFFFF',
  funbgcexRoot: 'CCCCCCCCCCCCCCCCCCCCCC',
  funbgcexRegion: 'DDDDDDDDDDDDDDDDDDDDDD',
  fungalRuntime: 'GGGGGGGGGGGGGGGGGGGGGG',
  fungalImage: 'HHHHHHHHHHHHHHHHHHHHHH',
  funbgcexFunctions: 'IIIIIIIIIIIIIIIIIIIIII',
  funbgcexAfter: 'JJJJJJJJJJJJJJJJJJJJJJ',
  otherRoot: 'KKKKKKKKKKKKKKKKKKKKKK',
});

function descriptor(id, filename, category, role, bundleId, overrides = {}) {
  return {
    id,
    filename,
    label: filename,
    bytes: 128,
    mime: overrides.mime || 'text/html; charset=utf-8',
    category,
    kind: overrides.kind || 'html',
    role,
    bundle_id: bundleId,
    pair_id: bundleId,
    genome_label: category === 'antismash' ? 'antiSMASH fixture' : 'FunBGCeX fixture',
    previewable: true,
    downloadable: true,
  };
}

const descriptors = Object.freeze([
  descriptor(ids.fungalRoot, 'index.html', 'antismash', 'index', 'fungalBundleOpaque001x'),
  descriptor(ids.bacterialRoot, 'index.html', 'antismash', 'index', 'bacteriaBundleOpaque01x'),
  descriptor(ids.funbgcexRoot, 'results.html', 'funbgcex', 'index', 'funbgcexBundleOpaque01x'),
]);

const children = new Map([
  [`${ids.fungalRoot}:knownclusterblast/region1/hit.html`,
    descriptor(ids.fungalRegion, 'hit.html', 'antismash', 'region', 'fungalBundleOpaque001x')],
  [`${ids.bacterialRoot}:knownclusterblast/region1/hit.html`,
    descriptor(ids.bacterialRegion, 'hit.html', 'antismash', 'region', 'bacteriaBundleOpaque01x')],
  [`${ids.funbgcexRoot}:HTMLs/BGC1.html`,
    descriptor(ids.funbgcexRegion, 'BGC1.html', 'funbgcex', 'region', 'funbgcexBundleOpaque01x')],
  [`${ids.fungalRoot}:regions.js`,
    descriptor(
      ids.fungalRuntime,
      'regions.js',
      'antismash',
      'asset',
      'fungalBundleOpaque001x',
      { kind: 'script', mime: 'text/javascript; charset=utf-8' },
    )],
  [`${ids.fungalRoot}:smcogs/tree.png`,
    descriptor(
      ids.fungalImage,
      'tree.png',
      'antismash',
      'asset',
      'fungalBundleOpaque001x',
      { kind: 'image', mime: 'image/png' },
    )],
  [`${ids.funbgcexRoot}:scripts/functions.js`,
    descriptor(
      ids.funbgcexFunctions,
      'functions.js',
      'funbgcex',
      'asset',
      'funbgcexBundleOpaque01x',
      { kind: 'script', mime: 'text/javascript; charset=utf-8' },
    )],
  [`${ids.funbgcexRoot}:scripts/after.js`,
    descriptor(
      ids.funbgcexAfter,
      'after.js',
      'funbgcex',
      'asset',
      'funbgcexBundleOpaque01x',
      { kind: 'script', mime: 'text/javascript; charset=utf-8' },
    )],
]);
for (let index = 0; index < 80; index += 1) {
  children.set(
    `${ids.fungalRoot}:runtime/hit-${index}.html`,
    descriptor(ids.fungalRegion, 'hit.html', 'antismash', 'region', 'fungalBundleOpaque001x'),
  );
}

const fixtures = new Map([
  [ids.fungalRoot, '<!doctype html><html><body><h1>Fungal antiSMASH</h1><a href="knownclusterblast/region1/hit.html">Region 1</a><a href="region001.gbk">GBK download</a><a href="result.json">JSON download</a><a href="bundle.zip">ZIP download</a><div id="runtime-links"></div><script defer src="regions.js"></script></body></html>'],
  [ids.fungalRegion, '<!doctype html><html><head><link rel="stylesheet" href="../../css/missing.css"></head><body><h1>Fungal region detail</h1></body></html>'],
  [ids.bacterialRoot, '<!doctype html><html><body><h1>Bacterial antiSMASH</h1><a href="knownclusterblast/region1/hit.html">Region 1</a></body></html>'],
  [ids.bacterialRegion, '<!doctype html><html><body><h1>Bacterial region detail</h1></body></html>'],
  [ids.funbgcexRoot, `<!doctype html><html><head>
    <style id="bundle-css">
      @import url("https://styles.example.invalid/external.css");
      @import "css/missing-import.css";
      #missing-css { background-image: url("images/missing.png"); }
      #external-css { background-image: url("https://assets.example.invalid/tracker.png"); }
    </style>
    <script id="funbgcex-functions" defer src="scripts/functions.js"></script>
    <script id="funbgcex-after" defer src="scripts/after.js"></script>
  </head><body>
    <h1>FunBGCeX</h1>
    <a href="HTMLs/BGC1.html">BGC 1</a>
    <button id="filter-button" type="button" onclick="Filter()">Filter</button>
    <button id="copy-button" type="button" onclick="copy()">Copy</button>
    <output id="callback-result"></output>
    <div id="funbgcex-ready"></div>
    <div id="missing-css"></div><div id="external-css"></div>
    <a id="external-link" href="https://outside.example.invalid/docs" target="_blank">External docs</a>
  </body></html>`],
  [ids.funbgcexRegion, '<!doctype html><html><body><h1>FunBGCeX BGC 1 detail</h1></body></html>'],
  [ids.fungalRuntime, 'var burst="";for(var i=0;i<80;i+=1){burst += "<a id=\\"runtime-burst-"+i+"\\" href=\\"runtime/hit-"+i+".html\\">Burst "+i+"</a>";}document.getElementById("runtime-links").innerHTML = "<a id=\\"runtime-html\\" href=\\"knownclusterblast/region1/hit.html\\">Runtime MIBiG hits</a><a id=\\"runtime-image\\" href=\\"smcogs/tree.png\\">Runtime smCOG tree</a><a id=\\"runtime-private\\" href=\\"region001.gbk\\">Runtime private GBK</a><div id=\\"runtime-burst\\">"+burst+"</div>";'],
  [ids.fungalImage, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64')],
  [ids.funbgcexFunctions, `window.funbgcexDeferredOrder = ['functions'];
    function Filter() { document.getElementById('callback-result').textContent = 'filtered'; }
    function copy() { document.getElementById('callback-result').textContent = 'copied'; }`],
  [ids.funbgcexAfter, `window.funbgcexDeferredOrder.push('after');
    document.body.dataset.funbgcexDeferredOrder = window.funbgcexDeferredOrder.join(',');
    document.getElementById('funbgcex-ready').textContent = typeof Filter + ':' + typeof copy;`],
]);

function artifactEndpoint(id) {
  return `/api/results/${runId}/artifacts/${id}`;
}

test.describe('authenticated generated HTML bundles', () => {
  test.beforeEach(async ({ page }) => {
    const state = {
      apiRequests: [],
      resolverReferences: [],
      legacyRequests: [],
      otherRunRequests: [],
      failedRequests: [],
      consoleErrors: [],
      pageErrors: [],
      resolverDelayMs: 0,
      activeResolvers: 0,
      maxActiveResolvers: 0,
    };
    page.__bundleState = state;
    const watchPage = candidate => {
      candidate.on('console', message => {
        if (message.type() === 'error') state.consoleErrors.push(message.text());
      });
      candidate.on('pageerror', error => state.pageErrors.push(String(error)));
      candidate.on('requestfailed', request => state.failedRequests.push(request.url()));
    };
    watchPage(page);
    page.context().on('page', watchPage);

    await page.route('**/api/system/status', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ online: true, submissions_open: true, jobs_processed: 1 }),
    }));
    await page.route('**/api/jobs/**', async route => {
      state.legacyRequests.push(route.request().url());
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
    });
    await page.route(`**/api/results/${otherRunId}/**`, async route => {
      state.otherRunRequests.push(route.request().url());
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
    });
    await page.route(`**/api/results/${runId}/artifacts/**`, async route => {
      const request = route.request();
      const url = new URL(request.url());
      state.apiRequests.push(`${request.method()} ${url.pathname}${url.search}`);
      if (request.headers().authorization !== `Bearer ${token}`) {
        await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
        return;
      }

      const suffix = decodeURIComponent(url.pathname.slice(artifactEndpoint('').length));
      if (request.method() === 'POST' && suffix.endsWith('/resolve')) {
        const ownerId = suffix.slice(0, -'/resolve'.length);
        const requestPayload = request.postDataJSON() || {};
        const reference = String(requestPayload.reference || '').split('#', 1)[0];
        state.resolverReferences.push(reference);
        if (state.resolverDelayMs > 0 && reference.startsWith('runtime/hit-')) {
          state.activeResolvers += 1;
          state.maxActiveResolvers = Math.max(state.maxActiveResolvers, state.activeResolvers);
          await new Promise(resolve => setTimeout(resolve, state.resolverDelayMs));
          state.activeResolvers -= 1;
        }
        const child = children.get(`${ownerId}:${reference}`);
        if (!child) {
          if (requestPayload.optional === true && /\.(?:css|html?|png)$/i.test(reference)) {
            await route.fulfill({
              status: 200,
              contentType: 'application/json',
              body: JSON.stringify({ artifact: null, fragment: '' }),
            });
            return;
          }
          await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ artifact: child, fragment: '' }),
        });
        return;
      }

      const id = suffix.replace(/\/download$/, '');
      const body = fixtures.get(id);
      if (request.method() !== 'GET' || body === undefined) {
        await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
        return;
      }
      const item = descriptors.find(candidate => candidate.id === id)
        || [...children.values()].find(candidate => candidate.id === id);
      const bodyBytes = Buffer.isBuffer(body) ? body : Buffer.from(body);
      await route.fulfill({
        status: 200,
        contentType: item.mime,
        headers: {
          'Content-Disposition': `inline; filename="${item.filename}"`,
          'Content-Length': String(bodyBytes.length),
          'X-Content-Type-Options': 'nosniff',
        },
        body,
      });
    });
    await page.goto(baseUrl);
    await page.evaluate(({ publicRunId, readToken, artifactDescriptors }) => {
      accessMode = 'public';
      activeJobId = publicRunId;
      activePublicRunId = publicRunId;
      activeJobMeta = { id: publicRunId, public_run_id: publicRunId, status: 'success' };
      rememberOpenedRun(publicRunId, readToken, activeJobMeta);
      const keys = installResultArtifactDescriptors(artifactDescriptors);
      window.__bundleKeys = Object.fromEntries(keys.map(key => [resultArtifactId(key), key]));
    }, { publicRunId: runId, readToken: token, artifactDescriptors: descriptors });
  });

  async function openBundle(page, artifactId) {
    const popupPromise = page.waitForEvent('popup');
    await page.evaluate(({ publicRunId, id }) => openHtmlResultWithAssets(
      null,
      publicRunId,
      window.__bundleKeys[id],
    ), {
      publicRunId: runId,
      id: artifactId,
    });
    const popup = await popupPromise;
    await popup.locator('#clusterweave-tool-result-preview').waitFor();
    await expect(popup.locator('#clusterweave-tool-result-preview')).toHaveAttribute('sandbox', 'allow-scripts');
    await expect.poll(() => popup.frames().length).toBe(2);
    const frame = popup.frames()[1];
    await frame.waitForLoadState('domcontentloaded');
    expect(await popup.evaluate(() => window.opener)).toBeNull();
    return { popup, frame };
  }

  async function expectNestedNavigation(bundle, linkText, childId, expectedTitle, expectedBody) {
    const link = bundle.frame.getByRole('link', { name: linkText });
    await expect.poll(async () => new URL(await link.getAttribute('href')).pathname)
      .toBe(artifactEndpoint(childId));
    const href = await link.getAttribute('href');
    expect(href).not.toContain(internalJobId);
    expect(href).not.toContain('data/results');
    expect(href).not.toContain(token);
    await link.click();
    await expect.poll(() => bundle.popup.title()).toBe(expectedTitle);
    await expect(bundle.frame.locator('body')).toContainText(expectedBody);
    await bundle.popup.close();
  }

  test('fungal and bacterial antiSMASH plus FunBGCeX links stay inside the opaque preview', async ({ page }) => {
    const fungal = await openBundle(page, ids.fungalRoot);
    await expect(fungal.frame.locator('body')).toContainText('Fungal antiSMASH');
    for (const linkName of ['GBK download', 'JSON download', 'ZIP download']) {
      const disabled = fungal.frame.getByText(linkName, { exact: true });
      await expect(disabled).not.toHaveAttribute('href');
      await expect(disabled).toHaveAttribute('aria-disabled', 'true');
    }
    expect(page.__bundleState.resolverReferences).not.toContain('region001.gbk');
    expect(page.__bundleState.resolverReferences).not.toContain('result.json');
    expect(page.__bundleState.resolverReferences).not.toContain('bundle.zip');
    await expectNestedNavigation(fungal, 'Region 1', ids.fungalRegion, 'hit.html', 'Fungal region detail');

    const bacterial = await openBundle(page, ids.bacterialRoot);
    await expect(bacterial.frame.locator('body')).toContainText('Bacterial antiSMASH');
    await expectNestedNavigation(bacterial, 'Region 1', ids.bacterialRegion, 'hit.html', 'Bacterial region detail');

    const funbgcex = await openBundle(page, ids.funbgcexRoot);
    await expect(funbgcex.frame.locator('body')).toContainText('FunBGCeX');
    await expectNestedNavigation(funbgcex, 'BGC 1', ids.funbgcexRegion, 'BGC1.html', 'FunBGCeX BGC 1 detail');
  });

  test('runtime-injected antiSMASH links resolve through the authenticated parent relay', async ({ page }) => {
    const htmlBundle = await openBundle(page, ids.fungalRoot);
    const htmlLink = htmlBundle.frame.locator('#runtime-html');
    await expect(htmlLink).not.toHaveAttribute('href');
    await expect(htmlLink).toHaveAttribute('data-clusterweave-result-pending', '');
    const initialHtmlResolves = page.__bundleState.resolverReferences
      .filter(reference => reference === 'knownclusterblast/region1/hit.html').length;
    expect(initialHtmlResolves).toBe(1);
    expect(page.__bundleState.resolverReferences).not.toContain('smcogs/tree.png');

    const rootEnvelope = await htmlBundle.frame.locator(
      'script[data-clusterweave-result-preview]',
    ).evaluate(element => ({
      channel: element.dataset.channel,
      owner: element.dataset.owner,
    }));
    const beforeForgedSource = page.__bundleState.resolverReferences.length;
    await htmlBundle.popup.evaluate(envelope => {
      window.postMessage({
        type: 'clusterweave:result-bundle-resolve',
        channel: envelope.channel,
        owner: envelope.owner,
        request: 'r500000000',
        reference: 'runtime/hit-79.html',
      }, '*');
    }, rootEnvelope);
    await page.waitForTimeout(100);
    expect(page.__bundleState.resolverReferences).toHaveLength(beforeForgedSource);

    await htmlLink.hover();
    await expect.poll(() => page.__bundleState.resolverReferences
      .filter(reference => reference === 'knownclusterblast/region1/hit.html').length)
      .toBe(initialHtmlResolves + 1);
    await expect(htmlLink).toHaveAttribute('data-clusterweave-result-artifact', ids.fungalRegion);
    await expect.poll(async () => new URL(await htmlLink.getAttribute('href')).pathname)
      .toBe(artifactEndpoint(ids.fungalRegion));
    const privateLink = htmlBundle.frame.locator('#runtime-private');
    await expect(privateLink).not.toHaveAttribute('href');
    await expect(privateLink).toHaveAttribute('aria-disabled', 'true');
    await htmlLink.click();
    await expect(htmlBundle.frame.locator('body')).toContainText('Fungal region detail');
    const childEnvelope = await htmlBundle.frame.locator(
      'script[data-clusterweave-result-preview]',
    ).evaluate(element => ({
      channel: element.dataset.channel,
      owner: element.dataset.owner,
    }));
    expect(childEnvelope.channel).not.toBe(rootEnvelope.channel);
    const beforeStaleChannel = page.__bundleState.resolverReferences.length;
    await htmlBundle.frame.evaluate(envelope => {
      window.parent.postMessage({
        type: 'clusterweave:result-bundle-resolve',
        channel: envelope.channel,
        owner: envelope.owner,
        request: 'r500000001',
        reference: 'runtime/hit-78.html',
      }, '*');
    }, rootEnvelope);
    await page.waitForTimeout(100);
    expect(page.__bundleState.resolverReferences).toHaveLength(beforeStaleChannel);
    await htmlBundle.popup.close();

    const imageBundle = await openBundle(page, ids.fungalRoot);
    const imageLink = imageBundle.frame.locator('#runtime-image');
    await expect(imageLink).not.toHaveAttribute('href');
    await expect(imageLink).toHaveAttribute('data-clusterweave-result-pending', '');
    await imageLink.hover();
    await expect(imageLink).toHaveAttribute('data-clusterweave-result-artifact', ids.fungalImage);
    await expect.poll(async () => new URL(await imageLink.getAttribute('href')).pathname)
      .toBe(artifactEndpoint(ids.fungalImage));
    await imageLink.click();
    await expect(imageBundle.frame.locator('img')).toHaveAttribute('src', /^data:image\/png;base64,/);
    await expect.poll(() => imageBundle.popup.title()).toBe('tree.png');
    await imageBundle.popup.close();

    expect(page.__bundleState.resolverReferences).not.toContain('region001.gbk');
    expect(page.__bundleState.resolverReferences).toContain('knownclusterblast/region1/hit.html');
    expect(page.__bundleState.resolverReferences).toContain('smcogs/tree.png');
  });

  test('runtime links resolve lazily with coalescing and at most four parent requests active', async ({ page }) => {
    const bundle = await openBundle(page, ids.fungalRoot);
    const burstLinks = bundle.frame.locator('[id^="runtime-burst-"]');
    await expect(burstLinks).toHaveCount(80);
    expect(await burstLinks.evaluateAll(elements => elements.every(element => (
      !element.hasAttribute('href')
      && element.hasAttribute('data-clusterweave-result-pending')
    )))).toBeTruthy();
    expect(page.__bundleState.resolverReferences.filter(
      reference => reference.startsWith('runtime/hit-'),
    )).toEqual([]);

    page.__bundleState.resolverDelayMs = 500;
    await burstLinks.nth(0).hover();
    await burstLinks.nth(1).hover();
    await burstLinks.nth(0).hover();
    for (let index = 2; index < 16; index += 1) {
      await burstLinks.nth(index).hover();
    }

    await expect.poll(() => page.__bundleState.resolverReferences.filter(
      reference => reference.startsWith('runtime/hit-'),
    ).length).toBe(16);
    await expect.poll(() => page.__bundleState.activeResolvers).toBe(0);
    expect(page.__bundleState.resolverReferences.filter(
      reference => reference === 'runtime/hit-0.html',
    )).toHaveLength(1);
    expect(page.__bundleState.maxActiveResolvers).toBeGreaterThan(1);
    expect(page.__bundleState.maxActiveResolvers).toBeLessThanOrEqual(4);

    const cleanHref = await burstLinks.nth(0).getAttribute('href');
    expect(new URL(cleanHref).pathname).toBe(artifactEndpoint(ids.fungalRegion));
    expect(cleanHref).not.toContain('runtime/hit-0.html');
    expect(cleanHref).not.toContain(internalJobId);
    expect(cleanHref).not.toContain(token);
    await bundle.popup.close();
  });

  test('an open run A popup survives an active catalog switch to run B without contamination', async ({ page }) => {
    const bundle = await openBundle(page, ids.fungalRoot);
    const runtimeLink = bundle.frame.locator('#runtime-html');
    await expect(runtimeLink).not.toHaveAttribute('href');
    const rootChannel = await bundle.frame.locator(
      'script[data-clusterweave-result-preview]',
    ).getAttribute('data-channel');

    const otherDescriptor = descriptor(
      ids.otherRoot,
      'index.html',
      'antismash',
      'index',
      'otherBundleOpaque00001x',
    );
    const activeState = await page.evaluate(({ publicRunId, artifactDescriptor, oldChildId }) => {
      activeJobId = publicRunId;
      activePublicRunId = publicRunId;
      activeJobMeta = { id: publicRunId, public_run_id: publicRunId, status: 'success' };
      installResultArtifactDescriptors([artifactDescriptor], { replace: true });
      return {
        oldChildPresent: !!resultArtifactDescriptor(oldChildId),
        otherRootPresent: !!resultArtifactDescriptor(artifactDescriptor.id),
      };
    }, {
      publicRunId: otherRunId,
      artifactDescriptor: otherDescriptor,
      oldChildId: ids.fungalRegion,
    });
    expect(activeState).toEqual({ oldChildPresent: false, otherRootPresent: true });

    await runtimeLink.hover();
    await expect(runtimeLink).toHaveAttribute('data-clusterweave-result-artifact', ids.fungalRegion);
    const cleanHref = await runtimeLink.getAttribute('href');
    expect(new URL(cleanHref).pathname).toBe(artifactEndpoint(ids.fungalRegion));
    expect(page.__bundleState.otherRunRequests).toEqual([]);
    await runtimeLink.click();
    await expect(bundle.frame.locator('body')).toContainText('Fungal region detail');
    const nestedChannel = await bundle.frame.locator(
      'script[data-clusterweave-result-preview]',
    ).getAttribute('data-channel');
    expect(nestedChannel).not.toBe(rootChannel);

    expect(await page.evaluate(({ oldChildId, otherRootId }) => ({
      oldChildPresent: !!resultArtifactDescriptor(oldChildId),
      otherRootPresent: !!resultArtifactDescriptor(otherRootId),
    }), {
      oldChildId: ids.fungalRegion,
      otherRootId: ids.otherRoot,
    })).toEqual({ oldChildPresent: false, otherRootPresent: true });
    expect(page.__bundleState.otherRunRequests).toEqual([]);
    await bundle.popup.close();
  });

  test('FunBGCeX defer globals, CSS, and external links retain sandbox-safe semantics', async ({ page }) => {
    const bundle = await openBundle(page, ids.funbgcexRoot);

    await expect(bundle.frame.locator('#funbgcex-ready')).toHaveText('function:function');
    await expect(bundle.frame.locator('body')).toHaveAttribute(
      'data-funbgcex-deferred-order',
      'functions,after',
    );
    expect(await bundle.frame.evaluate(() => ({
      functionsParent: document.getElementById('funbgcex-functions').parentElement.tagName,
      afterParent: document.getElementById('funbgcex-after').parentElement.tagName,
      functionsBeforeAfter: !!(
        document.getElementById('funbgcex-functions').compareDocumentPosition(
          document.getElementById('funbgcex-after'),
        ) & Node.DOCUMENT_POSITION_FOLLOWING
      ),
      afterBeforeNavigator: !!(
        document.getElementById('funbgcex-after').compareDocumentPosition(
          document.querySelector('script[data-clusterweave-result-preview]'),
        ) & Node.DOCUMENT_POSITION_FOLLOWING
      ),
    }))).toEqual({
      functionsParent: 'BODY',
      afterParent: 'BODY',
      functionsBeforeAfter: true,
      afterBeforeNavigator: true,
    });

    await bundle.frame.locator('#filter-button').click();
    await expect(bundle.frame.locator('#callback-result')).toHaveText('filtered');
    await bundle.frame.locator('#copy-button').click();
    await expect(bundle.frame.locator('#callback-result')).toHaveText('copied');

    const rewrittenCss = await bundle.frame.locator('#bundle-css').textContent();
    expect(rewrittenCss).not.toContain('@import');
    expect(rewrittenCss).not.toContain('example.invalid');
    expect(rewrittenCss).not.toContain('missing-import.css');
    expect(rewrittenCss).not.toContain('images/missing.png');
    expect((rewrittenCss.match(/\bnone\b/g) || []).length).toBe(2);
    expect(page.__bundleState.resolverReferences).not.toContain('css/missing-import.css');
    expect(page.__bundleState.resolverReferences).toContain('images/missing.png');

    const external = bundle.frame.locator('#external-link');
    await expect(external).not.toHaveAttribute('href');
    await expect(external).not.toHaveAttribute('target');
    await expect(external).toHaveAttribute('aria-disabled', 'true');
    const openPageCount = page.context().pages().length;
    await external.click();
    expect(page.context().pages()).toHaveLength(openPageCount);
    await bundle.popup.close();
  });

  test.afterEach(async ({ page }) => {
    const state = page.__bundleState;
    expect(state.legacyRequests).toEqual([]);
    expect(state.otherRunRequests).toEqual([]);
    for (const request of state.apiRequests) {
      expect(request).not.toContain('/api/jobs/');
      expect(request).not.toContain(internalJobId);
      expect(request).not.toContain('data/results');
      expect(request).not.toContain(token);
      expect(request).not.toContain('knownclusterblast');
      expect(request).not.toContain('HTMLs/BGC1.html');
    }
    expect(state.failedRequests).toEqual([]);
    expect(state.consoleErrors).toEqual([]);
    expect(state.pageErrors).toEqual([]);
  });
});
