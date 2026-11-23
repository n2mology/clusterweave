const {test,expect}=require('@playwright/test');
const fs=require('fs'),path=require('path');
const evidence=process.env.CLUSTERWEAVE_FINAL_PANELS;
for(const width of [1440,390])test(`actual Clinker generated HTML and SVG/data exports at ${width}px`,async({page})=>{
 test.skip(!evidence,'Private retained actual panel outputs are opt-in');test.setTimeout(120000);
 const panels=JSON.parse(fs.readFileSync(path.join(evidence,'panel-index.json')));
 await page.setViewportSize({width,height:1000});const results=[];
 for(const panel of panels)for(const version of ['before','after']){
  await page.route('http://127.0.0.1/__qa_panel',r=>r.fulfill({path:panel[version],contentType:'text/html'}));
  await page.goto('http://127.0.0.1/__qa_panel');await expect.poll(()=>page.locator('svg polygon').count()).toBeGreaterThan(0);
  await page.waitForTimeout(400);
  const geometry=await page.locator('svg.clusterMap').evaluate(svg=>{
   const g=svg.querySelector('g.clusterMapG'),legend=g.querySelector('g.legend');const legendBox=legend.getBoundingClientRect();legend.style.display='none';const drawing=g.getBoundingClientRect();legend.style.display='';
   return {legend:{x:legendBox.x,y:legendBox.y,width:legendBox.width,height:legendBox.height},drawing:{x:drawing.x,y:drawing.y,width:drawing.width,height:drawing.height},groups:[...g.querySelectorAll('g')].slice(0,8).map(x=>x.getAttribute('class'))};
  });
  const row={taxon:panel.taxon,version,width,geometry};results.push(row);
  await expect(page.locator('#input-label-rotation')).toHaveValue('45');
  if(version==='after'){
   await expect(page.locator('#clusterweave-panel-provenance')).toHaveCount(0);
   expect(geometry.legend.x).toBeGreaterThanOrEqual(geometry.drawing.x+geometry.drawing.width+40);
   if(panel.taxon==='fungi'){
    await expect(page.locator('svg')).not.toContainText('[Laccaria_bicolor_S238N-H82]');
    await expect(page.locator('svg')).toContainText('NW 001889893.1.region001');
    await expect(page.locator('svg')).toContainText('NW 001889893.1.region002');
   }
   const plot=page.locator('#plot');row.scroll=await plot.evaluate(async el=>{el.scrollLeft=120;el.scrollTop=70;let rows=[];for(let i=0;i<12;i++){rows.push([el.clientWidth,el.clientHeight,el.scrollWidth,el.scrollHeight,el.scrollLeft,el.scrollTop]);await new Promise(r=>setTimeout(r,100));}return rows;});
   expect(new Set(row.scroll.map(JSON.stringify)).size).toBe(1);
   for(const [button,extension] of [['#btn-save-svg','svg'],['#btn-save-data','json']]){
    const pending=page.waitForEvent('download');await page.locator(button).click();const dl=await pending;const target=path.join(evidence,`${panel.taxon}-${width}.${extension}`);await dl.saveAs(target);
    if(extension==='json'){
     const data=JSON.parse(fs.readFileSync(target,'utf8'));row.dataExportKeys=Object.keys(data);
     // Native data download retains all clusters, groups and scientific links.
     const raw=fs.readFileSync(panel.after,'utf8');const original=JSON.parse(raw.split('const data=')[1].split(';function serialise')[0]);
     const emitted=data.data||data;expect(emitted.clusters.length).toBe(original.clusters.length);expect(emitted.links.length).toBe(original.links.length);
    }
   }
   await plot.evaluate(el=>{el.scrollLeft=0;el.scrollTop=0;});
   await page.screenshot({path:path.join(evidence,`${panel.taxon}-${width}-after-left.png`)});
   await plot.evaluate(el=>{el.scrollLeft=el.scrollWidth;el.scrollTop=0;});
   await page.screenshot({path:path.join(evidence,`${panel.taxon}-${width}-after-right.png`)});
   // Verify the actual downloaded SVG retains right-side legend placement.
   await page.route('http://127.0.0.1/__qa_export',r=>r.fulfill({path:path.join(evidence,`${panel.taxon}-${width}.svg`),contentType:'image/svg+xml'}));
   await page.goto('http://127.0.0.1/__qa_export');
   const exported=await page.locator('svg').evaluate(svg=>{const g=svg.querySelector('g.clusterMapG'),l=g.querySelector('g.legend');const a=l.getBoundingClientRect();l.style.display='none';const b=g.getBoundingClientRect();l.style.display='';return {legendX:a.x,drawingRight:b.right,width:svg.width.baseVal.value,height:svg.height.baseVal.value}});
   expect(exported.legendX).toBeGreaterThan(exported.drawingRight+40);row.exported=exported;
  }else await page.screenshot({path:path.join(evidence,`${panel.taxon}-${width}-before.png`)});
  await page.unroute('http://127.0.0.1/__qa_panel');
  fs.writeFileSync(path.join(evidence,`geometry-${width}.json`),JSON.stringify(results,null,2));
 }
});
