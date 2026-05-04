#!/usr/bin/env python3
from __future__ import annotations

import json
import mimetypes
import os
import shutil
import urllib.parse
import uuid
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from job_store import (
    QUEUE_DIR,
    append_log,
    job_dir,
    list_jobs,
    now_iso,
    read_job,
    read_logs,
    write_job,
)

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))

ALLOWED_EXTENSIONS = {".gbk", ".gb", ".gbff", ".fasta", ".fa", ".fna"}


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_path(path: str) -> tuple[str, dict[str, list[str]]]:
    parsed = urllib.parse.urlparse(path)
    return parsed.path, urllib.parse.parse_qs(parsed.query)


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_multipart_form_data(content_type: str, body: bytes) -> tuple[dict[str, list[str]], list[dict[str, object]]]:
    """Parse multipart/form-data using the stdlib email package."""
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )

    fields: dict[str, list[str]] = {}
    files: list[dict[str, object]] = []

    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        if disposition != "form-data":
            continue

        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if not name:
            continue

        if filename is not None:
            files.append({
                "field": name,
                "filename": filename,
                "content": payload,
            })
            continue

        charset = part.get_content_charset() or "utf-8"
        value = payload.decode(charset, errors="replace")
        fields.setdefault(name, []).append(value)

    return fields, files


class Handler(BaseHTTPRequestHandler):
    server_version = "ClusterWeaveHTTP/2.0"

    def _send_json(self, status: int, payload: object) -> None:
        data = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self, message: str = "Not found") -> None:
        self._send_json(HTTPStatus.NOT_FOUND, {"detail": message})

    def _bad_request(self, message: str) -> None:
        self._send_json(HTTPStatus.BAD_REQUEST, {"detail": message})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        route, query = parse_path(self.path)

        if route == "/":
            index = Path(__file__).parent / "static" / "index.html"
            if not index.exists():
                self._not_found("Frontend not found")
                return
            self._send_text(HTTPStatus.OK, "text/html; charset=utf-8", index.read_bytes())
            return

        if route == "/api/jobs":
            self._send_json(HTTPStatus.OK, list_jobs())
            return

        if route.startswith("/api/jobs/"):
            parts = route.split("/")
            if len(parts) < 4:
                self._not_found()
                return
            job_id = parts[3]
            job = read_job(job_id)
            if job is None:
                self._not_found(f"Job '{job_id}' not found")
                return

            if len(parts) == 4:
                self._send_json(HTTPStatus.OK, job)
                return

            if len(parts) >= 5 and parts[4] == "logs":
                since = parse_int(query.get("since", ["0"])[0], 0)
                lines = read_logs(job_id)
                self._send_json(HTTPStatus.OK, {"lines": lines[max(0, since):], "total": len(lines)})
                return

            if len(parts) >= 5 and parts[4] == "files":
                if len(parts) == 5:
                    self._send_json(HTTPStatus.OK, {"files": job.get("result_files", [])})
                    return

                rel_path = "/".join(parts[5:])
                full = job_dir(job_id) / rel_path
                try:
                    full.relative_to(job_dir(job_id))
                except ValueError:
                    self._bad_request("Invalid path")
                    return
                if not full.exists() or not full.is_file():
                    self._not_found("File not found")
                    return

                mime, _ = mimetypes.guess_type(str(full))
                self._send_text(HTTPStatus.OK, mime or "application/octet-stream", full.read_bytes())
                return

        self._not_found()

    def do_POST(self) -> None:  # noqa: N802
        route, _ = parse_path(self.path)
        if route != "/api/jobs":
            self._not_found()
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._bad_request("Expected multipart/form-data")
            return

        content_length = parse_int(self.headers.get("Content-Length", "0"), 0)
        if content_length <= 0:
            self._bad_request("Missing or invalid Content-Length")
            return

        body = self.rfile.read(content_length)
        fields, files = parse_multipart_form_data(content_type, body)

        project_name = str(fields.get("project_name", ["my_project"])[0])
        cpus = max(1, min(parse_int(fields.get("cpus", ["4"])[0], 4), os.cpu_count() or 4))

        settings = {
            "target_genome": str(fields.get("target_genome", [""])[0]).strip(),
            "run_bigscape": parse_bool(fields.get("run_bigscape", ["1"])[0], True),
            "run_crosswalk": parse_bool(fields.get("run_crosswalk", ["1"])[0], True),
            "run_clinker": parse_bool(fields.get("run_clinker", ["1"])[0], True),
            "run_ecology_analysis": parse_bool(fields.get("run_ecology_analysis", ["0"])[0], False),
            "ecology_field": str(fields.get("ecology_field", ["ecofun_primary"])[0]).strip(),
            "focus_ecology_label": str(fields.get("focus_ecology_label", [""])[0]).strip(),
            "genefinding_mode": str(fields.get("genefinding_mode", ["auto"])[0]).strip() or "auto",
            "bigscape_mix_mode": parse_bool(fields.get("bigscape_mix_mode", ["1"])[0], True),
            "clinker_use_docker_image": parse_bool(fields.get("clinker_use_docker_image", ["1"])[0], True),
            "clinker_docker_image": str(fields.get("clinker_docker_image", [""])[0]).strip(),
            "clinker_docker_data_volume": str(fields.get("clinker_docker_data_volume", [""])[0]).strip(),
            "clinker_max_regions": max(0, parse_int(fields.get("clinker_max_regions", ["0"])[0], 0)),
            "atlas_min_records": max(1, parse_int(fields.get("atlas_min_records", ["2"])[0], 2)),
            "shortlist_limit": max(1, parse_int(fields.get("shortlist_limit", ["12"])[0], 12)),
            "max_comparators": max(1, parse_int(fields.get("max_comparators", ["50"])[0], 50)),
            "capture_external_artifacts": parse_bool(fields.get("capture_external_artifacts", ["1"])[0], True),
            "auto_normalize_metadata": parse_bool(fields.get("auto_normalize_metadata", ["1"])[0], True),
            "metadata_tsv": str(fields.get("metadata_tsv", [""])[0]).strip(),
        }

        if not settings["clinker_docker_image"]:
            settings["clinker_docker_image"] = os.environ.get(
                "CLINKER_DOCKER_IMAGE", "quay.io/biocontainers/clinker-py:0.0.32--pyhdfd78af_0"
            )
        if not settings["clinker_docker_data_volume"]:
            settings["clinker_docker_data_volume"] = os.environ.get("CLINKER_DOCKER_DATA_VOLUME", "")

        uploads = [item for item in files if item["field"] == "files"]
        if not uploads:
            self._bad_request("At least one file is required")
            return

        job_id = uuid.uuid4().hex[:8]
        created_at = now_iso()
        job = {
            "id": job_id,
            "name": project_name,
            "status": "pending",
            "stage": "queued",
            "created_at": created_at,
            "updated_at": created_at,
            "log_count": 0,
            "result_files": [],
            "error": None,
            "cpus": cpus,
            "settings": settings,
        }

        out_dir = job_dir(job_id)
        in_dir = out_dir / "inputs"
        in_dir.mkdir(parents=True, exist_ok=True)

        for item in uploads:
            filename = Path(str(item.get("filename") or "unknown")).name
            ext = Path(filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                self._bad_request(
                    f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
                )
                return

            destination = in_dir / filename
            with destination.open("wb") as handle:
                handle.write(bytes(item["content"]))
            append_log(job_id, f"Uploaded: {filename} ({destination.stat().st_size:,} bytes)")

        lines = read_logs(job_id)
        job["log_count"] = len(lines)
        job["updated_at"] = now_iso()
        write_job(job)

        queue_payload = {"job_id": job_id, "cpus": cpus, "settings": settings}
        queue_file = QUEUE_DIR / f"{job_id}.json"
        queue_file.write_text(json.dumps(queue_payload), encoding="utf-8")

        self._send_json(HTTPStatus.CREATED, {"job_id": job_id, "status": job["status"], "message": "Pipeline queued"})

    def do_DELETE(self) -> None:  # noqa: N802
        route, _ = parse_path(self.path)
        if not route.startswith("/api/jobs/"):
            self._not_found()
            return
        parts = route.split("/")
        if len(parts) != 4:
            self._not_found()
            return
        job_id = parts[3]

        job = read_job(job_id)
        if job is None:
            self._not_found(f"Job '{job_id}' not found")
            return

        target = job_dir(job_id)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)

        for q in QUEUE_DIR.glob(f"{job_id}*.json"):
            q.unlink(missing_ok=True)
        for q in QUEUE_DIR.glob(f"{job_id}*.working"):
            q.unlink(missing_ok=True)

        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"ClusterWeave web server listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
