#!/usr/bin/env python3
from __future__ import annotations

import json
import mimetypes
import os
import shutil
from datetime import datetime
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
from runtime_capabilities import unavailable_stage_reason

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))

ALLOWED_EXTENSIONS = {
    ".gbk",
    ".gb",
    ".gbff",
    ".fasta",
    ".fa",
    ".fna",
    ".fsa",
    ".txt",
    ".tsv",
    ".csv",
    ".json",
    ".gff",
    ".gff3",
    ".faa",
    ".mgf",
    ".zip",
}
WORKER_STATUS_PATH = Path(os.environ.get("DATA_DIR", "/data")) / "worker" / "status.json"
INLINE_MIME_OVERRIDES = {
    ".svg": "image/svg+xml; charset=utf-8",
    ".svgz": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


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


def parse_payload_bool(payload: dict[str, object], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def settings_bool(settings: dict[str, object], key: str, default: bool = False) -> bool:
    value = settings.get(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, object] | None:
    content_length = parse_int(handler.headers.get("Content-Length", "0"), 0)
    if content_length <= 0:
        return {}
    try:
        payload = json.loads(handler.rfile.read(content_length).decode("utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def worker_status() -> dict[str, object]:
    if not WORKER_STATUS_PATH.exists():
        return {
            "ready": False,
            "state": "bootstrapping",
            "detail": "Worker has not started yet",
            "substep": "Waiting for worker container",
            "updated_at": None,
            "stale": True,
            "runtime": {},
            "worker": {},
            "capabilities": {},
        }

    try:
        payload = json.loads(WORKER_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "ready": False,
            "state": "bootstrapping",
            "detail": "Worker status unreadable",
            "substep": "Retrying status read",
            "updated_at": None,
            "stale": True,
            "runtime": {},
            "worker": {},
            "capabilities": {},
        }

    updated_at = payload.get("updated_at")
    stale = True
    if isinstance(updated_at, str):
        try:
            age = (datetime.now() - datetime.fromisoformat(updated_at)).total_seconds()
            stale = age > 30
        except ValueError:
            stale = True

    state = str(payload.get("state", "bootstrapping"))
    phase = str(payload.get("phase", state))
    detail = str(payload.get("detail", ""))
    substep = str(payload.get("substep", ""))

    raw_progress = payload.get("progress", 0)
    try:
        progress = int(raw_progress)
    except (TypeError, ValueError):
        progress = 0

    progress = max(0, min(100, progress))

    payload_ready = payload.get("ready")
    if isinstance(payload_ready, bool):
        ready = payload_ready and not stale
    else:
        ready = (state in {"ready", "idle", "processing"}) and not stale

    return {
        "ready": ready,
        "state": state,
        "phase": phase,
        "progress": progress,
        "detail": detail,
        "substep": substep,
        "updated_at": updated_at,
        "stale": stale,
        "runtime": payload.get("runtime", {}),
        "worker": payload.get("worker", {}),
        "capabilities": payload.get("capabilities", {}),
    }


def result_file_mime(path: Path) -> str:
    override = INLINE_MIME_OVERRIDES.get(path.suffix.lower())
    if override:
        return override
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def content_disposition(disposition: str, filename: str) -> str:
    basename = Path(filename).name or "download"
    ascii_name = basename.encode("ascii", errors="ignore").decode("ascii") or "download"
    ascii_name = ascii_name.replace("\\", "_").replace('"', '\\"')
    encoded_name = urllib.parse.quote(basename)
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'


def validate_runtime_request(settings: dict[str, object], status: dict[str, object]) -> str | None:
    if not status.get("ready"):
        return "Worker is not ready yet. Wait for bootstrap to finish before submitting a job."

    capabilities = status.get("capabilities")
    if not isinstance(capabilities, dict):
        return None

    stages = capabilities.get("stages")
    if not isinstance(stages, dict):
        return None

    checks = [
        ("annotation", settings_bool(settings, "run_annotation")),
        ("bigscape", settings_bool(settings, "run_bigscape")),
        ("clinker", settings_bool(settings, "run_clinker") and settings_bool(settings, "execute_clinker")),
        ("nplinker", settings_bool(settings, "run_nplinker")),
        ("figures", settings_bool(settings, "run_figures") and settings_bool(settings, "figures_required")),
    ]
    for stage, required in checks:
        if not required:
            continue
        payload = stages.get(stage)
        if isinstance(payload, dict) and not payload.get("available", False):
            return f"Selected stage unavailable: {stage}. {unavailable_stage_reason(capabilities, stage)}"
    return None


def enqueue_job(job_id: str, cpus: int, settings: dict[str, object]) -> None:
    queue_payload = {"job_id": job_id, "cpus": cpus, "settings": settings}
    queue_file = QUEUE_DIR / f"{job_id}.json"
    queue_file.write_text(json.dumps(queue_payload), encoding="utf-8")


def base_job_settings(job: dict[str, object]) -> dict[str, object]:
    submission_settings = job.get("submission_settings")
    if isinstance(submission_settings, dict):
        return dict(submission_settings)
    current_settings = job.get("settings")
    return dict(current_settings) if isinstance(current_settings, dict) else {}


def rerun_settings(base_settings: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    settings = dict(base_settings)
    bool_fields = [
        "run_genome_prep",
        "run_annotation",
        "run_bigscape",
        "run_summary",
        "run_crosswalk",
        "run_clinker",
        "execute_clinker",
        "run_figures",
        "run_nplinker",
        "force",
    ]
    for key in bool_fields:
        if key in payload:
            settings[key] = parse_payload_bool(payload, key, settings_bool(settings, key, False))

    settings["run_ncbi_install"] = parse_payload_bool(payload, "run_ncbi_install", False)
    settings["reuse_existing_layout"] = True
    if "run_summary" in payload and "run_crosswalk" not in payload:
        settings["run_crosswalk"] = settings["run_summary"]
    if "execute_clinker" not in payload and "run_clinker" in payload:
        settings["execute_clinker"] = settings["run_clinker"]
    return settings


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

    def _send_text(
        self,
        status: int,
        content_type: str,
        body: bytes,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
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

        if route == "/api/system/status":
            self._send_json(HTTPStatus.OK, worker_status())
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

                rel_path = urllib.parse.unquote("/".join(parts[5:]))
                base_dir = job_dir(job_id).resolve()
                full = (base_dir / rel_path).resolve()
                try:
                    full.relative_to(base_dir)
                except ValueError:
                    self._bad_request("Invalid path")
                    return
                if not full.exists() or not full.is_file():
                    self._not_found("File not found")
                    return

                disposition = "attachment" if parse_bool(query.get("download", ["0"])[0], False) else "inline"
                headers = {
                    "Content-Disposition": content_disposition(disposition, full.name),
                    "X-Content-Type-Options": "nosniff",
                }
                self._send_text(HTTPStatus.OK, result_file_mime(full), full.read_bytes(), headers)
                return

        self._not_found()

    def do_POST(self) -> None:  # noqa: N802
        route, _ = parse_path(self.path)
        if route.startswith("/api/jobs/") and route.endswith("/rerun"):
            parts = route.split("/")
            if len(parts) != 5:
                self._not_found()
                return
            job_id = parts[3]
            job = read_job(job_id)
            if job is None:
                self._not_found(f"Job '{job_id}' not found")
                return
            if job.get("status") in {"pending", "running"}:
                self._send_json(HTTPStatus.CONFLICT, {"detail": "Job is already queued or running"})
                return

            payload = read_json_body(self)
            if payload is None:
                self._bad_request("Expected JSON object")
                return

            base_settings = base_job_settings(job)
            settings = rerun_settings(base_settings, payload)
            if not any(
                settings_bool(settings, key)
                for key in ["run_genome_prep", "run_annotation", "run_bigscape", "run_summary", "run_clinker", "run_figures", "run_nplinker"]
            ):
                self._bad_request("Select at least one stage to rerun")
                return
            runtime_error = validate_runtime_request(settings, worker_status())
            if runtime_error:
                self._send_json(HTTPStatus.CONFLICT, {"detail": runtime_error})
                return

            cpus = max(1, min(parse_int(str(payload.get("cpus", job.get("cpus", 4))), 4), os.cpu_count() or 4))
            append_log(job_id, "Re-queued existing job with selected stage rerun settings.")
            lines = read_logs(job_id)
            job["status"] = "pending"
            job["stage"] = "queued"
            job["error"] = None
            job["cpus"] = cpus
            job["settings"] = settings
            job["submission_settings"] = base_settings
            job["last_rerun_settings"] = settings
            job["log_count"] = len(lines)
            job["updated_at"] = now_iso()
            job["rerun_count"] = int(job.get("rerun_count", 0) or 0) + 1
            write_job(job)
            enqueue_job(job_id, cpus, settings)
            self._send_json(HTTPStatus.ACCEPTED, {"job_id": job_id, "status": "pending", "message": "Rerun queued"})
            return

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
            "project_name": project_name,
            "target_genome": str(fields.get("target_genome", [""])[0]).strip(),
            "run_ncbi_install": parse_bool(fields.get("run_ncbi_install", ["0"])[0], False),
            "run_genome_prep": parse_bool(fields.get("run_genome_prep", ["1"])[0], True),
            "run_annotation": parse_bool(fields.get("run_annotation", ["1"])[0], True),
            "run_bigscape": parse_bool(fields.get("run_bigscape", ["1"])[0], True),
            "run_crosswalk": parse_bool(fields.get("run_crosswalk", ["1"])[0], True),
            "run_summary": parse_bool(fields.get("run_summary", fields.get("run_crosswalk", ["1"]))[0], True),
            "run_clinker": parse_bool(fields.get("run_clinker", ["1"])[0], True),
            "execute_clinker": parse_bool(fields.get("execute_clinker", fields.get("run_clinker", ["1"]))[0], True),
            "run_figures": parse_bool(fields.get("run_figures", ["1"])[0], True),
            "run_nplinker": parse_bool(fields.get("run_nplinker", ["0"])[0], False),
            "run_ecology_analysis": parse_bool(fields.get("run_ecology_analysis", ["0"])[0], False),
            "ecology_field": str(fields.get("ecology_field", ["ecofun_primary"])[0]).strip(),
            "focus_ecology_label": str(fields.get("focus_ecology_label", [""])[0]).strip(),
            "genefinding_mode": str(fields.get("genefinding_mode", ["auto"])[0]).strip() or "auto",
            "bigscape_mix_mode": parse_bool(fields.get("bigscape_mix_mode", ["1"])[0], True),
            "force": parse_bool(fields.get("force", ["0"])[0], False),
            "workers": max(1, parse_int(fields.get("workers", ["2"])[0], 2)),
            "threads": max(1, parse_int(fields.get("threads", [str(cpus)])[0], cpus)),
            "anno_cpus": max(1, parse_int(fields.get("anno_cpus", [str(cpus)])[0], cpus)),
            "annotation_fallback_order": str(fields.get("annotation_fallback_order", ["funannotate"])[0]).strip(),
            "braker3_enabled": parse_bool(fields.get("braker3_enabled", ["0"])[0], False),
            "funannotate_busco_db": str(fields.get("funannotate_busco_db", ["dikarya"])[0]).strip(),
            "funannotate_organism_name": str(fields.get("funannotate_organism_name", ["Fungal_sp"])[0]).strip(),
            "clinker_mode": str(fields.get("clinker_mode", ["auto"])[0]).strip() or "auto",
            "panel_target_set": str(fields.get("panel_target_set", ["both"])[0]).strip() or "both",
            "clinker_use_docker_image": parse_bool(fields.get("clinker_use_docker_image", ["1"])[0], True),
            "clinker_docker_image": str(fields.get("clinker_docker_image", [""])[0]).strip(),
            "clinker_docker_data_volume": str(fields.get("clinker_docker_data_volume", [""])[0]).strip(),
            "clinker_max_regions": max(0, parse_int(fields.get("clinker_max_regions", ["0"])[0], 0)),
            "atlas_stage_limit": max(1, parse_int(fields.get("atlas_stage_limit", fields.get("shortlist_limit", ["12"]))[0], 12)),
            "atlas_min_records": max(1, parse_int(fields.get("atlas_min_records", ["2"])[0], 2)),
            "shortlist_limit": max(1, parse_int(fields.get("shortlist_limit", ["12"])[0], 12)),
            "shared_family_stage_limit": max(1, parse_int(fields.get("shared_family_stage_limit", fields.get("shortlist_limit", ["12"]))[0], 12)),
            "shared_family_min_records": max(1, parse_int(fields.get("shared_family_min_records", ["4"])[0], 4)),
            "max_comparators": max(1, parse_int(fields.get("max_comparators", ["50"])[0], 50)),
            "max_same_ecology": max(0, parse_int(fields.get("max_same_ecology", ["20"])[0], 20)),
            "max_other_ecology": max(0, parse_int(fields.get("max_other_ecology", ["20"])[0], 20)),
            "capture_external_artifacts": parse_bool(fields.get("capture_external_artifacts", ["1"])[0], True),
            "auto_normalize_metadata": parse_bool(fields.get("auto_normalize_metadata", ["1"])[0], True),
            "metadata_tsv": str(fields.get("metadata_tsv", [""])[0]).strip(),
            "auto_pull_images": str(fields.get("auto_pull_images", ["always"])[0]).strip() or "always",
            "auto_build_funbgcex_sif": parse_bool(fields.get("auto_build_funbgcex_sif", ["1"])[0], True),
            "auto_pull_bigscape_sif": parse_bool(fields.get("auto_pull_bigscape_sif", ["1"])[0], True),
            "auto_download_pfam": parse_bool(fields.get("auto_download_pfam", ["1"])[0], True),
            "auto_download_fasttree": parse_bool(fields.get("auto_download_fasttree", ["1"])[0], True),
            "mibig_auto_download": parse_bool(fields.get("mibig_auto_download", ["1"])[0], True),
            "nplinker_run_mode": str(fields.get("nplinker_run_mode", ["local"])[0]).strip() or "local",
            "nplinker_podp_id": str(fields.get("nplinker_podp_id", [""])[0]).strip(),
            "massive_dataset_id": str(fields.get("massive_dataset_id", [""])[0]).strip(),
            "target_strain": str(fields.get("target_strain", fields.get("target_genome", [""]))[0]).strip(),
            "gnps_version": str(fields.get("gnps_version", ["2"])[0]).strip() or "2",
            "auto_pull_nplinker_sif": parse_bool(fields.get("auto_pull_nplinker_sif", ["1"])[0], True),
            "nplinker_bootstrap_env": parse_bool(fields.get("nplinker_bootstrap_env", ["1"])[0], True),
            "figures_required": parse_bool(fields.get("figures_required", ["0"])[0], False),
            "env_overrides": str(fields.get("env_overrides", [""])[0]),
        }

        if not settings["clinker_docker_image"]:
            settings["clinker_docker_image"] = os.environ.get(
                "CLINKER_DOCKER_IMAGE", "quay.io/biocontainers/clinker-py:0.0.32--pyhdfd78af_0"
            )
        if not settings["clinker_docker_data_volume"]:
            settings["clinker_docker_data_volume"] = os.environ.get("CLINKER_DOCKER_DATA_VOLUME", "")
        if settings["genefinding_mode"] in {"funannotate", "braker3,funannotate"}:
            settings["annotation_fallback_order"] = settings["genefinding_mode"]
            if "braker3" in settings["genefinding_mode"]:
                settings["braker3_enabled"] = True

        runtime_error = validate_runtime_request(settings, worker_status())
        if runtime_error:
            self._send_json(HTTPStatus.CONFLICT, {"detail": runtime_error})
            return

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
            "submission_settings": dict(settings),
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

        enqueue_job(job_id, cpus, settings)

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
