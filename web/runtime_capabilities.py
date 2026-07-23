#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _stage(available: bool, detail: str, missing: list[str] | None = None) -> dict[str, Any]:
    return {
        "available": available,
        "detail": detail,
        "missing": missing or [],
    }


def _ncbi_cli_root() -> Path:
    configured = os.environ.get("NCBI_CLI_ROOT", "").strip()
    if configured:
        return Path(configured)
    software_root = Path(os.environ.get("CLUSTERWEAVE_SOFTWARE_ROOT", "/data/software"))
    return software_root / "ncbi_cli"


def _has_ncbi_datasets() -> bool:
    root = _ncbi_cli_root()
    return (
        shutil.which("datasets") is not None
        or (root / "datasets").is_file() and os.access(root / "datasets", os.X_OK)
        or (root / "datasets.exe").is_file()
    )


def _clusterweave_root() -> Path:
    configured = os.environ.get("CLUSTERWEAVE_ROOT", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1]


def _taxon_tree_renderer() -> Path:
    configured = os.environ.get("TAXON_TREE_RENDERER", "").strip()
    if configured:
        return Path(configured)
    return _clusterweave_root() / "bin" / "render_phylo_taxon_profile.py"


def _phylogeny_sif_path() -> Path:
    configured = os.environ.get("PHYLOGENY_SIF_PATH", "").strip()
    if configured:
        return Path(configured)
    return (
        _clusterweave_root()
        / "software"
        / "phylogeny"
        / "clusterweave_phylogeny_1.0.0.sif"
    )


def _docker_image_available(image: str) -> bool:
    if not image or shutil.which("docker") is None:
        return False
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", image],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _sequence_phylogeny_stage(
    *,
    docker_ready: bool,
    has_singularity: bool,
    has_apptainer: bool,
) -> dict[str, Any]:
    """Report a pre-installed pinned runtime without pulling or building it."""

    requested_runtime = (
        os.environ.get("PHYLOGENY_RUNTIME", "auto").strip().lower() or "auto"
    )
    image = os.environ.get(
        "PHYLOGENY_DOCKER_IMAGE", "clusterweave-phylogeny:1.0.0"
    ).strip()
    sif_path = _phylogeny_sif_path()
    docker_image_ready = docker_ready and _docker_image_available(image)
    sif_engine = "apptainer" if has_apptainer else "singularity" if has_singularity else ""
    sif_ready = bool(sif_engine) and sif_path.is_file()

    if requested_runtime == "docker":
        available = docker_image_ready
        runtime = "docker"
        missing = [] if available else [f"prebuilt Docker image {image}"]
    elif requested_runtime in {"sif", "apptainer", "singularity"}:
        available = sif_ready
        runtime = sif_engine or "sif"
        missing = [] if available else ["pinned phylogeny SIF and apptainer/singularity"]
    elif requested_runtime == "auto":
        available = docker_image_ready or sif_ready
        runtime = "docker" if docker_image_ready else sif_engine if sif_ready else "none"
        missing = [] if available else ["prebuilt phylogeny Docker image or pinned SIF"]
    else:
        available = False
        runtime = "none"
        missing = ["supported PHYLOGENY_RUNTIME (auto, docker, or sif)"]

    if available:
        detail = f"Optional pinned sequence-phylogeny runtime available via {runtime}"
    else:
        detail = (
            "Optional sequence-phylogeny runtime unavailable; the core taxonomy "
            "figure remains available"
        )
    stage = _stage(available, detail, missing)
    stage.update(
        {
            "runtime": runtime,
            "requested_runtime": requested_runtime,
            "image": image,
            "sif_available": sif_ready,
        }
    )
    return stage


def runtime_health() -> dict[str, Any]:
    """Describe the worker runtime without mutating host/container state."""
    executor = os.environ.get("CLUSTERWEAVE_EXECUTOR", "local").strip().lower() or "local"
    runtime_mode = os.environ.get("CLUSTERWEAVE_RUNTIME_MODE", "hpc-singularity")
    engine = os.environ.get("ENGINE") or os.environ.get("CLUSTERWEAVE_CONTAINER_ENGINE") or ""
    docker_socket_enabled = _truthy(os.environ.get("CLUSTERWEAVE_ENABLE_DOCKER_SOCKET"), False)
    docker_sock = Path(os.environ.get("DOCKER_HOST_SOCKET", "/var/run/docker.sock"))

    has_docker_cli = shutil.which("docker") is not None
    has_docker_socket = docker_sock.exists()
    docker_ready = docker_socket_enabled and has_docker_cli and has_docker_socket

    has_singularity = shutil.which("singularity") is not None
    has_apptainer = shutil.which("apptainer") is not None
    sif_ready = has_singularity or has_apptainer
    has_antismash = shutil.which("antismash") is not None
    has_rscript = shutil.which("Rscript") is not None
    has_ncbi_datasets = _has_ncbi_datasets()
    has_clinker = shutil.which("clinker") is not None
    has_sbatch = shutil.which("sbatch") is not None
    has_squeue = shutil.which("squeue") is not None
    has_sacct = shutil.which("sacct") is not None
    has_scancel = shutil.which("scancel") is not None
    taxon_tree_renderer = _taxon_tree_renderer()
    taxon_tree_available = taxon_tree_renderer.is_file()
    taxon_tree_stage = _stage(
        taxon_tree_available,
        (
            "Dependency-light taxonomy/BGC/GCF figure renderer available"
            if taxon_tree_available
            else "Dependency-light taxonomy/BGC/GCF figure renderer unavailable"
        ),
        [] if taxon_tree_available else ["render_phylo_taxon_profile.py"],
    )
    sequence_phylogeny_stage = _sequence_phylogeny_stage(
        docker_ready=docker_ready,
        has_singularity=has_singularity,
        has_apptainer=has_apptainer,
    )

    if executor == "slurm":
        missing = [
            name
            for name, available in [
                ("sbatch", has_sbatch),
                ("squeue", has_squeue),
                ("sacct", has_sacct),
                ("scancel", has_scancel),
            ]
            if not available
        ]
        scheduler_ready = not missing
        scheduler_detail = (
            "Slurm scheduler backend available"
            if scheduler_ready
            else "Slurm scheduler commands unavailable"
        )
        return {
            "mode": runtime_mode,
            "executor": executor,
            "engine": engine or "auto",
            "docker_socket_enabled": docker_socket_enabled,
            "docker_cli": has_docker_cli,
            "docker_socket": has_docker_socket,
            "docker_ready": docker_ready,
            "singularity": has_singularity,
            "apptainer": has_apptainer,
            "ncbi_datasets": has_ncbi_datasets,
            "slurm": {
                "sbatch": has_sbatch,
                "squeue": has_squeue,
                "sacct": has_sacct,
                "scancel": has_scancel,
            },
            "stages": {
                "prepare": _stage(scheduler_ready, scheduler_detail, missing),
                "annotation": _stage(scheduler_ready, scheduler_detail, missing),
                "bigscape": _stage(scheduler_ready, scheduler_detail, missing),
                "summary": _stage(scheduler_ready, scheduler_detail, missing),
                "clinker": _stage(scheduler_ready, scheduler_detail, missing),
                "figures": _stage(scheduler_ready, scheduler_detail, missing),
                "taxon_tree_figure": taxon_tree_stage,
                "sequence_phylogeny": sequence_phylogeny_stage,
                "nplinker": _stage(scheduler_ready, scheduler_detail, missing),
            },
        }

    if engine == "docker":
        annotation_available = docker_ready
        annotation_missing = [] if annotation_available else ["docker socket"]
        bigscape_available = docker_ready
        bigscape_missing = [] if bigscape_available else ["docker socket"]
        clinker_available = docker_ready or has_clinker
        clinker_missing = [] if clinker_available else ["docker socket or local clinker"]
        nplinker_available = docker_ready
        nplinker_missing = [] if nplinker_available else ["docker socket"]
    else:
        annotation_available = sif_ready
        annotation_missing = [] if annotation_available else ["singularity/apptainer"]
        bigscape_available = sif_ready
        bigscape_missing = [] if bigscape_available else ["singularity/apptainer"]
        clinker_available = sif_ready or has_clinker
        clinker_missing = [] if clinker_available else ["singularity/apptainer or local clinker"]
        nplinker_available = sif_ready
        nplinker_missing = [] if nplinker_available else ["singularity/apptainer"]

    return {
        "mode": runtime_mode,
        "executor": executor,
        "engine": engine or "auto",
        "docker_socket_enabled": docker_socket_enabled,
        "docker_cli": has_docker_cli,
        "docker_socket": has_docker_socket,
        "docker_ready": docker_ready,
        "singularity": has_singularity,
        "apptainer": has_apptainer,
        "antismash": has_antismash,
        "rscript": has_rscript,
        "ncbi_datasets": has_ncbi_datasets,
        "stages": {
            "prepare": _stage(
                has_ncbi_datasets,
                "NCBI Datasets CLI available for accession retrieval" if has_ncbi_datasets else "NCBI Datasets CLI unavailable for accession retrieval",
                [] if has_ncbi_datasets else ["NCBI datasets CLI"],
            ),
            "annotation": _stage(
                annotation_available,
                "antiSMASH/FunBGCeX runtime available" if annotation_available else "Annotation runtime unavailable",
                annotation_missing,
            ),
            "bigscape": _stage(
                bigscape_available,
                "BiG-SCAPE runtime available" if bigscape_available else "BiG-SCAPE runtime unavailable",
                bigscape_missing,
            ),
            "summary": _stage(True, "Summary helpers run in the worker Python environment"),
            "clinker": _stage(
                clinker_available,
                "clinker runtime available" if clinker_available else "clinker runtime unavailable",
                clinker_missing,
            ),
            "figures": _stage(
                has_rscript,
                "Rscript available" if has_rscript else "Rscript unavailable; figure stage should stay optional",
                [] if has_rscript else ["Rscript"],
            ),
            "taxon_tree_figure": taxon_tree_stage,
            "sequence_phylogeny": sequence_phylogeny_stage,
            "nplinker": _stage(
                nplinker_available,
                "NPLinker runtime available" if nplinker_available else "NPLinker runtime unavailable",
                nplinker_missing,
            ),
        },
    }


def unavailable_stage_reason(capabilities: dict[str, Any], stage: str) -> str:
    stages = capabilities.get("stages") if isinstance(capabilities, dict) else {}
    payload = stages.get(stage, {}) if isinstance(stages, dict) else {}
    missing = payload.get("missing") or []
    detail = str(payload.get("detail") or f"{stage} runtime unavailable")
    if missing:
        return f"{detail}; missing: {', '.join(str(item) for item in missing)}"
    return detail
