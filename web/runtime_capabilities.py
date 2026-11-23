#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import shutil
import subprocess
import time
import copy
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


# The worker publishes status each second. Rehashing the SIF and launching a
# namespace probe on every heartbeat blocks cancellation and queue handling.
# This cache is only for status; every native run still verifies the runtime.
_PLANT_PROBE_CACHE = None


def _probe_file_identity(path):
    try:
        st = Path(path).stat()
        return (str(Path(path).resolve()), st.st_dev, st.st_ino, st.st_size,
                st.st_mtime_ns, st.st_ctime_ns)
    except (OSError, TypeError):
        return (str(path), None)


def plantismash_capability() -> dict[str, Any]:
    global _PLANT_PROBE_CACHE
    path = Path(os.environ.get("PLANTISMASH_SIF") or str(Path(os.environ.get("CLUSTERWEAVE_SOFTWARE_ROOT", "/data/software")) / "plantismash/plant.sif"))
    engine = os.environ.get("PLANTISMASH_ENGINE", "apptainer")
    root = Path(os.environ.get("CLUSTERWEAVE_ROOT", Path(__file__).resolve().parents[1]))
    resolved = shutil.which(engine)
    key = tuple(_probe_file_identity(p) for p in
                (path, resolved, root / 'bin/plantismash_runtime.py',
                 root / 'config/plantismash-profile.json', root / 'bin/plantismash_prereqs.py',
                 root / 'bin/plantismash_native.py')) + (engine,)
    now = time.monotonic()
    if _PLANT_PROBE_CACHE is not None:
        previous_key, expires, previous = _PLANT_PROBE_CACHE
        if key == previous_key and now < expires:
            return copy.deepcopy(previous)
    ready = False
    detail = "Accepted plantiSMASH SIF and execution engine are not configured"
    if Path(engine).name in {"apptainer", "singularity"} and resolved and path.is_file():
        command = [sys.executable, str(root / "bin/plantismash_runtime.py"), "check", "--sif", str(path), "--engine", engine]
        try:
            check = subprocess.run(command, capture_output=True, text=True, timeout=45)
            ready = check.returncode == 0
            detail = "Supplied translated plant CDS; isolated extras prerequisites verified" if ready else check.stderr.strip()[-2400:]
        except (OSError, subprocess.SubprocessError) as error:
            detail = "plantiSMASH worker execution check failed: " + str(error)
    value = _stage(ready, detail, [] if ready else ["prepared plantiSMASH with working worker isolation"])

    value.update(support="annotated-green-plants", locally_prepared=ready, experimental_prediction=False, producer="plantismash-2.0.4-clusterweave-extras-v3", profile="annotated-plants-2.0.4-extras-v3")
    _PLANT_PROBE_CACHE = (key, time.monotonic() + (60 if ready else 5), copy.deepcopy(value))
    return value


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
            "plantismash": plantismash_capability(),
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
        software = Path(os.environ.get("CLUSTERWEAVE_SOFTWARE_ROOT", "/data/software"))
        def prepared(name: str, relative: str) -> bool:
            path = Path(os.environ.get(name) or str(software / relative))
            return path.is_file() and path.stat().st_size > 0
        annotation_missing = [] if sif_ready else ["singularity/apptainer"]
        for variable, relative in (("ANTISMASH_SIF", "antismash/antismash_standalone.sif"),
                                   ("FUNBGCEX_SIF", "funbgcex/funbgcex_bundle.sif")):
            if not prepared(variable, relative):
                annotation_missing.append(variable)
        annotation_available = not annotation_missing
        bigscape_missing = [] if sif_ready else ["singularity/apptainer"]
        if not prepared("BIGSCAPE_SIF_PATH", "big_scape/bigscape_2.0.0-beta.6.sif"):
            bigscape_missing.append("BIGSCAPE_SIF_PATH")
        bigscape_available = not bigscape_missing
        clinker_available = has_clinker or (sif_ready and prepared("CLINKER_SIF_PATH", "clinker/clinker-py_0.0.32--pyhdfd78af_0.sif"))
        clinker_missing = [] if clinker_available else ["prepared clinker SIF and engine, or local clinker"]
        nplinker_available = sif_ready and prepared("NPLINKER_SIF_PATH", "nplinker/nplinker_python3.11.sif")
        nplinker_python = Path(os.environ.get("NPLINKER_VENV_DIR") or str(software / "nplinker/venv")) / "bin/python"
        nplinker_available = nplinker_available and nplinker_python.is_file() and os.access(nplinker_python, os.X_OK)
        nplinker_missing = [] if nplinker_available else ["prepared NPLinker SIF, Python environment and engine"]

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
            "plantismash": plantismash_capability(),
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
