const {test,expect}=require('@playwright/test');
const path=require('path');
const evidence=process.env.CLUSTERWEAVE_COHORT_SCREENSHOTS;
const decision={schema:'clusterweave-cohort-decision-v1',attempt:'attempt1',decision_id:'d'.repeat(64),state:'awaiting_decision',eligible:true,included:['Streptomyces'],excluded:['Arabidopsis','Septoria'],outcomes:[
 {genome_id:'Arabidopsis',taxon_group:'plants',state:'failed',category:'supplied_annotation_incompatible',reason:'Supplied annotation incompatible; plantiSMASH was not run.',counts:null},
 {genome_id:'Septoria',taxon_group:'fungi',state:'failed',category:'annotation_runtime_failure',reason:'Annotation/runtime failure; no complete detector outputs.',counts:null},
 {genome_id:'Streptomyces',taxon_group:'bacteria',state:'success',category:'validated_output',reason:'Validated bacterial outputs available.',counts:{antismash:36}},
],plan:{bigscape:'will run: validated cohort',summary:'will run: validated cohort',clinker:'will run: validated cohort; requires valid comparisons',figures:'will run: validated cohort',phylogeny:'skipped: not selected',nplinker:'blocked: target excluded'}};
for(const width of [1440,390]) test(`explicit cohort decision and single click at ${width}px`,async({page})=>{
 let status='awaiting_decision',posts=[];
 await page.setViewportSize({width,height:1100});
 await page.route('**/api/**',async route=>{
  const u=new URL(route.request().url());
  if(u.pathname.endsWith('/continue')){posts.push(route.request().postDataJSON());status='pending';return route.fulfill({status:202,json:{status:'pending',duplicate:false}})}
  if(u.pathname.endsWith('/artifacts'))return route.fulfill({json:{artifacts:[],result_index_state:'stored'}});
  if(u.pathname.endsWith('/activity'))return route.fulfill({json:{events:[],genome_progress:[]}});
  if(u.pathname==='/api/results/cohort-fixture')return route.fulfill({json:{id:'cohort-fixture',public_run_id:'cohort-fixture',name:'Mixed cohort',status,stage:status,analysis_scope:'mixed',cohort_decision:decision,public_events:[],genome_progress:[]}});
  return route.fulfill({json:{online:true,submissions_open:false,jobs:[]}});
 });
 await page.goto('http://127.0.0.1:4173');
 await page.waitForFunction(()=>typeof loadJob==='function');
 await page.evaluate(()=>loadJob('cohort-fixture',false,{publicResult:true}));
 const panel=page.locator('#cohort-decision');
 await expect(panel).toBeVisible();
 await expect(panel).toHaveCSS('border-top-width','3px');
 await expect(panel.locator('.module-head')).toBeVisible();
 await expect(panel.locator('.cohort-genome')).toHaveCount(3);
 for(const phrase of ['Arabidopsis','Supplied annotation incompatible','plantiSMASH was not run','Septoria','Annotation/runtime failure','Streptomyces','36 BGCs','blocked: target excluded'])await expect(panel).toContainText(phrase);
 expect(await panel.evaluate(el=>el.scrollWidth-el.clientWidth)).toBeLessThanOrEqual(1);
 if(evidence)await panel.screenshot({path:path.join(evidence,`decision-${width}.png`)});
 const button=panel.getByRole('button',{name:'Continue with 1 genome; exclude 2',exact:true});
 await button.click();
 await expect.poll(()=>posts.length).toBe(1);
 expect(posts[0]).toEqual({decision_id:decision.decision_id,included:decision.included,excluded:decision.excluded});
 await expect(panel.getByRole('button')).toHaveCount(0);
 status='completed_with_exclusions';
 await page.evaluate(()=>loadJob('cohort-fixture',false,{publicResult:true}));
 await expect(panel.getByRole('heading', {level:3})).toHaveText('Completed with exclusions');
 await page.evaluate(()=>{document.body.dataset.jobState='complete';document.body.dataset.resultsAvailable='true';});
 await expect(panel).toBeVisible();
 if(width===1440)expect((await panel.boundingBox()).width).toBeGreaterThan(700);
 await expect(panel).toContainText('failed');
 if(evidence)await panel.screenshot({path:path.join(evidence,`completed-exclusions-${width}.png`)});
});
test('all-failure outcome has no continuation action',async({page})=>{
 const blocked={...decision,eligible:false,state:'failed',included:[],excluded:['Arabidopsis','Septoria'],outcomes:decision.outcomes.slice(0,2)};
 await page.route('**/api/**',route=>route.fulfill({json:new URL(route.request().url()).pathname==='/api/results/failed-fixture'?{id:'failed-fixture',public_run_id:'failed-fixture',status:'failed',stage:'annotation',name:'All failed',analysis_scope:'mixed',cohort_decision:blocked,public_events:[],genome_progress:[]}:{artifacts:[],events:[],online:true}}));
 await page.goto('http://127.0.0.1:4173');await page.waitForFunction(()=>typeof loadJob==='function');await page.evaluate(()=>loadJob('failed-fixture',false,{publicResult:true}));
 const panel=page.locator('#cohort-decision');await expect(panel).toContainText('Continuation is unavailable');await expect(panel.getByRole('button')).toHaveCount(0);
});
