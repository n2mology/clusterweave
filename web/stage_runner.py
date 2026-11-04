#!/usr/bin/env python3
"""Run one stage with wait4 accounting, preserving its streamed output."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from resource_usage import StageSampler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--job", required=True)
    args, command = parser.parse_known_args()
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        return 127
    started = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    # The worker signals this entire session; stay alive to collect the child's status.
    signal.signal(signal.SIGTERM, lambda *_: None)
    sampler = StageSampler(args.job, os.getpgrp())
    try:
        sampler.start()
    except RuntimeError:
        sampler = None
    try:
        child = subprocess.Popen(command)
    except OSError:
        if sampler:
            try:
                sampler.finish()
            except Exception:
                pass
        return 127
    _, status, usage = os.wait4(child.pid, 0)
    child.returncode = os.waitstatus_to_exitcode(status)
    finished = datetime.now(timezone.utc).isoformat()
    try:
        observations = sampler.finish() if sampler else {"sampling_incomplete": True, "container_observation": "unavailable"}
    except Exception:
        observations = {"sampling_incomplete": True, "container_observation": "unavailable"}
    values = {"schema": 1, "started_at_utc": started, "finished_at_utc": finished,
              "wall_seconds": round(time.monotonic() - start, 6), "exit_code": child.returncode,
              "native_cpu_seconds": usage.ru_utime + usage.ru_stime,
              "native_largest_process_peak_rss_bytes": int(usage.ru_maxrss) * (1 if sys.platform == "darwin" else 1024),
              "native_cpu_method": "wait4 user+system CPU of the stage process and waited descendants; excludes Docker daemon and sibling tool containers",
              "native_peak_method": "wait4 maximum individual-process RSS; not concurrent aggregate RSS",
              **observations}
    try:
        if any(p.is_symlink() for p in (args.metrics, *args.metrics.parents)):
            raise ValueError("Unsafe metrics path")
        args.metrics.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".metrics-", dir=args.metrics.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(values, handle, sort_keys=True, allow_nan=False)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, args.metrics)
        finally:
            Path(temporary).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass  # Accounting failure must not change the scientific exit status.
    return child.returncode if child.returncode >= 0 else 128 - child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
