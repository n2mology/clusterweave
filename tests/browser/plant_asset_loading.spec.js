const {test,expect}=require('@playwright/test');

async function exercise(page, scenario) {
  await page.goto('http://127.0.0.1:4173/');
  return page.evaluate(async scenario=>{
    const {createResultReaderBoundary}=await import('/assets/result-reader-boundary.js');
    const context={runId:'fixture',byKey:new Map(),byId:new Map()},keys=new Map(),names=new Map();
    let active=0,peak=0,svgBodies=0;const fetched=[];
    const data='var geneclusters = {}; var details_data = {};';
    const boundary=createResultReaderBoundary({state:{activeResultArtifactByKey:context.byKey,activeResultArtifactById:context.byId},
      resolveResultArtifact:async(job,owner,ref)=>({key:keys.get(ref)}),
      resultFetch:async(job,key)=>{
        const name=names.get(key);fetched.push(name);
        if(name==='geneclusters.js')return new Response(data,{headers:{'Content-Length':String(new Blob([data]).size)}});
        peak=Math.max(peak,++active);await new Promise(r=>setTimeout(r,3));active--;
        const body=scenario==='invalid'?'<svg>':'<svg xmlns="http://www.w3.org/2000/svg"><rect width="3" height="4"/></svg>';
        const response=new Response(body,{headers:{'Content-Length':String(scenario==='oversized'?33*1024*1024:new Blob([body]).size)}});
        const read=response.text.bind(response);response.text=()=>{svgBodies++;return read()};return response;
      }});
    const paths=['index.html','geneclusters.js','plotly-latest.min.js',...Array.from({length:12},(_,i)=>`svg/comparison${i}.svg`)];
    for(const [i,name] of paths.entries()) {
      const key=boundary.installResultArtifactDescriptor({id:String(i).padStart(22,'A'),filename:name.split('/').pop(),category:'plantismash',kind:name.endsWith('.html')?'html':'asset',bundle_id:scenario==='foreign'&&name.endsWith('.svg')?'other':'native'},context);
      keys.set(name,key);names.set(key,name);
    }
    const options=scenario==='preload'?'':paths.filter(p=>p.endsWith('.svg')).map(p=>`<option value="${p}">match</option>`).join('');
    const doc=new DOMParser().parseFromString(`<html><body><div id="overview"></div><select class="clusterblast-selector">${options}</select><script src="geneclusters.js"></script><script src="plotly-latest.min.js"></script></body></html>`,'text/html');
    let error='';const budget={declaredBytes:0,actualBytes:0};
    try {await boundary.inlineToolResultScripts(doc,'fixture',keys.get('index.html'),{resultContext:context,toolBundleAssetBudget:budget})}catch(e){error=e.message}
    return {fetched,peak,svgBodies,error,budget,externalScripts:doc.querySelectorAll('script[src]').length};
  },scenario);
}

test('plant data preflight reuses the fetched body once',async({page})=>{
 const r=await exercise(page,'preload');expect(r.error).toBe('');expect(r.fetched).toEqual(['geneclusters.js']);expect(r.externalScripts).toBe(0);
});
test('comparison loading is concurrent, bounded and fully budgeted',async({page})=>{
 const r=await exercise(page,'valid');expect(r.error).toBe('');expect(r.peak).toBe(4);expect(r.svgBodies).toBe(12);expect(r.fetched.filter(x=>x==='geneclusters.js')).toHaveLength(1);expect(r.budget.actualBytes).toBe(r.budget.declaredBytes);
});
for(const scenario of ['foreign','invalid','oversized'])test(`comparison loading rejects ${scenario} assets`,async({page})=>{
 const r=await exercise(page,scenario);expect(r.error).not.toBe('');
 if(scenario==='foreign'){expect(r.error).toContain('outside its report bundle');expect(r.svgBodies).toBe(0)}
 if(scenario==='invalid')expect(r.error).toContain('Invalid plantiSMASH comparison SVG');
 if(scenario==='oversized'){expect(r.error).toContain('exceeds 32 MiB');expect(r.svgBodies).toBe(0)}
});
