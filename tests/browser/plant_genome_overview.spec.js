const {test,expect}=require('@playwright/test');
for(const kind of ['combined-native','legacy-record-index']) test(`plant report preserves its own native overview: ${kind}`,async({page})=>{
 await page.goto('http://127.0.0.1:4173/');
 const result=await page.evaluate(async kind=>{
  const {createResultReaderBoundary}=await import('/assets/result-reader-boundary.js');
  const context={runId:'fixture',byKey:new Map(),byId:new Map()};let fetched=0;
  const boundary=createResultReaderBoundary({state:{activeResultArtifactByKey:context.byKey,activeResultArtifactById:context.byId},escapeHtml:String,resolveResultArtifact:async()=>{throw Error('Unexpected reconstruction fetch')},resultFetch:async()=>{fetched++;throw Error('Unexpected report fetch')}});
  const key=boundary.installResultArtifactDescriptor({id:'R'.repeat(22),filename:'index.html',category:'plantismash',kind:'html',bundle_id:'bundle'},context);
  const source=kind==='combined-native'?'<table id="cluster-overview"><thead><tr><th>Record</th><th>CD-HIT</th></tr></thead><tbody><tr><td>OriginalRecord</td><td>3</td></tr></tbody></table><div id="cluster-76">Native final cluster</div>':'<ul><li><a href="shards/000001/native/index.html">OriginalRecord</a></li></ul>';
  const html=await boundary.rewriteHtmlResultAssets(source,'job',key,{allowToolBundleScripts:true,resultContext:context});
  const doc=new DOMParser().parseFromString(html,'text/html');
  return {fetched,custom:!!doc.querySelector('#clusterweave-plant-genome-overview'),native:doc.querySelector('#cluster-76')?.textContent,link:doc.querySelector('a')?.getAttribute('href'),headers:[...doc.querySelectorAll('th')].map(x=>x.textContent)};
 },kind);
 expect(result.fetched).toBe(0);expect(result.custom).toBe(false);
 if(kind==='combined-native'){expect(result.native).toBe('Native final cluster');expect(result.headers).toEqual(['Record','CD-HIT']);}
 else expect(result.link).toBe('shards/000001/native/index.html');
});
