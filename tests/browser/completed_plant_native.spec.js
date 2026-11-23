const {test,expect}=require('@playwright/test');
const fs=require('fs');const path=require('path');
const evidence=process.env.CLUSTERWEAVE_REPAIR_EVIDENCE;
for(const width of [1440,390])test(`retained plant report opens record and cluster in its sandbox at ${width}px`,async({page})=>{
  test.skip(!evidence,'Private retained native outputs are opt-in');
  const a=JSON.parse(fs.readFileSync(path.join(evidence,'browser-fixture-access.json')));
  await page.setViewportSize({width,height:1000});
  const errors=[];const failures=[];
  await page.goto(`http://127.0.0.1:4181/#/results/${a.run_id}/${a.token}`);
  await page.waitForFunction(()=>typeof activeResultFiles!=='undefined'&&activeResultFiles.length>0);
  const block = page.locator('[data-output-key="plantismash"]');
  await expect(block).toBeEnabled();
  await block.click();
  const popupPromise=page.waitForEvent('popup');await page.locator('#files-container').getByRole('link',{name:'Open',exact:true}).click();
  const popup=await popupPromise;await popup.setViewportSize({width,height:1000});popup.on('pageerror',e=>errors.push(String(e)));popup.on('response',r=>{if(r.status()>=400)failures.push(r.status())});
  await expect(popup.locator('iframe')).toHaveAttribute('sandbox','allow-scripts allow-downloads');
  const frame=popup.frameLocator('#clusterweave-tool-result-preview');
  // Opening the genome accounts for every BGC before entering a native record.
  await expect(frame.locator("#clusterweave-plant-genome-overview tbody tr")).toHaveCount(76);
  await frame.locator("#clusterweave-plant-records summary").click();
  await frame.getByRole("link",{name:"NC_037285.2",exact:true}).click();
  await expect(frame.locator('#cluster-overview')).toBeVisible({timeout:30000});
  const resources = await frame.locator('body').evaluate(body => ({
    styles: body.ownerDocument.styleSheets.length, scripts: body.ownerDocument.scripts.length,
    brokenImages: [...body.ownerDocument.images].filter(i => i.getAttribute('src') && (!i.complete || !i.naturalWidth)).length,
  }));
  expect(resources.styles).toBeGreaterThan(0);expect(resources.scripts).toBeGreaterThan(0);expect(resources.brokenImages).toBe(0);
  await frame.getByRole('link',{name:'Cluster 1',exact:true}).click();
  await expect(frame.locator('body')).toContainText('Location: 455238 - 544224 nt');
  await expect(frame.locator('body')).toContainText('LOC7483252');
  for(const [name,extension] of [['Download cluster GenBank file','.gbk']]) {
    const pending=popup.waitForEvent('download');await frame.locator('#cluster-1').getByRole('link',{name,exact:true}).click();const dl=await pending;
    expect(dl.suggestedFilename().endsWith(extension)).toBeTruthy();await dl.saveAs(path.join(evidence,`native-${width}-${dl.suggestedFilename()}`));
  }
  await frame.locator('#download').click();
  await expect(frame.locator('#downloadmenu')).toContainText('not produced');
  const pendingXls=popup.waitForEvent('download');await frame.getByRole('link',{name:'Download XLS overview file',exact:true}).click();const xls=await pendingXls;
  expect(xls.suggestedFilename()).toMatch(/\.xlsx$/);await xls.saveAs(path.join(evidence,`native-${width}-${xls.suggestedFilename()}`));
  await frame.locator('#download').click();
  await frame.locator('#cluster-1-rules-header').click();
  await expect(frame.locator('body')).toContainText('Hide pHMM detection rules used');
  await popup.screenshot({path:path.join(evidence,`native-functional-${width}.png`),fullPage:true});
  await frame.getByRole('link',{name:'Overview',exact:true}).click();
  await expect(frame.getByRole('link',{name:'Cluster 2',exact:true})).toBeVisible();
  await popup.getByRole('button',{name:'Genome overview',exact:true}).click();
  await frame.locator('#clusterweave-plant-records summary').click();
  await expect(frame.getByRole('link',{name:'NC_037285.2',exact:true})).toBeVisible();
  await expect(frame.locator('#clusterweave-plant-records a')).toHaveCount(33);
  await frame.getByRole('link',{name:'NW_026291140.1',exact:true}).click();
  await expect(frame.locator('body')).toContainText('No secondary metabolite clusters were found in the input sequence(s)');
  await expect(frame.locator('#cluster-overview tbody tr')).toHaveCount(1);
  await popup.screenshot({path:path.join(evidence,`native-empty-${width}.png`),fullPage:true});
  expect(errors).toEqual([]);expect(failures).toEqual([]);
  await popup.close();
  await page.locator('[data-output-key="summaries"]').click();
  await page.getByRole('combobox',{name:'Kingdom',exact:true}).selectOption('plants');
  await expect(page.locator('.all-bgc-table tbody tr')).toHaveCount(76);
  await expect(page.locator('.all-bgc-table tbody tr').first()).toContainText('—');
  const sample=page.locator('.all-bgc-table tbody tr').filter({hasText:'NC_037291.2.cluster001'});
  await expect(sample).toHaveCount(1);
  await expect(sample.locator('td').nth(4)).toHaveText('NC_037291.2.cluster001');
  await expect(sample.locator('td').nth(5)).toHaveText('saccharide');
  await expect(sample.locator('td').nth(16)).toHaveText('UDPGT_2, p450');
  await expect(sample.locator('td').nth(17)).toHaveText('—');
  await expect(sample.locator('td').nth(18)).toHaveText('3');
  await expect(sample.locator('td').nth(19)).toHaveText('—');
  await expect(sample.locator('td').nth(20)).toHaveText('—');
  await expect(sample.locator('td').nth(21)).toHaveText('—');
  await page.screenshot({path:path.join(evidence,`plant-summary-${width}.png`),fullPage:true});
  await page.evaluate(()=>switchSummaryView('atlas'));
  await expect(page.locator('[data-atlas-domain="plants"]')).toContainText('69 total');
  await expect(page.locator('[data-atlas-domain="plants"] .atlas-table tbody tr')).toHaveCount(20);
  await expect(page.locator('[data-atlas-domain="plants"]')).toContainText('Similarity searches not run');
});

for(const width of [1440,390])test(`retained comparative Clinker panels render and scroll stably at ${width}px`,async({page})=>{
  test.skip(!evidence,'Private retained native outputs are opt-in');
  const a=JSON.parse(fs.readFileSync(path.join(evidence,'browser-fixture-access.json')));
  await page.setViewportSize({width,height:1000});
  await page.goto(`http://127.0.0.1:4181/#/results/${a.run_id}/${a.token}`);
  await page.waitForFunction(()=>typeof activeResultFiles!=='undefined'&&activeResultFiles.length>0);
  await page.locator('[data-output-key="synteny"]').click();
  await expect(page.getByRole('tab',{name:/PLANT PANELS/})).toHaveCount(0);
  for(const [taxon,tab] of [['fungi',/FUNGAL PANELS/],['bacteria',/BACTERIAL PANELS/]]){
    await page.getByRole('tab',{name:tab}).click();
    const reader=page.locator('.clinker-reader');await expect(reader).toHaveAttribute('data-clinker-taxon',taxon);
    const pending=page.waitForEvent('popup');await reader.getByRole('link',{name:'Open',exact:true}).click();const popup=await pending;await popup.setViewportSize({width,height:1000});
    const errors=[];popup.on('pageerror',e=>errors.push(String(e)));
    await expect(popup.locator('#clusterweave-clinker-preview')).toHaveAttribute('sandbox','allow-scripts allow-downloads');
    const f=popup.frameLocator('#clusterweave-clinker-preview');
  await expect(f.locator('#clusterweave-panel-provenance')).toHaveCount(0);
    await expect.poll(()=>f.locator('svg polygon').count()).toBeGreaterThan(0);
    await expect(f.locator('#input-label-rotation')).toHaveValue('45');
    await popup.waitForTimeout(700);
    const samples = await f.locator('#plot').evaluate(async el => {
      const result=[];el.scrollLeft=100;el.scrollTop=70;
      for(let i=0;i<12;i++){result.push([el.clientWidth,el.clientHeight,el.scrollWidth,el.scrollHeight,el.scrollLeft,el.scrollTop]);await new Promise(r=>setTimeout(r,100));}
      return result;
    });
    expect(new Set(samples.map(JSON.stringify)).size).toBe(1);
    fs.writeFileSync(path.join(evidence,`clinker-scroll-${taxon}-${width}.json`),JSON.stringify(samples));
    for(const selector of ['#btn-save-svg','#btn-save-data']){
      const downloaded=popup.waitForEvent('download');await f.locator(selector).click();const dl=await downloaded;
      expect(dl.suggestedFilename()).toMatch(/\.(svg|json)$/);await dl.saveAs(path.join(evidence,`clinker-${taxon}-${width}-${dl.suggestedFilename()}`));
    }
    await popup.screenshot({path:path.join(evidence,`clinker-${taxon}-${width}.png`),fullPage:true});expect(errors).toEqual([]);await popup.close();
  }
});
