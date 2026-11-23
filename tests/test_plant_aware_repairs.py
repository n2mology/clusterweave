"""Regression controls for capacity bounds and recovered native warnings."""
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web'))
from resource_policy import MemoryFormula, build_hosted_resource_plan, estimate_job_resources


class PlantAwareRepairsTests(unittest.TestCase):
    def test_hosted_plan_matches_admission_and_bounds_cpu_and_memory(self):
        formula = MemoryFormula(base_memory_mb=1024, per_genome_memory_mb=1024,
            per_antismash_shard_memory_mb=1792, per_annotation_cpu_memory_mb=128,
            per_funbgcex_worker_memory_mb=64, safety_factor=1.2, minimum_memory_mb=8192)
        for cpus, memory, expected in [(4,13107,(1,2,2)), (8,26000,(2,2,2)), (1,8192,(1,1,1))]:
            with self.subTest(cpus=cpus, memory=memory):
                plan = build_hosted_resource_plan(cpus,3,{},genome_parallelism=2,
                    antismash_record_parallelism=2,funannotate_cpus_per_genome=8,
                    funbgcex_workers_per_genome=2,memory_budget_mb=memory,memory_formula=formula)
                self.assertEqual((plan.genome_parallelism, plan.antismash_record_parallelism,
                                  plan.antismash_shard_cpus),expected)
                estimate=estimate_job_resources(cpus,plan.as_settings(),3,memory_formula=formula)
                self.assertEqual(estimate.plan,plan)
                self.assertLessEqual(estimate.memory_mb,memory)
                self.assertLessEqual(plan.antismash_sharded_cpu_slots,cpus)
                self.assertLessEqual(plan.annotation_cpu_slots,cpus)
                self.assertLessEqual(plan.funbgcex_cpu_slots,cpus)

    def test_recoverable_warning_and_genuine_failure_classification(self):
        source=(ROOT/'run_annotation_and_detection.sh').read_text()
        function=re.search(r'^tool_activity_public_message\(\) \{\n.*?^\}',source,re.M|re.S).group()
        lines=[
            "mkdir -p failed for path /nonexistent/.config/matplotlib: [Errno 13] Permission denied: '/nonexistent'",
            'Matplotlib created a temporary cache directory at /tmp/matplotlib-abcdef',
            'Traceback (most recent call last):',
            'ERROR: invalid output JSON',
            'ERROR: database unavailable',
            '0 failed; Running whole-genome PFAM search',
        ]
        script=function+'\nwhile IFS= read -r line; do tool_activity_public_message antismash "$line" || true; done\n'
        result=subprocess.run(['bash','-c',script],input='\n'.join(lines)+'\n',capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.splitlines(),[
            'antiSMASH reported a recoverable Matplotlib cache warning',
            'antiSMASH reported a recoverable Matplotlib cache warning',
            'antiSMASH reported an error','antiSMASH reported an error','antiSMASH reported an error',
            'Running whole-genome PFAM search'])

if __name__=='__main__': unittest.main()
