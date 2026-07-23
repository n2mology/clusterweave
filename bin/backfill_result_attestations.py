#!/usr/bin/env python3
"""Build signed result indexes for completed legacy jobs outside request paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]
WEB_ROOT = REPO_ROOT / "web"
if not (WEB_ROOT / "app.py").is_file() and (SCRIPT_PATH.parent / "app.py").is_file():
    WEB_ROOT = SCRIPT_PATH.parent
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from app import result_file_is_publicly_servable  # noqa: E402
from job_store import (  # noqa: E402
    JOBS_DIR,
    atomic_write_text,
    compact_job_summary,
    job_summary_path,
    list_jobs,
)
from result_attestation import write_result_attestation  # noqa: E402
from result_policy import PUBLIC_RESULTS_MANIFEST_PATH  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_ids", nargs="*", help="specific job IDs; default is all terminal jobs")
    args = parser.parse_args()
    selected = set(args.job_ids)
    built = 0
    summaries = 0
    failed = 0
    for job in list_jobs():
        job_id = str(job.get("id") or "")
        if selected and job_id not in selected:
            continue
        try:
            atomic_write_text(
                job_summary_path(job_id),
                json.dumps(
                    compact_job_summary(job),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            summaries += 1
        except (OSError, TypeError, ValueError) as exc:
            print(f"{job_id}\tSUMMARY_FAILED\t{type(exc).__name__}", file=sys.stderr)
            failed += 1
        if str(job.get("status") or "").lower() not in {"success", "failed"}:
            continue
        base = JOBS_DIR / job_id
        if not (base / PUBLIC_RESULTS_MANIFEST_PATH).is_file():
            continue
        try:
            attestation = write_result_attestation(
                base,
                job_id,
                verify_hashes=True,
                path_validator=lambda path: result_file_is_publicly_servable(
                    base, path
                ),
            )
            print(f"{job_id}\t{attestation.generation}\t{len(attestation.files)}")
            built += 1
        except (OSError, ValueError, UnicodeError) as exc:
            print(f"{job_id}\tFAILED\t{type(exc).__name__}", file=sys.stderr)
            failed += 1
    print(f"summaries={summaries} attestations={built} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
