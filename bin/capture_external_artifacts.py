#!/usr/bin/env python3
"""Write a run-local manifest of external artifacts used by ClusterWeave."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


FIELDNAMES = [
    "stage",
    "artifact",
    "source_uri",
    "local_path",
    "version_or_tag",
    "tool_versions",
    "resolved_digest",
    "sha256",
    "size_bytes",
    "captured_at",
]

DEFAULT_FUNANNOTATE_BASE_IMAGE_URI = "docker://nextgenusfs/funannotate:v1.8.17"
DEFAULT_FUNANNOTATE_DOCKER_IMAGE_URI = "docker://clusterweave-funannotate:v1.8.17-busco"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def env(name: str, default: str = "") -> str:
    return clean(os.environ.get(name, default))


def digest_from_source(source_uri: str) -> str:
    text = clean(source_uri)
    if "@sha256:" in text:
        return "sha256:" + text.split("@sha256:", 1)[1]
    return ""


def tag_from_source(source_uri: str) -> str:
    text = clean(source_uri)
    if not text:
        return ""
    text = text.split("@", 1)[0]
    if text.startswith("docker://"):
        image = text.removeprefix("docker://")
        last_segment = image.rsplit("/", 1)[-1]
        if ":" in last_segment:
            return last_segment.rsplit(":", 1)[1]
        return "latest"
    name = Path(text).name
    return name or text


def docker_image_from_uri(source_uri: str) -> str:
    text = clean(source_uri)
    if not text:
        return ""
    text = text.removeprefix("docker://")
    return text.split("@", 1)[0]


def docker_image_identifier(image_ref: str) -> str:
    image_ref = clean(image_ref)
    if not image_ref or shutil.which("docker") is None:
        return ""
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", image_ref],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    try:
        metadata = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return ""
    if not metadata:
        return ""
    repo_digests = metadata[0].get("RepoDigests") or []
    for repo_digest in repo_digests:
        digest = digest_from_source(repo_digest)
        if digest:
            return digest
    return clean(metadata[0].get("Id", ""))


def funannotate_uses_docker_runtime() -> bool:
    engine = env("ENGINE").lower()
    if engine == "docker":
        return True
    if engine in {"singularity", "apptainer"}:
        return False
    return "docker" in env("CLUSTERWEAVE_RUNTIME_MODE").lower()


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def sha256_directory(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        rel = child.relative_to(path).as_posix()
        child_sha, child_size = sha256_file(child)
        digest.update(rel.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(child_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(child_sha.encode("ascii"))
        digest.update(b"\0")
        size += child_size
    return digest.hexdigest(), size


def hash_path(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "", ""
    if path.is_file():
        digest, size = sha256_file(path)
        return digest, str(size)
    if path.is_dir():
        digest, size = sha256_directory(path)
        return digest, str(size)
    return "", ""


def add_row(
    rows: list[dict[str, str]],
    *,
    stage: str,
    artifact: str,
    source_uri: str,
    local_path: Path,
    version_or_tag: str = "",
    tool_versions: str = "",
    resolved_digest: str = "",
    captured_at: str,
) -> None:
    source_uri = clean(source_uri)
    version_or_tag = clean(version_or_tag) or tag_from_source(source_uri)
    sha256, size_bytes = hash_path(local_path)
    rows.append(
        {
            "stage": stage,
            "artifact": artifact,
            "source_uri": source_uri,
            "local_path": str(local_path),
            "version_or_tag": version_or_tag,
            "tool_versions": clean(tool_versions)[:800],
            "resolved_digest": clean(resolved_digest) or digest_from_source(source_uri),
            "sha256": sha256,
            "size_bytes": size_bytes,
            "captured_at": captured_at,
        }
    )


def add_virtual_row(
    rows: list[dict[str, str]],
    *,
    stage: str,
    artifact: str,
    source_uri: str,
    local_path: str = "",
    version_or_tag: str = "",
    resolved_digest: str = "",
    tool_versions: str = "",
    captured_at: str,
) -> None:
    source_uri = clean(source_uri)
    rows.append(
        {
            "stage": stage,
            "artifact": artifact,
            "source_uri": source_uri,
            "local_path": clean(local_path),
            "version_or_tag": clean(version_or_tag) or tag_from_source(source_uri),
            "tool_versions": clean(tool_versions)[:800],
            "resolved_digest": clean(resolved_digest) or digest_from_source(source_uri),
            "sha256": "",
            "size_bytes": "",
            "captured_at": captured_at,
        }
    )


def add_funannotate_runtime_row(
    rows: list[dict[str, str]],
    *,
    software_root: Path,
    captured_at: str,
) -> None:
    if funannotate_uses_docker_runtime():
        source_uri = env("FUNANNOTATE_IMAGE_URI", DEFAULT_FUNANNOTATE_DOCKER_IMAGE_URI)
        image_ref = docker_image_from_uri(source_uri)
        add_virtual_row(
            rows,
            stage="stage1_annotation_detection",
            artifact="funannotate_docker_image",
            source_uri=source_uri,
            local_path=f"docker-image://{image_ref}" if image_ref else "",
            resolved_digest=digest_from_source(source_uri) or docker_image_identifier(image_ref),
            captured_at=captured_at,
        )
        return

    funannotate_sif = Path(
        env("FUNANNOTATE_SIF", str(software_root / "funannotate" / "funannotate_v1.8.17.sif"))
    )
    add_row(
        rows,
        stage="stage1_annotation_detection",
        artifact="funannotate_sif",
        source_uri=env(
            "FUNANNOTATE_SIF_SOURCE",
            env("FUNANNOTATE_BASE_IMAGE_URI", DEFAULT_FUNANNOTATE_BASE_IMAGE_URI),
        ),
        local_path=funannotate_sif,
        captured_at=captured_at,
    )


def add_phylogeny_runtime_row(
    rows: list[dict[str, str]],
    *,
    results_root: Path,
    captured_at: str,
) -> None:
    manifest_path = Path(
        env(
            "PHYLOGENY_MANIFEST_JSON",
            str(results_root / "phylogeny" / "phylogeny_run_manifest.json"),
        )
    )
    if not manifest_path.is_file():
        return
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    runtime = clean(payload.get("runtime")).lower()
    runtime_identity = clean(payload.get("runtime_identity"))[:300]
    tool_versions = clean(payload.get("tool_versions"))[:800]
    if runtime == "docker":
        image_ref = env(
            "PHYLOGENY_DOCKER_IMAGE", "clusterweave-phylogeny:1.0.0"
        ).removeprefix("docker://")
        if not runtime_identity:
            runtime_identity = docker_image_identifier(image_ref)
        if not runtime_identity:
            return
        add_virtual_row(
            rows,
            stage="optional_sequence_phylogeny",
            artifact="phylogeny_docker_image",
            source_uri=f"docker://{image_ref}",
            local_path=f"docker-image://{image_ref}",
            resolved_digest=runtime_identity,
            tool_versions=tool_versions,
            captured_at=captured_at,
        )
    elif runtime in {"apptainer", "singularity", "sif"}:
        sif_path = Path(
            env(
                "PHYLOGENY_SIF_PATH",
                str(
                    Path(__file__).resolve().parents[1]
                    / "software"
                    / "phylogeny"
                    / "clusterweave_phylogeny_1.0.0.sif"
                ),
            )
        )
        if not sif_path.is_file():
            return
        add_row(
            rows,
            stage="optional_sequence_phylogeny",
            artifact="phylogeny_sif",
            source_uri=env(
                "PHYLOGENY_SIF_SOURCE",
                "local-pinned-sif:clusterweave_phylogeny_1.0.0.sif",
            ),
            local_path=sif_path,
            resolved_digest=runtime_identity,
            tool_versions=tool_versions,
            captured_at=captured_at,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture checksums and source hints for external ClusterWeave artifacts."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="ClusterWeave repository root.",
    )
    parser.add_argument(
        "--project-name",
        default=env("PROJECT_NAME", "clusterweave"),
        help="Project name used under data/results.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output TSV. Defaults to data/results/<project>/reproducibility/external_artifacts.tsv.",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    data_root = Path(env("DATA_ROOT", str(project_root / "data")))
    software_root = Path(env("SOFTWARE_ROOT", str(project_root / "software")))
    results_root = Path(env("RESULTS_ROOT", str(data_root / "results" / args.project_name)))
    output_path = args.output or (results_root / "reproducibility" / "external_artifacts.tsv")
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    antismash_sif = Path(env("ANTISMASH_SIF", str(software_root / "antismash" / "antismash_standalone.sif")))
    funbgcex_sif = Path(env("FUNBGCEX_SIF", str(software_root / "funbgcex" / "funbgcex_bundle.sif")))
    braker_sif = Path(env("BRAKER_SIF", str(software_root / "braker" / "braker3.sif")))
    bigscape_softdir = Path(env("BIGSCAPE_SOFTDIR", str(software_root / "big_scape")))
    bigscape_sif = Path(
        env("BIGSCAPE_SIF_PATH", env("SIF_PATH", str(bigscape_softdir / "bigscape_2.0.0-beta.6.sif")))
    )
    res_dir = Path(env("RES_DIR", str(bigscape_softdir / "resources")))
    pfam_dir = Path(env("PFAM_DIR", str(res_dir / "pfam")))
    pfam_hmm = Path(env("PFAM_HMM", str(pfam_dir / "Pfam-A.hmm")))
    local_bin = Path(env("LOCAL_BIN", str(bigscape_softdir / "bin")))
    fasttree_host = Path(env("FASTTREE_HOST", str(local_bin / "fasttree")))
    mibig_version = env("MIBIG_VERSION_DEFAULT", "4.0")
    mibig_cache = Path(env("MIBIG_CACHE", str(res_dir / "mibig_cache")))
    clinker_tag = env("CLINKER_CONTAINER_TAG", "0.0.32--pyhdfd78af_0")
    clinker_sif = Path(env("CLINKER_SIF_PATH", str(software_root / "clinker" / f"clinker-py_{clinker_tag}.sif")))
    nplinker_softdir = Path(env("NPLINKER_SOFTWARE_ROOT", str(software_root / "nplinker")))
    nplinker_sif = Path(env("NPLINKER_SIF_PATH", str(nplinker_softdir / "nplinker_python3.11.sif")))

    rows: list[dict[str, str]] = []
    add_row(
        rows,
        stage="stage1_annotation_detection",
        artifact="antismash_sif",
        source_uri=env("ANTISMASH_IMAGE_URI", "docker://antismash/standalone:8.0.4"),
        local_path=antismash_sif,
        captured_at=captured_at,
    )
    add_row(
        rows,
        stage="stage1_annotation_detection",
        artifact="funbgcex_sif",
        source_uri=env("FUNBGCEX_IMAGE_URI", "built_from_repo_recipe:software/funbgcex/Singularity.def"),
        local_path=funbgcex_sif,
        version_or_tag=env("FUNBGCEX_VERSION", "1.0.1"),
        captured_at=captured_at,
    )
    add_funannotate_runtime_row(rows, software_root=software_root, captured_at=captured_at)
    if braker_sif.exists() or env("BRAKER3_ENABLED", "0") == "1":
        add_row(
            rows,
            stage="stage1_annotation_detection",
            artifact="braker3_sif",
            source_uri=env("BRAKER_IMAGE_URI", "docker://teambraker/braker3:v3.0.7.6@sha256:5f8b3c508a9fe1bbc2e9a74dcc013eeed82f91dd5945adca7823514d9c8aecf8"),
            local_path=braker_sif,
            captured_at=captured_at,
        )

    mibig_url = env("MIBIG_GBK_URL") or f"{env('MIBIG_URL_BASE', 'https://dl.secondarymetabolites.org/mibig')}/mibig_gbk_{mibig_version}.tar.gz"
    for artifact in [
        (
            "stage2_bigscape",
            "bigscape_sif",
            env("BIGSCAPE_SIF_SOURCE", env("SIF_SOURCE", "docker://ghcr.io/medema-group/big-scape:2.0.0-beta.6")),
            bigscape_sif,
            "",
        ),
        (
            "stage2_bigscape",
            "pfam_hmm",
            env("PFAM_URL", "https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release/Pfam-A.hmm.gz"),
            pfam_hmm,
            env("PFAM_VERSION", ""),
        ),
        (
            "stage2_bigscape",
            "fasttree_binary",
            env("FASTTREE_URL", "https://raw.githubusercontent.com/morgannprice/fasttree/29c5e62fbcd93230ee325f9c6a17b81f00e3c72a/FastTree"),
            fasttree_host,
            env("FASTTREE_VERSION", "2.2.0"),
        ),
        ("stage2_bigscape", "mibig_cache", mibig_url, mibig_cache, mibig_version),
        (
            "stage4_clinker",
            "clinker_sif",
            env("CLINKER_SIF_SOURCE", f"docker://quay.io/biocontainers/clinker-py:{clinker_tag}"),
            clinker_sif,
            clinker_tag,
        ),
    ]:
        stage, name, source_uri, local_path, version = artifact
        add_row(
            rows,
            stage=stage,
            artifact=name,
            source_uri=source_uri,
            local_path=local_path,
            version_or_tag=version,
            captured_at=captured_at,
        )

    if nplinker_sif.exists():
        add_row(
            rows,
            stage="optional_nplinker",
            artifact="nplinker_base_sif",
            source_uri=env("NPLINKER_SIF_SOURCE", "docker://python:3.11-slim"),
            local_path=nplinker_sif,
            captured_at=captured_at,
        )

    add_phylogeny_runtime_row(
        rows,
        results_root=results_root,
        captured_at=captured_at,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote external artifact manifest: {output_path}")


if __name__ == "__main__":
    main()
