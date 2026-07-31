from __future__ import annotations

import sys
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
BIN_DIR = REPO_ROOT / "bin"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from resource_policy import (  # noqa: E402
    MemoryFormula,
    ResourceRequest,
    bounded_cpu_limit,
    bounded_resource_plan,
    build_hosted_resource_plan,
    estimate_job_resources,
    genome_count_from_input_summary,
)
from annotation_runtime import (  # noqa: E402
    build_annotation_resource_plan,
    effective_cpu_count,
    effective_memory_mb,
    nonnegative_int,
    positive_int,
)


def request(
    cpus: int,
    genomes: int,
    genome_fanout: int,
    record_fanout: int,
    shard_cpus: int,
    legacy_cpus: int,
    anno_cpus: int,
    workers: int,
) -> ResourceRequest:
    return ResourceRequest(
        job_cpus=cpus,
        genome_count=genomes,
        target_genome_parallelism=genome_fanout,
        target_antismash_record_parallelism=record_fanout,
        target_antismash_shard_cpus=shard_cpus,
        target_antismash_legacy_cpus=legacy_cpus,
        target_anno_cpus=anno_cpus,
        target_funbgcex_workers=workers,
    )


class ResourcePolicyTests(unittest.TestCase):
    def test_annotation_runtime_preserves_shell_numeric_input_rules(self) -> None:
        self.assertEqual(positive_int("5", 32), 5)
        self.assertEqual(positive_int("+5", 32), 32)
        self.assertEqual(positive_int(" 5", 32), 32)
        self.assertEqual(positive_int("0", 32), 32)
        self.assertEqual(nonnegative_int("4096"), 4096)
        self.assertEqual(nonnegative_int("+4096"), 0)

    def test_annotation_runtime_detects_cgroup_cpu_and_memory_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cpuset.cpus.effective").write_text("0-7\n", encoding="utf-8")
            (root / "cpu.max").write_text("400000 100000\n", encoding="utf-8")
            (root / "memory.max").write_text(
                str(8 * 1024 * 1024 * 1024), encoding="utf-8"
            )
            (root / "memory.current").write_text(
                str(2 * 1024 * 1024 * 1024), encoding="utf-8"
            )
            meminfo = root / "meminfo"
            meminfo.write_text("MemAvailable: 16777216 kB\n", encoding="utf-8")

            self.assertEqual(effective_cpu_count(root, online_cpus=12), 4)
            self.assertEqual(
                effective_memory_mb(root, meminfo_path=meminfo),
                6144,
            )
            empty_cgroup = root / "empty"
            empty_cgroup.mkdir()
            low_meminfo = root / "low_meminfo"
            low_meminfo.write_text("MemAvailable: 512 kB\n", encoding="utf-8")
            self.assertEqual(
                effective_memory_mb(empty_cgroup, meminfo_path=low_meminfo),
                0,
            )

    def test_annotation_runtime_prefers_present_v2_cgroup_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cpu").mkdir()
            (root / "memory").mkdir()
            (root / "cpuset.cpus.effective").write_text("0-7\n", encoding="utf-8")
            (root / "cpu.max").write_text("max 100000\n", encoding="utf-8")
            (root / "cpu" / "cpu.cfs_quota_us").write_text("100000\n", encoding="utf-8")
            (root / "cpu" / "cpu.cfs_period_us").write_text("100000\n", encoding="utf-8")
            (root / "memory.max").write_text("max\n", encoding="utf-8")
            (root / "memory.current").write_text("0\n", encoding="utf-8")
            (root / "memory" / "memory.limit_in_bytes").write_text(
                str(2 * 1024 * 1024 * 1024), encoding="utf-8"
            )
            (root / "memory" / "memory.usage_in_bytes").write_text(
                str(1024 * 1024 * 1024), encoding="utf-8"
            )
            meminfo = root / "meminfo"
            meminfo.write_text("MemAvailable: 16777216 kB\n", encoding="utf-8")

            self.assertEqual(effective_cpu_count(root, online_cpus=12), 8)
            self.assertEqual(effective_memory_mb(root, meminfo_path=meminfo), 16384)

    def test_annotation_runtime_plan_uses_shared_r02_policy(self) -> None:
        result = build_annotation_resource_plan(
            mode="conservative",
            requested_cpus=12,
            cpus_explicit=True,
            effective_cpus=12,
            effective_memory_mb=24576,
            total_genomes=25,
            genome_parallelism=5,
            anno_cpus=8,
            funbgcex_workers=10,
            antismash_record_parallelism=4,
            antismash_shard_cpus=9,
            antismash_legacy_cpus=9,
            memory_budget_mb=None,
            auto_max_cpus=32,
            auto_max_genome_parallelism=4,
            auto_min_cpus_per_genome=2,
            auto_memory_percent=70,
            auto_memory_per_genome_mb=8192,
            auto_max_anno_cpus=8,
            auto_max_funbgcex_workers=2,
            auto_max_antismash_record_parallelism=3,
        )
        expected = request(12, 25, 5, 4, 9, 9, 8, 10).bounded_plan()

        self.assertEqual(result.plan, expected)
        self.assertEqual(
            result.shell_fields(),
            (12, 5, 2, 2, 2, 2, 1, 2, 12, 24576, 0, 10, 10, 10, 10),
        )

    def test_annotation_runtime_auto_plan_preserves_cgroup_memory_shape(self) -> None:
        result = build_annotation_resource_plan(
            mode="auto",
            requested_cpus=6,
            cpus_explicit=False,
            effective_cpus=12,
            effective_memory_mb=24576,
            total_genomes=25,
            genome_parallelism=1,
            anno_cpus=6,
            funbgcex_workers=2,
            antismash_record_parallelism=1,
            antismash_shard_cpus=None,
            antismash_legacy_cpus=None,
            memory_budget_mb=None,
            auto_max_cpus=32,
            auto_max_genome_parallelism=4,
            auto_min_cpus_per_genome=2,
            auto_memory_percent=70,
            auto_memory_per_genome_mb=8192,
            auto_max_anno_cpus=8,
            auto_max_funbgcex_workers=2,
            auto_max_antismash_record_parallelism=3,
        )

        self.assertEqual(
            result.shell_fields(),
            (12, 2, 6, 6, 2, 3, 2, 6, 12, 24576, 24576, 12, 4, 12, 12),
        )

    def test_cpu_limit_uses_narrowest_configured_effective_and_worker_budget(self) -> None:
        cases = [
            (8, 16, None, 8),
            (8, 4, None, 4),
            (8, 16, 3, 3),
            (1, 8, 4, 1),
            (0, 0, 0, 1),
        ]
        for configured, effective, worker, expected in cases:
            with self.subTest(
                configured=configured,
                effective=effective,
                worker=worker,
            ):
                self.assertEqual(
                    bounded_cpu_limit(
                        configured,
                        effective,
                        worker_cpu_budget=worker,
                    ),
                    expected,
                )

    def test_resource_truth_table_covers_modes_cpu_limits_and_input_sizes(self) -> None:
        settings = {
            "genome_parallelism": 50,
            "antismash_record_parallelism": 50,
            "antismash_shard_cpus": 50,
            "antismash_legacy_cpus": 50,
            "anno_cpus": 50,
            "workers": 50,
        }
        for mode in ("public", "admin", "local"):
            for cpus in (1, 4, 8):
                for genome_count in (1, 40, 50):
                    with self.subTest(
                        mode=mode,
                        cpus=cpus,
                        genome_count=genome_count,
                    ):
                        if mode in {"public", "admin"}:
                            plan = build_hosted_resource_plan(
                                cpus,
                                genome_count,
                                settings,
                                genome_parallelism=4,
                                antismash_record_parallelism=3,
                                funannotate_cpus_per_genome=4,
                                funbgcex_workers_per_genome=2,
                            )
                        else:
                            plan = ResourceRequest.from_settings(
                                cpus,
                                settings,
                                genome_count,
                            ).bounded_plan()

                        self.assertEqual(plan.job_cpus, cpus)
                        self.assertEqual(plan.genome_count, genome_count)
                        self.assertLessEqual(plan.genome_parallelism, genome_count)
                        self.assertLessEqual(plan.annotation_cpu_slots, cpus)
                        self.assertLessEqual(plan.funbgcex_cpu_slots, cpus)
                        self.assertLessEqual(plan.antismash_sharded_cpu_slots, cpus)
                        self.assertLessEqual(plan.antismash_legacy_cpu_slots, cpus)
                        self.assertEqual(plan.cpu_slots, cpus)

    def test_bounded_plan_table(self) -> None:
        cases = [
            (
                "single CPU",
                request(1, 10, 10, 10, 10, 10, 10, 10),
                (1, 1, 1, 1, 1, 1),
            ),
            (
                "one genome uses per-process CPU",
                request(8, 1, 4, 4, 8, 8, 4, 2),
                (1, 4, 2, 8, 4, 2),
            ),
            (
                "three genomes divide an eight CPU job",
                request(8, 5, 3, 4, 2, 8, 8, 8),
                (3, 2, 1, 2, 2, 2),
            ),
            (
                "balanced sixteen CPU job",
                request(16, 4, 4, 4, 4, 16, 8, 3),
                (4, 4, 1, 4, 4, 3),
            ),
            (
                "genome fanout cannot exceed inputs",
                request(64, 2, 50, 8, 8, 64, 32, 32),
                (2, 8, 4, 32, 32, 32),
            ),
        ]

        for label, resource_request, expected in cases:
            with self.subTest(label=label):
                plan = bounded_resource_plan(resource_request)
                self.assertEqual(
                    (
                        plan.genome_parallelism,
                        plan.antismash_record_parallelism,
                        plan.antismash_shard_cpus,
                        plan.antismash_legacy_cpus,
                        plan.anno_cpus,
                        plan.funbgcex_workers,
                    ),
                    expected,
                )
                self.assertLessEqual(plan.genome_parallelism, plan.genome_count)
                self.assertLessEqual(plan.annotation_cpu_slots, plan.job_cpus)
                self.assertLessEqual(plan.funbgcex_cpu_slots, plan.job_cpus)
                self.assertLessEqual(plan.antismash_sharded_cpu_slots, plan.job_cpus)
                self.assertLessEqual(plan.antismash_legacy_cpu_slots, plan.job_cpus)
                self.assertLessEqual(plan.phylogeny_cpu_slots, plan.job_cpus)
                self.assertEqual(plan.cpu_slots, plan.job_cpus)
                for key, value in plan.as_settings().items():
                    if key == "run_phylogeny":
                        continue
                    self.assertGreaterEqual(value, 1)

    def test_nonpositive_and_invalid_values_still_make_positive_plan(self) -> None:
        resource_request = request(0, -2, 0, -1, 0, -8, 0, -3)
        plan = resource_request.bounded_plan()
        self.assertEqual(plan.job_cpus, 1)
        self.assertEqual(plan.genome_count, 1)
        self.assertTrue(
            all(
                value == 1
                for key, value in plan.as_settings().items()
                if key != "run_phylogeny"
            )
        )
        self.assertFalse(plan.run_phylogeny)

    def test_estimate_cpu_is_peak_stage_demand(self) -> None:
        plan = request(12, 3, 2, 3, 2, 4, 5, 2).bounded_plan()
        estimate = request(12, 3, 2, 3, 2, 4, 5, 2).estimate()
        self.assertEqual(plan.annotation_cpu_slots, 10)
        self.assertEqual(plan.funbgcex_cpu_slots, 4)
        self.assertEqual(plan.antismash_sharded_cpu_slots, 12)
        self.assertEqual(plan.antismash_legacy_cpu_slots, 8)
        self.assertEqual(estimate.cpu_slots, 12)
        self.assertEqual(estimate.plan, plan)

    def test_memory_formula_is_configurable_and_safety_adjusted(self) -> None:
        formula = MemoryFormula(
            base_memory_mb=100,
            per_genome_memory_mb=10,
            per_antismash_shard_memory_mb=20,
            per_annotation_cpu_memory_mb=3,
            per_funbgcex_worker_memory_mb=5,
            safety_factor=1.5,
            minimum_memory_mb=1,
        )
        estimate = request(8, 2, 2, 2, 2, 4, 4, 2).estimate(formula)
        self.assertEqual(estimate.cpu_slots, 8)
        self.assertEqual(estimate.memory_mb, 366)

    def test_default_memory_estimate_scales_with_concurrency(self) -> None:
        shapes = [
            request(4, 1, 1, 1, 4, 4, 4, 2),
            request(8, 4, 2, 2, 2, 4, 4, 2),
            request(16, 8, 4, 4, 1, 4, 4, 2),
        ]
        estimates = [shape.estimate() for shape in shapes]
        self.assertLess(estimates[0].memory_mb, estimates[1].memory_mb)
        self.assertLess(estimates[1].memory_mb, estimates[2].memory_mb)
        self.assertEqual([item.cpu_slots for item in estimates], [4, 8, 16])

    def test_invalid_memory_safety_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MemoryFormula(per_genome_memory_mb=-1)
        with self.assertRaises(ValueError):
            MemoryFormula(safety_factor=0.99)
        with self.assertRaises(ValueError):
            MemoryFormula(minimum_memory_mb=0)

    def test_worker_adapter_matches_shell_default_for_zero_shard_cpus(self) -> None:
        estimate = estimate_job_resources(
            12,
            {
                "genome_parallelism": "2",
                "antismash_record_parallelism": "3",
                "antismash_shard_cpus": "0",
                "antismash_legacy_cpus": "6",
                "anno_cpus": "6",
                "workers": "3",
            },
            genome_count=5,
        )
        plan = estimate.plan
        self.assertEqual(plan.genome_parallelism, 2)
        self.assertEqual(plan.antismash_record_parallelism, 3)
        self.assertEqual(plan.antismash_shard_cpus, 2)
        self.assertEqual(plan.antismash_legacy_cpus, 6)
        self.assertEqual(estimate.cpu_slots, 12)
        self.assertGreater(estimate.memory_mb, 0)

    def test_worker_adapter_unknown_genome_count_preserves_requested_fanout(self) -> None:
        estimate = estimate_job_resources(
            8,
            {"genome_parallelism": 3, "anno_cpus": 2},
        )
        self.assertEqual(estimate.plan.genome_count, 3)
        self.assertEqual(estimate.plan.genome_parallelism, 3)

    def test_optional_phylogeny_is_clamped_inside_job_cpu_budget(self) -> None:
        estimate = estimate_job_resources(
            8,
            {
                "genome_parallelism": 2,
                "run_phylogeny": "true",
                "phylogeny_cpus": 6,
                "phylogeny_parallelism": 3,
            },
            genome_count=2,
        )
        plan = estimate.plan
        self.assertTrue(plan.run_phylogeny)
        self.assertEqual(plan.phylogeny_parallelism, 1)
        self.assertEqual(plan.phylogeny_cpus, 6)
        self.assertEqual(plan.phylogeny_cpu_slots, 6)
        self.assertLessEqual(plan.phylogeny_cpu_slots, plan.job_cpus)
        self.assertEqual(plan.cpu_slots, 8)

    def test_sequential_phylogeny_memory_uses_peak_not_sum(self) -> None:
        formula = MemoryFormula(
            base_memory_mb=100,
            per_genome_memory_mb=0,
            per_antismash_shard_memory_mb=0,
            per_annotation_cpu_memory_mb=0,
            per_funbgcex_worker_memory_mb=0,
            phylogeny_base_memory_mb=200,
            per_phylogeny_cpu_memory_mb=100,
            safety_factor=1.5,
            minimum_memory_mb=1,
        )
        estimate = estimate_job_resources(
            8,
            {
                "run_phylogeny": True,
                "phylogeny_cpus": 2,
                "phylogeny_parallelism": 2,
            },
            genome_count=1,
            memory_formula=formula,
        )
        # Serial execution uses max(core=100, phylogeny=400) * 1.5,
        # not (100 + 400) * 1.5.
        self.assertEqual(estimate.memory_mb, 600)

    def test_disabled_phylogeny_does_not_change_legacy_estimate(self) -> None:
        base = estimate_job_resources(8, {}, genome_count=1)
        disabled = estimate_job_resources(
            8,
            {
                "run_phylogeny": "0",
                "phylogeny_cpus": 8,
                "phylogeny_parallelism": 8,
            },
            genome_count=1,
        )
        self.assertEqual(disabled.cpu_slots, base.cpu_slots)
        self.assertEqual(disabled.memory_mb, base.memory_mb)

    def test_genome_count_collapses_paired_genome_files(self) -> None:
        summary = {
            "accession_count": 2,
            "genome_file_count": 3,
            "genome_readiness": [
                {"stem": "sample-a"},
                {"stem": "sample-b"},
                {"stem": "SAMPLE-B"},
            ],
        }
        self.assertEqual(genome_count_from_input_summary(summary), 4)
        self.assertEqual(genome_count_from_input_summary({"genome_count": 7}), 7)
        self.assertEqual(genome_count_from_input_summary({}), 1)


if __name__ == "__main__":
    unittest.main()
