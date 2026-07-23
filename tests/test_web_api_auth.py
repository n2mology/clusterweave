from __future__ import annotations

import hashlib
import http.client
import importlib
import io
import json
import os
from contextlib import redirect_stderr
from datetime import datetime, timezone
import sqlite3
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import zipfile


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
            "CLUSTERWEAVE_ADMIN_TOKEN_SHA256",
            "CLUSTERWEAVE_ADMIN_TOKEN_HASH",
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
            "CLUSTERWEAVE_SMTP_TLS",
            "CLUSTERWEAVE_SMTP_SSL",
            "CLUSTERWEAVE_SMTP_OUTBOX_DIR",
            "CLUSTERWEAVE_PUBLIC_BASE_URL",
            "CLUSTERWEAVE_MAX_ACCESSIONS",
            "CLUSTERWEAVE_MAX_GENOME_FILES",
            "CLUSTERWEAVE_MAX_UPLOAD_FILE_MB",
            "CLUSTERWEAVE_MAX_UPLOAD_TOTAL_MB",
            "CLUSTERWEAVE_MAX_UPLOAD_BODY_OVERHEAD_MB",
            "CLUSTERWEAVE_MAX_CONCURRENT_UPLOADS",
            "CLUSTERWEAVE_UPLOAD_STAGING_DIR",
            "CLUSTERWEAVE_MAX_QUEUED_JOBS",
            "CLUSTERWEAVE_MAX_CPUS_PER_JOB",
            "CLUSTERWEAVE_MIN_FREE_DISK_GB",
            "CLUSTERWEAVE_PUBLIC_GENOME_PARALLELISM",
            "CLUSTERWEAVE_PUBLIC_ANTISMASH_RECORD_PARALLELISM",
            "CLUSTERWEAVE_PUBLIC_FUNANNOTATE_CPUS_PER_GENOME",
            "CLUSTERWEAVE_PUBLIC_FUNBGCEX_WORKERS_PER_GENOME",
            "CLUSTERWEAVE_NCBI_ACCESSION_PREFLIGHT",
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
                "CLUSTERWEAVE_NCBI_ACCESSION_PREFLIGHT": "1",
            }
        )
        os.environ.pop("CLUSTERWEAVE_ALLOWED_ORIGINS", None)
        os.environ.pop("CLUSTERWEAVE_ADMIN_TOKEN_SHA256", None)
        os.environ.pop("CLUSTERWEAVE_ADMIN_TOKEN_HASH", None)

        self.inserted_web_path = False
        if str(WEB_DIR) not in sys.path:
            sys.path.insert(0, str(WEB_DIR))
            self.inserted_web_path = True
        for name in ["app", "job_store", "notifications"]:
            sys.modules.pop(name, None)
        self.job_store = importlib.import_module("job_store")
        self.notifications = importlib.import_module("notifications")
        self.app = importlib.import_module("app")
        self.app.fetch_ncbi_datasets_json = self.fake_ncbi_datasets_json
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

    def fake_ncbi_datasets_json(self, path: str) -> dict[str, object]:
        accession_reports = {
            "GCA_000011425.1": {"tax_id": 227321, "name": "Aspergillus nidulans FGSC A4", "status": "current", "strain": "FGSC A4"},
            "GCA_030770425.1": {"tax_id": 2704583, "name": "Darksidea phi", "status": "current"},
            "GCF_000011425.1": {"tax_id": 227321, "name": "Aspergillus nidulans FGSC A4", "status": "current", "strain": "FGSC A4"},
            "GCF_000001405.40": {"tax_id": 9606, "name": "Homo sapiens", "status": "current"},
            "GCF_000005845.2": {"tax_id": 511145, "name": "Escherichia coli str. K-12 substr. MG1655", "status": "current"},
            "GCF_000000001.1": {"tax_id": 227321, "name": "Aspergillus nidulans FGSC A4", "status": "current"},
        }
        taxonomy = {
            227321: {
                "organism_name": "Aspergillus nidulans FGSC A4",
                "lineage": [1, 131567, 2759, 4751, 4890],
                "classification": {
                    "domain": {"id": 2759, "name": "Eukaryota"},
                    "kingdom": {"id": 4751, "name": "Fungi"},
                    "phylum": {"id": 4890, "name": "Ascomycota"},
                    "class": {"id": 147545, "name": "Eurotiomycetes"},
                    "order": {"id": 5042, "name": "Eurotiales"},
                    "family": {"id": 1131492, "name": "Aspergillaceae"},
                    "genus": {"id": 5052, "name": "Aspergillus"},
                    "species": {"id": 162425, "name": "Aspergillus nidulans"},
                },
            },
            2704583: {
                "organism_name": "Darksidea phi",
                "lineage": [1, 131567, 2759, 4751, 4890],
                "classification": {
                    "domain": {"id": 2759, "name": "Eukaryota"},
                    "kingdom": {"id": 4751, "name": "Fungi"},
                    "phylum": {"id": 4890, "name": "Ascomycota"},
                    "class": {"id": 147541, "name": "Dothideomycetes"},
                    "order": {"id": 501485, "name": "Pleosporales"},
                    "family": {"id": 93133, "name": "Pleosporaceae"},
                    "genus": {"id": 2704582, "name": "Darksidea"},
                    "species": {"id": 2704583, "name": "Darksidea phi"},
                },
            },
            9606: {
                "organism_name": "Homo sapiens",
                "lineage": [1, 131567, 2759, 33208, 7711, 9605],
                "classification": {
                    "domain": {"id": 2759, "name": "Eukaryota"},
                    "kingdom": {"id": 33208, "name": "Metazoa"},
                    "phylum": {"id": 7711, "name": "Chordata"},
                    "class": {"id": 40674, "name": "Mammalia"},
                    "order": {"id": 9443, "name": "Primates"},
                    "family": {"id": 9604, "name": "Hominidae"},
                    "genus": {"id": 9605, "name": "Homo"},
                    "species": {"id": 9606, "name": "Homo sapiens"},
                },
            },
            511145: {
                "organism_name": "Escherichia coli str. K-12 substr. MG1655",
                "lineage": [1, 131567, 2, 1224, 561],
                "classification": {
                    "domain": {"id": 2, "name": "Bacteria"},
                    "phylum": {"id": 1224, "name": "Pseudomonadota"},
                    "class": {"id": 1236, "name": "Gammaproteobacteria"},
                    "order": {"id": 91347, "name": "Enterobacterales"},
                    "family": {"id": 543, "name": "Enterobacteriaceae"},
                    "genus": {"id": 561, "name": "Escherichia"},
                    "species": {"id": 562, "name": "Escherichia coli"},
                },
            },
        }
        if path.startswith("genome/accession/") and path.endswith("/dataset_report"):
            accession = path.split("/", 2)[2].rsplit("/", 1)[0]
            record = accession_reports.get(accession)
            if record is None:
                return {"reports": [], "total_count": 0}
            return {
                "reports": [
                    {
                        "accession": accession,
                        "organism": {
                            "tax_id": record["tax_id"],
                            "organism_name": record["name"],
                            **(
                                {"infraspecific_names": {"strain": record["strain"]}}
                                if record.get("strain")
                                else {}
                            ),
                        },
                        "assembly_info": {"assembly_status": record["status"]},
                    }
                ],
                "total_count": 1,
            }
        if path.startswith("taxonomy/taxon/") and path.endswith("/dataset_report"):
            tax_id = int(path.split("/")[2])
            payload = taxonomy.get(tax_id)
            return {
                "reports": [
                    {
                        "taxonomy": {
                            "tax_id": tax_id,
                            "current_scientific_name": {
                                "name": payload["organism_name"]
                            },
                            **payload,
                        }
                    }
                ],
                "total_count": 1,
            } if payload else {"reports": [], "total_count": 0}
        raise AssertionError(f"Unexpected NCBI test path: {path}")

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
            files or [("files", "accessions.txt", b"GCA_000011425.1\n")],
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
        root = self.job_store.job_dir(job_id)
        result_dir = root / "results"
        result_dir.mkdir(parents=True, exist_ok=True)
        figure_path = result_dir / "figure.svg"
        figure_path.write_text("<svg></svg>\n", encoding="utf-8")
        figure_bytes = figure_path.read_bytes()
        manifest = root / "downloads" / "public_results_manifest.tsv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            "path\tbytes\tsha256\n"
            f"results/figure.svg\t{len(figure_bytes)}\t{hashlib.sha256(figure_bytes).hexdigest()}\n",
            encoding="utf-8",
        )
        self.job_store.write_job(job)
        importlib.import_module("result_attestation").write_result_attestation(
            root,
            job_id,
            verify_hashes=True,
            path_validator=lambda path: self.app.result_file_is_publicly_servable(
                root, path
            ),
        )
        self.job_store.append_log(job_id, "test log line")
        return job

    def submitted_internal_job_id(self, payload: dict[str, object]) -> str:
        public_id = str(payload.get("public_run_id") or payload.get("job_id") or "")
        job = self.app.resolve_public_job(public_id)
        self.assertIsNotNone(job)
        assert job is not None
        internal_id = str(job.get("id") or "")
        self.assertRegex(internal_id, r"^[0-9a-f]{8}$")
        return internal_id

    def read_submitted_job(self, payload: dict[str, object]) -> dict[str, object]:
        internal_id = self.submitted_internal_job_id(payload)
        job = self.job_store.read_job(internal_id)
        self.assertIsNotNone(job)
        assert job is not None
        return job

    def submitted_public_run_id(self, payload: dict[str, object]) -> str:
        public_id = str(payload.get("public_run_id") or "")
        self.assertIsNotNone(self.app.resolve_public_job(public_id))
        return public_id

    def fixture_public_run_id(self, internal_job_id: str) -> str:
        job = self.job_store.read_job(internal_job_id)
        self.assertIsNotNone(job)
        assert job is not None
        public_id = self.app.public_run_id_for_job(job)
        self.assertIsNotNone(self.app.resolve_public_job(public_id))
        return public_id

    def public_artifact_catalog(
        self, internal_job_id: str, credential: str
    ) -> tuple[str, list[dict[str, object]]]:
        public_id = self.fixture_public_run_id(internal_job_id)
        status, payload, _ = self.request(
            "GET",
            f"/api/results/{public_id}/artifacts",
            headers=self.auth(credential),
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(payload, dict)
        artifacts = payload.get("artifacts")
        self.assertIsInstance(artifacts, list)
        assert isinstance(artifacts, list)
        return public_id, artifacts

    def find_public_artifact(
        self,
        artifacts: list[dict[str, object]],
        *,
        filename: str,
        category: str = "",
        role: str = "",
    ) -> dict[str, object]:
        matches = [
            artifact
            for artifact in artifacts
            if str(artifact.get("filename") or "") == filename
            and (not category or artifact.get("category") == category)
            and (not role or artifact.get("role") == role)
        ]
        self.assertEqual(len(matches), 1, matches)
        return matches[0]

    def write_bigscape_public_export(
        self,
        path: Path,
        *,
        marker: bool = True,
        version: int | None = None,
        policy: str | None = None,
    ) -> None:
        from bigscape_public_db import sanitize_bigscape_database
        from tests.test_bigscape_public_db import create_source_database

        path.parent.mkdir(parents=True, exist_ok=True)
        fixture_bytes = getattr(self, "_public_bigscape_fixture_bytes", None)
        if fixture_bytes is None:
            with tempfile.TemporaryDirectory() as fixture_tmp:
                source = Path(fixture_tmp) / "big_scape.db"
                create_source_database(source)
                fixture_bytes = sanitize_bigscape_database(source).public_path.read_bytes()
            self._public_bigscape_fixture_bytes = fixture_bytes
        path.write_bytes(fixture_bytes)

        if marker and version is None and policy is None:
            return
        connection = sqlite3.connect(path)
        try:
            if not marker:
                connection.execute(
                    f'DROP TABLE "{self.app.PUBLIC_BIGSCAPE_EXPORT_TABLE}"'
                )
            else:
                if version is not None:
                    connection.execute(
                        f'UPDATE "{self.app.PUBLIC_BIGSCAPE_EXPORT_TABLE}" '
                        "SET export_version=?",
                        (version,),
                    )
                if policy is not None:
                    connection.execute(
                        f'UPDATE "{self.app.PUBLIC_BIGSCAPE_EXPORT_TABLE}" '
                        "SET path_policy=?",
                        (policy,),
                    )
            connection.commit()
        finally:
            connection.close()

    def write_bigscape_viewer_export(self, public_path: Path) -> Path:
        import bigscape_public_db

        self.write_bigscape_public_export(public_path)
        tool_root = public_path.parent.parent
        index_path = tool_root / "index.html"
        script_path = tool_root / "html_content" / "js" / "bigscape.js"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.parent.mkdir(parents=True, exist_ok=True)
        index_fragments = "\n".join(
            f"<!-- {fragment} -->"
            for fragment in bigscape_public_db._VIEWER_INDEX_QUERY_FRAGMENTS
        )
        index_calls = "\n".join(
            "<script>window.db.exec('SELECT 1');</script>"
            for _ in range(bigscape_public_db._VIEWER_INDEX_EXEC_CALLS)
        )
        index_path.write_text(
            f"<!doctype html><html><body>{index_fragments}{index_calls}</body></html>\n",
            encoding="utf-8",
        )
        script_path.write_text(
            "window.db.exec(\""
            + bigscape_public_db._VIEWER_SCRIPT_QUERY_FRAGMENT
            + "\");\n",
            encoding="utf-8",
        )
        script_digest = hashlib.sha256(script_path.read_bytes()).hexdigest()
        with mock.patch.object(
            bigscape_public_db,
            "_BIGSCAPE_200_JS_SHA256",
            script_digest,
        ):
            prepared = bigscape_public_db.create_public_bigscape_viewer_database(
                public_path,
                force=True,
            )
        self.assertIsNotNone(prepared)
        self.app._PUBLIC_BIGSCAPE_VIEWER_EXPECTED_JS_SHA256 = script_digest
        assert prepared is not None
        return prepared[0]

    def write_public_manifest_job(
        self,
        job_id: str,
        read_token: str,
        result_paths: list[str],
        *,
        viewer_path: str = "",
    ) -> None:
        created = self.job_store.now_iso()
        root = self.job_store.job_dir(job_id)
        manifest = root / "downloads" / "public_results_manifest.tsv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for path in result_paths:
            target = root / path
            if target.is_file() and not target.is_symlink():
                content = target.read_bytes()
                rows.append(
                    f"{path}\t{len(content)}\t{hashlib.sha256(content).hexdigest()}"
                )
            else:
                rows.append(f"{path}\t0\t{'0' * 64}")
        manifest.write_text(
            "path\tbytes\tsha256\n"
            + "".join(f"{row}\n" for row in rows),
            encoding="utf-8",
        )
        job: dict[str, object] = {
                "id": job_id,
                "name": f"{job_id}-project",
                "status": "success",
                "stage": "complete",
                "created_at": created,
                "updated_at": created,
                "log_count": 0,
                "result_files": [
                    "downloads/public_results_manifest.tsv",
                    *result_paths,
                ],
                "error": None,
                "cpus": 1,
                "project_name": "demo",
                "read_token_hash": self.app.job_token_hash(read_token),
                "read_token_created_at": created,
            }
        if viewer_path:
            job["bigscape_viewer_database"] = viewer_path
        self.job_store.write_job(job)
        attestation_module = importlib.import_module("result_attestation")
        try:
            attestation_module.write_result_attestation(
                root,
                job_id,
                verify_hashes=True,
                path_validator=lambda path: self.app.result_file_is_publicly_servable(
                    root, path
                ),
                viewer_path=viewer_path,
            )
        except (OSError, ValueError, UnicodeError):
            # Invalid-family fixtures intentionally remain unattested.
            pass


    def test_anonymous_public_mode_gets_only_redacted_status_and_no_job_access(self) -> None:
        self.write_job("jobone", "read-one")
        self.write_job("queuedone", "read-queued", status="pending")
        self.write_job("runningone", "read-running", status="running")

        status, payload, headers = self.request("GET", "/api/system/status", headers={"Origin": "https://example.invalid"})
        self.assertEqual(status, 200)
        self.assertEqual(
            set(payload),
            {"online", "service", "submissions_open", "submissions", "jobs_processed", "running_jobs", "queued_jobs", "smtp_enabled", "public_quota"},
        )
        self.assertEqual(payload["public_quota"]["max_accessions"], 50)
        self.assertEqual(payload["public_quota"]["max_genome_files"], 50)
        self.assertEqual(payload["jobs_processed"], 1)
        self.assertEqual(payload["running_jobs"], 1)
        self.assertEqual(payload["queued_jobs"], 1)
        self.assertFalse(payload["smtp_enabled"])
        self.assertNotEqual(headers.get("Access-Control-Allow-Origin"), "*")

        public_id = self.fixture_public_run_id("jobone")
        protected_requests = [
            ("GET", "/api/jobs", None, {}, 401),
            ("GET", "/api/jobs/jobone", None, {}, 404),
            ("GET", "/api/jobs/jobone/logs", None, {}, 404),
            ("GET", "/api/jobs/jobone/files", None, {}, 404),
            ("GET", "/api/jobs/jobone/files/results/figure.svg", None, {}, 404),
            ("GET", f"/api/results/{public_id}", None, {}, 404),
            ("GET", f"/api/results/{public_id}/artifacts", None, {}, 404),
            ("POST", "/api/jobs/jobone/rerun", b"{}", {"Content-Type": "application/json"}, 401),
            ("DELETE", "/api/jobs/jobone", None, {}, 401),
        ]
        for method, path, body, headers, expected_status in protected_requests:
            with self.subTest(path=path):
                status, _, _ = self.request(method, path, body=body, headers=headers)
                self.assertEqual(status, expected_status)

    def test_submit_token_creates_job_and_returns_unstored_read_token(self) -> None:
        status, payload, _ = self.submit(
            {"project_name": "auth-case", "cpus": "2"},
            [("files", "accessions.txt", b"GCA_000011425.1\n")],
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["status"], "pending")
        self.assertIn("expires_at", payload)
        read_token = payload["read_token"]
        self.assertIsInstance(read_token, str)
        self.assertNotEqual(read_token, "")
        self.assertEqual(payload["result_url"], f"http://127.0.0.1:{self.base_port}/#/results/{payload['job_id']}/{read_token}")
        accession_metadata = payload["input_summary"]["accession_metadata"]
        self.assertEqual(accession_metadata[0]["accession"], "GCA_000011425.1")
        self.assertEqual(accession_metadata[0]["organism_name"], "Aspergillus nidulans FGSC A4")
        self.assertEqual(accession_metadata[0]["tax_id"], 227321)
        self.assertEqual(accession_metadata[0]["taxa"], "NCBI taxon 227321 / fungi")
        self.assertEqual(accession_metadata[0]["order_name"], "Eurotiales")
        self.assertEqual(accession_metadata[0]["family_name"], "Aspergillaceae")
        self.assertEqual(accession_metadata[0]["class_name"], "Eurotiomycetes")
        self.assertEqual(accession_metadata[0]["order_family"], "Eurotiales:Aspergillaceae")
        self.assertEqual(
            accession_metadata[0]["genome_id"],
            "Aspergillus_nidulans_FGSC_A4",
        )
        self.assertEqual(accession_metadata[0]["domain"], "Eukaryota")
        self.assertEqual(accession_metadata[0]["kingdom"], "Fungi")
        self.assertEqual(
            accession_metadata[0]["lineage_names"],
            "Eukaryota|Fungi|Ascomycota|Eurotiomycetes|Eurotiales|Aspergillaceae|Aspergillus|Aspergillus nidulans",
        )
        self.assertEqual(
            accession_metadata[0]["lineage_ids"],
            "2759|4751|4890|147545|5042|1131492|5052|162425",
        )

        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertNotIn("read_token", job)
        self.assertIn("read_token_hash", job)
        self.assertNotEqual(job["read_token_hash"], read_token)
        self.assertEqual(job["input_summary"]["accession_metadata"], accession_metadata)

        status, access, _ = self.request("GET", "/api/access/validate", headers=self.auth("submit-secret"))
        self.assertEqual(status, 200)
        self.assertFalse(access["admin"])
        self.assertTrue(access["submit"])

        status, _, _ = self.request("GET", "/api/system/status", headers=self.auth("submit-secret"))
        self.assertEqual(status, 403)

        status, _, _ = self.request("GET", "/api/access/validate", headers=self.auth("wrong-secret"))
        self.assertEqual(status, 403)

        status, _, _ = self.request("GET", "/api/jobs", headers=self.auth("submit-secret"))
        self.assertEqual(status, 403)

        logs = self.job_store.read_logs(self.submitted_internal_job_id(payload))
        self.assertTrue(any("Queued: waiting for worker slot." in line for line in logs))

        status, job_payload, _ = self.request("GET", f"/api/results/{payload['job_id']}", headers=self.auth(read_token))
        self.assertEqual(status, 200)
        self.assertNotIn("read_token_hash", job_payload)
        self.assertNotIn("read_token_created_at", job_payload)
        queue_status = job_payload.get("queue_status")
        self.assertIsInstance(queue_status, dict)
        assert isinstance(queue_status, dict)
        self.assertEqual(queue_status.get("state"), "queued")
        self.assertEqual(queue_status.get("position"), 1)
        self.assertEqual(queue_status.get("jobs_ahead"), 0)
        self.assertIn("worker slot", str(queue_status.get("detail", "")))
        self.assertNotIn("active_jobs", queue_status)

        queue_payload = json.loads(
            (Path(self.tmp.name) / "queue" / f"{self.submitted_internal_job_id(payload)}.json").read_text(encoding="utf-8")
        )
        self.assertIn("enqueued_at", queue_payload)

    def test_optional_inference_is_admin_only_and_bounded_at_submission(self) -> None:
        requested = {
            "analysis_scope": "fungi",
            "run_phylogeny": "1",
            "phylogeny_required": "1",
            "run_cross_kingdom_evidence": "1",
            "phylogeny_cpus": "999",
            "phylogeny_parallelism": "999",
            "phylogeny_max_families": "999",
            "phylogeny_timeout_seconds": "999999",
        }
        files = [("files", "fungus.fna", b">contig\nACGTACGT\n")]
        status, public_payload, _ = self.submit(requested, files)
        self.assertEqual(status, 201, public_payload)
        public_job = self.read_submitted_job(public_payload)
        self.assertIsNotNone(public_job)
        public_settings = public_job["settings"]  # type: ignore[index]
        self.assertFalse(public_settings["run_phylogeny"])
        self.assertFalse(public_settings["phylogeny_required"])
        self.assertFalse(public_settings["run_cross_kingdom_evidence"])

        requested["phylogeny_required"] = "0"
        status, admin_payload, _ = self.submit(
            requested,
            files,
            token="admin-secret",
        )
        self.assertEqual(status, 201, admin_payload)
        admin_job = self.read_submitted_job(admin_payload)
        self.assertIsNotNone(admin_job)
        admin_settings = admin_job["settings"]  # type: ignore[index]
        self.assertTrue(admin_settings["run_phylogeny"])
        self.assertFalse(admin_settings["phylogeny_required"])
        self.assertTrue(admin_settings["run_cross_kingdom_evidence"])
        self.assertEqual(admin_settings["phylogeny_cpus"], 2)
        self.assertEqual(admin_settings["phylogeny_parallelism"], 1)
        self.assertEqual(admin_settings["phylogeny_max_families"], 100)
        self.assertEqual(admin_settings["phylogeny_timeout_seconds"], 86_400)

    def test_scope_defaults_to_fungi_and_read_projection_hides_private_routes(self) -> None:
        status, submitted, _ = self.submit(
            {"project_name": "scope-default", "analysis_scope": ""},
            [("files", "accessions.txt", b"GCA_000011425.1\n")],
        )
        self.assertEqual(status, 201)
        job = self.read_submitted_job(submitted)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["analysis_scope"], "fungi")
        self.assertEqual(job["settings"]["analysis_scope"], "fungi")
        self.assertEqual(job["submission_settings"]["analysis_scope"], "fungi")
        self.assertEqual(job["taxon_counts"], {"fungi": 1, "bacteria": 0, "total": 1})
        self.assertEqual(len(job["taxon_routes"]), 1)
        self.assertEqual(job["taxon_routes"][0]["taxon_source"], "ncbi")
        self.assertEqual(
            job["taxon_routes"][0]["genome_id"],
            "Aspergillus_nidulans_FGSC_A4",
        )
        self.assertNotEqual(
            job["taxon_routes"][0]["genome_id"],
            job["taxon_routes"][0]["source_accession"],
        )
        self.assertEqual(job["settings"]["taxon_routes"], job["taxon_routes"])
        taxonomy_metadata = job["settings"]["taxonomy_metadata"]
        self.assertEqual(job["submission_settings"]["taxonomy_metadata"], taxonomy_metadata)
        self.assertEqual(len(taxonomy_metadata), 1)
        self.assertEqual(taxonomy_metadata[0]["input_key"], "GCA_000011425.1")
        self.assertEqual(taxonomy_metadata[0]["source_accession"], "GCA_000011425.1")
        self.assertEqual(taxonomy_metadata[0]["domain"], "Eukaryota")
        self.assertEqual(taxonomy_metadata[0]["kingdom"], "Fungi")
        self.assertEqual(taxonomy_metadata[0]["class"], "Eurotiomycetes")
        self.assertEqual(taxonomy_metadata[0]["order"], "Eurotiales")
        self.assertEqual(taxonomy_metadata[0]["family"], "Aspergillaceae")
        self.assertEqual(
            taxonomy_metadata[0]["lineage_names"],
            "Eukaryota|Fungi|Ascomycota|Eurotiomycetes|Eurotiales|Aspergillaceae|Aspergillus|Aspergillus nidulans",
        )
        self.assertEqual(
            taxonomy_metadata[0]["lineage_ids"],
            "2759|4751|4890|147545|5042|1131492|5052|162425",
        )

        status, read_payload, _ = self.request(
            "GET",
            f"/api/results/{self.submitted_public_run_id(submitted)}",
            headers=self.auth(submitted["read_token"]),
        )
        self.assertEqual(status, 200)
        self.assertEqual(read_payload["analysis_scope"], "fungi")
        self.assertEqual(read_payload["taxon_counts"]["fungi"], 1)
        self.assertEqual(read_payload["applicability_counts"]["funbgcex"], 1)
        self.assertNotIn("taxon_routes", read_payload)
        self.assertNotIn("taxonomy_metadata", read_payload)
        self.assertNotIn("accession_metadata", read_payload["input_summary"])
        self.assertNotIn("genome_readiness", read_payload["input_summary"])
        self.assertNotIn("Eurotiales", json.dumps(read_payload))

        status, admin_payload, _ = self.request(
            "GET",
            f"/api/jobs/{self.submitted_internal_job_id(submitted)}",
            headers=self.auth("admin-secret"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(admin_payload["taxon_routes"], job["taxon_routes"])
        self.assertEqual(admin_payload["settings"]["taxonomy_metadata"], taxonomy_metadata)

        self.write_job("historicalscope", "read-historical")
        historical_public_id = self.fixture_public_run_id("historicalscope")
        status, historical, _ = self.request(
            "GET",
            f"/api/results/{historical_public_id}",
            headers=self.auth("read-historical"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(historical["analysis_scope"], "fungi")

    def test_ncbi_scope_matrix_mixed_auto_route_and_authority_bypasses_closed(self) -> None:
        status, bacteria, _ = self.submit(
            {"project_name": "bacteria-ncbi", "analysis_scope": "bacteria"},
            [("files", "accessions.txt", b"GCF_000005845.2\n")],
        )
        self.assertEqual(status, 201)
        bacteria_job = self.read_submitted_job(bacteria)
        self.assertEqual(bacteria_job["taxon_counts"]["bacteria"], 1)  # type: ignore[index]
        bacterial_route = bacteria_job["taxon_routes"][0]  # type: ignore[index]
        self.assertEqual(bacterial_route["prediction_method"], "prodigal")
        self.assertEqual(bacterial_route["genome_id"], "Escherichia_coli")
        self.assertFalse(bacterial_route["genome_id"].startswith("bacteria_"))

        status, mismatch, _ = self.submit(
            {"project_name": "fungal-mismatch", "analysis_scope": "fungi"},
            [("files", "accessions.txt", b"GCF_000005845.2\n")],
        )
        self.assertEqual(status, 400)
        self.assertIn("not a fungal assembly", mismatch["detail"])

        status, reverse_mismatch, _ = self.submit(
            {"project_name": "bacterial-mismatch", "analysis_scope": "bacteria"},
            [("files", "accessions.txt", b"GCA_000011425.1\n")],
        )
        self.assertEqual(status, 400)
        self.assertIn("not a bacterial assembly", reverse_mismatch["detail"])

        status, mixed, _ = self.submit(
            {"project_name": "mixed-ncbi", "analysis_scope": "both"},
            [
                (
                    "files",
                    "accessions.txt",
                    b"GCA_000011425.1\nGCF_000005845.2\n",
                )
            ],
        )
        self.assertEqual(status, 201)
        mixed_job = self.read_submitted_job(mixed)
        self.assertEqual(
            mixed_job["taxon_counts"],  # type: ignore[index]
            {"fungi": 1, "bacteria": 1, "total": 2},
        )
        self.assertEqual(
            {row["taxon_group"] for row in mixed_job["taxon_routes"]},  # type: ignore[index]
            {"fungi", "bacteria"},
        )

        status, unsupported, _ = self.submit(
            {"project_name": "unsupported-both", "analysis_scope": "both"},
            [("files", "accessions.txt", b"GCF_000001405.40\n")],
        )
        self.assertEqual(status, 400)
        self.assertIn("unsupported taxonomy", unsupported["detail"])

        status, admin_mismatch, _ = self.submit(
            {"project_name": "admin-mismatch", "analysis_scope": "fungi"},
            [("files", "accessions.txt", b"GCF_000005845.2\n")],
            token="admin-secret",
        )
        self.assertEqual(status, 400)
        self.assertIn("not a fungal assembly", admin_mismatch["detail"])

        self.app.NCBI_ACCESSION_PREFLIGHT = False
        status, disabled_mismatch, _ = self.submit(
            {"project_name": "disabled-mismatch", "analysis_scope": "fungi"},
            [("files", "accessions.txt", b"GCF_000005845.2\n")],
        )
        self.assertEqual(status, 400)
        self.assertIn("not a fungal assembly", disabled_mismatch["detail"])

        self.app.PUBLIC_MODE = False
        status, local_mismatch, _ = self.submit(
            {"project_name": "local-mismatch", "analysis_scope": "fungi"},
            [("files", "accessions.txt", b"GCF_000005845.2\n")],
            token=None,
        )
        self.assertEqual(status, 400)
        self.assertIn("not a fungal assembly", local_mismatch["detail"])

    def test_both_upload_assignments_pair_same_stem_and_validate_keys(self) -> None:
        fasta = b">contig1\nATGCATGCATGCATGCATGCATGC\n"
        annotated_genbank = b"""LOCUS       PairedGenome            24 bp    DNA     linear   PLN 01-JAN-2026
FEATURES             Location/Qualifiers
     CDS             1..24
                     /translation="MKT"
ORIGIN
        1 atgcatgcat gcatgcatgc atgc
//
"""
        files = [
            ("files", "paired.fna", fasta),
            ("files", "paired.gbk", annotated_genbank),
        ]
        status, missing, _ = self.submit(
            {"project_name": "both-missing", "analysis_scope": "both"}, files
        )
        self.assertEqual(status, 400)
        self.assertIn("Both scope requires", missing["detail"])

        status, accepted, _ = self.submit(
            {
                "project_name": "both-paired",
                "analysis_scope": "both",
                "taxon_assignments": json.dumps(
                    [{"input_key": "paired", "taxon_group": "fungi"}]
                ),
            },
            files,
        )
        self.assertEqual(status, 201)
        job = self.read_submitted_job(accepted)
        self.assertEqual(len(job["taxon_routes"]), 1)  # type: ignore[index]
        self.assertEqual(job["taxon_routes"][0]["input_key"], "paired")  # type: ignore[index]
        self.assertEqual(job["taxon_routes"][0]["prediction_method"], "existing_cds")  # type: ignore[index]

        status, unknown, _ = self.submit(
            {
                "project_name": "both-unknown",
                "analysis_scope": "both",
                "taxon_assignments": '{"not_present":"fungi"}',
            },
            [("files", "paired.fna", fasta)],
        )
        self.assertEqual(status, 400)
        self.assertIn("unknown input_key", unknown["detail"])

        status, spoof, _ = self.submit(
            {
                "project_name": "ncbi-spoof",
                "analysis_scope": "both",
                "taxon_assignments": '{"GCF_000005845.2":"fungi"}',
            },
            [("files", "accessions.txt", b"GCF_000005845.2\n")],
        )
        self.assertEqual(status, 400)
        self.assertIn("cannot override authoritative NCBI", spoof["detail"])

    def test_exact_assignment_sidecar_and_authoritative_genbank_routing(self) -> None:
        fasta = b">contig1\nATGCATGCATGCATGCATGCATGC\n"
        sidecar = b"input_key\ttaxon_group\nmanual_bacterium\tbacteria\n"
        status, sidecar_job, _ = self.submit(
            {"project_name": "sidecar", "analysis_scope": "both"},
            [
                ("files", "manual_bacterium.fna", fasta),
                ("files", "taxon_assignments.tsv", sidecar),
            ],
        )
        self.assertEqual(status, 201)
        stored = self.read_submitted_job(sidecar_job)
        self.assertEqual(stored["taxon_routes"][0]["taxon_group"], "bacteria")  # type: ignore[index]
        self.assertEqual(stored["input_summary"]["taxon_assignment_file_count"], 1)  # type: ignore[index]
        self.assertEqual(stored["settings"]["taxonomy_metadata"], [])  # type: ignore[index]

        bacterial_genbank = b"""LOCUS       BacterialGenome         24 bp    DNA     linear   BCT 01-JAN-2026
  ORGANISM  Escherichia demo
            Bacteria; Pseudomonadota; Gammaproteobacteria.
FEATURES             Location/Qualifiers
     source          1..24
                     /organism="Escherichia demo"
                     /db_xref="taxon:511145"
ORIGIN
        1 atgcatgcat gcatgcatgc atgc
//
"""
        status, authoritative, _ = self.submit(
            {"project_name": "genbank-authority", "analysis_scope": "both"},
            [("files", "bacterium.gbk", bacterial_genbank)],
        )
        self.assertEqual(status, 201)
        authority_job = self.read_submitted_job(authoritative)
        route = authority_job["taxon_routes"][0]  # type: ignore[index]
        self.assertEqual(route["taxon_group"], "bacteria")
        self.assertEqual(route["taxon_source"], "genbank_source")
        self.assertEqual(route["prediction_method"], "prodigal")
        metadata = authority_job["settings"]["taxonomy_metadata"]  # type: ignore[index]
        self.assertEqual(len(metadata), 1)
        self.assertEqual(metadata[0]["input_key"], "bacterium")
        self.assertEqual(metadata[0]["domain"], "Bacteria")
        self.assertEqual(
            metadata[0]["lineage_names"],
            "Bacteria|Pseudomonadota|Gammaproteobacteria",
        )

        status, conflict, _ = self.submit(
            {
                "project_name": "genbank-conflict",
                "analysis_scope": "both",
                "taxon_assignments": '{"bacterium":"fungi"}',
            },
            [("files", "bacterium.gbk", bacterial_genbank)],
        )
        self.assertEqual(status, 400)
        self.assertIn("conflicts with authoritative GenBank", conflict["detail"])

    def test_rerun_preserves_frozen_routes_and_rejects_mutation(self) -> None:
        status, submitted, _ = self.submit(
            {"project_name": "immutable-route", "analysis_scope": "fungi"},
            [
                (
                    "files",
                    "accessions.txt",
                    b"GCA_000011425.1\nGCF_000011425.1\n",
                )
            ],
        )
        self.assertEqual(status, 201)
        job = self.read_submitted_job(submitted)
        self.assertIsNotNone(job)
        assert job is not None
        job["status"] = "success"
        job["stage"] = "complete"
        self.job_store.write_job(job)
        frozen = json.dumps(job["taxon_routes"], sort_keys=True)
        frozen_taxonomy = json.dumps(job["settings"]["taxonomy_metadata"], sort_keys=True)
        self.assertEqual(
            [route["genome_id"] for route in job["taxon_routes"]],
            [
                "Aspergillus_nidulans_FGSC_A4",
                "Aspergillus_nidulans_FGSC_A4_GCF_000011425.1",
            ],
        )
        headers = {"Content-Type": "application/json", **self.auth("admin-secret")}
        internal_job_id = self.submitted_internal_job_id(submitted)

        for mutation in [
            {"analysis_scope": "bacteria"},
            {"taxon_assignments": {"GCA_000011425.1": "bacteria"}},
            {"taxon_routes": []},
            {"taxonomy_metadata": []},
        ]:
            with self.subTest(mutation=mutation):
                body = json.dumps({"run_summary": True, **mutation}).encode("utf-8")
                status, payload, _ = self.request(
                    "POST",
                    f"/api/jobs/{internal_job_id}/rerun",
                    body=body,
                    headers=headers,
                )
                self.assertEqual(status, 400)
                self.assertIn("immutable", payload["detail"])
                unchanged = self.read_submitted_job(submitted)
                self.assertEqual(
                    json.dumps(unchanged["taxon_routes"], sort_keys=True), frozen  # type: ignore[index]
                )
                self.assertEqual(
                    json.dumps(unchanged["settings"]["taxonomy_metadata"], sort_keys=True),  # type: ignore[index]
                    frozen_taxonomy,
                )

        body = json.dumps(
            {
                "run_summary": True,
                "run_phylogeny": True,
                "run_cross_kingdom_evidence": True,
                "phylogeny_cpus": 999,
                "phylogeny_max_families": 999,
                "cpus": 1,
            }
        ).encode("utf-8")
        status, _, _ = self.request(
            "POST",
            f"/api/jobs/{internal_job_id}/rerun",
            body=body,
            headers=headers,
        )
        self.assertEqual(status, 202)
        rerun_job = self.read_submitted_job(submitted)
        self.assertEqual(
            json.dumps(rerun_job["taxon_routes"], sort_keys=True), frozen  # type: ignore[index]
        )
        self.assertEqual(rerun_job["last_rerun_settings"]["analysis_scope"], "fungi")  # type: ignore[index]
        self.assertEqual(rerun_job["last_rerun_settings"]["taxon_routes"], job["taxon_routes"])  # type: ignore[index]
        self.assertEqual(
            json.dumps(rerun_job["last_rerun_settings"]["taxonomy_metadata"], sort_keys=True),  # type: ignore[index]
            frozen_taxonomy,
        )
        self.assertTrue(rerun_job["last_rerun_settings"]["run_phylogeny"])  # type: ignore[index]
        self.assertTrue(rerun_job["last_rerun_settings"]["run_cross_kingdom_evidence"])  # type: ignore[index]
        self.assertEqual(rerun_job["last_rerun_settings"]["phylogeny_parallelism"], 1)  # type: ignore[index]
        self.assertEqual(rerun_job["last_rerun_settings"]["phylogeny_max_families"], 100)  # type: ignore[index]
        queue_payload = json.loads(
            (
                Path(self.tmp.name)
                / "queue"
                / f"{internal_job_id}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(queue_payload["settings"]["taxon_routes"], job["taxon_routes"])
        self.assertEqual(
            json.dumps(queue_payload["settings"]["taxonomy_metadata"], sort_keys=True),
            frozen_taxonomy,
        )

    def test_queue_positions_use_enqueued_time_not_random_job_id(self) -> None:
        queue_dir = Path(self.tmp.name) / "queue"
        records = {
            "a-late.json": {"job_id": "late", "enqueued_at": "2026-03-01T00:00:00"},
            "z-early.json": {"job_id": "early", "enqueued_at": "2026-01-01T00:00:00"},
            "m-middle.json": {"job_id": "middle", "created_at": "2026-02-01T00:00:00"},
            "b-fallback.json": {"job_id": "fallback-b"},
            "a-fallback.json": {"job_id": "fallback-a"},
        }
        for filename, record in records.items():
            (queue_dir / filename).write_text(json.dumps(record), encoding="utf-8")
        fallback_timestamp = datetime.fromisoformat("2027-01-01T00:00:00").timestamp()
        os.utime(queue_dir / "a-fallback.json", (fallback_timestamp, fallback_timestamp))
        os.utime(queue_dir / "b-fallback.json", (fallback_timestamp, fallback_timestamp))

        self.assertEqual(
            self.app.queued_job_ids(),
            ["early", "middle", "late", "fallback-a", "fallback-b"],
        )

    def test_worker_recovers_orphaned_running_jobs(self) -> None:
        created = "2026-01-01T00:00:00"
        job = {
            "id": "stalejob",
            "name": "stale-project",
            "status": "running",
            "stage": "Running annotation / BGC detection",
            "created_at": created,
            "updated_at": created,
            "log_count": 0,
            "result_files": [],
            "error": "interrupted",
            "cpus": 3,
            "settings": {"run_genome_prep": True, "run_annotation": True},
            "submission_settings": {"run_genome_prep": True, "run_annotation": True},
        }
        self.job_store.write_job(job)
        self.job_store.append_log("stalejob", "Running antiSMASH on demo")
        stale_working = Path(self.tmp.name) / "queue" / "stalejob.working"
        stale_working.write_text("{}", encoding="utf-8")

        sys.modules.pop("worker", None)
        try:
            worker = importlib.import_module("worker")
            recovered = worker.recover_orphaned_running_jobs()
        finally:
            sys.modules.pop("worker", None)

        self.assertEqual(recovered, ["stalejob"])
        recovered_job = self.job_store.read_job("stalejob")
        self.assertIsNotNone(recovered_job)
        assert recovered_job is not None
        self.assertEqual(recovered_job["status"], "pending")
        self.assertEqual(recovered_job["stage"], "queued")
        self.assertIsNone(recovered_job["error"])
        self.assertTrue(recovered_job["settings"]["reuse_existing_layout"])
        self.assertFalse(recovered_job["settings"]["run_genome_prep"])
        self.assertGreaterEqual(recovered_job["log_count"], 3)
        logs = self.job_store.read_logs("stalejob")
        self.assertTrue(any("Recovered interrupted running job" in line for line in logs))
        self.assertTrue(any("skipped accession genome prep" in line for line in logs))

        queue_path = Path(self.tmp.name) / "queue" / "stalejob.json"
        self.assertTrue(queue_path.exists())
        self.assertFalse(stale_working.exists())
        queue_payload = json.loads(queue_path.read_text(encoding="utf-8"))
        self.assertEqual(queue_payload["job_id"], "stalejob")
        self.assertEqual(queue_payload["cpus"], 3)
        self.assertTrue(queue_payload["settings"]["reuse_existing_layout"])
        self.assertFalse(queue_payload["settings"]["run_genome_prep"])

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

    def test_local_submission_does_not_require_data_use_acknowledgment(self) -> None:
        self.app.PUBLIC_MODE = False
        status, payload, _ = self.submit(fields={"data_use_ack": "0"})
        self.assertEqual(status, 201)
        self.assertEqual(payload["status"], "pending")

    def test_ncbi_panel_accessions_do_not_require_data_use_acknowledgment(self) -> None:
        status, payload, _ = self.submit(
            fields={"data_use_ack": "0"},
            files=[
                ("files", self.app.MANUAL_ACCESSIONS_FILENAME, b"GCA_000011425.1\n")
            ],
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["status"], "pending")

    def test_ncbi_panel_generated_ecology_metadata_does_not_require_acknowledgment(self) -> None:
        metadata = (
            b"accession\tgenome_id_current\ttaxonomy_id\tgenome_size_mb\t"
            b"genome_id_original_if_different\tecofun_primary\tecofun_secondary\n"
            b"GCA_000011425.1\tGCA_000011425.1\t\t\t\tsoil\t\n"
        )
        status, payload, _ = self.submit(
            fields={"data_use_ack": "0", "run_ecology_analysis": "1"},
            files=[
                ("files", self.app.MANUAL_ACCESSIONS_FILENAME, b"GCA_000011425.1\n"),
                ("files", self.app.PUBLIC_ECOLOGY_METADATA_FILENAME, metadata),
            ],
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["status"], "pending")
        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["input_summary"]["metadata_file_count"], 1)
        self.assertNotIn(
            "_generated_ecology_metadata_is_ncbi_only", job["input_summary"]
        )

    def test_reserved_ecology_filename_does_not_bypass_validation_or_acknowledgment(self) -> None:
        status, payload, _ = self.submit(
            fields={"data_use_ack": "0", "run_ecology_analysis": "1"},
            files=[
                ("files", self.app.MANUAL_ACCESSIONS_FILENAME, b"GCA_000011425.1\n"),
                (
                    "files",
                    self.app.PUBLIC_ECOLOGY_METADATA_FILENAME,
                    b"arbitrary bytes",
                ),
            ],
        )

        self.assertEqual(status, 400)
        self.assertIn("Generated ecology metadata", payload["detail"])
        self.assertIn("invalid header", payload["detail"])
        self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_public_submission_requires_project_name(self) -> None:
        status, payload, _ = self.submit(fields={"project_name": ""})
        self.assertEqual(status, 400)
        self.assertIn("Project name is required", payload["detail"])

    def test_notification_email_is_stored_only_when_smtp_enabled(self) -> None:
        fields = {"project_name": "email-case", "notify_email": "user@example.org"}
        status, payload, _ = self.submit(fields=fields)
        self.assertEqual(status, 400)
        self.assertIn("Email notifications", payload["detail"])

        self.app.SMTP_ENABLED = True
        status, payload, _ = self.submit(fields=fields)
        self.assertEqual(status, 201)
        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["notify_email"], "user@example.org")
        logs = "\n".join(self.job_store.read_logs(self.submitted_internal_job_id(payload)))
        self.assertNotIn("user@example.org", logs)

        status, job_payload, _ = self.request("GET", f"/api/results/{payload['job_id']}", headers=self.auth(payload["read_token"]))
        self.assertEqual(status, 200)
        self.assertNotIn("notify_email", job_payload)

    def test_read_token_unlocks_only_its_job_logs_and_files(self) -> None:
        self.write_job("jobone", "read-one")
        self.write_job("jobtwo", "read-two")
        public_one = self.fixture_public_run_id("jobone")
        public_two = self.fixture_public_run_id("jobtwo")

        status, payload, _ = self.request(
            "GET", f"/api/results/{public_one}", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], public_one)
        self.assertEqual(payload["public_run_id"], public_one)
        self.assertNotIn("settings", payload)
        self.assertNotIn("submission_settings", payload)

        status, _, _ = self.request(
            "GET", f"/api/results/{public_two}", headers=self.auth("read-one")
        )
        self.assertEqual(status, 404)

        status, payload, _ = self.request(
            "GET",
            f"/api/results/{public_one}/activity",
            headers=self.auth("read-one"),
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(payload["public_events"], list)
        self.assertNotIn("test log line", json.dumps(payload))

        public_id, artifacts = self.public_artifact_catalog("jobone", "read-one")
        self.assertEqual(public_id, public_one)
        figure = self.find_public_artifact(
            artifacts, filename="figure.svg", category="figures"
        )
        figure_id = str(figure["id"])
        status, body, headers = self.request(
            "GET",
            f"/api/results/{public_one}/artifacts/{figure_id}",
            headers=self.auth("read-one"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<svg></svg>\n")
        self.assertTrue(headers.get("Content-Disposition", "").startswith("inline;"))

        status, archive_body, headers = self.request(
            "GET",
            f"/api/results/{public_one}/archive",
            headers=self.auth("read-one"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "application/zip")
        self.assertIn(
            f"{public_one}_clusterweave_results.zip",
            headers.get("Content-Disposition", ""),
        )
        self.assertTrue(archive_body.startswith(b"PK"))
        with zipfile.ZipFile(io.BytesIO(archive_body)) as archive:
            self.assertEqual(archive.read("results/figure.svg"), b"<svg></svg>\n")
            self.assertEqual(
                archive.getinfo("results/figure.svg").compress_type,
                zipfile.ZIP_DEFLATED,
            )

        status, repeated_archive_body, _ = self.request(
            "GET",
            f"/api/results/{public_one}/archive",
            headers=self.auth("read-one"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(repeated_archive_body, archive_body)

        status, _, _ = self.request(
            "GET",
            f"/api/results/{public_two}/archive",
            headers=self.auth("read-one"),
        )
        self.assertEqual(status, 404)

    def test_direct_manifest_route_is_target_bounded_while_listing_uses_allowlist(self) -> None:
        job_id = "directmanifest"
        read_token = "read-direct-manifest"
        rel_path = "data/results/demo/figures/direct.svg"
        root = self.job_store.job_dir(job_id)
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"<svg>safe</svg>\n")
        self.write_public_manifest_job(job_id, read_token, [rel_path])

        public_id, artifacts = self.public_artifact_catalog(job_id, read_token)
        descriptor = self.find_public_artifact(
            artifacts,
            filename="direct.svg",
            category="figures",
        )
        artifact_url = f"/api/results/{public_id}/artifacts/{descriptor['id']}"

        original_digest = self.app._stable_public_sha256
        with mock.patch.object(
            self.app,
            "result_file_allowlist",
            side_effect=AssertionError(
                "opaque catalog and direct routes must not build the legacy allowlist"
            ),
        ), mock.patch.object(
            self.app,
            "_stable_public_sha256",
            wraps=original_digest,
        ) as target_digest:
            status, body, _ = self.request(
                "GET",
                artifact_url,
                headers=self.auth(read_token),
            )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<svg>safe</svg>\n")
        target_digest.assert_called_once()
        self.assertEqual(Path(target_digest.call_args.args[0]), target.resolve())

        with mock.patch.object(
            self.app,
            "result_file_allowlist",
            side_effect=AssertionError(
                "opaque catalog must use its signed completion-time attestation"
            ),
        ):
            status, payload, _ = self.request(
                "GET",
                f"/api/results/{public_id}/artifacts",
                headers=self.auth(read_token),
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["result_index_state"], "attested")
        self.assertEqual(
            {item["filename"] for item in payload["artifacts"]},
            {"public_results_manifest.tsv", "direct.svg"},
        )

        original_authorize = self.app.authorize_direct_result_file

        def authorize_then_replace(*args, **kwargs):
            authorized = original_authorize(*args, **kwargs)
            if authorized is not None:
                full, _identity = authorized
                replacement = b"<svg>RACE</svg>\n"
                self.assertEqual(len(replacement), full.stat().st_size)
                full.write_bytes(replacement)
            return authorized

        with mock.patch.object(
            self.app,
            "authorize_direct_result_file",
            side_effect=authorize_then_replace,
        ):
            status, payload, _ = self.request(
                "GET",
                artifact_url,
                headers=self.auth(read_token),
            )
        self.assertEqual(status, 409)
        self.assertIn("changed before streaming", payload["detail"])

    def test_direct_manifest_route_rejects_same_size_manifest_and_target_mutations(self) -> None:
        job_id = "directmutation"
        read_token = "read-direct-mutation"
        rel_path = "data/results/demo/figures/mutation.svg"
        root = self.job_store.job_dir(job_id)
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        original = b"<svg>A</svg>\n"
        target.write_bytes(original)
        self.write_public_manifest_job(job_id, read_token, [rel_path])

        public_id, artifacts = self.public_artifact_catalog(job_id, read_token)
        descriptor = self.find_public_artifact(
            artifacts,
            filename="mutation.svg",
            category="figures",
        )
        artifact_url = f"/api/results/{public_id}/artifacts/{descriptor['id']}"

        status, body, _ = self.request(
            "GET",
            artifact_url,
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, original)

        manifest = root / "downloads" / "public_results_manifest.tsv"
        manifest_before = manifest.read_bytes()
        digest = hashlib.sha256(original).hexdigest().encode("ascii")
        replacement = (b"0" if digest[:1] != b"0" else b"1") + digest[1:]
        manifest_after = manifest_before.replace(digest, replacement, 1)
        self.assertEqual(len(manifest_after), len(manifest_before))
        manifest.write_bytes(manifest_after)
        status, payload, _ = self.request(
            "GET",
            artifact_url,
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Result not found")

        self.write_public_manifest_job(job_id, read_token, [rel_path])
        status, _, _ = self.request(
            "GET",
            artifact_url,
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 200)
        mutated = b"<svg>B</svg>\n"
        self.assertEqual(len(mutated), len(original))
        target.write_bytes(mutated)
        status, payload, _ = self.request(
            "GET",
            artifact_url,
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Result not found")

    def test_direct_manifest_route_rejects_symlinks_and_noncanonical_traversal(self) -> None:
        job_id = "directpaths"
        read_token = "read-direct-paths"
        rel_path = "data/results/demo/figures/link.svg"
        root = self.job_store.job_dir(job_id)
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"<svg>safe</svg>\n")
        self.write_public_manifest_job(job_id, read_token, [rel_path])

        public_id, artifacts = self.public_artifact_catalog(job_id, read_token)
        descriptor = self.find_public_artifact(
            artifacts,
            filename="link.svg",
            category="figures",
        )
        artifact_url = f"/api/results/{public_id}/artifacts/{descriptor['id']}"

        target.unlink()
        try:
            target.symlink_to(root / "job.json")
        except (NotImplementedError, OSError):
            self.skipTest("symlinks are unavailable on this platform")
        status, payload, _ = self.request(
            "GET",
            artifact_url,
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Result not found")

        noncanonical_routes = [
            f"/api/results/{public_id}/artifacts/%2e%2e",
            f"/api/results/{public_id}/artifacts/not-a-valid-artifact-id",
            f"{artifact_url}/download/extra",
        ]
        for route in noncanonical_routes:
            with self.subTest(route=route):
                status, payload, _ = self.request(
                    "GET",
                    route,
                    headers=self.auth(read_token),
                )
                self.assertEqual(status, 404)
                self.assertEqual(payload["detail"], "Result not found")

    def test_direct_route_preserves_exact_bigscape_database_and_sidecar_policy(self) -> None:
        job_id = "directbigscape"
        read_token = "read-direct-bigscape"
        root = self.job_store.job_dir(job_id)
        exact = "data/results/demo/big_scape/public/clusterweave_public.sqlite"
        raw = "data/results/demo/big_scape/big_scape.db"
        near_name = "data/results/demo/big_scape/public/clusterweave_public.sqlite.bak"
        sidecar = exact + "-wal"
        self.write_bigscape_public_export(root / exact)
        public_bytes = (root / exact).read_bytes()
        for rel_path in [raw, near_name]:
            target = root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(public_bytes)
        self.write_public_manifest_job(job_id, read_token, [exact])

        public_id, artifacts = self.public_artifact_catalog(job_id, read_token)
        descriptor = self.find_public_artifact(
            artifacts,
            filename="clusterweave_public.sqlite",
            category="bigscape",
            role="public-database",
        )
        artifact_url = f"/api/results/{public_id}/artifacts/{descriptor['id']}"
        self.assertFalse(
            {Path(path).name for path in [raw, near_name, sidecar]}
            & {str(item["filename"]) for item in artifacts}
        )

        with mock.patch.object(
            self.app,
            "result_file_allowlist",
            side_effect=AssertionError(
                "opaque direct route must not build the legacy allowlist"
            ),
        ):
            status, body, _ = self.request(
                "GET",
                artifact_url,
                headers=self.auth(read_token),
            )
            self.assertEqual(status, 200)
            self.assertTrue(body.startswith(b"SQLite format 3\x00"))

        for denied in [raw, near_name, sidecar]:
            with self.subTest(path=denied):
                status, payload, _ = self.request(
                    "GET",
                    f"/api/jobs/{job_id}/files/{denied}",
                    headers=self.auth("admin-secret"),
                )
                self.assertEqual(status, 403)
                self.assertIn("not available", payload["detail"])

        exact_path = root / exact
        mutated_database = b"X" + public_bytes[1:]
        self.assertEqual(len(mutated_database), len(public_bytes))
        exact_path.write_bytes(mutated_database)
        status, payload, _ = self.request(
            "GET",
            artifact_url,
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Result not found")
        exact_path.write_bytes(public_bytes)
        status, body, _ = self.request(
            "GET",
            artifact_url,
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"SQLite format 3\x00"))

        sidecar_path = root / sidecar
        sidecar_path.write_bytes(b"active sqlite sidecar")
        status, payload, _ = self.request(
            "GET",
            artifact_url,
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Result not found")

    def test_only_exact_valid_marked_bigscape_database_is_served_to_read_or_admin(self) -> None:
        job_id = "bigscapedbjob"
        read_token = "read-bigscape-db"
        root = self.job_store.job_dir(job_id)
        exact = "data/results/demo/big_scape/public/clusterweave_public.sqlite"
        denied = [
            "data/results/demo/big_scape/big_scape.db",
            "data/results/demo/big_scape/output_files/data_sqlite.db",
            "data/results/demo/big_scape/public/data_sqlite.db",
            "data/results/demo/big_scape/public/clusterweave_public.sqlite-wal",
            "data/results/demo/big_scape/public/clusterweave_public.sqlite-shm",
            "data/results/demo/big_scape/public/clusterweave_public.sqlite-journal",
            "data/results/demo/big_scape/public/clusterweave_public.sqlite.bak",
            "data/results/demo/big_scape/public/CLUSTERWEAVE_PUBLIC.SQLITE",
            "data/results/demo/big_scape/public/nested/clusterweave_public.sqlite",
        ]
        self.write_bigscape_public_export(root / exact)
        for rel_path in denied:
            if not rel_path.endswith(("-wal", "-shm", "-journal")):
                self.write_bigscape_public_export(root / rel_path)
        self.write_public_manifest_job(job_id, read_token, [exact])

        public_id, artifacts = self.public_artifact_catalog(job_id, read_token)
        public_descriptor = self.find_public_artifact(
            artifacts,
            filename="clusterweave_public.sqlite",
            category="bigscape",
            role="public-database",
        )
        self.assertEqual(
            {
                str(item["filename"])
                for item in artifacts
                if item.get("role") != "manifest"
            },
            {"clusterweave_public.sqlite"},
        )
        artifact_url = (
            f"/api/results/{public_id}/artifacts/{public_descriptor['id']}"
        )

        for token in [read_token, "admin-secret"]:
            with self.subTest(token="admin" if token == "admin-secret" else "read", path=exact):
                status, body, headers = self.request(
                    "GET",
                    artifact_url,
                    headers=self.auth(token),
                )
                self.assertEqual(status, 200)
                self.assertTrue(body.startswith(b"SQLite format 3\x00"))
                self.assertEqual(
                    headers.get("Content-Type"),
                    "application/vnd.sqlite3",
                )
            for rel_path in denied:
                with self.subTest(
                    token="admin-legacy" if token == "admin-secret" else "read-legacy",
                    denied=rel_path,
                ):
                    status, payload, _ = self.request(
                        "GET",
                        f"/api/jobs/{job_id}/files/{rel_path}",
                        headers=self.auth(token),
                    )
                    self.assertEqual(status, 403 if token == "admin-secret" else 404)

        status, archive_body, _ = self.request(
            "GET",
            f"/api/results/{public_id}/archive",
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(archive_body)) as archive:
            names = set(archive.namelist())
        self.assertIn(
            "big_scape/public/clusterweave_public.sqlite",
            names,
        )
        for rel_path in denied:
            self.assertNotIn(
                "/".join(rel_path.split("/")[3:]),
                names,
            )

    def test_invalid_exact_bigscape_database_fails_closed_for_all_credentials(self) -> None:
        cases = ["bad-magic", "missing-marker", "wrong-version", "wrong-policy"]
        exact = "data/results/demo/big_scape/public/clusterweave_public.sqlite"
        for index, case in enumerate(cases):
            job_id = f"invalidbigscape{index}"
            read_token = f"read-invalid-{index}"
            root = self.job_store.job_dir(job_id)
            target = root / exact
            if case == "bad-magic":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"not a sqlite database")
            elif case == "missing-marker":
                self.write_bigscape_public_export(target, marker=False)
            elif case == "wrong-version":
                self.write_bigscape_public_export(
                    target,
                    version=self.app.PUBLIC_BIGSCAPE_EXPORT_VERSION + 1,
                )
            else:
                self.write_bigscape_public_export(
                    target,
                    policy="wrong-publication-policy",
                )
            self.write_public_manifest_job(job_id, read_token, [exact])

            public_id = self.fixture_public_run_id(job_id)
            for token in [read_token, "admin-secret"]:
                with self.subTest(case=case, token=token):
                    status, payload, _ = self.request(
                        "GET",
                        f"/api/results/{public_id}/artifacts",
                        headers=self.auth(token),
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(payload["result_index_state"], "indexing")
                    self.assertEqual(payload["artifacts"], [], case)

                    status, payload, _ = self.request(
                        "GET",
                        f"/api/results/{public_id}/artifacts/AAAAAAAAAAAAAAAAAAAAAA",
                        headers=self.auth(token),
                    )
                    self.assertEqual(status, 404)
                    self.assertEqual(payload["detail"], "Result not found")

            status, payload, _ = self.request(
                "GET",
                f"/api/jobs/{job_id}/files/{exact}",
                headers=self.auth("admin-secret"),
            )
            self.assertEqual(status, 403)
            self.assertIn("not available", payload["detail"])

    def test_compact_bigscape_viewer_is_dedicated_attested_and_never_listed(self) -> None:
        job_id = "bigscapeviewer"
        read_token = "read-bigscape-viewer"
        root = self.job_store.job_dir(job_id)
        public = "data/results/demo/big_scape/public/clusterweave_public.sqlite"
        viewer = "data/results/demo/big_scape/public/clusterweave_viewer.sqlite"
        index = "data/results/demo/big_scape/index.html"
        script = "data/results/demo/big_scape/html_content/js/bigscape.js"
        viewer_path = self.write_bigscape_viewer_export(root / public)
        self.assertEqual(viewer_path, root / viewer)
        viewer_bytes = viewer_path.read_bytes()
        self.write_public_manifest_job(
            job_id,
            read_token,
            [public, index, script],
            viewer_path=viewer,
        )

        public_id, artifacts = self.public_artifact_catalog(job_id, read_token)
        public_descriptor = self.find_public_artifact(
            artifacts,
            filename="clusterweave_public.sqlite",
            category="bigscape",
            role="public-database",
        )
        self.assertNotIn(viewer_path.name, {item["filename"] for item in artifacts})

        for token in [read_token, "admin-secret"]:
            label = "admin" if token == "admin-secret" else "read"
            with self.subTest(token=label, surface="job"):
                status, payload, _ = self.request(
                    "GET", f"/api/results/{public_id}", headers=self.auth(token)
                )
                self.assertEqual(status, 200)
                self.assertTrue(payload["bigscape_viewer_available"])
                self.assertEqual(payload["public_run_id"], public_id)
                self.assertNotIn("bigscape_viewer_database", payload)
                self.assertNotIn("result_files", payload)
            with self.subTest(token=label, surface="compact-job"):
                status, payload, _ = self.request(
                    "GET", f"/api/results/{public_id}?compact=1", headers=self.auth(token)
                )
                self.assertEqual(status, 200)
                self.assertTrue(payload["bigscape_viewer_available"])
                self.assertNotIn("bigscape_viewer_database", payload)
                self.assertNotIn("result_files", payload)
            with self.subTest(token=label, surface="files"):
                status, payload, _ = self.request(
                    "GET",
                    f"/api/results/{public_id}/artifacts",
                    headers=self.auth(token),
                )
                self.assertEqual(status, 200)
                self.assertTrue(payload["bigscape_viewer_available"])
                filenames = {item["filename"] for item in payload["artifacts"]}
                self.assertNotIn("clusterweave_viewer.sqlite", filenames)
                self.assertIn("clusterweave_public.sqlite", filenames)
            with self.subTest(token=label, surface="dedicated"):
                status, body, headers = self.request(
                    "GET",
                    f"/api/results/{public_id}/bigscape-viewer-database",
                    headers=self.auth(token),
                )
                self.assertEqual(status, 200)
                self.assertEqual(body, viewer_bytes)
                self.assertEqual(headers.get("Content-Type"), "application/vnd.sqlite3")
                self.assertEqual(headers.get("Cache-Control"), "private, no-store")
                self.assertTrue(headers.get("Content-Disposition", "").startswith("inline;"))
            with self.subTest(token=label, surface="generic-denied"):
                status, payload, _ = self.request(
                    "GET",
                    f"/api/jobs/{job_id}/files/{viewer}",
                    headers=self.auth(token),
                )
                self.assertEqual(status, 403 if token == "admin-secret" else 404)

        status, payload, _ = self.request(
            "GET", f"/api/results/{public_id}/bigscape-viewer-database"
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Result not found")
        status, payload, _ = self.request(
            "GET",
            f"/api/results/{public_id}/bigscape-viewer-database/clusterweave_viewer.sqlite",
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Result not found")

        status, payload, _ = self.request(
            "GET",
            f"/api/jobs/{job_id}",
            headers=self.auth("admin-secret"),
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["bigscape_viewer_available"])
        self.assertIn("bigscape_viewer_database", payload)

        status, jobs, _ = self.request(
            "GET", "/api/jobs", headers=self.auth("admin-secret")
        )
        self.assertEqual(status, 200)
        listed = next(item for item in jobs if item["id"] == job_id)
        self.assertNotIn("bigscape_viewer_database", listed)

        status, archive_body, _ = self.request(
            "GET",
            f"/api/results/{public_id}/archive",
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(archive_body)) as archive:
            names = set(archive.namelist())
        self.assertIn("big_scape/public/clusterweave_public.sqlite", names)
        self.assertNotIn("big_scape/public/clusterweave_viewer.sqlite", names)
        self.assertNotIn(
            "big_scape/public/.clusterweave_viewer.sqlite.source.json", names
        )

        near_paths = [
            viewer + ".bak",
            viewer + "-wal",
            "data/results/demo/big_scape/public/CLUSTERWEAVE_VIEWER.SQLITE",
            "data/results/demo/big_scape/public/nested/clusterweave_viewer.sqlite",
            "data/results/demo/big_scape/output_files/data_sqlite.db",
        ]
        for rel_path in near_paths:
            target = root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(viewer_bytes)
            with self.subTest(near=rel_path):
                status, payload, _ = self.request(
                    "GET",
                    f"/api/jobs/{job_id}/files/{rel_path}",
                    headers=self.auth("admin-secret"),
                )
                self.assertEqual(status, 403)
                self.assertIn("not available", payload["detail"])

        status, body, _ = self.request(
            "GET",
            f"/api/results/{public_id}/artifacts/{public_descriptor['id']}",
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"SQLite format 3\x00"))

        # An active sidecar invalidates the exact dedicated endpoint for every
        # credential, even though admin authentication succeeds.
        active_sidecar = Path(str(viewer_path) + "-wal")
        active_sidecar.write_bytes(b"active sqlite sidecar")
        for token in [read_token, "admin-secret"]:
            status, payload, _ = self.request(
                "GET",
                f"/api/results/{public_id}/bigscape-viewer-database",
                headers=self.auth(token),
            )
            self.assertEqual(status, 404)
            self.assertEqual(payload["detail"], "Result not found")
        active_sidecar.unlink()

        tampered = b"X" + viewer_bytes[1:]
        self.assertEqual(len(tampered), len(viewer_bytes))
        viewer_path.write_bytes(tampered)
        for token in [read_token, "admin-secret"]:
            status, payload, _ = self.request(
                "GET",
                f"/api/results/{public_id}/bigscape-viewer-database",
                headers=self.auth(token),
            )
            self.assertEqual(status, 404)
            self.assertEqual(payload["detail"], "Result not found")

    def test_tampered_legacy_package_cannot_substitute_raw_sqlite(self) -> None:
        job_id = "tamperedpackage"
        read_token = "read-tampered-package"
        root = self.job_store.job_dir(job_id)
        exact = "data/results/demo/big_scape/public/clusterweave_public.sqlite"
        raw = "data/results/demo/big_scape/big_scape.db"
        package = "downloads/demo_public_results.zip"

        self.write_bigscape_public_export(root / exact)
        public_bytes = (root / exact).read_bytes()
        private_prefix = b"/data/jobs/private/raw-big-scape-database\x00"
        self.assertLess(len(private_prefix), len(public_bytes))
        tampered_bytes = private_prefix + b"X" * (
            len(public_bytes) - len(private_prefix)
        )
        self.assertEqual(len(tampered_bytes), len(public_bytes))
        raw_path = root / raw
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(tampered_bytes)
        package_path = root / package
        package_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package_path, "w", allowZip64=True) as archive:
            archive.writestr(exact, tampered_bytes)

        self.write_public_manifest_job(job_id, read_token, [exact])
        stored = self.job_store.read_job(job_id)
        assert stored is not None
        stored["result_files"] = [package, *stored["result_files"], raw]
        self.job_store.write_job(stored)

        public_id, artifacts = self.public_artifact_catalog(job_id, read_token)
        public_descriptor = self.find_public_artifact(
            artifacts,
            filename="clusterweave_public.sqlite",
            category="bigscape",
            role="public-database",
        )
        manifest_descriptor = self.find_public_artifact(
            artifacts,
            filename="public_results_manifest.tsv",
            role="manifest",
        )
        self.assertEqual(
            {item["filename"] for item in artifacts},
            {"clusterweave_public.sqlite", "public_results_manifest.tsv"},
        )

        status, public_payload, _ = self.request(
            "GET", f"/api/results/{public_id}", headers=self.auth(read_token)
        )
        self.assertEqual(status, 200)
        self.assertNotIn("result_files", public_payload)
        self.assertEqual(public_payload["id"], public_id)
        self.assertEqual(public_payload["job_id"], public_id)
        self.assertNotEqual(public_payload["id"], job_id)

        status, admin_jobs, _ = self.request(
            "GET", "/api/jobs", headers=self.auth("admin-secret")
        )
        self.assertEqual(status, 200)
        listed = next(item for item in admin_jobs if item["id"] == job_id)
        self.assertNotIn("result_files", listed)
        self.assertGreaterEqual(listed["result_file_count"], 1)

        for token in [read_token, "admin-secret"]:
            for denied in [package, raw]:
                with self.subTest(token=token, denied=denied):
                    status, _, _ = self.request(
                        "GET",
                        f"/api/jobs/{job_id}/files/{denied}",
                        headers=self.auth(token),
                    )
                    self.assertEqual(status, 403 if token == "admin-secret" else 404)

            status, manifest_body, _ = self.request(
                "GET",
                f"/api/results/{public_id}/artifacts/{manifest_descriptor['id']}",
                headers=self.auth(token),
            )
            self.assertEqual(status, 200)
            self.assertTrue(manifest_body.startswith(b"path\tbytes\tsha256\n"))

            status, database_body, _ = self.request(
                "GET",
                f"/api/results/{public_id}/artifacts/{public_descriptor['id']}",
                headers=self.auth(token),
            )
            self.assertEqual(status, 200)
            self.assertEqual(database_body, public_bytes)

        status, archive_body, _ = self.request(
            "GET",
            f"/api/results/{public_id}/archive",
            headers=self.auth(read_token),
        )
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(archive_body)) as archive:
            member = "big_scape/public/clusterweave_public.sqlite"
            self.assertEqual(archive.read(member), public_bytes)
            self.assertNotIn(private_prefix, archive.read(member))
            self.assertNotIn("big_scape/big_scape.db", archive.namelist())
            manifest_rows = archive.read(
                "downloads/public_results_manifest.tsv"
            ).decode("utf-8").splitlines()
        self.assertEqual(manifest_rows[0], "path\tbytes\tsha256")
        self.assertEqual(
            manifest_rows[1],
            f"{member}\t{len(public_bytes)}\t{hashlib.sha256(public_bytes).hexdigest()}",
        )

    def test_viewer_marker_schema_and_attestation_sidecar_have_no_admin_bypass(self) -> None:
        public = "data/results/demo/big_scape/public/clusterweave_public.sqlite"
        viewer = "data/results/demo/big_scape/public/clusterweave_viewer.sqlite"
        index = "data/results/demo/big_scape/index.html"
        script = "data/results/demo/big_scape/html_content/js/bigscape.js"
        for offset, tamper in enumerate(("marker", "schema", "sidecar")):
            with self.subTest(tamper=tamper):
                job_id = f"viewertamper{offset}"
                read_token = f"read-viewer-tamper-{offset}"
                root = self.job_store.job_dir(job_id)
                viewer_path = self.write_bigscape_viewer_export(root / public)
                self.write_public_manifest_job(
                    job_id,
                    read_token,
                    [public, index, script],
                    viewer_path=viewer,
                )
                if tamper == "sidecar":
                    viewer_path.with_name(
                        ".clusterweave_viewer.sqlite.source.json"
                    ).write_text("{}\n", encoding="utf-8")
                else:
                    with sqlite3.connect(viewer_path) as connection:
                        if tamper == "marker":
                            connection.execute(
                                "UPDATE clusterweave_viewer_export "
                                "SET query_contract='unsupported'"
                            )
                        else:
                            connection.execute(
                                "CREATE TABLE unexpected(secret TEXT)"
                            )
                        connection.commit()

                public_id = self.fixture_public_run_id(job_id)
                for token in [read_token, "admin-secret"]:
                    status, payload, _ = self.request(
                        "GET", f"/api/results/{public_id}", headers=self.auth(token)
                    )
                    self.assertEqual(status, 200)
                    self.assertNotIn("bigscape_viewer_database", payload)
                    self.assertFalse(payload["bigscape_viewer_available"])
                    status, payload, _ = self.request(
                        "GET",
                        f"/api/results/{public_id}/bigscape-viewer-database",
                        headers=self.auth(token),
                    )
                    self.assertEqual(status, 404)
                    self.assertEqual(payload["detail"], "Result not found")

                status, payload, _ = self.request(
                    "GET",
                    f"/api/jobs/{job_id}/bigscape-viewer-database",
                    headers=self.auth("admin-secret"),
                )
                self.assertEqual(status, 403)
                self.assertIn("not available", payload["detail"])

    def test_bigscape_sidecars_invalidate_exact_export_and_are_never_served(self) -> None:
        exact = "data/results/demo/big_scape/public/clusterweave_public.sqlite"
        sidecars = [
            exact + "-wal",
            "data/results/demo/big_scape/big_scape.db-wal",
            "data/results/demo/big_scape/output_files/data_sqlite.db-journal",
        ]
        for index, sidecar in enumerate(sidecars):
            job_id = f"sidecarbigscape{index}"
            read_token = f"read-sidecar-{index}"
            root = self.job_store.job_dir(job_id)
            self.write_bigscape_public_export(root / exact)
            (root / sidecar).parent.mkdir(parents=True, exist_ok=True)
            (root / sidecar).write_bytes(b"active private sqlite sidecar")
            self.write_public_manifest_job(job_id, read_token, [exact])

            public_id = self.fixture_public_run_id(job_id)
            for token in [read_token, "admin-secret"]:
                status, payload, _ = self.request(
                    "GET",
                    f"/api/results/{public_id}/artifacts",
                    headers=self.auth(token),
                )
                self.assertEqual(status, 200)
                self.assertEqual(payload["result_index_state"], "indexing")
                self.assertEqual(payload["artifacts"], [], sidecar)

            for rel_path in [exact, sidecar]:
                with self.subTest(sidecar=sidecar, path=rel_path):
                    status, payload, _ = self.request(
                        "GET",
                        f"/api/jobs/{job_id}/files/{rel_path}",
                        headers=self.auth("admin-secret"),
                    )
                    self.assertEqual(status, 403)
                    self.assertIn("not available", payload["detail"])

    def test_bigscape_redaction_and_schema_attestation_fail_closed(self) -> None:
        exact = "data/results/demo/big_scape/public/clusterweave_public.sqlite"
        mutations = {
            "unsafe-path": (
                "UPDATE gbk SET path='inputs/dataset/original_name.gbk' WHERE id=1",
            ),
            "raw-hash": (
                "UPDATE gbk SET hash='raw-private-content-hash' WHERE id=1",
            ),
            "raw-nt-blob": (
                "UPDATE gbk SET nt_seq=CAST('ACGTACGTACGT' AS BLOB) WHERE id=1",
            ),
            "empty-nt-blob": (
                "UPDATE gbk SET nt_seq=zeroblob(0) WHERE id=1",
            ),
            "raw-aa": (
                "UPDATE cds SET aa_seq='MPRIVATESEQUENCE' WHERE id=1",
            ),
            "raw-alignment": (
                "UPDATE hsp_alignment SET alignment='MPRIVATE--ALIGNMENT' WHERE hsp_id=1",
            ),
            "unsafe-run-path": (
                "UPDATE run SET output_dir='private/output' WHERE id=1",
            ),
            "raw-config-hash": (
                "UPDATE run SET config_hash='raw-private-config-hash' WHERE id=1",
            ),
            "mibig-version-path-mismatch": (
                "UPDATE run SET mibig_version='4.0' WHERE id=1",
            ),
            "extra-schema": (
                "CREATE TABLE attacker_payload(secret TEXT)",
            ),
            "foreign-key": (
                "PRAGMA foreign_keys=OFF",
                "UPDATE bgc_record SET gbk_id=999999 WHERE id=1",
            ),
        }
        for index, (case, statements) in enumerate(mutations.items()):
            job_id = f"attestbigscape{index}"
            read_token = f"read-attest-{index}"
            root = self.job_store.job_dir(job_id)
            target = root / exact
            self.write_bigscape_public_export(target)
            connection = sqlite3.connect(target)
            try:
                for statement in statements:
                    connection.execute(statement)
                connection.commit()
            finally:
                connection.close()
            self.write_public_manifest_job(job_id, read_token, [exact])

            public_id = self.fixture_public_run_id(job_id)
            for token in [read_token, "admin-secret"]:
                with self.subTest(case=case, token=token):
                    status, payload, _ = self.request(
                        "GET",
                        f"/api/results/{public_id}/artifacts",
                        headers=self.auth(token),
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(payload["result_index_state"], "indexing")
                    self.assertEqual(payload["artifacts"], [], case)

            status, payload, _ = self.request(
                "GET",
                f"/api/jobs/{job_id}/files/{exact}",
                headers=self.auth("admin-secret"),
            )
            self.assertEqual(status, 403)
            self.assertIn("not available", payload["detail"])

    def test_bigscape_attestation_accepts_generic_and_multi_run_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generic = root / "generic.sqlite"
            self.write_bigscape_public_export(generic)
            with sqlite3.connect(generic) as connection:
                connection.execute(
                    "UPDATE gbk SET path='inputs/reference/reference_00000002.gbk' "
                    "WHERE id=2"
                )
                connection.commit()
            self.assertTrue(self.app.public_bigscape_database_export_valid(generic))

            multi_run = root / "multi-run.sqlite"
            self.write_bigscape_public_export(multi_run)
            with sqlite3.connect(multi_run) as connection:
                connection.execute(
                    "UPDATE run SET mibig_version='4.0' WHERE id=2"
                )
                connection.execute(
                    "UPDATE gbk SET path="
                    "'inputs/reference/mibig_antismash_3.1_gbk/"
                    "mibig_antismash_4.0_gbk/reference_00000002.gbk' "
                    "WHERE id=2"
                )
                connection.commit()
            self.assertTrue(
                self.app.public_bigscape_database_export_valid(multi_run)
            )

    def test_public_file_manifest_and_archive_omit_stale_paths(self) -> None:
        created = self.job_store.now_iso()
        result_files = [
            "downloads/demo_public_results.zip",
            "downloads/public_results_manifest.tsv",
            "data/results/demo/figures/bgc_overlap.svg",
            "data/results/demo/summary/family_atlas_shortlist.md",
            "data/results/demo/antismash/genome_a/index.html",
            "data/results/demo/antismash/genome_a/deleted.html",
            "data/results/demo/antismash/genome_a/region001.gbk",
        ]
        job = {
            "id": "manifestjob",
            "name": "manifest-demo",
            "status": "success",
            "stage": "complete",
            "created_at": created,
            "updated_at": created,
            "log_count": 0,
            "result_files": result_files,
            "error": None,
            "cpus": 2,
            "project_name": "demo",
            "read_token_hash": self.app.job_token_hash("read-manifest"),
            "read_token_created_at": created,
        }
        root = self.job_store.job_dir("manifestjob")
        manifest_text = (
            "path\tbytes\tsha256\n"
            "data/results/demo/figures/bgc_overlap.svg\t12\tdemo-figure\n"
            "data/results/demo/summary/family_atlas_shortlist.md\t12\tdemo-summary\n"
            "data/results/demo/antismash/genome_a/index.html\t24\tdemo-html\n"
        )
        file_contents = {
            "downloads/public_results_manifest.tsv": manifest_text,
            "data/results/demo/figures/bgc_overlap.svg": "<svg></svg>\n",
            "data/results/demo/summary/family_atlas_shortlist.md": "# shortlist\n",
            "data/results/demo/antismash/genome_a/index.html": "<html>antiSMASH</html>\n",
            "data/results/demo/antismash/genome_a/region001.gbk": "LOCUS raw\n",
            "data/results/demo/clinker/panels/atlas/choline/panel.html": "<html>synteny</html>\n",
            "data/results/demo/clinker/panels/atlas/choline/run_panel.sh": "docker run private\n",
            "data/results/demo/tmp/scratch.txt": "temporary\n",
            "data/results/demo/summary_tables/logs/raw.log": "SECRET=1\n",
            "data/results/demo/reproducibility/provenance.tsv": "/private/path\n",
            "data/results/demo/reproducibility/external_artifacts.tsv": "/private/path\n",
            "data/results/demo/run_clusterweave_context.env": "SECRET=1\n",
            "data/results/demo/downloads/nested.zip": "PK\n",
        }
        manifest_public_paths = [
            "data/results/demo/figures/bgc_overlap.svg",
            "data/results/demo/summary/family_atlas_shortlist.md",
            "data/results/demo/antismash/genome_a/index.html",
        ]
        manifest_text = "path\tbytes\tsha256\n" + "".join(
            f"{path}\t{len(file_contents[path].encode('utf-8'))}\t"
            f"{hashlib.sha256(file_contents[path].encode('utf-8')).hexdigest()}\n"
            for path in manifest_public_paths
        )
        file_contents["downloads/public_results_manifest.tsv"] = manifest_text
        for rel_path, content in file_contents.items():
            target = root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        symlink = root / "data" / "results" / "demo" / "figures" / "leak.svg"
        try:
            symlink.symlink_to(root / "job.json")
        except (NotImplementedError, OSError):
            pass
        package_path = root / "downloads" / "demo_public_results.zip"
        with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("downloads/public_results_manifest.tsv", file_contents["downloads/public_results_manifest.tsv"])
            archive.writestr("data/results/demo/figures/bgc_overlap.svg", file_contents["data/results/demo/figures/bgc_overlap.svg"])
        importlib.import_module("result_attestation").write_result_attestation(
            root,
            "manifestjob",
            verify_hashes=True,
            path_validator=lambda path: self.app.result_file_is_publicly_servable(
                root, path
            ),
        )
        self.job_store.write_job(job)

        public_id, artifacts = self.public_artifact_catalog(
            "manifestjob", "read-manifest"
        )
        self.assertEqual(
            {artifact["filename"] for artifact in artifacts},
            {
                "public_results_manifest.tsv",
                "bgc_overlap.svg",
                "family_atlas_shortlist.md",
                "index.html",
            },
        )
        self.assertEqual(
            {artifact["category"] for artifact in artifacts},
            {"downloads", "figures", "summaries", "antismash"},
        )

        status, job_payload, _ = self.request(
            "GET",
            f"/api/results/{public_id}",
            headers=self.auth("read-manifest"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(job_payload["public_run_id"], public_id)
        self.assertNotIn("result_files", job_payload)

        manifest_descriptor = self.find_public_artifact(
            artifacts,
            filename="public_results_manifest.tsv",
            role="manifest",
        )
        status, manifest_body, _ = self.request(
            "GET",
            f"/api/results/{public_id}/artifacts/{manifest_descriptor['id']}",
            headers=self.auth("read-manifest"),
        )
        self.assertEqual(status, 200)
        manifest_rows = {
            line.split("\t", 1)[0]
            for line in manifest_body.decode("utf-8").splitlines()[1:]
            if line.strip()
        }
        self.assertEqual(manifest_rows, set(manifest_public_paths))

        status, payload, _ = self.request(
            "GET",
            "/api/jobs/manifestjob/files/downloads/demo_public_results.zip",
            headers=self.auth("read-manifest"),
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Result not found")

        status, archive_body, _ = self.request(
            "GET",
            f"/api/results/{public_id}/archive",
            headers=self.auth("read-manifest"),
        )
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(archive_body)) as archive:
            names = set(archive.namelist())
        self.assertEqual(
            names,
            {
                "downloads/public_results_manifest.tsv",
                "figures/bgc_overlap.svg",
                "summary/family_atlas_shortlist.md",
                "antismash/genome_a/index.html",
            },
        )
        for name in names:
            self.assertFalse(name.startswith("data/results/demo/"), name)
        self.assertNotIn("downloads/demo_public_results.zip", names)
        self.assertNotIn("data/results/demo/antismash/genome_a/deleted.html", names)
        self.assertNotIn("antismash/genome_a/region001.gbk", names)
        self.assertNotIn("clinker/panels/atlas/choline/panel.html", names)
        self.assertNotIn("clinker/panels/atlas/choline/run_panel.sh", names)
        self.assertNotIn("tmp/scratch.txt", names)
        self.assertNotIn("summary_tables/logs/raw.log", names)
        self.assertNotIn("reproducibility/provenance.tsv", names)
        self.assertNotIn("reproducibility/external_artifacts.tsv", names)
        self.assertNotIn("run_clusterweave_context.env", names)
        self.assertNotIn("downloads/nested.zip", names)
        self.assertNotIn("figures/leak.svg", names)

    def test_exact_taxonomy_tree_files_share_read_token_admin_and_archive_policy(self) -> None:
        created = self.job_store.now_iso()
        root = self.job_store.job_dir("treejob")
        prefix = "data/results/demo"
        tree_contents = {
            f"{prefix}/figures/phylogeny/clusterweave_taxon_tree.svg": b"<svg><title>Taxon tree</title></svg>\n",
            f"{prefix}/figures/phylogeny/clusterweave_taxon_tree.png": b"PNG fixture\n",
            f"{prefix}/figures/phylogeny/clusterweave_taxon_tree.nwk": b"(fungus,bacterium);\n",
            f"{prefix}/figures/phylogeny/clusterweave_taxon_tree_leaf_profiles.tsv": b"genome_id\ttaxon_group\n",
            f"{prefix}/figures/phylogeny/clusterweave_gcf_network_edges.tsv": b"source\ttarget\n",
            f"{prefix}/figures/phylogeny/clusterweave_taxon_tree.graphml": b"<graphml />\n",
            f"{prefix}/figures/phylogeny/clusterweave_tree_manifest.json": b'{"schema_version":1}\n',
            f"{prefix}/figures/phylogeny/clusterweave_tree_methods.json": b'{"tree_method":"taxonomy"}\n',
        }
        tree_bundle_buffer = io.BytesIO()
        with zipfile.ZipFile(tree_bundle_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("clusterweave_taxon_tree.nwk", "(fungus,bacterium);\n")
        tree_bundle_path = f"{prefix}/figures/phylogeny/clusterweave_tree_bundle.zip"
        tree_contents[tree_bundle_path] = tree_bundle_buffer.getvalue()

        approved_tables = {
            f"{prefix}/summary/candidate_bgc_gcf_crosswalk.tsv": b"genome\tgcf_id\n",
            f"{prefix}/summary_tables/antismash_product_types_exact.tsv": b"genome\texact_product_type\n",
            f"{prefix}/summary_tables/bacteria_id_legend.tsv": b"bacteria_id\tgenome_id\n",
            f"{prefix}/summary_tables/ecobac_metadata_normalized.tsv": b"accession\tgenome_id_current\n",
            f"{prefix}/summary_tables/fungal_id_legend.tsv": b"fungal_id\tgenome_id\n",
            f"{prefix}/summary_tables/genome_id_legend.tsv": b"genome_id\ttaxon_group\n",
            f"{prefix}/summary_tables/genome_taxon_manifest.tsv": b"genome_id\ttaxon_group\n",
            f"{prefix}/summary_tables/routing_diagnostics.tsv": b"input_key\troute_status\n",
            f"{prefix}/summary_tables/taxonomy_metadata_normalized.tsv": b"genome_id\ttaxid\n",
            f"{prefix}/integrated_evidence/cross_kingdom_evidence.tsv": b"candidate_id\tevidence_tier\n",
            f"{prefix}/integrated_evidence/cross_kingdom_evidence.json": b'{"candidates":[]}\n',
            f"{prefix}/integrated_evidence/cross_kingdom_evidence_cards.txt": b"Cross-Kingdom evidence\n",
            f"{prefix}/integrated_evidence/putative_transfer_evidence.tsv": b"candidate_id\tevidence_tier\n",
            f"{prefix}/integrated_evidence/putative_transfer_evidence.json": b'{"candidates":[]}\n',
            f"{prefix}/integrated_evidence/putative_transfer_evidence_cards.txt": b"Putative transfer evidence\n",
        }
        legacy_public = {
            f"{prefix}/figures/bgc_overlap.svg": b"<svg></svg>\n",
            f"{prefix}/antismash/genome_a/index.html": b"<html>antiSMASH</html>\n",
            f"{prefix}/funbgcex/genome_a/index.html": b"<html>FunBGCeX</html>\n",
        }
        rejected = {
            f"{prefix}/figures/phylogeny/clusterweave_tree_manifest-copy.json": b"{}\n",
            f"{prefix}/figures/phylogeny/clusterweave_tree_bundle-copy.zip": b"PK private\n",
            f"{prefix}/figures/phylogeny/clusterweave_taxon_tree-copy.nwk": b"(private);\n",
            f"{prefix}/figures/phylogeny/clusterweave_taxon_tree_extra.svg": b"<svg />\n",
            f"{prefix}/figures/phylogeny/alignment.fasta": b">private\nATGC\n",
            f"{prefix}/antismash/genome_a/genome_a.json": b'{"sequence":"ATGC"}\n',
            f"{prefix}/input_gbks/raw.gbk": b"LOCUS raw\nORIGIN\n        1 atgc\n//\n",
            f"{prefix}/summary_tables/shard_manifest.tsv": b"private_path\n",
            f"{prefix}/summary_tables/cache/cached.tsv": b"private\n",
            f"{prefix}/summary_tables/run_manifest.json": b'{"command":"private"}\n',
            f"{prefix}/integrated_evidence/cross_kingdom_evidence-copy.json": b"{}\n",
            f"{prefix}/integrated_evidence/nested/cross_kingdom_evidence.tsv": b"private\n",
            f"{prefix}/integrated_evidence/putative_transfer_evidence-copy.json": b"{}\n",
            f"{prefix}/integrated_evidence/nested/putative_transfer_evidence.tsv": b"private\n",
            f"{prefix}/integrated_evidence/status_manifest.json": b'{"status":"private"}\n',
            f"{prefix}/integrated_evidence/private_sequences.faa": b">private\nMPEPTIDE\n",
        }
        approved = {**tree_contents, **approved_tables, **legacy_public}
        manifest_paths = [*approved]
        manifest_text = "path\tbytes\tsha256\n" + "".join(
            f"{path}\t{len(approved[path])}\t"
            f"{hashlib.sha256(approved[path]).hexdigest()}\n"
            for path in manifest_paths
        )

        for rel_path, content in {**approved, **rejected}.items():
            target = root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        manifest_path = root / "downloads" / "public_results_manifest.tsv"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(manifest_text, encoding="utf-8")
        package_path = root / "downloads" / "demo_public_results.zip"
        with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("downloads/public_results_manifest.tsv", manifest_text)
            archive.writestr(
                "data/results/demo/figures/phylogeny/clusterweave_tree_bundle.zip",
                tree_contents[tree_bundle_path],
            )

        job = {
            "id": "treejob",
            "name": "tree-demo",
            "project_name": "demo",
            "status": "success",
            "stage": "complete",
            "created_at": created,
            "updated_at": created,
            "log_count": 0,
            "result_files": [
                "downloads/demo_public_results.zip",
                "downloads/public_results_manifest.tsv",
                *manifest_paths,
            ],
            "error": None,
            "cpus": 2,
            "read_token_hash": self.app.job_token_hash("read-tree"),
            "read_token_created_at": created,
        }
        self.job_store.write_job(job)
        importlib.import_module("result_attestation").write_result_attestation(
            root,
            "treejob",
            verify_hashes=True,
            path_validator=lambda path: self.app.result_file_is_publicly_servable(
                root, path
            ),
        )

        svg_path = f"{prefix}/figures/phylogeny/clusterweave_taxon_tree.svg"
        public_id, artifacts = self.public_artifact_catalog("treejob", "read-tree")
        svg_descriptor = self.find_public_artifact(
            artifacts,
            filename="clusterweave_taxon_tree.svg",
            category="phylogeny",
        )
        bundle_descriptor = self.find_public_artifact(
            artifacts,
            filename="clusterweave_tree_bundle.zip",
            category="phylogeny",
        )
        manifest_descriptor = self.find_public_artifact(
            artifacts,
            filename="public_results_manifest.tsv",
            role="manifest",
        )
        self.assertEqual(len(artifacts), len(approved) + 1)
        self.assertEqual(
            sorted(str(artifact["filename"]) for artifact in artifacts),
            sorted(
                ["public_results_manifest.tsv"]
                + [Path(path).name for path in approved]
            ),
        )

        for route in [
            f"/api/results/{public_id}",
            f"/api/results/{public_id}/artifacts",
            f"/api/results/{public_id}/artifacts/{svg_descriptor['id']}",
            f"/api/results/{public_id}/archive",
        ]:
            with self.subTest(route=route, authority="anonymous"):
                status, payload, _ = self.request("GET", route)
                self.assertEqual(status, 404)
                self.assertEqual(payload["detail"], "Result not found")

        for token in ["read-tree", "admin-secret"]:
            with self.subTest(token=token, file="svg-inline"):
                status, body, headers = self.request(
                    "GET",
                    f"/api/results/{public_id}/artifacts/{svg_descriptor['id']}",
                    headers=self.auth(token),
                )
                self.assertEqual(status, 200)
                self.assertEqual(body, tree_contents[svg_path])
                self.assertEqual(headers.get("Content-Type"), "image/svg+xml; charset=utf-8")
                self.assertTrue(headers.get("Content-Disposition", "").startswith("inline;"))

            status, _, headers = self.request(
                "GET",
                f"/api/results/{public_id}/artifacts/{svg_descriptor['id']}/download",
                headers=self.auth(token),
            )
            self.assertEqual(status, 200)
            self.assertTrue(headers.get("Content-Disposition", "").startswith("attachment;"))

            status, bundle_body, _ = self.request(
                "GET",
                f"/api/results/{public_id}/artifacts/{bundle_descriptor['id']}",
                headers=self.auth(token),
            )
            self.assertEqual(status, 200)
            self.assertEqual(bundle_body, tree_contents[tree_bundle_path])

            status, manifest_body, _ = self.request(
                "GET",
                f"/api/results/{public_id}/artifacts/{manifest_descriptor['id']}",
                headers=self.auth(token),
            )
            self.assertEqual(status, 200)
            self.assertEqual(manifest_body, manifest_text.encode("utf-8"))

            for rel_path in rejected:
                with self.subTest(token=token, rejected=rel_path):
                    status, _, _ = self.request(
                        "GET", f"/api/jobs/treejob/files/{rel_path}", headers=self.auth(token)
                    )
                    self.assertEqual(status, 403 if token == "admin-secret" else 404)

            status, archive_body, headers = self.request(
                "GET",
                f"/api/results/{public_id}/archive",
                headers=self.auth(token),
            )
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("Content-Type"), "application/zip")
            with zipfile.ZipFile(io.BytesIO(archive_body)) as archive:
                archive_names = set(archive.namelist())
            expected_archive_names = {
                "downloads/public_results_manifest.tsv",
                *(path.removeprefix(f"{prefix}/") for path in approved),
            }
            self.assertEqual(archive_names, expected_archive_names)
            self.assertIn("figures/phylogeny/clusterweave_tree_bundle.zip", archive_names)
            self.assertNotIn("downloads/demo_public_results.zip", archive_names)
            self.assertTrue(
                {
                    path.removeprefix(f"{prefix}/")
                    for path in rejected
                }.isdisjoint(archive_names)
            )

        status, body, _ = self.request(
            "GET",
            f"/api/jobs/treejob/files/{svg_path}",
            headers=self.auth("admin-secret"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, tree_contents[svg_path])

        status, payload, _ = self.request(
            "GET",
            "/api/jobs/treejob/files/downloads/demo_public_results.zip",
            headers=self.auth("admin-secret"),
        )
        self.assertEqual(status, 403)
        self.assertIn("not available", payload["detail"])

    def test_read_token_cannot_fetch_unmanifested_or_private_job_files(self) -> None:
        self.write_job("jobone", "read-one")
        job_root = self.job_store.job_dir("jobone")
        for rel, content in {
            "inputs/private.fna": ">private\nATGC\n",
            "work/intermediate.txt": "work detail\n",
            "data/genomes/fungi/project/raw.gbk": "LOCUS       raw\n",
            "data/results/project/private.tsv": "not\tmanifested\n",
        }.items():
            path = job_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        public_id, artifacts = self.public_artifact_catalog("jobone", "read-one")
        self.assertEqual(
            {artifact["filename"] for artifact in artifacts},
            {"public_results_manifest.tsv", "figure.svg"},
        )
        figure = self.find_public_artifact(
            artifacts,
            filename="figure.svg",
            category="figures",
        )

        for rel in [
            "job.json",
            "logs.txt",
            "inputs/private.fna",
            "work/intermediate.txt",
            "data/genomes/fungi/project/raw.gbk",
            "data/results/project/private.tsv",
            "results/missing.svg",
        ]:
            with self.subTest(rel=rel):
                status, payload, _ = self.request(
                    "GET",
                    f"/api/jobs/jobone/files/{rel}",
                    headers=self.auth("read-one"),
                )
                self.assertEqual(status, 404)
                self.assertEqual(payload["detail"], "Result not found")

        status, body, _ = self.request(
            "GET",
            f"/api/results/{public_id}/artifacts/{figure['id']}",
            headers=self.auth("read-one"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<svg></svg>\n")

        status, payload, _ = self.request(
            "GET",
            "/api/jobs/jobone/files/inputs/private.fna",
            headers=self.auth("admin-secret"),
        )
        self.assertEqual(status, 403)
        self.assertIn("not available", payload["detail"])

    def test_raw_logs_are_admin_only_in_public_mode(self) -> None:
        self.write_job("jobone", "read-one")
        public_id = self.fixture_public_run_id("jobone")

        status, payload, _ = self.request("GET", "/api/jobs/jobone/logs", headers=self.auth("read-one"))
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Result not found")

        status, payload, _ = self.request(
            "GET",
            f"/api/results/{public_id}/activity",
            headers=self.auth("read-one"),
        )
        self.assertEqual(status, 200)
        self.assertIn("public_events", payload)
        self.assertNotIn("lines", payload)

        status, payload, _ = self.request("GET", "/api/jobs/jobone/logs", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)

    def test_read_token_payload_redacts_raw_settings_and_errors(self) -> None:
        self.write_job("jobone", "read-one", status="failed")
        job = self.job_store.read_job("jobone")
        self.assertIsNotNone(job)
        assert job is not None
        job["error"] = "/data/jobs/jobone failed with SECRET_TOKEN=abc"
        job["settings"] = {
            "target_genome": "private_target",
            "env_overrides": "SECRET_TOKEN=abc",
            "massive_dataset_id": "MSV000000000",
        }
        job["submission_settings"] = dict(job["settings"])
        self.job_store.write_job(job)

        status, payload, _ = self.request("GET", "/api/jobs/jobone", headers=self.auth("read-one"))
        self.assertEqual(status, 200)
        self.assertNotIn("settings", payload)
        self.assertNotIn("submission_settings", payload)
        self.assertNotIn("result_root", payload)
        rendered = json.dumps(payload)
        self.assertNotIn("SECRET_TOKEN", rendered)
        self.assertNotIn("/data/jobs", rendered)
        self.assertIn("error_summary", payload)

        status, payload, _ = self.request("GET", "/api/jobs/jobone", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertIn("settings", payload)
        self.assertIn("SECRET_TOKEN", payload["error"])

    def test_public_activity_events_sanitize_per_genome_runtime_logs(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        self.job_store.write_logs(
            "jobone",
            [
                "[08:04:16] Stage 1/4: running run_annotation_and_detection.sh",
                "[08:04:20] Genomes to process (4): fungus_id1, fungus id2, /data/jobs/jobone/private/fungus_id3.fna, fungus_id4",
                "[08:04:21] [1/4] genome=fungus_id1",
                "[08:04:22] [2026-05-12 08:04:22] [INFO] fungus_id1: running antiSMASH (outdir=/data/jobs/jobone/private/secret)",
                '[08:04:23] [2026-05-12 08:04:23] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="Scanning protein domains"',
                "[08:04:24] [2026-05-12 08:04:24] [INFO] TOOL_RAW genome=fungus_id1 tool=antismash stream=stderr /data/jobs/jobone/private/secret raw ERROR",
                "[08:04:25] [2026-05-12 08:04:25] [INFO] TOOL_HEARTBEAT genome=fungus_id1 tool=antismash phase=detect elapsed=1800s",
                "[08:04:26] [2026-05-12 08:04:26] [INFO] TOOL_RAW genome=fungus_id1 tool=antismash stream=stderr INFO     28/06 08:04:26   Running whole-genome PFAM search",
                '[08:04:27] [2026-05-12 08:04:27] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="Scanning protein domains"',
                "[08:04:28] [2026-05-12 08:04:28] [INFO] TOOL_HEARTBEAT genome=fungus_id1 tool=antismash phase=detect elapsed=3600s",
                '[08:04:29] [2026-05-12 08:04:29] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=funannotate phase=predict message="Training gene models"',
                "[08:04:30] [2026-05-12 08:04:30] [INFO] fungus_id4: running FunBGCeX (outdir=/data/jobs/jobone/private/secret)",
                "[08:04:31] [WARN] Rhizopus_delemar: funannotate could not train AUGUSTUS; validated_busco_models=153 required_training_models=200 busco_db=fungi policy=taxonomy:mucorales",
                "[08:04:32] Stage 2/4: running run_bigscape.sh",
            ],
        )

        status, payload, _ = self.request("GET", "/api/jobs/jobone", headers=self.auth("read-one"))
        self.assertEqual(status, 200)
        events = payload["public_events"]
        rendered = json.dumps(events)
        self.assertIn("Running antiSMASH on fungus_id1", rendered)
        self.assertIn("antiSMASH: Scanning protein domains", rendered)
        self.assertIn("antiSMASH: Running whole-genome PFAM search", rendered)
        self.assertIn("antiSMASH still running", rendered)
        self.assertIn("1h active", rendered)
        scanning_event = next(event for event in events if event.get("title") == "antiSMASH: Scanning protein domains")
        self.assertEqual(scanning_event.get("time"), "08:04:27")
        self.assertIn("funannotate: Training gene models", rendered)
        self.assertIn("Running FunBGCeX on fungus_id4", rendered)
        self.assertIn("Annotation skipped for Rhizopus_delemar", rendered)
        self.assertIn("BUSCO training had 153 of 200 required models", rendered)
        self.assertIn("Running BiG-SCAPE family graph", rendered)
        self.assertNotIn("TOOL_RAW", rendered)
        self.assertNotIn("raw ERROR", rendered)
        self.assertNotIn("/data/jobs", rendered)
        self.assertNotIn("secret", rendered)

    def test_public_activity_heartbeat_refresh_preserves_tool_progress(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        logs = [
            "[08:04:16] Stage 1/4: running run_annotation_and_detection.sh",
            "[08:04:20] Genomes to process (1): fungus_id1",
            "[08:04:21] [1/1] genome=fungus_id1",
            '[08:04:23] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="Scanning protein domains"',
        ]
        for index in range(45):
            elapsed = (index + 1) * 60
            logs.append(
                f"[08:05:{index % 60:02d}] [INFO] TOOL_HEARTBEAT genome=fungus_id1 tool=antismash phase=detect elapsed={elapsed}s"
            )
        self.job_store.write_logs("jobone", logs)

        status, payload, _ = self.request("GET", "/api/jobs/jobone", headers=self.auth("read-one"))
        self.assertEqual(status, 200)
        events = payload["public_events"]
        titles = [event.get("title") for event in events]
        self.assertIn("antiSMASH: Scanning protein domains", titles)
        heartbeats = [event for event in events if event.get("title") == "antiSMASH still running"]
        self.assertEqual(len(heartbeats), 1)
        self.assertEqual(heartbeats[0].get("meta"), "fungus_id1 / Genome 1 of 1 / 45 min active")

    def test_genome_progress_is_independent_sanitized_and_survives_event_limit(self) -> None:
        self.write_job("jobone", "read-one", status="success")
        job = self.job_store.read_job("jobone")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "fungus_id1",
                "taxon_group": "fungi",
                "source_accession": "GCA_000011425.1",
            },
            {
                "genome_id": "bacteria_demo",
                "taxon_group": "bacteria",
                "source_accession": "GCF_000005845.2",
            },
            {
                "genome_id": "Rhizopus_stolonifer_PRFJ01",
                "taxon_group": "fungi",
                "source_accession": "GCA_030770425.1",
            },
            *[
                {
                    "genome_id": f"accepted_genome_{index:02d}",
                    "taxon_group": "fungi",
                    "source_accession": f"GCA_{index:09d}.1",
                }
                for index in range(1, 38)
            ],
        ]
        self.job_store.write_job(job)
        logs = [
            '[08:00:01] NCBI_DOWNLOAD_PROGRESS accession=GCA_000011425.1 taxon=fungi status=running percent=2 message="Downloading genome from NCBI"',
            '[08:00:02] GENOME_PROGRESS genome=fungus_id1 stage=annotation percent=25 bar=[#####---------------] message="Annotation fallback produced GenBank"',
            '[08:00:03] GENOME_PROGRESS genome=bacteria_demo stage=antismash percent=70 bar=[##############------] message="antiSMASH complete"',
            '[08:00:04] GENOME_PROGRESS genome=bacteria_demo stage=funbgcex percent=100 bar=[####################] message="FunBGCeX not applicable to bacterial taxon"',
            '[08:00:05] GENOME_PROGRESS genome=fungus_id1 stage=funbgcex percent=100 bar=[####################] message="FunBGCeX complete"',
            '[08:00:06] GENOME_PROGRESS genome=Rhizopus_stolonifer_PRFJ01 stage=annotation percent=100 bar=[####################] message="Dropped: funannotate_busco_training_insufficient /data/jobs/jobone/private"',
        ]
        logs.extend(
            f"[08:01:{index % 60:02d}] Wrote summary table {index}"
            for index in range(55)
        )
        self.job_store.write_logs("jobone", logs)

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genomes = {row["genome_id"]: row for row in payload["genome_progress"]}
        self.assertEqual(len(genomes), 40)
        self.assertTrue(
            {"fungus_id1", "bacteria_demo", "Rhizopus_stolonifer_PRFJ01"}
            <= set(genomes)
        )
        self.assertEqual(genomes["fungus_id1"]["status"], "complete")
        self.assertEqual(genomes["fungus_id1"]["percent"], 100)
        self.assertEqual(genomes["bacteria_demo"]["status"], "complete")
        self.assertEqual(genomes["bacteria_demo"]["taxon_group"], "bacteria")
        self.assertEqual(genomes["bacteria_demo"]["stage"], "complete")
        self.assertEqual(genomes["bacteria_demo"]["tool"], "antiSMASH")
        self.assertEqual(genomes["bacteria_demo"]["message"], "BGC detection complete")
        self.assertEqual(genomes["Rhizopus_stolonifer_PRFJ01"]["status"], "warning")
        self.assertTrue(genomes["Rhizopus_stolonifer_PRFJ01"]["terminal"])
        rendered = json.dumps(payload["genome_progress"])
        self.assertNotIn("/data/jobs", rendered)
        self.assertNotIn("private", rendered)
        self.assertNotIn("FunBGCeX not applicable to bacterial", rendered)

    def test_ncbi_bacterial_route_id_matches_fungal_naming_policy(self) -> None:
        genome_id = self.app.ncbi_route_genome_id(
            "Bacillus subtilis subsp. subtilis str. 168",
            "bacteria",
            {"organism": {"infraspecific_names": {"strain": "168"}}},
            "GCF_000009045.1",
        )
        self.assertEqual(genome_id, "Bacillus_subtilis_168")
        self.assertFalse(genome_id.startswith("bacteria_"))

    def test_legacy_ncbi_bacterial_progress_hides_historical_display_prefix(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        job = self.job_store.read_job("jobone")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "bacteria_Bacillus_subtilis_168",
                "taxon_group": "bacteria",
                "taxon_source": "ncbi",
                "organism_name": "Bacillus subtilis 168",
                "source_accession": "GCF_000009045.1",
            }
        ]
        self.job_store.write_job(job)
        self.job_store.write_logs(
            "jobone",
            [
                '[08:00:01] GENOME_PROGRESS genome=bacteria_Bacillus_subtilis_168 stage=antismash percent=42 bar=[########------------] message="Running whole-genome PFAM search"',
            ],
        )

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["genome_progress"]), 1)
        genome = payload["genome_progress"][0]
        self.assertEqual(genome["genome_id"], "bacteria_Bacillus_subtilis_168")
        self.assertEqual(genome["display_label"], "Bacillus subtilis 168")
        self.assertEqual(genome["taxon_group"], "bacteria")

    def test_late_legacy_taxon_route_recomputes_bacterial_display_label(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        self.job_store.write_logs(
            "jobone",
            [
                '[08:00:01] GENOME_PROGRESS genome=bacteria_Bacillus_subtilis_168 stage=antismash percent=42 bar=[########------------] message="Running whole-genome PFAM search"',
                '[08:00:02] TAXON_ROUTE genome=bacteria_Bacillus_subtilis_168 taxon=bacteria source=ncbi status=routed message="prediction=prodigal detector=antismash"',
            ],
        )
        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genome = payload["genome_progress"][0]
        self.assertEqual(genome["display_label"], "Bacillus subtilis 168")
        self.assertEqual(genome["taxon_group"], "bacteria")

    def test_uploaded_bacterial_name_keeps_non_synthetic_bacteria_prefix(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        job = self.job_store.read_job("jobone")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "bacteria_isolate_7",
                "taxon_group": "bacteria",
                "taxon_source": "user_declaration",
            }
        ]
        self.job_store.write_job(job)
        self.job_store.write_logs(
            "jobone",
            [
                '[08:00:01] GENOME_PROGRESS genome=bacteria_isolate_7 stage=antismash percent=42 bar=[########------------] message="Running whole-genome PFAM search"',
                '[08:00:02] TAXON_ROUTE genome=bacteria_isolate_7 taxon=bacteria source=user_declaration status=routed message="prediction=prodigal detector=antismash"',
            ],
        )

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )

        self.assertEqual(status, 200)
        genome = payload["genome_progress"][0]
        self.assertEqual(genome["display_label"], "bacteria isolate 7")
        self.assertEqual(genome["taxon_group"], "bacteria")


    def test_antismash_record_progress_maps_to_sanitized_genome_band(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        job = self.job_store.read_job("jobone")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "fungus_id1",
                "taxon_group": "fungi",
                "source_accession": "GCA_000011425.1",
            }
        ]
        self.job_store.write_job(job)
        self.job_store.write_logs(
            "jobone",
            [
                '[08:00:01] ANTISMASH_RECORD_PROGRESS genome=fungus_id1 record=private_record_alpha ordinal=2/5 percent=40 bar=[########------------] message="antiSMASH record shard complete"',
                '[08:00:02] ANTISMASH_RECORD_PROGRESS genome=fungus_id1 record=private_record_beta ordinal=3/5 percent=41 bar=[########------------] message="TOKEN=fake-record-secret /data/jobs/jobone/private/record.gbk"',
            ],
        )

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genome = payload["genome_progress"][0]
        self.assertEqual(genome["percent"], 49)
        self.assertEqual(genome["stage"], "antismash")
        self.assertEqual(genome["tool"], "antiSMASH")
        self.assertEqual(genome["status"], "running")
        self.assertEqual(genome["message"], "Record 3 of 5 · 41%")
        rendered = json.dumps(payload["genome_progress"])
        self.assertNotIn("private_record_alpha", rendered)
        self.assertNotIn("private_record_beta", rendered)
        self.assertNotIn("fake-record-secret", rendered)
        self.assertNotIn("/data/jobs", rendered)
        self.assertNotIn("private", rendered)

    def test_bacterial_native_terminal_marker_projects_antismash_tool(self) -> None:
        self.write_job("jobone", "read-one", status="success")
        job = self.job_store.read_job("jobone")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "bacteria_demo",
                "taxon_group": "bacteria",
                "source_accession": "GCF_000005845.2",
            }
        ]
        self.job_store.write_job(job)
        self.job_store.write_logs(
            "jobone",
            [
                '[08:00:01] GENOME_PROGRESS genome=bacteria_demo stage=antismash percent=70 bar=[##############------] message="antiSMASH complete"',
                '[08:00:02] GENOME_PROGRESS genome=bacteria_demo stage=antismash percent=100 bar=[####################] message="BGC detection complete"',
            ],
        )

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genome = payload["genome_progress"][0]
        self.assertEqual(genome["stage"], "complete")
        self.assertEqual(genome["tool"], "antiSMASH")
        self.assertEqual(genome["percent"], 100)
        self.assertEqual(genome["status"], "complete")
        self.assertEqual(genome["message"], "BGC detection complete")
        self.assertTrue(genome["terminal"])

    def test_bacterial_legacy_success_marker_cannot_overwrite_failure(self) -> None:
        self.write_job("jobone", "read-one", status="success")
        job = self.job_store.read_job("jobone")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "bacteria_demo",
                "taxon_group": "bacteria",
                "source_accession": "GCF_000005845.2",
            }
        ]
        self.job_store.write_job(job)
        self.job_store.write_logs(
            "jobone",
            [
                '[08:00:01] GENOME_PROGRESS genome=bacteria_demo stage=antismash percent=70 bar=[##############------] message="antiSMASH failed"',
                '[08:00:02] GENOME_PROGRESS genome=bacteria_demo stage=complete percent=100 bar=[####################] message="BGC detection complete"',
            ],
        )

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genome = payload["genome_progress"][0]
        self.assertEqual(genome["stage"], "complete")
        self.assertEqual(genome["tool"], "antiSMASH")
        self.assertEqual(genome["percent"], 100)
        self.assertEqual(genome["status"], "warning")
        self.assertEqual(genome["message"], "antiSMASH failed")
        self.assertTrue(genome["terminal"])

    def test_antismash_record_failure_waits_for_genome_completion(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        job = self.job_store.read_job("jobone")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "fungus_id1",
                "taxon_group": "fungi",
                "source_accession": "GCA_000011425.1",
            }
        ]
        self.job_store.write_job(job)
        logs = [
            '[08:00:01] ANTISMASH_RECORD_PROGRESS genome=fungus_id1 record=private_record_alpha ordinal=1/2 percent=50 bar=[##########----------] message="antiSMASH record shard failed"',
        ]
        self.job_store.write_logs("jobone", logs)

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genome = payload["genome_progress"][0]
        self.assertEqual(genome["percent"], 52)
        self.assertEqual(genome["status"], "running")
        self.assertFalse(genome["terminal"])

        logs.append(
            '[08:00:02] GENOME_PROGRESS genome=fungus_id1 stage=antismash percent=70 bar=[##############------] message="antiSMASH complete"'
        )
        self.job_store.write_logs("jobone", logs)
        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genome = payload["genome_progress"][0]
        self.assertEqual(genome["percent"], 70)
        self.assertEqual(genome["status"], "running")
        self.assertFalse(genome["terminal"])

        logs.append(
            '[08:00:03] GENOME_PROGRESS genome=fungus_id1 stage=funbgcex percent=100 bar=[####################] message="FunBGCeX complete"'
        )
        self.job_store.write_logs("jobone", logs)
        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genome = payload["genome_progress"][0]
        self.assertEqual(genome["percent"], 100)
        self.assertEqual(genome["status"], "complete")
        self.assertTrue(genome["terminal"])

    def test_fungal_tool_warning_is_not_attributed_to_later_funbgcex_completion(self) -> None:
        self.write_job("jobone", "read-one", status="success")
        job = self.job_store.read_job("jobone")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "fungus_id1",
                "taxon_group": "fungi",
                "source_accession": "GCA_000011425.1",
            }
        ]
        self.job_store.write_job(job)
        self.job_store.write_logs(
            "jobone",
            [
                '[08:00:01] GENOME_PROGRESS genome=fungus_id1 stage=antismash percent=70 bar=[##############------] message="antiSMASH rejected record NC_003424.3: overlapping exon coordinates in an annotated feature"',
                '[08:00:02] GENOME_PROGRESS genome=fungus_id1 stage=funbgcex percent=100 bar=[####################] message="FunBGCeX complete"',
            ],
        )

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genome = payload["genome_progress"][0]
        self.assertEqual(genome["status"], "complete_with_warning")
        self.assertEqual(genome["stage"], "complete")
        self.assertEqual(genome["tool"], "FunBGCeX")
        self.assertEqual(genome["message"], "FunBGCeX complete")
        self.assertEqual(genome["warning_tool"], "antiSMASH")
        self.assertIn("NC_003424.3", genome["warning_message"])
        self.assertEqual(genome["stage_states"]["genome_acquired"]["status"], "complete")
        self.assertEqual(genome["stage_states"]["antismash"]["status"], "failed")
        self.assertEqual(genome["stage_states"]["funbgcex"]["status"], "complete")
        self.assertEqual(genome["stage_states"]["complete"]["status"], "queued")
        self.assertTrue(genome["terminal"])


    def test_download_completion_is_waiting_until_genome_work_starts(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        job = self.job_store.read_job("jobone")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "download_complete",
                "taxon_group": "fungi",
                "source_accession": "GCA_000011425.1",
            },
            {
                "genome_id": "downloaded_alias",
                "taxon_group": "fungi",
                "source_accession": "GCA_030770425.1",
            },
            {
                "genome_id": "still_waiting",
                "taxon_group": "bacteria",
                "source_accession": "GCF_000005845.2",
            },
        ]
        self.job_store.write_job(job)
        self.job_store.write_logs(
            "jobone",
            [
                '[08:00:01] NCBI_DOWNLOAD_PROGRESS accession=GCA_000011425.1 taxon=fungi status=complete percent=8 message="NCBI genome download complete"',
                '[08:00:02] NCBI_DOWNLOAD_PROGRESS accession=GCA_030770425.1 taxon=fungi status=downloaded percent=8 message="Genome downloaded"',
                '[08:00:03] NCBI_DOWNLOAD_PROGRESS accession=GCF_000005845.2 taxon=bacteria status=completed percent=8 message="Download completed"',
                '[08:00:04] GENOME_PROGRESS genome=download_complete stage=annotation percent=25 bar=[#####---------------] message="Annotation fallback produced GenBank"',
                '[08:00:05] [INFO] TOOL_HEARTBEAT genome=downloaded_alias tool=antismash phase=detect elapsed=60s',
            ],
        )

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genomes = {row["genome_id"]: row for row in payload["genome_progress"]}
        self.assertEqual(genomes["download_complete"]["status"], "running")
        self.assertEqual(genomes["download_complete"]["stage"], "annotation")
        self.assertEqual(genomes["downloaded_alias"]["status"], "running")
        self.assertEqual(genomes["downloaded_alias"]["tool"], "antiSMASH")
        self.assertEqual(genomes["still_waiting"]["status"], "queued")
        self.assertEqual(genomes["still_waiting"]["stage"], "download")
        self.assertEqual(genomes["still_waiting"]["percent"], 8)
        self.assertEqual(genomes["still_waiting"]["message"], "NCBI genome downloaded | queued")
        self.assertFalse(genomes["still_waiting"]["terminal"])

    def test_genome_progress_exposes_effective_annotation_method_only_when_known(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        job = self.job_store.read_job("jobone")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "uploaded_existing",
                "taxon_group": "fungi",
                "taxon_source": "genbank_source",
                "prediction_method": "existing_cds",
            },
            {
                "genome_id": "uploaded_fasta",
                "taxon_group": "fungi",
                "taxon_source": "user_declaration",
                "prediction_method": "funannotate",
            },
            {
                "genome_id": "ncbi_pending",
                "taxon_group": "fungi",
                "taxon_source": "ncbi",
                "prediction_method": "funannotate",
            },
            {
                "genome_id": "ncbi_existing",
                "taxon_group": "fungi",
                "taxon_source": "ncbi",
                "prediction_method": "funannotate",
            },
            {
                "genome_id": "ncbi_fallback",
                "taxon_group": "fungi",
                "taxon_source": "ncbi",
                "prediction_method": "funannotate",
            },
        ]
        self.job_store.write_job(job)
        self.job_store.write_logs(
            "jobone",
            [
                '[08:00:01] GENOME_ANNOTATION_DECISION genome=ncbi_existing required=no method=existing_cds message="Complete CDS translations already available"',
                '[08:00:02] TOOL_PROGRESS genome=ncbi_existing tool=antismash phase=detect message="Running whole-genome PFAM search"',
                '[08:00:03] GENOME_ANNOTATION_DECISION genome=ncbi_fallback required=yes method=funannotate message="Funannotate annotation required"',
                '[08:00:04] TOOL_PROGRESS genome=ncbi_fallback tool=funannotate phase=predict message="Predicting genes"',
            ],
        )

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genomes = {row["genome_id"]: row for row in payload["genome_progress"]}
        self.assertEqual(genomes["uploaded_existing"]["annotation_method"], "existing_cds")
        self.assertEqual(genomes["uploaded_fasta"]["annotation_method"], "funannotate")
        self.assertEqual(genomes["ncbi_pending"]["annotation_method"], "")
        self.assertEqual(genomes["ncbi_existing"]["annotation_method"], "existing_cds")
        self.assertEqual(genomes["ncbi_existing"]["stage"], "antismash")
        self.assertEqual(genomes["ncbi_fallback"]["annotation_method"], "funannotate")
        self.assertEqual(genomes["ncbi_fallback"]["stage"], "funannotate")

    def test_genome_progress_resets_terminal_warning_on_rerun(self) -> None:
        self.write_job("jobone", "read-one", status="success")
        job = self.job_store.read_job("jobone")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "Rhizopus_stolonifer_PRFJ01",
                "taxon_group": "fungi",
                "source_accession": "GCA_030770425.1",
            }
        ]
        self.job_store.write_job(job)
        logs = [
            '[08:00:01] GENOME_PROGRESS genome=Rhizopus_stolonifer_PRFJ01 stage=annotation percent=100 bar=[####################] message="Dropped: funannotate_busco_training_insufficient /data/jobs/jobone/private"',
        ]
        logs.extend(f"[08:01:{index % 60:02d}] Old downstream event {index}" for index in range(45))
        logs.extend(
            [
                '[09:00:01] GENOME_PROGRESS genome=Rhizopus_stolonifer_PRFJ01 stage=annotation percent=0 bar=[--------------------] message="Starting annotation and BGC prediction"',
                '[09:00:02] GENOME_PROGRESS genome=Rhizopus_stolonifer_PRFJ01 stage=annotation percent=25 bar=[#####---------------] message="Annotation fallback produced GenBank"',
                '[09:00:03] GENOME_PROGRESS genome=Rhizopus_stolonifer_PRFJ01 stage=funbgcex percent=100 bar=[####################] message="FunBGCeX complete"',
            ]
        )
        self.job_store.write_logs("jobone", logs)

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        genome = payload["genome_progress"][0]
        self.assertEqual(genome["status"], "complete")
        self.assertEqual(genome["percent"], 100)
        self.assertEqual(genome["stage"], "complete")
        self.assertEqual(genome["message"], "FunBGCeX complete")
        self.assertTrue(genome["terminal"])

    def test_live_job_status_payload_skips_result_index_hydration(self) -> None:
        self.write_job("livejob", "read-live", status="running")
        job = self.job_store.read_job("livejob")
        assert job is not None
        job["result_files"] = ["data/results/demo/figures/partial.svg"]
        with mock.patch.object(
            self.app,
            "result_file_allowlist",
            side_effect=AssertionError("live status poll must not hydrate results"),
        ):
            payload = self.app.job_payload(
                job, admin=True, include_public_events=True
            )
            job["status"] = "success"
            compact_payload = self.app.job_payload(
                job, admin=True, include_public_events=True, include_results=False
            )
        self.assertEqual(payload["result_files"], [])
        self.assertEqual(compact_payload["result_files"], [])

    def test_admin_compact_metadata_preserves_legacy_result_identity_without_hydration(self) -> None:
        job_id = "legacycompact"
        self.write_job(job_id, "read-legacy-compact", status="success")
        job = self.job_store.read_job(job_id)
        assert job is not None
        self.assertNotIn("public_run_id", job)
        expected_public_id = self.app.public_run_id_for_job(job)

        with mock.patch.object(
            self.app,
            "result_file_allowlist",
            side_effect=AssertionError("compact metadata must not hydrate results"),
        ):
            status, listed_jobs, _ = self.request(
                "GET", "/api/jobs", headers=self.auth("admin-secret")
            )
            self.assertEqual(status, 200)
            listed = next(item for item in listed_jobs if item["id"] == job_id)

            status, compact, _ = self.request(
                "GET",
                f"/api/jobs/{job_id}?compact=1",
                headers=self.auth("admin-secret"),
            )
            self.assertEqual(status, 200)

        for payload in (listed, compact):
            self.assertEqual(payload["public_run_id"], expected_public_id)
            self.assertRegex(payload["public_run_id"], r"^[A-Za-z0-9_-]{22}$")
            self.assertEqual(payload["result_file_count"], 1)
        self.assertNotIn("result_files", listed)
        self.assertEqual(compact["result_files"], [])

    def test_250k_tool_log_projection_is_fast_incremental_and_semantically_complete(self) -> None:
        self.write_job("longjob", "read-long", status="running")
        job = self.job_store.read_job("longjob")
        assert job is not None
        job["taxon_routes"] = [
            {
                "genome_id": "rerun_fungus",
                "taxon_group": "fungi",
                "source_accession": "GCA_000011425.1",
            },
            {
                "genome_id": "completed_bacterium",
                "taxon_group": "bacteria",
                "source_accession": "GCF_000005845.2",
            },
            {
                "genome_id": "still_queued",
                "taxon_group": "fungi",
                "source_accession": "GCA_030770425.1",
            },
        ]
        markers = [
            '[08:00:00] TOOL_RAW genome=completed_bacterium tool=antismash stream=stderr Running whole-genome PFAM search',
            '[08:00:01] GENOME_PROGRESS genome=rerun_fungus stage=annotation percent=100 bar=[####################] message="Dropped: old private failure /data/jobs/longjob/private"',
            '[08:00:02] GENOME_PROGRESS genome=completed_bacterium stage=antismash percent=100 bar=[####################] message="antiSMASH complete"',
            '[09:00:01] GENOME_PROGRESS genome=rerun_fungus stage=annotation percent=0 bar=[--------------------] message="Starting annotation and BGC prediction"',
            '[09:00:02] GENOME_PROGRESS genome=rerun_fungus stage=annotation percent=25 bar=[#####---------------] message="Predicting genes"',
        ]
        noise = (
            "[08:30:00] TOOL_RAW genome=rerun_fungus tool=antismash "
            "stream=stderr routine-shard-diagnostic\n"
        )
        noise_count = 250_000 - len(markers)
        path = self.job_store.job_logs_path("longjob")
        path.write_text(
            "\n".join(markers[:3])
            + "\n"
            + noise * noise_count
            + "\n".join(markers[3:])
            + "\n",
            encoding="utf-8",
        )
        job["log_count"] = 250_000
        self.job_store.write_job(job)

        started = time.perf_counter()
        cold = self.app.job_payload(job, admin=False, include_public_events=True)
        cold_seconds = time.perf_counter() - started
        started = time.perf_counter()
        warm = self.app.job_payload(job, admin=False, include_public_events=True)
        warm_seconds = time.perf_counter() - started

        self.assertEqual(cold["public_events"], warm["public_events"])
        self.assertEqual(cold["genome_progress"], warm["genome_progress"])
        genomes = {row["genome_id"]: row for row in cold["genome_progress"]}
        self.assertEqual(genomes["rerun_fungus"]["status"], "running")
        self.assertEqual(genomes["rerun_fungus"]["percent"], 25)
        self.assertEqual(genomes["completed_bacterium"]["status"], "complete")
        self.assertEqual(genomes["still_queued"]["status"], "queued")
        rendered = json.dumps(cold)
        self.assertIn("Running whole-genome PFAM search", rendered)
        self.assertNotIn("routine-shard-diagnostic", rendered)
        self.assertNotIn("/data/jobs", rendered)
        self.assertLess(cold_seconds, 4.0, f"cold 250k-line projection took {cold_seconds:.3f}s")
        self.assertLess(warm_seconds, 0.25, f"warm 250k-line payload took {warm_seconds:.3f}s")

        appended = self.job_store.append_log(
            "longjob",
            'TOOL_HEARTBEAT genome=rerun_fungus tool=antismash phase=detect elapsed=60s',
        )
        started = time.perf_counter()
        incremental = self.app.job_payload(job, admin=False, include_public_events=True)
        incremental_seconds = time.perf_counter() - started
        self.assertLess(incremental_seconds, 0.25)
        self.assertIn("antiSMASH still running", json.dumps(incremental["public_events"]))

        status, admin_logs, _ = self.request(
            "GET", "/api/jobs/longjob/logs?since=250000", headers=self.auth("admin-secret")
        )
        self.assertEqual(status, 200)
        self.assertEqual(admin_logs["total"], 250_001)
        self.assertEqual(admin_logs["lines"], [appended])
        status, tail, _ = self.request(
            "GET", "/api/jobs/longjob/logs?tail=500", headers=self.auth("admin-secret")
        )
        self.assertEqual(status, 200)
        self.assertEqual(500, len(tail["lines"]))
        self.assertEqual((249_501, 250_001), (tail["start"], tail["end"]))
        self.assertTrue(tail["has_earlier"])
        self.assertEqual(appended, tail["lines"][-1])

        status, earlier, _ = self.request(
            "GET",
            f"/api/jobs/longjob/logs?before={tail['start']}&limit=500",
            headers=self.auth("admin-secret"),
        )
        self.assertEqual(status, 200)
        self.assertEqual((249_001, 249_501), (earlier["start"], earlier["end"]))
        self.assertEqual(500, len(earlier["lines"]))
        self.assertEqual(tail["generation"], earlier["generation"])

        with mock.patch.object(
            self.app,
            "public_activity_projection_lines",
            side_effect=AssertionError("admin metadata must not hydrate logs"),
        ):
            status, selected, _ = self.request(
                "GET", "/api/jobs/longjob", headers=self.auth("admin-secret")
            )
        self.assertEqual(status, 200)
        self.assertNotIn("public_events", selected)

    def test_public_projection_returns_a_snapshot_copy(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        self.job_store.write_logs(
            "jobone",
            [
                '[08:00:01] GENOME_PROGRESS genome=fungus_id1 stage=annotation percent=25 bar=[#####---------------] message="Predicting genes"',
            ],
        )
        first = self.app.public_activity_projection_lines("jobone")
        first.append("caller mutation")
        second = self.app.public_activity_projection_lines("jobone")
        self.assertNotIn("caller mutation", second)

    def test_public_tool_progress_redacts_credential_shaped_messages(self) -> None:
        self.write_job("jobone", "read-one", status="running")
        self.job_store.write_logs(
            "jobone",
            [
                '[08:04:23] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="Bearer fake-bearer-value"',
                '[08:04:24] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="https://example.invalid/run?token=fake-query-value"',
                '[08:04:25] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="SMTP_PASSWORD=fake-smtp-value"',
                '[08:04:26] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="/data/jobs/jobone/private/input.fna"',
                '[08:04:27] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="Authorization: Basic fake-basic-value"',
                '[08:04:28] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="Cookie: session=fake-cookie-value"',
                '[08:04:29] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="https://example.invalid/object?x-amz-signature=fake-signature-value"',
                '[08:04:30] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="input=/data/jobs/jobone/private/input.fna"',
                '[08:04:31] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="input=C:/' + '/'.join(("Users", "tester", "input.fna")) + '"',
                '[08:04:32] [INFO] TOOL_PROGRESS genome=fungus_id1 tool=antismash phase=detect message="file:///data/jobs/jobone/private/input.fna"',
            ],
        )

        status, payload, _ = self.request(
            "GET", "/api/jobs/jobone", headers=self.auth("read-one")
        )
        self.assertEqual(status, 200)
        rendered = json.dumps(payload["public_events"])
        self.assertIn("antiSMASH: Running", rendered)
        for secret_marker in [
            "fake-bearer-value",
            "fake-query-value",
            "fake-smtp-value",
            "SMTP_PASSWORD",
            "/data/jobs",
            "fake-basic-value",
            "fake-cookie-value",
            "fake-signature-value",
            "C:/Users",
        ]:
            self.assertNotIn(secret_marker, rendered)

    def test_content_disposition_strips_header_control_characters(self) -> None:
        header = self.app.content_disposition(
            "attachment\r\nX-Injected: yes",
            "tree.svg\r\nX-Injected: yes",
        )
        self.assertTrue(header.startswith("attachment;"))
        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
        self.assertNotIn("X-Injected:", header)

    def test_sqlite_result_mime_is_deterministic_across_runtime_images(self) -> None:
        self.assertEqual(
            self.app.result_file_mime(Path("clusterweave_public.sqlite")),
            "application/vnd.sqlite3",
        )

    def test_file_stream_treats_client_disconnect_as_normal_completion(self) -> None:
        target = Path(self.tmp.name) / "bounded-result.bin"
        target.write_bytes(b"clusterweave-stream")

        for error_type in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            with self.subTest(error_type=error_type.__name__):
                handler = object.__new__(self.app.Handler)
                handler.wfile = mock.Mock()
                handler.wfile.write.side_effect = error_type("client disconnected")
                handler.send_response = mock.Mock()
                handler.send_header = mock.Mock()
                handler.end_headers = mock.Mock()
                handler._send_cors_headers = mock.Mock()

                handler._send_file(200, target, "application/octet-stream")

                handler.send_response.assert_called_once_with(200)
                handler.wfile.write.assert_called_once()

    def test_invalid_job_ids_cannot_escape_job_root(self) -> None:
        for job_id in ["..", ".", "../outside", "job/child", "job%2fchild", ""]:
            with self.subTest(job_id=job_id):
                self.assertFalse(self.job_store.valid_job_id(job_id))
                with self.assertRaises(ValueError):
                    self.job_store.job_dir(job_id)
                self.assertIsNone(self.job_store.read_job(job_id))

        status, _, _ = self.request(
            "GET", "/api/jobs/%2e%2e", headers=self.auth("admin-secret")
        )
        self.assertEqual(status, 404)

    def test_http_access_log_redacts_query_credentials(self) -> None:
        captured = io.StringIO()
        with redirect_stderr(captured):
            status, _, _ = self.request(
                "GET", "/api/system/status?token=fake-access-log-value"
            )
            signed_status, _, _ = self.request(
                "GET",
                "/api/system/status?Policy=fake-policy-value&X-Amz-Security-Token=fake-security-token-value&Signature=fake-signature-value",
            )
        self.assertEqual(status, 200)
        self.assertEqual(signed_status, 200)
        rendered = captured.getvalue()
        self.assertIn("token=[redacted]", rendered)
        self.assertIn("?[signed-query-redacted]", rendered)
        self.assertNotIn("fake-access-log-value", rendered)
        self.assertNotIn("fake-policy-value", rendered)
        self.assertNotIn("fake-security-token-value", rendered)
        self.assertNotIn("fake-signature-value", rendered)
        status, _, _ = self.request(
            "DELETE", "/api/jobs/%2e%2e", headers=self.auth("admin-secret")
        )
        self.assertEqual(status, 404)


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
        public_id = self.app.public_run_id_for_job(updated)
        self.assertIn(f"https://clusterweave.example.org/app/#/results/{public_id}/", body)
        self.assertIn("You can review logs and any partial results at", body)
        self.assertIn(f"The ClusterWeave job {public_id} you submitted", body)
        self.assertIn("Result access code:", body)
        self.assertIn("Suggested fixes:", body)
        self.assertNotIn("/data/jobs", body)
        self.assertNotIn("SECRET_TOKEN", body)
        self.assertNotIn("Traceback", body)
        self.assertNotIn("command --bad", body)
        link = next(line for line in body.splitlines() if f"#/results/{public_id}/" in line)
        email_token = link.rsplit("/", 1)[-1]
        status, payload, _ = self.request("GET", f"/api/results/{public_id}", headers=self.auth(email_token))
        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], public_id)

    def test_success_notification_email_is_concise_result_message(self) -> None:
        job = {
            "id": "donejob",
            "status": "success",
            "project_name": "done-project",
            "created_at": "2026-06-28T01:03:29",
            "expires_at": "2026-07-28T01:03:29",
            "retention_days": 30,
            "notify_email": "user@example.org",
            "input_summary": {"accession_count": 2, "genome_file_count": 1},
        }
        message = self.notifications.build_job_email(job, "https://clusterweave.example.org/#/results/donejob/read", "read")
        public_id = self.app.public_run_id_for_job(job)
        body = message.get_content()
        self.assertEqual(message["Subject"], f"ClusterWeave job {public_id} finished: complete")
        self.assertIn("Dear ClusterWeave user,", body)
        self.assertIn(f"The ClusterWeave job {public_id} you submitted on 2026-06-28 01:03:29", body)
        self.assertIn("for project 'done-project' with 2 NCBI accessions and 1 uploaded genome file", body)
        self.assertIn("has finished with status complete.", body)
        self.assertIn("You can find the results at", body)
        self.assertIn("https://clusterweave.example.org/#/results/donejob/read", body)
        self.assertIn("Result access code: read", body)
        self.assertIn("Results will be kept for one month and then deleted automatically on 2026-07-28 01:03:29.", body)
        self.assertIn("https://github.com/n2mology/clusterweave", body)
        self.assertIn("If you found ClusterWeave useful", body)
        self.assertNotIn("Workflow summary:", body)
        self.assertNotIn("Input summary:", body)

    def test_smtp_ssl_uses_implicit_tls_without_starttls(self) -> None:
        os.environ["CLUSTERWEAVE_SMTP_ENABLED"] = "1"
        os.environ["CLUSTERWEAVE_SMTP_HOST"] = "smtp.example.org"
        os.environ["CLUSTERWEAVE_SMTP_PORT"] = "465"
        os.environ["CLUSTERWEAVE_SMTP_USERNAME"] = "smtp-user"
        os.environ["CLUSTERWEAVE_SMTP_PASSWORD"] = "smtp-pass"
        os.environ["CLUSTERWEAVE_SMTP_TLS"] = "1"
        os.environ["CLUSTERWEAVE_SMTP_SSL"] = "1"
        os.environ["CLUSTERWEAVE_SMTP_OUTBOX_DIR"] = ""
        job = {
            "id": "ssljob",
            "status": "success",
            "project_name": "ssl-project",
            "notify_email": "user@example.org",
            "retention_days": 30,
        }
        message = self.notifications.build_job_email(job, "https://clusterweave.example.org/#/results/ssljob/read", "read")
        connection = mock.MagicMock()
        smtp_context = mock.MagicMock()
        smtp_context.__enter__.return_value = connection
        with mock.patch.object(self.notifications.smtplib, "SMTP_SSL", return_value=smtp_context) as smtp_ssl, \
             mock.patch.object(self.notifications.smtplib, "SMTP") as smtp_plain:
            self.notifications.deliver_email(message)

        smtp_ssl.assert_called_once_with("smtp.example.org", 465, timeout=10.0)
        smtp_plain.assert_not_called()
        connection.starttls.assert_not_called()
        connection.login.assert_called_once_with("smtp-user", "smtp-pass")
        connection.send_message.assert_called_once_with(message)

    def test_admin_token_unlocks_job_list_status_rerun_and_delete(self) -> None:
        self.write_job("jobone", "read-one")

        status, payload, _ = self.request("GET", "/api/jobs", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["id"], "jobone")
        self.assertNotIn("read_token_hash", payload[0])
        self.assertEqual({"run_summary": True}, payload[0]["rerun_stage_settings"])
        self.assertNotIn("submission_settings", payload[0])
        self.assertNotIn("env_overrides", json.dumps(payload[0]))

        status, access, _ = self.request("GET", "/api/access/validate", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertTrue(access["admin"])
        self.assertTrue(access["submit"])

        status, payload, _ = self.request("GET", "/api/system/status", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertIn("runtime", payload)
        self.assertIn("capabilities", payload)
        self.assertIn("jobs_processed", payload)
        self.assertIn("running_jobs", payload)
        self.assertIn("queued_jobs", payload)

        rerun_body = json.dumps({"run_summary": True, "cpus": 1}).encode("utf-8")
        headers = {"Content-Type": "application/json", **self.auth("admin-secret")}
        status, payload, _ = self.request("POST", "/api/jobs/jobone/rerun", body=rerun_body, headers=headers)
        self.assertEqual(status, 202)
        self.assertEqual(payload["status"], "pending")

        status, _, _ = self.request("DELETE", "/api/jobs/jobone", headers=self.auth("admin-secret"))
        self.assertEqual(status, 204)
        self.assertIsNone(self.job_store.read_job("jobone"))

    def test_worker_status_normalizes_naive_and_timezone_aware_timestamps(self) -> None:
        worker_status_path = Path(self.tmp.name) / "worker" / "status.json"
        cases = [
            ("fresh naive", datetime.now().isoformat(), False, True),
            ("stale naive", "2000-01-01T00:00:00", True, False),
            (
                "fresh UTC Z",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                False,
                True,
            ),
            ("stale UTC Z", "2000-01-01T00:00:00Z", True, False),
        ]

        for label, updated_at, expected_stale, expected_ready in cases:
            with self.subTest(label=label):
                payload = {
                    "ready": True,
                    "state": "idle",
                    "phase": "idle",
                    "progress": 100,
                    "detail": "Ready for tests",
                    "substep": "",
                    "updated_at": updated_at,
                    "runtime": {"mode": "test"},
                    "worker": {"active_jobs": [], "active_count": 0},
                    "capabilities": {},
                }
                worker_status_path.write_text(json.dumps(payload), encoding="utf-8")

                status, response, _ = self.request(
                    "GET", "/api/system/status", headers=self.auth("admin-secret")
                )

                self.assertEqual(status, 200)
                self.assertEqual(response["updated_at"], updated_at)
                self.assertIs(response["stale"], expected_stale)
                self.assertIs(response["ready"], expected_ready)

    def test_hash_only_admin_credential_accepts_raw_candidate_and_rejects_wrong(self) -> None:
        raw_admin_token = "hash-only-admin-secret"
        os.environ.pop("CLUSTERWEAVE_ADMIN_TOKEN", None)
        os.environ["CLUSTERWEAVE_ADMIN_TOKEN_SHA256"] = hashlib.sha256(
            raw_admin_token.encode("utf-8")
        ).hexdigest()
        self.app.ADMIN_TOKEN = os.environ.get("CLUSTERWEAVE_ADMIN_TOKEN", "")
        self.app.ADMIN_TOKEN_SHA256 = os.environ["CLUSTERWEAVE_ADMIN_TOKEN_SHA256"]

        self.assertEqual(self.app.ADMIN_TOKEN, "")
        self.assertNotIn("CLUSTERWEAVE_ADMIN_TOKEN_HASH", os.environ)
        status, access, _ = self.request(
            "GET", "/api/access/validate", headers=self.auth(raw_admin_token)
        )
        self.assertEqual(status, 200)
        self.assertTrue(access["admin"])
        self.assertTrue(access["submit"])

        status, payload, _ = self.request(
            "GET", "/api/access/validate", headers=self.auth("wrong-admin-secret")
        )
        self.assertEqual(status, 403)
        self.assertIn("not accepted", payload["detail"])

    def test_admin_delete_running_job_requests_cancellation_before_removal(self) -> None:
        self.write_job("activejob", "read-active", status="running")

        status, payload, _ = self.request("DELETE", "/api/jobs/activejob", headers=self.auth("admin-secret"))

        self.assertEqual(status, 202)
        self.assertEqual(payload["status"], "cancel_requested")
        self.assertIsNotNone(self.job_store.read_job("activejob"))
        self.assertTrue(self.job_store.job_cancel_requested("activejob"))
        self.assertTrue(self.job_store.job_delete_path("activejob").exists())
        logs = self.job_store.read_logs("activejob")
        self.assertTrue(any("stopping active workflow" in line for line in logs))

    def test_rerun_preserves_partial_public_outputs_and_resume_settings(self) -> None:
        created = self.job_store.now_iso()
        result_files = [
            "downloads/demo_public_results.zip",
            "downloads/public_results_manifest.tsv",
            "data/results/demo/antismash/genome_a/index.html",
            "data/results/demo/antismash/genome_a/style.css",
            "data/results/demo/antismash/genome_a/region001.gbk",
            "data/results/demo/funbgcex/genome_a/index.html",
            "data/results/demo/funbgcex/genome_a/raw.tsv",
            "data/results/demo/big_scape/output_files/index.html",
            "data/results/demo/big_scape/output_files/data_sqlite.db",
            "data/results/demo/big_scape/output_files/network.gml",
            "data/results/demo/clinker/panels/atlas/choline/panel.html",
            "data/results/demo/clinker/panels/atlas/choline/panel.js",
            "data/results/demo/clinker/panels/atlas/choline/deleted.html",
            "data/results/demo/clinker/panels/atlas/choline/panel_manifest.tsv",
            "data/results/demo/figures/bgc_overlap.svg",
            "data/results/demo/summary/family_atlas_shortlist.tsv",
        ]
        job = {
            "id": "partialjob",
            "name": "partial-demo",
            "status": "failed",
            "stage": "Staging synteny panels",
            "created_at": created,
            "updated_at": created,
            "log_count": 2,
            "result_files": result_files,
            "error": "clinker failed with exit code 1",
            "cpus": 2,
            "project_name": "demo",
            "settings": {
                "run_genome_prep": True,
                "run_annotation": True,
                "run_bigscape": True,
                "run_summary": True,
                "run_clinker": True,
                "run_figures": True,
            },
            "submission_settings": {
                "run_genome_prep": True,
                "run_annotation": True,
                "run_bigscape": True,
                "run_summary": True,
                "run_clinker": True,
                "run_figures": True,
                "env_overrides": "SECRET_TOKEN=1",
            },
            "read_token_hash": self.app.job_token_hash("read-partial"),
            "read_token_created_at": created,
        }
        self.job_store.write_job(job)
        for rel_path in result_files:
            if rel_path.endswith("/") or rel_path.endswith("/deleted.html"):
                continue
            target = self.job_store.job_dir("partialjob") / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("partial output\n", encoding="utf-8")
        partial_digest = hashlib.sha256(b"partial output\n").hexdigest()
        manifest_rows = [
            "path\tbytes\tsha256",
            f"data/results/demo/antismash/genome_a/index.html\t15\t{partial_digest}",
            f"data/results/demo/antismash/genome_a/style.css\t15\t{partial_digest}",
            f"data/results/demo/funbgcex/genome_a/index.html\t15\t{partial_digest}",
            f"data/results/demo/big_scape/output_files/index.html\t15\t{partial_digest}",
            f"data/results/demo/clinker/panels/atlas/choline/panel.html\t15\t{partial_digest}",
            f"data/results/demo/clinker/panels/atlas/choline/panel.js\t15\t{partial_digest}",
            f"data/results/demo/figures/bgc_overlap.svg\t15\t{partial_digest}",
            f"data/results/demo/summary/family_atlas_shortlist.tsv\t15\t{partial_digest}",
        ]
        (self.job_store.job_dir("partialjob") / "downloads" / "public_results_manifest.tsv").write_text(
            "\n".join(manifest_rows) + "\n",
            encoding="utf-8",
        )
        self.job_store.append_log("partialjob", "Reusing existing staged ClusterWeave layout for rerun.")
        self.job_store.append_log("partialjob", "Stage 4/4: running run_clinker.sh")
        importlib.import_module("result_attestation").write_result_attestation(
            self.job_store.job_dir("partialjob"),
            "partialjob",
            verify_hashes=True,
            path_validator=lambda path: self.app.result_file_is_publicly_servable(
                self.job_store.job_dir("partialjob"), path
            ),
        )

        public_id, artifacts = self.public_artifact_catalog(
            "partialjob", "read-partial"
        )
        published = [
            (artifact["category"], artifact["filename"])
            for artifact in artifacts
        ]
        self.assertIn(("antismash", "index.html"), published)
        self.assertIn(("funbgcex", "index.html"), published)
        self.assertIn(("bigscape", "index.html"), published)
        self.assertIn(("synteny", "panel.html"), published)
        self.assertEqual(
            next(artifact["label"] for artifact in artifacts if artifact["category"] == "synteny"),
            "choline",
        )
        self.assertIn(("figures", "bgc_overlap.svg"), published)
        self.assertIn(("summaries", "family_atlas_shortlist.tsv"), published)
        self.assertTrue(
            {
                "data_sqlite.db",
                "deleted.html",
                "region001.gbk",
                "raw.tsv",
                "network.gml",
                "panel_manifest.tsv",
            }.isdisjoint({str(artifact["filename"]) for artifact in artifacts})
        )
        artifact_ids = {str(artifact["id"]) for artifact in artifacts}

        rerun_body = json.dumps({"run_clinker": True, "run_figures": True, "cpus": 1}).encode("utf-8")
        headers = {"Content-Type": "application/json", **self.auth("admin-secret")}
        status, rerun_payload, _ = self.request("POST", "/api/jobs/partialjob/rerun", body=rerun_body, headers=headers)
        self.assertEqual(status, 202)
        self.assertEqual(rerun_payload["status"], "pending")

        stored = self.job_store.read_job("partialjob")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["status"], "pending")
        self.assertEqual(stored["stage"], "queued")
        self.assertEqual(stored["result_files"], result_files)
        self.assertEqual(stored["submission_settings"], job["submission_settings"])
        self.assertTrue(stored["last_rerun_settings"]["reuse_existing_layout"])
        self.assertTrue(stored["last_rerun_settings"]["run_clinker"])
        self.assertTrue(stored["last_rerun_settings"]["execute_clinker"])
        self.assertTrue(stored["last_rerun_settings"]["run_figures"])
        self.assertFalse(stored["last_rerun_settings"]["run_annotation"])
        self.assertFalse(stored["last_rerun_settings"]["run_bigscape"])
        self.assertFalse(stored["last_rerun_settings"]["run_summary"])
        self.assertEqual(stored["rerun_count"], 1)

        queue_payload = json.loads((Path(self.tmp.name) / "queue" / "partialjob.json").read_text(encoding="utf-8"))
        self.assertEqual(queue_payload["job_id"], "partialjob")
        self.assertTrue(queue_payload["settings"]["reuse_existing_layout"])
        self.assertTrue(queue_payload["settings"]["run_clinker"])
        self.assertTrue(queue_payload["settings"]["execute_clinker"])
        self.assertTrue(queue_payload["settings"]["run_figures"])
        self.assertFalse(queue_payload["settings"]["run_annotation"])
        self.assertFalse(queue_payload["settings"]["run_bigscape"])
        self.assertFalse(queue_payload["settings"]["run_summary"])

        status, pending_files, _ = self.request(
            "GET",
            f"/api/results/{public_id}/artifacts",
            headers=self.auth("read-partial"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            {str(artifact["id"]) for artifact in pending_files["artifacts"]},
            artifact_ids,
        )

    def test_nested_tool_html_bundle_headers_and_access_boundaries(self) -> None:
        root = self.job_store.job_dir("bundlejob")
        prefix = "data/results/demo"
        files = {
            f"{prefix}/antismash/genome_a/index.html": b"<!doctype html><title>antiSMASH</title>",
            f"{prefix}/antismash/genome_a/css/main.css": b"body { color: #123; }\n",
            f"{prefix}/antismash/genome_a/js/app.js": b"window.bundleReady = true;\n",
            f"{prefix}/antismash/genome_a/knownclusterblast/region1/hit.html": b"<!doctype html><title>hit</title>",
            f"{prefix}/funbgcex/genome_a/allBGCs.html": b"<!doctype html><a href='results/x/HTMLs/BGC1.html'>BGC1</a>",
            f"{prefix}/funbgcex/genome_a/results/x/HTMLs/BGC1.html": b"<!doctype html><title>BGC1</title>",
            f"{prefix}/antismash/genome_a/private.sqlite": b"SQLite format 3\x00private",
            f"{prefix}/antismash/genome_a/genome_a.antismash.json": b"{\"records\":[]}",
        }
        for rel_path, content in files.items():
            target = root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        public_paths = [
            rel_path for rel_path in files
            if not rel_path.endswith(("private.sqlite", ".antismash.json"))
        ]
        self.write_public_manifest_job("bundlejob", "read-bundle", public_paths)
        self.write_public_manifest_job("otherjob", "read-other", [])

        root_html = f"{prefix}/antismash/genome_a/index.html"
        nested_html = f"{prefix}/antismash/genome_a/knownclusterblast/region1/hit.html"
        funbgcex_html = f"{prefix}/funbgcex/genome_a/results/x/HTMLs/BGC1.html"
        public_id, artifacts = self.public_artifact_catalog(
            "bundlejob", "read-bundle"
        )
        anti_root = self.find_public_artifact(
            artifacts,
            filename="index.html",
            category="antismash",
            role="index",
        )
        fun_root = self.find_public_artifact(
            artifacts,
            filename="allBGCs.html",
            category="funbgcex",
            role="index",
        )
        self.assertEqual(
            {
                (artifact["category"], artifact["filename"])
                for artifact in artifacts
                if artifact["role"] != "manifest"
            },
            {("antismash", "index.html"), ("funbgcex", "allBGCs.html")},
        )

        anti_root_url = f"/api/results/{public_id}/artifacts/{anti_root['id']}"
        fun_root_url = f"/api/results/{public_id}/artifacts/{fun_root['id']}"
        for route in [anti_root_url, fun_root_url]:
            with self.subTest(route=route, role="anonymous"):
                status, payload, _ = self.request("GET", route)
                self.assertEqual(status, 404)
                self.assertEqual(payload["detail"], "Result not found")
            with self.subTest(route=route, role="wrong-read-token"):
                status, payload, _ = self.request(
                    "GET", route, headers=self.auth("read-other")
                )
                self.assertEqual(status, 404)
                self.assertEqual(payload["detail"], "Result not found")
            with self.subTest(route=route, role="read-token"):
                status, body, headers = self.request(
                    "GET", route, headers=self.auth("read-bundle")
                )
                self.assertEqual(status, 200)
                self.assertTrue(body.lower().startswith(b"<!doctype html>"))
                self.assertEqual(
                    headers.get("Content-Type"), "text/html; charset=utf-8"
                )
                self.assertTrue(
                    headers.get("Content-Disposition", "").startswith("inline;")
                )
                csp = headers.get("Content-Security-Policy", "")
                self.assertIn("sandbox", csp)
                self.assertNotIn("allow-same-origin", csp)
                self.assertEqual(headers.get("Cache-Control"), "private, no-store")
                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

        def resolve(owner: dict[str, object], reference: str, token: str):
            return self.request(
                "POST",
                f"/api/results/{public_id}/artifacts/{owner['id']}/resolve",
                body=json.dumps({"reference": reference}).encode("utf-8"),
                headers={"Content-Type": "application/json", **self.auth(token)},
            )

        resolved_cases = [
            (
                anti_root,
                "knownclusterblast/region1/hit.html#r1c1",
                nested_html,
                "hit.html",
                "#r1c1",
            ),
            (
                fun_root,
                "results/x/HTMLs/BGC1.html",
                funbgcex_html,
                "BGC1.html",
                "",
            ),
        ]
        for owner, reference, expected_path, filename, fragment in resolved_cases:
            with self.subTest(reference=reference):
                status, payload, _ = resolve(owner, reference, "read-bundle")
                self.assertEqual(status, 200)
                self.assertEqual(payload["fragment"], fragment)
                resolved = payload["artifact"]
                self.assertEqual(resolved["filename"], filename)
                self.assertEqual(resolved["kind"], "html")
                self.assertEqual(resolved["role"], "region" if filename == "BGC1.html" else "page")
                self.assertNotIn(expected_path, json.dumps(resolved))

                status, body, headers = self.request(
                    "GET",
                    f"/api/results/{public_id}/artifacts/{resolved['id']}",
                    headers=self.auth("read-bundle"),
                )
                self.assertEqual(status, 200)
                self.assertEqual(body, files[expected_path])
                self.assertEqual(
                    headers.get("Content-Type"), "text/html; charset=utf-8"
                )
                self.assertIn("sandbox", headers.get("Content-Security-Policy", ""))

                status, denied, _ = self.request(
                    "GET",
                    f"/api/results/{public_id}/artifacts/{resolved['id']}",
                    headers=self.auth("read-other"),
                )
                self.assertEqual(status, 404)
                self.assertEqual(denied["detail"], "Result not found")

        for reference, filename, mime in [
            ("css/main.css", "main.css", "text/css; charset=utf-8"),
            ("js/app.js", "app.js", "text/javascript; charset=utf-8"),
        ]:
            status, payload, _ = resolve(anti_root, reference, "read-bundle")
            self.assertEqual(status, 200)
            asset = payload["artifact"]
            self.assertEqual(asset["filename"], filename)
            status, body, headers = self.request(
                "GET",
                f"/api/results/{public_id}/artifacts/{asset['id']}",
                headers=self.auth("read-bundle"),
            )
            self.assertEqual(status, 200)
            self.assertEqual(body, files[f"{prefix}/antismash/genome_a/{reference}"])
            self.assertEqual(headers.get("Content-Type"), mime)
            self.assertNotIn("Content-Security-Policy", headers)

        for rel_path in [
            f"{prefix}/antismash/genome_a/private.sqlite",
            f"{prefix}/antismash/genome_a/genome_a.antismash.json",
            f"{prefix}/antismash/index.html",
        ]:
            with self.subTest(rel_path=rel_path, private=True):
                status, _, _ = self.request(
                    "GET", f"/api/jobs/bundlejob/files/{rel_path}",
                    headers=self.auth("admin-secret"),
                )
                self.assertEqual(status, 403)

        for reference in [
            "../genome_b/index.html",
            "../../funbgcex/genome_a/allBGCs.html",
            "/etc/passwd",
            "https://example.invalid/index.html",
            "..\\genome_b\\index.html",
        ]:
            with self.subTest(reference=reference, containment=True):
                status, payload, _ = resolve(anti_root, reference, "read-bundle")
                self.assertEqual(status, 404)
                self.assertEqual(payload["detail"], "Result not found")

        status, payload, _ = resolve(
            anti_root, "knownclusterblast/region1/hit.html", "read-other"
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Result not found")

    def test_public_deployment_smoke_role_matrix_and_result_file_access(self) -> None:
        self.write_job("smokeone", "read-one")

        status, payload, _ = self.request("GET", "/api/system/status")
        self.assertEqual(status, 200)
        self.assertEqual(
            set(payload),
            {"online", "service", "submissions_open", "submissions", "jobs_processed", "running_jobs", "queued_jobs", "smtp_enabled", "public_quota"},
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
                expected = 401 if path == "/api/jobs" else 404
                self.assertEqual(status, expected)

        status, submitted, _ = self.submit(
            fields={"project_name": "smoke-submit", "cpus": "1"},
            files=[("files", "accessions.txt", b"GCA_000011425.1\n")],
        )
        self.assertEqual(status, 201)
        submitted_public_id = submitted["job_id"]
        submitted_read_token = submitted["read_token"]
        self.assertTrue(submitted_read_token)
        stored = self.read_submitted_job(submitted)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["status"], "pending")
        submitted_internal_id = str(stored["id"])
        self.assertNotIn("read_token", stored)
        self.assertIn("read_token_hash", stored)

        status, _, _ = self.request("GET", "/api/jobs", headers=self.auth("submit-secret"))
        self.assertEqual(status, 403)

        status, own_job, _ = self.request("GET", f"/api/results/{submitted_public_id}", headers=self.auth(submitted_read_token))
        self.assertEqual(status, 200)
        self.assertEqual(own_job["id"], submitted_public_id)

        status, _, _ = self.request("GET", "/api/jobs/smokeone", headers=self.auth(submitted_read_token))
        self.assertEqual(status, 404)

        status, _, _ = self.request("GET", "/api/jobs/smokeone/files", headers=self.auth("read-one"))
        self.assertEqual(status, 404)

        status, body, headers = self.request("GET", "/api/jobs/smokeone/files/results/figure.svg", headers=self.auth("read-one"))
        self.assertEqual(status, 404)

        status, _, headers = self.request(
            "GET",
            "/api/jobs/smokeone/files/results/figure.svg?download=1",
            headers=self.auth("read-one"),
        )
        self.assertEqual(status, 404)

        status, admin_status, _ = self.request("GET", "/api/system/status", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertIn("runtime", admin_status)
        self.assertIn("worker", admin_status)
        self.assertIn("jobs_processed", admin_status)
        self.assertIn("running_jobs", admin_status)
        self.assertIn("queued_jobs", admin_status)

        status, jobs, _ = self.request("GET", "/api/jobs", headers=self.auth("admin-secret"))
        self.assertEqual(status, 200)
        self.assertGreaterEqual({job["id"] for job in jobs}, {"smokeone", submitted_internal_id})

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
            ("table.csv", b"accession\nGCA_000011425.1\n"),
            ("table.tsv", b"accession\nGCA_000011425.1\n"),
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
                self.assertEqual(
                    list((Path(self.tmp.name) / ".upload_staging").glob("upload-*")),
                    [],
                )

    def test_multipart_parser_stages_file_bodies_on_disk_and_cleans_them(self) -> None:
        content = b">contig-one\n" + (b"ACGT" * (self.app.UPLOAD_COPY_CHUNK_BYTES // 2)) + b"\n"
        body, content_type = self.multipart_body(
            {"project_name": "disk-backed"},
            [("files", "disk-backed.fna", content)],
        )

        fields, files = self.app.parse_multipart_form_data(
            content_type,
            io.BytesIO(body),
            content_length=len(body),
        )
        self.assertEqual(fields["project_name"], ["disk-backed"])
        self.assertEqual(len(files), 1)
        item = files[0]
        self.assertNotIn("content", item)
        self.assertEqual(item["size"], len(content))
        staged = Path(str(item["staged_path"]))
        self.assertTrue(staged.is_file())
        self.assertEqual(staged.stat().st_size, len(content))
        with self.app.open_upload_binary(item) as handle:
            self.assertEqual(handle.read(16), content[:16])

        self.app.cleanup_staged_uploads(files)
        self.assertFalse(staged.exists())

    def test_accepted_submission_moves_staged_upload_and_leaves_no_temp_file(self) -> None:
        content = b">contig-one\nACGTACGTACGT\n"
        status, payload, _ = self.submit(
            fields={"project_name": "staged-submit"},
            files=[("files", "staged-submit.fna", content)],
        )

        self.assertEqual(status, 201)
        saved = (
            self.job_store.job_dir(self.submitted_internal_job_id(payload))
            / "inputs"
            / "staged-submit.fna"
        )
        self.assertEqual(saved.read_bytes(), content)
        staging_dir = Path(self.tmp.name) / ".upload_staging"
        self.assertEqual(list(staging_dir.glob("upload-*")), [])

    def test_public_genome_content_checker_rejects_bad_fasta_before_job_creation(self) -> None:
        rejected_files = [
            ("empty.fna", b""),
            ("notes.fasta", b"this is not a FASTA genome\n"),
            ("protein_like.fna", b">protein\nMKWVTFISLLFLFSSAYSRGVFRRDTHKSEIAHRFKDLGE\n"),
        ]
        for filename, content in rejected_files:
            with self.subTest(filename=filename):
                status, payload, _ = self.submit(files=[("files", filename, content)])
                self.assertEqual(status, 400)
                self.assertIn("detail", payload)
                self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_public_genome_content_checker_records_valid_fasta_and_genbank_readiness(self) -> None:
        self.app.PUBLIC_GENOME_PARALLELISM = 8
        genbank = b"""LOCUS       DemoGenome              24 bp    DNA     linear   PLN 01-JAN-2026
FEATURES             Location/Qualifiers
     CDS             1..24
                     /translation="MKT"
ORIGIN
        1 atgcatgcat gcatgcatgc atgc
//
"""
        genbank_without_translations = b"""LOCUS       FallbackGenome          24 bp    DNA     linear   PLN 01-JAN-2026
FEATURES             Location/Qualifiers
ORIGIN
        1 atgcatgcat gcatgcatgc atgc
//
"""
        status, payload, _ = self.submit(
            files=[
                ("files", "Aspergillus_fumigatus_Af293.fna", b">contig1\nATGCRYSWKMBDHVNATGCNNNN\n"),
                ("files", "Penicillium_demo.gbk", genbank),
                ("files", "Fallback_demo.fna", b">contig1\nATGCATGCATGCATGCATGCATGC\n"),
                ("files", "Fallback_demo.gbff", genbank_without_translations),
            ]
        )
        self.assertEqual(status, 201)
        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        summary = job["input_summary"]
        self.assertEqual(summary["genome_file_count"], 4)
        self.assertEqual(job["settings"]["genome_count"], 3)
        self.assertEqual(job["settings"]["genome_parallelism"], 3)
        readiness = {item["filename"]: item for item in summary["genome_readiness"]}
        self.assertEqual(readiness["Aspergillus_fumigatus_Af293.fna"]["readiness"], "raw_fasta_requires_annotation")
        self.assertEqual(readiness["Penicillium_demo.gbk"]["readiness"], "annotated_genbank_ready")
        self.assertEqual(readiness["Fallback_demo.fna"]["readiness"], "raw_fasta_requires_annotation")
        self.assertEqual(readiness["Fallback_demo.gbff"]["readiness"], "genbank_requires_fallback_or_translations")

    def test_public_genbank_requires_every_non_pseudogene_cds_translation(self) -> None:
        partial = b"""LOCUS       PartialGenome           30 bp    DNA     linear   PLN 01-JAN-2026
FEATURES             Location/Qualifiers
     CDS             1..9
                     /translation="MKT"
     CDS             10..18
                     /product="untranslated protein"
ORIGIN
        1 atgaaaactatgaaaactatgaaaact
//
"""
        empty_marker = partial.replace(
            b'/product="untranslated protein"',
            b'/translation=""',
        )
        for filename, payload in [
            ("partial.gbk", partial),
            ("empty-marker.gbk", empty_marker),
        ]:
            with self.subTest(filename=filename):
                readiness, reason = self.app.classify_public_genbank(filename, payload)
                self.assertEqual(readiness, "genbank_requires_fallback_or_translations")
                self.assertIn("lacks complete non-empty CDS translations", reason)

    def test_public_genbank_without_translations_requires_same_stem_fasta_before_job_creation(self) -> None:
        genbank_without_translations = b"""LOCUS       FallbackGenome          24 bp    DNA     linear   PLN 01-JAN-2026
FEATURES             Location/Qualifiers
ORIGIN
        1 atgcatgcat gcatgcatgc atgc
//
"""
        status, payload, _ = self.submit(files=[("files", "Fallback_demo.gbff", genbank_without_translations)])
        self.assertEqual(status, 400)
        self.assertIn("lacks CDS translations", payload["detail"])
        self.assertIn("same-stem nucleotide FASTA", payload["detail"])
        self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_public_genome_content_checker_rejects_malformed_genbank_before_job_creation(self) -> None:
        malformed = b"""LOCUS       DemoGenome              24 bp    DNA     linear   PLN 01-JAN-2026
ORIGIN
        1 atgcatgcat gcatgcatgc atgc
//
"""
        status, payload, _ = self.submit(files=[("files", "broken.gbk", malformed)])
        self.assertEqual(status, 400)
        self.assertIn("FEATURES", payload["detail"])
        self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_public_genome_stems_must_be_safe_and_unique(self) -> None:
        fasta = b">contig1\nATGCATGCATGC\n"
        rejected_single_files = [
            ("bad name.fna", fasta),
            ("bad(name).fna", fasta),
            ("bad/name.fna", fasta),
        ]
        for filename, content in rejected_single_files:
            with self.subTest(filename=filename):
                status, payload, _ = self.submit(files=[("files", filename, content)])
                self.assertEqual(status, 400)
                self.assertIn("simple stem", payload["detail"])
                self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

        status, payload, _ = self.submit(
            files=[
                ("files", "duplicate.fna", fasta),
                ("files", "duplicate.fa", fasta),
            ]
        )
        self.assertEqual(status, 400)
        self.assertIn("duplicate FASTA", payload["detail"])
        self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_accession_lists_reject_malformed_assembly_accessions_before_job_creation(self) -> None:
        rejected_files = [
            ("accessions.txt", b"totally_random\n"),
            ("accessions.txt", b"GCF_123\n"),
            ("accessions.txt", b"ABC_000001405.1\n"),
            ("accessions.txt", b"GCA_000011425\n"),
            ("accessions.txt", b"PRJNA31257\n"),
            ("accessions.txt", b"SAMN02604091\n"),
            ("accessions.txt", b"SRR123456\n"),
            ("accessions.txt", b"NZ_CP000001.1\n"),
            ("accessions.txt", b"NC_000001.11\n"),
            ("accessions.txt", b"9606\n"),
            ("manual_accessions.txt", b"not_an_assembly\n"),
        ]
        for filename, content in rejected_files:
            with self.subTest(filename=filename, content=content):
                status, payload, _ = self.submit(files=[("files", filename, content)])
                self.assertEqual(status, 400)
                self.assertIn("invalid accession", payload["detail"])
                self.assertIn("GCA_000011425.1", payload["detail"])
                self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_public_accession_lists_reject_non_fungal_assemblies_before_job_creation(self) -> None:
        for accession, organism in [
            ("GCF_000001405.40", "Homo sapiens"),
            ("GCF_000005845.2", "Escherichia coli"),
        ]:
            with self.subTest(accession=accession):
                status, payload, _ = self.submit(files=[("files", "accessions.txt", f"{accession}\n".encode("utf-8"))])
                self.assertEqual(status, 400)
                self.assertIn(organism, payload["detail"])
                self.assertIn("not a fungal assembly", payload["detail"])
                self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_public_submission_rejects_multiple_accession_lists_before_job_creation(self) -> None:
        status, payload, _ = self.submit(
            files=[
                ("files", "accessions-one.txt", b"GCA_000011425.1\n"),
                ("files", "accessions-two.txt", b"GCA_030770425.1\n"),
            ]
        )
        self.assertEqual(status, 400)
        self.assertIn("one accession list", payload["detail"])
        self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_accession_lists_require_one_accession_per_line(self) -> None:
        status, payload, _ = self.submit(
            files=[("files", "accessions.txt", b"GCA_030770425.1 GCA_000011425.1\n")]
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
            (
                "files", "ecofun_metadata_normalized.tsv",
                b"accession\tgenome_id_current\ttaxonomy_id\tgenome_size_mb\tgenome_id_original_if_different\tecofun_primary\tecofun_secondary\n"
                b"\tAspergillus_fumigatus_Af293\t\t\t\tsoil\t\n",
            ),
        ]

        status, payload, _ = self.submit(fields={"project_name": "eco-off", "run_ecology_analysis": "0"}, files=files)
        self.assertEqual(status, 400)
        self.assertIn("Ecology metadata", payload["detail"])

        status, payload, _ = self.submit(fields={"project_name": "eco-on", "run_ecology_analysis": "1"}, files=files)
        self.assertEqual(status, 201)
        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["input_summary"]["metadata_file_count"], 1)
        self.assertEqual(job["input_summary"]["genome_file_count"], 1)

    def test_public_accession_and_genome_quotas_are_enforced(self) -> None:
        accepted = [f"GCF_{100000000 + idx:09d}.1" for idx in range(1, 51)]
        original_fetch = self.app.fetch_ncbi_datasets_json

        def fifty_accession_fixture(path: str) -> dict[str, object]:
            if path.startswith("genome/accession/") and path.endswith("/dataset_report"):
                accession = path.split("/", 2)[2].rsplit("/", 1)[0]
                if accession in accepted:
                    return {
                        "reports": [{
                            "accession": accession,
                            "organism": {
                                "tax_id": 227321,
                                "organism_name": f"Aspergillus fixture {accession}",
                            },
                            "assembly_info": {"assembly_status": "current"},
                        }],
                        "total_count": 1,
                    }
            return original_fetch(path)

        self.app.fetch_ncbi_datasets_json = fifty_accession_fixture
        exactly_fifty = ("\n".join(accepted) + "\n").encode("utf-8")
        status, payload, _ = self.submit(
            fields={"project_name": "fifty-accessions"},
            files=[("files", "accessions.txt", exactly_fifty)],
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["input_summary"]["accession_count"], 50)

        fifty_one = exactly_fifty + b"GCF_199999999.1\n"
        status, payload, _ = self.submit(files=[("files", "accessions.txt", fifty_one)])
        self.assertEqual(status, 400)
        self.assertIn("at most 50 accessions", payload["detail"])

        exactly_fifty_genomes = [
            ("files", f"genome_{idx}.fna", f">seq{idx}\nATGC\n".encode("utf-8"))
            for idx in range(50)
        ]
        status, payload, _ = self.submit(
            fields={"project_name": "fifty-genomes"},
            files=exactly_fifty_genomes,
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["input_summary"]["genome_file_count"], 50)

        status, payload, _ = self.submit(files=exactly_fifty_genomes + [("files", "genome_50.fna", b">seq50\nATGC\n")])
        self.assertEqual(status, 400)
        self.assertIn("50 genome files", payload["detail"])

    def test_public_upload_size_and_queue_quotas_are_enforced(self) -> None:
        self.app.MAX_UPLOAD_FILE_MB = 1
        status, payload, _ = self.submit(files=[("files", "large.fna", b"A" * (1024 * 1024 + 1))])
        self.assertEqual(status, 400)
        self.assertIn("1 MB", payload["detail"])

        self.app.MAX_UPLOAD_TOTAL_MB = 1
        files = [
            ("files", "one.fna", b">one\n" + b"A" * (700 * 1024) + b"\n"),
            ("files", "two.fna", b">two\n" + b"A" * (400 * 1024) + b"\n"),
        ]
        status, payload, _ = self.submit(files=files)
        self.assertEqual(status, 400)
        self.assertIn("Total upload size", payload["detail"])

        self.app.MAX_QUEUED_JOBS = 0
        status, payload, _ = self.submit()
        self.assertEqual(status, 429)
        self.assertIn("queue is full", payload["detail"])

    def test_oversized_multipart_body_is_rejected_before_parsing(self) -> None:
        maximum = (
            self.app.MAX_UPLOAD_TOTAL_MB + self.app.MAX_UPLOAD_BODY_OVERHEAD_MB
        ) * self.app.BYTES_PER_MB
        status, payload, _ = self.request(
            "POST",
            "/api/jobs",
            body=b"",
            headers={
                **self.auth("submit-secret"),
                "Content-Type": "multipart/form-data; boundary=bounded-test",
                "Content-Length": str(maximum + 1),
            },
        )

        self.assertEqual(status, 413)
        self.assertIn("exceeds", payload["detail"])

    def test_concurrent_upload_slots_fail_closed_without_parsing(self) -> None:
        acquired = [
            self.app.UPLOAD_SEMAPHORE.acquire(blocking=False)
            for _ in range(self.app.MAX_CONCURRENT_UPLOADS)
        ]
        self.assertTrue(all(acquired))
        try:
            status, payload, _ = self.submit(fields={"project_name": "busy-upload"})
        finally:
            for _ in acquired:
                self.app.UPLOAD_SEMAPHORE.release()

        self.assertEqual(status, 429)
        self.assertIn("upload intake is busy", payload["detail"])

    def test_submission_rejects_low_disk_before_creating_job(self) -> None:
        self.app.MIN_FREE_DISK_GB = 10
        disk_usage = mock.Mock(free=9 * 1024 * 1024 * 1024)
        with mock.patch.object(self.app.shutil, "disk_usage", return_value=disk_usage):
            status, payload, _ = self.submit()

        self.assertEqual(status, 507)
        self.assertIn("storage", payload["detail"].lower())
        self.assertIn("10 GiB required", payload["detail"])
        self.assertEqual(list((Path(self.tmp.name) / "jobs").glob("*")), [])

    def test_public_cpu_clamping_and_retention_metadata(self) -> None:
        fields = {
            "project_name": "quota-case",
            "cpus": "64",
            "threads": "64",
            "anno_cpus": "64",
            "workers": "64",
            "genome_parallelism": "64",
            "antismash_record_parallelism": "64",
            "antismash_shard_cpus": "64",
        }
        status, payload, _ = self.submit(fields=fields)
        self.assertEqual(status, 201)

        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["cpus"], min(8, os.cpu_count() or 8))
        self.assertEqual(job["settings"]["genome_count"], 1)
        self.assertEqual(job["settings"]["genome_parallelism"], 1)
        self.assertEqual(job["settings"]["antismash_record_parallelism"], 1)
        self.assertEqual(job["settings"]["antismash_shard_cpus"], job["cpus"])
        self.assertEqual(job["settings"]["antismash_legacy_cpus"], job["cpus"])
        self.assertEqual(job["settings"]["anno_cpus"], min(4, job["cpus"]))
        self.assertEqual(job["settings"]["workers"], min(2, job["cpus"]))
        self.assertLessEqual(job["settings"]["threads"], job["cpus"])
        annotation_cpu_demand = (
            job["settings"]["genome_parallelism"] * job["settings"]["anno_cpus"]
        )
        self.assertLessEqual(annotation_cpu_demand, job["cpus"])
        antismash_cpu_demand = (
            job["settings"]["genome_parallelism"]
            * job["settings"]["antismash_record_parallelism"]
            * job["settings"]["antismash_shard_cpus"]
        )
        self.assertLessEqual(antismash_cpu_demand, job["cpus"])
        legacy_antismash_cpu_demand = (
            job["settings"]["genome_parallelism"]
            * job["settings"]["antismash_legacy_cpus"]
        )
        self.assertLessEqual(legacy_antismash_cpu_demand, job["cpus"])
        funbgcex_cpu_demand = (
            job["settings"]["genome_parallelism"] * job["settings"]["workers"]
        )
        self.assertLessEqual(funbgcex_cpu_demand, job["cpus"])
        self.assertLessEqual(job["settings"]["genome_parallelism"], job["cpus"])
        self.assertEqual(job["retention_days"], 30)
        self.assertIn("expires_at", job)
        self.assertNotIn("completed_at", job)
        self.assertNotIn("failed_at", job)

        job["status"] = "success"
        job["updated_at"] = "2026-01-01T00:00:00"
        self.job_store.write_job(job)
        completed = self.read_submitted_job(payload)
        self.assertIsNotNone(completed)
        assert completed is not None
        self.assertEqual(completed["completed_at"], "2026-01-01T00:00:00")
        self.assertEqual(completed["expires_at"], "2026-01-31T00:00:00")

    def test_public_operator_targets_are_bounded_after_input_count_is_known(self) -> None:
        self.app.PUBLIC_GENOME_PARALLELISM = 4
        self.app.PUBLIC_ANTISMASH_RECORD_PARALLELISM = 3
        self.app.PUBLIC_FUNANNOTATE_CPUS_PER_GENOME = 4
        self.app.PUBLIC_FUNBGCEX_WORKERS_PER_GENOME = 2
        files = [
            ("files", f"genome-{index}.fna", f">seq{index}\nATGCATGC\n".encode("utf-8"))
            for index in range(5)
        ]

        with mock.patch.object(self.app.os, "cpu_count", return_value=8):
            status, payload, _ = self.submit(
                fields={
                    "resource_plan_mode": "explicit",
                    "genome_parallelism": "99",
                    "antismash_record_parallelism": "99",
                    "antismash_shard_cpus": "99",
                    "anno_cpus": "99",
                    "workers": "99",
                },
                files=files,
            )
        self.assertEqual(status, 201)

        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        settings = job["settings"]
        self.assertEqual(job["cpus"], 8)
        self.assertEqual(settings["genome_count"], 5)
        self.assertEqual(settings["genome_parallelism"], 4)
        self.assertEqual(settings["antismash_record_parallelism"], 2)
        self.assertEqual(settings["antismash_shard_cpus"], 1)
        self.assertEqual(settings["antismash_legacy_cpus"], 2)
        self.assertEqual(settings["anno_cpus"], 2)
        self.assertEqual(settings["workers"], 2)
        self.assertLessEqual(settings["genome_parallelism"] * settings["anno_cpus"], job["cpus"])
        self.assertLessEqual(settings["genome_parallelism"] * settings["workers"], job["cpus"])
        self.assertLessEqual(
            settings["genome_parallelism"]
            * settings["antismash_record_parallelism"]
            * settings["antismash_shard_cpus"],
            job["cpus"],
        )
        self.assertLessEqual(
            settings["genome_parallelism"] * settings["antismash_legacy_cpus"],
            job["cpus"],
        )

    def test_public_legacy_antismash_fallback_respects_genome_fanout_budget(self) -> None:
        status, payload, _ = self.submit(
            fields={
                "project_name": "public-legacy-antismash-budget",
                "genome_parallelism": "64",
                "antismash_record_parallelism": "1",
                "antismash_shard_cpus": "0",
            }
        )
        self.assertEqual(status, 201)

        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        settings = job["settings"]
        self.assertEqual(settings["antismash_record_parallelism"], 1)
        self.assertEqual(
            settings["antismash_legacy_cpus"],
            max(1, job["cpus"] // settings["genome_parallelism"]),
        )
        self.assertLessEqual(
            settings["genome_parallelism"] * settings["antismash_legacy_cpus"],
            job["cpus"],
        )

    def test_hosted_admin_normal_webui_uses_operator_default_fanout(self) -> None:
        self.app.MAX_CPUS_PER_JOB = 12
        self.app.PUBLIC_GENOME_PARALLELISM = 3
        self.app.PUBLIC_ANTISMASH_RECORD_PARALLELISM = 3
        self.app.PUBLIC_FUNANNOTATE_CPUS_PER_GENOME = 4
        self.app.PUBLIC_FUNBGCEX_WORKERS_PER_GENOME = 2
        fields = {
            "project_name": "admin-sharded-qa",
            "cpus": "8",
            "threads": "8",
            "anno_cpus": "8",
            "workers": "2",
            "genome_parallelism": "1",
            "antismash_record_parallelism": "1",
            "antismash_shard_cpus": "0",
        }
        files = [
            (
                "files",
                f"fungus-{index}.fna",
                f">seq{index}\nATGCATGC\n".encode("utf-8"),
            )
            for index in range(10)
        ]

        with mock.patch.object(self.app.os, "cpu_count", return_value=12):
            status, payload, _ = self.submit(
                fields=fields,
                files=files,
                token="admin-secret",
            )
        self.assertEqual(status, 201)

        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        settings = job["settings"]
        self.assertEqual(job["cpus"], 12)
        self.assertEqual(settings["genome_count"], 10)
        self.assertEqual(settings["genome_parallelism"], 3)
        self.assertEqual(settings["antismash_record_parallelism"], 3)
        self.assertEqual(settings["antismash_shard_cpus"], 1)
        self.assertEqual(settings["antismash_legacy_cpus"], 4)
        self.assertEqual(settings["anno_cpus"], 4)
        self.assertEqual(settings["workers"], 2)
        self.assertEqual(settings["threads"], 12)
        self.assertEqual(job["submission_settings"], settings)
        queue_payload = json.loads(
            (
                Path(self.tmp.name)
                / "queue"
                / f"{self.submitted_internal_job_id(payload)}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(queue_payload["cpus"], 12)
        self.assertEqual(queue_payload["settings"]["genome_parallelism"], 3)
        self.assertEqual(
            queue_payload["settings"]["antismash_record_parallelism"], 3
        )
        self.assertLessEqual(
            settings["genome_parallelism"]
            * settings["antismash_record_parallelism"]
            * settings["antismash_shard_cpus"],
            job["cpus"],
        )
        self.assertLessEqual(
            settings["genome_parallelism"] * settings["antismash_legacy_cpus"],
            job["cpus"],
        )
        self.assertLessEqual(settings["genome_parallelism"] * settings["anno_cpus"], job["cpus"])
        self.assertLessEqual(settings["genome_parallelism"] * settings["workers"], job["cpus"])

    def test_hosted_admin_explicit_resource_plan_remains_bounded(self) -> None:
        self.app.MAX_CPUS_PER_JOB = 12
        self.app.PUBLIC_GENOME_PARALLELISM = 3
        self.app.PUBLIC_ANTISMASH_RECORD_PARALLELISM = 3
        files = [
            (
                "files",
                f"explicit-{index}.fna",
                f">seq{index}\nATGCATGC\n".encode("utf-8"),
            )
            for index in range(5)
        ]

        with mock.patch.object(self.app.os, "cpu_count", return_value=12):
            status, payload, _ = self.submit(
                fields={
                    "project_name": "admin-explicit-shape",
                    "resource_plan_mode": "explicit",
                    "cpus": "8",
                    "threads": "7",
                    "genome_parallelism": "2",
                    "antismash_record_parallelism": "2",
                    "antismash_shard_cpus": "1",
                    "anno_cpus": "3",
                    "workers": "2",
                },
                files=files,
                token="admin-secret",
            )
        self.assertEqual(status, 201)

        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        settings = job["settings"]
        self.assertEqual(job["cpus"], 8)
        self.assertEqual(settings["genome_count"], 5)
        self.assertEqual(settings["genome_parallelism"], 2)
        self.assertEqual(settings["antismash_record_parallelism"], 2)
        self.assertEqual(settings["antismash_shard_cpus"], 1)
        self.assertEqual(settings["antismash_legacy_cpus"], 4)
        self.assertEqual(settings["anno_cpus"], 3)
        self.assertEqual(settings["workers"], 2)
        self.assertEqual(settings["threads"], 7)
        self.assertLessEqual(
            settings["genome_parallelism"]
            * settings["antismash_record_parallelism"]
            * settings["antismash_shard_cpus"],
            job["cpus"],
        )
        self.assertLessEqual(
            settings["genome_parallelism"] * settings["antismash_legacy_cpus"],
            job["cpus"],
        )
        self.assertLessEqual(
            settings["genome_parallelism"] * settings["anno_cpus"],
            job["cpus"],
        )
        self.assertLessEqual(
            settings["genome_parallelism"] * settings["workers"],
            job["cpus"],
        )


    def test_public_submission_locks_base_stages_but_honors_safe_downstream_toggles(self) -> None:
        fields = {
            "project_name": "canonical-case",
            "cpus": "1",
            "threads": "1",
            "anno_cpus": "1",
            "workers": "64",
            "genome_parallelism": "64",
            "run_ncbi_install": "1",
            "run_genome_prep": "0",
            "run_annotation": "0",
            "run_bigscape": "0",
            "run_summary": "0",
            "run_crosswalk": "0",
            "run_clinker": "0",
            "execute_clinker": "0",
            "run_figures": "0",
            "figures_required": "1",
            "force": "1",
            "genefinding_mode": "braker3,funannotate",
            "annotation_fallback_order": "braker3,funannotate",
            "braker3_enabled": "1",
        }
        status, payload, _ = self.submit(fields=fields)
        self.assertEqual(status, 201)

        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        settings = job["settings"]
        self.assertEqual(job["cpus"], min(8, os.cpu_count() or 8))
        self.assertFalse(settings["run_ncbi_install"])
        self.assertTrue(settings["run_genome_prep"])
        self.assertTrue(settings["has_accession_inputs"])
        self.assertTrue(settings["run_annotation"])
        self.assertFalse(settings["run_bigscape"])
        self.assertFalse(settings["run_summary"])
        self.assertFalse(settings["run_crosswalk"])
        self.assertFalse(settings["run_clinker"])
        self.assertFalse(settings["execute_clinker"])
        self.assertFalse(settings["run_figures"])
        self.assertFalse(settings["figures_required"])
        self.assertFalse(settings["force"])
        self.assertEqual(settings["genefinding_mode"], "auto")
        self.assertEqual(settings["annotation_fallback_order"], "funannotate")
        self.assertFalse(settings["braker3_enabled"])
        self.assertEqual(settings["threads"], job["cpus"])
        self.assertEqual(settings["anno_cpus"], min(4, job["cpus"]))
        self.assertEqual(settings["workers"], min(2, job["cpus"]))
        self.assertEqual(settings["genome_parallelism"], 1)

    def test_public_submission_uses_nonforgeable_automatic_funannotate_policy(self) -> None:
        fields = {
            "project_name": "forged-annotation-case",
            "funannotate_busco_db": "ascomycota_odb10",
            "funannotate_organism_name": "Homo sapiens",
        }
        status, payload, _ = self.submit(fields=fields)
        self.assertEqual(status, 201)

        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        settings = job["settings"]
        self.assertEqual(settings["funannotate_busco_db"], "auto")
        self.assertEqual(settings["funannotate_organism_name"], "auto")

    def test_web_submission_sanitizes_restricted_annotation_fallbacks_in_local_mode(self) -> None:
        self.app.PUBLIC_MODE = False
        fields = {
            "project_name": "local-annotation-case",
            "genefinding_mode": "braker3,funannotate",
            "annotation_fallback_order": "braker3,funannotate",
            "braker3_enabled": "1",
            "cpus": "8",
            "genome_parallelism": "2",
            "antismash_record_parallelism": "3",
            "antismash_shard_cpus": "1",
        }
        status, payload, _ = self.submit(fields=fields, token=None)
        self.assertEqual(status, 201)

        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["settings"]["genefinding_mode"], "funannotate")
        self.assertEqual(job["settings"]["annotation_fallback_order"], "funannotate")
        self.assertFalse(job["settings"]["braker3_enabled"])
        self.assertEqual(job["settings"]["genome_parallelism"], 2)
        self.assertEqual(job["settings"]["antismash_record_parallelism"], 3)
        self.assertEqual(job["settings"]["antismash_shard_cpus"], 1)

    def test_public_runtime_unavailable_is_operator_facing(self) -> None:
        worker_dir = Path(self.tmp.name) / "worker"
        status_payload = {
            "ready": True,
            "state": "idle",
            "phase": "idle",
            "progress": 100,
            "detail": "Ready for tests",
            "substep": "",
            "updated_at": self.job_store.now_iso(),
            "runtime": {"mode": "test"},
            "worker": {"active_jobs": [], "active_count": 0},
            "capabilities": {
                "stages": {
                    "annotation": {
                        "available": False,
                        "detail": "Annotation runtime unavailable",
                        "missing": ["singularity/apptainer"],
                    }
                }
            },
        }
        (worker_dir / "status.json").write_text(json.dumps(status_payload), encoding="utf-8")

        status, payload, _ = self.submit(fields={"project_name": "runtime-case"})
        self.assertEqual(status, 503)
        self.assertIn("operator restores backend runtime services", payload["detail"])
        self.assertNotIn("Selected stage unavailable", payload["detail"])

    def test_only_required_sequence_phylogeny_needs_runtime_capability(self) -> None:
        unavailable = {
            "ready": True,
            "capabilities": {
                "stages": {
                    "taxon_tree_figure": {"available": True, "detail": "core ready"},
                    "sequence_phylogeny": {
                        "available": False,
                        "detail": "optional runtime unavailable",
                        "missing": ["prebuilt runtime"],
                    },
                }
            },
        }
        optional = {"run_phylogeny": True, "phylogeny_required": False}
        required = {"run_phylogeny": True, "phylogeny_required": True}
        self.assertIsNone(self.app.validate_runtime_request(optional, unavailable))
        reason = self.app.validate_runtime_request(required, unavailable)
        self.assertIsNotNone(reason)
        self.assertIn("sequence_phylogeny", str(reason))

        available = json.loads(json.dumps(unavailable))
        available["capabilities"]["stages"]["sequence_phylogeny"]["available"] = True
        available["capabilities"]["stages"]["taxon_tree_figure"]["available"] = False
        self.assertIsNone(self.app.validate_runtime_request(required, available))

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
        self.assertIn('"completed_jobs_deleted": 1', totals_text)
        self.assertNotIn("user@example.org", totals_text)
        self.assertNotIn("secret-hash", totals_text)

        status, payload, _ = self.request("GET", "/api/system/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["jobs_processed"], 1)

    def test_retention_sweeper_never_deletes_pending_or_running_jobs(self) -> None:
        created = "2026-01-01T00:00:00"
        queue_paths: list[Path] = []
        for status in ["pending", "running"]:
            job_id = f"old-{status}"
            self.job_store.write_job(
                {
                    "id": job_id,
                    "name": job_id,
                    "status": status,
                    "stage": "queued" if status == "pending" else "annotation",
                    "created_at": created,
                    "updated_at": created,
                    "cpus": 2,
                    "settings": {},
                    "submission_settings": {},
                }
            )
            queue_path = Path(self.tmp.name) / "queue" / f"{job_id}.json"
            queue_path.write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
            queue_paths.append(queue_path)

        result = self.job_store.sweep_expired_jobs(
            now=datetime.fromisoformat("2026-02-01T00:00:00")
        )

        self.assertEqual(result["deleted_jobs"], 0)
        for status, queue_path in zip(["pending", "running"], queue_paths):
            self.assertTrue(self.job_store.job_dir(f"old-{status}").is_dir())
            self.assertTrue(queue_path.is_file())

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
            fields={"project_name": "admin-restricted-env", "env_overrides": "BRAKER3_ENABLED=1"},
            token="admin-secret",
        )
        self.assertEqual(status, 400)
        self.assertIn("Restricted runtime/resource", payload["detail"])

        status, payload, _ = self.submit(
            fields={"project_name": "admin-resource-env", "env_overrides": "CPUS=999"},
            token="admin-secret",
        )
        self.assertEqual(status, 400)
        self.assertIn("CPUS", payload["detail"])

        for key, value in [
            ("RUN_PHYLOGENY", "1"),
            ("PHYLOGENY_CPUS", "999"),
            ("PHYLOGENY_PARALLELISM", "999"),
            ("TAXONOMY_METADATA", "spoofed"),
        ]:
            with self.subTest(restricted_phylogeny_key=key):
                status, payload, _ = self.submit(
                    fields={
                        "project_name": f"admin-{key.lower()}",
                        "env_overrides": f"{key}={value}",
                    },
                    token="admin-secret",
                )
                self.assertEqual(status, 400)
                self.assertIn(key, payload["detail"])

        status, payload, _ = self.submit(
            fields={"project_name": "admin-env-allowed", "env_overrides": "SECRET=1"},
            token="admin-secret",
        )
        self.assertEqual(status, 201)
        job = self.read_submitted_job(payload)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["settings"]["env_overrides"], "SECRET=1")


if __name__ == "__main__":
    unittest.main()
