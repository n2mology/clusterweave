"""Selected-bin cardinality regression for the pinned BiG-SCAPE browser reader."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js required for browser compatibility contract")
class HeatmapCompatibilityTests(unittest.TestCase):
    def test_selected_rows_and_columns_guard_without_changing_multi_genome_rendering(self):
        source = (Path(__file__).resolve().parents[1] / "web/static/assets/result-reader-boundary.js").read_text()
        helper = "function rewriteBigscapeHeatmapForSandbox" + source.split("function rewriteBigscapeHeatmapForSandbox", 1)[1].split("async function inlineBigscapeResultScripts", 1)[0]
        program = helper + r"""
const signature = 'var inchlib_data = generateRealHeatmapData(run_data["input"], run_data["networks"][idx]);';
const original = 'function renderHeatmap(idx, run_data) {' + signature + 'drawn++;}';
const script = {textContent: original};
rewriteBigscapeHeatmapForSandbox({querySelectorAll: () => [script]});
const cases = [];
for (const [rows, columns] of [[1,2],[2,1],[2,2],[3,4]]) {
  let drawn = 0; const messages = [];
  const $ = () => ({text: message => messages.push(message), val: message => messages.push(message)});
  const generateRealHeatmapData = () => ({data: {nodes: Object.fromEntries(Array.from({length:rows}, (_,i) => ['leaf_'+i,{objects:['g'+i]}])), feature_names:Array(columns).fill('family')}});
  eval(script.textContent + ';renderHeatmap(0,{input:{},networks:[{}]});');
  cases.push({rows,columns,drawn,messages:messages.length});
}
let driftRejected = false;
try { rewriteBigscapeHeatmapForSandbox({querySelectorAll: () => [{textContent:'function renderHeatmap() {}'}]}); } catch(e) { driftRejected = /compatibility profile/.test(e.message); }
const unrelated = {textContent:'const untouched = true;'};
rewriteBigscapeHeatmapForSandbox({querySelectorAll: () => [unrelated]});
console.log(JSON.stringify({cases,driftRejected,unrelated:unrelated.textContent}));
"""
        result = subprocess.run(["node", "-e", program], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), {
            "cases": [
                {"rows": 1, "columns": 2, "drawn": 0, "messages": 2},
                {"rows": 2, "columns": 1, "drawn": 0, "messages": 2},
                {"rows": 2, "columns": 2, "drawn": 1, "messages": 0},
                {"rows": 3, "columns": 4, "drawn": 1, "messages": 0},
            ], "driftRejected": True, "unrelated": "const untouched = true;",
        })

    def test_zero_edges_render_without_inventing_similarity_or_hiding_sql_errors(self):
        source = (Path(__file__).resolve().parents[1] / "web/static/assets/result-reader-boundary.js").read_text()
        helper = "function rewriteBigscapeEmptyEdgesForSandbox" + source.split("function rewriteBigscapeEmptyEdgesForSandbox", 1)[1].split("async function inlineBigscapeResultScripts", 1)[0]
        program = helper + r"""
const script = {textContent:'function generate_bs_similarity() { var distances = window.db.exec(`SELECT distance.record_a_id, distance.record_b_id, distance.distance FROM distance`)[0].values; return distances; }'};
rewriteBigscapeEmptyEdgesForSandbox({querySelectorAll:()=>[script]});
const results=[];
for(const response of [[],[{values:[[1,2,0.25]]}]]) {
 const window={db:{exec:()=>response}};
 results.push(eval(script.textContent+';generate_bs_similarity();'));
}
let sqlErrorPreserved=false;
try { const window={db:{exec:()=>{throw Error('invalid database')}}};eval(script.textContent+';generate_bs_similarity();'); } catch(e) {sqlErrorPreserved=e.message==='invalid database';}
let driftRejected=false;
try {rewriteBigscapeEmptyEdgesForSandbox({querySelectorAll:()=>[{textContent:'function generate_bs_similarity() {}'}]});} catch(e) {driftRejected=/compatibility profile/.test(e.message);}
console.log(JSON.stringify({results,sqlErrorPreserved,driftRejected}));
"""
        result = subprocess.run(["node", "-e", program], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), {
            "results": [[], [[1, 2, 0.25]]], "sqlErrorPreserved": True, "driftRejected": True,
        })
