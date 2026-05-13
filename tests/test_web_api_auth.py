from __future__ import annotations

import http.client
import importlib
import json
import os
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"


class WebApiAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env_keys = [
            "DATA_DIR",
            "CLUSTERWEAVE_PUBLIC_MODE",
            "CLUSTERWEAVE_SUBMIT_TOKEN",
            "CLUSTERWEAVE_ADMIN_TOKEN",
            "CLUSTERWEAVE_JOB_TOKEN_SECRET",
            "CLUSTERWEAVE_SUBMISSIONS_OPEN",
            "CLUSTERWEAVE_ALLOWED_ORIGINS",
            "CLUSTERWEAVE_ALLOW_ENV_OVERRIDES",
            "CLUSTERWEAVE_JOB_RETENTION_DAYS",
            "CLUSTERWEAVE_ALLOW_NEVER_EXPIRE_JOBS",
            "CLUSTERWEAVE_SMTP_ENABLED",
            "CLUSTERWEAVE_SMTP_HOST",
            "CLUSTERWEAVE_SMTP_PORT",
            "CLUSTERWEAVE_SMTP_USERNAME",
            "CLUSTERWEAVE_SMTP_PASSWORD",
            "CLUSTERWEAVE_SMTP_FROM",
            "CLUSTERWEAVE_SMTP_OUTBOX_DIR",
            "CLUSTERWEAVE_PUBLIC_BASE_URL",
            "CLUSTERWEAVE_MAX_ACCESSIONS",
            "CLUSTERWEAVE_MAX_GENOME_FILES",
            "CLUSTERWEAVE_MAX_UPLOAD_FILE_MB",
            "CLUSTERWEAVE_MAX_UPLOAD_TOTAL_MB",
            "CLUSTERWEAVE_MAX_QUEUED_JOBS",
            "CLUSTERWEAVE_MAX_CPUS_PER_JOB",
        ]
        self.old_env = {key: os.environ.get(key) for key in self.env_keys}
        os.environ.update(
            {
                "DATA_DIR": self.tmp.name,
                "CLUSTERWEAVE_PUBLIC_MODE": "1",
                "CLUSTERWEAVE_SUBMIT_TOKEN": "submit-secret",
                "CLUSTERWEAVE_ADMIN_TOKEN": "admin-secret",
                "CLUSTERWEAVE_JOB_TOKEN_SECRET": "job-token-secret",
                "CLUSTERWEAVE_SUBMISSIONS_OPEN": "1",
                "CLUSTERWEAVE_ALLOW_ENV_OVERRIDES": "0",
                "CLUSTERWEAVE_JOB_RETENTION_DAYS": "30",
                "CLUSTERWEAVE_SMTP_ENABLED": "0",
            }
        )
        os.environ.pop("CLUSTERWEAVE_ALLOWED_ORIGINS", None)

        self.inserted_web_path = False
        if str(WEB_DIR) not in sys.path:
            sys.path.insert(0, str(WEB_DIR))
            self.inserted_web_path = True
        for name in ["app", "job_store", "notifications"]:
            sys.modules.pop(name, None)
        self.job_store = importlib.import_module("job_store")
        self.notifications = importlib.import_module("notifications")
        self.app = importlib.import_module("app")
        self.write_ready_worker_status()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_host, self.base_port = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        for name in ["app", "job_store", "notifications"]:
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

    def write_ready_worker_status(self) -> None:
        worker_dir = Path(self.tmp.name) / "worker"
        worker_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "ready": True,
            "state": "idle",
            "phase": "idle",
            "progress": 100,
            "detail": "Ready for tests",
            "substep": "",
            "updated_at": self.job_store.now_iso(),
            "runtime": {"mode": "test"},
            "worker": {"active_jobs": [], "active_count": 0},
            "capabilities": {},
        }
        (worker_dir / "status.json").write_text(json.dumps(payload), encoding="utf-8")

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, object, dict[str, str]]:
        conn = http.client.HTTPConnection(self.base_host, self.base_port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        raw = response.read()
        response_headers = dict(response.getheaders())
        conn.close()
        if response_headers.get("Content-Type", "").startswith("application/json") and raw:
            return response.status, json.loads(raw.decode("utf-8")), response_headers
        return response.status, raw, response_headers

    def auth(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def submit(
        self,
        fields: dict[str, str] | None = None,
        files: list[tuple[str, str, bytes]] | None = None,
        token: str | None = "submit-secret",
    ) -> tuple[int, object, dict[str, str]]:
        merged_fields = {"project_name": "auth-case", "cpus": "2", "data_use_ack": "1"}
        if fields:
            merged_fields.update(fields)
        body, content_type = self.multipart_body(
            merged_fields,
            files or [("files", "accessions.txt", b"GCF_000001405.40\n")],
        )
        headers = {"Content-Type": content_type}
        if token:
            headers.update(self.auth(token))
        return self.request("POST", "/api/jobs", body=body, headers=headers)

    def multipart_body(
        self,
        fields: dict[str, str],
        files: list[tuple[str, str, bytes]],
    ) -> tuple[bytes, str]:
        boundary = "----ClusterWeaveTestBoundary"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        for field, filename, content in files:
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                    "Content-Type: text/plain\r\n\r\n"
                ).encode("utf-8")
            )
            chunks.append(content)
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    def write_job(self, job_id: str, read_token: str, status: str = "success") -> dict[str, object]:
        created = self.job_store.now_iso()
        job = {
            "id": job_id,
            "name": f"{job_id}-project",
            "status": status,
            "stage": "complete" if status == "success" else "queued",
            "created_at": created,
            "updated_at": created,
            "log_count": 1,
            "result_files": ["results/figure.svg"],
            "error": None,
            "cpus": 2,
            "settings": {"run_summary": True, "env_overrides": "SECRET_TOKEN=1"},
            "submission_settings": {"run_summary": True, "env_overrides": "SECRET_TOKEN=1"},
            "read_token_hash": self.app.job_token_hash(read_token),
            "read_token_created_at": created,
        }
        result_dir = self.job_store.job_dir(job_id) / "results"
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / "figure.svg").write_text("<svg></svg>\n", encoding="utf-8")
        self.job_store.write_job(job)
        self.job_store.append_log(job_id, "test log line")
        return job

    def test_anonymous_public_mode_gets_only_redacted_status_and_no_job_access(self) -> None:
        self.write_job("jobone", "read-one")

        status, payload, headers = self.request("GET", "/api/system/status", headers={"Origin": "https://example.invalid"})
        self.assertEqual(status, 200)
        self.assertEqual(
            set(payload),
            {"online", "service", "submissions_open", "submissions", "jobs_processed", "smtp_enabled"},
        )
        self.assertEqual(payload["jobs_processed"], 1)
        self.assertFalse(payload["smtp_enabled"])
        self.assertNotEqual(headers.get("Access-Control-Allow-Origin"), "*")

        protected_requests = [
            ("GET", "/api/jobs", None, {}),
            ("GET", "/api/jobs/jobone", None, {}),
            ("GET", "/api/jobs/jobone/logs", None, {}),
            ("GET", "/api/jobs/jobone/files", None, {}),
            ("GET", "/api/jobs/jobone/files/results/figure.svg", None, {}),
            ("POST", "/api/jobs/jobone/rerun", b"{}", {"Content-Type": "application/json"}),
            ("DELETE", "/api/jobs/jobone", None, {}),
        ]
        for method, path, body, headers in protected_requests:
            with self.subTest(path=path):
                status, _, _ = self.request(method, path, body=body, headers=headers)
                self.assertEqual(status, 401)

    def test_submit_token_creates_job_and_returns_unstored_read_token(self) -> None:
        status, payload, _ = self.submit(
            {"project_name": "auth-case", "cpus": "2"},
            [("files", "accessions.txt", b"GCF_000001405.40\n")],
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["status"], "pending")
        self.assertIn("expires_at", payload)
        read_token = payload["read_token"]
        self.assertIsInstance(read_token, str)
        self.assertNotEqual(read_token, "")

        job = self.job_store.read_job(payload["job_id"])
        self.assertIsNotNone(job)
        assert job is not None
        self.assertNotIn("read_token", job)
        self.assertIn("read_token_hash", job)
        self.assertNotEqual(job["read_token_hash"], read_token)

        status, _, _ = self.request("GET", "/api/jobs", headers=self.auth("submit-secret"))
        self.assertEqual(status, 403)

        status, job_payload, _ = self.request("GET", f"/api/jobs/{payload['job_id']}", headers=self.auth(read_token))
        self.assertEqual(status, 200)
        self.assertNotIn("read_token_hash", job_payload)
        self.assertNotIn("read_token_created_at", job_payload)

    def test_invite_only_public_submission_rejects_missing_submission_code(self) -> None:
        status, payload, _ = self.submit(token=None)
        self.assertEqual(status, 401)
        self.assertIn("Submission access code", payload["detail"])

    def test_open_public_submission_accepts_missing_submission_code_when_no_submit_token_is_configured(self) -> None:
        self.app.SUBMIT_TOKEN = ""
        status, payload, _ = self.submit(token=None)
        self.assertEqual(status, 201)
        self.assertEqual(payload["status"], "pending")
        self.assertTrue(payload["read_token"])

    def test_public_submission_requires_data_use_acknowledgment(self) -> None:
        status, payload, _ = self.submit(fields={"data_use_ack": "0"})
        self.assertEqual(status, 400)
        self.assertIn("Data-use acknowledgment", payload["detail"])

    def test_notification_email_is_stored_only_when_smtp_enabled(self) -> None:
        fields = {"project_name": "email-case", "notify_email": "user@example.org"}
        status, payload, _ = self.submit(fields=fields)
        self.assertEqual(status, 400)
        self.assertIn("Email notifications", payload["detail"])

        self.app.SMTP_ENABLED = True
        status, payload, _ = self.submit(fields=fields)
        self.assertEqual(status, 201)
        job = self.job_store.read_job(payload["job_id"])
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["notify_email"], "user@example.org")
        logs = "\n".join(self.job_store.read_logs(payload["job_id"]))
        self.assertNotIn("user@example.org", logs)

        status, job_payload, _ = self.request("GET", f"/api/jobs/{payload['job_id']}", headers=self.auth(payload["read_token"]))
        self.assertEqual(status, 200)
        self.assertNotIn("notify_email", job_payload)

    def test_read_token_unlocks_only_its_job_logs_and_files(self) -> None:
        self.write_job("jobone", "read-one")
        self.write_job("jobtwo", "read-two")

        status, payload, _ = self.request("GET", "/api/jobs/jobone", headers=self.auth("read-one"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], "jobone")
        self.assertEqual(payload["settings"]["env_overrides"], "[redacted]")

        status, _, _ = self.request("GET", "/api/jobs/jobtwo", headers=self.auth("read-one"))
        self.assertEqual(status, 403)

        status, payload, _ = self.request("GET", "/api/jobs/jobone/logs", headers=self.auth("read-one"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)

        status, payload, _ = self.request("GET", "/api/jobs/jobone/files", headers=self.auth("read-one"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["files"], ["results/figure.svg"])

        status, body, _ = self.request("GET", "/api/jobs/jobone/files/results/figure.svg", headers=self.auth("read-one"))
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<svg></svg>\n")

    def test_public_activity_events_sanitize_per_genome_runtime_logs(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        self.job_store.write_logs(
            "jobone",
            [
                "[08:04:16] Stage 1/4: running run_annotation_and_detection.sh",
                "[08:04:20] Genomes to process (4): fungus_id1, fungus id2, /data/jobs/jobone/private/fungus_id3.fna, fungus_id4",
                "[08:04:21] [1/4] genome=fungus_id1",
                "[08:04:22] [2026-05-12 08:04:22] [INFO] fungus_id1: running antiSMASH (outdir=/data/jobs/jobone/private/secret)",
                "[08:04:23] [2026-05-12 08:04:23] [INFO] fungus_id4: running FunBGCeX (outdir=/data/jobs/jobone/private/secret)",
                "[08:04:24] Stage 2/4: running run_bigscape.sh",
            ],
        )

        status, payload, _ = self.request("GET", "/api/jobs/jobone", headers=self.auth("read-one"))
        self.assertEqual(status, 200)
        events = payload["public_events"]
        rendered = json.dumps(events)
        self.assertIn("Running antiSMASH on fungus_id1", rendered)
        self.assertIn("Running FunBGCeX on fungus_id4", rendered)
        self.assertIn("Running BiG-SCAPE family graph", rendered)
        self.assertNotIn("/data/jobs", rendered)
        self.assertNotIn("secret", rendered)

    def test_terminal_notification_email_is_sanitized_and_adds_read_token_hash(self) -> None:
        outbox = Path(self.tmp.name) / "outbox"
        os.environ["CLUSTERWEAVE_SMTP_ENABLED"] = "1"
        os.environ["CLUSTERWEAVE_SMTP_OUTBOX_DIR"] = str(outbox)
        os.environ["CLUSTERWEAVE_PUBLIC_BASE_URL"] = "https://clusterweave.example.org/app/"
        self.write_job("failjob", "read-one", status="failed")
        job = self.job_store.read_job("failjob")
        self.assertIsNotNone(job)
        assert job is not None
        job["notify_email"] = "user@example.org"
        job["stage"] = "Running canonical ClusterWeave workflow"
        job["error"] = "/data/jobs/failjob failed with SECRET_TOKEN=abc\nTraceback command --bad"
        self.job_store.write_job(job)

        outcome = self.notifications.maybe_send_terminal_notification("failjob")
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome["delivery"], "sent")
        updated = self.job_store.read_job("failjob")
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertIn("read_token_hashes", updated)
        self.assertTrue(updated["read_token_hashes"])
        self.assertEqual(updated["notification"]["delivery"], "sent")

        messages = list(outbox.glob("*.eml"))
        self.assertEqual(len(messages), 1)
        body = messages[0].read_text(encoding="utf-8")
        self.assertIn("https://clusterweave.example.org/app/#/job/failjob/", body)
        self.assertIn("Suggested fixes:", body)
        self.assertNotIn("/data/jobs", body)
        self.assertNotIn("SECRET_TOKEN", body)
        self.assertNotIn("Traceback", body)
        self.assertNotIn("command --bad", body)
        link = next(line for line in body.splitlines() if "#/job/failjob/" in line)
        email_token = link.rsplit("/", 1)[-1]
        status, payload, _ = self.request("GET", "/api/jobs/failjob", headers=self.auth(email_token))
        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], "failjob")

    def test_admin_token_unlocks_job_list_status_rerun_and_delete(self) -> None:
        self.write_job("jobone", "read-one")

        status, payload, _ = self.request("GET", "/api/jobs", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["id"], "jobone")
        self.assertNotIn("read_token_hash", payload[0])

        status, payload, _ = self.request("GET", "/api/system/status", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertIn("runtime", payload)
        self.assertIn("capabilities", payload)

        rerun_body = json.dumps({"run_summary": True, "cpus": 1}).encode("utf-8")
        headers = {"Content-Type": "application/json", **self.auth("admin-secret")}
        status, payload, _ = self.request("POST", "/api/jobs/jobone/rerun", body=rerun_body, headers=headers)
        self.assertEqual(status, 202)
        self.assertEqual(payload["status"], "pending")

        status, _, _ = self.request("DELETE", "/api/jobs/jobone", headers=self.auth("admin-secret"))
        self.assertEqual(status, 204)
        self.assertIsNone(self.job_store.read_job("jobone"))

    def test_public_deployment_smoke_role_matrix_and_result_file_access(self) -> None:
        self.write_job("smokeone", "read-one")

        status, payload, _ = self.request("GET", "/api/system/status")
        self.assertEqual(status, 200)
        self.assertEqual(
            set(payload),
            {"online", "service", "submissions_open", "submissions", "jobs_processed", "smtp_enabled"},
        )
        self.assertNotIn("worker", payload)
        self.assertNotIn("runtime", payload)
        self.assertNotIn("capabilities", payload)

        for method, path in [
            ("GET", "/api/jobs"),
            ("GET", "/api/jobs/smokeone"),
            ("GET", "/api/jobs/smokeone/logs"),
            ("GET", "/api/jobs/smokeone/files"),
            ("GET", "/api/jobs/smokeone/files/results/figure.svg?download=1"),
        ]:
            with self.subTest(role="anonymous", path=path):
                status, _, _ = self.request(method, path)
                self.assertEqual(status, 401)

        status, submitted, _ = self.submit(
            fields={"project_name": "smoke-submit", "cpus": "1"},
            files=[("files", "accessions.txt", b"GCF_000001405.40\n")],
        )
        self.assertEqual(status, 201)
        submitted_job_id = submitted["job_id"]
        submitted_read_token = submitted["read_token"]
        self.assertTrue(submitted_read_token)
        stored = self.job_store.read_job(submitted_job_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["status"], "pending")
        self.assertNotIn("read_token", stored)
        self.assertIn("read_token_hash", stored)

        status, _, _ = self.request("GET", "/api/jobs", headers=self.auth("submit-secret"))
        self.assertEqual(status, 403)

        status, own_job, _ = self.request("GET", f"/api/jobs/{submitted_job_id}", headers=self.auth(submitted_read_token))
        self.assertEqual(status, 200)
        self.assertEqual(own_job["id"], submitted_job_id)

        status, _, _ = self.request("GET", "/api/jobs/smokeone", headers=self.auth(submitted_read_token))
        self.assertEqual(status, 403)

        status, file_list, _ = self.request("GET", "/api/jobs/smokeone/files", headers=self.auth("read-one"))
        self.assertEqual(status, 200)
        self.assertEqual(file_list["files"], ["results/figure.svg"])

        status, body, headers = self.request("GET", "/api/jobs/smokeone/files/results/figure.svg", headers=self.auth("read-one"))
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<svg></svg>\n")
        self.assertIn("inline", headers.get("Content-Disposition", ""))

        status, _, headers = self.request(
            "GET",
            "/api/jobs/smokeone/files/results/figure.svg?download=1",
            headers=self.auth("read-one"),
        )
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers.get("Content-Disposition", ""))

        status, admin_status, _ = self.request("GET", "/api/system/status", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertIn("runtime", admin_status)
        self.assertIn("worker", admin_status)

        status, jobs, _ = self.request("GET", "/api/jobs", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertGreaterEqual({job["id"] for job in jobs}, {"smokeone", submitted_job_id})

        status, logs, _ = self.request("GET", "/api/jobs/smokeone/logs", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertEqual(logs["total"], 1)

        rerun_body = json.dumps({"run_summary": True, "cpus": 1}).encode("utf-8")
        headers = {"Content-Type": "application/json", **self.auth("admin-secret")}
        status, rerun_payload, _ = self.request("POST", "/api/jobs/smokeone/rerun", body=rerun_body, headers=headers)
        self.assertEqual(status, 202)
        self.assertEqual(rerun_payload["status"], "pending")

        status, _, _ = self.request("DELETE", "/api/jobs/smokeone", headers=self.auth("admin-secret"))
        self.assertEqual(status, 204)
        self.assertIsNone(self.job_store.read_job("smokeone"))

    def test_local_mode_keeps_existing_lab_api_behavior_without_tokens(self) -> None:
        self.app.PUBLIC_MODE = False
        self.write_job("localjob", "read-local")

        status, payload, _ = self.request("GET", "/api/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["id"], "localjob")

        status, payload, _ = self.request("GET", "/api/system/status")
        self.assertEqual(status, 200)
        self.assertIn("runtime", payload)

        status, payload, _ = self.request("GET", "/api/jobs/localjob/logs")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)

        status, _, _ = self.request("DELETE", "/api/jobs/localjob")
        self.assertEqual(status, 204)

    def test_public_upload_policy_rejects_unsupported_inputs_before_job_creation(self) -> None:
        rejected_files = [
            ("table.csv", b"accession\nGCF_000001405.40\n"),
            ("table.tsv", b"accession\nGCF_000001405.40\n"),
            ("proteins.faa", b">protein\nMADEUP\n"),
            ("network.json", b"{}"),
            ("archive.zip", b"PK"),
        ]
        for filename, content in rejected_files:
            with self.subTest(filename=filename):
                status, payload, _ = self.submit(files=[("files", filename, content)])
                self.assertEqual(status, 400)
                self.assertIn("detail", payload)
                self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_accession_lists_reject_malformed_assembly_accessions_before_job_creation(self) -> None:
        rejected_files = [
            ("accessions.txt", b"totally_random\n"),
            ("accessions.txt", b"GCF_123\n"),
            ("accessions.txt", b"ABC_000001405.1\n"),
            ("accessions.txt", b"GCF_000001405\n"),
            ("manual_accessions.txt", b"not_an_assembly\n"),
        ]
        for filename, content in rejected_files:
            with self.subTest(filename=filename, content=content):
                status, payload, _ = self.submit(files=[("files", filename, content)])
                self.assertEqual(status, 400)
                self.assertIn("invalid accession", payload["detail"])
                self.assertIn("GCA_000011425.1", payload["detail"])
                self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_accession_lists_require_one_accession_per_line(self) -> None:
        status, payload, _ = self.submit(
            files=[("files", "accessions.txt", b"GCF_000001405.40 GCA_000011425.1\n")]
        )
        self.assertEqual(status, 400)
        self.assertIn("one accession per line", payload["detail"])
        self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_manual_accessions_are_validated_even_in_local_mode(self) -> None:
        self.app.PUBLIC_MODE = False
        status, payload, _ = self.submit(files=[("files", "manual_accessions.txt", b"random_accession\n")])
        self.assertEqual(status, 400)
        self.assertIn("invalid accession", payload["detail"])
        self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_public_ecology_metadata_requires_ecology_mode(self) -> None:
        files = [
            ("files", "Aspergillus_fumigatus_Af293.fna", b">seq\nATGC\n"),
            ("files", "ecofun_metadata_normalized.tsv", b"accession\tgenome_id_current\tecofun_primary\n\tAf293\tsoil\n"),
        ]

        status, payload, _ = self.submit(fields={"project_name": "eco-off", "run_ecology_analysis": "0"}, files=files)
        self.assertEqual(status, 400)
        self.assertIn("Ecology metadata", payload["detail"])

        status, payload, _ = self.submit(fields={"project_name": "eco-on", "run_ecology_analysis": "1"}, files=files)
        self.assertEqual(status, 201)
        job = self.job_store.read_job(payload["job_id"])
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["input_summary"]["metadata_file_count"], 1)
        self.assertEqual(job["input_summary"]["genome_file_count"], 1)

    def test_public_accession_and_genome_quotas_are_enforced(self) -> None:
        too_many_accessions = "\n".join(f"GCF_{idx:09d}.1" for idx in range(26)).encode("utf-8") + b"\n"
        status, payload, _ = self.submit(files=[("files", "accessions.txt", too_many_accessions)])
        self.assertEqual(status, 400)
        self.assertIn("25 accessions", payload["detail"])

        many_genomes = [
            ("files", f"genome_{idx}.fna", f">seq{idx}\nATGC\n".encode("utf-8"))
            for idx in range(26)
        ]
        status, payload, _ = self.submit(files=many_genomes)
        self.assertEqual(status, 400)
        self.assertIn("25 genome files", payload["detail"])

    def test_public_upload_size_and_queue_quotas_are_enforced(self) -> None:
        self.app.MAX_UPLOAD_FILE_MB = 1
        status, payload, _ = self.submit(files=[("files", "large.fna", b"A" * (1024 * 1024 + 1))])
        self.assertEqual(status, 400)
        self.assertIn("1 MB", payload["detail"])

        self.app.MAX_UPLOAD_TOTAL_MB = 1
        files = [
            ("files", "one.fna", b"A" * (700 * 1024)),
            ("files", "two.fna", b"A" * (400 * 1024)),
        ]
        status, payload, _ = self.submit(files=files)
        self.assertEqual(status, 400)
        self.assertIn("Total upload size", payload["detail"])

        self.app.MAX_QUEUED_JOBS = 0
        status, payload, _ = self.submit()
        self.assertEqual(status, 429)
        self.assertIn("queue is full", payload["detail"])

    def test_public_cpu_clamping_and_retention_metadata(self) -> None:
        fields = {
            "project_name": "quota-case",
            "cpus": "64",
            "threads": "64",
            "anno_cpus": "64",
            "workers": "64",
        }
        status, payload, _ = self.submit(fields=fields)
        self.assertEqual(status, 201)

        job = self.job_store.read_job(payload["job_id"])
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["cpus"], min(8, os.cpu_count() or 8))
        self.assertLessEqual(job["settings"]["threads"], job["cpus"])
        self.assertLessEqual(job["settings"]["anno_cpus"], job["cpus"])
        self.assertLessEqual(job["settings"]["workers"], job["cpus"])
        self.assertEqual(job["retention_days"], 30)
        self.assertIn("expires_at", job)
        self.assertNotIn("completed_at", job)
        self.assertNotIn("failed_at", job)

        job["status"] = "success"
        job["updated_at"] = "2026-01-01T00:00:00"
        self.job_store.write_job(job)
        completed = self.job_store.read_job(payload["job_id"])
        self.assertIsNotNone(completed)
        assert completed is not None
        self.assertEqual(completed["completed_at"], "2026-01-01T00:00:00")
        self.assertEqual(completed["expires_at"], "2026-01-31T00:00:00")

    def test_retention_never_requires_explicit_admin_opt_in(self) -> None:
        os.environ["CLUSTERWEAVE_JOB_RETENTION_DAYS"] = "0"
        os.environ.pop("CLUSTERWEAVE_ALLOW_NEVER_EXPIRE_JOBS", None)
        with self.assertRaises(ValueError):
            self.job_store.configured_retention_days()

        os.environ["CLUSTERWEAVE_ALLOW_NEVER_EXPIRE_JOBS"] = "1"
        self.assertIsNone(self.job_store.configured_retention_days())

    def test_retention_sweeper_deletes_expired_jobs_and_keeps_only_aggregate_counters(self) -> None:
        created = "2026-01-01T00:00:00"
        job = {
            "id": "oldjob",
            "name": "old-project",
            "status": "success",
            "stage": "complete",
            "created_at": created,
            "updated_at": created,
            "completed_at": created,
            "log_count": 1,
            "result_files": ["results/figure.svg"],
            "error": None,
            "cpus": 2,
            "settings": {},
            "submission_settings": {},
            "notify_email": "user@example.org",
            "read_token_hash": "secret-hash",
            "read_token_hashes": ["email-secret-hash"],
            "email_read_token_created_at": created,
        }
        result_dir = self.job_store.job_dir("oldjob") / "results"
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / "figure.svg").write_text("<svg></svg>\n", encoding="utf-8")
        self.job_store.write_job(job)
        self.job_store.append_log("oldjob", "log line")
        queue_path = Path(self.tmp.name) / "queue" / "oldjob.json"
        queue_path.write_text("{}", encoding="utf-8")

        result = self.job_store.sweep_expired_jobs(now=datetime.fromisoformat("2026-02-01T00:00:00"))
        self.assertEqual(result["deleted_jobs"], 1)
        self.assertFalse(self.job_store.job_dir("oldjob").exists())
        self.assertFalse(queue_path.exists())

        totals_path = Path(self.tmp.name) / "retention" / "sweep_totals.json"
        self.assertTrue(totals_path.exists())
        totals_text = totals_path.read_text(encoding="utf-8")
        self.assertIn("expired_jobs_deleted", totals_text)
        self.assertNotIn("user@example.org", totals_text)
        self.assertNotIn("secret-hash", totals_text)

    def test_public_raw_controls_are_blocked_unless_admin_env_overrides_are_enabled(self) -> None:
        status, payload, _ = self.submit(fields={"project_name": "nplinker-case", "run_nplinker": "1"})
        self.assertEqual(status, 400)
        self.assertIn("NPLinker", payload["detail"])

        status, payload, _ = self.submit(fields={"project_name": "metadata-path", "metadata_tsv": "/tmp/raw.tsv"})
        self.assertEqual(status, 400)
        self.assertIn("metadata paths", payload["detail"])

        status, payload, _ = self.submit(fields={"project_name": "env-case", "env_overrides": "SECRET=1"})
        self.assertEqual(status, 400)
        self.assertIn("environment overrides", payload["detail"])

        status, payload, _ = self.submit(
            fields={"project_name": "admin-env-denied", "env_overrides": "SECRET=1"},
            token="admin-secret",
        )
        self.assertEqual(status, 400)
        self.assertIn("environment overrides", payload["detail"])

        self.app.ALLOW_ENV_OVERRIDES = True
        status, payload, _ = self.submit(
            fields={"project_name": "admin-env-allowed", "env_overrides": "SECRET=1"},
            token="admin-secret",
        )
        self.assertEqual(status, 201)
        job = self.job_store.read_job(payload["job_id"])
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["settings"]["env_overrides"], "SECRET=1")


if __name__ == "__main__":
    unittest.main()
