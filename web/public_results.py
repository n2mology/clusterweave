"""Opaque public identifiers and path-free result artifact descriptors."""

from __future__ import annotations

import base64
import hashlib
import hmac
import mimetypes
import os
import posixpath
import re
import secrets
import urllib.parse
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path, PurePosixPath
from typing import Any

from result_attestation import ResultAttestation
from result_policy import (
    PUBLIC_RESULTS_MANIFEST_PATH,
    normalized_job_result_path,
    result_is_public_bigscape_database,
)


PUBLIC_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
MAX_BUNDLE_REFERENCE_CHARS = 2048

_MIME_OVERRIDES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml; charset=utf-8",
    ".svgz": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".eot": "application/vnd.ms-fontobject",
    ".map": "application/json; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".sqlite": "application/vnd.sqlite3",
    ".sqlite3": "application/vnd.sqlite3",
    ".db": "application/vnd.sqlite3",
    ".zip": "application/zip",
}


def _b64_identifier(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _identifier_secret(purpose: bytes) -> bytes:
    configured = os.environ.get("CLUSTERWEAVE_JOB_TOKEN_SECRET", "")
    seed = (
        configured.encode("utf-8")
        if configured
        else b"clusterweave-local-public-result-identifiers-v1"
    )
    return hmac.new(seed, purpose, hashlib.sha256).digest()


def _opaque_hmac(purpose: bytes, *fields: str) -> str:
    message = b"\0".join(str(field).encode("utf-8") for field in fields)
    digest = hmac.new(_identifier_secret(purpose), message, hashlib.sha256).digest()
    return _b64_identifier(digest[:16])


def valid_public_run_id(value: object) -> bool:
    return bool(PUBLIC_RUN_ID_RE.fullmatch(str(value or "")))


def valid_artifact_id(value: object) -> bool:
    return bool(ARTIFACT_ID_RE.fullmatch(str(value or "")))


def generate_public_run_id() -> str:
    """Return an unguessable 128-bit identifier for a newly submitted run."""

    return _b64_identifier(secrets.token_bytes(16))


def legacy_public_run_id(internal_job_id: object) -> str:
    """Return a stable opaque alias for a job created before public IDs existed."""

    job_id = str(internal_job_id or "")
    if not job_id:
        return ""
    return _opaque_hmac(b"clusterweave-public-run-legacy-v1", job_id)


def public_run_id_for_job(job: dict[str, Any]) -> str:
    stored = str(job.get("public_run_id") or "")
    if valid_public_run_id(stored):
        return stored
    return legacy_public_run_id(job.get("id"))


def ensure_public_run_id(job: dict[str, Any], *, randomize: bool = False) -> str:
    public_id = public_run_id_for_job(job)
    if not valid_public_run_id(job.get("public_run_id")):
        public_id = generate_public_run_id() if randomize else public_id
        if public_id:
            job["public_run_id"] = public_id
    return public_id


def _analysis_parts(rel_path: str) -> tuple[list[str], int]:
    parts = normalized_job_result_path(rel_path).split("/")
    if len(parts) >= 4 and [part.lower() for part in parts[:2]] == ["data", "results"]:
        return parts[3:], 3
    return parts, 0


def _clinker_family_parts(full_parts: list[str], parts: list[str], offset: int) -> list[str]:
    """Bound clinker navigation to the exact staged panel directory."""

    if len(parts) <= 1:
        return full_parts[: offset + 1]
    if len(parts) >= 3:
        return full_parts[:-1]
    return full_parts[: offset + 1]


def _clinker_descriptor_context(rel_path: str) -> tuple[str, str, str]:
    parts, _offset = _analysis_parts(rel_path)
    lowered = [part.lower() for part in parts]
    taxon_group = ""
    genome_label = ""
    track = ""
    for candidate in ("atlas", "priority", "shared_family"):
        if candidate in lowered:
            track = candidate
            break
    for index, part in enumerate(lowered):
        if part not in {"fungi", "bacteria"}:
            continue
        taxon_group = part
        if index + 1 < len(parts) - 1:
            genome_label = parts[index + 1]
        break
    return taxon_group, genome_label, track


def _artifact_category(rel_path: str) -> tuple[str, str, str, str]:
    """Return category, display tool, genome label, and private family root."""

    full_parts = normalized_job_result_path(rel_path).split("/")
    parts, offset = _analysis_parts(rel_path)
    lower = [part.lower() for part in parts]
    if not parts:
        return "other", "", "", rel_path

    root = lower[0]
    tool = ""
    genome_label = ""
    family_parts = list(full_parts)
    if root == "antismash":
        category = "antismash"
        tool = "antiSMASH"
        if len(parts) >= 2:
            genome_label = parts[1]
            family_parts = full_parts[: offset + 2]
    elif root == "funbgcex":
        category = "funbgcex"
        tool = "FunBGCeX"
        if len(parts) >= 2:
            genome_label = parts[1]
            family_parts = full_parts[: offset + 2]
    elif root in {"big_scape", "bigscape", "big-scape"}:
        category = "bigscape"
        tool = "BiG-SCAPE"
        family_parts = full_parts[: offset + 1]
    elif root in {"clinker", "clinker_shared_family"}:
        category = "synteny"
        tool = "clinker"
        family_parts = _clinker_family_parts(full_parts, parts, offset)
    elif root == "figures":
        category = "phylogeny" if len(lower) >= 2 and lower[1] == "phylogeny" else "figures"
        family_parts = full_parts[: offset + (2 if category == "phylogeny" else 1)]
    elif root in {"summary", "summary_tables"}:
        category = "summaries"
        family_parts = full_parts[: offset + 1]
    elif root == "integrated_evidence":
        category = "evidence"
        family_parts = full_parts[: offset + 1]
    elif root == "downloads" or rel_path == PUBLIC_RESULTS_MANIFEST_PATH:
        category = "downloads"
        family_parts = full_parts[:1]
    elif root == "results":
        category = "figures"
        family_parts = full_parts[:1]
    else:
        category = "other"
        family_parts = full_parts[:1]
    return category, tool, genome_label, "/".join(family_parts)


def _artifact_mime(rel_path: str) -> str:
    suffix = Path(rel_path).suffix.lower()
    if suffix in _MIME_OVERRIDES:
        return _MIME_OVERRIDES[suffix]
    guessed, _encoding = mimetypes.guess_type(rel_path)
    return guessed or "application/octet-stream"


def _artifact_kind(path: str, mime: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".css":
        return "stylesheet"
    if suffix in {".js", ".mjs"}:
        return "script"
    if mime.startswith("image/"):
        return "image"
    if suffix in {".woff", ".woff2", ".ttf", ".eot"}:
        return "font"
    if suffix in {".sqlite", ".sqlite3", ".db"}:
        return "database"
    if suffix in {".csv", ".tsv", ".json", ".txt", ".md", ".nwk", ".graphml"}:
        return "data"
    if suffix in {".zip", ".pdf"}:
        return "document"
    return "artifact"


def _artifact_role(rel_path: str, category: str, kind: str) -> str:
    filename = Path(rel_path).name.lower()
    stem = Path(filename).stem
    if rel_path == PUBLIC_RESULTS_MANIFEST_PATH:
        return "manifest"
    if result_is_public_bigscape_database(rel_path):
        return "public-database"
    if kind == "html":
        if category == "antismash":
            if "region" in stem:
                return "region"
            return "index" if filename in {"index.html", "index.htm"} else "page"
        if category == "funbgcex":
            if stem.startswith("bgc") or "region" in stem:
                return "region"
            if filename in {
                "index.html", "index.htm", "results.html", "result.html", "allbgcs.html",
            }:
                return "index"
            return "page"
        return "index" if filename in {"index.html", "index.htm"} else "page"
    return "asset" if category in {"antismash", "funbgcex", "bigscape", "synteny"} else kind


def _artifact_label(rel_path: str, category: str, filename: str) -> str:
    """Return a concise path-free display label for one public artifact."""

    if category != "synteny" or filename.lower() not in {"panel.html", "index.html"}:
        return filename
    parts, _offset = _analysis_parts(rel_path)
    if len(parts) < 2:
        return filename
    parent = parts[-2]
    if parent.lower() in {
        "clinker", "clinker_shared_family", "panels", "atlas", "priority",
        "shared", "shared_family", "family",
    }:
        return filename
    label = re.sub(r"\s+", " ", urllib.parse.unquote(parent).replace("_", " ")).strip()
    return label[:160] if label and not any(ord(character) < 32 for character in label) else filename


def _artifact_is_listed(category: str, kind: str, role: str, rel_path: str, family_root: str) -> bool:
    """Keep large generated bundles out of the interactive catalog payload."""

    try:
        depth = len(PurePosixPath(rel_path).relative_to(PurePosixPath(family_root)).parts)
    except ValueError:
        return False
    filename = Path(rel_path).name.lower()
    if category == "antismash":
        return role == "index" and depth <= 2
    if category == "funbgcex":
        return role == "index" and (filename in {"results.html", "result.html", "allbgcs.html"} or depth <= 4)
    if category == "bigscape":
        return role == "public-database" or (role == "index" and depth <= 4)
    if category == "synteny":
        return kind == "html"
    return True


@dataclass(frozen=True)
class ArtifactRecord:
    id: str
    path: str
    digest: str
    size: int
    family_root: str
    family_id: str
    listed: bool
    descriptor: dict[str, object]


@dataclass(frozen=True)
class ArtifactCatalog:
    public_run_id: str
    generation: str
    records: tuple[ArtifactRecord, ...]

    @cached_property
    def records_by_id(self) -> dict[str, ArtifactRecord]:
        return {record.id: record for record in self.records}

    @cached_property
    def records_by_path(self) -> dict[str, ArtifactRecord]:
        return {record.path: record for record in self.records}

    def by_id(self) -> dict[str, ArtifactRecord]:
        return self.records_by_id

    def by_path(self) -> dict[str, ArtifactRecord]:
        return self.records_by_path

    @cached_property
    def public_descriptors(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(record.descriptor) for record in self.records if record.listed)

    def descriptors(self) -> list[dict[str, object]]:
        return [dict(descriptor) for descriptor in self.public_descriptors]


def build_artifact_catalog(
    job: dict[str, Any],
    attestation: ResultAttestation,
    *,
    manifest_size: int = 0,
) -> ArtifactCatalog:
    internal_job_id = str(job.get("id") or "")
    public_id = public_run_id_for_job(job)
    if not internal_job_id or not valid_public_run_id(public_id):
        raise ValueError("job does not have a valid public result identity")
    if attestation.job_id != internal_job_id:
        raise ValueError("result attestation belongs to another job")

    rows: list[tuple[str, int, str]] = [
        (PUBLIC_RESULTS_MANIFEST_PATH, max(0, int(manifest_size)), attestation.manifest_sha256),
        *attestation.files,
    ]
    records: list[ArtifactRecord] = []
    seen_ids: set[str] = set()
    for rel_path, size, digest in rows:
        normalized = normalized_job_result_path(rel_path)
        if not normalized:
            continue
        artifact_id = _opaque_hmac(
            b"clusterweave-public-artifact-v1",
            internal_job_id,
            public_id,
            attestation.generation,
            normalized,
            digest,
        )
        if artifact_id in seen_ids:
            raise ValueError("opaque artifact identifier collision")
        seen_ids.add(artifact_id)
        category, tool, genome_label, family_root = _artifact_category(normalized)
        family_id = _opaque_hmac(
            b"clusterweave-public-artifact-family-v1",
            internal_job_id,
            public_id,
            attestation.generation,
            family_root,
        )
        mime = _artifact_mime(normalized)
        kind = _artifact_kind(normalized, mime)
        role = _artifact_role(normalized, category, kind)
        filename = Path(normalized).name or "artifact"
        descriptor: dict[str, object] = {
            "id": artifact_id,
            "filename": filename,
            "label": _artifact_label(normalized, category, filename),
            "bytes": max(0, int(size)),
            "mime": mime,
            "category": category,
            "kind": kind,
            "role": role,
            "bundle_id": family_id,
            "pair_id": family_id,
            "previewable": kind in {"html", "image", "data", "document"},
            "downloadable": True,
        }
        if tool:
            descriptor["tool"] = tool
        if category == "synteny":
            clinker_taxon, clinker_genome, clinker_track = _clinker_descriptor_context(normalized)
            if clinker_taxon:
                descriptor["taxon_group"] = clinker_taxon
            if clinker_genome:
                genome_label = clinker_genome
            if clinker_track:
                descriptor["track"] = clinker_track
        if genome_label:
            descriptor["genome_label"] = genome_label
        records.append(
            ArtifactRecord(
                artifact_id,
                normalized,
                digest,
                int(size),
                family_root,
                family_id,
                _artifact_is_listed(category, kind, role, normalized, family_root),
                descriptor,
            )
        )
    return ArtifactCatalog(public_id, attestation.generation, tuple(records))


def bundle_reference_candidate(
    owner: ArtifactRecord,
    reference: object,
) -> tuple[str, str] | None:
    """Normalize one bundle reference while enforcing its family boundary."""

    raw = str(reference or "")
    if not raw or len(raw) > MAX_BUNDLE_REFERENCE_CHARS:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        return None
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc:
        return None
    decoded_path = urllib.parse.unquote(parsed.path)
    if "\\" in decoded_path or decoded_path.startswith("/") or "\x00" in decoded_path:
        return None
    candidate = (
        posixpath.normpath(posixpath.join(posixpath.dirname(owner.path), decoded_path))
        if decoded_path
        else owner.path
    )
    candidate = normalized_job_result_path(candidate)
    if not candidate:
        return None
    try:
        PurePosixPath(candidate).relative_to(PurePosixPath(owner.family_root))
    except ValueError:
        return None
    fragment = urllib.parse.unquote(parsed.fragment)
    if len(fragment) > 512 or any(
        ord(character) < 32 or ord(character) == 127 for character in fragment
    ):
        return None
    return candidate, (f"#{fragment}" if fragment else "")


def resolve_bundle_reference(
    catalog: ArtifactCatalog,
    owner: ArtifactRecord,
    reference: object,
) -> tuple[ArtifactRecord, str] | None:
    """Resolve one generated-page reference inside its attested tool family."""

    candidate = bundle_reference_candidate(owner, reference)
    if candidate is None:
        return None
    target_path, fragment = candidate
    target = catalog.by_path().get(target_path)
    if target is None or not hmac.compare_digest(target.family_id, owner.family_id):
        return None
    return target, fragment


__all__ = [
    "ARTIFACT_ID_RE",
    "ArtifactCatalog",
    "ArtifactRecord",
    "PUBLIC_RUN_ID_RE",
    "bundle_reference_candidate",
    "build_artifact_catalog",
    "ensure_public_run_id",
    "generate_public_run_id",
    "legacy_public_run_id",
    "public_run_id_for_job",
    "resolve_bundle_reference",
    "valid_artifact_id",
    "valid_public_run_id",
]
