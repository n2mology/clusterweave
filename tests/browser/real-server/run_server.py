#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_DIR = REPO_ROOT / "web"
REAL_SERVER_PORTS = {"4174", "4175", "4176"}


def _interrupt_server(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def _seed_lifecycle_fixture(app: object) -> None:
    import job_store
    from result_attestation import write_result_attestation

    created = "2026-07-24T12:00:00"
    updated = "2026-07-24T12:01:00"
    fixtures = [
        {
            "id": "r01equeued",
            "public_run_id": "R01eQueuedRunFixture01",
            "read_token": "r01e-queued-read-token",
            "name": "Queued lifecycle fixture",
            "project_name": "r01e_queued",
            "status": "pending",
            "stage": "queued",
            "taxon_routes": [
                {
                    "genome_id": "queued_fungus",
                    "organism_name": "Queued fungal genome",
                    "taxon_group": "fungi",
                    "taxon_source": "user_declaration",
                }
            ],
            "logs": [],
        },
        {
            "id": "r01erunning",
            "public_run_id": "R01eRunningRunFixture1",
            "read_token": "r01e-running-read-token",
            "name": "Running lifecycle fixture",
            "project_name": "r01e_running",
            "status": "running",
            "stage": "annotation",
            "taxon_routes": [
                {
                    "genome_id": "running_fungus",
                    "organism_name": "Running fungal genome",
                    "taxon_group": "fungi",
                    "taxon_source": "user_declaration",
                    "prediction_method": "funannotate",
                },
                {
                    "genome_id": "waiting_bacterium",
                    "organism_name": "Waiting bacterial genome",
                    "taxon_group": "bacteria",
                    "taxon_source": "user_declaration",
                    "prediction_method": "prodigal",
                },
            ],
            "logs": [
                '[12:00:01] GENOME_PROGRESS genome=running_fungus stage=annotation percent=25 bar=[#####---------------] message="Annotation complete"',
                '[12:00:02] ANTISMASH_RECORD_PROGRESS genome=running_fungus record=private_record ordinal=2/5 percent=40 bar=[########------------] message="antiSMASH record shard complete"',
                '[12:00:03] TOOL_PROGRESS genome=running_fungus tool=antismash phase=record_3 message="Scanning protein domains"',
            ],
        },
        {
            "id": "r01edone",
            "public_run_id": "R01eDoneRunFixture0001",
            "read_token": "r01e-completed-read-token",
            "name": "Completed lifecycle fixture",
            "project_name": "r01e_completed",
            "status": "success",
            "stage": "complete",
            "completed_at": updated,
            "taxon_routes": [
                {
                    "genome_id": "completed_fungus",
                    "organism_name": "Completed fungal genome",
                    "taxon_group": "fungi",
                    "taxon_source": "user_declaration",
                }
            ],
            "logs": [
                '[12:00:01] GENOME_PROGRESS genome=completed_fungus stage=funbgcex percent=100 bar=[####################] message="FunBGCeX complete"',
            ],
        },
    ]

    for fixture in fixtures:
        logs = list(fixture.pop("logs"))
        token = str(fixture.pop("read_token"))
        routes = list(fixture["taxon_routes"])
        job = {
            **fixture,
            "created_at": created,
            "updated_at": updated,
            "log_count": len(logs),
            "result_files": [],
            "analysis_scope": "both",
            "taxon_counts": {"fungi": 1, "bacteria": 1 if len(routes) > 1 else 0, "total": len(routes)},
            "input_summary": {
                "analysis_scope": "both",
                "genome_count": len(routes),
                "taxon_counts": {"fungi": 1, "bacteria": 1 if len(routes) > 1 else 0, "total": len(routes)},
            },
            "read_token_hash": app.job_token_hash(token),
            "read_token_created_at": created,
        }
        root = job_store.job_dir(str(job["id"]))
        if job["status"] == "success":
            relative = "data/results/r01e_completed/figures/lifecycle_overview.svg"
            content = (
                b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 320" role="img">'
                b'<title>R01e lifecycle overview</title>'
                b'<desc>Synthetic completed-result fixture for public browser characterization.</desc>'
                b'<rect width="640" height="320" fill="#f4f1e8"/>'
                b'<text x="40" y="170" font-size="34">ClusterWeave lifecycle complete</text>'
                b'</svg>\n'
            )
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            manifest = root / "downloads" / "public_results_manifest.tsv"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(
                "path\tbytes\tsha256\n"
                f"{relative}\t{len(content)}\t{hashlib.sha256(content).hexdigest()}\n",
                encoding="utf-8",
            )
            job["result_files"] = ["downloads/public_results_manifest.tsv", relative]
        job_store.write_job(job)
        if logs:
            job_store.write_logs(str(job["id"]), logs)
        if job["status"] == "success":
            write_result_attestation(
                root,
                str(job["id"]),
                verify_hashes=True,
                path_validator=lambda path, base=root: app.result_file_is_publicly_servable(base, path),
            )

    app.enqueue_job("r01equeued", 2, {"analysis_scope": "both"})


def _seed_admin_fixture() -> None:
    import job_store

    created = "2026-07-24T13:00:00"
    job = {
        "id": "f01a11ce",
        "public_run_id": "R01fAdminRunFixture001",
        "name": "Administrator browser fixture",
        "project_name": "r01f_admin",
        "status": "running",
        "stage": "annotation",
        "created_at": created,
        "updated_at": "2026-07-24T13:01:00",
        "log_count": 3,
        "result_files": [],
        "analysis_scope": "fungi",
        "taxon_counts": {"fungi": 1, "bacteria": 0, "total": 1},
        "input_summary": {
            "analysis_scope": "fungi",
            "genome_count": 1,
            "taxon_counts": {"fungi": 1, "bacteria": 0, "total": 1},
        },
        "taxon_routes": [
            {
                "genome_id": "admin_fungus",
                "organism_name": "Administrator fixture genome",
                "taxon_group": "fungi",
                "taxon_source": "user_declaration",
                "prediction_method": "funannotate",
            }
        ],
    }
    job_store.write_job(job)
    job_store.write_logs(
        str(job["id"]),
        [
            "[13:00:01] Preparing administrator fixture",
            "[13:00:02] GENOME_PROGRESS genome=admin_fungus stage=annotation percent=25 bar=[#####---------------] message=Annotating",
            "[13:00:03] TOOL_PROGRESS genome=admin_fungus tool=funannotate phase=predict message=Calling genes",
        ],
    )


def main() -> None:
    sys.dont_write_bytecode = True
    data_dir = Path(os.environ["CLUSTERWEAVE_REAL_SERVER_DATA_DIR"]).resolve()
    expected_prefix = Path(tempfile.gettempdir()) / "clusterweave-playwright-real-server-"
    if not data_dir.is_dir() or not str(data_dir).startswith(str(expected_prefix)):
        raise RuntimeError("Real-server test data directory is outside the expected temp prefix")
    port = os.environ.get("CLUSTERWEAVE_REAL_SERVER_PORT", "4174")
    if port not in REAL_SERVER_PORTS:
        raise RuntimeError("Real-server test port is outside the expected allowlist")
    fixture = os.environ.get("CLUSTERWEAVE_REAL_SERVER_FIXTURE", "")
    if fixture not in {"", "lifecycle", "admin"}:
        raise RuntimeError("Unknown real-server test fixture")
    os.environ.update(
        {
            "HOST": "127.0.0.1",
            "PORT": port,
            "DATA_DIR": str(data_dir),
            "CLUSTERWEAVE_UPLOAD_STAGING_DIR": str(data_dir / ".upload_staging"),
            "CLUSTERWEAVE_PUBLIC_MODE": "1",
            "CLUSTERWEAVE_ALLOW_UNSAFE_LOCAL_MODE": "0",
            "CLUSTERWEAVE_SUBMISSIONS_OPEN": "0",
            "CLUSTERWEAVE_NCBI_ACCESSION_PREFLIGHT": "0",
            "CLUSTERWEAVE_SMTP_ENABLED": "0",
            "CLUSTERWEAVE_ALLOWED_ORIGINS": "",
            "CLUSTERWEAVE_SUBMIT_TOKEN": "",
            "CLUSTERWEAVE_SUBMIT_TOKEN_SHA256": "",
            "CLUSTERWEAVE_SUBMIT_TOKEN_HASH": "",
            "CLUSTERWEAVE_ADMIN_TOKEN": "",
            "CLUSTERWEAVE_ADMIN_TOKEN_SHA256": "",
            "CLUSTERWEAVE_ADMIN_TOKEN_HASH": "",
            "CLUSTERWEAVE_JOB_TOKEN_SECRET": "",
        }
    )
    if fixture == "admin":
        os.environ["CLUSTERWEAVE_ADMIN_TOKEN"] = "r01f-admin-browser-token"
    sys.path.insert(0, str(WEB_DIR))

    import app

    if fixture == "lifecycle":
        _seed_lifecycle_fixture(app)
    elif fixture == "admin":
        _seed_admin_fixture()
    signal.signal(signal.SIGINT, _interrupt_server)
    signal.signal(signal.SIGTERM, _interrupt_server)
    app.main()


if __name__ == "__main__":
    main()
