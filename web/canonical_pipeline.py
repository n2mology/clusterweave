#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CLUSTERWEAVE_ROOT = Path(os.environ.get("CLUSTERWEAVE_ROOT", "/clusterweave"))
GLOBAL_SOFTWARE_ROOT = Path(os.environ.get("CLUSTERWEAVE_SOFTWARE_ROOT", str(DATA_DIR / "software")))

GENOME_EXTS = {".gbk", ".gb", ".gbff", ".fasta", ".fa", ".fna", ".fsa"}
ACCESSION_EXTS = {".txt", ".tsv", ".csv"}
METADATA_EXTS = {".tsv", ".csv"}
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
    error: Optional[str] = None
    project_name: str = ""
    result_root: str = ""
    on_change: Optional[Callable[[], None]] = field(default=None, repr=False, compare=False)

    def add_log(self, line: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_lines.append(f"[{ts}] {line}")
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
            "error": self.error,
            "project_name": self.project_name,
            "result_root": self.result_root,
        }


@dataclass
class ProjectLayout:
    project_name: str
    repo_root: Path
    data_root: Path
    genome_root: Path
    results_root: Path
    software_root: Path
    work_root: Path
    downloads_root: Path
    accession_file: Optional[Path] = None
    metadata_file: Optional[Path] = None
    nplinker_gnps_dir: Optional[Path] = None
    nplinker_strain_mapping: Optional[Path] = None
    genome_inputs: list[Path] = field(default_factory=list)


async def _stream_cmd(cmd: list[str], cwd: Path, job: Job, env: dict[str, str]) -> int:
    job.add_log(f"$ {' '.join(str(item) for item in cmd)}")
    proc_env = {**os.environ, **env}
    try:
        proc = await asyncio.create_subprocess_exec(
            *[str(item) for item in cmd],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd),
            env=proc_env,
        )
        assert proc.stdout is not None
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                public_stage = _public_stage_from_stream_line(line)
                if public_stage:
                    job.stage = public_stage
                job.add_log(line)
        return await proc.wait()
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


async def _run_required_stage(job: Job, stage: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
    job.set_stage(stage)
    rc = await _stream_cmd(cmd, cwd=cwd, job=job, env=env)
    if rc != 0:
        raise RuntimeError(f"{stage} failed with exit code {rc}")


async def _run_optional_stage(job: Job, stage: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> bool:
    job.set_stage(stage)
    rc = await _stream_cmd(cmd, cwd=cwd, job=job, env=env)
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
    layout.genome_root.mkdir(parents=True, exist_ok=True)
    (layout.results_root / "summary_tables").mkdir(parents=True, exist_ok=True)
    nplinker_upload_root = layout.work_root / "nplinker_uploads"
    gnps_root = nplinker_upload_root / "gnps"
    explicit_metadata = _cfg_str(settings, "metadata_tsv")

    for src in input_files:
        suffix = src.suffix.lower()
        if suffix in GENOME_EXTS:
            copied = _copy_unique(src, layout.genome_root)
            layout.genome_inputs.append(copied)
            job.add_log(f"Staged genome input: {copied.relative_to(layout.data_root)}")
            continue
        if _looks_like_accession_file(src) and layout.accession_file is None:
            copied = _copy_unique(src, layout.downloads_root, "accessions.txt")
            layout.accession_file = copied
            job.add_log(f"Staged accession list: {copied.relative_to(layout.data_root.parent)}")
            continue
        if _looks_like_metadata_file(src) and layout.metadata_file is None:
            dest_name = Path(explicit_metadata).name if explicit_metadata else "ecofun_metadata_normalized.tsv"
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


def _restore_existing_layout_inputs(layout: ProjectLayout, job: Job) -> None:
    accession_file = layout.downloads_root / "accessions.txt"
    if accession_file.exists():
        layout.accession_file = accession_file

    metadata_root = layout.results_root / "summary_tables"
    for candidate in [
        metadata_root / "ecofun_metadata_normalized.tsv",
        metadata_root / "ecofun_metadata_template.tsv",
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

    layout.genome_inputs = [
        path for path in sorted(layout.genome_root.glob("*"))
        if path.is_file() and path.suffix.lower() in GENOME_EXTS
    ]
    job.add_log("Reusing existing staged ClusterWeave layout for rerun.")


def _parse_raw_env(raw: str) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if ENV_KEY_RE.match(key):
            overrides[key] = value.strip().strip("\"'")
    return overrides


def _base_env(layout: ProjectLayout, settings: dict[str, Any], cpus: int) -> dict[str, str]:
    threads = _cfg_int(settings, "threads", cpus)
    env = {
        "PROJECT_DIR": str(layout.repo_root),
        "PROJECT_ROOT": str(layout.repo_root),
        "PROJECTS_ROOT": str(layout.data_root.parent),
        "PROJECT_NAME": layout.project_name,
        "DATA_ROOT": str(layout.data_root),
        "RESULTS_BASE": str(layout.data_root / "results"),
        "RESULTS_ROOT": str(layout.results_root),
        "GENOMES_ROOT": str(layout.data_root / "genomes" / "fungi"),
        "GENOME_ROOT": str(layout.genome_root),
        "SOFTWARE_ROOT": str(layout.software_root),
        "TOOLS_ROOT": str(layout.software_root),
        "WORK_ROOT": str(layout.work_root),
        "STAGE_DIR": str(layout.work_root / "bigscape_stage_region_gbks"),
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
        "CPUS": str(cpus),
        "THREADS": str(threads),
        "ANNO_CPUS": str(_cfg_int(settings, "anno_cpus", cpus)),
        "WORKERS": str(_cfg_int(settings, "workers", 2)),
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
        "ECOLOGY_FIELD": _cfg_str(settings, "ecology_field", "ecofun_primary") or "ecofun_primary",
        "FOCUS_ECOLOGY_LABEL": _cfg_str(settings, "focus_ecology_label"),
        "AUTO_NORMALIZE_METADATA": "1" if _cfg_bool(settings, "auto_normalize_metadata", True) else "0",
        "CAPTURE_EXTERNAL_ARTIFACTS": "1" if _cfg_bool(settings, "capture_external_artifacts", True) else "0",
        "ATLAS_STAGE_LIMIT": str(_cfg_int(settings, "atlas_stage_limit", _cfg_int(settings, "shortlist_limit", 12))),
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
    return any(path.is_file() for path in layout.genome_root.glob("*") if path.suffix.lower() in GENOME_EXTS)


PUBLIC_SUMMARY_FILENAMES = {
    "all_tools_shared_unshared_summary.csv",
    "family_atlas_shortlist.md",
    "family_atlas_shortlist.tsv",
    "priority_shortlist.md",
    "priority_shortlist.tsv",
    "shared_family_shortlist.md",
    "shared_family_shortlist.tsv",
}
PUBLIC_SUMMARY_TABLE_FILENAMES = {
    "ecofun_metadata_normalized.tsv",
    "ecofun_metadata_template.tsv",
}
PUBLIC_FIGURE_EXTENSIONS = {".svg", ".png", ".pdf", ".graphml", ".tsv"}


def _is_public_result_file(path: Path, layout: ProjectLayout) -> bool:
    if not path.is_file():
        return False
    try:
        rel = path.relative_to(layout.results_root).as_posix()
    except ValueError:
        return False
    lower = rel.lower()
    if any(marker in f"/{lower}" for marker in [
        "/antismash/",
        "/funbgcex/",
        "/funannotate/",
        "/braker3/",
        "/big_scape/",
        "/input_gbks/",
        "/summary_tables/logs/",
        "/reproducibility/",
        "/clinker/",
    ]):
        return False
    parts = rel.split("/")
    filename = parts[-1]
    if len(parts) >= 2 and parts[0] == "figures" and path.suffix.lower() in PUBLIC_FIGURE_EXTENSIONS:
        return True
    if len(parts) == 2 and parts[0] == "summary" and filename in PUBLIC_SUMMARY_FILENAMES:
        return True
    if len(parts) == 2 and parts[0] == "summary_tables" and filename in PUBLIC_SUMMARY_TABLE_FILENAMES:
        return True
    return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_public_manifest(manifest_path: Path, job_dir: Path, public_paths: list[Path]) -> None:
    lines = ["path\tbytes\tsha256"]
    for path in public_paths:
        rel = path.relative_to(job_dir).as_posix()
        lines.append(f"{rel}\t{path.stat().st_size}\t{_sha256(path)}")
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _collect_result_files(job: Job, job_dir: Path, layout: ProjectLayout) -> None:
    job.result_files = []
    downloads_dir = job_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    public_paths: list[Path] = []
    if layout.results_root.exists():
        public_paths = [
            path for path in sorted(layout.results_root.rglob("*"))
            if _is_public_result_file(path, layout)
        ]

    manifest_path = downloads_dir / "public_results_manifest.tsv"
    _write_public_manifest(manifest_path, job_dir, public_paths)

    archive_path = downloads_dir / f"{layout.project_name}_public_results.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in public_paths:
            archive.write(path, path.relative_to(job_dir).as_posix())

    job.result_files = [
        archive_path.relative_to(job_dir).as_posix(),
        manifest_path.relative_to(job_dir).as_posix(),
    ]
    job.result_files.extend(path.relative_to(job_dir).as_posix() for path in public_paths)


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

    cfg = settings or {}
    project_name = _safe_project_name(_cfg_str(cfg, "project_name", job.name))
    repo_root = Path(_cfg_str(cfg, "clusterweave_root", str(CLUSTERWEAVE_ROOT))).resolve()
    if not repo_root.exists():
        repo_root = Path(__file__).resolve().parents[1]

    layout = ProjectLayout(
        project_name=project_name,
        repo_root=repo_root,
        data_root=job_dir / "data",
        genome_root=job_dir / "data" / "genomes" / "fungi" / project_name,
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
            layout.genome_root.exists() or layout.results_root.exists()
        ):
            _restore_existing_layout_inputs(layout, job)
        else:
            _stage_uploaded_inputs(input_files, layout, cfg, job)
        env = _base_env(layout, cfg, cpus)
        notify()

        run_genome_prep = _cfg_bool(cfg, "run_genome_prep", layout.accession_file is not None)
        run_ncbi_install = _cfg_bool(cfg, "run_ncbi_install", False)
        run_figures = _cfg_bool(cfg, "run_figures", True)
        figures_required = _cfg_bool(cfg, "figures_required", False)
        run_nplinker = _cfg_bool(cfg, "run_nplinker", False)

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

        _collect_result_files(job, job_dir, layout)
        job.status = JobStatus.SUCCESS
        job.stage = "complete"
        job.add_log("Canonical ClusterWeave workflow finished successfully.")

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
