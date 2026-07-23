#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for module_root in (ROOT / "web", Path("/app")):
    if module_root.is_dir() and str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))

from genbank_readiness import inspect_genbank_translation_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether every non-pseudogene CDS has a non-empty translation"
    )
    parser.add_argument("genbank")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = inspect_genbank_translation_path(args.genbank)
    if args.json:
        print(
            json.dumps(
                {
                    "structurally_complete": result.structurally_complete,
                    "usable_translated_cds": result.usable_translated_cds,
                    "records": result.record_count,
                    "cds_total": result.cds_total,
                    "pseudogene_cds": result.pseudogene_cds,
                    "translated_cds": result.translated_cds,
                    "untranslated_cds": result.untranslated_cds,
                },
                sort_keys=True,
            )
        )
    return 0 if result.usable_translated_cds else 1


if __name__ == "__main__":
    raise SystemExit(main())
