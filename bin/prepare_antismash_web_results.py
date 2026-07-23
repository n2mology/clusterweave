#!/usr/bin/env python3
"""Build a minimal antiSMASH reuse-results document for web rendering.

Sharded analysis keeps the canonical merged JSON intact.  The web renderer only
needs records that contain detected areas; excluding empty records bounds HTML
rendering without changing any scientific result or downloadable source bundle.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile


def prepare_web_results(source: Path, destination: Path) -> int:
    with source.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict) or not isinstance(document.get("records"), list):
        raise ValueError("antiSMASH results JSON has no records list")

    records = [
        record
        for record in document["records"]
        if isinstance(record, dict) and record.get("areas")
    ]
    record_ids = {
        str(record.get("id") or record.get("original_id") or "")
        for record in records
    }
    record_ids.discard("")
    timings = document.get("timings", {})
    if not isinstance(timings, dict):
        raise ValueError("antiSMASH results JSON timings is not an object")

    filtered = dict(document)
    filtered["records"] = records
    filtered["timings"] = {
        key: value for key, value in timings.items() if str(key) in record_ids
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(filtered, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        count = prepare_web_results(args.source, args.destination)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"antiSMASH web-results preparation failed: {exc}", file=os.sys.stderr)
        return 1
    print(count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
