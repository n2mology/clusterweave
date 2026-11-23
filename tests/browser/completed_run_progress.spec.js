const {test,expect}=require('@playwright/test');
const fs=require('fs');const path=require('path');
const base='http://127.0.0.1:4173';
const evidence=process.env.CLUSTERWEAVE_REPAIR_EVIDENCE;
async function tree(page) {
  await page.goto(base+'/assets/progress-tree-contract.json');
  await page.setContent('<link rel="stylesheet" href="/assets/progress-tree.css"><style>body{margin:0;background:#121923;color:white;font:14px monospace}.log-terminal{padding:16px;box-sizing:border-box}</style><div class="log-terminal" id="log-terminal"></div>');
  await page.evaluate(async()=>{const m=await import('/assets/progress-tree.js');window.treeModule=m;window.contract=await(await fetch('/assets/progress-tree-contract.json')).json();window.consoleTree=m.createProgressTreeConsole({documentImpl:document,contract,createRawLineElement:text=>{const n=document.createElement('div');n.textContent=text;return n}})});
}
for(const width of [1440,390]) test(`independent genome branches, connected wrapping and raw diagnostics at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:1100});await tree(page);
  const long='Populus_trichocarpa_Nisqually_1_with_a_long_readable_input_name';
  const context=[
    {index:1,line:'Stage 1/4: running detection'},
    {index:2,line:`GENOME_PROGRESS genome=${long} stage=annotation percent=0 bar=[----------] message="Queued genome 2/3"`},
    {index:3,line:`GENOME_PROGRESS genome=${long} stage=annotation percent=1 bar=[----------] message="Validating supplied plant CDS annotations"`},
    {index:4,line:'GENOME_PROGRESS genome=Short stage=annotation percent=100 bar=[##########] message="Genome workflow complete"'},
  ];
  await page.evaluate(context=>consoleTree.hydrate({jobId:'fixture',logGeneration:'one',start:500,context,lines:['TOOL_RAW genome=Long tool=antismash stream=stdout TOOL_RAW genome=Long tool=antismash stream=stderr ERROR in raw diagnostic']}),context);
  await expect(page.locator(`[data-tree-key="genome:annotation:${long}"]`)).toContainText('Validating supplied plant CDS');
  await expect(page.locator('[data-tree-key="genome:annotation:Short"]')).toHaveAttribute('data-tree-state','complete');
  await expect(page.locator('#log-terminal')).not.toContainText('TOOL_RAW');
  await page.evaluate(long=>consoleTree.append({jobId:'fixture',logGeneration:'one',start:501,lines:[`TOOL_PROGRESS genome=${long} tool=plantismash phase=detect message="Finding plant biosynthetic gene clusters"`]}),long);
  await expect(page.locator(`[data-tree-key="tool:annotation:${long}:plantiSMASH"]`)).toContainText('Finding plant');
  await page.evaluate(long=>consoleTree.append({jobId:'fixture',logGeneration:'one',start:502,lines:[`GENOME_PROGRESS genome=${long} stage=plantismash percent=100 bar=[##########] message="Completed plantiSMASH: 76 BGCs SUCCESS_WITH_CALLS"`]}),long);
  await expect(page.locator(`[data-tree-key="genome:annotation:${long}"]`)).toHaveAttribute('data-tree-state','complete');
  await expect(page.locator(`[data-tree-key="tool:annotation:${long}:plantiSMASH"]`)).toHaveAttribute('data-tree-state','complete');
  await page.evaluate(()=>consoleTree.append({jobId:'fixture',logGeneration:'one',start:503,lines:["WARNING: Error changing the container working directory. Using '/' instead: chdir /nonexistent: no such file or directory"]}));
  await expect(page.locator('[data-tree-state="failed"]')).toHaveCount(0);
  expect(await page.locator('#log-terminal').evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true);
  const positions=await page.locator('.progress-tree-meter').evaluateAll(es=>es.map(e=>Math.round(e.getBoundingClientRect().left)));
  expect(new Set(positions).size).toBe(1);
  expect(await page.locator('.tree-connector.corner.last').count()).toBeGreaterThan(0);
  if(evidence)await page.screenshot({path:path.join(evidence,`tree-responsive-${width}.png`),fullPage:true});
  await page.evaluate(()=>consoleTree.setMode('raw'));
  await expect(page.locator('#log-terminal')).toContainText('TOOL_RAW');
});

test('retained completion logs keep all genome branches before loading history',async({browser})=>{
  test.skip(!evidence,'Private retained-run fixture is opt-in');
  for(const version of ['before','after']){
    const page=await browser.newPage({viewport:{width:1440,height:1200}});
    if(version==='before')await page.route('**/assets/progress-tree*',async route=>{const name=new URL(route.request().url()).pathname.split('/').pop();await route.fulfill({path:path.join(evidence,'before-source/web/static/assets',name)})});
    await tree(page);
    const snapshots=JSON.parse(fs.readFileSync(path.join(evidence,`progress-${version}.json`)));
    for(const snapshot of snapshots){
      await page.evaluate(s=>consoleTree.hydrate({jobId:'retained',logGeneration:s.time,...s}),snapshot);
      await page.screenshot({path:path.join(evidence,`tree-${version}-${snapshot.time.replaceAll(':','')}.png`),fullPage:true});
      if(version==='after'){
        await expect(page.locator('[data-tree-key^="genome:annotation:"]')).toHaveCount(3);
        await expect(page.locator('[data-tree-key="genome:annotation:Populus_trichocarpa_Nisqually-1"]')).toHaveAttribute('data-tree-state','complete');
        await expect(page.locator('#log-terminal')).not.toContainText('TOOL_RAW');
        await page.evaluate(s=>consoleTree.hydrate({jobId:'retained',logGeneration:s.time,start:s.start-1,lines:['earlier detail'],context:s.context,prepend:true}),snapshot);
        await expect(page.locator('[data-tree-key^="genome:annotation:"]')).toHaveCount(3);
      }
    }
    await page.close();
  }
});

test('DNA phase is driven by animation frames, independently of progress polling',async({page})=>{
  await page.goto(base+'/assets/progress-tree-contract.json');
  await page.setContent('<div id="region" style="width:800px;height:230px"><canvas id="canvas"></canvas></div>');
  const result=await page.evaluate(async()=>{
    const {WorkflowDnaProgress}=await import('/assets/workflow-dna-progress.js');
    // Exercise the real state/frame methods without GPU timing noise.
    const dna=Object.create(WorkflowDnaProgress.prototype);
    const calls=[];Object.assign(dna,{progress:0,profile:null,phase:0,helixSpin:{rotation:{x:0}},lastFrameTime:1000,lastRenderTime:1000,hasProgressState:false,disposed:false,suspended:false,motionPaused:false,baseAutoSpiral:true,reducedMotion:{matches:false},applyCameraProfile(){},applyColors(){},updateGeometry(){calls.push('geometry')},syncAnimationLoop(){},renderer:{render(){calls.push('render')}}});
    const phases=[];
    for(let i=1;i<=50;i++){dna.setProgress(i/100,{state:'running'});phases.push(dna.phase)}
    dna.renderFrame(2000);const first=dna.phase;
    for(let i=51;i<=90;i++)dna.setProgress(i/100,{state:'running'});
    dna.renderFrame(3000);const second=dna.phase;
    dna.reducedMotion.matches=true;dna.renderFrame(4000,true);
    return {phases,first,second,reduced:dna.phase,calls,progress:dna.progress};
  });
  expect(result.phases.every(x=>x===0)).toBe(true);
  expect(result.first).toBeCloseTo(1.15);expect(result.second).toBeCloseTo(2.3);expect(result.reduced).toBeCloseTo(2.3);
  expect(result.progress).toBe(.9);
});


test('real WebGL DNA keeps a continuous clock through asynchronous output updates',async({page})=>{
  await page.goto(base+'/assets/progress-tree-contract.json');
  await page.setContent('<div id="region" style="width:800px;height:230px"><canvas id="canvas"></canvas></div>');
  await page.evaluate(async()=>{
    const {WorkflowDnaProgress}=await import('/assets/workflow-dna-progress.js');
    window.dna=new WorkflowDnaProgress({canvas:document.querySelector('canvas'),region:document.querySelector('#region')});
    dna.setProgress(.3,{state:'running'});
    window.samples=[];const render=dna.renderFrame.bind(dna);
    dna.renderFrame=(now,force)=>{const before=dna.phase;render(now,force);if(dna.phase!==before)samples.push({time:now,phase:dna.phase,ball:dna.ball.position.x})};
    let updates=0;window.updates=setInterval(()=>dna.setProgress(.3+(++updates%40)/100,{state:'running'}),27);
  });
  await page.waitForTimeout(1800);
  const result=await page.evaluate(()=>{clearInterval(updates);const result={samples,phase:dna.phase,rotation:dna.helixSpin.rotation.x,renderCalls:dna.renderer.info.render.calls};dna.dispose();return result});
  expect(result.samples.length).toBeGreaterThan(8);
  for(let i=1;i<result.samples.length;i++){
    const a=result.samples[i-1],b=result.samples[i];
    expect(b.phase-a.phase).toBeCloseTo((b.time-a.time)/1000*1.15,5);
  }
  expect(result.rotation).toBeCloseTo(result.phase,5);
  expect(new Set(result.samples.map(s=>s.ball)).size).toBeGreaterThan(3);
  expect(result.renderCalls).toBeGreaterThan(0);
  if(evidence)fs.writeFileSync(path.join(evidence,'dna-webgl-samples.json'),JSON.stringify(result,null,2));
});
