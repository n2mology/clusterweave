"""Mixed-network defaults and bounded native comparison loading."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'web/static/assets/result-reader-boundary.js'


@unittest.skipUnless(shutil.which('node'), 'Node required for viewer contracts')
class ViewerScopeLoadingTests(unittest.TestCase):
    def node(self, helper, program):
        result = subprocess.run(['node', '-e', helper + program], check=True, text=True, capture_output=True)
        return json.loads(result.stdout)

    def test_combined_default_explicit_scope_and_single_bin_compatibility(self):
        source = SOURCE.read_text()
        helper = 'function rewriteBigscapeNetworkScope' + source.split('function rewriteBigscapeNetworkScope', 1)[1].split('async function inlineBigscapeResultScripts', 1)[0]
        result = self.node(helper, r'''
const original = `function loadOverview() { $("#network-selection").append(network_opts); }
function populateCcTable() { var sorted_bs_ccs = bs_ccs.toSorted((a, b) => b.size - a.size); }`;
const script = {textContent:original};
rewriteBigscapeNetworkScope({querySelectorAll:()=>[script],getElementById:()=>null});
const cases=[];
for(const labels of [['Categoryless','mix','NRPS'],['NRPS'],['mix']]) {
 const options=labels.map((text,i)=>({text,value:String(i)}));let selected='0';const texts={};
 const document={getElementById:()=>({options})};
 const $=selector=>({append:()=>{},val:v=>{selected=v},text:v=>{texts[selector]=v;return {attr:()=>{}}}});
 const network_opts=[];let bin_label='mix';
 let bs_ccs=[{size:2,families:[{members:[1,2]}]},{size:2,families:[{members:[2,3]}]}];
 if(!Array.prototype.toSorted)Array.prototype.toSorted=function(compare){return this.slice().sort(compare)};
 eval(script.textContent+';loadOverview();populateCcTable();');
 const count=texts['#load-all']; const initialSelection=labels[Number(selected)];
 // Selecting a category / applying search must keep its actual distinct count.
 selected=String(options.length-1);bin_label=labels.at(-1);bs_ccs=[{size:1,families:[{members:[8]}]}];
 eval(script.textContent+';populateCcTable();');
 cases.push({default:initialSelection,initialCount:count,selectedAfterFilter:selected,filteredCount:texts['#load-all'],scope:texts['#clusterweave-network-scope']});
}
let drift=false;try{rewriteBigscapeNetworkScope({querySelectorAll:()=>[{textContent:'function populateCcTable() {}'}]})}catch(e){drift=/compatibility profile/.test(e.message)}
console.log(JSON.stringify({cases,drift}));
''')
        self.assertTrue(result['drift'])
        self.assertEqual([r['default'] for r in result['cases']], ['mix', 'NRPS', 'mix'])
        for case in result['cases']:
            self.assertEqual(case['initialCount'], 'Visualize shown BGCs (3)')
            self.assertEqual(case['filteredCount'], 'Visualize shown BGCs (1)')
            self.assertIn('1 BGCs shown', case['scope'])
        self.assertEqual(result['cases'][0]['selectedAfterFilter'], '2')

    def test_bounded_concurrency_complete_coverage_and_failure_stops_new_work(self):
        source = SOURCE.read_text()
        helper = 'async function loadPlantComparisonAssets' + source.split('async function loadPlantComparisonAssets', 1)[1].split('async function preparePlantExtraViews', 1)[0]
        result = self.node(helper, r'''
(async()=>{
 let active=0,peak=0;const completed=[];
 await loadPlantComparisonAssets(Array.from({length:19},(_,i)=>i),async i=>{
  peak=Math.max(peak,++active);await new Promise(r=>setTimeout(r,2));completed.push(i);active--;
 });
 let failed=false;const started=[];
 try{await loadPlantComparisonAssets(Array.from({length:19},(_,i)=>i),async i=>{
  started.push(i);if(i===0)throw Error('invalid SVG');await new Promise(r=>setTimeout(r,5));
 })}catch(e){failed=e.message==='invalid SVG'}
 let emptyCalls=0;await loadPlantComparisonAssets([],async()=>emptyCalls++);
 console.log(JSON.stringify({peak,active,completed:completed.sort((a,b)=>a-b),failed,started,emptyCalls}));
})().catch(e=>{console.error(e);process.exit(1)});
''')
        self.assertEqual(result['peak'], 4)
        self.assertEqual(result['active'], 0)
        self.assertEqual(result['completed'], list(range(19)))
        self.assertTrue(result['failed'])
        self.assertLessEqual(len(result['started']), 4)
        self.assertEqual(result['emptyCalls'], 0)

    def test_parallel_asset_budget_still_rejects_total_and_unsafe_headers(self):
        source = SOURCE.read_text()
        helper = 'function assertToolResultAssetSize' + source.split('function assertToolResultAssetSize', 1)[1].split('function isExactPublicClinkerPanelHtml', 1)[0]
        program = r'''
const TOOL_RESULT_PREVIEW_ASSET_MAX_BYTES=32*1024*1024,TOOL_RESULT_PREVIEW_TOTAL_ASSET_MAX_BYTES=64*1024*1024;
const response=n=>({headers:{get:()=>n}});const budget={declaredBytes:0,actualBytes:0};let rejected=false;
for(let i=0;i<4;i++){try{assertToolResultAssetSize(response(String(20*1024*1024)),20*1024*1024,budget)}catch(e){rejected=true;}}
const unsafe=[null,'','-1',String(33*1024*1024),'no-size'].map(n=>{try{assertToolResultAssetSize(response(n),0,{declaredBytes:0,actualBytes:0});return false}catch{return true}});
console.log(JSON.stringify({rejected,unsafe}));
'''
        result = self.node(helper, program)
        self.assertTrue(result['rejected'])
        self.assertTrue(all(result['unsafe']))
