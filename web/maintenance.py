#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

try:
    from job_store import sweep_expired_jobs
except ImportError:  # pragma: no cover - package-style imports in local tests
    from .job_store import sweep_expired_jobs


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    command = args[0] if args else "sweep-expired-jobs"
    if command not in {"sweep-expired-jobs", "sweep"}:
        print("usage: maintenance.py [sweep-expired-jobs]", file=sys.stderr)
        return 2
    print(json.dumps(sweep_expired_jobs(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
