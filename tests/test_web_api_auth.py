from __future__ import annotations

import http.client
import importlib
import json
import os
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
            }
        )
        os.environ.pop("CLUSTERWEAVE_ALLOWED_ORIGINS", None)

        self.inserted_web_path = False
        if str(WEB_DIR) not in sys.path:
            sys.path.insert(0, str(WEB_DIR))
            self.inserted_web_path = True
        for name in ["app", "job_store"]:
            sys.modules.pop(name, None)
        self.job_store = importlib.import_module("job_store")
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
        for name in ["app", "job_store"]:
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
        token: str = "submit-secret",
    ) -> tuple[int, object, dict[str, str]]:
        body, content_type = self.multipart_body(
            fields or {"project_name": "auth-case", "cpus": "2"},
            files or [("files", "accessions.txt", b"GCF_000001405.40\n")],
        )
        headers = {"Content-Type": content_type, **self.auth(token)}
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
            {"online", "service", "submissions_open", "submissions", "jobs_processed"},
        )
        self.assertEqual(payload["jobs_processed"], 1)
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
