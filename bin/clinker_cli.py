#!/usr/bin/env python3
"""Run a staged clinker panel with bounded, informative diagnostics."""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys


GENBANK_SUFFIXES = {".gb", ".gbk", ".gbff", ".genbank"}
PARENT_WARNING = re.compile(
    r"^(?:\[\d{2}:\d{2}:\d{2}\]\s*)?WARNING - "
    r"Could not find parent gene of .+\. Using coding sequence coordinates instead\.\s*$"
)
CIRCULAR_CHECK = re.compile(
    r"^(?:\[\d{2}:\d{2}:\d{2}\]\s*)?WARNING - .+ is circular, checking for genes spanning the origin\s*$"
)
ORIGIN_ADVICE = re.compile(
    r"^(?:\[\d{2}:\d{2}:\d{2}\]\s*)?WARNING - To disable this behaviour, use --dont_set_origin\s*$"
)


def input_policy(paths: list[str]) -> tuple[bool, bool]:
    """Prove origin shifting is a no-op and identify CDS-only annotations."""
    if not paths or any(Path(p).suffix.lower() not in GENBANK_SUFFIXES for p in paths):
        return False, False
    try:
        from Bio import SeqIO

        seen = seen_cds = False
        origin_noop = cds_only = True
        for path in paths:
            records = 0
            for record in SeqIO.parse(path, "genbank"):
                seen = True
                records += 1
                cds = [f for f in record.features if f.type == "CDS"]
                if cds:
                    seen_cds = True
                    cds_only &= not any(f.type == "gene" for f in record.features)
                if record.annotations.get("topology") != "circular":
                    continue
                for feature in record.features:
                    if feature.type.lower() not in {"gene", "cds"}:
                        continue
                    # Compound and unknown locations retain ordinary repair,
                    # including either strand's origin-spanning features.
                    parts = feature.location.parts
                    if len(parts) != 1 or parts[0].start >= parts[0].end:
                        origin_noop = False
            if not records:
                return False, False
        return seen and origin_noop, seen_cds and cds_only
    except (ImportError, OSError, ValueError, AttributeError, TypeError):
        return False, False


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--" not in args:
        print("Usage: clinker_cli.py INPUT... -- CLINKER_OPTIONS...", file=sys.stderr)
        return 2
    split = args.index("--")
    inputs, options = args[:split], args[split + 1:]
    if not inputs:
        return 2
    origin_noop, cds_only = input_policy(inputs)
    if origin_noop and "--dont_set_origin" not in options and "-dso" not in options:
        options.append("--dont_set_origin")
        print("[INFO] clinker --dont_set_origin: no gene or CDS location requires origin shifting.", file=sys.stderr)
    genbank_only = all(Path(p).suffix.lower() in GENBANK_SUFFIXES for p in inputs)
    try:
        child = subprocess.Popen(
            ["clinker", *inputs, *options], stderr=subprocess.PIPE,
            text=True, errors="replace", bufsize=1,
        )
    except OSError as error:
        print(f"[ERROR] Could not launch clinker: {error}", file=sys.stderr)
        return 127
    parent_count = circular_count = 0
    assert child.stderr is not None
    with child.stderr:
        for line in child.stderr:
            if genbank_only and PARENT_WARNING.fullmatch(line.rstrip("\r\n")):
                parent_count += 1
            elif genbank_only and CIRCULAR_CHECK.fullmatch(line.rstrip("\r\n")):
                circular_count += 1
            elif genbank_only and ORIGIN_ADVICE.fullmatch(line.rstrip("\r\n")):
                continue
            else:
                sys.stderr.write(line)
                sys.stderr.flush()
    status = child.wait()
    if circular_count:
        print(f"[INFO] clinker checked circular origins for {circular_count} records; origin correction remains enabled.", file=sys.stderr)
    if parent_count:
        level = "INFO" if cds_only else "WARN"
        print(
            f"[{level}] clinker used CDS coordinates for {parent_count} features "
            "without a matching parent gene.", file=sys.stderr,
        )
    return status if status >= 0 else 128 - status


if __name__ == "__main__":
    raise SystemExit(main())
