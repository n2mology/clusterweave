#!/usr/bin/env python3
"""Count accepted detector outcomes before the canonical grouping stage."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re


def usable_count(manifest, results):
    count = 0
    with Path(manifest).open(newline='') as stream:
        for row in csv.DictReader(stream, delimiter='\t'):
            gbk = row.get('gbk_used', '')
            if not gbk or row.get('gbk_status') == 'annotation_fallbacks_failed':
                continue
            if row.get('taxon_group') != 'plants':
                count += row.get('antismash_status') in {'ran_ok', 'ran_ok_sanitized', 'skipped_done'}
                continue
            genome = row.get('genome_id', '')
            if row.get('detector_profile') != 'plantismash' or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', genome):
                continue
            native = Path(results) / 'plantismash' / genome
            try:
                outcome = json.loads((native / 'outcome.json').read_text())
                exit_record = json.loads((native / 'native-exit.json').read_text())
                calls = outcome.get('calls')
                expected = 'SUCCESSFUL_EMPTY' if calls == 0 else 'SUCCESS_WITH_CALLS'
                valid = (type(calls) is int and calls >= 0
                         and outcome.get('state') == expected
                         and outcome.get('genome_id') == genome
                         and outcome.get('producer') in {'plantismash-2.0.4-private-repeat2', 'plantismash-2.0.4-clusterweave-extras-v3'}
                         and exit_record.get('exit_code') == 0
                         and hashlib.sha256(Path(gbk).read_bytes()).hexdigest() == outcome.get('source_sha256')
                         and hashlib.sha256((native / 'native/native-completion.json').read_bytes()).hexdigest() == outcome.get('completion_sha256'))
                count += bool(valid)
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    args = parser.parse_args()
    print(usable_count(args.manifest, args.results))
