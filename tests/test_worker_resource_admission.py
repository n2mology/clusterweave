from __future__ import annotations

import asyncio
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"


class WorkerResourceAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env_keys = [
            "DATA_DIR",
            "WORKER_CONCURRENCY",
            "WORKER_CPU_BUDGET",
            "WORKER_MEMORY_BUDGET_MB",
            "WORKER_MEMORY_PHYLOGENY_BASE_MB",
            "WORKER_MEMORY_PER_PHYLOGENY_CPU_MB",
            "WORKER_MIN_FREE_DISK_GB",
            "PIPELINE_RESOURCE_MODE",
            "PIPELINE_AUTO_MAX_GENOME_PARALLELISM",
            "PIPELINE_AUTO_MAX_ANTISMASH_RECORD_PARALLELISM",
            "PIPELINE_AUTO_MAX_ANNO_CPUS",
            "PIPELINE_AUTO_MAX_FUNBGCEX_WORKERS",
            "WORKER_PENDING_RECOVERY_GRACE_SECONDS",
        ]
        self.old_env = {key: os.environ.get(key) for key in self.env_keys}
        os.environ.update(
            {
                "DATA_DIR": self.tmp.name,
                "WORKER_CONCURRENCY": "100",
                "WORKER_CPU_BUDGET": "16",
                "WORKER_MEMORY_BUDGET_MB": "49152",
                "WORKER_MEMORY_PHYLOGENY_BASE_MB": "3072",
                "WORKER_MEMORY_PER_PHYLOGENY_CPU_MB": "1536",
                "WORKER_MIN_FREE_DISK_GB": "0",
            }
        )
        self.inserted_web_path = False
        if str(WEB_DIR) not in sys.path:
            sys.path.insert(0, str(WEB_DIR))
            self.inserted_web_path = True
        for name in ["job_store", "worker"]:
            sys.modules.pop(name, None)
        self.job_store = importlib.import_module("job_store")
        self.worker = importlib.import_module("worker")

    def tearDown(self) -> None:
        for name in ["job_store", "worker"]:
            sys.modules.pop(name, None)
        if self.inserted_web_path:
            try:
                sys.path.remove(str(WEB_DIR))
            except ValueError:
                pass
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def create_job(
        self,
        job_id: str,
        *,
        status: str = "pending",
        stage: str = "queued",
        cpus: int = 8,
        settings: dict[str, object] | None = None,
        created_at: str = "2026-01-01T00:00:00+00:00",
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": job_id,
            "name": job_id,
            "status": status,
            "stage": stage,
            "created_at": created_at,
            "updated_at": created_at,
            "log_count": 0,
            "result_files": [],
            "error": None,
            "cpus": cpus,
            "settings": settings or {},
            "submission_settings": settings or {},
            "input_summary": {"accession_count": 15, "genome_file_count": 0},
        }
        self.job_store.write_job(payload)
        return payload

    def enqueue(
        self,
        job_id: str,
        *,
        cpus: int = 8,
        settings: dict[str, object] | None = None,
        enqueued_at: str | None = None,
        suffix: str = ".json",
    ) -> Path:
        payload: dict[str, object] = {
            "job_id": job_id,
            "cpus": cpus,
            "settings": settings or {},
        }
        if enqueued_at is not None:
            payload["enqueued_at"] = enqueued_at
        path = self.job_store.QUEUE_DIR / f"{job_id}{suffix}"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_sixteen_cpu_forty_eight_gib_starts_two_then_releases(self) -> None:
        admission = self.worker.ResourceAdmission(
            cpu_budget=16,
            memory_budget_mb=48 * 1024,
            max_jobs=3,
        )
        request = self.worker.JobResourceReservation(cpu_slots=8, memory_mb=24 * 1024)

        self.assertTrue(admission.reserve("first", request))
        self.assertTrue(admission.reserve("second", request))
        self.assertFalse(admission.reserve("third", request))
        self.assertEqual(admission.allocated_cpu_slots, 16)
        self.assertEqual(admission.allocated_memory_mb, 48 * 1024)

        self.assertEqual(admission.release("first"), request)
        self.assertTrue(admission.reserve("third", request))
        self.assertLessEqual(admission.allocated_cpu_slots, admission.cpu_budget)
        self.assertLessEqual(admission.allocated_memory_mb, admission.memory_budget_mb)

    def test_calibrated_production_profile_admits_three_large_jobs_not_four(self) -> None:
        settings = {
            "genome_parallelism": 3,
            "antismash_record_parallelism": 3,
            "antismash_shard_cpus": 1,
            "antismash_legacy_cpus": 4,
            "anno_cpus": 4,
            "workers": 2,
        }
        formula = self.worker.MemoryFormula(
            base_memory_mb=1024,
            per_genome_memory_mb=1024,
            per_antismash_shard_memory_mb=1792,
            per_annotation_cpu_memory_mb=128,
            per_funbgcex_worker_memory_mb=64,
            safety_factor=1.2,
            minimum_memory_mb=8192,
        )
        estimate = self.worker.estimate_job_resources(
            12,
            settings,
            25,
            memory_formula=formula,
        )
        reservation = self.worker.JobResourceReservation(estimate.cpu_slots, estimate.memory_mb)
        admission = self.worker.ResourceAdmission(
            cpu_budget=48,
            memory_budget_mb=92160,
            max_jobs=3,
        )

        self.assertEqual(reservation.cpu_slots, 12)
        self.assertEqual(reservation.memory_mb, 26573)
        for job_id in ["large-a", "large-b", "large-c"]:
            self.assertTrue(admission.reserve(job_id, reservation))
        self.assertFalse(admission.reserve("large-d", reservation))
        self.assertEqual(admission.allocated_cpu_slots, 36)
        self.assertEqual(admission.allocated_memory_mb, 79719)

    def test_worker_env_phylogeny_terms_reserve_sequential_peak(self) -> None:
        self.create_job("phylogeny", cpus=8)
        settings = {
            "genome_parallelism": 1,
            "antismash_record_parallelism": 1,
            "antismash_shard_cpus": 1,
            "antismash_legacy_cpus": 1,
            "anno_cpus": 1,
            "workers": 1,
            "run_phylogeny": True,
            "phylogeny_cpus": 2,
            "phylogeny_parallelism": 2,
        }

        self.assertEqual(
            self.worker.WORKER_MEMORY_FORMULA.phylogeny_base_memory_mb,
            3072,
        )
        self.assertEqual(
            self.worker.WORKER_MEMORY_FORMULA.per_phylogeny_cpu_memory_mb,
            1536,
        )
        enabled = self.worker.estimate_claim_reservation("phylogeny", 8, settings)
        disabled = self.worker.estimate_claim_reservation(
            "phylogeny", 8, {**settings, "run_phylogeny": False}
        )

        # max(core peak, 3072 + 2 * 1536) * 1.25; the family runner is
        # serial and sequential stages
        # must not be summed into one impossible concurrent reservation.
        self.assertEqual(enabled.cpu_slots, 8)
        self.assertEqual(enabled.memory_mb, 7680)
        self.assertLess(disabled.memory_mb, enabled.memory_mb)

    def test_auto_mode_reserves_operator_expanded_shell_shape(self) -> None:
        self.create_job("autoexpand", cpus=12)
        os.environ.update(
            {
                "PIPELINE_RESOURCE_MODE": "auto",
                "PIPELINE_AUTO_MAX_GENOME_PARALLELISM": "4",
                "PIPELINE_AUTO_MAX_ANTISMASH_RECORD_PARALLELISM": "3",
                "PIPELINE_AUTO_MAX_ANNO_CPUS": "8",
                "PIPELINE_AUTO_MAX_FUNBGCEX_WORKERS": "2",
            }
        )
        reservation = self.worker.estimate_claim_reservation(
            "autoexpand",
            12,
            {
                "genome_parallelism": 1,
                "antismash_record_parallelism": 1,
                "antismash_shard_cpus": 1,
                "anno_cpus": 1,
                "workers": 1,
            },
        )

        # Four genome lanes x three record shards is the worst-case shell auto
        # shape; admission must not reserve the much smaller submitted shape.
        self.assertEqual(reservation.cpu_slots, 12)
        self.assertEqual(reservation.memory_mb, 47360)

    def test_fifo_claim_uses_payload_time_not_uuid_name(self) -> None:
        self.create_job("zzzz")
        self.create_job("aaaa")
        self.enqueue("aaaa", enqueued_at="2026-01-02T00:00:00+00:00")
        self.enqueue("zzzz", enqueued_at="2026-01-01T00:00:00+00:00")
        admission = self.worker.ResourceAdmission(cpu_budget=16, memory_budget_mb=49152, max_jobs=2)
        request = self.worker.JobResourceReservation(8, 4096)

        with mock.patch.object(self.worker, "estimate_claim_reservation", return_value=request):
            claim, reason = self.worker.claim_next_admissible_job(admission)

        self.assertEqual(reason, "")
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.job_id, "zzzz")
        self.assertTrue(claim.lease_path.exists())
        self.assertTrue((self.job_store.QUEUE_DIR / "aaaa.json").exists())

    def test_fifo_falls_back_to_mtime_for_legacy_payloads(self) -> None:
        self.create_job("zzzz")
        self.create_job("aaaa")
        older = self.enqueue("zzzz")
        newer = self.enqueue("aaaa")
        os.utime(older, (1000, 1000))
        os.utime(newer, (2000, 2000))

        self.assertEqual([path.stem for path in self.worker.ordered_queue_paths()], ["zzzz", "aaaa"])

    def test_invalid_fifo_head_is_quarantined_without_blocking_next_job(self) -> None:
        self.create_job("broken")
        self.create_job("healthy")
        broken = self.enqueue("broken", enqueued_at="2026-01-01T00:00:00+00:00")
        broken.write_text("{", encoding="utf-8")
        os.utime(broken, (1000, 1000))
        self.enqueue("healthy", enqueued_at="2026-01-02T00:00:00+00:00")
        admission = self.worker.ResourceAdmission(cpu_budget=16, memory_budget_mb=49152, max_jobs=2)
        request = self.worker.JobResourceReservation(8, 4096)

        with mock.patch.object(self.worker, "estimate_claim_reservation", return_value=request):
            claim, reason = self.worker.claim_next_admissible_job(admission)

        self.assertEqual(reason, "")
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.job_id, "healthy")
        self.assertEqual(self.job_store.read_job("broken")["status"], "failed")
        self.assertEqual(
            len(list((self.job_store.DATA_DIR / "worker" / "rejected_queue").glob("broken.json.*.invalid"))),
            1,
        )

    def test_impossible_fifo_head_fails_without_blocking_next_job(self) -> None:
        self.create_job("oversized", cpus=32)
        self.create_job("healthy", cpus=8)
        self.enqueue("oversized", cpus=32, enqueued_at="2026-01-01T00:00:00+00:00")
        self.enqueue("healthy", cpus=8, enqueued_at="2026-01-02T00:00:00+00:00")
        admission = self.worker.ResourceAdmission(cpu_budget=16, memory_budget_mb=49152, max_jobs=2)

        def estimate(job_id: str, *_args: object, **_kwargs: object):
            if job_id == "oversized":
                return self.worker.JobResourceReservation(32, 4096)
            return self.worker.JobResourceReservation(8, 4096)

        with mock.patch.object(self.worker, "estimate_claim_reservation", side_effect=estimate):
            claim, reason = self.worker.claim_next_admissible_job(admission)

        self.assertEqual(reason, "")
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.job_id, "healthy")
        rejected = self.job_store.read_job("oversized")
        assert rejected is not None
        self.assertEqual(rejected["status"], "failed")
        self.assertIn("cannot fit this worker", rejected["error"])

    def test_claim_lease_is_removed_only_after_running_metadata_is_written(self) -> None:
        self.create_job("durable")
        self.enqueue("durable", enqueued_at="2026-01-01T00:00:00+00:00")
        admission = self.worker.ResourceAdmission(cpu_budget=16, memory_budget_mb=49152, max_jobs=2)
        request = self.worker.JobResourceReservation(8, 4096)
        with mock.patch.object(self.worker, "estimate_claim_reservation", return_value=request):
            claim, _ = self.worker.claim_next_admissible_job(admission)
        assert claim is not None
        original_mark = self.worker.mark_claim_running

        def checked_mark(*args: object, **kwargs: object) -> None:
            self.assertTrue(claim.lease_path.exists())
            original_mark(*args, **kwargs)
            stored = self.job_store.read_job("durable")
            assert stored is not None
            self.assertEqual(stored["status"], "running")

        async def checked_process(*args: object, **kwargs: object) -> None:
            self.assertFalse(claim.lease_path.exists())

        with (
            mock.patch.object(self.worker, "mark_claim_running", side_effect=checked_mark),
            mock.patch.object(self.worker, "process_one", side_effect=checked_process),
        ):
            asyncio.run(
                self.worker.process_claim(
                    claim.job_id,
                    claim.cpus,
                    claim.settings,
                    lease_path=claim.lease_path,
                    reservation=request,
                    admission=admission,
                )
            )

        self.assertEqual(admission.allocated_cpu_slots, 0)
        self.assertEqual(admission.allocated_memory_mb, 0)

    def test_success_failure_and_cancel_all_release_reservations(self) -> None:
        request = self.worker.JobResourceReservation(4, 2048)

        async def success(*args: object, **kwargs: object) -> None:
            return None

        async def failure(*args: object, **kwargs: object) -> None:
            raise RuntimeError("boom")

        async def cancelled(*args: object, **kwargs: object) -> None:
            raise asyncio.CancelledError()

        cases = [("success", success, None), ("failure", failure, RuntimeError), ("cancel", cancelled, None)]
        for name, behavior, expected_error in cases:
            with self.subTest(name=name):
                admission = self.worker.ResourceAdmission(cpu_budget=8, memory_budget_mb=8192, max_jobs=2)
                self.assertTrue(admission.reserve(name, request))
                patches = [
                    mock.patch.object(self.worker, "process_one", side_effect=behavior),
                    mock.patch.object(self.worker, "stop_job_containers"),
                    mock.patch.object(self.worker, "finalize_cancelled_job"),
                ]
                for patcher in patches:
                    patcher.start()
                    self.addCleanup(patcher.stop)
                if name == "failure":
                    read_patcher = mock.patch.object(self.worker, "read_job", return_value=None)
                    read_patcher.start()
                    self.addCleanup(read_patcher.stop)

                if expected_error is None:
                    asyncio.run(
                        self.worker.process_claim(
                            name,
                            4,
                            {},
                            reservation=request,
                            admission=admission,
                        )
                    )
                else:
                    with self.assertRaises(expected_error):
                        asyncio.run(
                            self.worker.process_claim(
                                name,
                                4,
                                {},
                                reservation=request,
                                admission=admission,
                            )
                        )
                self.assertEqual(admission.allocated_cpu_slots, 0)
                self.assertEqual(admission.allocated_memory_mb, 0)
                for patcher in reversed(patches):
                    patcher.stop()

    def _simulate_queue(self, job_count: int, genome_count: int, max_active: int) -> None:
        settings = {
            "genome_count": genome_count,
            "genome_parallelism": 3,
            "antismash_record_parallelism": 3,
            "antismash_shard_cpus": 1,
            "anno_cpus": 2,
            "workers": 2,
        }
        estimate = self.worker.estimate_job_resources(8, settings, genome_count)
        request = self.worker.JobResourceReservation(estimate.cpu_slots, estimate.memory_mb)
        admission = self.worker.ResourceAdmission(
            cpu_budget=request.cpu_slots * max_active,
            memory_budget_mb=request.memory_mb * max_active,
            max_jobs=max_active,
        )
        pending = [f"job-{index:03d}" for index in range(job_count)]
        active: list[str] = []
        completed = 0
        while pending or active:
            while pending and admission.reserve(pending[0], request):
                active.append(pending.pop(0))
                self.assertLessEqual(admission.allocated_cpu_slots, admission.cpu_budget)
                self.assertLessEqual(admission.allocated_memory_mb, admission.memory_budget_mb)
                self.assertLessEqual(len(active), max_active)
            self.assertTrue(active, "simulation must always make progress")
            finished = active.pop(0)
            admission.release(finished)
            completed += 1
        self.assertEqual(completed, job_count)
        self.assertEqual(admission.allocated_cpu_slots, 0)
        self.assertEqual(admission.allocated_memory_mb, 0)

    def test_large_public_and_local_queue_simulations_never_overcommit(self) -> None:
        with self.subTest(workload="100 submissions x 15 genomes"):
            self._simulate_queue(100, 15, 3)
        with self.subTest(workload="5 concurrent jobs x 25 genomes"):
            self._simulate_queue(5, 25, 5)

    def test_stale_working_lease_recovers_exactly_once(self) -> None:
        settings = {"run_genome_prep": True, "genome_parallelism": 3}
        self.create_job("stale", status="running", stage="annotation", settings=settings)
        self.enqueue("stale", settings=settings, suffix=".working")

        with mock.patch.object(self.worker, "_stop_job_containers") as stop:
            first = self.worker.recover_orphaned_running_jobs()
            second = self.worker.recover_orphaned_running_jobs()

        self.assertEqual(first, ["stale"])
        self.assertEqual(second, [])
        stop.assert_called_once_with("stale", "interrupted job recovery")
        self.assertTrue((self.job_store.QUEUE_DIR / "stale.json").exists())
        self.assertFalse((self.job_store.QUEUE_DIR / "stale.working").exists())
        stored = self.job_store.read_job("stale")
        assert stored is not None
        self.assertEqual(stored["status"], "pending")
        self.assertFalse(stored["settings"]["run_genome_prep"])
        logs = self.job_store.read_logs("stale")
        self.assertEqual(sum("re-queued exactly once" in line for line in logs), 1)

    def test_stranded_pending_metadata_republishes_queue_exactly_once(self) -> None:
        self.create_job("stranded", cpus=6, settings={"genome_parallelism": 2})

        first = self.worker.recover_stranded_pending_jobs()
        second = self.worker.recover_stranded_pending_jobs()

        self.assertEqual(first, ["stranded"])
        self.assertEqual(second, [])
        queue = self.job_store.QUEUE_DIR / "stranded.json"
        self.assertTrue(queue.exists())
        payload = json.loads(queue.read_text(encoding="utf-8"))
        self.assertEqual(payload["cpus"], 6)
        self.assertEqual(payload["settings"]["genome_parallelism"], 2)
        logs = self.job_store.read_logs("stranded")
        self.assertEqual(sum("queue publication was interrupted" in line for line in logs), 1)

    def test_pending_recovery_grace_does_not_race_live_web_enqueue(self) -> None:
        fresh = self.create_job("fresh")
        fresh["created_at"] = self.job_store.now_iso()
        fresh["updated_at"] = fresh["created_at"]
        self.job_store.write_job(fresh)

        self.assertEqual(self.worker.recover_stranded_pending_jobs(), [])
        self.assertFalse((self.job_store.QUEUE_DIR / "fresh.json").exists())

    def test_canonical_raw_env_cannot_replace_admitted_resource_shape(self) -> None:
        canonical = sys.modules["canonical_pipeline"]
        parsed = canonical._parse_raw_env(
            "CUSTOM_LABEL=allowed\nCPUS=999\nANTISMASH_RECORD_PARALLELISM=999\nOMP_NUM_THREADS=999"
        )

        self.assertEqual(parsed, {"CUSTOM_LABEL": "allowed"})

    def test_orphan_recovery_stops_containers_before_queue_publication(self) -> None:
        self.create_job("orphan", status="running", stage="annotation")
        events: list[str] = []
        original_mark = self.worker._mark_recovered_pending

        def stop(*args: object, **kwargs: object) -> None:
            events.append("stop")

        def mark(*args: object, **kwargs: object) -> None:
            events.append("mark")
            original_mark(*args, **kwargs)

        with (
            mock.patch.object(self.worker, "_stop_job_containers", side_effect=stop),
            mock.patch.object(self.worker, "_mark_recovered_pending", side_effect=mark),
        ):
            recovered = self.worker.recover_orphaned_running_jobs()

        self.assertEqual(recovered, ["orphan"])
        self.assertEqual(events, ["stop", "mark"])
        self.assertTrue((self.job_store.QUEUE_DIR / "orphan.json").exists())

    def test_low_disk_holds_fifo_queue_without_claiming(self) -> None:
        self.create_job("diskheld")
        queue_path = self.enqueue("diskheld")
        admission = self.worker.ResourceAdmission(cpu_budget=16, memory_budget_mb=49152, max_jobs=3)

        with (
            mock.patch.object(self.worker, "WORKER_MIN_FREE_DISK_GB", 20.0),
            mock.patch.object(self.worker, "free_disk_gb", return_value=2.0),
        ):
            claim, reason = self.worker.claim_next_admissible_job(admission)

        self.assertIsNone(claim)
        self.assertIn("free disk", reason)
        self.assertTrue(queue_path.exists())
        self.assertFalse(queue_path.with_suffix(".working").exists())
        self.assertEqual(admission.allocated_cpu_slots, 0)

    def test_worker_status_exposes_budget_and_allocation(self) -> None:
        admission = self.worker.ResourceAdmission(cpu_budget=16, memory_budget_mb=49152, max_jobs=3)
        self.assertTrue(admission.reserve("active", self.worker.JobResourceReservation(8, 24576)))
        with mock.patch.object(self.worker, "runtime_health", return_value={"mode": "test"}):
            self.worker.write_worker_status(
                "processing",
                "test",
                active_jobs=["active"],
                admission=admission,
            )

        payload = json.loads(self.worker.WORKER_STATUS_PATH.read_text(encoding="utf-8"))
        resources = payload["worker"]["resource_admission"]
        self.assertEqual(resources["cpu_budget"], 16)
        self.assertEqual(resources["memory_budget_mb"], 49152)
        self.assertEqual(resources["allocated_cpu_slots"], 8)
        self.assertEqual(resources["allocated_memory_mb"], 24576)
        self.assertEqual(resources["reservations"]["active"]["cpu_slots"], 8)


if __name__ == "__main__":
    unittest.main()
