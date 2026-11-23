const {test,expect}=require('@playwright/test');
const fs=require('fs');const path=require('path');
const evidence=process.env.CLUSTERWEAVE_EXTRAS_EVIDENCE;
for(const width of [1440,390])test(`real plant extra-feature graphics work within isolation at ${width}px`,async({page})=>{
  test.skip(!evidence,'Private real native extra-feature outputs are opt-in');test.setTimeout(120000);
  const a=JSON.parse(fs.readFileSync(path.join(evidence,'browser-extra-access.json')));
  await page.setViewportSize({width,height:1000});
  await page.goto(`${process.env.CLUSTERWEAVE_EXTRAS_BASE_URL||"http://127.0.0.1:4181"}/#/results/${a.run_id}/${a.token}`);
  await page.waitForFunction(()=>typeof activeResultFiles!=='undefined'&&activeResultFiles.length>0);
  await page.locator('[data-output-key="plantismash"]').click();
  const pending=page.waitForEvent('popup');await page.locator('#files-container').getByRole('link',{name:'Open',exact:true}).click();
  const popup=await pending;await popup.setViewportSize({width,height:1000});
  const errors=[];const failures=[];popup.on('pageerror',e=>errors.push(String(e)));popup.on('response',r=>{if(r.status()>=400)failures.push(r.status())});
  await expect(popup.locator('iframe')).toHaveAttribute('sandbox','allow-scripts allow-downloads',{timeout:30000});
  const f=popup.frameLocator('#clusterweave-tool-result-preview');
  if(a.record_id){
    await expect(f.locator('#clusterweave-plant-genome-overview')).toBeVisible();
    await f.locator('#clusterweave-plant-records summary').click();
    await f.getByRole('link',{name:a.record_id,exact:true}).click();
  }
  await expect(f.locator('#cluster-overview')).toBeVisible();
  await f.getByRole('link',{name:'Cluster 1',exact:true}).click();
  await expect(f.locator('#knownclusterblast-1-svg svg')).toHaveCount(1);
  await expect(f.locator('#knownclusterblast-1-select')).toContainText('cucurbitacin C (33%');
  const selector=f.locator('#clusterblast-1-select');
  const values=await selector.locator('option').evaluateAll(nodes=>nodes.map(n=>n.value));
  expect(values.length).toBeGreaterThan(2);
  let previous=await f.locator('#clusterblast-1-svg').innerHTML();
  for(const value of values.slice(1,3)){
    await selector.selectOption(value);
    await expect(f.locator('#clusterblast-1-svg svg')).toHaveCount(1);
    const next=await f.locator('#clusterblast-1-svg').innerHTML();expect(next).not.toBe(previous);previous=next;
    const pendingDownload=popup.waitForEvent('download');await f.locator('#clusterblast-1-download').click();
    const download=await pendingDownload;expect(download.suggestedFilename()).toContain(path.basename(value));
    await download.saveAs(path.join(evidence,`extra-${width}-${path.basename(value)}`));
  }
  await f.locator('#cl-summary-cluster-1 tr').filter({hasText:'LOC18101168'}).locator('td').last().click();
  const dialog=f.locator('#clusterweave-subgroup-view');await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('LOC18101168');await expect(dialog.locator('img')).toHaveCount(2);
  await expect.poll(()=>dialog.locator('img').evaluateAll(nodes=>nodes.every(i=>i.complete&&i.naturalWidth>0))).toBe(true);
  const pendingTree=popup.waitForEvent('download');await dialog.getByRole('link',{name:'Download tree',exact:true}).click();
  const tree=await pendingTree;expect(tree.suggestedFilename()).toContain('LOC18101168.svg');await tree.saveAs(path.join(evidence,`subgroup-${width}.svg`));
  await popup.screenshot({path:path.join(evidence,`extra-subgroup-${width}.png`),fullPage:true});
  await dialog.getByRole('button',{name:'Close',exact:true}).click();await expect(dialog).toHaveCount(0);
  const csvControl=f.locator('#cluster-1').getByRole('button',{name:'Download CSV',exact:true});
  await expect(csvControl).toBeVisible();
  let unexpectedDownloads=0;const countUnexpected=()=>unexpectedDownloads++;popup.on('download',countUnexpected);
  await csvControl.evaluate(el=>el.click());await popup.waitForTimeout(150);expect(unexpectedDownloads).toBe(0);popup.off('download',countUnexpected);
  const csvPending=popup.waitForEvent('download');await csvControl.click();const csvDownload=await csvPending;
  expect(csvDownload.suggestedFilename()).toBe('tfbs_motifs_per_cds_cluster1_NC_037291.2.csv');
  const csvFile=path.join(evidence,`tfbs-aggregate-${width}.csv`);await csvDownload.saveAs(csvFile);
  expect(fs.readFileSync(csvFile,'utf8')).toContain('CDS,CDS strand,TSS,Window,Motifs,#Hits');
  for(const [label,extension] of [[/Download full TFBS hits for this BGC/,'.tsv.gz'],[/Download TFBS hits for all BGCs/,'.csv']]){
    const pending=popup.waitForEvent('download');await f.locator('#cluster-1').getByRole('link',{name:label}).click();
    const download=await pending;expect(download.suggestedFilename().endsWith(extension)).toBe(true);await download.saveAs(path.join(evidence,`tfbs-${width}-${download.suggestedFilename()}`));
  }
  const security=await f.locator('body').evaluate(body=>({csp:body.ownerDocument.querySelector('meta[http-equiv="Content-Security-Policy"]').content,storage:(()=>{try{localStorage.getItem('x');return 'accessible'}catch(e){return e.name}})()}));
  expect(security.csp).toContain("connect-src 'none'");expect(security.csp).not.toContain('unsafe-eval');expect(security.storage).toBe('SecurityError');
  await popup.screenshot({path:path.join(evidence,`extra-comparison-${width}.png`),fullPage:true});
  await f.locator('[id$="LOC18101168-orf"]').first().click();
  await f.getByRole('link',{name:'View smCOG seed phylogenetic tree with this gene',exact:true}).filter({visible:true}).click();
  await expect(f.locator('#cluster-overview')).toHaveCount(0);
  await expect(f.locator('img')).toHaveCount(1);
  await expect(f.locator('img')).toHaveAttribute('alt','LOC18101168.png');
  await expect.poll(()=>f.locator('img').evaluate(i=>i.complete&&i.naturalWidth>0)).toBe(true);
  await popup.screenshot({path:path.join(evidence,`extra-smcog-${width}.png`),fullPage:true});
  expect(errors).toEqual([]);expect(failures).toEqual([]);
});
