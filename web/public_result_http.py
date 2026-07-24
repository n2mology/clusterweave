"""HTTP routing for opaque, capability-protected public result artifacts.

The app module imports this router, while this module resolves the active app
module lazily at request time.  That keeps the route implementation testable
without weakening the existing file-policy and stable-streaming checks.
"""

from __future__ import annotations

from http import HTTPStatus
import importlib
import re
import urllib.parse
import zipfile

from public_results import (
    bundle_reference_candidate,
    resolve_bundle_reference,
    valid_artifact_id,
)


_MAX_RESOLVE_BODY_BYTES = 8192
_GENERATED_BUNDLE_CATEGORIES = {"antismash", "funbgcex", "bigscape", "synteny"}
_OPTIONAL_BUNDLE_SUFFIXES = {
    ".css",
    ".eot",
    ".gif",
    ".htm",
    ".html",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".mjs",
    ".otf",
    ".png",
    ".svg",
    ".svgz",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
}


def _api(handler: object):
    return importlib.import_module(handler.__class__.__module__)


def _generic_not_found(handler: object) -> None:
    handler._not_found("Result not found")


def _authorized_context(handler: object, public_id: str):
    api = _api(handler)
    job = api.resolve_public_job(public_id)
    if job is None or not api.request_can_read_job(handler, job):
        _generic_not_found(handler)
        return None
    internal_id = str(job.get("id") or "")
    if not internal_id:
        _generic_not_found(handler)
        return None
    try:
        base = api.job_dir(internal_id).resolve()
    except (OSError, ValueError):
        _generic_not_found(handler)
        return None
    return api, job, base


def _catalog(api: object, job: dict[str, object], base):
    return api.artifact_catalog_for_job(
        job,
        base,
        path_validator=lambda path: api.result_file_is_publicly_servable(base, path),
    )


def _catalog_payload(public_id: str, catalog: object | None) -> dict[str, object]:
    if catalog is None:
        return {
            "run_id": public_id,
            "public_run_id": public_id,
            "generation": "",
            "result_index_state": "indexing",
            "artifacts": [],
        }
    descriptors = catalog.descriptors()
    return {
        "run_id": public_id,
        "public_run_id": public_id,
        "generation": catalog.generation,
        "result_index_state": "attested",
        "artifact_count": len(descriptors),
        "artifacts": descriptors,
    }


def handle_public_result_get(handler: object, route: str, query: dict[str, list[str]]) -> bool:
    """Handle a clean GET route, returning False only for unrelated routes."""

    if not route.startswith("/api/results/"):
        return False
    parts = route.split("/")
    if len(parts) < 4:
        _generic_not_found(handler)
        return True
    public_id = urllib.parse.unquote(parts[3])
    context = _authorized_context(handler, public_id)
    if context is None:
        return True
    api, job, base = context

    if len(parts) == 4:
        payload = api.job_payload(
            job,
            admin=False,
            include_public_events=False,
            include_results=False,
        )
        stored_results = job.get("result_files")
        payload["bigscape_viewer_available"] = (
            api.authorize_bigscape_viewer_database(job, base) is not None
        )
        result_count = (
            len(stored_results) if isinstance(stored_results, (list, tuple)) else 0
        )
        payload["result_file_count"] = result_count
        payload["result_index_state"] = "stored" if result_count else "pending"
        handler._send_json(HTTPStatus.OK, payload)
        return True

    if len(parts) == 5 and parts[4] == "activity":
        internal_id = str(job.get("id") or "")
        known_log_count = max(0, api.parse_int(job.get("log_count"), 0))
        lines = api.public_activity_projection_lines(internal_id, known_log_count)
        handler._send_json(
            HTTPStatus.OK,
            {
                "run_id": public_id,
                "public_run_id": public_id,
                "public_events": api.public_activity_from_logs(internal_id, lines),
                "genome_progress": api.public_genome_progress(
                    job, lines
                ),
            },
        )
        return True

    if len(parts) == 5 and parts[4] == "archive":
        safe_public_id = re.sub(r"[^A-Za-z0-9_-]+", "_", public_id) or "result"
        authorized_archive = api.authorize_prebuilt_public_archive(job, base)
        temporary_archive = authorized_archive is None
        expected_identity = None
        if authorized_archive is not None:
            archive_path, expected_identity = authorized_archive
        else:
            try:
                archive_path = api.build_public_archive(job, base)
            except (OSError, RuntimeError, zipfile.BadZipFile):
                handler._send_json(
                    HTTPStatus.CONFLICT,
                    {"detail": "Public results changed while the package was prepared; retry."},
                )
                return True
        try:
            handler._send_file(
                HTTPStatus.OK,
                archive_path,
                "application/zip",
                {
                    "Content-Disposition": api.content_disposition(
                        "attachment", f"{safe_public_id}_clusterweave_results.zip"
                    ),
                    "Cache-Control": "private, no-store",
                    "X-Content-Type-Options": "nosniff",
                },
                expected_identity=expected_identity,
            )
        finally:
            if temporary_archive:
                archive_path.unlink(missing_ok=True)
        return True

    if len(parts) == 5 and parts[4] == "bigscape-viewer-database":
        authorized = api.authorize_bigscape_viewer_database(job, base)
        if authorized is None:
            _generic_not_found(handler)
            return True
        full, identity = authorized
        handler._send_file(
            HTTPStatus.OK,
            full,
            "application/vnd.sqlite3",
            {
                "Content-Disposition": api.content_disposition(
                    "inline", api.PUBLIC_BIGSCAPE_VIEWER_DATABASE_FILENAME
                ),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
            expected_identity=identity,
        )
        return True

    if len(parts) < 5 or parts[4] != "artifacts":
        _generic_not_found(handler)
        return True
    catalog = _catalog(api, job, base)
    if len(parts) == 5:
        payload = _catalog_payload(public_id, catalog)
        payload["bigscape_viewer_available"] = (
            catalog is not None
            and api.authorize_bigscape_viewer_database(job, base) is not None
        )
        handler._send_json(HTTPStatus.OK, payload)
        return True
    if (
        catalog is None
        or len(parts) not in {6, 7}
        or (len(parts) == 7 and parts[6] != "download")
    ):
        _generic_not_found(handler)
        return True
    artifact_id = urllib.parse.unquote(parts[5])
    if not valid_artifact_id(artifact_id):
        _generic_not_found(handler)
        return True
    record = catalog.by_id().get(artifact_id)
    if record is None:
        _generic_not_found(handler)
        return True
    authorized = api.authorize_direct_result_file(job, base, record.path)
    if authorized is None:
        _generic_not_found(handler)
        return True
    full, identity = authorized
    disposition = "attachment" if len(parts) == 7 else "inline"
    headers = {
        "Content-Disposition": api.content_disposition(disposition, full.name),
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    descriptor = record.descriptor
    if (
        descriptor.get("kind") == "html"
        and descriptor.get("category") in _GENERATED_BUNDLE_CATEGORIES
    ):
        # Direct navigation is inert; the frontend fetches these bytes and
        # runs them only inside its opaque-origin, scripts-only sandbox.
        headers["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'"
        )
    handler._send_file(
        HTTPStatus.OK,
        full,
        api.result_file_mime(full),
        headers,
        expected_identity=identity,
    )
    return True


def handle_public_result_post(handler: object, route: str) -> bool:
    """Resolve a generated bundle reference without accepting a storage path."""

    if not route.startswith("/api/results/"):
        return False
    parts = route.split("/")
    if len(parts) != 7 or parts[4] != "artifacts" or parts[6] != "resolve":
        _generic_not_found(handler)
        return True
    public_id = urllib.parse.unquote(parts[3])
    context = _authorized_context(handler, public_id)
    if context is None:
        return True
    api, job, base = context
    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except (TypeError, ValueError):
        content_length = 0
    if content_length <= 0 or content_length > _MAX_RESOLVE_BODY_BYTES:
        _generic_not_found(handler)
        return True
    payload = api.read_json_body(handler)
    reference = payload.get("reference") if isinstance(payload, dict) else None
    if not isinstance(reference, str):
        _generic_not_found(handler)
        return True
    catalog = _catalog(api, job, base)
    owner_id = urllib.parse.unquote(parts[5])
    if catalog is None or not valid_artifact_id(owner_id):
        _generic_not_found(handler)
        return True
    owner = catalog.by_id().get(owner_id)
    if owner is None:
        _generic_not_found(handler)
        return True
    if (
        owner.descriptor.get("kind") not in {"html", "stylesheet"}
        or owner.descriptor.get("category") not in _GENERATED_BUNDLE_CATEGORIES
    ):
        _generic_not_found(handler)
        return True
    resolved = resolve_bundle_reference(catalog, owner, reference)
    if resolved is None:
        candidate = bundle_reference_candidate(owner, reference)
        if payload.get("optional") is True and candidate is not None:
            target_path, fragment = candidate
            suffix = "." + target_path.rsplit(".", 1)[-1].lower() if "." in target_path else ""
            if suffix in _OPTIONAL_BUNDLE_SUFFIXES:
                # Optional generated assets may be absent from an upstream
                # bundle. Return the same null result for missing and
                # non-attested files so callers neither create a failed
                # browser request nor gain an existence oracle.
                handler._send_json(
                    HTTPStatus.OK,
                    {"artifact": None, "fragment": fragment},
                )
                return True
        _generic_not_found(handler)
        return True
    target, fragment = resolved
    handler._send_json(
        HTTPStatus.OK,
        {"artifact": dict(target.descriptor), "fragment": fragment},
    )
    return True


__all__ = ["handle_public_result_get", "handle_public_result_post"]
