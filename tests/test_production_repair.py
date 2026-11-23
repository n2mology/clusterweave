"""Progress, retrieval and public-table regressions from the production repair."""
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'web'),str(ROOT/'bin')]
import cached_accession as cache
import render_progress_tree as tree

class RepairTests(unittest.TestCase):
    def test_private_tool_stream_retains_original_text_while_central_is_bounded(self):
        import subprocess
        import shlex
        from annotation_source import shell_function
        source=(ROOT/'run_annotation_and_detection.sh').read_text()
        script='set -euo pipefail\nlog() { printf "%s\\n" "$*"; }\n'
        for name in ['tool_activity_clean_line','tool_activity_limit_line','tool_activity_public_message','tool_activity_emit_progress','tool_activity_stream']:
            script+=shell_function(source,name)
        raw=('\x1b[31mDomain α\t'+'x'*5000+'\r\nPLANT_PHASE phase=exporting\n').encode()
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)/'private.log'
            command=script+'tool_activity_stream Plant plantismash stdout '+shlex.quote(str(private))+' detect\n'
            result=subprocess.run(['bash','-c',command],input=raw,capture_output=True,check=True)
            self.assertEqual(private.read_bytes(),raw)
            central=result.stdout.decode()
            self.assertNotIn('\x1b',central)
            self.assertNotIn('α',central)
            self.assertNotIn('x'*1201,central)
            self.assertIn('Exporting plantiSMASH native reports',central)

    def test_retrieval_source_ignores_only_detector_receipt_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ['scripts/ncbi/download_ncbi_genomes.sh','bin/accession_cache.py','bin/cached_genbank.py','bin/cached_accession.py','web/plant_annotation.py','web/genbank_readiness.py']:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
            with patch.object(cache,'ROOT',root):
                before=cache.snapshot_source_digest('plants')
                p=root/'bin/cached_accession.py';p.write_text(p.read_text().replace('Optional producer metadata never participates', 'Changed downstream reporting metadata never participates'))
                self.assertEqual(cache.snapshot_source_digest('plants'),before)
                p=root/'web/plant_annotation.py';p.write_text(p.read_text()+'\nANNOTATION_IDENTITY_REVISION = 2\n')
                self.assertNotEqual(cache.snapshot_source_digest('plants'),before)

    def test_parallel_record_counts_full_context_reordering_and_restart(self):
        with tempfile.TemporaryDirectory() as data, patch.dict(os.environ, {"DATA_DIR": data}):
            import job_store
        contract=tree.load_contract()
        lines=['GENOME_PROGRESS genome=Plant stage=annotation percent=0 bar=[] message="Starting genome"']
        lines += ['PLANT_RECORD_PROGRESS genome=Plant record=2 ordinal=2/3 state=complete',
                  'PLANT_RECORD_PROGRESS genome=Plant record=1 ordinal=1/3 state=running',
                  'PLANT_RECORD_PROGRESS genome=Plant record=2 ordinal=2/3 state=running',
                  'PLANT_RECORD_PROGRESS genome=Plant record=1 ordinal=1/3 state=complete',
                  'TOOL_HEARTBEAT genome=Plant tool=plantismash phase=detect elapsed=120s']
        progress={}
        for i,line in enumerate(lines):job_store._remember_progress(progress,line,i)
        full=tree.build_progress_tree(contract,enumerate(lines))
        sparse=tree.build_progress_tree(contract,[(x['index'],x['line']) for x in sorted(progress.values(),key=lambda x:x['index'])])
        key='tool:annotation:Plant:plantiSMASH'
        for model in [full,sparse]:
            self.assertEqual(model.nodes[key].percentage,58)
            self.assertEqual(model.nodes[key].state,'running')
            self.assertIn('2/3 complete',model.nodes[key].message)
            self.assertEqual(model.nodes['genome:annotation:Plant'].percentage,58)
        lines+=['PLANT_RECORD_PROGRESS genome=Plant record=3 ordinal=3/3 state=complete']
        model=tree.build_progress_tree(contract,enumerate(lines))
        self.assertEqual(model.nodes[key].percentage,69)
        self.assertEqual(model.nodes[key].state,'running')
        lines+=['GENOME_PROGRESS genome=Sibling stage=annotation percent=100 bar=[] message="Genome workflow complete"']
        lines+=['GENOME_PROGRESS genome=Plant stage=annotation percent=0 bar=[] message="Restarting genome"',
                'PLANT_RECORD_PROGRESS genome=Plant record=3 ordinal=3/3 state=running']
        model=tree.build_progress_tree(contract,enumerate(lines))
        self.assertEqual(model.nodes[key].percentage,35)
        self.assertEqual(model.nodes['genome:annotation:Sibling'].state,'complete')

    def test_public_tables_preserve_private_exact_bytes_zero_and_missing(self):
        from types import SimpleNamespace
        from canonical_pipeline import _prepare_public_tables
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'summary/bgc_comparison.csv';p.parent.mkdir()
            raw=b'genome,producer,native_profile,score,missing\nP,plantismash-2.0.4-private-repeat2,p,0,\n'
            p.write_bytes(raw)
            with patch('canonical_pipeline._is_public_result_file', side_effect=lambda p,l:p==root/'summary/bgc_comparison.csv'):
                self.assertEqual(_prepare_public_tables(SimpleNamespace(results_root=root)),['summary/bgc_comparison.csv'])
                self.assertEqual(_prepare_public_tables(SimpleNamespace(results_root=root)),[])
            self.assertEqual(p.read_text(),'genome,score,missing\nP,0,\n')
            self.assertEqual(next((root/'reproducibility/private_table_sources').glob('*.csv')).read_bytes(),raw)

    def test_plant_api_has_detector_stage_without_funannotate(self):
        with tempfile.TemporaryDirectory() as data, patch.dict(os.environ, {"DATA_DIR": data}):
            import app
        job={"status":"running","taxon_routes":[{"genome_id":"Plant","taxon_group":"plants","prediction_method":"existing_cds"}]}
        lines=['GENOME_PROGRESS genome=Plant stage=annotation percent=0 bar=[] message="Starting genome"',
               'PLANT_RECORD_PROGRESS genome=Plant record=2 ordinal=2/3 state=complete',
               'PLANT_RECORD_PROGRESS genome=Plant record=1 ordinal=1/3 state=complete',
               'TOOL_PROGRESS genome=Plant tool=plantismash phase=detect message="Merging plantiSMASH record outputs"']
        row=app.public_genome_progress(job,lines)[0]
        self.assertEqual(row['percent'],58)
        self.assertEqual(row['region_progress']['processed'],2)
        self.assertEqual(row['stage_states']['plantismash']['status'],'running')
        self.assertNotIn('funannotate',row['stage_states'])
        self.assertFalse(row['terminal'])

    def test_late_shards_cannot_reopen_genome_but_explicit_restart_can(self):
        with tempfile.TemporaryDirectory() as data, patch.dict(os.environ, {"DATA_DIR": data}):
            import app
        job={"status":"running","taxon_routes":[{"genome_id":"Plant","taxon_group":"plants","prediction_method":"existing_cds"}]}
        lines=['GENOME_PROGRESS genome=Plant stage=plantismash percent=100 bar=[] message="Genome workflow complete"',
               'PLANT_RECORD_PROGRESS genome=Plant record=1 ordinal=1/3 state=running',
               'TOOL_PROGRESS genome=Plant tool=plantismash phase=detect message="Merging plantiSMASH record outputs"']
        row=app.public_genome_progress(job,lines)[0]
        self.assertEqual((row['percent'],row['status'],row['terminal']),(100,'complete',True))
        lines+=['GENOME_PROGRESS genome=Plant stage=annotation percent=0 bar=[] message="Restarting genome"',
                'PLANT_RECORD_PROGRESS genome=Plant record=1 ordinal=1/3 state=running']
        row=app.public_genome_progress(job,lines)[0]
        self.assertEqual((row['percent'],row['status'],row['terminal']),(35,'running',False))
