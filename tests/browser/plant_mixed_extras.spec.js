const {test,expect}=require('@playwright/test');
const fs=require('fs'),path=require('path');
const evidence=process.env.CLUSTERWEAVE_MIXED_EXTRAS_EVIDENCE;
const base=process.env.CLUSTERWEAVE_MIXED_EXTRAS_BASE_URL||'http://127.0.0.1:4182';
for(const width of [1440,390])test(`real extras summary and comparative panels at ${width}px`,async({page})=>{
 test.skip(!evidence,'Private real output fixture is opt-in');test.setTimeout(120000);
 const a=JSON.parse(fs.readFileSync(path.join(evidence,'mixed-access.json')));
 await page.setViewportSize({width,height:1000});await page.goto(`${base}/#/results/${a.run_id}/${a.token}`);
 await page.waitForFunction(()=>typeof activeResultFiles!=='undefined'&&activeResultFiles.length>0);
 await page.locator('[data-output-key="summaries"]').click();
 await page.getByRole('combobox',{name:'Kingdom',exact:true}).selectOption('plants');
 const sample=page.locator('.all-bgc-table tbody tr').filter({hasText:'NC_037291.2.cluster001'});
 await expect(sample).toHaveCount(1);
 for(const [column,value] of [[4,'NC_037291.2.cluster001'],[5,'saccharide'],[16,'UDPGT_2, p450'],[17,'—'],[18,'3'],[19,'33'],[21,'cucurbitacin C']])await expect(sample.locator('td').nth(column)).toHaveText(value);
 await expect(sample.locator('td').nth(20).locator('a')).toHaveAttribute('href',/mibig\.secondarymetabolites\.org\/repository\/BGC0001315\.3/);
 await expect(page.locator('.all-bgc-table thead')).not.toContainText('Native');
 await expect(page.locator('.all-bgc-table')).not.toContainText('plantismash-2.0.4-private-repeat2');
 await page.locator('#files-container').screenshot({path:path.join(evidence,`mixed-summary-${width}.png`)});
 await page.evaluate(()=>switchSummaryView('atlas'));
 await expect(page.locator('[data-atlas-domain="plants"]')).toContainText(a.atlas_plant_product||'cucurbitacin C');
 await expect(page.locator('[data-atlas-domain="plants"]')).not.toContainText('Similarity searches not run');
 await page.locator('#files-container').screenshot({path:path.join(evidence,`mixed-atlas-${width}.png`)});
 await page.locator('[data-output-key="synteny"]').click();
 for(const [taxon,tab,accession] of [['plants',/PLANT PANELS/,'BGC0001315'],['fungi',/FUNGAL PANELS/,'BGC0001248'],['bacteria',/BACTERIAL PANELS/,'BGC0002416']]){
  await page.getByRole('tab',{name:tab}).click();const reader=page.locator('.clinker-reader');await expect(reader).toHaveAttribute('data-clinker-taxon',taxon);
  const pending=page.waitForEvent('popup');await (a.panel_labels?.[taxon]?reader.locator('tbody tr').filter({hasText:a.panel_labels[taxon]}):reader).getByRole('link',{name:'Open',exact:true}).click();const popup=await pending;await popup.setViewportSize({width,height:1000});const errors=[];popup.on('pageerror',e=>errors.push(String(e)));
  await expect(popup.locator('#clusterweave-clinker-preview')).toHaveAttribute('sandbox','allow-scripts allow-downloads');const f=popup.frameLocator('#clusterweave-clinker-preview');
  await expect(f.locator('#clusterweave-panel-provenance')).toHaveCount(0);
  await expect.poll(()=>f.locator('svg polygon').count()).toBeGreaterThan(0);await expect(f.locator('#input-label-rotation')).toHaveValue('45');await popup.waitForTimeout(700);
  const samples=await f.locator('#plot').evaluate(async el=>{const rows=[];el.scrollLeft=100;el.scrollTop=70;for(let i=0;i<12;i++){rows.push([el.clientWidth,el.clientHeight,el.scrollWidth,el.scrollHeight,el.scrollLeft,el.scrollTop]);await new Promise(r=>setTimeout(r,100));}return rows;});expect(new Set(samples.map(JSON.stringify)).size).toBe(1);fs.writeFileSync(path.join(evidence,`mixed-scroll-${taxon}-${width}.json`),JSON.stringify(samples));
  for(const selector of ['#btn-save-svg','#btn-save-data']){const ready=popup.waitForEvent('download');await f.locator(selector).click();const dl=await ready;expect(dl.suggestedFilename()).toMatch(/\.(svg|json)$/);await dl.saveAs(path.join(evidence,`mixed-${taxon}-${width}-${dl.suggestedFilename()}`));}
  await f.locator('#plot').evaluate(el=>{el.scrollLeft=0;el.scrollTop=0;});
  await popup.screenshot({path:path.join(evidence,`mixed-clinker-${taxon}-${width}.png`)});expect(errors).toEqual([]);await popup.close();
 }
});
