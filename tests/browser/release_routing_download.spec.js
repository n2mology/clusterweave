const { test, expect } = require('@playwright/test');

const baseUrl = 'http://127.0.0.1:4173';

async function routeSystemStatus(page) {
  await page.route('**/api/system/status*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      online: true,
      ready: true,
      service: 'online',
      submissions_open: true,
      submissions: 'open',
      smtp_enabled: false,
      worker: { status: 'ready', running_count: 0, active_count: 0 },
      capabilities: { stages: {} },
      jobs_processed: 0,
      running_jobs: 0,
      queued_jobs: 0,
      public_quota: { max_accessions: 50, max_genome_files: 50 },
    }),
  }));
}

test('input CTA validates first and submits only after the chartreuse state', async ({ page }) => {
  await routeSystemStatus(page);
  let postCount = 0;
  await page.route('**/api/jobs', route => {
    if (route.request().method() !== 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    }
    postCount += 1;
    return route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'validatedRunFixture',
        public_run_id: 'validatedRunFixture',
        read_token: 'fixture-read-token',
        result_url: '/results/validatedRunFixture',
        input_summary: { taxon_counts: { fungi: 1, bacteria: 0, total: 1 } },
      }),
    });
  });
  await page.route('**/api/results/validatedRunFixture*', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/artifacts')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ run_id: 'validatedRunFixture', artifacts: [] }),
      });
    }
    if (path.endsWith('/activity')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ public_events: [], genome_progress: [] }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'validatedRunFixture',
        public_run_id: 'validatedRunFixture',
        project_name: 'validation_fixture',
        status: 'pending',
        stage: 'queued',
        created_at: '2026-07-23T12:00:00',
        updated_at: '2026-07-23T12:00:00',
        result_file_count: 0,
        analysis_scope: 'fungi',
      }),
    });
  });

  await page.goto(baseUrl);
  await page.locator('#project-name').fill('validation_fixture');
  await page.locator('#file-input').setInputFiles({
    name: 'fixture.fna',
    mimeType: 'text/plain',
    buffer: Buffer.from(`>fixture_contig\n${'ACGT'.repeat(600)}\n`),
  });

  const button = page.locator('#run-btn');
  await expect(button).toBeEnabled();
  await expect(button).toHaveText('Validate');
  await expect(button).toHaveClass(/is-validation-pending/);
  await expect(button).toHaveCSS('background-color', 'rgb(255, 122, 24)');

  await button.click();
  await expect(button).toHaveText('Submit run');
  await expect(button).toHaveClass(/is-submit-ready/);
  await expect(button).toHaveCSS('background-color', 'rgb(215, 255, 31)');
  await expect(page.locator('#upload-status')).toContainText('Validation passed');
  expect(postCount).toBe(0);

  await button.click();
  await expect.poll(() => postCount).toBe(1);
});

test('package transfer survives a new run and its progress tray does not collide', async ({ page }) => {
  await routeSystemStatus(page);
  await page.route('**/api/jobs', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }));
  await page.route('**/api/results/nextRunFixture*', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/artifacts')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ run_id: 'nextRunFixture', artifacts: [] }),
      });
    }
    if (path.endsWith('/activity')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ public_events: [], genome_progress: [] }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'nextRunFixture',
        public_run_id: 'nextRunFixture',
        project_name: 'next_run',
        status: 'pending',
        stage: 'queued',
        created_at: '2026-07-23T12:10:00',
        updated_at: '2026-07-23T12:10:00',
        result_file_count: 0,
        analysis_scope: 'fungi',
      }),
    });
  });

  await page.goto(baseUrl);
  await page.evaluate(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, options) => {
      const url = String(input instanceof Request ? input.url : input);
      if (!url.includes('/api/results/archiveRunFixture/archive')) {
        return originalFetch(input, options);
      }
      const chunkSize = 256 * 1024;
      const chunks = [
        new Uint8Array(chunkSize).fill(1),
        new Uint8Array(chunkSize).fill(2),
        new Uint8Array(chunkSize).fill(3),
      ];
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(chunks[0]);
          setTimeout(() => controller.enqueue(chunks[1]), 350);
          setTimeout(() => {
            controller.enqueue(chunks[2]);
            controller.close();
          }, 700);
        },
      });
      return Promise.resolve(new Response(stream, {
        status: 200,
        headers: {
          'content-type': 'application/zip',
          'content-length': String(chunkSize * chunks.length),
        },
      }));
    };
    setAccessMode('public');
    activeJobId = 'archiveRunFixture';
    activePublicRunId = 'archiveRunFixture';
    publicResultRunIds.add('archiveRunFixture');
    activeResultPackageFileCount = 1;
    activeResultFiles = ['artifact/figures/AAAAAAAAAAAAAAAAAAAAAA/fixture.svg'];
    document.body.dataset.jobState = 'complete';
    updateArchiveButton();
  });

  const downloadEvent = page.waitForEvent('download');
  await page.locator('#download-package-btn').click();
  const tray = page.locator('#archive-download-tray');
  await expect(tray).toBeVisible();
  await expect(tray).toHaveAttribute('aria-busy', 'true');
  await expect.poll(() => page.locator('#archive-download-progress').getAttribute('aria-valuenow')).toBe('33');

  await page.evaluate(() => {
    void loadJob('nextRunFixture', false, { publicResult: true, source: 'submit' });
  });
  await expect.poll(() => page.evaluate(() => activeJobId)).toBe('nextRunFixture');
  await expect.poll(() => page.evaluate(() => activeArchiveDownload?.runId || '')).toBe('archiveRunFixture');
  await expect(tray).toBeVisible();

  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe('archiveRunFixture_clusterweave_results.zip');
  await expect(page.locator('#archive-download-title')).toHaveText('PACKAGE READY');
  await expect(page.locator('#archive-download-percent')).toHaveText('100%');

  await page.evaluate(() => {
    document.body.dataset.jobState = 'complete';
    document.getElementById('completion-callout').classList.remove('hidden');
  });
  for (const width of [1280, 760, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const geometry = await page.evaluate(() => {
      const trayBox = document.getElementById('archive-download-tray').getBoundingClientRect();
      const calloutBox = document.getElementById('completion-callout').getBoundingClientRect();
      const overlap = !(
        trayBox.right <= calloutBox.left
        || trayBox.left >= calloutBox.right
        || trayBox.bottom <= calloutBox.top
        || trayBox.top >= calloutBox.bottom
      );
      return {
        tray: { left: trayBox.left, right: trayBox.right, top: trayBox.top, bottom: trayBox.bottom },
        overlap,
        viewport: { width: innerWidth, height: innerHeight },
      };
    });
    expect(geometry.tray.left).toBeGreaterThanOrEqual(0);
    expect(geometry.tray.right).toBeLessThanOrEqual(geometry.viewport.width);
    expect(geometry.tray.top).toBeGreaterThanOrEqual(0);
    expect(geometry.tray.bottom).toBeLessThanOrEqual(geometry.viewport.height);
    expect(geometry.overlap).toBeFalsy();
  }
});
