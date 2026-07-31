#!/usr/bin/env python3
"""Transactionally retain only merge-critical antiSMASH shard artifacts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
import uuid


MARKER_NAME = ".compacted"


class CompactionError(RuntimeError):
    """Raised when a shard cannot be compacted without losing diagnostics."""


def _target_record(document: dict[str, Any], expected_record_id: str) -> dict[str, Any]:
    records = document.get("records")
    if not isinstance(records, list) or not records:
        raise CompactionError("antiSMASH shard JSON has no records")

    matching_records = [
        record
        for record in records
        if isinstance(record, dict)
        and (
            str(record.get("id", "")) == expected_record_id
            or str(record.get("original_id", "")) == expected_record_id
        )
    ]
    if len(matching_records) != 1:
        analysed_records = [
            record
            for record in records
            if isinstance(record, dict) and (record.get("areas") or record.get("modules"))
        ]
        if len(analysed_records) == 1:
            matching_records = analysed_records
    if len(matching_records) != 1:
        raise CompactionError(
            "antiSMASH shard JSON did not contain exactly one target record "
            f"{expected_record_id!r}"
        )
    return matching_records[0]


def _target_timings(
    timings: Any, expected_record_id: str, target_record: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(timings, dict):
        raise CompactionError("antiSMASH shard JSON timings is not an object")

    candidate_ids = {
        expected_record_id,
        str(target_record.get("id", "")),
        str(target_record.get("original_id", "")),
    }
    candidate_ids.discard("")
    selected = {key: value for key, value in timings.items() if str(key) in candidate_ids}
    if selected:
        return selected
    # antiSMASH versions can normalize the timing key separately from the record
    # identifier. A single timing entry is unambiguous for a one-record shard.
    if len(timings) == 1:
        key, value = next(iter(timings.items()))
        return {key: value}
    if not timings:
        return {}
    raise CompactionError(
        f"antiSMASH shard JSON has no unambiguous timing entry for {expected_record_id!r}"
    )


def _source_json(shard_dir: Path, json_name: str) -> Path:
    expected = shard_dir / json_name
    if expected.is_file():
        return expected
    fallbacks = sorted(
        path
        for path in shard_dir.glob("*.antismash.json")
        if path.is_file() and not path.is_symlink()
    )
    if len(fallbacks) == 1:
        return fallbacks[0]
    raise CompactionError(
        f"missing expected antiSMASH shard JSON {expected}; "
        f"found {len(fallbacks)} fallback files"
    )


def _atomic_json_write(path: Path, document: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Validate the exact bytes that will become visible to the merger.
        with temporary_path.open(encoding="utf-8") as handle:
            validated = json.load(handle)
        if not isinstance(validated, dict) or len(validated.get("records", [])) != 1:
            raise CompactionError("compacted antiSMASH JSON failed validation")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _region_files(shard_dir: Path) -> list[Path]:
    regions: list[Path] = []
    for root, directory_names, file_names in os.walk(shard_dir, followlinks=False):
        root_path = Path(root)
        directory_names[:] = [
            name for name in directory_names if not (root_path / name).is_symlink()
        ]
        for name in file_names:
            if "region" not in name or not name.endswith(".gbk"):
                continue
            path = root_path / name
            if path.is_symlink() or not path.is_file():
                raise CompactionError(f"refusing unsafe region artifact: {path}")
            regions.append(path)
    return sorted(regions, key=lambda path: path.relative_to(shard_dir).as_posix())


def _activate_compacted_directory(shard_dir: Path, staged_dir: Path) -> None:
    parent = shard_dir.parent
    backup = parent / f".{shard_dir.name}.raw.{uuid.uuid4().hex}"
    displaced_compact = parent / f".{shard_dir.name}.compact-failed.{uuid.uuid4().hex}"
    os.rename(shard_dir, backup)
    try:
        os.rename(staged_dir, shard_dir)
    except BaseException:
        os.rename(backup, shard_dir)
        raise

    try:
        shutil.rmtree(backup)
    except BaseException:
        # Retaining the raw shard is more important than keeping the compact copy
        # when reclamation itself fails.
        try:
            os.rename(shard_dir, displaced_compact)
            os.rename(backup, shard_dir)
        finally:
            shutil.rmtree(displaced_compact, ignore_errors=True)
        raise


def compact_shard(
    shard_dir: Path, expected_record_id: str, json_name: str, *, retain: bool = False
) -> None:
    if retain:
        return
    if not shard_dir.is_dir() or shard_dir.is_symlink():
        raise CompactionError(f"antiSMASH shard directory is invalid: {shard_dir}")
    if not json_name or Path(json_name).name != json_name or json_name in {".", ".."}:
        raise CompactionError(f"unsafe compact JSON filename: {json_name!r}")

    source_json = _source_json(shard_dir, json_name)
    try:
        with source_json.open(encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CompactionError(f"cannot read antiSMASH shard JSON {source_json}: {exc}") from exc
    if not isinstance(document, dict):
        raise CompactionError(f"antiSMASH shard JSON is not an object: {source_json}")

    target_record = _target_record(document, expected_record_id)
    compact_document = dict(document)
    compact_document["records"] = [target_record]
    compact_document["timings"] = _target_timings(
        document.get("timings", {}), expected_record_id, target_record
    )
    regions = _region_files(shard_dir)

    staged_dir = Path(
        tempfile.mkdtemp(prefix=f".{shard_dir.name}.compact.", dir=shard_dir.parent)
    )
    try:
        _atomic_json_write(staged_dir / json_name, compact_document)
        for region in regions:
            relative = region.relative_to(shard_dir)
            destination = staged_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise CompactionError(f"region artifact collision: {relative}")
            shutil.copy2(region, destination, follow_symlinks=False)

        marker = {
            "schema": 1,
            "record_id": expected_record_id,
            "json": json_name,
            "region_count": len(regions),
        }
        _atomic_json_write(staged_dir / MARKER_NAME, {"records": [marker]})
        # Keep the marker clear and independent from antiSMASH's schema.
        marker_path = staged_dir / MARKER_NAME
        marker_path.write_text(
            json.dumps(marker, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        _activate_compacted_directory(shard_dir, staged_dir)
    except BaseException:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise


def merge_shards(
    output_path: Path, record_and_paths: list[tuple[str, Path]]
) -> None:
    if not record_and_paths:
        raise CompactionError("no antiSMASH shard JSON documents were provided")
    merged: dict[str, Any] | None = None
    merged_records = []
    merged_timings: dict[str, Any] = {}
    for expected_record_id, input_path in record_and_paths:
        try:
            with input_path.open(encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise CompactionError(
                f"cannot read antiSMASH shard JSON {input_path}: {exc}"
            ) from exc
        if not isinstance(document, dict):
            raise CompactionError(
                f"antiSMASH shard JSON is not an object: {input_path}"
            )
        merged_records.append(_target_record(document, expected_record_id))
        timings = document.get("timings", {})
        if not isinstance(timings, dict):
            raise CompactionError(
                f"antiSMASH shard JSON timings is not an object: {input_path}"
            )
        if merged is None:
            merged = document
        merged_timings.update(timings)

    if merged is None:
        raise CompactionError("no antiSMASH shard JSON documents were provided")
    merged["records"] = merged_records
    merged["timings"] = merged_timings
    temporary_path = Path(str(output_path) + ".tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(merged, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-dir", type=Path)
    parser.add_argument("--record-id")
    parser.add_argument("--json-name")
    parser.add_argument("--retain", choices=("0", "1"), default="0")
    parser.add_argument("--merge-output", type=Path)
    parser.add_argument(
        "--record-json-pair", action="append", nargs=2, metavar=("RECORD_ID", "JSON")
    )
    args = parser.parse_args()
    merge_mode = args.merge_output is not None or args.record_json_pair is not None
    if merge_mode:
        if args.merge_output is None or not args.record_json_pair:
            parser.error("merge mode requires --merge-output and --record-json-pair")
        if (
            args.shard_dir is not None
            or args.record_id is not None
            or args.json_name is not None
        ):
            parser.error("merge mode cannot include shard compaction arguments")
    else:
        missing = [
            option
            for option, value in (
                ("--shard-dir", args.shard_dir),
                ("--record-id", args.record_id),
                ("--json-name", args.json_name),
            )
            if value is None
        ]
        if missing:
            parser.error("the following arguments are required: " + ", ".join(missing))
    return args


def main() -> int:
    args = _parse_args()
    if args.merge_output is not None:
        try:
            merge_shards(
                args.merge_output,
                [
                    (record_id, Path(json_path))
                    for record_id, json_path in args.record_json_pair
                ],
            )
        except (CompactionError, OSError) as exc:
            print(f"antiSMASH shard merge failed: {exc}", file=os.sys.stderr)
            return 1
        return 0
    try:
        compact_shard(
            args.shard_dir,
            args.record_id,
            args.json_name,
            retain=args.retain == "1",
        )
    except (CompactionError, OSError) as exc:
        print(f"antiSMASH shard compaction failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
