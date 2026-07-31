#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Iterable, Mapping


SCHEMA = "clusterweave.runtime-preparation.v1"
FASTTREE_URL = (
    "https://raw.githubusercontent.com/morgannprice/fasttree/"
    "29c5e62fbcd93230ee325f9c6a17b81f00e3c72a/FastTree"
)
FASTTREE_SHA256 = "55a9d997813aae2208bd4c2081bfa690e0ecdba2d6c491805d8689415c43e38e"
NPLINKER_VERSION = "2.0.0"
PFAM_URL = "https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release/Pfam-A.hmm.gz"
MIBIG_VERSION = "4.0"
MIBIG_URL = "https://dl.secondarymetabolites.org/mibig/mibig_antismash_4.0_gbk_as8b1.tar.bz2"
FUNANNOTATE_BUSCO_DBS = "ascomycota basidiomycota microsporidia dikarya fungi"


class PreparationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class Executor:
    def which(self, command: str) -> str | None:
        return shutil.which(command)

    def run(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        capture: bool = True,
    ) -> CommandResult:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            text=True,
            check=False,
        )
        return CommandResult(
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )

    def run_with_progress(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None,
        cwd: Path | None,
        callback: Any,
    ) -> CommandResult:
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout:
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr:
                process = subprocess.Popen(
                    args,
                    cwd=str(cwd) if cwd is not None else None,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                )
                progress = 0
                while True:
                    try:
                        returncode = process.wait(timeout=2)
                        break
                    except subprocess.TimeoutExpired:
                        progress = min(99, progress + 1)
                        callback(progress)
                stdout.seek(0)
                stderr.seek(0)
                return CommandResult(returncode, stdout.read(), stderr.read())


@dataclass(frozen=True)
class ImageSpec:
    key: str
    reference: str
    mode: str
    scope: str


@dataclass
class PreparationReport:
    profile: str
    scope: str
    ready: bool = True
    changed: bool = False
    assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "profile": self.profile,
            "scope": self.scope,
            "ready": self.ready,
            "changed": self.changed,
            "assets": self.assets,
            "errors": self.errors,
        }


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _env_path(env: Mapping[str, str], key: str, default: Path) -> Path:
    value = env.get(key, "").strip()
    return Path(value) if value else default


def _image_from_uri(value: str) -> str:
    return value.removeprefix("docker://")


def local_image_specs(env: Mapping[str, str], root: Path) -> list[ImageSpec]:
    del root
    return [
        ImageSpec(
            "clinker_image",
            env.get(
                "CLINKER_DOCKER_IMAGE",
                "quay.io/biocontainers/clinker-py:0.0.32--pyhdfd78af_0",
            ),
            "pull",
            "startup",
        ),
        ImageSpec(
            "bigscape_image",
            env.get(
                "BIGSCAPE_DOCKER_IMAGE",
                "ghcr.io/medema-group/big-scape:2.0.0-beta.6",
            ),
            "pull",
            "startup",
        ),
        ImageSpec(
            "funbgcex_image",
            env.get("FUNBGCEX_DOCKER_IMAGE", "clusterweave-funbgcex:latest"),
            "funbgcex-build",
            "startup",
        ),
        ImageSpec(
            "braker3_image",
            _image_from_uri(
                env.get(
                    "BRAKER_IMAGE_URI",
                    "docker://teambraker/braker3:v3.0.7.6@sha256:"
                    "5f8b3c508a9fe1bbc2e9a74dcc013eeed82f91dd5945adca7823514d9c8aecf8",
                )
            ),
            "pull",
            "all",
        ),
        ImageSpec(
            "funannotate_image",
            _image_from_uri(
                env.get(
                    "FUNANNOTATE_IMAGE_URI",
                    "docker://clusterweave-funannotate:v1.8.17-busco",
                )
            ),
            "funannotate-build",
            "all",
        ),
        ImageSpec(
            "nplinker_image",
            env.get("NPLINKER_DOCKER_IMAGE", "python:3.11-slim"),
            "pull",
            "all",
        ),
    ]


def funannotate_validation_command(
    env: Mapping[str, str], root: Path
) -> list[str]:
    helper = _env_path(
        env,
        "FUNANNOTATE_BUILD_SCRIPT",
        root / "software" / "funannotate" / "build_funannotate_sif.sh",
    )
    return ["bash", str(helper), "validate"]


class StatusWriter:
    def __init__(self, path: Path | None, env: Mapping[str, str]) -> None:
        self.path = path
        self.env = env

    def update(self, phase: str, progress: int, detail: str, substep: str) -> None:
        if self.path is None:
            return
        capabilities: dict[str, Any] = {}
        roots = [Path("/app"), Path(self.env.get("CLUSTERWEAVE_ROOT", "")) / "web"]
        for root in roots:
            if not root.is_dir():
                continue
            inserted = False
            try:
                if str(root) not in sys.path:
                    sys.path.insert(0, str(root))
                    inserted = True
                from runtime_capabilities import runtime_health

                capabilities = runtime_health()
                break
            except Exception:
                capabilities = {}
            finally:
                if inserted:
                    sys.path.remove(str(root))
        payload = {
            "ready": False,
            "state": "bootstrapping",
            "phase": phase,
            "progress": max(0, min(100, int(progress))),
            "detail": detail,
            "substep": substep,
            "updated_at": datetime.now().isoformat(),
            "runtime": {
                "mode": capabilities.get("mode"),
                "engine": capabilities.get("engine"),
                "docker_ready": capabilities.get("docker_ready"),
                "docker_socket_enabled": capabilities.get("docker_socket_enabled"),
            }
            if capabilities
            else {},
            "capabilities": capabilities,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        os.replace(temporary, self.path)


class RuntimePreparer:
    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        executor: Executor | None = None,
        profile: str | None = None,
        manifest_path: Path | None = None,
        status_path: Path | None = None,
    ) -> None:
        self.env = dict(os.environ if env is None else env)
        self.executor = executor or Executor()
        self.root = _env_path(
            self.env, "CLUSTERWEAVE_ROOT", Path(__file__).resolve().parents[1]
        )
        software_default = self.root / "software"
        self.software_root = _env_path(
            self.env, "CLUSTERWEAVE_SOFTWARE_ROOT", software_default
        )
        self.profile = profile or self._infer_profile()
        self.manifest_path = manifest_path or _env_path(
            self.env,
            "RUNTIME_PREPARATION_MANIFEST",
            self.software_root / "runtime-preparation.v1.json",
        )
        self.status = StatusWriter(status_path, self.env)
        self._assets: dict[str, dict[str, Any]] = {}
        self._changed = False
        self._active_status: tuple[str, str, str] | None = None

    def _infer_profile(self) -> str:
        mode = self.env.get("CLUSTERWEAVE_RUNTIME_MODE", "").strip().lower()
        if mode == "lab-docker":
            return "local-docker"
        if mode == "public-queue" or self.env.get("CLUSTERWEAVE_EXECUTOR", "").strip():
            return "external"
        engine = self.env.get("ENGINE", "").strip().lower()
        return "local-docker" if engine == "docker" else "external"

    @staticmethod
    def _truthy(value: str | None) -> bool:
        return (value or "").strip().lower() in {"1", "true", "yes", "on"}

    def _record(self, key: str, **values: Any) -> None:
        self._assets[key] = {name: value for name, value in values.items() if value is not None}

    def _command_env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        result = os.environ.copy()
        result.update(self.env)
        if extra:
            result.update(extra)
        return result

    def _run(
        self,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> CommandResult:
        return self.executor.run(
            args,
            env=self._command_env(env),
            cwd=cwd,
            capture=True,
        )

    def _run_required(
        self,
        args: list[str],
        *,
        label: str,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> CommandResult:
        command_env = self._command_env(env)
        if (
            type(self.executor) is Executor
            and self._active_status is not None
            and self.status.path is not None
        ):
            result = self.executor.run_with_progress(
                args,
                env=command_env,
                cwd=cwd,
                callback=self._publish_progress,
            )
        else:
            result = self.executor.run(
                args,
                env=command_env,
                cwd=cwd,
                capture=True,
            )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            suffix = f": {detail[-500:]}" if detail else ""
            raise PreparationError(f"{label} failed{suffix}")
        return result

    def _require_command(self, command: str) -> str:
        resolved = self.executor.which(command)
        if not resolved:
            raise PreparationError(f"required command unavailable: {command}")
        return resolved

    def _validate_profile(self) -> None:
        socket_enabled = self._truthy(
            self.env.get("CLUSTERWEAVE_ENABLE_DOCKER_SOCKET")
        )
        if self.profile == "local-docker":
            if not socket_enabled:
                raise PreparationError(
                    "local-docker preparation requires the explicit Docker socket gate"
                )
            if self.env.get("ENGINE", "docker").strip().lower() != "docker":
                raise PreparationError("local-docker preparation requires ENGINE=docker")
            self._require_command("docker")
            socket_path = Path(
                self.env.get("DOCKER_HOST_SOCKET", "/var/run/docker.sock")
            )
            if not socket_path.exists():
                raise PreparationError(f"Docker socket is unavailable: {socket_path}")
            self._run_required(["docker", "info"], label="Docker daemon check")
            self._record(
                "profile",
                mode="local-docker",
                docker_socket_enabled=True,
            )
            return
        if self.profile == "external":
            if socket_enabled:
                raise PreparationError(
                    "external preparation refuses an enabled Docker socket gate"
                )
            self._record(
                "profile",
                mode="external",
                docker_socket_enabled=False,
            )
            return
        raise PreparationError(
            f"unsupported preparation profile: {self.profile} "
            "(expected local-docker or external)"
        )

    def _phase(self, phase: str, detail: str, operation: str) -> None:
        substep = f"{operation} {detail}"
        self._active_status = (phase, detail, substep)
        self.status.update(phase, 0, detail, substep)

    def _publish_progress(self, progress: int) -> None:
        if self._active_status is None:
            return
        phase, detail, substep = self._active_status
        self.status.update(phase, progress, detail, substep)

    def _complete_phase(
        self, phase: str, detail: str, substep: str | None = None
    ) -> None:
        self.status.update(phase, 100, detail, substep or f"{detail} ready")
        self._active_status = None

    def _check_worker_components(self) -> None:
        self._require_command("python3")
        self._require_command("Rscript")
        self._run_required(["Rscript", "--version"], label="Rscript check")

        antismash = self._require_command("antismash")
        self._run_required([antismash, "--version"], label="antiSMASH check")

        module_candidates = [
            self.root / "web" / "genbank_readiness.py",
            Path("/app/genbank_readiness.py"),
        ]
        genbank_module = next((path for path in module_candidates if path.is_file()), None)
        if genbank_module is None:
            raise PreparationError("shared GenBank readiness module is unavailable")
        required_helpers = [
            self.root / "bin" / "gff3_to_gbk_with_translations.py",
            self.root / "bin" / "nplinker_run_and_export.py",
        ]
        missing = [str(path) for path in required_helpers if not path.is_file()]
        if missing:
            raise PreparationError(
                "canonical runtime helper unavailable: " + ", ".join(missing)
            )
        self._record(
            "worker_components",
            rscript=True,
            antismash=True,
            genbank_readiness_sha256=sha256_file(genbank_module),
            canonical_helpers={
                path.name: sha256_file(path) for path in required_helpers
            },
        )
    def _antismash_database(self, mutate: bool) -> None:
        phase = "antismash"
        directory = _env_path(
            self.env, "ANTISMASH_DB_DIR", Path("/databases/antismash")
        )
        marker = directory / ".databases_downloaded"
        cached = marker.is_file()
        if not cached:
            self._phase(
                phase,
                "Downloading antiSMASH databases",
                "Preparing" if mutate else "Checking",
            )
        if not marker.is_file():
            if not mutate:
                raise PreparationError(f"antiSMASH databases are not prepared: {directory}")
            self._require_command("download-antismash-databases")
            directory.mkdir(parents=True, exist_ok=True)
            self._run_required(
                [
                    "download-antismash-databases",
                    "--database-dir",
                    str(directory),
                ],
                label="antiSMASH database preparation",
            )
            marker.touch()
            self._changed = True
        self._record(
            "antismash_database",
            path=str(directory),
            marker=marker.name,
        )
        if cached:
            self._complete_phase(
                phase,
                "antiSMASH databases already present",
                "Using cached antiSMASH databases",
            )
        else:
            self._complete_phase(
                phase, "antiSMASH databases ready", "Database bundle available"
            )

    def _pfam(self, mutate: bool) -> None:
        phase = "pfam"
        directory = _env_path(self.env, "PFAM_DIR", Path("/databases/pfam"))
        hmm = _env_path(self.env, "PFAM_HMM", directory / "Pfam-A.hmm")
        indexes = [hmm.with_name(f"{hmm.name}.{suffix}") for suffix in ("h3f", "h3i", "h3m", "h3p")]
        cached = hmm.is_file() and hmm.stat().st_size > 0 and all(
            index.is_file() and index.stat().st_size > 0 for index in indexes
        )
        if not cached:
            self._phase(
                phase,
                "Preparing Pfam-A database",
                "Preparing" if mutate else "Checking",
            )
        if not hmm.is_file() or hmm.stat().st_size == 0:
            if not mutate:
                raise PreparationError(f"Pfam-A.hmm is not prepared: {hmm}")
            self._require_command("curl")
            directory.mkdir(parents=True, exist_ok=True)
            compressed = directory / ".Pfam-A.hmm.gz.download"
            expanded = directory / ".Pfam-A.hmm.download"
            try:
                self._run_required(
                    [
                        "curl",
                        "-fL",
                        "--retry",
                        "3",
                        "--show-error",
                        "-o",
                        str(compressed),
                        self.env.get("PFAM_URL", PFAM_URL),
                    ],
                    label="Pfam download",
                )
                with gzip.open(compressed, "rb") as source, expanded.open("wb") as target:
                    shutil.copyfileobj(source, target)
                if expanded.stat().st_size == 0:
                    raise PreparationError("downloaded Pfam-A.hmm is empty")
                os.replace(expanded, hmm)
            finally:
                compressed.unlink(missing_ok=True)
                expanded.unlink(missing_ok=True)
            self._changed = True
        if any(not index.is_file() or index.stat().st_size == 0 for index in indexes):
            if not mutate:
                raise PreparationError(f"Pfam-A indexes are not prepared beside {hmm}")
            self._require_command("hmmpress")
            self._phase(phase, "Indexing Pfam-A database", "Preparing")
            self._run_required(["hmmpress", "-f", str(hmm)], label="Pfam indexing")
            self._changed = True
        if any(not index.is_file() or index.stat().st_size == 0 for index in indexes):
            raise PreparationError(f"Pfam-A index preparation is incomplete beside {hmm}")
        self._record(
            "pfam",
            path=str(hmm),
            sha256=sha256_file(hmm),
            indexes=[index.name for index in indexes],
        )
        if cached:
            self._complete_phase(
                phase,
                "Pfam-A database already present",
                "Using cached Pfam database",
            )
        else:
            self._complete_phase(phase, "Pfam-A database ready", "Pfam index ready")

    def _ncbi_cli_paths(self) -> tuple[Path | None, Path | None]:
        root = _env_path(
            self.env, "NCBI_CLI_ROOT", self.software_root / "ncbi_cli"
        )
        datasets = root / "datasets"
        dataformat = root / "dataformat"
        datasets_path = datasets if datasets.is_file() and os.access(datasets, os.X_OK) else None
        dataformat_path = dataformat if dataformat.is_file() and os.access(dataformat, os.X_OK) else None
        if datasets_path is None:
            resolved = self.executor.which("datasets")
            datasets_path = Path(resolved) if resolved else None
        if dataformat_path is None:
            resolved = self.executor.which("dataformat")
            dataformat_path = Path(resolved) if resolved else None
        return datasets_path, dataformat_path

    def _ncbi_cli(self, mutate: bool) -> None:
        phase = "ncbi_cli"
        datasets, dataformat = self._ncbi_cli_paths()
        cached = datasets is not None and dataformat is not None
        if not cached:
            self._phase(
                phase,
                "Installing NCBI Datasets CLI",
                "Preparing" if mutate else "Checking",
            )
        if datasets is None or dataformat is None:
            if not mutate:
                raise PreparationError("NCBI datasets and dataformat CLIs are not prepared")
            installer = _env_path(
                self.env,
                "NCBI_CLI_INSTALLER",
                self.root / "install_ncbi_cli.sh",
            )
            if not installer.is_file():
                raise PreparationError(f"NCBI CLI installer is unavailable: {installer}")
            install_root = _env_path(
                self.env, "NCBI_CLI_ROOT", self.software_root / "ncbi_cli"
            )
            install_root.mkdir(parents=True, exist_ok=True)
            self._run_required(
                ["bash", str(installer)],
                label="NCBI CLI preparation",
                env={
                    "PROJECT_ROOT": str(self.root),
                    "INSTALL_DIR": str(install_root),
                },
            )
            datasets, dataformat = self._ncbi_cli_paths()
            self._changed = True
        if datasets is None or dataformat is None:
            raise PreparationError("NCBI CLI preparation did not produce both tools")
        self._run_required([str(datasets), "version"], label="datasets version check")
        self._run_required([str(dataformat), "version"], label="dataformat version check")
        self._record(
            "ncbi_datasets",
            path=str(datasets),
            sha256=sha256_file(datasets),
        )
        self._record(
            "ncbi_dataformat",
            path=str(dataformat),
            sha256=sha256_file(dataformat),
        )
        if cached:
            self._complete_phase(
                phase, "NCBI Datasets CLI ready", "Using cached datasets/dataformat"
            )
        else:
            self._complete_phase(
                phase, "NCBI Datasets CLI ready", "datasets/dataformat installed"
            )

    def _docker_image_identity(self, reference: str) -> str | None:
        result = self._run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", reference]
        )
        if result.returncode != 0:
            return None
        identity = result.stdout.strip()
        return identity or None

    @staticmethod
    def _require_versioned_image(spec: ImageSpec) -> None:
        if not spec.reference:
            raise PreparationError(f"{spec.key} image reference is empty")
        if spec.mode != "funbgcex-build" and (
            spec.reference.endswith(":latest")
            or (":" not in spec.reference.rsplit("/", 1)[-1] and "@sha256:" not in spec.reference)
        ):
            raise PreparationError(
                f"{spec.key} image must use an explicit version or digest: {spec.reference}"
            )

    def _prepare_image(self, spec: ImageSpec, mutate: bool) -> None:
        phase = spec.key
        self._require_versioned_image(spec)
        identity = self._docker_image_identity(spec.reference)
        cached = identity is not None
        if not cached:
            details = {
                "clinker_image": "Pulling clinker container image",
                "bigscape_image": "Pulling BiG-SCAPE container image",
                "funbgcex_image": "Building FunBGCeX container image",
            }
            detail = details.get(spec.key, spec.key.replace("_", " "))
            self._phase(phase, detail, "Preparing" if mutate else "Checking")
        if identity is None:
            if not mutate:
                raise PreparationError(f"container image is not prepared: {spec.reference}")
            if spec.mode == "pull":
                self._run_required(
                    ["docker", "pull", spec.reference],
                    label=f"{spec.key} pull",
                )
            elif spec.mode == "funbgcex-build":
                dockerfile = _env_path(
                    self.env,
                    "FUNBGCEX_DOCKERFILE",
                    self.root / "software" / "funbgcex" / "Dockerfile",
                )
                context = _env_path(
                    self.env,
                    "FUNBGCEX_BUILD_CONTEXT",
                    dockerfile.parent,
                )
                if not dockerfile.is_file():
                    raise PreparationError(f"FunBGCeX Dockerfile is unavailable: {dockerfile}")
                self._run_required(
                    [
                        "docker",
                        "build",
                        "-t",
                        spec.reference,
                        "-f",
                        str(dockerfile),
                        str(context),
                    ],
                    label="FunBGCeX image build",
                )
            elif spec.mode == "funannotate-build":
                command = funannotate_validation_command(self.env, self.root)
                helper = Path(command[1])
                if not helper.is_file():
                    raise PreparationError(
                        f"funannotate build helper is unavailable: {helper}"
                    )
                base_image = _image_from_uri(
                    self.env.get(
                        "FUNANNOTATE_BASE_IMAGE_URI",
                        "docker://nextgenusfs/funannotate:v1.8.17",
                    )
                )
                self._run_required(
                    ["bash", str(helper), "docker"],
                    label="funannotate image build",
                    env={
                        "IMAGE_TAG": spec.reference,
                        "FUNANNOTATE_BASE_IMAGE": base_image,
                        "FUNANNOTATE_BUSCO_DBS": self.env.get(
                            "FUNANNOTATE_BUSCO_DBS", FUNANNOTATE_BUSCO_DBS
                        ),
                    },
                )
            else:
                raise PreparationError(f"unsupported image preparation mode: {spec.mode}")
            identity = self._docker_image_identity(spec.reference)
            self._changed = True
        if identity is None:
            raise PreparationError(f"container image preparation failed: {spec.reference}")
        if spec.mode == "funannotate-build":
            command = funannotate_validation_command(self.env, self.root)
            self._run_required(
                command,
                label="funannotate BUSCO validation",
                env={
                    "IMAGE_TAG": spec.reference,
                    "FUNANNOTATE_BUSCO_DBS": self.env.get(
                        "FUNANNOTATE_BUSCO_DBS", FUNANNOTATE_BUSCO_DBS
                    ),
                },
            )
        self._record(spec.key, reference=spec.reference, identity=identity)
        completion = {
            "clinker_image": ("clinker container image ready", "Image ready"),
            "bigscape_image": ("BiG-SCAPE container image ready", "Image ready"),
            "funbgcex_image": (
                "FunBGCeX container image ready",
                "Image already present" if cached else "Image build attempted",
            ),
        }
        detail, substep = completion.get(
            spec.key, (spec.key.replace("_", " "), "Image ready")
        )
        self._complete_phase(phase, detail, substep)

    def _fasttree(self, mutate: bool) -> None:
        path = _env_path(
            self.env,
            "FASTTREE_HOST",
            self.software_root / "big_scape" / "bin" / "fasttree",
        )
        expected = self.env.get("FASTTREE_SHA256", FASTTREE_SHA256).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise PreparationError("FASTTREE_SHA256 must be 64 lowercase hexadecimal characters")
        self._phase("fasttree", "FastTree", "Preparing" if mutate else "Checking")
        if not path.is_file():
            if not mutate:
                raise PreparationError(f"FastTree is not prepared: {path}")
            self._require_command("curl")
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as handle:
                temporary = Path(handle.name)
            try:
                self._run_required(
                    [
                        "curl",
                        "-fL",
                        "--retry",
                        "3",
                        "--show-error",
                        "-o",
                        str(temporary),
                        self.env.get("FASTTREE_URL", FASTTREE_URL),
                    ],
                    label="FastTree download",
                )
                if sha256_file(temporary) != expected:
                    raise PreparationError("FastTree checksum mismatch")
                temporary.chmod(0o755)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            self._changed = True
        actual = sha256_file(path)
        if actual != expected:
            raise PreparationError(f"FastTree checksum mismatch for {path}")
        self._record("fasttree", path=str(path), sha256=actual)
        self._complete_phase("fasttree", "FastTree")

    @staticmethod
    def _safe_extract(archive: Path, destination: Path) -> None:
        destination_resolved = destination.resolve()
        with tarfile.open(archive, "r:*") as handle:
            validated: list[tuple[tarfile.TarInfo, Path]] = []
            for member in handle.getmembers():
                if not member.isfile() and not member.isdir():
                    raise PreparationError(
                        f"MiBIG archive contains unsupported member: {member.name}"
                    )
                target = (destination / member.name).resolve()
                try:
                    target.relative_to(destination_resolved)
                except ValueError as exc:
                    raise PreparationError(
                        f"MiBIG archive escapes destination: {member.name}"
                    ) from exc
                validated.append((member, target))
            for member, target in validated:
                if member.isdir():
                    if target.exists() and not target.is_dir():
                        raise PreparationError(
                            f"MiBIG archive contains conflicting member: {member.name}"
                        )
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if target.exists():
                    raise PreparationError(
                        f"MiBIG archive contains duplicate member: {member.name}"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                source = handle.extractfile(member)
                if source is None:
                    raise PreparationError(
                        f"MiBIG archive member cannot be read: {member.name}"
                    )
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)

    @staticmethod
    def _mibig_files(version_dir: Path) -> list[Path]:
        if not version_dir.is_dir():
            return []
        return sorted(
            path
            for path in version_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".gb", ".gbk"}
        )

    @staticmethod
    def _tree_sha256(root: Path, files: Iterable[Path]) -> str:
        digest = hashlib.sha256()
        for path in files:
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(bytes.fromhex(sha256_file(path)))
        return digest.hexdigest()

    def _mibig(self, mutate: bool) -> None:
        cache = _env_path(
            self.env,
            "MIBIG_CACHE",
            self.software_root / "big_scape" / "resources" / "mibig_cache",
        )
        version = self.env.get("MIBIG_VERSION_DEFAULT", MIBIG_VERSION)
        expected = cache / f"mibig_antismash_{version}_gbk"
        self._phase("mibig", "MiBIG GenBank cache", "Preparing" if mutate else "Checking")
        files = self._mibig_files(expected)
        if not files:
            if not mutate:
                raise PreparationError(f"MiBIG cache is not prepared: {expected}")
            self._require_command("curl")
            cache.mkdir(parents=True, exist_ok=True)
            local_archives = sorted(cache.glob(f"mibig_antismash_{version}_gbk*.tar.bz2"))
            downloaded: Path | None = None
            if local_archives:
                archive = local_archives[0]
            else:
                with tempfile.NamedTemporaryFile(
                    dir=cache, prefix=".mibig.", suffix=".tar.bz2", delete=False
                ) as handle:
                    downloaded = Path(handle.name)
                archive = downloaded
                self._run_required(
                    [
                        "curl",
                        "-fL",
                        "--retry",
                        "3",
                        "--show-error",
                        "-o",
                        str(archive),
                        self.env.get("MIBIG_GBK_URL", "")
                        or self.env.get("MIBIG_URL", MIBIG_URL),
                    ],
                    label="MiBIG download",
                )
            staging = Path(tempfile.mkdtemp(dir=cache, prefix=".mibig-extract."))
            try:
                self._safe_extract(archive, staging)
                candidates = sorted(
                    path
                    for path in staging.glob(f"mibig_antismash_{version}_gbk*")
                    if path.is_dir()
                )
                if len(candidates) != 1 or not self._mibig_files(candidates[0]):
                    raise PreparationError(
                        "MiBIG archive did not contain one BiG-SCAPE-ready GenBank tree"
                    )
                if expected.exists():
                    raise PreparationError(
                        f"refusing to replace incomplete MiBIG directory: {expected}"
                    )
                os.replace(candidates[0], expected)
            finally:
                if downloaded is not None:
                    downloaded.unlink(missing_ok=True)
                shutil.rmtree(staging, ignore_errors=True)
            files = self._mibig_files(expected)
            self._changed = True
        if not files:
            raise PreparationError(f"MiBIG cache contains no GenBank files: {expected}")
        self._record(
            "mibig",
            path=str(expected),
            version=version,
            files=len(files),
            sha256=self._tree_sha256(expected, files),
        )
        self._complete_phase("mibig", "MiBIG GenBank cache")

    def _nplinker_environment_ready(
        self, image: str, venv: Path, marker: Path, version: str
    ) -> bool:
        marker_value = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
        if marker_value != version:
            return False
        data_volume = (
            self.env.get("NPLINKER_DOCKER_DATA_VOLUME", "").strip()
            or self.env.get("DOCKER_DATA_VOLUME", "").strip()
        )
        args = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--entrypoint",
            "",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
        ]
        if data_volume:
            args.extend(["-v", f"{data_volume}:/data:ro"])
        else:
            args.extend(["-v", f"{self.software_root}:{self.software_root}:ro"])
        probe = (
            "import importlib.metadata as m,sys; "
            "raise SystemExit(0 if m.version('nplinker') == sys.argv[1] else 1)"
        )
        args.extend([image, str(venv / "bin" / "python"), "-c", probe, version])
        return self._run(args).returncode == 0

    def _nplinker_environment(self, mutate: bool) -> None:
        version = self.env.get("NPLINKER_VERSION", NPLINKER_VERSION)
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+", version):
            raise PreparationError("NPLINKER_VERSION contains unsupported characters")
        venv = _env_path(
            self.env,
            "NPLINKER_VENV_DIR",
            self.software_root / "nplinker" / "venv",
        )
        marker = venv / ".clusterweave-nplinker-version"
        image = next(
            spec.reference
            for spec in local_image_specs(self.env, self.root)
            if spec.key == "nplinker_image"
        )
        self._phase(
            "nplinker_environment",
            "NPLinker environment",
            "Preparing" if mutate else "Checking",
        )
        ready = self._nplinker_environment_ready(image, venv, marker, version)
        if not ready:
            if not mutate:
                raise PreparationError(
                    f"NPLinker {version} environment is not prepared: {venv}"
                )
            venv.parent.mkdir(parents=True, exist_ok=True)
            data_volume = (
                self.env.get("NPLINKER_DOCKER_DATA_VOLUME", "").strip()
                or self.env.get("DOCKER_DATA_VOLUME", "").strip()
            )
            args = ["docker", "run", "--rm", "--entrypoint", ""]
            if data_volume:
                args.extend(["-v", f"{data_volume}:/data"])
            else:
                args.extend(["-v", f"{self.software_root}:{self.software_root}"])
            quoted_venv = shlex.quote(str(venv))
            quoted_version = shlex.quote(version)
            script = (
                "set -eu; "
                f"python -m venv {quoted_venv}; "
                f"{quoted_venv}/bin/python -m pip install --cache-dir "
                f"{shlex.quote(str(venv.parent / 'pip_cache'))} -U pip setuptools wheel; "
                f"{quoted_venv}/bin/python -m pip install --cache-dir "
                f"{shlex.quote(str(venv.parent / 'pip_cache'))} nplinker=={quoted_version}; "
                f"printf '%s\\n' {quoted_version} > "
                f"{shlex.quote(str(marker))}"
            )
            args.extend([image, "sh", "-lc", script])
            self._run_required(args, label="NPLinker environment preparation")
            self._changed = True
            if not self._nplinker_environment_ready(image, venv, marker, version):
                raise PreparationError(
                    f"NPLinker environment preparation is incomplete: {venv}"
                )
        self._record(
            "nplinker_environment",
            path=str(venv),
            version=version,
        )
        self._complete_phase("nplinker_environment", "NPLinker environment")

    def _startup_asset_enabled(self, key: str) -> bool:
        flags = {
            "ncbi_cli": ("AUTO_INSTALL_NCBI_CLI", True),
            "clinker_image": ("PREPULL_CLINKER_IMAGE", True),
            "bigscape_image": ("PREPULL_BIGSCAPE_IMAGE", True),
            "funbgcex_image": ("PREPULL_FUNBGCEX_IMAGE", True),
        }
        if key == "funbgcex_image" and not self._truthy(
            self.env.get("AUTO_BUILD_FUNBGCEX_DOCKER", "1")
        ):
            return False
        name, default = flags[key]
        value = self.env.get(name)
        return default if value is None or value == "" else self._truthy(value)

    def _record_startup_skip(
        self, key: str, detail: str, substep: str
    ) -> None:
        self._record(key, skipped=True, detail=detail)
        self.status.update(key, 100, detail, substep)

    def _external_assets(self, scope: str) -> None:
        executor = self.env.get("CLUSTERWEAVE_EXECUTOR", "local").strip().lower()
        if executor == "slurm":
            missing = [
                command
                for command in ("sbatch", "squeue", "sacct", "scancel")
                if not self.executor.which(command)
            ]
            if missing:
                raise PreparationError(
                    "Slurm preparation check missing: " + ", ".join(missing)
                )
            self._record("slurm", commands=["sbatch", "squeue", "sacct", "scancel"])
        engine = self.env.get("ENGINE", "").strip().lower()
        if engine not in {"apptainer", "singularity"}:
            raise PreparationError(
                "external preparation requires ENGINE=apptainer or ENGINE=singularity"
            )
        self._require_command(engine)
        self._check_worker_components()
        self._ncbi_cli(False)
        if scope == "startup":
            return
        defaults = {
            "ANTISMASH_SIF": self.software_root / "antismash" / "antismash_8.0.4.sif",
            "FUNBGCEX_SIF": self.software_root / "funbgcex" / "funbgcex_bundle.sif",
            "FUNANNOTATE_SIF": self.software_root / "funannotate" / "funannotate_v1.8.17.sif",
            "BIGSCAPE_SIF_PATH": self.software_root / "big_scape" / "bigscape_2.0.0-beta.6.sif",
            "CLINKER_SIF_PATH": self.software_root / "clinker" / "clinker-py_0.0.32--pyhdfd78af_0.sif",
            "NPLINKER_SIF_PATH": self.software_root / "nplinker" / "nplinker_python3.11.sif",
        }
        for name, default in defaults.items():
            path = _env_path(self.env, name, default)
            if not path.is_file() or path.stat().st_size == 0:
                raise PreparationError(f"external runtime is not prepared: {name}={path}")
            self._record(name.lower(), path=str(path), sha256=sha256_file(path))

    def _load_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.is_file():
            return {}
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PreparationError(
                f"runtime preparation manifest is unreadable: {self.manifest_path}"
            ) from exc
        if payload.get("schema") != SCHEMA:
            raise PreparationError(
                f"unsupported runtime preparation manifest: {self.manifest_path}"
            )
        return payload

    def _validate_manifest_scope(
        self, existing: Mapping[str, Any], scope: str
    ) -> None:
        if not existing:
            raise PreparationError(
                f"preparation manifest is unavailable: {self.manifest_path}"
            )
        if existing.get("profile") != "local-docker":
            raise PreparationError("preparation manifest profile is not local-docker")
        scopes = existing.get("scopes")
        if not isinstance(scopes, list) or scope not in scopes:
            raise PreparationError(
                f"preparation manifest does not cover requested scope: {scope}"
            )

    @staticmethod
    def _identity_fields(asset: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: asset[key]
            for key in ("reference", "identity", "sha256", "version")
            if key in asset
        }

    def _verify_manifest_identities(self, existing: Mapping[str, Any]) -> None:
        recorded = existing.get("assets", {})
        if not isinstance(recorded, dict):
            raise PreparationError("runtime preparation manifest assets are malformed")
        for key, current in self._assets.items():
            prior = recorded.get(key)
            if not isinstance(prior, dict):
                continue
            prior_identity = self._identity_fields(prior)
            current_identity = self._identity_fields(current)
            if prior_identity and current_identity and prior_identity != current_identity:
                raise PreparationError(
                    f"prepared asset identity changed for {key}; explicit review is required"
                )

    def _write_manifest(self, scope: str, existing: Mapping[str, Any]) -> None:
        old_assets = existing.get("assets", {}) if isinstance(existing, dict) else {}
        merged_assets = dict(old_assets) if isinstance(old_assets, dict) else {}
        merged_assets.update(self._assets)
        scopes = set(existing.get("scopes", [])) if isinstance(existing, dict) else set()
        scopes.add("startup")
        if scope == "all":
            scopes.add("all")
        payload = {
            "schema": SCHEMA,
            "profile": self.profile,
            "scopes": sorted(scopes),
            "assets": merged_assets,
        }
        encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if self.manifest_path.is_file() and self.manifest_path.read_bytes() == encoded:
            return
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=self.manifest_path.parent,
            prefix=f".{self.manifest_path.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temporary, self.manifest_path)
        finally:
            temporary.unlink(missing_ok=True)
        self._changed = True

    def _execute(self, *, mutate: bool, scope: str, keep_going: bool) -> PreparationReport:
        if scope not in {"startup", "all"}:
            raise PreparationError(f"unsupported preparation scope: {scope}")
        self._assets = {}
        self._changed = False
        report = PreparationReport(profile=self.profile, scope=scope)
        if scope == "startup":
            self.status.update(
                "prepare",
                100,
                "Preparing worker bootstrap",
                "Worker bootstrap plan created",
            )
        self._validate_profile()
        existing = self._load_manifest() if self.profile == "local-docker" else {}

        def run_step(label: str, operation: Any) -> None:
            try:
                operation()
            except PreparationError as exc:
                report.ready = False
                report.errors.append(f"{label}: {exc}")
                if self._active_status is not None:
                    phase, detail, _ = self._active_status
                    self.status.update(
                        phase,
                        100,
                        f"{detail} failed; continuing",
                        "Continuing with partial bootstrap",
                    )
                    self._active_status = None
                if not keep_going:
                    raise

        if self.profile == "local-docker" and not mutate:
            run_step(
                "preparation manifest",
                lambda: self._validate_manifest_scope(existing, scope),
            )

        if self.profile == "external":
            run_step("external profile", lambda: self._external_assets(scope))
        else:
            run_step("worker components", self._check_worker_components)
            run_step("antiSMASH databases", lambda: self._antismash_database(mutate))
            run_step("Pfam", lambda: self._pfam(mutate))
            if scope == "all" or self._startup_asset_enabled("ncbi_cli"):
                run_step("NCBI CLI", lambda: self._ncbi_cli(mutate))
            else:
                self._record_startup_skip(
                    "ncbi_cli",
                    "Skipping NCBI Datasets CLI install",
                    "Auto-install disabled",
                )
            for spec in local_image_specs(self.env, self.root):
                if scope == "startup" and spec.scope != "startup":
                    continue
                if scope == "startup" and not self._startup_asset_enabled(spec.key):
                    skip_messages = {
                        "clinker_image": (
                            "Skipping clinker image pre-pull",
                            "Pre-pull disabled",
                        ),
                        "bigscape_image": (
                            "Skipping BiG-SCAPE image pre-pull",
                            "Pre-pull disabled",
                        ),
                        "funbgcex_image": (
                            "Skipping FunBGCeX image build",
                            "Pre-build disabled",
                        ),
                    }
                    detail, substep = skip_messages[spec.key]
                    self._record_startup_skip(spec.key, detail, substep)
                    continue
                run_step(spec.key, lambda spec=spec: self._prepare_image(spec, mutate))
            if scope == "all":
                run_step("FastTree", lambda: self._fasttree(mutate))
                run_step("MiBIG", lambda: self._mibig(mutate))
                run_step(
                    "NPLinker environment",
                    lambda: self._nplinker_environment(mutate),
                )
            if report.ready:
                run_step(
                    "manifest identities",
                    lambda: self._verify_manifest_identities(existing),
                )
                if mutate and report.ready:
                    self._write_manifest(scope, existing)
        report.assets = dict(self._assets)
        report.changed = self._changed
        return report

    def prepare(self, *, scope: str = "all", keep_going: bool = False) -> PreparationReport:
        return self._execute(mutate=self.profile == "local-docker", scope=scope, keep_going=keep_going)

    def check(self, *, scope: str = "all", keep_going: bool = False) -> PreparationReport:
        return self._execute(mutate=False, scope=scope, keep_going=keep_going)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or non-mutatingly check ClusterWeave runtime assets."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "check"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument(
            "--profile",
            choices=("local-docker", "external"),
            help="Override profile inference from CLUSTERWEAVE_RUNTIME_MODE.",
        )
        subparser.add_argument(
            "--scope",
            choices=("startup", "all"),
            default="all",
            help="Prepare/check the startup subset or every supported runtime asset.",
        )
        subparser.add_argument(
            "--keep-going",
            action="store_true",
            help="Check remaining assets after a failure.",
        )
        subparser.add_argument(
            "--manifest",
            type=Path,
            help="Override the local preparation manifest path.",
        )
        subparser.add_argument(
            "--status-file",
            type=Path,
            help="Publish worker bootstrap progress to this JSON file.",
        )
        subparser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        preparer = RuntimePreparer(
            profile=args.profile,
            manifest_path=args.manifest,
            status_path=args.status_file,
        )
        operation = preparer.prepare if args.command == "prepare" else preparer.check
        report = operation(scope=args.scope, keep_going=args.keep_going)
        if args.status_file is not None and args.scope == "startup":
            preparer.status.update(
                "starting_worker",
                100,
                "Starting worker process",
                "Handing off to worker loop",
            )
    except PreparationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        for key, asset in report.assets.items():
            identity = asset.get("identity") or asset.get("sha256") or asset.get("version") or "ready"
            print(f"RUNTIME_ASSET {key} ready {identity}")
        for error in report.errors:
            print(f"RUNTIME_ASSET error {error}", file=sys.stderr)
        print(
            f"RUNTIME_PREPARATION profile={report.profile} scope={report.scope} "
            f"ready={str(report.ready).lower()} changed={str(report.changed).lower()}"
        )
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
