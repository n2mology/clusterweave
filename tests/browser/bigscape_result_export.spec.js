const { test, expect } = require('@playwright/test');

const baseUrl = 'http://127.0.0.1:4173';
const runId = 'bigscapePublicRun123x';
const token = 'bigscape-read-token';
const htmlId = 'RRRRRRRRRRRRRRRRRRRRRR';

test('BiG-SCAPE loads its compact database and exports TSV/visualization with safe citations', async ({ page }) => {
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  const watchPage = candidate => {
    candidate.on('console', message => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    candidate.on('pageerror', error => pageErrors.push(String(error)));
    candidate.on('requestfailed', request => failedRequests.push(request.url()));
  };
  watchPage(page);
  page.context().on('page', watchPage);

  await page.route('**/api/system/status', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ online: true, submissions_open: true, jobs_processed: 1 }),
  }));
  await page.context().route('https://bigscape-corason.secondarymetabolites.org/**', route => route.fulfill({
    status: 200,
    contentType: 'text/html; charset=utf-8',
    body: '<!doctype html><title>BiG-SCAPE citation fixture</title>',
  }));
  await page.route(`**/api/results/${runId}/artifacts/${htmlId}`, route => {
    expect(route.request().headers().authorization).toBe(`Bearer ${token}`);
    return route.fulfill({
      status: 200,
      contentType: 'text/html; charset=utf-8',
      body: `<!doctype html><html><head><title>BiG-SCAPE fixture</title></head><body>
        <p id="status"></p><p id="loaded"></p>
        <button id="download-tsv" type="button">Download table</button>
        <button id="download-visualization" type="button">Download visualization</button>
        <p id="family-detail"></p>
        <a id="citation" href="https://bigscape-corason.secondarymetabolites.org/" target="_blank">BiG-SCAPE citation</a>
        <script>
          window.initSqlJs = async function () {
            return { Database: class { constructor(bytes) { window.__fixtureDatabaseBytes = bytes.byteLength; } } };
          };
          window.dataLoaded = function () {
            document.getElementById('loaded').textContent = 'database ready';
            const family = document.createElement('a');
            family.id = 'family-control';
            family.textContent = 'FAM_00001';
            family.setAttribute('data-clusterweave-bigscape-control', '');
            family.setAttribute('role', 'button');
            family.setAttribute('tabindex', '0');
            family.addEventListener('click', function () {
              const count = Number(family.dataset.activations || 0) + 1;
              family.dataset.activations = String(count);
              document.getElementById('family-detail').textContent = 'family opened ' + count;
            });
            document.body.appendChild(family);
          };
          function sendDownload(content, filename, type) {
            const link = document.createElement('a');
            link.href = 'data:' + type + ';charset=utf-8,' + encodeURIComponent(content);
            link.download = filename; document.body.appendChild(link); link.click(); link.remove();
          }
          document.getElementById('download-tsv').addEventListener('click', function () {
            sendDownload('bgc\\tfamily\\nfixture\\t1\\n', 'selection.tsv', 'text/tab-separated-values');
          });
          document.getElementById('download-visualization').addEventListener('click', function () {
            sendDownload('<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>', 'network.svg', 'image/svg+xml');
          });
        </script>
      </body></html>`,
    });
  });
  await page.route(`**/api/results/${runId}/bigscape-viewer-database`, route => {
    expect(route.request().headers().authorization).toBe(`Bearer ${token}`);
    const body = Buffer.alloc(64);
    Buffer.from('SQLite format 3\0', 'binary').copy(body);
    return route.fulfill({
      status: 200,
      contentType: 'application/vnd.sqlite3',
      headers: { 'Content-Length': String(body.length), 'X-Content-Type-Options': 'nosniff' },
      body,
    });
  });

  await page.goto(baseUrl);
  const htmlKey = await page.evaluate(({ publicRunId, readToken, id }) => {
    accessMode = 'public';
    activeJobId = publicRunId;
    activePublicRunId = publicRunId;
    activeJobMeta = {
      id: publicRunId,
      public_run_id: publicRunId,
      status: 'success',
      bigscape_viewer_available: true,
    };
    rememberOpenedRun(publicRunId, readToken, activeJobMeta);
    return installResultArtifactDescriptors([{
      id,
      filename: 'index.html',
      label: 'BiG-SCAPE',
      category: 'bigscape',
      kind: 'html',
      role: 'page',
      mime: 'text/html; charset=utf-8',
      previewable: true,
      downloadable: true,
    }])[0];
  }, { publicRunId: runId, readToken: token, id: htmlId });

  const popupPromise = page.waitForEvent('popup');
  await page.evaluate(({ publicRunId, key }) => openBigscapeResult(
    null,
    publicRunId,
    key,
    'clusterweave_viewer.sqlite',
  ), { publicRunId: runId, key: htmlKey });
  const popup = await popupPromise;
  const preview = popup.locator('#clusterweave-bigscape-preview');
  await preview.waitFor();
  await expect(preview).toHaveAttribute('sandbox', 'allow-scripts allow-downloads');
  await expect.poll(() => popup.frames().length).toBe(2);
  const frame = popup.frames()[1];
  await expect(frame.locator('#loaded')).toHaveText('database ready');
  expect(await frame.evaluate(() => ({
    loaded: window.CLUSTERWEAVE_BIGSCAPE_DATABASE_LOADED,
    transferred: window.CLUSTERWEAVE_BIGSCAPE_DATABASE_BYTES,
    opened: window.__fixtureDatabaseBytes,
  }))).toEqual({ loaded: true, transferred: 64, opened: 64 });

  const familyControl = frame.locator('#family-control');
  await expect(familyControl).toHaveAttribute('role', 'button');
  expect(await familyControl.getAttribute('href')).toBeNull();
  const frameUrl = frame.url();
  await familyControl.click();
  await expect(frame.locator('#family-detail')).toHaveText('family opened 1');
  await familyControl.press('Enter');
  await expect(frame.locator('#family-detail')).toHaveText('family opened 2');
  await familyControl.press(' ');
  await expect(frame.locator('#family-detail')).toHaveText('family opened 3');
  expect(frame.url()).toBe(frameUrl);

  for (const [button, filename] of [
    ['#download-tsv', 'selection.tsv'],
    ['#download-visualization', 'network.svg'],
  ]) {
    const downloadPromise = popup.waitForEvent('download');
    await frame.locator(button).click();
    expect((await downloadPromise).suggestedFilename()).toBe(filename);
  }

  const citation = frame.locator('#citation');
  await expect(citation).toHaveAttribute(
    'data-clusterweave-result-external',
    'https://bigscape-corason.secondarymetabolites.org/',
  );
  const citationPagePromise = page.context().waitForEvent('page');
  await citation.click();
  const citationPage = await citationPagePromise;
  await expect(citationPage).toHaveURL('https://bigscape-corason.secondarymetabolites.org/');
  expect(await citationPage.evaluate(() => window.opener)).toBeNull();
  await citationPage.close();

  expect(await popup.evaluate(() => window.opener)).toBeNull();
  await popup.close();
  expect(failedRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
