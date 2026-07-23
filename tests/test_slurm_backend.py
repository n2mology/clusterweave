from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"


class SlurmBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env_keys = [
            "DATA_DIR",
            "CLUSTERWEAVE_ROOT",
            "CLUSTERWEAVE_SOFTWARE_ROOT",
            "CLUSTERWEAVE_SLURM_ACCOUNT",
            "CLUSTERWEAVE_SLURM_PARTITION",
            "CLUSTERWEAVE_SLURM_QOS",
            "CLUSTERWEAVE_SLURM_TIME",
            "CLUSTERWEAVE_SLURM_MEM",
            "CLUSTERWEAVE_SLURM_NODES",
            "CLUSTERWEAVE_SLURM_CPUS_PER_TASK",
            "CLUSTERWEAVE_SLURM_MAX_SUBMITTED",
            "CLUSTERWEAVE_SLURM_WORKDIR",
            "CLUSTERWEAVE_SLURM_PROLOGUE",
            "ENGINE",
            "SLURM_JOB_ID",
            "SLURM_JOBID",
        ]
        self.old_env = {key: os.environ.get(key) for key in self.env_keys}
        os.environ.update(
            {
                "DATA_DIR": self.tmp.name,
                "CLUSTERWEAVE_ROOT": str(REPO_ROOT),
                "CLUSTERWEAVE_SOFTWARE_ROOT": str(Path(self.tmp.name) / "software"),
                "CLUSTERWEAVE_SLURM_ACCOUNT": "placeholder-account",
                "CLUSTERWEAVE_SLURM_PARTITION": "placeholder-partition",
                "CLUSTERWEAVE_SLURM_QOS": "placeholder-qos",
                "CLUSTERWEAVE_SLURM_TIME": "00:30:00",
                "CLUSTERWEAVE_SLURM_MEM": "8G",
                "CLUSTERWEAVE_SLURM_NODES": "1",
                "CLUSTERWEAVE_SLURM_CPUS_PER_TASK": "2",
                "CLUSTERWEAVE_SLURM_MAX_SUBMITTED": "2",
                "CLUSTERWEAVE_SLURM_PROLOGUE": "module purge\nmodule load apptainer",
                "ENGINE": "apptainer",
            }
        )
        self.inserted_web_path = False
        if str(WEB_DIR) not in sys.path:
            sys.path.insert(0, str(WEB_DIR))
            self.inserted_web_path = True
        for name in ["job_store", "notifications", "slurm_backend", "worker"]:
            sys.modules.pop(name, None)
        self.job_store = importlib.import_module("job_store")
        self.slurm_backend = importlib.import_module("slurm_backend")
        self.commands: list[list[str]] = []
        self.squeue_state = "RUNNING\n"
        self.sacct_state = "COMPLETED\n"

    def tearDown(self) -> None:
        for name in ["job_store", "notifications", "slurm_backend", "worker"]:
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

    def runner(self, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        self.commands.append(args)
        if args[0] == "sbatch":
            return subprocess.CompletedProcess(args, 0, "12345;placeholder\n", "")
        if args[0] == "squeue":
            return subprocess.CompletedProcess(args, 0, self.squeue_state, "")
        if args[0] == "sacct":
            return subprocess.CompletedProcess(args, 0, self.sacct_state, "")
        if args[0] == "scancel":
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"Unexpected command: {args}")

    def write_job(self, job_id: str = "jobabc") -> dict[str, object]:
        created = self.job_store.now_iso()
        job = {
            "id": job_id,
            "name": "slurm-case",
            "status": "pending",
            "stage": "queued",
            "created_at": created,
            "updated_at": created,
            "log_count": 0,
            "result_files": [],
            "error": None,
            "cpus": 3,
            "settings": {"project_name": "slurm-case", "run_summary": True},
            "submission_settings": {"project_name": "slurm-case", "run_summary": True},
        }
        self.job_store.write_job(job)
        return job

    def test_render_sbatch_script_uses_env_driven_scheduler_config(self) -> None:
        config = self.slurm_backend.SlurmConfig.from_env()
        slurm_dir = self.job_store.job_dir("jobabc") / "slurm"
        payload_path = slurm_dir / "queue_payload.json"
        script = self.slurm_backend.render_sbatch_script(
            config,
            job_id="jobabc",
            cpus=4,
            payload_path=payload_path,
            slurm_dir=slurm_dir,
        )

        self.assertIn("#SBATCH --job-name=cw-jobabc", script)
        self.assertIn("#SBATCH --export=NONE", script)
        self.assertIn("#SBATCH --account=placeholder-account", script)
        self.assertIn("#SBATCH --partition=placeholder-partition", script)
        self.assertIn("#SBATCH --qos=placeholder-qos", script)
        self.assertIn("#SBATCH --time=00:30:00", script)
        self.assertIn("#SBATCH --mem=8G", script)
        self.assertIn("#SBATCH --nodes=1", script)
        self.assertIn("#SBATCH --cpus-per-task=4", script)
        self.assertIn("export CLUSTERWEAVE_EXECUTOR=local", script)
        self.assertIn("export CLUSTERWEAVE_ENABLE_DOCKER_SOCKET=0", script)
        self.assertIn("export ENGINE=apptainer", script)
        self.assertIn("module load apptainer", script)
        self.assertIn("--once jobabc", script)
        self.assertIn("--queue-payload", script)

    def test_scheduler_commands_strip_service_credentials(self) -> None:
        sensitive = {
            "CLUSTERWEAVE_JOB_TOKEN_SECRET": "fake-job-secret",
            "CLUSTERWEAVE_SMTP_PASSWORD": "fake-smtp-secret",
            "CLUSTERWEAVE_ADMIN_TOKEN": "fake-admin-secret",
            "DOCKER_AUTH_CONFIG": "fake-docker-auth",
        }
        with mock.patch.dict(os.environ, sensitive, clear=False):
            child_env = self.slurm_backend._scheduler_command_env()
        for key in sensitive:
            self.assertNotIn(key, child_env)

        completed = subprocess.CompletedProcess(["squeue"], 0, "", "")
        with mock.patch.object(
            self.slurm_backend.subprocess, "run", return_value=completed
        ) as run:
            self.slurm_backend._default_runner(["squeue"], 5)
        passed_env = run.call_args.kwargs["env"]
        for key in sensitive:
            self.assertNotIn(key, passed_env)

    def test_slurm_state_parsing_and_clusterweave_mapping(self) -> None:
        self.assertEqual(self.slurm_backend.parse_sbatch_job_id("98765;cluster\n"), "98765")
        self.assertEqual(self.slurm_backend.parse_squeue_state("RUNNING\n"), "RUNNING")
        self.assertEqual(self.slurm_backend.parse_sacct_state("FAILED|1:0\n"), "FAILED")
        self.assertEqual(
            self.slurm_backend.clusterweave_status_for_slurm_state("PENDING"),
            ("pending", "queued on Slurm", None),
        )
        self.assertEqual(
            self.slurm_backend.clusterweave_status_for_slurm_state("RUNNING"),
            ("running", "running on Slurm", None),
        )
        self.assertEqual(
            self.slurm_backend.clusterweave_status_for_slurm_state("COMPLETED"),
            ("success", "complete", None),
        )
        status, stage, error = self.slurm_backend.clusterweave_status_for_slurm_state("TIMEOUT")
        self.assertEqual(status, "failed")
        self.assertEqual(stage, "failed")
        self.assertIn("TIMEOUT", error or "")

    def test_submit_poll_and_cancel_update_job_metadata_without_real_slurm(self) -> None:
        self.write_job("jobabc")
        backend = self.slurm_backend.SlurmBackend(
            config=self.slurm_backend.SlurmConfig.from_env(),
            runner=self.runner,
        )

        submitted = backend.submit_claim(("jobabc", 3, {"project_name": "slurm-case", "run_summary": True}))
        self.assertEqual(submitted, "jobabc")
        job = self.job_store.read_job("jobabc")
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["executor"], "slurm")
        self.assertEqual(job["slurm_job_id"], "12345")
        self.assertEqual(job["scheduler"]["kind"], "slurm")
        self.assertEqual(job["scheduler"]["state"], "PENDING")
        self.assertTrue((self.job_store.job_dir("jobabc") / "slurm" / "submit.sbatch").exists())
        self.assertTrue((self.job_store.job_dir("jobabc") / "slurm" / "queue_payload.json").exists())
        self.assertTrue(any(cmd[:3] == ["sbatch", "--export=NONE", "--parsable"] for cmd in self.commands))

        backend.poll_once()
        running = self.job_store.read_job("jobabc")
        self.assertIsNotNone(running)
        assert running is not None
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["stage"], "running on Slurm")
        self.assertEqual(running["scheduler"]["state"], "RUNNING")

        self.squeue_state = ""
        backend.poll_once()
        complete = self.job_store.read_job("jobabc")
        self.assertIsNotNone(complete)
        assert complete is not None
        self.assertEqual(complete["status"], "success")
        self.assertEqual(complete["stage"], "complete")
        self.assertEqual(complete["scheduler"]["state"], "COMPLETED")
        self.assertTrue(any(cmd[0] == "sacct" for cmd in self.commands))

        self.write_job("cancelme")
        cancel_job = self.job_store.read_job("cancelme")
        assert cancel_job is not None
        cancel_job["status"] = "running"
        cancel_job["executor"] = "slurm"
        cancel_job["slurm_job_id"] = "67890"
        cancel_job["scheduler"] = {"kind": "slurm", "job_id": "67890", "state": "RUNNING"}
        self.job_store.write_job(cancel_job)
        self.job_store.request_job_cancel("cancelme", "test cancellation")
        backend.poll_once()
        cancelled = self.job_store.read_job("cancelme")
        self.assertIsNotNone(cancelled)
        assert cancelled is not None
        self.assertEqual(cancelled["status"], "failed")
        self.assertEqual(cancelled["stage"], "cancelled")
        self.assertEqual(cancelled["scheduler"]["state"], "CANCELLED")
        self.assertTrue(any(cmd[:2] == ["scancel", "67890"] for cmd in self.commands))

    def test_scheduler_error_logs_redact_credentials(self) -> None:
        self.write_job("failsecret")

        def failing_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args,
                1,
                "",
                (
                    "Authorization: Bearer fake-slurm-secret; "
                    "--token fake-cli-secret; "
                    "https://user:fake-userinfo-secret@example.invalid"
                ),
            )

        backend = self.slurm_backend.SlurmBackend(
            config=self.slurm_backend.SlurmConfig.from_env(),
            runner=failing_runner,
        )
        self.assertIsNone(
            backend.submit_claim(
                ("failsecret", 2, {"project_name": "slurm-case", "run_summary": True})
            )
        )
        rendered = "\n".join(self.job_store.read_logs("failsecret"))
        self.assertIn("Authorization: [redacted]", rendered)
        self.assertNotIn("fake-slurm-secret", rendered)
        self.assertNotIn("fake-cli-secret", rendered)
        self.assertNotIn("fake-userinfo-secret", rendered)

    def test_poll_refreshes_scheduler_metadata_for_terminal_clusterweave_job(self) -> None:
        self.write_job("fastfail")
        job = self.job_store.read_job("fastfail")
        assert job is not None
        job["status"] = "failed"
        job["stage"] = "Preparing ClusterWeave project layout"
        job["error"] = "pipeline failed before scheduler poll"
        job["executor"] = "slurm"
        job["slurm_job_id"] = "54321"
        job["scheduler"] = {
            "kind": "slurm",
            "job_id": "54321",
            "state": "PENDING",
            "clusterweave_status": "pending",
        }
        self.job_store.write_job(job)

        self.squeue_state = ""
        self.sacct_state = "FAILED|1:0\n"
        backend = self.slurm_backend.SlurmBackend(
            config=self.slurm_backend.SlurmConfig.from_env(),
            runner=self.runner,
        )

        active = backend.poll_once()

        self.assertEqual(active, [])
        refreshed = self.job_store.read_job("fastfail")
        self.assertIsNotNone(refreshed)
        assert refreshed is not None
        self.assertEqual(refreshed["status"], "failed")
        self.assertEqual(refreshed["stage"], "Preparing ClusterWeave project layout")
        self.assertEqual(refreshed["error"], "pipeline failed before scheduler poll")
        self.assertEqual(refreshed["scheduler"]["state"], "FAILED")
        self.assertEqual(refreshed["scheduler"]["clusterweave_status"], "failed")
        self.assertTrue(any(cmd[0] == "sacct" and "54321" in cmd for cmd in self.commands))

    def test_worker_one_shot_claim_uses_captured_queue_payload(self) -> None:
        self.write_job("jobonce")
        payload_path = self.job_store.job_dir("jobonce") / "slurm" / "queue_payload.json"
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(
            '{"job_id": "jobonce", "cpus": 7, "settings": {"project_name": "from-payload", "run_figures": false}}',
            encoding="utf-8",
        )

        worker = importlib.import_module("worker")
        cpus, settings = worker._one_shot_claim("jobonce", queue_payload=str(payload_path))

        self.assertEqual(cpus, 7)
        self.assertEqual(settings["project_name"], "from-payload")
        self.assertFalse(settings["run_figures"])

    def test_worker_persist_job_recovers_runtime_slurm_metadata(self) -> None:
        self.write_job("jobruntime")
        os.environ["SLURM_JOB_ID"] = "24680"
        worker = importlib.import_module("worker")

        meta = self.job_store.read_job("jobruntime")
        assert meta is not None
        job = worker.build_job_from_meta(meta)
        job.status = worker.JobStatus.SUCCESS
        job.stage = "complete"

        worker.persist_job(job, 4, {"project_name": "runtime-slurm"})

        stored = self.job_store.read_job("jobruntime")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["status"], "success")
        self.assertEqual(stored["executor"], "slurm")
        self.assertEqual(stored["slurm_job_id"], "24680")
        self.assertEqual(stored["scheduler"]["kind"], "slurm")
        self.assertEqual(stored["scheduler"]["job_id"], "24680")
        self.assertEqual(stored["scheduler"]["state"], "RUNNING")
        self.assertEqual(stored["scheduler"]["clusterweave_status"], "success")


if __name__ == "__main__":
    unittest.main()
