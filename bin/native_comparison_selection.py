#!/usr/bin/env python3
"""Bind engine selections by input CDS ordinal, validating the complete native slice.

BiG-SCAPE 2 beta.6 assigns orf_num before overlap filtering. Identical proteins,
locations and repeated annotation identifiers are legitimate separate features;
none is a global identity. The retained ordinal identifies the chosen feature,
while location/strand/translation checks reject stale or conflicting mappings.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from native_reporting_view import resolve_engine_records, native_record, join_error


def select_features(record, selected, row, db):
    cds = [(i, f) for i, f in enumerate(record.features) if f.type == 'CDS']
    # Supplied-CDS native contract requires translations for every CDS. Without
    # them the engine may skip/retranslate a feature, so ordinal equivalence is
    # not established and must not be guessed.
    if any(not f.qualifiers.get('translation', [''])[0] for _, f in cds):
        raise join_error(row, 'native CDS lacks supplied translation; ordinal contract unavailable')
    by_ordinal = {}
    for entry in selected:
        cid, start, stop, strand, peptide, orf = entry
        if not isinstance(orf, int) or not 1 <= orf <= len(cds) or orf in by_ordinal:
            raise join_error(row, 'missing or ambiguous selected CDS ordinal', [(x[0], x[-1]) for x in selected])
        ordinal, feature = cds[orf - 1]
        actual = (int(feature.location.start), int(feature.location.end), feature.location.strand,
                  feature.qualifiers['translation'][0])
        if actual != (start, stop, strand, peptide):
            raise join_error(row, f'CDS ordinal/content conflict: orf={orf} native_feature={ordinal} '
                             f'protein={feature.qualifiers.get("protein_id", [])}', [(cid, start, stop, strand)])
        by_ordinal[orf] = cid
    provenance = {x['native_feature_ordinal']: x for x in row.get('cds_provenance', [])}
    output = []
    for orf, (ordinal, feature) in enumerate(cds, 1):
        cid = by_ordinal.get(orf)
        item = {'native_feature_ordinal': ordinal, 'input_cds_ordinal': orf,
                'location': str(feature.location),
                'protein_id': feature.qualifiers.get('protein_id', []),
                'locus_tag': feature.qualifiers.get('locus_tag', []),
                'translation_sha256': hashlib.sha256(feature.qualifiers['translation'][0].encode()).hexdigest(),
                'selected': cid is not None}
        if ordinal in provenance:
            item['original_feature_key'] = provenance[ordinal]['original_feature_key']
            item['original_feature_ordinal'] = provenance[ordinal]['original_feature_ordinal']
        if cid is not None:
            item['raw_cds_id'] = cid
            item['selected_domains'] = [dict(zip(('raw_hsp_id','accession','start','stop','bit_score'), v))
                for v in db.execute('SELECT id,accession,env_start,env_stop,bit_score FROM hsp WHERE cds_id=? ORDER BY id', (cid,))]
        output.append(item)
    return output


def engine_input_contract(database):
    """Fail closed if the deployed pre-filter ordinal contract is unproven."""
    import re
    with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as db:
        runs = list(db.execute('SELECT label,end_time FROM run'))
    if len(runs) != 1 or not runs[0][1] or not re.fullmatch(r'[A-Za-z0-9_.-]+', runs[0][0]):
        raise ValueError(f'Native selection requires one completed engine run; candidates={runs}')
    log = Path(database).parent / (runs[0][0] + '.log')
    text = log.read_text()
    versions = set(re.findall(r'Starting BiG-SCAPE (\S+)', text))
    if versions != {'2.0.0-beta.6'} or 'All tasks done' not in text:
        raise ValueError(f'Unproven native CDS ordinal contract: engine versions={sorted(versions)} run={runs[0][0]}')
    return {'engine': 'BiG-SCAPE 2.0.0-beta.6', 'run_label': runs[0][0],
            'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
            'cds_ordinal': 'one-based input CDS order before overlap filtering; all supplied translations required'}


def record_selection(results, database):
    results = Path(results)
    path = results / 'summary/native_reporting_keys.json'
    if not path.is_file():
        return None
    view = json.loads(path.read_text())
    output = []
    contract = engine_input_contract(database)
    with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as db:
        for row, gid in resolve_engine_records(view, database, results):
            record = native_record(results, row)
            selected = [] if gid is None else list(db.execute(
                'SELECT id,nt_start,nt_stop,strand,aa_seq,orf_num FROM cds WHERE gbk_id=? ORDER BY orf_num', (gid,)))
            features = select_features(record, selected, row, db)
            output.append({**row, 'raw_gbk_id': gid, 'native_cds': len(features),
                           'selected_cds': len(selected), 'excluded_cds': len(features)-len(selected), 'features': features})
    receipt = {'schema': 'native-comparison-selection-v2', 'records': output, 'engine_contract': contract,
               'identity_contract': 'gbk.id + pre-filter orf_num, verified against native CDS order, bounds, strand and unchanged supplied translation; original record/CDS provenance remains separate from identifiers and engine selection',
               'interpretation': 'Complete native output remains retained, including length-excluded clusters and overlap-excluded CDS. Exclusion is not evidence of biological absence or harmlessness. Distances and families can depend on selection and input order.',
               'historical_D1': 'FAIL', 'historical_D3': 'FAIL'}
    (results / 'summary/native_comparison_selection.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    args = parser.parse_args()
    record_selection(args.results, args.database)
