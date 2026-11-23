const {test,expect}=require('@playwright/test');
test('native plant reader preserves opaque artifact and producer categories', async ({page})=>{
  await page.goto('http://127.0.0.1:4173');
  const data=await page.evaluate(()=>{
    document.body.innerHTML='<div id="files-container"></div>';
    activeJobId='PPPPPPPPPPPPPPPPPPPPPP';activePublicRunId=activeJobId;
    activeJobMeta={id:activeJobId,public_run_id:activeJobId,status:'success',analysis_scope:'plants',taxon_counts:{plants:1,total:1}};
    const keys=installResultArtifactDescriptors([{id:'NNNNNNNNNNNNNNNNNNNNNN',category:'plantismash',kind:'html',role:'index',filename:'index.html',label:'Plant native output',mime:'text/html; charset=utf-8',bytes:200,genome_label:'Plant_one',bundle_id:'PlantNativeBundle000001',previewable:true,downloadable:true}],{replace:true});
    const views=uniqueToolHtmlArtifacts(keys,'plantismash');renderToolHtmlReader(activeJobId,'plantismash',views);
    return {count:views.length,id:resultArtifactId(views[0]?.path),label:resultCategoryLabel('plantismash')};
  });
  expect(data).toEqual({count:1,id:'NNNNNNNNNNNNNNNNNNNNNN',label:'PLANTISMASH'});
  await expect(page.locator('#files-container')).toContainText('Per-genome plantiSMASH HTML views.');
  await expect(page.locator('#files-container .result-tool-row')).toHaveCount(1);
});

test('native plant reader stays concise with a separate indexed archive',async({page})=>{
  await page.goto('http://127.0.0.1:4173');
  await page.evaluate(()=>{
    document.body.innerHTML='<div id="files-container"></div>';activeJobId='PPPPPPPPPPPPPPPPPPPPPP';activePublicRunId=activeJobId;
    rememberOpenedRun(activeJobId,'fixture-read-token',{id:activeJobId,public_run_id:activeJobId,status:'success'});
    activeResultFiles=installResultArtifactDescriptors([
      {id:'NNNNNNNNNNNNNNNNNNNNNN',category:'plantismash',kind:'html',role:'index',filename:'index.html',label:'Plant',bundle_id:'PlantNativeBundle000001',previewable:true,downloadable:true},
      {id:'AAAAAAAAAAAAAAAAAAAAAA',category:'plantismash',kind:'document',role:'complete-native-plant-archive',filename:'complete-native.zip',label:'Plant native archive',bundle_id:'PlantNativeBundle000001',downloadable:true}
    ],{replace:true});
    renderToolHtmlReader(activeJobId,'plantismash',uniqueToolHtmlArtifacts(activeResultFiles,'plantismash'));
  });
  await expect(page.getByRole('link',{name:'Download native reports',exact:true})).toHaveCount(0);
  await expect(page.getByRole('link',{name:'Download',exact:true})).toHaveCount(1);
  await expect(page.getByRole('link',{name:'Open',exact:true})).toHaveCount(1);
});

for (const width of [1440,390]) test(`plant Results Block is enabled by its actual indexed report at ${width}px`, async ({page}) => {
  await page.setViewportSize({width,height:900});
  await page.goto('http://127.0.0.1:4173');
  await page.evaluate(() => {
    activeJobId='PPPPPPPPPPPPPPPPPPPPPP';activePublicRunId=activeJobId;
    activeJobMeta={id:activeJobId,status:'success',analysis_scope:'plants',taxon_counts:{plants:1,total:1}};
    setActiveSavedAnalysisContext(activeJobMeta);
    rememberOpenedRun(activeJobId,'fixture-read-token',activeJobMeta);
    const keys=installResultArtifactDescriptors([{id:'NNNNNNNNNNNNNNNNNNNNNN',category:'plantismash',kind:'html',role:'index',filename:'index.html',label:'Plant',bundle_id:'PlantNativeBundle000001',previewable:true,downloadable:true}],{replace:true});
    document.body.innerHTML='<div id="result-bubble-panel"></div><div id="files-container"></div>';
    resultDashboardOpen=true;
    renderResultBubblePanel(keys,'success');
  });
  const tab=page.locator('[data-output-key="plantismash"]');
  await expect(tab).toBeEnabled();await tab.click();
  await expect(page.locator('#files-container').getByRole('link',{name:'Open',exact:true})).toBeVisible();
});
