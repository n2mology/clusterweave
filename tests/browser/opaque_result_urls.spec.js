const { test, expect } = require('@playwright/test');

const baseUrl = 'http://127.0.0.1:4173';
const runId = 'rUNPUBlicId1234567890x';
const internalJobId = 'f6ad164d';
const token = 'fixture-private-read-token';

const ids = Object.freeze({
  fungal: 'AAAAAAAAAAAAAAAAAAAAAA',
  bacterial: 'BBBBBBBBBBBBBBBBBBBBBB',
  funbgcex: 'CCCCCCCCCCCCCCCCCCCCCC',
  funbgcexRegion: 'DDDDDDDDDDDDDDDDDDDDDD',
});

const descriptors = Object.freeze([
  {
    id: ids.fungal,
    filename: 'index.html',
    label: 'Fungus_alpha antiSMASH',
    bytes: 320,
    mime: 'text/html; charset=utf-8',
    category: 'antismash',
    kind: 'html',
    role: 'index',
    bundle_id: 'fungalBundleOpaque001x',
    pair_id: 'fungalBundleOpaque001x',
    genome_label: 'Fungus_alpha',
    previewable: true,
    downloadable: true,
  },
  {
    id: ids.bacterial,
    filename: 'index.html',
    label: 'Bacterium_beta antiSMASH',
    bytes: 330,
    mime: 'text/html; charset=utf-8',
    category: 'antismash',
    kind: 'html',
    role: 'index',
    bundle_id: 'bacteriaBundleOpaque01x',
    pair_id: 'bacteriaBundleOpaque01x',
    genome_label: 'Bacterium_beta',
    previewable: true,
    downloadable: true,
  },
  {
    id: ids.funbgcex,
    filename: 'allBGCs.html',
    label: 'Fungus_alpha FunBGCeX',
    bytes: 240,
    mime: 'text/html; charset=utf-8',
    category: 'funbgcex',
    kind: 'html',
    role: 'index',
    bundle_id: 'funbgcexBundleOpaque01x',
    pair_id: 'funbgcexBundleOpaque01x',
    genome_label: 'Fungus_alpha',
    previewable: true,
    downloadable: true,
  },
]);

const resolvedFunbgcexRegion = Object.freeze({
  id: ids.funbgcexRegion,
  filename: 'BGC1.html',
  label: 'BGC1.html',
  bytes: 96,
  mime: 'text/html; charset=utf-8',
  category: 'funbgcex',
  kind: 'html',
  role: 'region',
  bundle_id: 'funbgcexBundleOpaque01x',
  pair_id: 'funbgcexBundleOpaque01x',
  genome_label: 'Fungus_alpha',
  previewable: true,
  downloadable: true,
});

const antiSmashHtml = (kingdom) => `<!doctype html>
<html><body>
<script>
window.viewer = { switchToRegion(id) {
  const region = document.getElementById(id);
  region.dataset.active = 'true';
  region.dataset.activationCount = String(Number(region.dataset.activationCount || 0) + 1);
} };
</script>
<a id="region-node-link" href="#r1c1">Region 1 node</a>
<a id="region-row-link" href="#r1c1">Region 1 row</a>
<section id="r1c1">${kingdom} antiSMASH region detail</section>
</body></html>`;

const bodies = new Map([
  [ids.fungal, antiSmashHtml('Fungal')],
  [ids.bacterial, antiSmashHtml('Bacterial')],
  [ids.funbgcex, `<!doctype html><html><body>
    <a id="bgc-link" href="results/Fungus_alpha.funbgcex_results/HTMLs/BGC1.html#top">BGC 1</a>
  </body></html>`],
  [ids.funbgcexRegion, '<!doctype html><html><body><main id="top">FunBGCeX BGC 1 detail</main></body></html>'],
]);

function artifactEndpoint(id) {
  return `/api/results/${runId}/artifacts/${id}`;
}

test.describe('opaque public result URLs and sandboxed bundle navigation', () => {
  test.beforeEach(async ({ page }) => {
    const state = {
      apiRequests: [],
      resolverRequests: [],
      failedRequests: [],
      consoleErrors: [],
      pageErrors: [],
    };
    page.__opaqueResultState = state;

    const watchPage = candidate => {
      candidate.on('console', message => {
        if (message.type() === 'error') state.consoleErrors.push(message.text());
      });
      candidate.on('pageerror', error => state.pageErrors.push(String(error)));
      candidate.on('requestfailed', request => {
        state.failedRequests.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText || 'failed'}`);
      });
    };
    watchPage(page);
    page.context().on('page', watchPage);

    await page.route('**/api/system/status', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ online: true, submissions_open: true, jobs_processed: 2 }),
    }));

    await page.route(`**/api/results/${runId}/activity`, async route => {
      const request = route.request();
      const url = new URL(request.url());
      state.apiRequests.push(`${request.method()} ${url.pathname}${url.search}${url.hash}`);
      if (request.method() !== 'GET' || request.headers().authorization !== `Bearer ${token}`) {
        await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: runId,
          public_events: [],
          genome_progress: [],
        }),
      });
    });

    await page.route(`**/api/results/${runId}`, async route => {
      const request = route.request();
      const url = new URL(request.url());
      state.apiRequests.push(`${request.method()} ${url.pathname}${url.search}${url.hash}`);
      if (request.method() !== 'GET' || request.headers().authorization !== `Bearer ${token}`) {
        await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: runId,
          job_id: runId,
          public_run_id: runId,
          status: 'success',
          stage: 'complete',
          name: 'Opaque fixture',
          log_count: 0,
        }),
      });
    });

    await page.route(`**/api/results/${runId}/artifacts`, async route => {
      const request = route.request();
      const url = new URL(request.url());
      state.apiRequests.push(`${request.method()} ${url.pathname}${url.search}${url.hash}`);
      if (request.method() !== 'GET' || request.headers().authorization !== `Bearer ${token}`) {
        await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: runId,
          public_run_id: runId,
          generation: 'fixture-generation',
          result_index_state: 'attested',
          artifacts: descriptors,
        }),
      });
    });

    await page.route(`**/api/results/${runId}/artifacts/**`, async route => {
      const request = route.request();
      const url = new URL(request.url());
      state.apiRequests.push(`${request.method()} ${url.pathname}${url.search}${url.hash}`);
      if (request.headers().authorization !== `Bearer ${token}`) {
        await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
        return;
      }

      const prefix = artifactEndpoint('');
      const suffix = decodeURIComponent(url.pathname.slice(prefix.length));
      if (request.method() === 'POST' && suffix === `${ids.funbgcex}/resolve`) {
        const payload = request.postDataJSON();
        state.resolverRequests.push(payload.reference);
        if (payload.reference !== 'results/Fungus_alpha.funbgcex_results/HTMLs/BGC1.html#top') {
          await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ artifact: resolvedFunbgcexRegion, fragment: '#top' }),
        });
        return;
      }

      const id = suffix.replace(/\/download$/, '');
      const body = bodies.get(id);
      if (request.method() !== 'GET' || body === undefined) {
        await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'text/html; charset=utf-8',
        headers: {
          'Content-Length': String(Buffer.byteLength(body)),
          'Content-Disposition': `inline; filename="${id === ids.funbgcexRegion ? 'BGC1.html' : 'index.html'}"`,
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
      activeJobMeta = {
        id: publicRunId,
        job_id: publicRunId,
        public_run_id: publicRunId,
        status: 'success',
        name: 'Opaque fixture',
      };
      rememberOpenedRun(publicRunId, readToken, activeJobMeta);
      const keys = installResultArtifactDescriptors(artifactDescriptors);
      window.__opaqueResultKeys = Object.fromEntries(
        keys.map(key => [resultArtifactId(key), key]),
      );
    }, { publicRunId: runId, readToken: token, artifactDescriptors: descriptors });
  });

  async function openBundle(page, artifactId) {
    const cleanHref = await page.evaluate(
      ({ publicRunId, id }) => resultHref(publicRunId, window.__opaqueResultKeys[id]),
      { publicRunId: runId, id: artifactId },
    );
    const cleanUrl = new URL(cleanHref);
    expect(cleanUrl.pathname).toBe(artifactEndpoint(artifactId));
    expect(cleanHref).not.toContain(internalJobId);
    expect(cleanHref).not.toContain('data/results');
    expect(cleanHref).not.toContain(token);

    const popupPromise = page.waitForEvent('popup');
    await page.evaluate(
      ({ publicRunId, id }) => openHtmlResultWithAssets(
        null, publicRunId, window.__opaqueResultKeys[id],
      ),
      { publicRunId: runId, id: artifactId },
    );
    const popup = await popupPromise;
    await popup.locator('#clusterweave-tool-result-preview').waitFor();
    await expect(popup.locator('#clusterweave-tool-result-preview')).toHaveAttribute('sandbox', 'allow-scripts');
    await expect.poll(() => popup.frames().length).toBe(2);
    const frame = popup.frames()[1];
    await frame.waitForLoadState('domcontentloaded');
    expect(await popup.evaluate(() => window.opener)).toBeNull();
    return { popup, frame };
  }

  async function assertNoDisclosure(bundle) {
    const popupHtml = await bundle.popup.locator('html').evaluate(node => node.outerHTML);
    const frameHtml = await bundle.frame.locator('html').evaluate(node => node.outerHTML);
    for (const serialized of [popupHtml, frameHtml, bundle.popup.url(), bundle.frame.url()]) {
      expect(serialized).not.toContain(internalJobId);
      expect(serialized).not.toContain('data/results');
      expect(serialized).not.toContain(token);
    }
  }

  test('fungal and bacterial antiSMASH hash links stay functional without resolver traffic', async ({ page }) => {
    for (const [artifactId, expectedText] of [
      [ids.fungal, 'Fungal antiSMASH region detail'],
      [ids.bacterial, 'Bacterial antiSMASH region detail'],
    ]) {
      const bundle = await openBundle(page, artifactId);
      const resolverCount = page.__opaqueResultState.resolverRequests.length;
      for (const [selector, expectedCount] of [
        ['#region-node-link', '1'],
        ['#region-row-link', '2'],
      ]) {
        const link = bundle.frame.locator(selector);
        const hoverUrl = new URL(await link.getAttribute('href'));
        expect(hoverUrl.pathname).toBe(artifactEndpoint(artifactId));
        expect(hoverUrl.hash).toBe('#r1c1');
        await expect(link).toHaveAttribute('data-clusterweave-result-fragment', '#r1c1');
        await link.click();
        await expect(bundle.frame.locator('#r1c1')).toHaveAttribute('data-active', 'true');
        await expect(bundle.frame.locator('#r1c1')).toHaveAttribute('data-activation-count', expectedCount);
      }
      await expect(bundle.frame.locator('#r1c1')).toContainText(expectedText);
      expect(page.__opaqueResultState.resolverRequests).toHaveLength(resolverCount);
      await assertNoDisclosure(bundle);
      await bundle.popup.close();
    }
  });

  test('FunBGCeX resolves one attested child to a clean hover URL and keeps its fragment', async ({ page }) => {
    const bundle = await openBundle(page, ids.funbgcex);
    const link = bundle.frame.locator('#bgc-link');
    const href = await link.getAttribute('href');
    const cleanUrl = new URL(href);
    expect(cleanUrl.pathname).toBe(artifactEndpoint(ids.funbgcexRegion));
    expect(cleanUrl.hash).toBe('#top');
    expect(href).not.toContain('Fungus_alpha.funbgcex_results');
    expect(href).not.toContain(internalJobId);
    expect(href).not.toContain(token);

    await link.click();
    await expect(bundle.frame.locator('body')).toContainText('FunBGCeX BGC 1 detail');
    await expect.poll(() => bundle.frame.evaluate(() => window.location.hash)).toBe('#top');
    await expect.poll(() => bundle.popup.title()).toBe('BGC1.html');
    expect(page.__opaqueResultState.resolverRequests).toEqual([
      'results/Fungus_alpha.funbgcex_results/HTMLs/BGC1.html#top',
    ]);
    await assertNoDisclosure(bundle);
    await bundle.popup.close();
  });

  test('an initial tokenized result route reloads through opaque APIs and scrubs the token', async ({ page }) => {
    await page.goto(`${baseUrl}/#/results/${runId}/${token}`);
    await expect.poll(() => page.url()).toBe(`${baseUrl}/#/results/${runId}`);
    await expect(page.locator('body')).toHaveAttribute('data-existing-run-loaded', 'true');

    const serialized = await page.locator('html').evaluate(node => node.outerHTML);
    const hrefs = await page.locator('[href]').evaluateAll(nodes => nodes.map(node => node.getAttribute('href') || ''));
    for (const value of [serialized, ...hrefs]) {
      expect(value).not.toContain(token);
      expect(value).not.toContain(internalJobId);
      expect(value).not.toContain('data/results');
    }
    expect(page.__opaqueResultState.apiRequests.some(request => request === `GET /api/results/${runId}`)).toBeTruthy();
    expect(page.__opaqueResultState.apiRequests.some(request => request === `GET /api/results/${runId}/artifacts`)).toBeTruthy();
  });

  test.afterEach(async ({ page }) => {
    const state = page.__opaqueResultState;
    for (const request of state.apiRequests) {
      expect(request).not.toContain('/api/jobs/');
      expect(request).not.toContain(internalJobId);
      expect(request).not.toContain('data/results');
      expect(request).not.toContain(token);
      expect(request).not.toContain('Fungus_alpha.funbgcex_results');
    }
    expect(state.failedRequests).toEqual([]);
    expect(state.consoleErrors).toEqual([]);
    expect(state.pageErrors).toEqual([]);
  });
});
