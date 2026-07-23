from __future__ import annotations

import hashlib
import http.client
import importlib
import json
import os
from http.server import ThreadingHTTPServer
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.parse


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{22,}$")


class OpaquePublicResultTests(unittest.TestCase):
    """End-to-end policy checks for clean public result identifiers."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env_keys = [
            "DATA_DIR",
            "CLUSTERWEAVE_PUBLIC_MODE",
            "CLUSTERWEAVE_ADMIN_TOKEN",
            "CLUSTERWEAVE_ADMIN_TOKEN_SHA256",
            "CLUSTERWEAVE_ADMIN_TOKEN_HASH",
            "CLUSTERWEAVE_JOB_TOKEN_SECRET",
            "CLUSTERWEAVE_ALLOWED_ORIGINS",
        ]
        self.old_env = {key: os.environ.get(key) for key in self.env_keys}
        os.environ.update(
            {
                "DATA_DIR": self.tmp.name,
                "CLUSTERWEAVE_PUBLIC_MODE": "1",
                "CLUSTERWEAVE_ADMIN_TOKEN": "opaque-admin-token",
                "CLUSTERWEAVE_JOB_TOKEN_SECRET": "opaque-result-test-secret",
            }
        )
        os.environ.pop("CLUSTERWEAVE_ADMIN_TOKEN_SHA256", None)
        os.environ.pop("CLUSTERWEAVE_ADMIN_TOKEN_HASH", None)
        os.environ.pop("CLUSTERWEAVE_ALLOWED_ORIGINS", None)

        self.inserted_web_path = False
        if str(WEB_DIR) not in sys.path:
            sys.path.insert(0, str(WEB_DIR))
            self.inserted_web_path = True
        for name in [
            "app",
            "job_store",
            "result_attestation",
            "public_results",
            "public_result_backend",
            "public_artifacts",
            "result_artifacts",
        ]:
            sys.modules.pop(name, None)
        self.job_store = importlib.import_module("job_store")
        self.app = importlib.import_module("app")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

        self.first = self._write_bundle_job(
            "d34db33f", "first-read-token", "Hidden_Project_Alpha"
        )
        self.second = self._write_bundle_job(
            "c0ffee42", "second-read-token", "Hidden_Project_Beta"
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        for name in [
            "app",
            "job_store",
            "result_attestation",
            "public_results",
            "public_result_backend",
            "public_artifacts",
            "result_artifacts",
        ]:
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

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str = "",
        payload: dict[str, object] | None = None,
    ) -> tuple[int, object, dict[str, str]]:
        body = None
        headers = self._auth(token) if token else {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        response_headers = dict(response.getheaders())
        connection.close()
        if response_headers.get("Content-Type", "").startswith("application/json"):
            return response.status, json.loads(raw.decode("utf-8")), response_headers
        return response.status, raw, response_headers

    def _write_bundle_job(
        self, internal_id: str, read_token: str, project: str
    ) -> dict[str, object]:
        root = self.job_store.job_dir(internal_id)
        prefix = f"data/results/{project}"
        files = {
            f"{prefix}/antismash/Fungus_alpha/index.html": (
                b'<!doctype html><html><body><a href="#r1c1">Fungal region</a>'
                b'<section id="r1c1">Fungal region detail</section></body></html>'
            ),
            f"{prefix}/antismash/Fungus_alpha/knownclusterblast/region1/hit.html": (
                b"<!doctype html><html><body>Fungal region detail</body></html>"
            ),
            f"{prefix}/antismash/Fungus_alpha/css/style.css": (
                b"body{background-image:url(../images/plus-circle.svg)}\n"
            ),
            f"{prefix}/antismash/Fungus_alpha/images/plus-circle.svg": (
                b'<svg xmlns="http://www.w3.org/2000/svg"><title>plus</title></svg>\n'
            ),
            f"{prefix}/antismash/Bacterium_beta/index.html": (
                b'<!doctype html><html><body><a href="#r1c1">Bacterial region</a>'
                b'<section id="r1c1">Bacterial region detail</section></body></html>'
            ),
            f"{prefix}/antismash/Bacterium_beta/knownclusterblast/region1/hit.html": (
                b"<!doctype html><html><body>Bacterial region detail</body></html>"
            ),
            f"{prefix}/funbgcex/Fungus_alpha/allBGCs.html": (
                b'<!doctype html><html><body><a href="results/Fungus_alpha.funbgcex_results/'
                b'HTMLs/BGC1.html#top">BGC 1</a></body></html>'
            ),
            (
                f"{prefix}/funbgcex/Fungus_alpha/results/"
                "Fungus_alpha.funbgcex_results/results.html"
            ): (
                b'<!doctype html><html><body><a href="HTMLs/BGC1.html">'
                b"BGC 1</a></body></html>"
            ),
            (
                f"{prefix}/funbgcex/Fungus_alpha/results/"
                "Fungus_alpha.funbgcex_results/HTMLs/BGC1.html"
            ): (
                b'<!doctype html><html><body><main id="top">'
                b"FunBGCeX BGC 1 detail</main></body></html>"
            ),
            f"{prefix}/figures/overview.svg": b"<svg><title>overview</title></svg>\n",
            f"{prefix}/big_scape/index.html": (
                b"<!doctype html><html><body>BiG-SCAPE</body></html>"
            ),
            (
                f"{prefix}/clinker/panels/atlas/bacteria/"
                "bacteria_Bacterium_beta/bacterial_panel/panel.html"
            ): b"<!doctype html><html><body>bacterial clinker panel</body></html>",
            (
                f"{prefix}/clinker/panels/atlas/fungi/"
                "Fungus_alpha/fungal_panel/panel.html"
            ): b"<!doctype html><html><body>fungal clinker panel</body></html>",
        }
        for relative, content in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        # These files deliberately exist but never enter the signed public index.
        private_files = {
            f"{prefix}/antismash/Fungus_alpha/raw-record.json": b'{"sequence":"ATGC"}\n',
            f"{prefix}/big_scape/output_files/big_scape.db": b"private sqlite bytes\n",
            "data/genomes/private.gbk": b"LOCUS PRIVATE\nORIGIN\n        1 atgc\n//\n",
        }
        for relative, content in private_files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        manifest_path = root / "downloads" / "public_results_manifest.tsv"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for relative, content in files.items():
            rows.append(
                f"{relative}\t{len(content)}\t{hashlib.sha256(content).hexdigest()}"
            )
        manifest_path.write_text(
            "path\tbytes\tsha256\n" + "".join(f"{row}\n" for row in rows),
            encoding="utf-8",
        )

        now = self.job_store.now_iso()
        job = {
            "id": internal_id,
            "name": f"{project} result",
            "project_name": project,
            "status": "success",
            "stage": "complete",
            "created_at": now,
            "updated_at": now,
            "completed_at": now,
            "log_count": 0,
            "result_files": ["downloads/public_results_manifest.tsv", *files],
            "read_token_hash": self.app.job_token_hash(read_token),
            "read_token_created_at": now,
        }
        self.job_store.write_job(job)
        importlib.import_module("result_attestation").write_result_attestation(
            root,
            internal_id,
            verify_hashes=True,
            path_validator=lambda path: self.app.result_file_is_publicly_servable(
                root, path
            ),
        )
        return {
            "internal_id": internal_id,
            "read_token": read_token,
            "project": project,
            "prefix": prefix,
            "files": files,
        }

    def _public_id(self, fixture: dict[str, object]) -> str:
        status, payload, _ = self._request(
            "GET",
            f"/api/jobs/{fixture['internal_id']}?compact=1",
            token=str(fixture["read_token"]),
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(payload, dict)
        public_id = str(
            payload.get("public_run_id")
            or payload.get("run_id")
            or payload.get("id")
            or ""
        )
        self._assert_opaque_id(public_id)
        self.assertNotEqual(public_id, fixture["internal_id"])
        return public_id

    def _artifacts(
        self, fixture: dict[str, object]
    ) -> tuple[str, dict[str, object], list[dict[str, object]]]:
        public_id = self._public_id(fixture)
        status, payload, _ = self._request(
            "GET",
            f"/api/results/{urllib.parse.quote(public_id)}/artifacts",
            token=str(fixture["read_token"]),
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(payload, dict)
        artifacts = payload.get("artifacts")
        self.assertIsInstance(artifacts, list)
        self.assertTrue(artifacts)
        return public_id, payload, artifacts

    def _assert_opaque_id(self, value: str) -> None:
        self.assertRegex(value, OPAQUE_ID_RE)
        # URL-safe base64 carries six bits per character; 22 characters is at
        # least the encoded width of a 128-bit random/HMAC identifier.
        self.assertGreaterEqual(len(value) * 6, 128)

    def _assert_public_payload_clean(
        self, payload: object, fixtures: list[dict[str, object]] | None = None
    ) -> None:
        encoded = json.dumps(payload, sort_keys=True)
        lowered = encoded.lower()
        self.assertNotIn("data/results/", lowered)
        self.assertNotIn("/jobs/", lowered)
        self.assertNotIn("job.json", lowered)
        self.assertNotIn("logs.txt", lowered)
        for fixture in fixtures or [self.first, self.second]:
            self.assertNotIn(str(fixture["internal_id"]), encoded)

        def visit(value: object) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertNotIn(
                        str(key).lower(),
                        {"path", "relative_path", "storage_path", "full_path", "sha256"},
                    )
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)

    @staticmethod
    def _find_artifact(
        artifacts: list[dict[str, object]],
        *,
        filename: str,
        contains: str = "",
    ) -> dict[str, object]:
        matches = [
            artifact
            for artifact in artifacts
            if str(artifact.get("filename") or "") == filename
            and contains.lower() in json.dumps(artifact).lower()
        ]
        if len(matches) != 1:
            raise AssertionError(
                f"Expected one {filename!r} artifact containing {contains!r}; got {matches!r}"
            )
        return matches[0]

    def _resolve(
        self,
        fixture: dict[str, object],
        public_id: str,
        owner_id: str,
        reference: str,
        *,
        optional: bool = False,
    ) -> tuple[int, object, dict[str, str]]:
        payload: dict[str, object] = {"reference": reference}
        if optional:
            payload["optional"] = True
        return self._request(
            "POST",
            (
                f"/api/results/{urllib.parse.quote(public_id)}/artifacts/"
                f"{urllib.parse.quote(owner_id)}/resolve"
            ),
            token=str(fixture["read_token"]),
            payload=payload,
        )

    def test_public_and_artifact_identifiers_are_stable_opaque_and_job_scoped(self) -> None:
        first_id, first_payload, first_artifacts = self._artifacts(self.first)
        repeated_id, repeated_payload, repeated_artifacts = self._artifacts(self.first)
        second_id, second_payload, second_artifacts = self._artifacts(self.second)

        self.assertEqual(repeated_id, first_id)
        self.assertNotEqual(second_id, first_id)
        self.assertEqual(first_payload["generation"], repeated_payload["generation"])
        self.assertEqual(
            [artifact["id"] for artifact in first_artifacts],
            [artifact["id"] for artifact in repeated_artifacts],
        )
        for artifact in [*first_artifacts, *second_artifacts]:
            self._assert_opaque_id(str(artifact.get("id") or ""))
        self.assertTrue(
            {artifact["id"] for artifact in first_artifacts}.isdisjoint(
                {artifact["id"] for artifact in second_artifacts}
            )
        )

        for fixture, public_id, payload in [
            (self.first, first_id, first_payload),
            (self.second, second_id, second_payload),
        ]:
            self._assert_public_payload_clean(payload)
            status, metadata, _ = self._request(
                "GET",
                f"/api/results/{urllib.parse.quote(public_id)}",
                token=str(fixture["read_token"]),
            )
            self.assertEqual(status, 200)
            self.assertEqual(metadata["id"], public_id)
            self.assertEqual(metadata["job_id"], public_id)
            self.assertEqual(metadata["public_run_id"], public_id)
            self._assert_public_payload_clean(metadata)

    def test_clinker_descriptors_are_path_free_taxon_aware_and_panel_bounded(self) -> None:
        public_id, payload, artifacts = self._artifacts(self.first)
        bacterial = self._find_artifact(
            artifacts, filename="panel.html", contains="bacteria_Bacterium_beta"
        )
        fungal = self._find_artifact(
            artifacts, filename="panel.html", contains="Fungus_alpha"
        )
        self.assertEqual(bacterial["taxon_group"], "bacteria")
        self.assertEqual(bacterial["genome_label"], "bacteria_Bacterium_beta")
        self.assertEqual(bacterial["track"], "atlas")
        self.assertEqual(fungal["taxon_group"], "fungi")
        self.assertEqual(fungal["genome_label"], "Fungus_alpha")
        self._assert_public_payload_clean(payload)

        status, blocked, _ = self._resolve(
            self.first,
            public_id,
            str(bacterial["id"]),
            "../../../fungi/Fungus_alpha/fungal_panel/panel.html",
            optional=True,
        )
        self.assertEqual(status, 404)
        self._assert_public_payload_clean(blocked)

    def test_clean_artifact_delivery_mime_disposition_and_uniform_not_found(self) -> None:
        public_id, payload, artifacts = self._artifacts(self.first)
        figure = self._find_artifact(artifacts, filename="overview.svg")
        artifact_id = str(figure["id"])
        base = (
            f"/api/results/{urllib.parse.quote(public_id)}/artifacts/"
            f"{urllib.parse.quote(artifact_id)}"
        )

        status, body, headers = self._request(
            "GET", base, token=str(self.first["read_token"])
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, self.first["files"][f"{self.first['prefix']}/figures/overview.svg"])
        self.assertEqual(headers.get("Content-Type"), "image/svg+xml; charset=utf-8")
        self.assertTrue(headers.get("Content-Disposition", "").startswith("inline;"))
        self.assertNotIn(str(self.first["internal_id"]), headers.get("Content-Disposition", ""))

        status, _, headers = self._request(
            "GET", f"{base}/download", token=str(self.first["read_token"])
        )
        self.assertEqual(status, 200)
        self.assertTrue(headers.get("Content-Disposition", "").startswith("attachment;"))

        generated_html = [
            ("index.html", "Fungus_alpha"),
            ("allBGCs.html", "Fungus_alpha"),
            ("index.html", "BiG-SCAPE"),
            ("panel.html", "bacteria_Bacterium_beta"),
        ]
        for filename, marker in generated_html:
            with self.subTest(generated_html=marker):
                artifact = self._find_artifact(
                    artifacts,
                    filename=filename,
                    contains=marker,
                )
                status, _, html_headers = self._request(
                    "GET",
                    (
                        f"/api/results/{urllib.parse.quote(public_id)}/artifacts/"
                        f"{urllib.parse.quote(str(artifact['id']))}"
                    ),
                    token=str(self.first["read_token"]),
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    html_headers.get("Content-Type"),
                    "text/html; charset=utf-8",
                )
                csp = html_headers.get("Content-Security-Policy", "")
                self.assertTrue(csp.startswith("sandbox; default-src 'none';"))
                self.assertNotIn("allow-same-origin", csp)
                self.assertTrue(html_headers.get("Content-Disposition", "").startswith("inline;"))

        second_id, _, second_artifacts = self._artifacts(self.second)
        second_figure = self._find_artifact(second_artifacts, filename="overview.svg")
        unknown_artifact = "A" * 22
        probes = [
            (base, ""),
            (base, "wrong-read-token"),
            (
                f"/api/results/{urllib.parse.quote(second_id)}/artifacts/{second_figure['id']}",
                str(self.first["read_token"]),
            ),
            (
                f"/api/results/{urllib.parse.quote(public_id)}/artifacts/{second_figure['id']}",
                str(self.first["read_token"]),
            ),
            (
                f"/api/results/{'Z' * 22}/artifacts/{artifact_id}",
                str(self.first["read_token"]),
            ),
            (
                f"/api/results/{urllib.parse.quote(public_id)}/artifacts/{unknown_artifact}",
                str(self.first["read_token"]),
            ),
            (
                f"/api/results/{urllib.parse.quote(public_id)}/artifacts/..%2F..%2Fjob.json",
                str(self.first["read_token"]),
            ),
        ]
        for path, token in probes:
            with self.subTest(path=path, token=bool(token)):
                status, response_payload, _ = self._request("GET", path, token=token)
                self.assertEqual(status, 404)
                self._assert_public_payload_clean(response_payload)

        # A legacy internal-ID metadata URL remains readable only with its
        # matching token so old bookmarks can discover the opaque run ID.
        # Unknown IDs and failed authentication must be indistinguishable.
        legacy_metadata_path = f"/api/jobs/{self.first['internal_id']}?compact=1"
        unknown_internal_id = "dead" + "beef"
        unknown_legacy_path = f"/api/jobs/{unknown_internal_id}?compact=1"
        for path, token in [
            (legacy_metadata_path, ""),
            (legacy_metadata_path, "wrong-read-token"),
            (unknown_legacy_path, ""),
            (unknown_legacy_path, "wrong-read-token"),
        ]:
            with self.subTest(legacy_path=path, token=bool(token)):
                status, legacy_error, _ = self._request("GET", path, token=token)
                self.assertEqual(status, 404)
                self.assertEqual(legacy_error, {"detail": "Result not found"})

        status, legacy_metadata, _ = self._request(
            "GET",
            legacy_metadata_path,
            token=str(self.first["read_token"]),
        )
        self.assertEqual(status, 200)
        self.assertEqual(legacy_metadata["public_run_id"], public_id)
        self._assert_public_payload_clean(legacy_metadata)

        # Every nested legacy route is admin-only in public mode.
        status, legacy_payload, _ = self._request(
            "GET",
            f"/api/jobs/{self.first['internal_id']}/files",
            token=str(self.first["read_token"]),
        )
        self.assertEqual(status, 404)
        self.assertEqual(legacy_payload, {"detail": "Result not found"})

        status, legacy_logs, _ = self._request(
            "GET",
            f"/api/jobs/{self.first['internal_id']}/logs?tail=500",
            token=str(self.first["read_token"]),
        )
        self.assertEqual(status, 404)
        self.assertEqual(legacy_logs, {"detail": "Result not found"})

        legacy_path = f"{self.first['prefix']}/figures/overview.svg"
        status, legacy_body, _ = self._request(
            "GET",
            (
                f"/api/jobs/{self.first['internal_id']}/files/"
                + "/".join(urllib.parse.quote(part) for part in legacy_path.split("/"))
            ),
            token="opaque-admin-token",
        )
        self.assertEqual(status, 200)
        self.assertEqual(legacy_body, self.first["files"][legacy_path])

    def test_nested_bundle_resolution_is_family_bounded_and_attested(self) -> None:
        public_id, _, artifacts = self._artifacts(self.first)
        fungal = self._find_artifact(
            artifacts, filename="index.html", contains="Fungus_alpha"
        )
        bacterial = self._find_artifact(
            artifacts, filename="index.html", contains="Bacterium_beta"
        )
        funbgcex = self._find_artifact(
            artifacts, filename="allBGCs.html", contains="Fungus_alpha"
        )

        valid = [
            (
                fungal,
                "knownclusterblast/region1/hit.html#r1c1",
                b"Fungal region detail",
                "#r1c1",
            ),
            (
                bacterial,
                "knownclusterblast/region1/hit.html",
                b"Bacterial region detail",
                "",
            ),
            (
                funbgcex,
                "results/Fungus_alpha.funbgcex_results/HTMLs/BGC1.html#top",
                b"FunBGCeX BGC 1 detail",
                "#top",
            ),
        ]
        for owner, reference, expected, fragment in valid:
            with self.subTest(reference=reference):
                status, payload, _ = self._resolve(
                    self.first, public_id, str(owner["id"]), reference
                )
                self.assertEqual(status, 200)
                descriptor = payload.get("artifact", payload)
                self.assertIsInstance(descriptor, dict)
                self._assert_public_payload_clean(payload)
                self._assert_opaque_id(str(descriptor.get("id") or ""))
                self.assertEqual(payload.get("fragment", ""), fragment)
                status, body, headers = self._request(
                    "GET",
                    (
                        f"/api/results/{urllib.parse.quote(public_id)}/artifacts/"
                        f"{urllib.parse.quote(str(descriptor['id']))}"
                    ),
                    token=str(self.first["read_token"]),
                )
                self.assertEqual(status, 200)
                self.assertIn(expected, body)
                self.assertTrue(headers.get("Content-Type", "").startswith("text/html"))
                self.assertTrue(headers.get("Content-Disposition", "").startswith("inline;"))

        status, css_payload, _ = self._resolve(
            self.first, public_id, str(fungal["id"]), "css/style.css"
        )
        self.assertEqual(status, 200)
        css_descriptor = css_payload.get("artifact", css_payload)
        self.assertEqual(css_descriptor.get("kind"), "stylesheet")
        self._assert_public_payload_clean(css_payload)

        status, image_payload, _ = self._resolve(
            self.first,
            public_id,
            str(css_descriptor["id"]),
            "../images/plus-circle.svg",
        )
        self.assertEqual(status, 200)
        image_descriptor = image_payload.get("artifact", image_payload)
        self.assertEqual(image_descriptor.get("filename"), "plus-circle.svg")
        self._assert_public_payload_clean(image_payload)
        status, image_body, image_headers = self._request(
            "GET",
            (
                f"/api/results/{urllib.parse.quote(public_id)}/artifacts/"
                f"{urllib.parse.quote(str(image_descriptor['id']))}"
            ),
            token=str(self.first["read_token"]),
        )
        self.assertEqual(status, 200)
        self.assertIn(b"<title>plus</title>", image_body)
        self.assertTrue(image_headers.get("Content-Type", "").startswith("image/svg+xml"))

        status, missing_payload, _ = self._resolve(
            self.first,
            public_id,
            str(fungal["id"]),
            "knownclusterblast/missing.html#top",
            optional=True,
        )
        self.assertEqual(status, 200)
        self.assertIsNone(missing_payload.get("artifact"))
        self.assertEqual(missing_payload.get("fragment"), "#top")
        self._assert_public_payload_clean(missing_payload)

        for reference in [
            "../../../../../../job.html",
            "../../Bacterium_beta/missing.html",
            "raw-record.json",
        ]:
            with self.subTest(optional_blocked_reference=reference):
                status, payload, _ = self._resolve(
                    self.first,
                    public_id,
                    str(fungal["id"]),
                    reference,
                    optional=True,
                )
                self.assertEqual(status, 404)
                self._assert_public_payload_clean(payload)

        for reference in [
            "../../Bacterium_beta/index.html",
            "../../../../figures/overview.svg",
            "../raw-record.json",
        ]:
            with self.subTest(stylesheet_reference=reference):
                status, payload, _ = self._resolve(
                    self.first, public_id, str(css_descriptor["id"]), reference
                )
                self.assertEqual(status, 404)
                self._assert_public_payload_clean(payload)

        blocked = [
            "../../../../../../job.json",
            "../../funbgcex/Fungus_alpha/results/Fungus_alpha.funbgcex_results/results.html",
            "raw-record.json",
            "../../figures/overview.svg",
            "/etc/passwd",
            "https://example.invalid/escape.html",
        ]
        for reference in blocked:
            with self.subTest(reference=reference):
                status, payload, _ = self._resolve(
                    self.first, public_id, str(fungal["id"]), reference
                )
                self.assertEqual(status, 404)
                self._assert_public_payload_clean(payload)

        status, payload, _ = self._resolve(
            self.first, public_id, "A" * 22, "knownclusterblast/region1/hit.html"
        )
        self.assertEqual(status, 404)
        self._assert_public_payload_clean(payload)


    def test_clean_artifact_route_never_follows_an_attested_path_replaced_by_symlink(
        self,
    ) -> None:
        public_id, _, artifacts = self._artifacts(self.first)
        figure = self._find_artifact(artifacts, filename="overview.svg")
        root = self.job_store.job_dir(str(self.first["internal_id"]))
        target = root / str(self.first["prefix"]) / "figures" / "overview.svg"
        private_target = root / "data" / "genomes" / "private.gbk"
        target.unlink()
        target.symlink_to(private_target)

        status, payload, _ = self._request(
            "GET",
            (
                f"/api/results/{urllib.parse.quote(public_id)}/artifacts/"
                f"{urllib.parse.quote(str(figure['id']))}"
            ),
            token=str(self.first["read_token"]),
        )
        self.assertEqual(status, 404)
        self._assert_public_payload_clean(payload)
        self.assertNotIn("LOCUS PRIVATE", json.dumps(payload))


    def test_interactive_metadata_paths_never_hydrate_attestations_hashes_or_raw_logs(
        self,
    ) -> None:
        public_id = self._public_id(self.first)
        forbidden = mock.Mock(side_effect=AssertionError("interactive metadata hydration"))
        with mock.patch.multiple(
            self.app,
            read_result_attestation=forbidden,
            _stable_public_sha256=forbidden,
            read_logs=forbidden,
            read_log_slice=forbidden,
            read_log_window=forbidden,
            read_logs_since=forbidden,
        ):
            status, public_payload, _ = self._request(
                "GET",
                f"/api/results/{urllib.parse.quote(public_id)}",
                token=str(self.first["read_token"]),
            )
            self.assertEqual(status, 200)
            self._assert_public_payload_clean(public_payload)

            status, admin_payload, _ = self._request(
                "GET",
                f"/api/jobs/{self.first['internal_id']}?compact=1",
                token="opaque-admin-token",
            )
            self.assertEqual(status, 200)
            self.assertEqual(admin_payload["id"], self.first["internal_id"])

        forbidden.assert_not_called()

        status, activity_payload, _ = self._request(
            "GET",
            f"/api/results/{urllib.parse.quote(public_id)}/activity",
            token=str(self.first["read_token"]),
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            set(activity_payload),
            {"run_id", "public_run_id", "public_events", "genome_progress"},
        )
        self._assert_public_payload_clean(activity_payload)

    def test_unchanged_artifact_catalog_reuses_completion_attestation(self) -> None:
        public_id = self._public_id(self.first)
        backend = importlib.import_module("public_result_backend")
        original = backend.read_result_attestation
        with mock.patch.object(
            backend,
            "read_result_attestation",
            wraps=original,
        ) as attestation_reads:
            for _ in range(2):
                status, payload, _ = self._request(
                    "GET",
                    f"/api/results/{urllib.parse.quote(public_id)}/artifacts",
                    token=str(self.first["read_token"]),
                )
                self.assertEqual(status, 200)
                self.assertEqual(payload["result_index_state"], "attested")
        self.assertEqual(attestation_reads.call_count, 1)

if __name__ == "__main__":
    unittest.main()
