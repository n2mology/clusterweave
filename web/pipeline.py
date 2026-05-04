#!/usr/bin/env python3
"""
ClusterWeave Web — pipeline orchestrator.

Runs antiSMASH → BiG-SCAPE → clinker directly (no Singularity required)
and exposes a Job model that the FastAPI layer can track.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Paths (overridable via environment)
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_DIR = Path(os.environ.get("ANTISMASH_DB_DIR", "/databases/antismash"))
PFAM_DIR = Path(os.environ.get("PFAM_DIR", "/databases/pfam"))
PFAM_HMM = PFAM_DIR / "Pfam-A.hmm"
CLUSTERWEAVE_BIN = Path(os.environ.get("CLUSTERWEAVE_BIN", "/clusterweave/bin"))
BIGSCAPE_USE_DOCKER_IMAGE = os.environ.get("BIGSCAPE_USE_DOCKER_IMAGE", "1") == "1"
BIGSCAPE_DOCKER_IMAGE = os.environ.get(
    "BIGSCAPE_DOCKER_IMAGE", "ghcr.io/medema-group/big-scape:2.0.0-beta.6"
)
BIGSCAPE_DOCKER_DATA_VOLUME = os.environ.get("BIGSCAPE_DOCKER_DATA_VOLUME", "")
BIGSCAPE_DOCKER_PFAM_VOLUME = os.environ.get("BIGSCAPE_DOCKER_PFAM_VOLUME", "")
CLINKER_USE_DOCKER_IMAGE = os.environ.get("CLINKER_USE_DOCKER_IMAGE", "1") == "1"
CLINKER_DOCKER_IMAGE = os.environ.get(
    "CLINKER_DOCKER_IMAGE", "quay.io/biocontainers/clinker-py:0.0.32--pyhdfd78af_0"
)
CLINKER_DOCKER_DATA_VOLUME = os.environ.get("CLINKER_DOCKER_DATA_VOLUME", "")


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------
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
    on_change: Optional[Callable[[], None]] = field(default=None, repr=False, compare=False)

    def add_log(self, line: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {line}"
        self.log_lines.append(entry)
        self.updated_at = datetime.now().isoformat()
        if self.on_change:
            self.on_change()

    def set_stage(self, stage: str) -> None:
        self.stage = stage
        self.add_log(f"=== Stage: {stage} ===")

    def to_dict(self) -> dict:
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
        }


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------
async def _stream_cmd(
    cmd: list[str],
    cwd: Optional[Path],
    job: Job,
    env: Optional[dict] = None,
) -> int:
    """Run *cmd* asynchronously, streaming stdout/stderr into job.log_lines."""
    job.add_log(f"$ {' '.join(str(c) for c in cmd)}")
    proc_env = {**os.environ, **(env or {})}
    try:
        proc = await asyncio.create_subprocess_exec(
            *[str(c) for c in cmd],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd) if cwd else None,
            env=proc_env,
        )
        assert proc.stdout is not None
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                job.add_log(line)
        rc = await proc.wait()
    except FileNotFoundError as exc:
        job.add_log(f"ERROR: command not found — {exc}")
        return 127
    return rc


def _collect_region_gbks(antismash_root: Path) -> list[Path]:
    """Return all *.region*.gbk files produced by antiSMASH."""
    return sorted(antismash_root.rglob("*.region*.gbk"))


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------
async def _run_antismash(
    input_gbk: Path,
    output_root: Path,
    cpus: int,
    job: Job,
    genefinding_override: str = "auto",
) -> Path:
    """Run antiSMASH on a single annotated GenBank file."""
    out_dir = output_root / input_gbk.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # Detect how to call antismash
    antismash_cmd: list[str]
    if shutil.which("antismash"):
        antismash_cmd = ["antismash"]
    else:
        antismash_cmd = [sys.executable, "-m", "antismash"]

    if genefinding_override in {"none", "prodigal"}:
        genefinding = genefinding_override
    else:
        genefinding = "none" if input_gbk.suffix.lower() in {".gbk", ".gb", ".gbff"} else "prodigal"

    cmd = [
        *antismash_cmd,
        "--cpus", str(cpus),
        "--output-dir", str(out_dir),
        "--genefinding-tool", genefinding,
        "--databases", str(DB_DIR),
        "--minimal",                 # speed up: skip HTML report generation
        "--enable-html",             # still generate JSON for downstream processing
        str(input_gbk),
    ]
    # Remove --enable-html if antismash doesn't support it; use --enable-html only if needed.
    # A safer minimal run:
    cmd = [
        *antismash_cmd,
        "--cpus", str(cpus),
        "--output-dir", str(out_dir),
        "--genefinding-tool", genefinding,
        "--databases", str(DB_DIR),
        str(input_gbk),
    ]
    rc = await _stream_cmd(cmd, cwd=None, job=job)
    if rc != 0:
        raise RuntimeError(f"antiSMASH failed (exit {rc}) for {input_gbk.name}")
    return out_dir


async def _run_bigscape(
    antismash_root: Path,
    output_dir: Path,
    cpus: int,
    job: Job,
    mix_mode: bool = True,
    use_docker_image: bool = BIGSCAPE_USE_DOCKER_IMAGE,
    docker_image: str = BIGSCAPE_DOCKER_IMAGE,
    docker_data_volume: str = BIGSCAPE_DOCKER_DATA_VOLUME,
    docker_pfam_volume: str = BIGSCAPE_DOCKER_PFAM_VOLUME,
) -> Path:
    """Run BiG-SCAPE v2 on antiSMASH region GenBank files."""
    if not PFAM_HMM.exists():
        job.add_log(f"WARN: Pfam-A.hmm not found at {PFAM_HMM}. BiG-SCAPE may fail.")

    output_dir.mkdir(parents=True, exist_ok=True)

    bigscape_cmd: list[str]
    if shutil.which("bigscape"):
        bigscape_cmd = ["bigscape"]
    elif shutil.which("bigscape.py"):
        bigscape_cmd = ["bigscape.py"]
    else:
        if use_docker_image:
            ok = await _run_bigscape_in_docker(
                antismash_root,
                output_dir,
                cpus,
                job,
                mix_mode,
                docker_image,
                docker_data_volume,
                docker_pfam_volume,
            )
            if ok:
                return output_dir
        job.add_log("WARN: BiG-SCAPE command not found in worker runtime. Skipping family clustering stage.")
        return output_dir

    cmd = [
        *bigscape_cmd,
        "--input-dir", str(antismash_root),
        "--output-dir", str(output_dir),
        "--pfam-path", str(PFAM_HMM),
        "--cores", str(cpus),
    ]
    if mix_mode:
        cmd.append("--mix")
    rc = await _stream_cmd(cmd, cwd=None, job=job)
    if rc != 0:
        raise RuntimeError(f"BiG-SCAPE failed (exit {rc})")
    return output_dir


async def _run_bigscape_in_docker(
    antismash_root: Path,
    output_dir: Path,
    cpus: int,
    job: Job,
    mix_mode: bool,
    docker_image: str,
    docker_data_volume: str,
    docker_pfam_volume: str,
) -> bool:
    if not shutil.which("docker"):
        job.add_log("WARN: docker CLI not available in worker; cannot use BiG-SCAPE container image.")
        return False
    if not docker_data_volume or not docker_pfam_volume:
        job.add_log("WARN: BIGSCAPE_DOCKER_DATA_VOLUME or BIGSCAPE_DOCKER_PFAM_VOLUME not set; cannot run BiG-SCAPE container image.")
        return False

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{docker_data_volume}:/data",
        "-v",
        f"{docker_pfam_volume}:/databases/pfam",
        docker_image,
        "cluster",
        "-i",
        str(antismash_root),
        "-o",
        str(output_dir),
        "-p",
        str(PFAM_HMM),
        "-c",
        str(cpus),
    ]
    if mix_mode:
        cmd.append("--legacy-weights")
    rc = await _stream_cmd(cmd, cwd=None, job=job)
    if rc == 0:
        job.add_log(f"Used BiG-SCAPE container image: {docker_image}")
        return True
    job.add_log(f"WARN: BiG-SCAPE container run failed (exit {rc}).")
    return False


async def _run_clinker(
    region_gbks: list[Path],
    output_html: Path,
    job: Job,
    use_docker_image: bool = CLINKER_USE_DOCKER_IMAGE,
    docker_image: str = CLINKER_DOCKER_IMAGE,
    docker_data_volume: str = CLINKER_DOCKER_DATA_VOLUME,
    max_regions: int = 0,
) -> Path:
    """Run clinker on a collection of BGC region GenBank files."""
    if not region_gbks:
        job.add_log("No region GBK files found — skipping clinker.")
        return output_html

    output_html.parent.mkdir(parents=True, exist_ok=True)
    selected_regions = region_gbks
    if max_regions > 0 and len(region_gbks) > max_regions:
        selected_regions = region_gbks[:max_regions]
        job.add_log(f"Limiting clinker input regions to first {max_regions} for this run.")

    clinker_cmd: list[str]
    if shutil.which("clinker"):
        clinker_cmd = ["clinker"]
    elif shutil.which("clinker.py"):
        clinker_cmd = ["clinker.py"]
    else:
        if use_docker_image:
            ok = await _run_clinker_in_docker(selected_regions, output_html, job, docker_image, docker_data_volume)
            if ok:
                return output_html
        _write_clinker_fallback_html(output_html, selected_regions)
        job.add_log("WARN: clinker command/module not found. Generated fallback HTML report instead.")
        return output_html

    cmd = [
        *clinker_cmd,
        *[str(g) for g in selected_regions],
        "--plot", str(output_html),
        "--no-input-limit",
    ]
    rc = await _stream_cmd(cmd, cwd=None, job=job)
    if rc != 0:
        _write_clinker_fallback_html(output_html, selected_regions)
        job.add_log(f"WARN: clinker failed (exit {rc}). Generated fallback HTML report instead.")
    return output_html


async def _run_clinker_in_docker(
    region_gbks: list[Path],
    output_html: Path,
    job: Job,
    docker_image: str,
    docker_data_volume: str,
) -> bool:
    """Run clinker from a preinstalled container image via Docker socket."""
    if not shutil.which("docker"):
        job.add_log("WARN: docker CLI not available in worker; cannot use clinker container image.")
        return False
    if not docker_data_volume:
        job.add_log("WARN: CLINKER_DOCKER_DATA_VOLUME not set; cannot run clinker container image.")
        return False

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{docker_data_volume}:/data",
        docker_image,
        "clinker",
        *[str(g) for g in region_gbks],
        "--plot",
        str(output_html),
        "--no-input-limit",
    ]
    rc = await _stream_cmd(cmd, cwd=None, job=job)
    if rc == 0:
        job.add_log(f"Used clinker container image: {docker_image}")
        return True
    job.add_log(f"WARN: clinker container run failed (exit {rc}).")
    return False


def _write_clinker_fallback_html(output_html: Path, region_gbks: list[Path]) -> None:
    """Create a minimal HTML summary when clinker is unavailable."""
    output_html.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"<li><code>{p.name}</code> <span>({p})</span></li>" for p in region_gbks
    )
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>ClusterWeave Fallback Report</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1d2330; }}
    .card {{ max-width: 960px; border: 1px solid #d9deea; border-radius: 10px; padding: 1.25rem 1.5rem; }}
    h1 {{ margin-top: 0; font-size: 1.35rem; }}
    .muted {{ color: #5f6b85; }}
    code {{ background: #f5f7fb; padding: 0.15rem 0.35rem; border-radius: 4px; }}
    li {{ margin: 0.35rem 0; }}
    span {{ color: #4b5874; font-size: 0.92rem; }}
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>clinker Visualization Unavailable</h1>
    <p class=\"muted\">ClusterWeave detected BGC regions but could not run clinker in this worker runtime. This fallback report lists the region GenBank files that can be downloaded and visualized externally.</p>
    <p><strong>Detected regions:</strong> {len(region_gbks)}</p>
    <ul>
      {rows}
    </ul>
  </div>
</body>
</html>
"""
    output_html.write_text(html, encoding="utf-8")


async def _run_crosswalk(
    antismash_root: Path,
    bigscape_out: Path,
    output_tsv: Path,
    job: Job,
) -> Optional[Path]:
    """Build the BGC→GCF crosswalk table using ClusterWeave's bin script."""
    script = CLUSTERWEAVE_BIN / "build_bgc_gcf_crosswalk.py"
    if not script.exists():
        job.add_log(f"WARN: {script} not found — skipping crosswalk.")
        return None

    # Find bigscape clustering TSV and record_annotations TSV
    clustering_tsvs = list(bigscape_out.rglob("*_clustering_c0.3.tsv"))
    record_ann_tsvs = list(bigscape_out.rglob("record_annotations.tsv"))

    if not clustering_tsvs:
        job.add_log("WARN: No BigSCAPE clustering TSV found — skipping crosswalk.")
        return None

    output_tsv.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(script),
        "--antismash-root", str(antismash_root),
        "--bigscape-root", str(bigscape_out),
        "--output", str(output_tsv),
    ]
    if record_ann_tsvs:
        cmd += ["--bigscape-record-annotations", str(record_ann_tsvs[0])]
    if clustering_tsvs:
        cmd += ["--bigscape-clustering", str(clustering_tsvs[0])]

    rc = await _stream_cmd(cmd, cwd=None, job=job)
    if rc != 0:
        job.add_log(f"WARN: crosswalk script returned exit {rc} — continuing.")
        return None
    return output_tsv


async def _postprocess_clinker_html(html_path: Path, job: Job) -> None:
    """Optionally post-process the clinker HTML with ClusterWeave's bin script."""
    script = CLUSTERWEAVE_BIN / "postprocess_clinker_html.py"
    if not script.exists() or not html_path.exists():
        return
    rc = await _stream_cmd(
        [sys.executable, str(script), str(html_path)],
        cwd=None,
        job=job,
    )
    if rc != 0:
        job.add_log("WARN: clinker HTML post-processing failed — using raw output.")


# ---------------------------------------------------------------------------
# Top-level pipeline entry point
# ---------------------------------------------------------------------------
async def run_pipeline(
    job: Job,
    input_files: list[Path],
    job_dir: Path,
    cpus: int = 4,
    settings: Optional[dict[str, Any]] = None,
    on_update: Optional[Callable[[], None]] = None,
) -> None:
    """
    Execute the full ClusterWeave pipeline for the given annotated GenBank files.

    Stages:
      1. antiSMASH  — BGC detection per genome
      2. BiG-SCAPE  — BGC family clustering
      3. crosswalk  — BGC→GCF summary table
      4. clinker    — synteny visualisation
    """
    def notify():
        if on_update:
            on_update()

    cfg = settings or {}

    def cfg_bool(key: str, default: bool) -> bool:
        value = cfg.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def cfg_int(key: str, default: int) -> int:
        value = cfg.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def cfg_str(key: str, default: str) -> str:
        value = cfg.get(key, default)
        return str(value) if value is not None else default

    try:
        job.status = JobStatus.RUNNING
        notify()

        antismash_root = job_dir / "antismash"
        bigscape_out = job_dir / "bigscape"
        summary_dir = job_dir / "summary"
        clinker_html = job_dir / "results" / "clinker_visualization.html"
        crosswalk_tsv = summary_dir / "bgc_gcf_crosswalk.tsv"

        antismash_root.mkdir(parents=True, exist_ok=True)
        summary_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "results").mkdir(parents=True, exist_ok=True)

        run_bigscape = cfg_bool("run_bigscape", True)
        run_crosswalk = cfg_bool("run_crosswalk", True)
        run_clinker = cfg_bool("run_clinker", True)
        bigscape_mix_mode = cfg_bool("bigscape_mix_mode", True)
        genefinding_mode = cfg_str("genefinding_mode", "auto")
        bigscape_use_docker_image = cfg_bool("bigscape_use_docker_image", BIGSCAPE_USE_DOCKER_IMAGE)
        bigscape_docker_image = cfg_str("bigscape_docker_image", BIGSCAPE_DOCKER_IMAGE)
        bigscape_docker_data_volume = cfg_str("bigscape_docker_data_volume", BIGSCAPE_DOCKER_DATA_VOLUME)
        bigscape_docker_pfam_volume = cfg_str("bigscape_docker_pfam_volume", BIGSCAPE_DOCKER_PFAM_VOLUME)
        clinker_use_docker_image = cfg_bool("clinker_use_docker_image", CLINKER_USE_DOCKER_IMAGE)
        clinker_docker_image = cfg_str("clinker_docker_image", CLINKER_DOCKER_IMAGE)
        clinker_docker_data_volume = cfg_str("clinker_docker_data_volume", CLINKER_DOCKER_DATA_VOLUME)
        clinker_max_regions = max(0, cfg_int("clinker_max_regions", 0))

        job.add_log(
            "Run settings: "
            f"run_bigscape={run_bigscape}, run_crosswalk={run_crosswalk}, run_clinker={run_clinker}, "
            f"genefinding_mode={genefinding_mode}, bigscape_use_docker_image={bigscape_use_docker_image}, clinker_use_docker_image={clinker_use_docker_image}"
        )

        # ------------------------------------------------------------------
        # Stage 1: antiSMASH
        # ------------------------------------------------------------------
        job.set_stage("antiSMASH BGC detection")
        notify()
        for gbk in input_files:
            job.add_log(f"Processing: {gbk.name}")
            notify()
            await _run_antismash(gbk, antismash_root, cpus, job, genefinding_mode)

        region_gbks = _collect_region_gbks(antismash_root)
        job.add_log(f"Found {len(region_gbks)} BGC region(s) across all genomes.")
        notify()

        if not region_gbks:
            job.add_log("No BGC regions detected — pipeline complete (no clusters found).")
            job.status = JobStatus.SUCCESS
            job.stage = "complete"
            _collect_result_files(job, job_dir)
            notify()
            return

        # ------------------------------------------------------------------
        # Stage 2: BiG-SCAPE
        # ------------------------------------------------------------------
        if run_bigscape:
            job.set_stage("BiG-SCAPE family clustering")
            notify()
            await _run_bigscape(
                antismash_root,
                bigscape_out,
                cpus,
                job,
                mix_mode=bigscape_mix_mode,
                use_docker_image=bigscape_use_docker_image,
                docker_image=bigscape_docker_image,
                docker_data_volume=bigscape_docker_data_volume,
                docker_pfam_volume=bigscape_docker_pfam_volume,
            )
            notify()
        else:
            job.add_log("Skipping BiG-SCAPE family clustering (disabled in run settings).")

        # ------------------------------------------------------------------
        # Stage 3: Crosswalk summary table
        # ------------------------------------------------------------------
        if run_crosswalk:
            job.set_stage("Building BGC–GCF crosswalk table")
            notify()
            await _run_crosswalk(antismash_root, bigscape_out, crosswalk_tsv, job)
            notify()
        else:
            job.add_log("Skipping BGC–GCF crosswalk table (disabled in run settings).")

        # ------------------------------------------------------------------
        # Stage 4: clinker visualisation
        # ------------------------------------------------------------------
        if run_clinker:
            job.set_stage("clinker synteny visualisation")
            notify()
            await _run_clinker(
                region_gbks,
                clinker_html,
                job,
                use_docker_image=clinker_use_docker_image,
                docker_image=clinker_docker_image,
                docker_data_volume=clinker_docker_data_volume,
                max_regions=clinker_max_regions,
            )
            await _postprocess_clinker_html(clinker_html, job)
            notify()
        else:
            job.add_log("Skipping clinker visualisation (disabled in run settings).")

        # ------------------------------------------------------------------
        # Finish
        # ------------------------------------------------------------------
        job.status = JobStatus.SUCCESS
        job.stage = "complete"
        _collect_result_files(job, job_dir)
        job.add_log("Pipeline finished successfully.")

    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = str(exc)
        job.add_log(f"FATAL: {exc}")

    finally:
        notify()


def _collect_result_files(job: Job, job_dir: Path) -> None:
    """Populate job.result_files with relative paths of notable outputs."""
    patterns = [
        "results/*.html",
        "summary/*.tsv",
        "summary/*.csv",
        "bigscape/**/*.tsv",
        "antismash/**/*.gbk",
        "antismash/**/*.json",
    ]
    seen: set[str] = set()
    for pattern in patterns:
        for path in sorted(job_dir.glob(pattern)):
            rel = str(path.relative_to(job_dir))
            if rel not in seen:
                seen.add(rel)
                job.result_files.append(rel)
