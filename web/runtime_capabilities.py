#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
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


def runtime_health() -> dict[str, Any]:
    """Describe the worker runtime without mutating host/container state."""
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
    has_clinker = shutil.which("clinker") is not None

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
        "engine": engine or "auto",
        "docker_socket_enabled": docker_socket_enabled,
        "docker_cli": has_docker_cli,
        "docker_socket": has_docker_socket,
        "docker_ready": docker_ready,
        "singularity": has_singularity,
        "apptainer": has_apptainer,
        "antismash": has_antismash,
        "rscript": has_rscript,
        "stages": {
            "prepare": _stage(True, "Upload and accession staging are handled by the web worker"),
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
