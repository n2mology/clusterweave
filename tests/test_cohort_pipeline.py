"""Canonical waiting/resume tests with real validated fixture outputs."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import cohort_gate as gate
import canonical_pipeline as pipeline
from test_cohort_continuation import fixture


class CohortPipelineTests(unittest.TestCase):
    def test_wait_resume_and_restart_do_not_run_annotation_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); results, values=fixture(root)
            inputs=root/'data/genomes/bacteria/cohort';inputs.mkdir(parents=True)
            (inputs/'bacterium.fna').write_text('>chr\n'+'ATG'*100+'\n')
            job=pipeline.Job(id='local-fixture',name='cohort')
            settings={'project_name':'cohort','clusterweave_root':str(Path(__file__).resolve().parents[1]),
                      'run_genome_prep':False,'run_figures':False,'run_phylogeny':False,'run_nplinker':False,
                      'run_cross_kingdom_evidence':False,'run_annotation':True,'analysis_scope':'mixed'}
            commands=[]
            async def stream(cmd,cwd,job,env):
                commands.append((cmd,dict(env)))
                self.assertEqual(Path(cmd[-1]).name,'run_clusterweave.sh')
                if env.get('RUN_STAGE_ANNOTATION')=='0':
                    cohort=Path(env['RESULTS_ROOT'])
                    self.assertNotEqual(cohort,results)
                    self.assertEqual([r['genome_id'] for r in gate.rows(cohort/'summary_tables/run_manifest.tsv')[1]],['bacterium'])
                    self.assertEqual([p.name for p in Path(env['BACTERIA_GENOME_ROOT']).glob('*.fna')],['bacterium.fna'])
                    self.assertFalse(list(Path(env['PLANTS_GENOME_ROOT']).glob('*')))
                    return 0
                context=json.loads(Path(env['CLUSTERWEAVE_COHORT_CONTEXT']).read_text())
                gate.build_gate(results,env['CLUSTERWEAVE_COHORT_CONTROL'],context['identity'],settings,1)
                return 75
            with mock.patch.object(pipeline,'GLOBAL_SOFTWARE_ROOT',root/'software'), \
                 mock.patch.object(pipeline,'_stage_uploaded_inputs'), \
                 mock.patch.object(pipeline,'_stream_cmd',side_effect=stream), \
                 mock.patch.object(pipeline,'_collect_result_files'), \
                 mock.patch.object(pipeline,'collect_run_versions'), \
                 mock.patch.object(pipeline,'probe_annotation_runtimes',return_value=[{'tool':'antiSMASH','runtime_sha256':'a'*64}]), \
                 mock.patch.object(pipeline,'controller_image',return_value='b'*64):
                asyncio.run(pipeline.run_pipeline(job,[],root,cpus=1,settings=settings))
                self.assertEqual(job.status,pipeline.JobStatus.AWAITING_DECISION)
                self.assertEqual(len(commands),1)
                # A worker restart after the closed attempt cannot rerun native work.
                asyncio.run(pipeline.run_pipeline(job,[],root,cpus=1,settings=settings))
                self.assertEqual(job.status,pipeline.JobStatus.AWAITING_DECISION)
                self.assertEqual(len(commands),1)
                control=root/'cohort/current.json';value=gate.load_gate(control)
                gate.accept(control,value['decision_id'],value['included'],value['excluded'],attempt_identity=value['identity'])
                job.continuation_id=value['decision_id']
                asyncio.run(pipeline.run_pipeline(job,[],root,cpus=1,settings=settings))
                self.assertEqual(job.status,pipeline.JobStatus.COMPLETED_WITH_EXCLUSIONS,job.error)
                self.assertEqual(len(commands),2)
                self.assertEqual(commands[-1][1]['RUN_STAGE_ANNOTATION'],'0')
                self.assertEqual([r['state'] for r in job.cohort_decision['outcomes']],['success','failed','failed'])

    def test_stale_runtime_refuses_resume_before_downstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);results,values=fixture(root)
            inputs=root/'data/genomes/bacteria/cohort';inputs.mkdir(parents=True)
            (inputs/'bacterium.fna').write_text('>chr\nATG\n')
            value=gate.build_gate(results,root/'cohort/current.json',{'job_id':'local-fixture','rerun_count':0,'source_sha256':'obsolete'}, {},1)
            gate.accept(root/'cohort/current.json',value['decision_id'],value['included'],value['excluded'],attempt_identity=value['identity'])
            job=pipeline.Job(id='local-fixture',name='cohort',continuation_id=value['decision_id'])
            with mock.patch.object(pipeline,'GLOBAL_SOFTWARE_ROOT',root/'software'),mock.patch.object(pipeline,'_stream_cmd') as stream,mock.patch.object(pipeline,'_collect_result_files'),mock.patch.object(pipeline,'collect_run_versions'),mock.patch.object(pipeline,'probe_annotation_runtimes',return_value=[]),mock.patch.object(pipeline,'controller_image',return_value='a'*64):
                asyncio.run(pipeline.run_pipeline(job,[],root,settings={'project_name':'cohort','run_genome_prep':False}))
                self.assertEqual(job.status,pipeline.JobStatus.FAILED)
                stream.assert_not_called()
