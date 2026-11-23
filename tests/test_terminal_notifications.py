from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib
import os
from pathlib import Path
import smtplib
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


WEB_DIR = Path(__file__).resolve().parents[1] / "web"


class TerminalNotificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {
            "DATA_DIR": self.tmp.name,
            "CLUSTERWEAVE_SMTP_ENABLED": "1",
            "CLUSTERWEAVE_PUBLIC_BASE_URL": "https://example.org/",
            "WORKER_MIN_FREE_DISK_GB": "0",
        })
        self.env.start()
        self.modules = ["notifications", "job_store", "worker", "slurm_backend"]
        self.saved_modules = {name: sys.modules.pop(name, None) for name in self.modules}
        sys.path.insert(0, str(WEB_DIR))
        self.store = importlib.import_module("job_store")
        self.notifications = importlib.import_module("notifications")
        self.delivery = mock.patch.object(self.notifications, "deliver_email")
        self.send = self.delivery.start()
        self.job = {
            "id": "notice", "name": "Example", "status": "success", "stage": "complete",
            "notify_email": "user@example.org", "settings": {}, "cpus": 1,
            "created_at": self.store.now_iso(), "retention_days": 30,
            "read_token_hashes": ["existing-access"],
        }
        self.store.write_job(self.job)

    def tearDown(self) -> None:
        self.delivery.stop()
        for name in self.modules:
            sys.modules.pop(name, None)
            if self.saved_modules[name] is not None:
                sys.modules[name] = self.saved_modules[name]
        sys.path.remove(str(WEB_DIR))
        self.env.stop()
        self.tmp.cleanup()

    def update(self, **values):
        job = self.store.read_job("notice")
        job.update(values)
        self.store.write_job(job)
        return job

    def notify(self, **kwargs):
        return self.notifications.maybe_send_terminal_notification("notice", **kwargs)

    def test_only_configured_terminal_jobs_are_eligible(self) -> None:
        for values in [{"status": "pending"}, {"status": "running"},
                       {"status": "success", "notify_email": ""},
                       {"notify_email": "invalid"}]:
            self.update(**values)
            self.assertIsNone(self.notify())
        self.update(notify_email="user@example.org")
        with mock.patch.dict(os.environ, {"CLUSTERWEAVE_SMTP_ENABLED": "0"}):
            self.assertIsNone(self.notify())
        self.assertIsNone(self.notifications.maybe_send_terminal_notification("absent"))
        self.send.assert_not_called()
        self.assertNotIn("notification", self.store.read_job("notice"))

    def test_one_notice_for_each_accepted_attempt_even_with_same_outcome(self) -> None:
        ids = []
        for attempt in range(4):
            self.update(rerun_count=attempt, status="pending")
            self.assertIsNone(self.notify())
            self.update(status="success")
            outcome = self.notify()
            self.assertEqual(outcome["attempt"], attempt)
            self.assertEqual(outcome["outcome"], "success")
            self.assertEqual(outcome["delivery"], "sent")
            ids.append(str(self.send.call_args.args[0]["Message-ID"]))
            self.assertEqual(self.notify(), outcome)
            self.update(status="failed", stage="failed")
            self.assertEqual(self.notify(), outcome)
        self.assertEqual(self.send.call_count, 4)
        self.assertEqual(len(set(ids)), 4)
        self.assertIn("existing-access", self.store.read_job("notice")["read_token_hashes"])

    def test_legacy_sent_record_suppresses_initial_but_not_rerun(self) -> None:
        old = {"status": "success", "sent_at": "2026-01-01", "delivery": "sent"}
        self.update(notification=old)
        self.assertEqual(self.notify(), old)
        self.send.assert_not_called()
        self.update(rerun_count=1)
        self.assertEqual(self.notify()["attempt"], 1)
        self.send.assert_called_once()

    def test_confirmed_rejection_can_retry_without_duplicate_after_success(self) -> None:
        self.send.side_effect = [smtplib.SMTPConnectError(421, "secret transport detail"), None]
        failed = self.notify()
        self.assertEqual(failed["delivery"], "failed")
        self.assertNotIn("secret", str(failed))
        first_id = str(self.send.call_args.args[0]["Message-ID"])
        self.assertEqual(self.notify()["delivery"], "sent")
        self.assertEqual(str(self.send.call_args.args[0]["Message-ID"]), first_id)
        self.notify()
        self.assertEqual(self.send.call_count, 2)

    def test_explicit_smtp_rejections_remain_retryable(self) -> None:
        errors = [smtplib.SMTPConnectError(421, "rejected"),
                  smtplib.SMTPHeloError(550, "rejected"),
                  smtplib.SMTPAuthenticationError(535, "rejected"),
                  smtplib.SMTPSenderRefused(550, "rejected", "sender@example.org"),
                  smtplib.SMTPRecipientsRefused({"user@example.org": (550, "rejected")}),
                  smtplib.SMTPDataError(554, "rejected")]
        for attempt, error in enumerate(errors):
            with self.subTest(error=type(error).__name__):
                self.update(rerun_count=attempt)
                self.send.side_effect = error
                self.assertEqual(self.notify()["delivery"], "failed")
                self.send.side_effect = None
                self.assertEqual(self.notify()["delivery"], "sent")
        self.assertEqual(self.send.call_count, 2 * len(errors))

    def test_delivery_acknowledged_but_persistence_failure_does_not_resend(self) -> None:
        write = self.store.write_job
        calls = []
        def fail_completion(job):
            calls.append(job)
            if len(calls) == 2:
                raise OSError("temporary metadata error")
            write(job)
        with mock.patch.object(self.notifications, "write_job", side_effect=fail_completion):
            with self.assertRaises(OSError):
                self.notify()
        self.assertEqual(self.notify()["delivery"], "sending")
        self.send.assert_called_once()

    def test_uncertain_handoff_and_interrupted_send_do_not_auto_retry(self) -> None:
        self.send.side_effect = smtplib.SMTPServerDisconnected("private server detail")
        outcome = self.notify()
        self.assertEqual(outcome["delivery"], "unknown")
        self.assertNotIn("private", str(outcome))
        self.assertEqual(self.notify(), outcome)
        self.send.assert_called_once()
        self.update(rerun_count=1)
        self.send.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.notify()
        self.assertEqual(self.store.read_job("notice")["notification"]["delivery"], "sending")
        self.send.side_effect = None
        self.assertEqual(self.notify()["delivery"], "sending")
        self.assertEqual(self.send.call_count, 2)

    def test_parallel_threads_send_once(self) -> None:
        barrier = threading.Barrier(8)
        def notify():
            barrier.wait(timeout=10)
            return self.notify()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: notify(), range(8)))
        self.send.assert_called_once()
        self.assertEqual(self.store.read_job("notice")["notification"]["delivery"], "sent")

    def test_parallel_processes_send_once(self) -> None:
        output = Path(self.tmp.name) / "deliveries"
        code = """
import sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import notifications
output=Path(sys.argv[2])
def deliver(message):
    with output.open('a') as handle: handle.write('sent\\n')
    time.sleep(0.1)
notifications.deliver_email=deliver
notifications.maybe_send_terminal_notification('notice')
"""
        children = [subprocess.Popen([sys.executable, "-I", "-B", "-c", code, str(WEB_DIR), str(output)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(4)]
        for child in children:
            _, stderr = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, stderr.decode())
        self.assertEqual(output.read_text(), "sent\n")

    def test_delivery_completion_cannot_overwrite_new_attempt(self) -> None:
        def deliver(message):
            with self.store.queue_admission_lock():
                self.update(rerun_count=1, status="pending", stage="queued")
            self.update(status="success", stage="complete")
            self.send.side_effect = None
            self.assertEqual(self.notify()["attempt"], 1)
        self.send.side_effect = deliver
        self.assertEqual(self.notify()["attempt"], 0)
        latest = self.store.read_job("notice")
        self.assertEqual(latest["rerun_count"], 1)
        self.assertEqual(latest["notification"]["attempt"], 1)
        self.assertEqual(latest["notification"]["delivery"], "sent")
        self.assertEqual(self.send.call_count, 2)

    def test_success_failure_and_confirmed_cancellation_have_distinct_messages(self) -> None:
        for attempt, status, stage, label in [(0, "success", "complete", "complete"),
                                               (1, "failed", "annotation", "failed"),
                                               (2, "failed", "cancelled", "cancelled")]:
            self.update(rerun_count=attempt, status=status, stage=stage,
                        error="/private/path SECRET_TOKEN=hidden")
            if stage == "cancelled":
                self.assertIsNone(self.notify())
            result = self.notify(cancellation_confirmed=stage == "cancelled")
            message = self.send.call_args.args[0]
            self.assertTrue(str(message["Subject"]).endswith(": " + label))
            body = message.get_content()
            self.assertNotIn("/private/path", body)
            self.assertNotIn("SECRET_TOKEN", body)
            self.assertIn("Result access code:", body)
            self.assertEqual(result["outcome"], "cancelled" if stage == "cancelled" else status)
            if stage == "cancelled":
                self.assertIn("was cancelled", body)
                self.assertNotIn("Suggested fixes:", body)
                self.assertNotIn("Failed stage:", body)
        self.assertEqual(self.store.read_job("notice")["status"], "failed")

    def test_local_marker_waits_for_finalization_and_notifies_before_deletion(self) -> None:
        worker = importlib.import_module("worker")
        self.update(status="running", stage="running")
        self.store.request_job_cancel("notice", delete_after_cancel=True)
        self.assertIsNone(self.notify())
        def delivered(message):
            self.assertTrue(self.store.job_dir("notice").exists())
            self.assertEqual(self.store.read_job("notice")["stage"], "cancelled")
        self.send.side_effect = delivered
        worker.finalize_cancelled_job("notice", 1, {})
        self.send.assert_called_once()
        self.assertFalse(self.store.job_dir("notice").exists())

    def test_active_local_task_stops_before_cancellation_notice(self) -> None:
        worker = importlib.import_module("worker")
        self.update(status="running", stage="running")
        stopped = []
        async def cancelled(*args):
            stopped.append("task exited")
            raise asyncio.CancelledError
        with mock.patch.object(worker, "process_one", side_effect=cancelled), \
             mock.patch.object(worker, "stop_job_containers", side_effect=lambda _: stopped.append("containers stopped")):
            self.send.side_effect = lambda _: self.assertEqual(stopped, ["task exited", "containers stopped"])
            asyncio.run(worker.process_claim("notice", 1, {}))
        self.send.assert_called_once()

    def test_compute_node_finalizer_defers_slurm_notice_and_deletion_until_poll(self):
        worker = importlib.import_module("worker")
        backend_module = importlib.import_module("slurm_backend")
        self.update(status="running", stage="annotation", executor="slurm", slurm_job_id="42",
                    scheduler={"kind": "slurm", "job_id": "42", "state": "RUNNING"})
        self.store.request_job_cancel("notice", delete_after_cancel=True)
        worker.finalize_cancelled_job("notice", 1, {})
        self.assertTrue(self.store.job_dir("notice").exists())
        self.send.assert_not_called()
        backend = backend_module.SlurmBackend(runner=mock.Mock(return_value=subprocess.CompletedProcess([], 0, "CANCELLED\n", "")))
        backend.poll_once()
        self.send.assert_called_once()
        self.assertFalse(self.store.job_dir("notice").exists())

    def test_slurm_terminal_notification_requires_scheduler_evidence(self):
        self.update(executor="slurm", slurm_job_id="42",
                    scheduler={"kind": "slurm", "job_id": "42", "state": "RUNNING"})
        self.assertIsNone(self.notify())
        self.send.assert_not_called()
        self.update(scheduler={"kind": "slurm", "job_id": "42", "state": "COMPLETED", "terminal_confirmed_at": self.store.now_iso()})
        self.assertEqual(self.notify()["delivery"], "sent")
        self.send.assert_called_once()

    def test_scheduler_failed_confirms_recorded_compute_cancellation(self):
        backend_module = importlib.import_module("slurm_backend")
        self.update(status="failed", stage="cancelled", executor="slurm", slurm_job_id="42",
                    scheduler={"kind": "slurm", "job_id": "42", "state": "RUNNING"})
        backend = backend_module.SlurmBackend(runner=mock.Mock(return_value=subprocess.CompletedProcess([], 0, "FAILED\n", "")))
        backend.poll_once()
        self.send.assert_called_once()
        self.assertTrue(str(self.send.call_args.args[0]["Subject"]).endswith(": cancelled"))

    def test_stale_scheduler_dispatch_cannot_notify_a_newer_attempt(self):
        self.update(rerun_count=1)
        self.assertIsNone(self.notify(expected_attempt=0))
        self.send.assert_not_called()
        self.assertEqual(self.notify(expected_attempt=1)["attempt"], 1)
        self.send.assert_called_once()

    def test_slurm_request_is_not_confirmation_but_polled_cancelled_is(self) -> None:
        backend_module = importlib.import_module("slurm_backend")
        for scheduler_id, returncode in [("42", 0), ("42", 1), ("", 0)]:
            with self.subTest(scheduler_id=scheduler_id, returncode=returncode):
                self.send.reset_mock()
                self.update(status="running", stage="running", notification={}, executor="slurm",
                            slurm_job_id=scheduler_id, scheduler={"kind": "slurm", "job_id": scheduler_id, "state": "RUNNING"})
                runner = mock.Mock(return_value=subprocess.CompletedProcess([], returncode, "", "unavailable"))
                backend = backend_module.SlurmBackend(config=backend_module.SlurmConfig.from_env(), runner=runner)
                backend.cancel_job(self.store.read_job("notice"))
                self.send.assert_not_called()
                for state in ["RUNNING", "UNKNOWN"]:
                    backend.apply_polled_state(self.store.read_job("notice"), state)
                    self.send.assert_not_called()
                backend.apply_polled_state(self.store.read_job("notice"), "CANCELLED")
                self.send.assert_called_once()
                backend.apply_polled_state(self.store.read_job("notice"), "CANCELLED")
                self.send.assert_called_once()
