#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import csv
import hashlib
import os
import re
import secrets
import shutil
import signal
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from bigscape_public_db import (
    DEFAULT_MAX_SOURCE_BYTES as DEFAULT_PUBLIC_BIGSCAPE_MAX_BYTES,
    prepare_public_bigscape_databases,
)
from genbank_readiness import inspect_genbank_translation_stream
from result_attestation import write_result_attestation
from result_policy import (
    PUBLIC_EVIDENCE_MANIFEST_PATH,
    PUBLIC_RESULTS_MANIFEST_PATH,
    is_public_analysis_relative_path,
    public_archive_entry_name,
    public_evidence_role,
    result_is_public_bigscape_database,
)
from taxon_routing import (
    build_taxon_routes,
    merge_assignments,
    normalize_analysis_scope,
    parse_assignment_json,
    parse_genbank_taxonomy_stream,
)


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CLUSTERWEAVE_ROOT = Path(os.environ.get("CLUSTERWEAVE_ROOT", "/clusterweave"))
GLOBAL_SOFTWARE_ROOT = Path(os.environ.get("CLUSTERWEAVE_SOFTWARE_ROOT", str(DATA_DIR / "software")))

GENOME_EXTS = {".gbk", ".gb", ".gbff", ".fasta", ".fa", ".fna", ".fsa"}
ACCESSION_EXTS = {".txt", ".tsv", ".csv"}
METADATA_EXTS = {".tsv", ".csv"}
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SENSITIVE_ENV_KEY_RE = re.compile(
    r"(?:^|_)(?:AUTH|AUTHORIZATION|COOKIE|CREDENTIALS?|PASS(?:WORD|WD)?|PRIVATE_KEY|SECRET|SIGNATURE|TOKEN)(?:_|$)|(?:ACCESS|API)[_-]?KEY|DOCKER_AUTH_CONFIG",
    re.IGNORECASE,
)
SENSITIVE_LOG_ASSIGNMENT_RE = re.compile(
    r"(?ix)(?<![A-Za-z0-9])"
    r"((?:--?)?(?:[A-Za-z0-9_.-]+[_-])?"
    r"(?:api[_-]?key|auth(?:orization)?|cookie|credential|pass(?:word|wd)?|private[_-]?key|secret|signature|token)"
    r"(?:[_-][A-Za-z0-9_.-]+)?\s*[:=]\s*)"
    r"([^\s;&]+)"
)
SENSITIVE_LOG_CLI_RE = re.compile(
    r"(?ix)(?<![A-Za-z0-9])"
    r"((?:--?)?(?:api[_-]?key|auth(?:orization)?|cookie|credential|pass(?:word|wd)?|private[_-]?key|secret|signature|token))"
    r"(\s+)"
    r"(\"[^\"]*\"|'[^']*'|[^\s;&]+)"
)
SENSITIVE_LOG_QUERY_RE = re.compile(
    r"(?i)([?&](?:access[_-]?token|api[_-]?key|auth[_-]?token|credential|expires|key-pair-id|policy|read[_-]?token|sig|signature|token|x-amz-credential|x-amz-signature|x-goog-credential|x-goog-signature)=)([^&#\s]+)"
)
SENSITIVE_LOG_HEADER_RE = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*([^\r\n]+)"
)
PRIVATE_JOB_PATH_RE = re.compile(
    rf"(?i)(?:file://)?{re.escape(str(DATA_DIR / 'jobs'))}/"
    r"[^\s\"'<>\)\]\},;]+"
)
TAXON_ROUTE_FIELDS = [
    "input_key",
    "genome_id",
    "taxon_group",
    "taxon_source",
    "taxid",
    "organism_name",
    "source_accession",
    "prediction_method",
    "detector_profile",
    "input_path_key",
    "route_status",
    "route_reason",
]
TAXONOMY_RANK_FIELDS = [
    "domain",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
]
TAXONOMY_METADATA_FIELDS = [
    "genome_id",
    "taxon_group",
    "taxon_source",
    "taxid",
    "organism_name",
    "source_accession",
    "lineage_names",
    "lineage_ids",
    *TAXONOMY_RANK_FIELDS,
]
AUTHORITATIVE_TAXON_SOURCES = {
    "genbank_source",
    "ncbi",
    "ncbi_taxonomy",
}
INACTIVE_ROUTE_STATUSES = {"failed", "invalid", "rejected", "unresolved", "unsupported"}

# Raw administrator overrides are useful for tool-specific experimentation, but
# execution-shape keys must stay identical to the plan admitted by the worker.
# Keep this defense in depth here as persisted jobs may predate the web/API
# validation that rejects the same keys.
RESOURCE_ENV_KEYS = {
    "CPUS",
    "THREADS",
    "ANNO_CPUS",
    "WORKERS",
    "GENOME_PARALLELISM",
    "ANNOTATION_GENOME_PARALLELISM",
    "ANTISMASH_RECORD_PARALLELISM",
    "ANTISMASH_SHARD_CPUS",
    "ANTISMASH_LEGACY_CPUS",
    "RUN_PHYLOGENY",
    "PHYLOGENY_REQUIRED",
    "PHYLOGENY_AUTO_PREPARE",
    "PHYLOGENY_AUTO_SELECT_CANDIDATES",
    "PHYLOGENY_PREPARE_HELPER",
    "PHYLOGENY_CANDIDATE_SELECTOR",
    "PHYLOGENY_CANDIDATES_TSV",
    "PHYLOGENY_CROSSWALK_TSV",
    "PHYLOGENY_ANTISMASH_ROOT",
    "PHYLOGENY_SEQUENCE_MAP",
    "PHYLOGENY_TOPOLOGY_RESULTS_TSV",
    "PHYLOGENY_MAX_CANDIDATES",
    "PHYLOGENY_MAX_REGIONS_PER_CANDIDATE",
    "PHYLOGENY_MAX_REGION_BYTES",
    "PHYLOGENY_MAX_INPUT_BYTES",
    "PHYLOGENY_MAX_PREPARED_BYTES",
    "PHYLOGENY_CPUS",
    "PHYLOGENY_PARALLELISM",
    "PHYLOGENY_MAX_FAMILIES",
    "PHYLOGENY_MAX_SEQUENCES_PER_FAMILY",
    "PHYLOGENY_MAX_ALIGNMENT_BYTES",
    "PHYLOGENY_TIMEOUT_SECONDS",
    "PHYLOGENY_RETAIN_SCRATCH",
    "PHYLOGENY_INPUT_ROOT",
    "PHYLOGENY_FAMILY_MANIFEST",
    "PHYLOGENY_RESULTS_ROOT",
    "PHYLOGENY_WORK_ROOT",
    "PHYLOGENY_LOG_ROOT",
    "PHYLOGENY_MANIFEST_TSV",
    "PHYLOGENY_MANIFEST_JSON",
    "PHYLOGENY_RUNTIME",
    "PHYLOGENY_DOCKER_IMAGE",
    "PHYLOGENY_SIF_PATH",
    "RUN_CROSS_KINGDOM_EVIDENCE",
    "CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES",
    "CROSS_KINGDOM_EVIDENCE_CANDIDATES",
    "CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV",
    "CROSS_KINGDOM_EVIDENCE_AUTO_SELECT",
    "CROSS_KINGDOM_EVIDENCE_CROSSWALK_TSV",
    "CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR",
    "CROSS_KINGDOM_EVIDENCE_WORK_ROOT",
    "CROSS_KINGDOM_EVIDENCE_STAGING_DIR",
    "CROSS_KINGDOM_EVIDENCE_PREVIOUS_DIR",
    "CROSS_KINGDOM_EVIDENCE_LOG_ROOT",
    "CROSS_KINGDOM_EVIDENCE_LOGFILE",
    "CROSS_KINGDOM_EVIDENCE_STATUS_MANIFEST",
    "CROSS_KINGDOM_EVIDENCE_BUILDER",
    "CROSS_KINGDOM_EVIDENCE_SELECTOR",
    "CROSS_KINGDOM_EVIDENCE_TOPOLOGY_TSV",
    "CROSS_KINGDOM_EVIDENCE_TOPOLOGY_MERGER",
    "CROSS_KINGDOM_EVIDENCE_ENRICHED_CANDIDATES_TSV",
    "CROSS_KINGDOM_EVIDENCE_CONTEXT_ENRICHER",
    "CROSS_KINGDOM_EVIDENCE_CONTEXT_CANDIDATES_TSV",
    "CROSS_KINGDOM_EVIDENCE_RANKING_TSV",
    "CROSS_KINGDOM_EVIDENCE_TAXON_MANIFEST",
    "CROSS_KINGDOM_EVIDENCE_ANTISMASH_ROOT",
    "CROSS_KINGDOM_EVIDENCE_CLINKER_ROOT",
    "CROSS_KINGDOM_EVIDENCE_GENOMES_ROOT",
    # Historical administrator keys remain blocked from raw override and are
    # consumed only as compatibility fallbacks by canonical settings readers.
    "RUN_HGT_EVIDENCE",
    "HGT_EVIDENCE_MAX_CANDIDATES",
    "HGT_EVIDENCE_CANDIDATES",
    "HGT_EVIDENCE_CANDIDATES_TSV",
    "HGT_EVIDENCE_AUTO_SELECT",
    "HGT_EVIDENCE_CROSSWALK_TSV",
    "HGT_EVIDENCE_OUTPUT_DIR",
    "HGT_EVIDENCE_WORK_ROOT",
    "HGT_EVIDENCE_STAGING_DIR",
    "HGT_EVIDENCE_PREVIOUS_DIR",
    "HGT_EVIDENCE_LOG_ROOT",
    "HGT_EVIDENCE_LOGFILE",
    "HGT_EVIDENCE_STATUS_MANIFEST",
    "HGT_EVIDENCE_BUILDER",
    "HGT_EVIDENCE_SELECTOR",
    "HGT_EVIDENCE_TOPOLOGY_TSV",
    "HGT_EVIDENCE_TOPOLOGY_MERGER",
    "HGT_EVIDENCE_ENRICHED_CANDIDATES_TSV",
    "HGT_EVIDENCE_CONTEXT_ENRICHER",
    "HGT_EVIDENCE_CONTEXT_CANDIDATES_TSV",
    "HGT_EVIDENCE_RANKING_TSV",
    "HGT_EVIDENCE_TAXON_MANIFEST",
    "HGT_EVIDENCE_ANTISMASH_ROOT",
    "HGT_EVIDENCE_CLINKER_ROOT",
    "HGT_EVIDENCE_GENOMES_ROOT",
    "PIPELINE_RESOURCE_MODE",
    "PIPELINE_MEMORY_BUDGET_MB",
    "PIPELINE_AUTO_MAX_CPUS",
    "PIPELINE_AUTO_MAX_GENOME_PARALLELISM",
    "PIPELINE_AUTO_MIN_CPUS_PER_GENOME",
    "PIPELINE_AUTO_MEMORY_PERCENT",
    "PIPELINE_AUTO_MEMORY_PER_GENOME_MB",
    "PIPELINE_AUTO_MAX_ANNO_CPUS",
    "PIPELINE_AUTO_MAX_FUNBGCEX_WORKERS",
    "PIPELINE_AUTO_MAX_ANTISMASH_RECORD_PARALLELISM",
    "CLUSTERWEAVE_TOOL_DOCKER_CPUS",
    "CLUSTERWEAVE_TOOL_DOCKER_MEMORY",
    "CLUSTERWEAVE_TOOL_DOCKER_PIDS_LIMIT",
    "CLUSTERWEAVE_CHILD_DOCKER_CPUS",
    "CLUSTERWEAVE_CHILD_DOCKER_MEMORY",
    "CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT",
    "CLUSTERWEAVE_NUMERIC_LIBRARY_THREADS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
}


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    name: str
    status: JobStatus = JobStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    stage: str = "queued"
    log_lines: list[str] = field(default_factory=list)
    result_files: list[str] = field(default_factory=list)
    bigscape_viewer_database: str = ""
    error: Optional[str] = None
    project_name: str = ""
    result_root: str = ""
    on_change: Optional[Callable[[], None]] = field(default=None, repr=False, compare=False)
    _redacting_private_key: bool = field(default=False, repr=False, compare=False)
    _synced_log_count: int = field(default=0, repr=False, compare=False)

    def add_log(self, line: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        safe_line, self._redacting_private_key = _sanitize_stored_log_line(
            line, self._redacting_private_key
        )
        self.log_lines.append(f"[{ts}] {safe_line}")
        self.updated_at = datetime.now().isoformat()
        if self.on_change:
            self.on_change()

    def set_stage(self, stage: str) -> None:
        self.stage = stage
        self.add_log(f"=== Stage: {stage} ===")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "stage": self.stage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "log_count": len(self.log_lines),
            "result_files": self.result_files,
            "bigscape_viewer_database": self.bigscape_viewer_database,
            "error": self.error,
            "project_name": self.project_name,
            "result_root": self.result_root,
        }


@dataclass(init=False)
class ProjectLayout:
    project_name: str
    repo_root: Path
    data_root: Path
    fungi_genome_root: Path
    bacteria_genome_root: Path
    results_root: Path
    software_root: Path
    work_root: Path
    downloads_root: Path
    accession_file: Optional[Path] = None
    metadata_file: Optional[Path] = None
    nplinker_gnps_dir: Optional[Path] = None
    nplinker_strain_mapping: Optional[Path] = None
    genome_inputs: list[Path] = field(default_factory=list)

    def __init__(
        self,
        project_name: str,
        repo_root: Path,
        data_root: Path,
        results_root: Path,
        software_root: Path,
        work_root: Path,
        downloads_root: Path,
        genome_root: Optional[Path] = None,
        fungi_genome_root: Optional[Path] = None,
        bacteria_genome_root: Optional[Path] = None,
        accession_file: Optional[Path] = None,
        metadata_file: Optional[Path] = None,
        nplinker_gnps_dir: Optional[Path] = None,
        nplinker_strain_mapping: Optional[Path] = None,
        genome_inputs: Optional[list[Path]] = None,
    ) -> None:
        self.project_name = project_name
        self.repo_root = repo_root
        self.data_root = data_root
        self.fungi_genome_root = fungi_genome_root or genome_root or (
            data_root / "genomes" / "fungi" / project_name
        )
        self.bacteria_genome_root = bacteria_genome_root or (
            data_root / "genomes" / "bacteria" / project_name
        )
        self.results_root = results_root
        self.software_root = software_root
        self.work_root = work_root
        self.downloads_root = downloads_root
        self.accession_file = accession_file
        self.metadata_file = metadata_file
        self.nplinker_gnps_dir = nplinker_gnps_dir
        self.nplinker_strain_mapping = nplinker_strain_mapping
        self.genome_inputs = list(genome_inputs or [])

    @property
    def genome_root(self) -> Path:
        """Compatibility accessor for the historical fungal-only layout."""

        return self.fungi_genome_root

    def root_for_taxon(self, taxon_group: str) -> Path:
        return self.bacteria_genome_root if taxon_group == "bacteria" else self.fungi_genome_root

    @property
    def genome_roots(self) -> tuple[Path, Path]:
        return self.fungi_genome_root, self.bacteria_genome_root


def _job_cancel_path(job: Job) -> Path:
    return DATA_DIR / "jobs" / job.id / "cancel.requested"


def _job_cancel_requested(job: Job) -> bool:
    return _job_cancel_path(job).exists()


def _raise_if_cancelled(job: Job) -> None:
    if _job_cancel_requested(job):
        job.add_log("Cancellation marker found; stopping before the next workflow step.")
        raise asyncio.CancelledError("Cancelled by administrator")


def _sensitive_env_key(value: object) -> bool:
    return bool(SENSITIVE_ENV_KEY_RE.search(str(value or "")))


def _child_process_env(explicit: dict[str, str]) -> dict[str, str]:
    inherited = {
        str(key): str(value)
        for key, value in os.environ.items()
        if not _sensitive_env_key(key)
    }
    inherited.update(
        {
            str(key): str(value)
            for key, value in explicit.items()
            if not _sensitive_env_key(key)
        }
    )
    return inherited


def _sanitize_stored_log_line(
    value: object, private_key_block: bool = False
) -> tuple[str, bool]:
    text = str(value or "").replace("\x00", "").replace("\r", " ").replace("\n", " ")
    if re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", text, re.IGNORECASE):
        return "[private key redacted]", True
    if private_key_block:
        ended = bool(
            re.search(r"-----END [A-Z ]*PRIVATE KEY-----", text, re.IGNORECASE)
        )
        return "[private key redacted]", not ended
    if re.search(r"-----END [A-Z ]*PRIVATE KEY-----", text, re.IGNORECASE):
        return "[private key redacted]", False
    text = SENSITIVE_LOG_HEADER_RE.sub(lambda match: f"{match.group(1)}: [redacted]", text)
    text = SENSITIVE_LOG_QUERY_RE.sub(lambda match: f"{match.group(1)}[redacted]", text)
    text = SENSITIVE_LOG_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}[redacted]", text
    )
    text = SENSITIVE_LOG_CLI_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text
    )
    text = re.sub(
        r"(?i)(://)([^/@\s:]+):([^/@\s]+)@", r"\1[redacted]@", text
    )
    text = PRIVATE_JOB_PATH_RE.sub("[private job path]", text)
    text = re.sub(
        r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{4,}", "Bearer [redacted]", text
    )
    compact = re.sub(r"\s+", "", text)
    if len(compact) >= 40 and re.fullmatch(r"[ACGTUNRYSWKMBDHV.-]+", compact, re.IGNORECASE):
        text = "[raw nucleotide sequence redacted]"
    elif (
        len(compact) >= 40
        and re.fullmatch(
            r"[ACDEFGHIKLMNPQRSTVWYBXZJUO*.-]+", compact, re.IGNORECASE
        )
        and _has_raw_protein_sequence_layout(text)
    ):
        text = "[raw protein sequence redacted]"
    return text[:4096], False


def _has_raw_protein_sequence_layout(value: str) -> bool:
    """Distinguish sequence-only lines from ordinary prose.

    The extended amino-acid alphabet spans every English letter, so alphabet
    membership alone cannot identify a protein sequence. Raw tool output is
    either one uninterrupted sequence token or fixed-width uppercase chunks;
    normal workflow messages contain mixed-case, variable-width words.
    """

    text = str(value or "").strip()
    chunks = re.split(r"\s+", text) if text else []
    if len(chunks) <= 1:
        return bool(chunks)
    if text != text.upper():
        return False
    width = len(chunks[0])
    return (
        width >= 10
        and all(len(chunk) == width for chunk in chunks[:-1])
        and 1 <= len(chunks[-1]) <= width
    )


def _safe_command_log(cmd: list[str]) -> str:
    safe: list[str] = []
    redact_next = False
    for item in (str(part) for part in cmd):
        if redact_next:
            safe.append("[inline-code-redacted]")
            redact_next = False
            continue
        if item in {"-c", "--command", "--eval"}:
            safe.append(item)
            redact_next = True
            continue
        sanitized, _ = _sanitize_stored_log_line(item)
        safe.append(sanitized if len(sanitized) <= 512 else "[argument-redacted]")
    return "$ " + " ".join(safe)


async def _stream_cmd(cmd: list[str], cwd: Path, job: Job, env: dict[str, str]) -> int:
    _raise_if_cancelled(job)
    job.add_log(_safe_command_log(cmd))
    proc_env = _child_process_env(env)
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *[str(item) for item in cmd],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd),
            env=proc_env,
            start_new_session=True,
        )
        assert proc.stdout is not None
        async for raw_line in proc.stdout:
            _raise_if_cancelled(job)
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                public_stage = _public_stage_from_stream_line(line)
                if public_stage:
                    job.stage = public_stage
                job.add_log(line)
        rc = await proc.wait()
        _raise_if_cancelled(job)
        return rc
    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            job.add_log("Cancellation requested; terminating active workflow process group.")
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=15)
            except asyncio.TimeoutError:
                job.add_log("Cancellation timeout; killing active workflow process group.")
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await proc.wait()
        raise
    except FileNotFoundError as exc:
        job.add_log(f"ERROR: command not found: {exc}")
        return 127


def _public_stage_from_stream_line(line: str) -> str | None:
    """Return a sanitized stage label derived from known canonical script markers."""
    if re.search(r"Stage 1/4:\s+running run_annotation_and_detection\.sh", line, re.IGNORECASE):
        return "Running annotation / BGC detection"
    if re.search(r"Stage 2/4:\s+running run_bigscape\.sh", line, re.IGNORECASE):
        return "Running BiG-SCAPE family graph"
    if re.search(r"Stage 3/4:\s+running summarize_clusterweave\.sh", line, re.IGNORECASE):
        return "Building summary tables"
    if re.search(r"Stage 4/4:\s+running run_clinker\.sh", line, re.IGNORECASE):
        return "Staging synteny panels"
    return None


def _stage_failure_summary(job: Job) -> str:
    for raw in reversed(job.log_lines[-24:]):
        text = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", str(raw or "")).strip()
        if not text:
            continue
        if re.search(r"\b(ERROR|FATAL|FAIL)\b|not found|failed|exit code", text, re.IGNORECASE):
            text = re.sub(r"\s+", " ", text)
            return text[:180]
    return ""


async def _run_required_stage(job: Job, stage: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
    _raise_if_cancelled(job)
    job.set_stage(stage)
    rc = await _stream_cmd(cmd, cwd=cwd, job=job, env=env)
    _raise_if_cancelled(job)
    if rc != 0:
        summary = _stage_failure_summary(job)
        detail = f": {summary}" if summary else ""
        raise RuntimeError(f"{stage} failed with exit code {rc}{detail}")


async def _run_optional_stage(job: Job, stage: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> bool:
    _raise_if_cancelled(job)
    job.set_stage(stage)
    rc = await _stream_cmd(cmd, cwd=cwd, job=job, env=env)
    _raise_if_cancelled(job)
    if rc != 0:
        job.add_log(f"WARN: optional stage '{stage}' failed with exit code {rc}; continuing.")
        return False
    return True


def _safe_project_name(value: str) -> str:
    value = (value or "my_project").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return value or "my_project"


def _cfg_bool(settings: dict[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip() == "":
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _cfg_int(settings: dict[str, Any], key: str, default: int) -> int:
    value = settings.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cfg_bounded_int(
    settings: dict[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    return max(minimum, min(maximum, _cfg_int(settings, key, default)))


def _cfg_str(settings: dict[str, Any], key: str, default: str = "") -> str:
    value = settings.get(key, default)
    return str(value).strip() if value is not None else default


def _web_safe_annotation_order(value: str) -> str:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    allowed = [part for part in parts if part.lower() not in {"braker3", "braker"}]
    return ",".join(allowed) or "funannotate"


def _first_noncomment_line(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                line = raw.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        return ""
    return ""


def _looks_like_accession_file(path: Path) -> bool:
    if path.suffix.lower() not in ACCESSION_EXTS:
        return False
    if "accession" in path.name.lower():
        return True
    first = _first_noncomment_line(path)
    if not first:
        return False
    token = re.split(r"[\s,]+", first)[0]
    return bool(re.match(r"^(GC[AF]_|NZ_|GCA_|GCF_)[A-Za-z0-9_.-]+$", token))


def _looks_like_metadata_file(path: Path) -> bool:
    if path.suffix.lower() not in METADATA_EXTS:
        return False
    name = path.name.lower()
    if any(token in name for token in ["metadata", "ecofun", "ecology"]):
        return True
    first = _first_noncomment_line(path).lower()
    return "genome_id_current" in first and "ecofun" in first


def _looks_like_strain_mapping(path: Path) -> bool:
    return path.suffix.lower() == ".json" and "strain" in path.name.lower() and "mapping" in path.name.lower()


def _copy_unique(src: Path, dest_dir: Path, dest_name: str | None = None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / (dest_name or src.name)
    if not target.exists():
        shutil.copy2(src, target)
        return target
    stem = target.stem
    suffix = target.suffix
    idx = 2
    while True:
        candidate = dest_dir / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            shutil.copy2(src, candidate)
            return candidate
        idx += 1


def _analysis_scope(settings: dict[str, Any]) -> str:
    return normalize_analysis_scope(settings.get("analysis_scope"))


def _safe_genome_id(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("._-")[:120]
    if not text:
        raise ValueError("Taxon route is missing a safe genome_id")
    if text.startswith("-"):
        text = f"genome_{text.lstrip('-')}"
    return text


def _safe_manifest_text(value: object, *, limit: int = 500) -> str:
    text = re.sub(r"[\t\r\n]+", " ", str(value or "")).strip()
    return text[:limit]


_PUBLIC_SOURCE_ACCESSION_RE = re.compile(
    r"^(?:GC[AF]|NZ)_[A-Z0-9][A-Z0-9._-]{3,158}$"
)


def _public_source_accession(value: object) -> str:
    """Return a public accession token, never an arbitrary metadata value."""

    text = _safe_manifest_text(value, limit=160).upper()
    return text if _PUBLIC_SOURCE_ACCESSION_RE.fullmatch(text) else ""


def _safe_input_path_key(value: object) -> str:
    text = _safe_manifest_text(value, limit=240).replace("\\", "/").lstrip("/")
    parts = [part for part in text.split("/") if part not in {"", ".", ".."}]
    return "/".join(parts)


def _normalize_taxon_routes(settings: dict[str, Any]) -> list[dict[str, str]]:
    raw_routes = settings.get("taxon_routes")
    if not isinstance(raw_routes, list):
        return []

    rows: list[dict[str, str]] = []
    for raw in raw_routes:
        if not isinstance(raw, dict):
            raise ValueError("Each taxon route must be an object")
        row = {field: _safe_manifest_text(raw.get(field)) for field in TAXON_ROUTE_FIELDS}
        row["taxon_group"] = row["taxon_group"].lower()
        if row["taxon_group"] not in {"fungi", "bacteria"}:
            raise ValueError(f"Unsupported taxon_group in route: {row['taxon_group'] or 'missing'}")
        row["genome_id"] = _safe_genome_id(row["genome_id"] or row["input_key"])
        row["input_path_key"] = _safe_input_path_key(row["input_path_key"])
        row["taxon_source"] = row["taxon_source"] or "legacy_default"
        row["prediction_method"] = row["prediction_method"] or (
            "prodigal" if row["taxon_group"] == "bacteria" else "funannotate"
        )
        row["detector_profile"] = row["detector_profile"] or (
            "antismash" if row["taxon_group"] == "bacteria" else "antismash+funbgcex"
        )
        row["route_status"] = (row["route_status"] or "routed").lower()
        rows.append(row)

    by_id: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        by_id.setdefault(row["genome_id"].casefold(), []).append(index)
    for indexes in by_id.values():
        if len(indexes) <= 1:
            continue
        duplicate = rows[indexes[0]]["genome_id"]
        raise ValueError(f"Duplicate genome_id in immutable taxon routes: {duplicate}")

    seen: set[str] = set()
    for row in rows:
        folded = row["genome_id"].casefold()
        if folded in seen:
            raise ValueError(f"Taxon route genome_id remains ambiguous: {row['genome_id']}")
        seen.add(folded)
    return rows


def _route_active(row: dict[str, str]) -> bool:
    return row.get("route_status", "").lower() not in INACTIVE_ROUTE_STATUSES


def _route_summaries(routes: list[dict[str, str]]) -> tuple[dict[str, int], dict[str, int]]:
    active = [row for row in routes if _route_active(row)]
    fungi = sum(1 for row in active if row["taxon_group"] == "fungi")
    bacteria = sum(1 for row in active if row["taxon_group"] == "bacteria")
    total = fungi + bacteria
    taxon_counts = {"fungi": fungi, "bacteria": bacteria, "total": total}
    applicability_counts = {
        "funannotate": sum(
            1 for row in active if row.get("prediction_method") == "funannotate"
        ),
        "prodigal": sum(
            1 for row in active if row.get("prediction_method") == "prodigal"
        ),
        "antismash": total,
        "funbgcex": fungi,
        "funbgcex_not_applicable_taxon": bacteria,
        "bigscape": total,
        "taxon_tree_figure": total,
    }
    return taxon_counts, applicability_counts


def _logical_input_stem(value: object) -> str:
    name = Path(str(value or "").replace("\\", "/")).name
    lower = name.lower()
    for suffix in sorted(GENOME_EXTS, key=len, reverse=True):
        if lower.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.casefold()


def _route_for_input(src: Path, routes: list[dict[str, str]]) -> dict[str, str] | None:
    source_stem = _logical_input_stem(src.name)
    matches: list[dict[str, str]] = []
    for row in routes:
        candidates = {
            _logical_input_stem(row.get("input_key")),
            _logical_input_stem(row.get("input_path_key")),
            _logical_input_stem(row.get("genome_id")),
        }
        candidates.discard("")
        if source_stem in candidates:
            matches.append(row)
    unique = {row["genome_id"].casefold(): row for row in matches}
    if len(unique) > 1:
        raise ValueError(f"Input '{src.name}' matches multiple immutable taxon routes")
    return next(iter(unique.values()), None)


def _direct_upload_taxon_routes(
    input_files: list[Path],
    settings: dict[str, Any],
    *,
    scope_was_explicit: bool,
) -> list[dict[str, str]]:
    """Build direct/CLI upload routes through the same authority as the API."""

    logical_inputs_by_key: dict[str, dict[str, object]] = {}
    raw_stems_by_key: dict[str, str] = {}
    for src in input_files:
        suffix = src.suffix.lower()
        if suffix not in GENOME_EXTS:
            continue

        raw_stem = src.name[: -len(suffix)] if suffix else src.name
        input_key = _safe_genome_id(raw_stem)
        normalized = input_key.casefold()
        previous_raw_stem = raw_stems_by_key.get(normalized)
        if (
            previous_raw_stem is not None
            and previous_raw_stem.casefold() != raw_stem.casefold()
        ):
            raise ValueError(
                f"Genome filenames collapse to the same safe input_key '{input_key}'"
            )
        raw_stems_by_key.setdefault(normalized, raw_stem)
        logical_input = logical_inputs_by_key.setdefault(
            normalized,
            {
                "input_key": input_key,
                "has_annotated_genbank": False,
                "authoritative_taxonomy": None,
            },
        )
        if suffix not in {".gb", ".gbk", ".gbff"}:
            continue

        with src.open("rb") as handle:
            readiness = inspect_genbank_translation_stream(handle)
        logical_input["has_annotated_genbank"] = readiness.usable_translated_cds
        with src.open("rb") as handle:
            authority = parse_genbank_taxonomy_stream(handle)
        if authority is None:
            continue
        previous = logical_input.get("authoritative_taxonomy")
        if (
            isinstance(previous, Mapping)
            and previous.get("taxon_group") != authority.get("taxon_group")
        ):
            raise ValueError(
                f"Same-stem GenBank inputs for '{input_key}' contain conflicting authoritative taxonomy"
            )
        logical_input["authoritative_taxonomy"] = previous or authority

    assignments = merge_assignments(
        parse_assignment_json(settings.get("taxon_assignments")),
        parse_assignment_json(settings.get("taxon_assignments_json")),
    )
    routes = build_taxon_routes(
        settings.get("analysis_scope"),
        [logical_inputs_by_key[key] for key in sorted(logical_inputs_by_key)],
        [],
        assignments,
    )
    if not scope_was_explicit:
        for route in routes:
            if route.get("taxon_source") != "user_declaration":
                continue
            route["taxon_source"] = "legacy_default"
            route["route_reason"] = "historical fungal compatibility default"
    return _normalize_taxon_routes({"taxon_routes": routes})


def _write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _taxonomy_key_variants(value: object) -> tuple[str, ...]:
    text = _safe_manifest_text(value, limit=160).casefold()
    return (text,) if text else ()


def _taxonomy_metadata_input_rows(value: object) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if isinstance(value, dict):
        single_row_fields = {
            "input_key",
            "source_accession",
            "accession",
            "genome_id",
            "taxid",
            "tax_id",
            "lineage",
            "lineage_names",
            *TAXONOMY_RANK_FIELDS,
        }
        if any(key in value for key in single_row_fields):
            items: list[tuple[object, object]] = [("", value)]
        else:
            items = sorted(value.items(), key=lambda item: str(item[0]).casefold())
    elif isinstance(value, list):
        items = [("", item) for item in value]
    elif value is None:
        items = []
    else:
        raise ValueError("taxonomy_metadata must be a keyed object or a list of rows")

    if len(items) > 500:
        raise ValueError("taxonomy_metadata exceeds the 500-row canonical limit")
    for metadata_key, payload in items:
        if not isinstance(payload, dict):
            raise ValueError("Each taxonomy_metadata entry must be an object")
        row = dict(payload)
        row["_metadata_key"] = metadata_key
        rows.append(row)
    return rows


def _taxonomy_lineage_text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        parts = [_safe_manifest_text(part, limit=160) for part in value]
        return "|".join(part for part in parts if part)[:1000]
    return _safe_manifest_text(value, limit=1000)


def _normalized_taxonomy_metadata_row(raw: dict[str, object]) -> dict[str, str]:
    row = {
        "_metadata_key": _safe_manifest_text(raw.get("_metadata_key"), limit=160),
        "input_key": _safe_manifest_text(raw.get("input_key"), limit=160),
        "source_accession": _safe_manifest_text(
            raw.get("source_accession") or raw.get("accession"), limit=160
        ),
        "genome_id": _safe_manifest_text(raw.get("genome_id"), limit=160),
        "taxon_group": _safe_manifest_text(raw.get("taxon_group"), limit=20).lower(),
        "taxon_source": _safe_manifest_text(raw.get("taxon_source"), limit=80).lower(),
        "taxid": _safe_manifest_text(raw.get("taxid") or raw.get("tax_id"), limit=40),
        "organism_name": _safe_manifest_text(raw.get("organism_name"), limit=300),
        "lineage_names": _taxonomy_lineage_text(
            raw.get("lineage_names") or raw.get("lineage")
        ),
        "lineage_ids": _taxonomy_lineage_text(raw.get("lineage_ids")),
    }
    for rank in TAXONOMY_RANK_FIELDS:
        row[rank] = _safe_manifest_text(
            raw.get(rank) or raw.get(f"{rank}_name"), limit=160
        )
    if not row["lineage_names"]:
        row["lineage_names"] = "|".join(
            row[rank] for rank in TAXONOMY_RANK_FIELDS if row[rank]
        )
    return row


def _taxonomy_rows_for_routes(
    taxonomy_path: Path,
    routes: list[dict[str, str]],
    taxonomy_metadata: object = None,
    mapping_metadata: Optional[list[dict[str, object]]] = None,
) -> list[dict[str, str]]:
    existing_rows: list[dict[str, object]] = []
    if taxonomy_path.is_file():
        with taxonomy_path.open("r", newline="", encoding="utf-8-sig") as handle:
            existing_rows.extend(
                dict(row) for row in csv.DictReader(handle, delimiter="\t")
            )
    mapping_rows = list(mapping_metadata or [])
    settings_rows = _taxonomy_metadata_input_rows(taxonomy_metadata)

    metadata_by_key: dict[str, dict[str, str]] = {}
    for raw in existing_rows:
        row = _normalized_taxonomy_metadata_row(raw)
        lookup_values = [
            row["_metadata_key"],
            row["input_key"],
            row["source_accession"],
            row["genome_id"],
        ]
        for value in lookup_values:
            for key in _taxonomy_key_variants(value):
                metadata_by_key[key] = row
    semantic_fields = [
        "taxon_group",
        "taxon_source",
        "taxid",
        "organism_name",
        "lineage_names",
        "lineage_ids",
        *TAXONOMY_RANK_FIELDS,
    ]
    for group_rows in (mapping_rows, settings_rows):
        group_by_key: dict[str, dict[str, str]] = {}
        for raw in group_rows:
            row = _normalized_taxonomy_metadata_row(raw)
            lookup_values = [
                row["_metadata_key"],
                row["input_key"],
                row["source_accession"],
                row["genome_id"],
            ]
            for value in lookup_values:
                for key in _taxonomy_key_variants(value):
                    previous = group_by_key.get(key)
                    if previous is not None and any(
                        previous.get(field, "") != row.get(field, "")
                        for field in semantic_fields
                    ):
                        raise ValueError(
                            f"Ambiguous taxonomy_metadata rows for key '{key}'"
                        )
                    group_by_key[key] = row
                    metadata_by_key[key] = row

    output: list[dict[str, str]] = []
    for route in routes:
        metadata: dict[str, str] = {}
        route_source = str(route.get("taxon_source") or "").strip().lower()
        if route_source in AUTHORITATIVE_TAXON_SOURCES:
            for value in (
                route.get("input_key"),
                route.get("source_accession"),
                route.get("genome_id"),
            ):
                match = next(
                    (
                        metadata_by_key[key]
                        for key in _taxonomy_key_variants(value)
                        if key in metadata_by_key
                    ),
                    None,
                )
                if match is not None:
                    metadata = match
                    break
            if metadata.get("taxon_group") and (
                metadata["taxon_group"] != str(route.get("taxon_group") or "").lower()
            ):
                raise ValueError(
                    f"Taxonomy metadata conflicts with routed taxon for "
                    f"{route.get('genome_id')}"
                )
            if metadata.get("taxon_source") and (
                metadata["taxon_source"] != route_source
            ):
                raise ValueError(
                    f"Taxonomy metadata source conflicts with immutable route for "
                    f"{route.get('genome_id')}"
                )

        row = {
            "genome_id": _safe_genome_id(route.get("genome_id")),
            "taxon_group": _safe_manifest_text(route.get("taxon_group"), limit=20),
            "taxon_source": _safe_manifest_text(route.get("taxon_source"), limit=80),
            "taxid": metadata.get("taxid") or _safe_manifest_text(
                route.get("taxid"), limit=40
            ),
            "organism_name": metadata.get("organism_name") or _safe_manifest_text(
                route.get("organism_name"), limit=300
            ),
            "source_accession": _safe_manifest_text(
                route.get("source_accession"), limit=160
            ),
            "lineage_names": metadata.get("lineage_names", ""),
            "lineage_ids": metadata.get("lineage_ids", ""),
        }
        for rank in TAXONOMY_RANK_FIELDS:
            row[rank] = metadata.get(rank, "")
        output.append(row)
    return output


def _taxonomy_metadata_from_mapping_files(
    layout: ProjectLayout,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    mapping_specs = [
        (
            "fungi",
            layout.fungi_genome_root
            / "accessions_fungusID_taxonomyID.txt",
        ),
        (
            "bacteria",
            layout.bacteria_genome_root
            / "accessions_bacteriaID_taxonomyID.txt",
        ),
    ]
    for taxon_group, mapping_path in mapping_specs:
        if not mapping_path.is_file():
            continue
        with mapping_path.open("r", encoding="utf-8-sig") as handle:
            for raw_line in handle:
                fields = raw_line.rstrip("\r\n").split("\t")
                if len(fields) < 2:
                    continue
                accession = _safe_manifest_text(fields[0], limit=160)
                genome_id = _safe_manifest_text(fields[1], limit=160)
                if (
                    not accession
                    or not genome_id
                    or accession.casefold() == "accession"
                ):
                    continue
                rows.append(
                    {
                        "input_key": accession,
                        "source_accession": accession,
                        "genome_id": genome_id,
                        "taxon_group": taxon_group,
                        "taxon_source": "ncbi",
                        "taxid": fields[2] if len(fields) > 2 else "",
                        "organism_name": fields[4] if len(fields) > 4 else "",
                        "lineage_ids": fields[5] if len(fields) > 5 else "",
                        "lineage_names": fields[6] if len(fields) > 6 else "",
                    }
                )
    return rows


def _write_routed_workflow_metadata(
    layout: ProjectLayout,
    routes: list[dict[str, str]],
    scope: str,
    *,
    ecology_enabled: bool,
) -> None:
    summary_root = layout.results_root / "summary_tables"
    ecology_names = (
        "ecofun_metadata_normalized.tsv",
        "ecofun_metadata_template.tsv",
        "ecobac_metadata_normalized.tsv",
        "ecobac_metadata_template.tsv",
    )
    if ecology_enabled and layout.metadata_file is not None and layout.metadata_file.is_file():
        return
    if ecology_enabled:
        output_root = summary_root
    else:
        for name in ecology_names:
            (summary_root / name).unlink(missing_ok=True)
        output_root = layout.work_root / "routing"

    if scope == "bacteria":
        output = output_root / "ecobac_metadata_normalized.tsv"
        fields = [
            "accession",
            "genome_id_current",
            "taxid",
            "organism_name",
            "ecobac_primary",
            "ecobac_secondary",
        ]
        rows = [
            {
                "accession": row["source_accession"],
                "genome_id_current": row["genome_id"],
                "taxid": row["taxid"],
                "organism_name": row["organism_name"],
                "ecobac_primary": "",
                "ecobac_secondary": "",
            }
            for row in routes
        ]
    else:
        output = output_root / "ecofun_metadata_normalized.tsv"
        fields = [
            "accession",
            "genome_id_current",
            "taxonomy_id",
            "genome_size_mb",
            "genome_id_original_if_different",
            "ecofun_primary",
            "ecofun_secondary",
        ]
        rows = [
            {
                "accession": row["source_accession"],
                "genome_id_current": row["genome_id"],
                "taxonomy_id": row["taxid"],
                "genome_size_mb": "",
                "genome_id_original_if_different": "",
                "ecofun_primary": "",
                "ecofun_secondary": "",
            }
            for row in routes
        ]
    _write_tsv(output, fields, rows)
    layout.metadata_file = output


def _write_taxon_manifests(
    layout: ProjectLayout,
    routes: list[dict[str, str]],
    taxonomy_metadata: object = None,
    *,
    ecology_enabled: bool = False,
) -> None:
    summary_root = layout.results_root / "summary_tables"
    safe_routes = [
        {
            field: (
                _safe_input_path_key(row.get(field))
                if field == "input_path_key"
                else _safe_manifest_text(row.get(field))
            )
            for field in TAXON_ROUTE_FIELDS
        }
        for row in routes
    ]
    _write_tsv(summary_root / "genome_taxon_manifest.tsv", TAXON_ROUTE_FIELDS, safe_routes)
    _write_tsv(
        summary_root / "routing_diagnostics.tsv",
        ["input_key", "genome_id", "taxon_group", "taxon_source", "route_status", "route_reason"],
        safe_routes,
    )
    taxonomy_path = summary_root / "taxonomy_metadata_normalized.tsv"
    taxonomy_rows = _taxonomy_rows_for_routes(
        taxonomy_path,
        safe_routes,
        taxonomy_metadata,
        _taxonomy_metadata_from_mapping_files(layout),
    )
    _write_tsv(taxonomy_path, TAXONOMY_METADATA_FIELDS, taxonomy_rows)

    routing_log_root = layout.results_root / "logs"
    routing_log_root.mkdir(parents=True, exist_ok=True)
    routing_log = routing_log_root / (
        "taxon_routing." + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".log"
    )
    fungi_count = sum(row["taxon_group"] == "fungi" for row in safe_routes)
    bacteria_count = sum(row["taxon_group"] == "bacteria" for row in safe_routes)
    unresolved_count = len(safe_routes) - fungi_count - bacteria_count
    scope = (
        "both"
        if fungi_count and bacteria_count
        else "bacteria"
        if bacteria_count
        else "fungi"
    )
    routing_lines = [
        (
            f"TAXON_ROUTE genome={row['genome_id']} taxon={row['taxon_group']} "
            f"source={row['taxon_source'] or 'unknown'} status={row['route_status'] or 'resolved'} "
            f'message="prediction={row["prediction_method"] or "unknown"} '
            f'detector={row["detector_profile"] or "unknown"}"'
        )
        for row in safe_routes
    ]
    routing_lines.append(
        f"TAXON_SUMMARY scope={scope} fungi={fungi_count} "
        f"bacteria={bacteria_count} unresolved={unresolved_count}"
    )
    routing_log.write_text("\n".join(routing_lines) + "\n", encoding="utf-8")

    generic_fields = ["genome_id", "taxon_group", "taxid", "organism_name", "source_accession"]
    _write_tsv(summary_root / "genome_id_legend.tsv", generic_fields, safe_routes)
    fungal_rows = [
        {"fungal_id": row["genome_id"], **row}
        for row in safe_routes
        if row["taxon_group"] == "fungi"
    ]
    bacterial_rows = [
        {"bacteria_id": row["genome_id"], **row}
        for row in safe_routes
        if row["taxon_group"] == "bacteria"
    ]
    fungal_legend = summary_root / "fungal_id_legend.tsv"
    if fungal_rows:
        _write_tsv(
            fungal_legend,
            ["fungal_id", "genome_id", "taxid", "organism_name", "source_accession"],
            fungal_rows,
        )
    else:
        fungal_legend.unlink(missing_ok=True)

    bacterial_legend = summary_root / "bacteria_id_legend.tsv"
    if bacterial_rows:
        _write_tsv(
            bacterial_legend,
            ["bacteria_id", "genome_id", "taxid", "organism_name", "source_accession"],
            bacterial_rows,
        )
    else:
        bacterial_legend.unlink(missing_ok=True)

    _write_routed_workflow_metadata(
        layout,
        safe_routes,
        scope,
        ecology_enabled=ecology_enabled,
    )


def _read_taxon_manifest(layout: ProjectLayout) -> list[dict[str, str]]:
    path = layout.results_root / "summary_tables" / "genome_taxon_manifest.tsv"
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return _normalize_taxon_routes({"taxon_routes": rows})


def _safe_extract_zip(src: Path, dest_dir: Path) -> None:
    dest_root = dest_dir.resolve()
    with zipfile.ZipFile(src) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            target = (dest_dir / member.filename).resolve()
            if dest_root not in target.parents and target != dest_root:
                raise ValueError(f"Unsafe path in zip archive: {member.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _stage_uploaded_inputs(input_files: list[Path], layout: ProjectLayout, settings: dict[str, Any], job: Job) -> None:
    for root in layout.genome_roots:
        root.mkdir(parents=True, exist_ok=True)
    (layout.results_root / "summary_tables").mkdir(parents=True, exist_ok=True)
    nplinker_upload_root = layout.work_root / "nplinker_uploads"
    gnps_root = nplinker_upload_root / "gnps"
    explicit_metadata = _cfg_str(settings, "metadata_tsv")
    scope = _analysis_scope(settings)
    scope_was_explicit = bool(str(settings.get("analysis_scope") or "").strip())
    routes = _normalize_taxon_routes(settings)
    routes_locked = bool(routes)
    if not routes_locked:
        routes = _direct_upload_taxon_routes(
            input_files,
            settings,
            scope_was_explicit=scope_was_explicit,
        )

    for src in input_files:
        suffix = src.suffix.lower()
        if suffix in GENOME_EXTS:
            route = _route_for_input(src, routes)
            if route is None:
                if routes_locked:
                    raise ValueError(f"Genome input '{src.name}' has no immutable taxon route")
                raise ValueError(
                    f"Genome input '{src.name}' was not resolved by shared taxon routing"
                )
            if not _route_active(route):
                raise ValueError(
                    f"Genome input '{src.name}' has inactive route status '{route['route_status']}'"
                )
            destination_root = layout.root_for_taxon(route["taxon_group"])
            destination = destination_root / f"{route['genome_id']}{suffix}"
            if destination.exists():
                raise ValueError(f"Duplicate staged genome input for '{route['genome_id']}': {src.name}")
            shutil.copy2(src, destination)
            copied = destination
            route["input_path_key"] = (
                copied.parent.relative_to(layout.data_root).as_posix() + f"/{route['genome_id']}"
            )
            layout.genome_inputs.append(copied)
            job.add_log(f"Staged genome input: {copied.relative_to(layout.data_root)}")
            continue
        if _looks_like_accession_file(src) and layout.accession_file is None:
            copied = _copy_unique(src, layout.downloads_root, "accessions.txt")
            layout.accession_file = copied
            job.add_log(f"Staged accession list: {copied.relative_to(layout.data_root.parent)}")
            continue
        if _looks_like_metadata_file(src) and layout.metadata_file is None:
            default_metadata_name = (
                "ecobac_metadata_normalized.tsv" if scope == "bacteria" else "ecofun_metadata_normalized.tsv"
            )
            dest_name = Path(explicit_metadata).name if explicit_metadata else default_metadata_name
            copied = _copy_unique(src, layout.results_root / "summary_tables", dest_name)
            layout.metadata_file = copied
            job.add_log(f"Staged ecology metadata: {copied.relative_to(layout.data_root)}")
            continue
        if _looks_like_strain_mapping(src):
            copied = _copy_unique(src, nplinker_upload_root, "strain_mappings.json")
            layout.nplinker_strain_mapping = copied
            job.add_log(f"Staged NPLinker strain mapping: {copied.relative_to(layout.data_root.parent)}")
            continue
        if suffix == ".mgf":
            copied = _copy_unique(src, gnps_root)
            layout.nplinker_gnps_dir = gnps_root
            job.add_log(f"Staged NPLinker GNPS asset: {copied.relative_to(layout.data_root.parent)}")
            continue
        if suffix == ".zip" and "gnps" in src.name.lower():
            target_dir = gnps_root / src.stem
            target_dir.mkdir(parents=True, exist_ok=True)
            try:
                _safe_extract_zip(src, target_dir)
                layout.nplinker_gnps_dir = gnps_root
                job.add_log(f"Extracted NPLinker GNPS archive: {target_dir.relative_to(layout.data_root.parent)}")
            except (zipfile.BadZipFile, ValueError) as exc:
                copied = _copy_unique(src, layout.downloads_root / "unclassified")
                job.add_log(f"WARN: GNPS archive could not be extracted ({exc}); kept as auxiliary upload: {copied.relative_to(layout.data_root.parent)}")
            continue
        copied = _copy_unique(src, layout.downloads_root / "unclassified")
        job.add_log(f"Kept auxiliary upload: {copied.relative_to(layout.data_root.parent)}")

    if layout.accession_file is not None and not routes and scope != "fungi":
        raise ValueError(
            "Bacterial or Both-mode accession preparation requires authoritative immutable taxon routes"
        )
    normalized_routes = _normalize_taxon_routes({"taxon_routes": routes})
    settings["analysis_scope"] = scope
    settings["taxon_routes"] = normalized_routes
    settings["taxon_counts"], settings["applicability_counts"] = _route_summaries(
        normalized_routes
    )
    _write_taxon_manifests(
        layout,
        normalized_routes,
        settings.get("taxonomy_metadata"),
        ecology_enabled=_cfg_bool(settings, "run_ecology_analysis", False),
    )


def _restore_existing_layout_inputs(
    layout: ProjectLayout,
    job: Job,
    settings: Optional[dict[str, Any]] = None,
) -> None:
    accession_file = layout.downloads_root / "accessions.txt"
    if accession_file.exists():
        layout.accession_file = accession_file

    metadata_root = layout.results_root / "summary_tables"
    for candidate in [
        metadata_root / "ecofun_metadata_normalized.tsv",
        metadata_root / "ecofun_metadata_template.tsv",
        metadata_root / "ecobac_metadata_normalized.tsv",
        metadata_root / "ecobac_metadata_template.tsv",
    ]:
        if candidate.exists():
            layout.metadata_file = candidate
            break

    gnps_root = layout.work_root / "nplinker_uploads" / "gnps"
    if gnps_root.exists() and any(path.is_file() for path in gnps_root.rglob("*")):
        layout.nplinker_gnps_dir = gnps_root

    strain_mapping = layout.work_root / "nplinker_uploads" / "strain_mappings.json"
    if strain_mapping.exists():
        layout.nplinker_strain_mapping = strain_mapping

    layout.genome_inputs = sorted(
        path
        for root in layout.genome_roots
        for path in root.glob("*")
        if path.is_file() and path.suffix.lower() in GENOME_EXTS
    )
    routes = _read_taxon_manifest(layout)
    if settings is not None and routes:
        settings["taxon_routes"] = routes
        taxa = {row["taxon_group"] for row in routes if _route_active(row)}
        settings["analysis_scope"] = (
            "both" if taxa == {"fungi", "bacteria"} else next(iter(taxa), "fungi")
        )
        settings["taxon_counts"], settings["applicability_counts"] = _route_summaries(
            routes
        )
        _write_taxon_manifests(
            layout,
            routes,
            settings.get("taxonomy_metadata") if settings else None,
            ecology_enabled=_cfg_bool(settings or {}, "run_ecology_analysis", False),
        )
    job.add_log("Reusing existing staged ClusterWeave layout for rerun.")


def _parse_raw_env(raw: str) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if (
            ENV_KEY_RE.match(key)
            and key.upper() not in RESOURCE_ENV_KEYS
            and not _sensitive_env_key(key)
        ):
            overrides[key] = value.strip().strip("\"'")
    return overrides


def _base_env(layout: ProjectLayout, settings: dict[str, Any], cpus: int) -> dict[str, str]:
    cpu_budget = max(1, int(cpus))
    analysis_scope = _analysis_scope(settings)
    ecology_field = _cfg_str(settings, "ecology_field")
    if not ecology_field or (
        analysis_scope == "bacteria" and ecology_field == "ecofun_primary"
    ):
        ecology_field = (
            "ecobac_primary" if analysis_scope == "bacteria" else "ecofun_primary"
        )
    threads = _cfg_int(settings, "threads", cpu_budget)
    antismash_record_parallelism = max(1, _cfg_int(settings, "antismash_record_parallelism", 1))
    configured_antismash_shard_cpus = _cfg_int(settings, "antismash_shard_cpus", 0)
    configured_antismash_legacy_cpus = _cfg_int(settings, "antismash_legacy_cpus", 0)
    # run_phylogeny.sh currently uses one bounded child at a time.
    phylogeny_parallelism = 1
    phylogeny_cpus = _cfg_bounded_int(
        settings,
        "phylogeny_cpus",
        1,
        1,
        max(1, cpu_budget // phylogeny_parallelism),
    )
    phylogeny_input_root = layout.results_root / "phylogeny_inputs"
    phylogeny_results_root = layout.results_root / "phylogeny"
    phylogeny_work_root = layout.work_root / "phylogeny"
    integrated_evidence_root = layout.results_root / "integrated_evidence"
    integrated_evidence_work = layout.work_root / "integrated_evidence"
    run_cross_kingdom_evidence = _cfg_bool(
        settings,
        "run_cross_kingdom_evidence",
        _cfg_bool(
            settings,
            "RUN_CROSS_KINGDOM_EVIDENCE",
            _cfg_bool(
                settings,
                "run_hgt_evidence",
                _cfg_bool(settings, "RUN_HGT_EVIDENCE", False),
            ),
        ),
    )
    cross_kingdom_evidence_max_candidates = _cfg_bounded_int(
        settings,
        "cross_kingdom_evidence_max_candidates",
        _cfg_int(
            settings,
            "CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES",
            _cfg_int(
                settings,
                "hgt_evidence_max_candidates",
                _cfg_int(settings, "HGT_EVIDENCE_MAX_CANDIDATES", 25),
            ),
        ),
        1,
        100,
    )
    env = {
        "PROJECT_DIR": str(layout.repo_root),
        "PROJECT_ROOT": str(layout.repo_root),
        "PROJECTS_ROOT": str(layout.data_root.parent),
        "PROJECT_NAME": layout.project_name,
        "DATA_ROOT": str(layout.data_root),
        "RESULTS_BASE": str(layout.data_root / "results"),
        "RESULTS_ROOT": str(layout.results_root),
        "GENOMES_ROOT": str(layout.data_root / "genomes" / "fungi"),
        "GENOME_ROOT": str(layout.fungi_genome_root),
        "FUNGI_GENOME_ROOT": str(layout.fungi_genome_root),
        "BACTERIA_GENOME_ROOT": str(layout.bacteria_genome_root),
        "GENOME_TAXON_MANIFEST": str(
            layout.results_root / "summary_tables" / "genome_taxon_manifest.tsv"
        ),
        "ANALYSIS_SCOPE": analysis_scope,
        "SOFTWARE_ROOT": str(layout.software_root),
        "TOOLS_ROOT": str(layout.software_root),
        "WORK_ROOT": str(layout.work_root),
        "STAGE_DIR": str(layout.work_root / "bigscape_stage_region_gbks"),
        "RUN_PHYLOGENY": "1" if _cfg_bool(settings, "run_phylogeny", False) else "0",
        "PHYLOGENY_REQUIRED": "1" if _cfg_bool(settings, "phylogeny_required", False) else "0",
        "PHYLOGENY_AUTO_PREPARE": (
            "1"
            if _cfg_bool(
                settings,
                "phylogeny_auto_prepare",
                _cfg_bool(
                    settings,
                    "PHYLOGENY_AUTO_PREPARE",
                    _cfg_bool(settings, "run_phylogeny", False),
                ),
            )
            else "0"
        ),
        "PHYLOGENY_AUTO_SELECT_CANDIDATES": "1",
        "PHYLOGENY_PREPARE_HELPER": str(
            layout.repo_root / "bin" / "prepare_phylogeny_families.py"
        ),
        "PHYLOGENY_CANDIDATE_SELECTOR": str(
            layout.repo_root / "bin" / "select_cross_kingdom_candidates.py"
        ),
        "PHYLOGENY_CANDIDATES_TSV": str(
            layout.results_root / "summary" / "cross_kingdom_candidates.tsv"
        ),
        "PHYLOGENY_CROSSWALK_TSV": str(
            layout.results_root / "summary" / "candidate_bgc_gcf_crosswalk.tsv"
        ),
        "PHYLOGENY_ANTISMASH_ROOT": str(layout.results_root / "antismash"),
        "PHYLOGENY_SEQUENCE_MAP": str(
            phylogeny_input_root / "sequence_taxon_map.tsv"
        ),
        "PHYLOGENY_TOPOLOGY_RESULTS_TSV": str(
            phylogeny_results_root / "topology_comparison.tsv"
        ),
        "PHYLOGENY_MAX_CANDIDATES": str(cross_kingdom_evidence_max_candidates),
        "PHYLOGENY_MAX_REGIONS_PER_CANDIDATE": str(
            _cfg_bounded_int(
                settings, "phylogeny_max_regions_per_candidate", 100, 1, 500
            )
        ),
        "PHYLOGENY_MAX_REGION_BYTES": str(
            _cfg_bounded_int(
                settings,
                "phylogeny_max_region_bytes",
                25 * 1024 * 1024,
                1,
                100 * 1024 * 1024,
            )
        ),
        "PHYLOGENY_MAX_INPUT_BYTES": str(
            _cfg_bounded_int(
                settings,
                "phylogeny_max_input_bytes",
                250 * 1024 * 1024,
                1,
                2 * 1024 * 1024 * 1024,
            )
        ),
        "PHYLOGENY_MAX_PREPARED_BYTES": str(
            _cfg_bounded_int(
                settings,
                "phylogeny_max_prepared_bytes",
                50_000_000,
                1,
                200_000_000,
            )
        ),
        "PHYLOGENY_CPUS": str(phylogeny_cpus),
        "PHYLOGENY_PARALLELISM": str(phylogeny_parallelism),
        "PHYLOGENY_MAX_FAMILIES": str(
            _cfg_bounded_int(settings, "phylogeny_max_families", 10, 1, 100)
        ),
        "PHYLOGENY_MAX_SEQUENCES_PER_FAMILY": str(
            _cfg_bounded_int(
                settings,
                "phylogeny_max_sequences_per_family",
                250,
                3,
                1000,
            )
        ),
        "PHYLOGENY_MAX_ALIGNMENT_BYTES": str(
            _cfg_bounded_int(
                settings,
                "phylogeny_max_alignment_bytes",
                50_000_000,
                1,
                200_000_000,
            )
        ),
        "PHYLOGENY_TIMEOUT_SECONDS": str(
            _cfg_bounded_int(
                settings, "phylogeny_timeout_seconds", 7200, 1, 86_400
            )
        ),
        "PHYLOGENY_RETAIN_SCRATCH": (
            "1" if _cfg_bool(settings, "phylogeny_retain_scratch", False) else "0"
        ),
        "PHYLOGENY_INPUT_ROOT": str(phylogeny_input_root),
        "PHYLOGENY_FAMILY_MANIFEST": str(phylogeny_input_root / "families.tsv"),
        "PHYLOGENY_RESULTS_ROOT": str(phylogeny_results_root),
        "PHYLOGENY_WORK_ROOT": str(phylogeny_work_root),
        "PHYLOGENY_LOG_ROOT": str(layout.results_root / "logs"),
        "PHYLOGENY_MANIFEST_TSV": str(
            phylogeny_results_root / "phylogeny_run_manifest.tsv"
        ),
        "PHYLOGENY_MANIFEST_JSON": str(
            phylogeny_results_root / "phylogeny_run_manifest.json"
        ),
        "PHYLOGENY_RUNTIME": os.environ.get("PHYLOGENY_RUNTIME", "auto"),
        "PHYLOGENY_DOCKER_IMAGE": os.environ.get(
            "PHYLOGENY_DOCKER_IMAGE", "clusterweave-phylogeny:1.0.0"
        ),
        "PHYLOGENY_SIF_PATH": os.environ.get(
            "PHYLOGENY_SIF_PATH",
            str(
                layout.repo_root
                / "software"
                / "phylogeny"
                / "clusterweave_phylogeny_1.0.0.sif"
            ),
        ),
        "RUN_CROSS_KINGDOM_EVIDENCE": "1" if run_cross_kingdom_evidence else "0",
        "CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES": str(
            cross_kingdom_evidence_max_candidates
        ),
        "CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV": str(
            layout.results_root / "summary" / "cross_kingdom_candidates.tsv"
        ),
        "CROSS_KINGDOM_EVIDENCE_AUTO_SELECT": "1",
        "CROSS_KINGDOM_EVIDENCE_CROSSWALK_TSV": str(
            layout.results_root / "summary" / "candidate_bgc_gcf_crosswalk.tsv"
        ),
        "CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR": str(integrated_evidence_root),
        "CROSS_KINGDOM_EVIDENCE_WORK_ROOT": str(integrated_evidence_work),
        "CROSS_KINGDOM_EVIDENCE_STAGING_DIR": str(integrated_evidence_work / "staged"),
        "CROSS_KINGDOM_EVIDENCE_PREVIOUS_DIR": str(
            integrated_evidence_work / "previous_public"
        ),
        "CROSS_KINGDOM_EVIDENCE_LOG_ROOT": str(layout.results_root / "logs"),
        "CROSS_KINGDOM_EVIDENCE_LOGFILE": str(
            layout.results_root / "logs" / "run_cross_kingdom_evidence.log"
        ),
        "CROSS_KINGDOM_EVIDENCE_STATUS_MANIFEST": str(
            layout.results_root
            / "logs"
            / "cross_kingdom_evidence_run_manifest.json"
        ),
        "CROSS_KINGDOM_EVIDENCE_BUILDER": str(
            layout.repo_root / "bin" / "build_cross_kingdom_evidence.py"
        ),
        "CROSS_KINGDOM_EVIDENCE_SELECTOR": str(
            layout.repo_root / "bin" / "select_cross_kingdom_candidates.py"
        ),
        "CROSS_KINGDOM_EVIDENCE_TOPOLOGY_TSV": str(
            phylogeny_results_root / "topology_comparison.tsv"
        ),
        "CROSS_KINGDOM_EVIDENCE_TOPOLOGY_MERGER": str(
            layout.repo_root / "bin" / "merge_topology_evidence.py"
        ),
        "CROSS_KINGDOM_EVIDENCE_ENRICHED_CANDIDATES_TSV": str(
            integrated_evidence_work / "staged" / "candidates_with_topology.tsv"
        ),
        "CROSS_KINGDOM_EVIDENCE_CONTEXT_ENRICHER": str(
            layout.repo_root / "bin" / "enrich_cross_kingdom_context.py"
        ),
        "CROSS_KINGDOM_EVIDENCE_CONTEXT_CANDIDATES_TSV": str(
            integrated_evidence_work / "staged" / "candidates_with_context.tsv"
        ),
        "CROSS_KINGDOM_EVIDENCE_RANKING_TSV": str(
            layout.results_root / "summary" / "targeted_candidate_ranking.tsv"
        ),
        "CROSS_KINGDOM_EVIDENCE_TAXON_MANIFEST": str(
            layout.results_root / "summary_tables" / "genome_taxon_manifest.tsv"
        ),
        "CROSS_KINGDOM_EVIDENCE_ANTISMASH_ROOT": str(
            layout.results_root / "antismash"
        ),
        "CROSS_KINGDOM_EVIDENCE_CLINKER_ROOT": str(
            layout.results_root / "clinker"
        ),
        "CROSS_KINGDOM_EVIDENCE_GENOMES_ROOT": str(layout.data_root / "genomes"),
        "ENGINE": _cfg_str(settings, "engine", os.environ.get("ENGINE", "")),
        "CLUSTERWEAVE_RUNTIME_MODE": os.environ.get("CLUSTERWEAVE_RUNTIME_MODE", "hpc-singularity"),
        "CLUSTERWEAVE_ENABLE_DOCKER_SOCKET": os.environ.get("CLUSTERWEAVE_ENABLE_DOCKER_SOCKET", "0"),
        "DOCKER_DATA_VOLUME": os.environ.get("DOCKER_DATA_VOLUME", os.environ.get("CLUSTERWEAVE_DOCKER_DATA_VOLUME", "")),
        "DOCKER_ANTISMASH_DB_VOLUME": os.environ.get("DOCKER_ANTISMASH_DB_VOLUME", ""),
        "DOCKER_PFAM_VOLUME": os.environ.get("DOCKER_PFAM_VOLUME", ""),
        "ANTISMASH_DB_DIR": os.environ.get("ANTISMASH_DB_DIR", "/databases/antismash"),
        "PFAM_DIR": os.environ.get("PFAM_DIR", str(layout.software_root / "big_scape" / "resources" / "pfam")),
        "PFAM_HMM": str(Path(os.environ.get("PFAM_DIR", str(layout.software_root / "big_scape" / "resources" / "pfam"))) / "Pfam-A.hmm"),
        "NCBI_CLI_ROOT": str(layout.software_root / "ncbi_cli"),
        "INSTALL_DIR": str(layout.software_root / "ncbi_cli"),
        "CPUS": str(cpu_budget),
        "THREADS": str(threads),
        "ANNO_CPUS": str(_cfg_int(settings, "anno_cpus", cpu_budget)),
        "WORKERS": str(_cfg_int(settings, "workers", 2)),
        "GENOME_PARALLELISM": str(_cfg_int(settings, "genome_parallelism", 1)),
        "ANTISMASH_RECORD_PARALLELISM": str(antismash_record_parallelism),
        "FORCE": "1" if _cfg_bool(settings, "force", False) else "0",
        "TARGET_GENOME": _cfg_str(settings, "target_genome"),
        "CLINKER_MODE": _cfg_str(settings, "clinker_mode", "auto") or "auto",
        "PANEL_TARGET_SET": _cfg_str(settings, "panel_target_set", "both") or "both",
        "RUN_STAGE_ANNOTATION": "1" if _cfg_bool(settings, "run_annotation", True) else "0",
        "RUN_STAGE_BIGSCAPE": "1" if _cfg_bool(settings, "run_bigscape", True) else "0",
        "RUN_STAGE_SUMMARY": "1" if _cfg_bool(settings, "run_summary", _cfg_bool(settings, "run_crosswalk", True)) else "0",
        "RUN_STAGE_CLINKER": "1" if _cfg_bool(settings, "run_clinker", True) else "0",
        "RUN_CLINKER": "1" if _cfg_bool(settings, "execute_clinker", _cfg_bool(settings, "run_clinker", True)) else "0",
        "RUN_ECOLOGY_ANALYSIS": "1" if _cfg_bool(settings, "run_ecology_analysis", False) else "0",
        "ECOLOGY_FIELD": ecology_field,
        "FOCUS_ECOLOGY_LABEL": _cfg_str(settings, "focus_ecology_label"),
        "AUTO_NORMALIZE_METADATA": "1" if _cfg_bool(settings, "auto_normalize_metadata", True) else "0",
        "CAPTURE_EXTERNAL_ARTIFACTS": "1" if _cfg_bool(settings, "capture_external_artifacts", True) else "0",
        "ATLAS_STAGE_LIMIT": str(_cfg_int(settings, "atlas_stage_limit", 20)),
        "ATLAS_MIN_RECORDS": str(_cfg_int(settings, "atlas_min_records", 2)),
        "SHORTLIST_LIMIT": str(_cfg_int(settings, "shortlist_limit", 12)),
        "SHARED_FAMILY_STAGE_LIMIT": str(_cfg_int(settings, "shared_family_stage_limit", _cfg_int(settings, "shortlist_limit", 12))),
        "SHARED_FAMILY_MIN_RECORDS": str(_cfg_int(settings, "shared_family_min_records", 4)),
        "MAX_COMPARATORS": str(_cfg_int(settings, "max_comparators", 50)),
        "MAX_SAME_ECOLOGY": str(_cfg_int(settings, "max_same_ecology", 20)),
        "MAX_OTHER_ECOLOGY": str(_cfg_int(settings, "max_other_ecology", 20)),
        "AUTO_PULL_IMAGES": _cfg_str(settings, "auto_pull_images", os.environ.get("AUTO_PULL_IMAGES", "always")) or "always",
        "AUTO_BUILD_FUNBGCEX_SIF": "1" if _cfg_bool(settings, "auto_build_funbgcex_sif", True) else "0",
        "AUTO_PULL_BIGSCAPE_SIF": "1" if _cfg_bool(settings, "auto_pull_bigscape_sif", True) else "0",
        "AUTO_DOWNLOAD_PFAM": "1" if _cfg_bool(settings, "auto_download_pfam", True) else "0",
        "AUTO_DOWNLOAD_FASTTREE": "1" if _cfg_bool(settings, "auto_download_fasttree", True) else "0",
        "MIBIG_AUTO_DOWNLOAD": "1" if _cfg_bool(settings, "mibig_auto_download", True) else "0",
        "ANTISMASH_DOCKER_IMAGE": os.environ.get("ANTISMASH_DOCKER_IMAGE", "antismash/standalone:8.0.4"),
        "FUNBGCEX_USE_DOCKER_IMAGE": os.environ.get("FUNBGCEX_USE_DOCKER_IMAGE", "1" if os.environ.get("ENGINE") == "docker" else "0"),
        "FUNBGCEX_DOCKER_IMAGE": os.environ.get("FUNBGCEX_DOCKER_IMAGE", "clusterweave-funbgcex:latest"),
        "AUTO_BUILD_FUNBGCEX_DOCKER": os.environ.get("AUTO_BUILD_FUNBGCEX_DOCKER", "1"),
        "BIGSCAPE_USE_DOCKER_IMAGE": os.environ.get("BIGSCAPE_USE_DOCKER_IMAGE", "1" if os.environ.get("ENGINE") == "docker" else "0"),
        "BIGSCAPE_DOCKER_IMAGE": os.environ.get("BIGSCAPE_DOCKER_IMAGE", "ghcr.io/medema-group/big-scape:2.0.0-beta.6"),
        "BIGSCAPE_DOCKER_DATA_VOLUME": os.environ.get("BIGSCAPE_DOCKER_DATA_VOLUME", os.environ.get("DOCKER_DATA_VOLUME", "")),
        "BIGSCAPE_DOCKER_PFAM_VOLUME": os.environ.get("BIGSCAPE_DOCKER_PFAM_VOLUME", os.environ.get("DOCKER_PFAM_VOLUME", "")),
        "CLINKER_USE_DOCKER_IMAGE": "1" if _cfg_bool(settings, "clinker_use_docker_image", os.environ.get("ENGINE") == "docker") else "0",
        "CLINKER_DOCKER_IMAGE": _cfg_str(settings, "clinker_docker_image", os.environ.get("CLINKER_DOCKER_IMAGE", "quay.io/biocontainers/clinker-py:0.0.32--pyhdfd78af_0")),
        "CLINKER_DOCKER_DATA_VOLUME": _cfg_str(settings, "clinker_docker_data_volume", os.environ.get("CLINKER_DOCKER_DATA_VOLUME", os.environ.get("DOCKER_DATA_VOLUME", ""))),
        "NPLINKER_USE_DOCKER_IMAGE": os.environ.get("NPLINKER_USE_DOCKER_IMAGE", "1" if os.environ.get("ENGINE") == "docker" else "0"),
        "NPLINKER_DOCKER_IMAGE": os.environ.get("NPLINKER_DOCKER_IMAGE", "python:3.11-slim"),
        "NPLINKER_DOCKER_DATA_VOLUME": os.environ.get("NPLINKER_DOCKER_DATA_VOLUME", os.environ.get("DOCKER_DATA_VOLUME", "")),
    }
    if configured_antismash_shard_cpus > 0:
        env["ANTISMASH_SHARD_CPUS"] = str(configured_antismash_shard_cpus)
    if configured_antismash_legacy_cpus > 0:
        env["ANTISMASH_LEGACY_CPUS"] = str(configured_antismash_legacy_cpus)
    if layout.accession_file is not None:
        env["ACCESSIONS_FILE"] = str(layout.accession_file)
    if layout.metadata_file is not None:
        env["METADATA_TSV"] = str(layout.metadata_file)
    if layout.nplinker_gnps_dir is not None:
        env["LOCAL_GNPS_DIR"] = str(layout.nplinker_gnps_dir)
    if layout.nplinker_strain_mapping is not None:
        env["LOCAL_STRAIN_MAPPING"] = str(layout.nplinker_strain_mapping)
    env["ANNOTATION_FALLBACK_ORDER"] = _web_safe_annotation_order(
        _cfg_str(settings, "annotation_fallback_order", "funannotate")
    )
    env["BRAKER3_ENABLED"] = "0"
    if _cfg_str(settings, "funannotate_busco_db"):
        env["FUNANNOTATE_BUSCO_DB"] = _cfg_str(settings, "funannotate_busco_db")
    if _cfg_str(settings, "funannotate_organism_name"):
        env["FUNANNOTATE_ORGANISM_NAME"] = _cfg_str(settings, "funannotate_organism_name")
    if _cfg_str(settings, "nplinker_podp_id"):
        env["PODP_ID"] = _cfg_str(settings, "nplinker_podp_id")
    if _cfg_str(settings, "massive_dataset_id"):
        env["MASSIVE_DATASET_ID"] = _cfg_str(settings, "massive_dataset_id")
    if _cfg_str(settings, "gnps_version"):
        env["GNPS_VERSION"] = _cfg_str(settings, "gnps_version")
    if "auto_pull_nplinker_sif" in settings:
        env["AUTO_PULL_NPLINKER_SIF"] = "1" if _cfg_bool(settings, "auto_pull_nplinker_sif", True) else "0"
    if "nplinker_bootstrap_env" in settings:
        env["NPLINKER_BOOTSTRAP_ENV"] = "1" if _cfg_bool(settings, "nplinker_bootstrap_env", True) else "0"
    env.update(_parse_raw_env(_cfg_str(settings, "env_overrides")))
    return env


def _script(layout: ProjectLayout, name: str) -> Path:
    path = layout.repo_root / name
    if not path.exists():
        raise FileNotFoundError(f"Missing ClusterWeave script: {path}")
    return path


def _has_genome_inputs(layout: ProjectLayout) -> bool:
    return any(
        path.is_file()
        for root in layout.genome_roots
        for path in root.glob("*")
        if path.suffix.lower() in GENOME_EXTS
    )


def _accession_versionless(value: str) -> str:
    value = value.strip().upper()
    if not re.match(r"^GC[AF]_", value):
        return ""
    return value.split(".", 1)[0]


def _resolve_target_genome_alias(layout: ProjectLayout, target: str) -> str:
    target = str(target or "").strip()
    if not target:
        return ""
    target_lower = target.lower()
    target_accession = _accession_versionless(target)
    mapping_paths = [
        layout.fungi_genome_root / "accessions_fungusID_taxonomyID.txt",
        layout.bacteria_genome_root / "accessions_bacteriaID_taxonomyID.txt",
    ]
    matches: set[str] = set()
    for mapping_path in mapping_paths:
        if not mapping_path.exists():
            continue
        try:
            with mapping_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    accession, sep, rest = line.rstrip("\n").partition("\t")
                    if not sep:
                        continue
                    genome_id = rest.split("\t", 1)[0].strip()
                    accession = accession.strip()
                    if not accession or not genome_id or accession.lower() == "accession":
                        continue
                    if target_lower == genome_id.lower():
                        matches.add(genome_id)
                    elif target_lower == accession.lower():
                        matches.add(genome_id)
                    elif target_accession and target_accession == _accession_versionless(accession):
                        matches.add(genome_id)
        except OSError:
            continue
    if len(matches) > 1:
        raise ValueError(
            f"Target genome/accession '{target}' is ambiguous across taxon mappings: "
            + ", ".join(sorted(matches))
        )
    return next(iter(matches), target)


def _is_public_result_file(path: Path, layout: ProjectLayout) -> bool:
    if layout.results_root.is_symlink() or not path.is_file() or path.is_symlink():
        return False
    try:
        rel = path.relative_to(layout.results_root).as_posix()
    except ValueError:
        return False
    cursor = layout.results_root
    for part in Path(rel).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return False
    try:
        path.resolve(strict=True).relative_to(layout.results_root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return is_public_analysis_relative_path(rel)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return (
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_size),
        int(stat.st_mtime_ns),
        int(stat.st_ctime_ns),
    )


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _write_public_manifest(
    manifest_path: Path,
    public_entries: list[tuple[Path, str]],
    *,
    known_records: Optional[
        Mapping[Path, tuple[tuple[int, int, int, int, int], str]]
    ] = None,
) -> dict[Path, tuple[tuple[int, int, int, int, int], str]]:
    lines = ["path\tbytes\tsha256"]
    records: dict[Path, tuple[tuple[int, int, int, int, int], str]] = {}
    reusable = known_records or {}
    for path, rel in public_entries:
        before = _file_identity(path)
        known = reusable.get(path)
        if known is not None:
            if known[0] != before:
                raise RuntimeError(
                    "Scientific evidence changed after its evidence manifest was generated"
                )
            digest = known[1]
        else:
            digest = _sha256(path)
        after = _file_identity(path)
        if after != before:
            raise RuntimeError("Public result changed while its manifest was generated")
        records[path] = (after, digest)
        lines.append(f"{rel}\t{after[2]}\t{digest}")
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _fsync_file(manifest_path)
    return records


def _evidence_genome_id(rel_path: str, role: str) -> str:
    parts = rel_path.split("/")
    if role == "staged_genome_genbank" and len(parts) == 2:
        return Path(parts[1]).stem
    if role in {"antismash_region_genbank", "funbgcex_bgc_genbank"} and len(parts) >= 2:
        return parts[1]
    return ""


def _evidence_taxon_metadata(layout: ProjectLayout) -> dict[str, tuple[str, str]]:
    manifest = layout.results_root / "summary_tables" / "genome_taxon_manifest.tsv"
    try:
        if manifest.is_symlink() or not manifest.is_file():
            return {}
        manifest.resolve(strict=True).relative_to(layout.results_root.resolve(strict=True))
        rows: dict[str, tuple[str, str]] = {}
        with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle, delimiter="\t"):
                genome_id = _safe_manifest_text(raw.get("genome_id"), limit=120)
                if not genome_id:
                    continue
                taxon_group = _safe_manifest_text(
                    raw.get("taxon_group"), limit=20
                ).lower()
                if taxon_group not in {"fungi", "bacteria"}:
                    taxon_group = ""
                source_accession = _public_source_accession(
                    raw.get("source_accession")
                )
                rows[genome_id.casefold()] = (taxon_group, source_accession)
        return rows
    except (OSError, ValueError, csv.Error):
        return {}


def _write_evidence_manifest(
    manifest_path: Path,
    layout: ProjectLayout,
) -> dict[Path, tuple[tuple[int, int, int, int, int], str]]:
    """Write a portable, path-redacted checksum index for exact genome evidence."""

    metadata = _evidence_taxon_metadata(layout)
    evidence: list[tuple[Path, str, str]] = []
    if layout.results_root.exists():
        for path in sorted(layout.results_root.rglob("*")):
            if not _is_public_result_file(path, layout):
                continue
            rel = path.relative_to(layout.results_root).as_posix()
            role = public_evidence_role(rel)
            if not role or role == "evidence_manifest":
                continue
            evidence.append((path, rel, role))

    lines = [
        "path\trole\tgenome_id\ttaxon_group\tsource_accession\tbytes\tsha256"
    ]
    records: dict[Path, tuple[tuple[int, int, int, int, int], str]] = {}
    for path, rel, role in evidence:
        before = _file_identity(path)
        digest = _sha256(path)
        after = _file_identity(path)
        if after != before:
            raise RuntimeError(
                "Scientific evidence changed while its evidence manifest was generated"
            )
        records[path] = (after, digest)
        genome_id = _safe_manifest_text(_evidence_genome_id(rel, role), limit=120)
        taxon_group, source_accession = metadata.get(
            genome_id.casefold(), ("", "")
        )
        lines.append(
            "\t".join(
                [
                    rel,
                    role,
                    genome_id,
                    taxon_group,
                    source_accession,
                    str(after[2]),
                    digest,
                ]
            )
        )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _fsync_file(manifest_path)
    return records


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def _portable_package_manifest(
    public_entries: list[tuple[Path, str]],
    records: Mapping[Path, tuple[tuple[int, int, int, int, int], str]],
) -> bytes:
    lines = ["path\tbytes\tsha256"]
    for path, rel in public_entries:
        identity, digest = records[path]
        lines.append(
            f"{public_archive_entry_name(rel)}\t{identity[2]}\t{digest}"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _public_bigscape_max_bytes() -> int:
    raw = os.environ.get(
        "CLUSTERWEAVE_PUBLIC_BIGSCAPE_MAX_BYTES",
        str(DEFAULT_PUBLIC_BIGSCAPE_MAX_BYTES),
    )
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PUBLIC_BIGSCAPE_MAX_BYTES
    return max(1, min(parsed, DEFAULT_PUBLIC_BIGSCAPE_MAX_BYTES))


def _prepare_public_bigscape_results(
    job: Job,
    layout: ProjectLayout,
) -> set[Path]:
    # Publication owns this derived pointer. Clear stale metadata before each
    # attempt and advertise it only after sanitizer-side validation succeeds.
    job.bigscape_viewer_database = ""
    try:
        preparation = prepare_public_bigscape_databases(
            layout.results_root,
            max_source_bytes=_public_bigscape_max_bytes(),
        )
    except Exception as exc:
        job.add_log(
            "WARN: sanitized BiG-SCAPE database unavailable "
            f"({type(exc).__name__})."
        )
        return set()

    for error in preparation.errors:
        job.add_log(f"WARN: sanitized BiG-SCAPE database unavailable: {error}")
    for database in preparation.databases:
        action = "reused" if database.reused else "created"
        job.add_log(
            "PUBLICATION: sanitized BiG-SCAPE database "
            f"{action} ({database.public_bytes} bytes)."
        )
    viewer_paths = [
        database.viewer_path
        for database in preparation.databases
        if database.viewer_path is not None
    ]
    if len(viewer_paths) == 1:
        try:
            job.bigscape_viewer_database = viewer_paths[0].relative_to(
                layout.data_root.parent
            ).as_posix()
        except ValueError:
            job.bigscape_viewer_database = ""
        if job.bigscape_viewer_database:
            viewer_bytes = next(
                database.viewer_bytes
                for database in preparation.databases
                if database.viewer_path == viewer_paths[0]
            )
            job.add_log(
                "PUBLICATION: compact BiG-SCAPE web viewer ready "
                f"({viewer_bytes} bytes)."
            )
    return {database.public_path.resolve() for database in preparation.databases}


def _collect_result_files(
    job: Job,
    job_dir: Path,
    layout: ProjectLayout,
    *,
    attested_bigscape_databases: Optional[set[Path]] = None,
    before_publish: Optional[Callable[[], None]] = None,
) -> None:
    downloads_dir = job_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    if attested_bigscape_databases is None:
        attested_bigscape_databases = _prepare_public_bigscape_results(job, layout)
    token = secrets.token_hex(8)
    evidence_path = layout.results_root / PUBLIC_EVIDENCE_MANIFEST_PATH
    evidence_temp = evidence_path.with_name(f".{evidence_path.name}.{token}.tmp")
    known_records = _write_evidence_manifest(evidence_temp, layout)

    public_entries: list[tuple[Path, str]] = []
    if layout.results_root.exists():
        for path in sorted(layout.results_root.rglob("*")):
            if not _is_public_result_file(path, layout):
                continue
            analysis_rel = path.relative_to(layout.results_root).as_posix()
            if analysis_rel == PUBLIC_EVIDENCE_MANIFEST_PATH:
                # Keep the previous published index intact until this refresh
                # and its package have both passed the publication checks.
                continue
            if (
                result_is_public_bigscape_database(analysis_rel)
                and path.resolve() not in attested_bigscape_databases
            ):
                continue
            public_entries.append((path, path.relative_to(job_dir).as_posix()))
    public_entries.append(
        (evidence_temp, evidence_path.relative_to(job_dir).as_posix())
    )
    public_entries.sort(key=lambda entry: entry[1])

    manifest_path = downloads_dir / Path(PUBLIC_RESULTS_MANIFEST_PATH).name
    archive_path = downloads_dir / f"{layout.project_name}_public_results.zip"
    manifest_temp = downloads_dir / f".{manifest_path.name}.{token}.tmp"
    archive_temp = downloads_dir / f".{archive_path.name}.{token}.tmp"
    try:
        records = _write_public_manifest(
            manifest_temp,
            public_entries,
            known_records=known_records,
        )
        package_manifest = _portable_package_manifest(public_entries, records)
        with zipfile.ZipFile(
            archive_temp,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=1,
            allowZip64=True,
        ) as archive:
            archive.writestr(
                _zip_info(PUBLIC_RESULTS_MANIFEST_PATH),
                package_manifest,
            )
            for path, rel in public_entries:
                archive.write(path, public_archive_entry_name(rel))
                if _file_identity(path) != records[path][0]:
                    raise RuntimeError(
                        "Public result changed while its archive was generated"
                    )
        _fsync_file(archive_temp)
        if any(
            _file_identity(path) != identity
            for path, (identity, _digest) in records.items()
        ):
            raise RuntimeError(
                "Public result changed before its manifest and archive were published"
            )
        if before_publish is not None:
            before_publish()
        os.replace(archive_temp, archive_path)
        os.replace(evidence_temp, evidence_path)
        os.replace(manifest_temp, manifest_path)
        # The manifest hashes were produced and identity-checked immediately
        # above. Sign their compact index now; request handlers never need to
        # rehash the complete result bundle to render a file list.
        write_result_attestation(
            job_dir,
            job.id,
            verify_hashes=False,
            viewer_path=job.bigscape_viewer_database,
            archive_path=archive_path.relative_to(job_dir).as_posix(),
        )

    finally:
        manifest_temp.unlink(missing_ok=True)
        archive_temp.unlink(missing_ok=True)
        evidence_temp.unlink(missing_ok=True)

    job.result_files = [
        archive_path.relative_to(job_dir).as_posix(),
        manifest_path.relative_to(job_dir).as_posix(),
    ]
    job.result_files.extend(rel for _path, rel in public_entries)


async def run_pipeline(
    job: Job,
    input_files: list[Path],
    job_dir: Path,
    cpus: int = 4,
    settings: Optional[dict[str, Any]] = None,
    on_update: Optional[Callable[[], None]] = None,
) -> None:
    def notify() -> None:
        if on_update:
            on_update()

    cfg = settings if settings is not None else {}
    project_name = _safe_project_name(_cfg_str(cfg, "project_name", job.name))
    repo_root = Path(_cfg_str(cfg, "clusterweave_root", str(CLUSTERWEAVE_ROOT))).resolve()
    if not repo_root.exists():
        repo_root = Path(__file__).resolve().parents[1]

    layout = ProjectLayout(
        project_name=project_name,
        repo_root=repo_root,
        data_root=job_dir / "data",
        fungi_genome_root=job_dir / "data" / "genomes" / "fungi" / project_name,
        bacteria_genome_root=job_dir / "data" / "genomes" / "bacteria" / project_name,
        results_root=job_dir / "data" / "results" / project_name,
        software_root=GLOBAL_SOFTWARE_ROOT,
        work_root=job_dir / "work",
        downloads_root=job_dir / "downloads",
    )
    layout.software_root.mkdir(parents=True, exist_ok=True)
    layout.work_root.mkdir(parents=True, exist_ok=True)
    job.project_name = project_name
    job.result_root = str(layout.results_root.relative_to(job_dir))

    try:
        job.status = JobStatus.RUNNING
        notify()

        job.set_stage("Preparing ClusterWeave project layout")
        if _cfg_bool(cfg, "reuse_existing_layout", False) and (
            any(root.exists() for root in layout.genome_roots) or layout.results_root.exists()
        ):
            _restore_existing_layout_inputs(layout, job, cfg)
        else:
            _stage_uploaded_inputs(input_files, layout, cfg, job)
        env = _base_env(layout, cfg, cpus)
        env["CLUSTERWEAVE_JOB_ID"] = job.id
        env["CLUSTERWEAVE_CANCEL_FILE"] = str(_job_cancel_path(job))
        _raise_if_cancelled(job)
        notify()

        run_genome_prep = _cfg_bool(cfg, "run_genome_prep", layout.accession_file is not None)
        run_ncbi_install = _cfg_bool(cfg, "run_ncbi_install", False)
        run_figures = _cfg_bool(cfg, "run_figures", True)
        figures_required = _cfg_bool(cfg, "figures_required", False)
        run_nplinker = _cfg_bool(cfg, "run_nplinker", False)
        run_phylogeny = _cfg_bool(cfg, "run_phylogeny", False)
        phylogeny_required = _cfg_bool(cfg, "phylogeny_required", False)
        run_cross_kingdom_evidence = _cfg_bool(
            cfg,
            "run_cross_kingdom_evidence",
            _cfg_bool(
                cfg,
                "RUN_CROSS_KINGDOM_EVIDENCE",
                _cfg_bool(
                    cfg,
                    "run_hgt_evidence",
                    _cfg_bool(cfg, "RUN_HGT_EVIDENCE", False),
                ),
            ),
        )

        if layout.accession_file is not None and run_ncbi_install:
            await _run_required_stage(
                job,
                "Installing NCBI CLI",
                ["bash", str(_script(layout, "install_ncbi_cli.sh"))],
                cwd=layout.repo_root,
                env=env,
            )

        if layout.accession_file is not None and run_genome_prep:
            await _run_required_stage(
                job,
                "Preparing genomes from accessions",
                ["bash", str(_script(layout, "prepare_genomes_from_accessions.sh"))],
                cwd=layout.repo_root,
                env=env,
            )
            prepared_routes = _read_taxon_manifest(layout)
            if prepared_routes:
                cfg["taxon_routes"] = prepared_routes
                taxa = {row["taxon_group"] for row in prepared_routes if _route_active(row)}
                cfg["analysis_scope"] = (
                    "both" if taxa == {"fungi", "bacteria"} else next(iter(taxa), "fungi")
                )
                cfg["taxon_counts"], cfg["applicability_counts"] = _route_summaries(
                    prepared_routes
                )
                _write_taxon_manifests(
                    layout,
                    prepared_routes,
                    cfg.get("taxonomy_metadata"),
                    ecology_enabled=_cfg_bool(cfg, "run_ecology_analysis", False),
                )

        target_before = _cfg_str(cfg, "target_genome")
        target_after = _resolve_target_genome_alias(layout, target_before)
        if target_after != target_before:
            env["TARGET_GENOME"] = target_after
            cfg["target_genome"] = target_after
            if _cfg_str(cfg, "target_strain") == target_before:
                cfg["target_strain"] = target_after
            job.add_log(f"Resolved target genome/accession {target_before} to {target_after}.")

        if not _has_genome_inputs(layout):
            raise RuntimeError(
                "No genome inputs were staged. Upload FASTA/GenBank files or provide an accession list with genome preparation enabled."
            )

        await _run_required_stage(
            job,
            "Running canonical ClusterWeave workflow",
            ["bash", str(_script(layout, "run_clusterweave.sh"))],
            cwd=layout.repo_root,
            env=env,
        )

        if run_figures:
            figure_cmd = ["bash", str(_script(layout, "run_figures.sh"))]
            figure_env = dict(env)
            figure_env["PROJECT_DIR"] = str(layout.data_root.parent)
            figure_env["RENDER_FIGURES_R"] = str(layout.repo_root / "bin" / "render_summary_figures.R")
            figure_env["RENDER_BIGSCAPE_NETWORK_PY"] = str(layout.repo_root / "bin" / "render_bigscape_network.py")
            if figures_required:
                await _run_required_stage(job, "Rendering summary figures", figure_cmd, cwd=layout.repo_root, env=figure_env)
            else:
                await _run_optional_stage(job, "Rendering summary figures", figure_cmd, cwd=layout.repo_root, env=figure_env)
        else:
            job.add_log("Skipping summary figures because run_figures=0.")

        if run_phylogeny:
            phylogeny_script = layout.repo_root / "run_phylogeny.sh"
            if not phylogeny_script.is_file():
                message = (
                    "Sequence phylogeny was requested but run_phylogeny.sh is "
                    "unavailable."
                )
                if phylogeny_required:
                    raise FileNotFoundError(message)
                job.add_log(f"WARN: {message} Core outputs are retained.")
            else:
                phylogeny_env = dict(env)
                phylogeny_env["RUN_PHYLOGENY"] = "1"
                phylogeny_env["CLUSTERWEAVE_CHILD_DOCKER_CPUS"] = env[
                    "PHYLOGENY_CPUS"
                ]
                phylogeny_env["CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT"] = (
                    os.environ.get("CLUSTERWEAVE_CHILD_DOCKER_PIDS_LIMIT", "256")
                )
                phylogeny_cmd = ["bash", str(phylogeny_script)]
                try:
                    if phylogeny_required:
                        await _run_required_stage(
                            job,
                            "Running required sequence phylogeny",
                            phylogeny_cmd,
                            cwd=layout.repo_root,
                            env=phylogeny_env,
                        )
                    else:
                        await _run_optional_stage(
                            job,
                            "Running optional sequence phylogeny",
                            phylogeny_cmd,
                            cwd=layout.repo_root,
                            env=phylogeny_env,
                        )
                finally:
                    if _cfg_bool(cfg, "capture_external_artifacts", True):
                        capture_script = (
                            layout.repo_root
                            / "bin"
                            / "capture_external_artifacts.py"
                        )
                        if capture_script.is_file():
                            await _run_optional_stage(
                                job,
                                "Refreshing external artifact provenance",
                                [
                                    sys.executable,
                                    str(capture_script),
                                    "--project-root",
                                    str(layout.repo_root),
                                    "--project-name",
                                    layout.project_name,
                                    "--output",
                                    str(
                                        layout.results_root
                                        / "reproducibility"
                                        / "external_artifacts.tsv"
                                    ),
                                ],
                                cwd=layout.repo_root,
                                env=env,
                            )
                        else:
                            job.add_log(
                                "WARN: post-phylogeny provenance helper is "
                                "unavailable; the private core artifact "
                                "manifest was not refreshed."
                            )

        if run_nplinker:
            target = _cfg_str(cfg, "target_genome")
            if not target:
                raise RuntimeError("NPLinker follow-up requires a target genome or strain.")
            nplinker_env = dict(env)
            nplinker_env["SOFTWARE_ROOT"] = str(layout.software_root / "nplinker")
            nplinker_env["TOOLS_ROOT"] = str(layout.software_root)
            nplinker_env["NPLINKER_SOFTWARE_ROOT"] = str(layout.software_root / "nplinker")
            nplinker_env["TARGET_STRAIN"] = _cfg_str(cfg, "target_strain", target) or target
            nplinker_env["RUN_MODE"] = _cfg_str(cfg, "nplinker_run_mode", "local") or "local"
            await _run_required_stage(
                job,
                "Running optional NPLinker follow-up",
                ["bash", str(_script(layout, "run_nplinker.sh"))],
                cwd=layout.repo_root,
                env=nplinker_env,
            )

        if run_cross_kingdom_evidence:
            evidence_script = layout.repo_root / "run_integrated_evidence.sh"
            if not evidence_script.is_file():
                job.add_log(
                    "WARN: optional cross-kingdom evidence was requested but "
                    "run_integrated_evidence.sh is unavailable; prior outputs "
                    "are retained."
                )
            else:
                evidence_env = dict(env)
                evidence_env["RUN_CROSS_KINGDOM_EVIDENCE"] = "1"
                evidence_env["PYTHON_BIN"] = os.environ.get(
                    "PYTHON_BIN", "python3"
                )
                await _run_optional_stage(
                    job,
                    "Running optional cross-kingdom evidence",
                    ["bash", str(evidence_script)],
                    cwd=layout.repo_root,
                    env=evidence_env,
                )

        _collect_result_files(job, job_dir, layout)
        job.status = JobStatus.SUCCESS
        job.stage = "complete"
        job.add_log("Canonical ClusterWeave workflow finished successfully.")

    except asyncio.CancelledError:
        job.status = JobStatus.FAILED
        job.stage = "cancelled"
        job.error = "Cancelled by administrator"
        job.add_log("Cancelled: administrator requested stop before downstream stages.")
        raise
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = str(exc)
        job.add_log(f"FATAL: {exc}")
        try:
            _collect_result_files(job, job_dir, layout)
        except Exception as collect_exc:
            job.add_log(f"WARN: could not collect result files: {collect_exc}")
    finally:
        notify()
