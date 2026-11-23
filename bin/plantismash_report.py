"""Read the pinned native report's JSON data without evaluating JavaScript."""
import json
from pathlib import Path
import re


def _text(value):
    return '' if value is None or str(value).strip() in {'', '-', 'n/a'} else str(value).strip()


def read_report(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Unsafe or oversized plant report data')
    match = re.fullmatch(r'\s*var geneclusters = ([\s\S]*);\s*var details_data = ([\s\S]*);\s*', path.read_text())
    if not match:
        raise ValueError('Unsupported plant report JSON profile')
    clusters, details = json.loads(match[1]), json.loads(match[2])
    if not isinstance(clusters, dict) or not isinstance(details, dict):
        raise ValueError('Invalid plant report JSON containers')
    return clusters


def call_report_fields(root, call, cache):
    root = Path(root)
    shard = root / 'native/shards' / f"{call['original_record_ordinal']:06d}" / 'native'
    report = (shard if shard.is_dir() else root / 'native') / 'geneclusters.js'
    if report not in cache:
        cache[report] = read_report(report)
    native_name = Path(call['native_cluster_gbk']).name
    number = re.search(r'\.cluster(\d+)\.gbk$', native_name)
    if not number:
        raise ValueError('Invalid native plant cluster name')
    row = cache[report][f'cluster-{int(number[1])}']
    if (row['start'], row['end']) != (call['start_1'], call['end_1']):
        raise ValueError('Plant report coordinates disagree with the validated call')
    domains, substrates = row.get('domains', []), row.get('substrates', [])
    if not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in [domains, substrates]):
        raise ValueError('Invalid plant report prediction fields')
    groups = row.get('cdhitclusters')
    if groups is not None and not isinstance(groups, list):
        raise ValueError('Invalid plant CD-HIT groups')
    accession, product = _text(row.get('BGCid')), _text(row.get('knowncluster'))
    if accession and not re.fullmatch(r'BGC\d{7}(?:\.\d+)?(?:_c\d+)?', accession):
        raise ValueError('Invalid native MIBiG accession')
    score = re.search(r'\((\d+(?:\.\d+)?)% (?:of genes|similarity)[^)]*\)', product)
    return {
        'bgc_record': f"{call['original_record_id']}.cluster{int(number[1]):03d}",
        'predictor_core_domains': ', '.join(dict.fromkeys(_text(v) for v in domains if _text(v))),
        'plantismash_subgroup_prediction': ', '.join(dict.fromkeys(_text(v) for v in substrates if _text(v))),
        'plantismash_cdhit_count': len(groups) if groups is not None else '',
        'plantismash_knowncluster_similarity_score': score[1] if score and accession else '',
        'plantismash_knowncluster_accession': accession,
        'plantismash_knowncluster_product': product[:score.start()].strip() if score else product,
    }
