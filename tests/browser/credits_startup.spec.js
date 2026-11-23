const { test, expect } = require('@playwright/test');

for (const width of [1440, 390]) {
  test(`credit tabs include scientific dependencies and base visuals at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/api/system/status*', route => route.fulfill({json:{online:true, submissions_open:true}}));
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:4173/');
    await expect(page.locator('#bootstrap-splash')).toBeHidden();
    await page.locator('#tool-credit-open').click();
    const drawer = page.getByRole('dialog', {name:'Upstream tool credit'});
    await expect(page.locator('#tool-credit-close')).toBeFocused();
    const base = drawer.getByRole('tab', {name:'BASE + VISUALS', exact:true});
    await drawer.getByRole('tab', {name:'Support', exact:true}).focus();
    await page.keyboard.press('End');
    await expect(base).toBeFocused();
    await expect(base).toHaveAttribute('aria-selected','true');
    const panel = drawer.getByRole('tabpanel', {name:'BASE + VISUALS', exact:true});
    await expect(panel).toBeVisible();
    for (const name of ['Docker Engine + CLI','Docker Compose','Apptainer','micromamba','Python','GNU Bash','R','NumPy','Matplotlib','Three.js','GSAP','CairoSVG']) {
      // Match the text node independently of the superscript license badge.
      expect(await panel.locator('.tool-credit-link').evaluateAll((links, expected) => links.some(a => a.firstChild.textContent.trim() === expected && a.querySelector('sup')?.textContent && a.target === '_blank' && a.rel === 'noopener'), name)).toBe(true);
    }
    expect(await panel.evaluate(n => n.scrollWidth <= n.clientWidth + 1)).toBe(true);
    await drawer.screenshot({path:testInfo.outputPath(`base-${width}.png`)});
    await page.keyboard.press('Home');
    await page.keyboard.press('ArrowRight');
    const web = drawer.getByRole('tabpanel', {name:'Web workflow', exact:true});
    for (const name of ['CD-HIT','NCBI BLAST+','MUSCLE 3','Exonerate','pplacer + guppy','GraPhlAn','TreeGraph 2','HMMER 2','HMMER 3','ETE 3','ConnecTF','TAIR']) {
      expect(await web.locator('.tool-credit-link').evaluateAll((links, expected) => links.some(a => a.firstChild.textContent.trim() === expected), name)).toBe(true);
    }
    expect(await web.evaluate(n => n.scrollWidth <= n.clientWidth + 1)).toBe(true);
    await drawer.screenshot({path:testInfo.outputPath(`web-${width}.png`)});
    await page.keyboard.press('Escape');
    await expect(drawer).toBeHidden();
    await expect(page.locator('#tool-credit-open')).toBeFocused();
    expect(errors).toEqual([]);
  });
}

test('plant startup row uses runtime capability independently of worker readiness', async ({page}, testInfo) => {
  let state = {ready:false, state:'bootstrapping', phase:'starting_worker', progress:95, capabilities:{stages:{plantismash:{available:true}}}};
  await page.route('**/api/system/status*', route => route.fulfill({json:state}));
  await page.goto('http://127.0.0.1:4173/');
  const row = page.locator('[data-bootstrap-step="plantismash"]');
  await expect(row).toContainText('plantiSMASH runtime');
  await expect(row).toHaveClass(/done/);
  await page.locator('#bootstrap-splash').screenshot({path:testInfo.outputPath('plant-startup.png')});
  state = {...state, capabilities:{stages:{plantismash:{available:false}}}};
  await expect(row).toContainText('Unavailable');
  await expect(row).not.toHaveClass(/done/);
  state = {...state, capabilities:{}};
  await expect(row).toContainText('Not yet verified');
  await expect(row).not.toHaveClass(/done/);
  // A ready worker must not turn unavailable or unreported plant support green.
  for (const available of [false, undefined]) {
    await page.evaluate(available => updateBootstrapSteps({ready:true, phase:'ready', capabilities:{stages:{plantismash:{available}}}}), available);
    await expect(row).not.toHaveClass(/done/);
  }
  // A missing plant runtime does not suppress another preparation stage.
  await page.evaluate(() => updateBootstrapSteps({ready:false, phase:'funannotate_image', capabilities:{stages:{plantismash:{available:false}}}}));
  await expect(page.locator('[data-bootstrap-step="funannotate_image"]')).toHaveClass(/running/);
  state = {...state, ready:true, phase:'ready'};
  await expect(page.locator('#bootstrap-splash')).toBeHidden();
});
