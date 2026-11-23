"""Durable exclusion decisions over a closed annotation attempt.

Failures remain failures. A decision permits only a separately materialized
cohort of complete detector outputs; it cannot admit a rejected output.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid

SCHEMA = 'clusterweave-cohort-decision-v1'
SUCCESS = {'ran_ok', 'ran_ok_sanitized', 'skipped_done'}
GENOME = re.compile(r'[A-Za-z0-9_.-]{1,120}')
FAILURES = {
    'annotation_incompatible': ('supplied_annotation_incompatible', 'Supplied annotation incompatible; plantiSMASH was not run.'),
    'annotation_required': ('annotation_required', 'Matching translated annotation required; plantiSMASH was not run.'),
    'annotation_fallbacks_failed': ('annotation_runtime_failure', 'Annotation/runtime failure; no complete detector outputs.'),
    'no_fasta_for_annotation': ('annotation_required', 'No sequence available for annotation.'),
    'funannotate_busco_training_insufficient': ('annotation_runtime_failure', 'Insufficient BUSCO training models.'),
    'funannotate_training_models_insufficient': ('annotation_runtime_failure', 'Insufficient annotation training models.'),
}


class GateError(ValueError):
    pass


def digest(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise GateError('Nonregular identity input')
        value = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
        stamp = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        if stamp(before) != stamp(after) or stamp(after) != stamp(os.stat(path, follow_symlinks=False)):
            raise GateError('Identity input changed while reading')
        return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x') as stream:
            json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def rows(path):
    with Path(path).open(newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        fields = reader.fieldnames
        result = list(reader)
    if not fields or len(fields) != len(set(fields)) or len(result) > 4096 or any(None in r or any(v is None for v in r.values()) for r in result):
        raise GateError('Invalid outcome manifest')
    return fields, result


def write_rows(path, fields, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        writer.writerows(values)


def inventory(root, paths):
    root = Path(root).resolve()
    found = {}
    for relative in paths:
        base = root / relative
        candidates = [base, *sorted(base.rglob('*'))] if base.is_dir() else [base]
        for path in candidates:
            if not path.exists() and not path.is_symlink():
                continue
            if any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to(root):
                raise GateError('Confinement failure in outcome inventory')
            mode = path.stat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise GateError('Nonregular output')
            found[path.relative_to(root).as_posix()] = {'sha256': digest(path), 'bytes': path.stat().st_size}
            if len(found) > 100000:
                raise GateError('Outcome inventory limit exceeded')
    return found


def microbial_count(results, row):
    """Require successful producer markers and consistent native region payloads."""
    from Bio import SeqIO
    genome = row['genome_id']
    directory = results / 'antismash' / genome
    if not (directory / '.done').is_file() or not (directory / 'index.html').stat().st_size:
        raise GateError('Incomplete antiSMASH output')
    names = list(directory.glob('*.json'))
    native = [json.loads(p.read_text()) for p in names if p.name.endswith('.antismash.json')]
    if len(native) != 1 or not native[0].get('records'):
        raise GateError('Invalid antiSMASH record inventory')
    full_files = [p for p in directory.glob('*.gbk') if not re.search(r'\.region\d+\.gbk$', p.name)]
    if len(full_files) != 1:
        raise GateError('Missing complete native GenBank')
    full = list(SeqIO.parse(full_files[0], 'genbank'))
    admitted = list(SeqIO.parse(results / 'input_gbks' / (genome + '.gbk'), 'genbank'))
    admitted_sequences = {str(r.seq).upper() for r in admitted}
    if not admitted or any(str(r.seq).upper() not in admitted_sequences for r in full):
        raise GateError('Native sequence differs from admitted input')
    records = native[0]['records']
    # antiSMASH's compact sharded report keeps zero-region records in JSON
    # but may omit them from the combined GenBank. Join by native identity;
    # never require a positional/count match or omit a called record.
    native_ids = [v.get('id') for v in records]
    full_ids = [r.id for r in full]
    if len(set(native_ids)) != len(native_ids) or len(set(full_ids)) != len(full_ids):
        raise GateError('Duplicate native record identity')
    if not set(full_ids) <= set(native_ids):
        raise GateError('GenBank record missing from native JSON')
    by_id = {r.id: r for r in full}
    expected = []
    for value in records:
        if not isinstance(value.get('areas'), list):
            raise GateError('Invalid native region inventory')
        record = by_id.get(value['id'])
        if record is None:
            sequence = value.get('seq', {}).get('data', '')
            if value['areas'] or any(f.get('type') == 'region' for f in value.get('features', [])):
                raise GateError('Called native record missing from GenBank')
            original = next((r for r in admitted if r.id == value['id']), None)
            if original is None or not sequence or sequence.upper() != str(original.seq).upper():
                raise GateError('Zero-region JSON sequence differs from admitted input')
            continue
        regions = [f for f in record.features if f.type == 'region']
        if len(regions) != len(value['areas']):
            raise GateError('Native region count differs')
        for feature, area in zip(regions, value['areas']):
            start, end = area['start'], area['end']
            if not (type(start) is int and type(end) is int and 0 <= start < end <= len(record)):
                raise GateError('Invalid native coordinates')
            if int(feature.location.start) != start or int(feature.location.end) != end:
                raise GateError('Native coordinates differ')
            expected.append(str(record.seq[start:end]).upper())
    crops = list(directory.glob('*.region*.gbk'))
    sequences = []
    for path in crops:
        parsed = list(SeqIO.parse(path, 'genbank'))
        if len(parsed) != 1:
            raise GateError('Invalid native region crop')
        sequences.append(str(parsed[0].seq).upper())
    if sorted(sequences) != sorted(expected):
        raise GateError('Incomplete or invalid native region sequences')
    counts = {'antismash': len(expected)}
    if row['taxon_group'] == 'fungi':
        fbx = results / 'funbgcex' / genome
        if row['funbgcex_status'] not in SUCCESS or not (fbx / '.done').is_file():
            raise GateError('Incomplete FunBGCeX output')
        with (fbx / 'allBGCs.csv').open(newline='') as stream:
            reader = csv.DictReader(stream)
            if not {'BGC no.', 'Scaffold', 'Start position', 'End position'} <= set(reader.fieldnames or []):
                raise GateError('Invalid FunBGCeX inventory')
            entries = list(reader)
        if any(None in r or any(v is None for v in r.values()) for r in entries):
            raise GateError('Invalid FunBGCeX rows')
        counts['funbgcex'] = len(entries)
    return counts


def genome_outcome(results, row):
    genome = row['genome_id']
    value = {'genome_id': genome, 'taxon_group': row['taxon_group'], 'state': 'failed',
             'category': 'invalid_scientific_output', 'reason': 'Incomplete or invalid scientific output.',
             'excludable': False, 'counts': None, 'manifest_row_sha256': fingerprint(row)}
    if row['gbk_status'] in FAILURES and not row['gbk_used']:
        value['category'], value['reason'] = FAILURES[row['gbk_status']]
        value['excludable'] = True
        return value
    if row['gbk_status'] == 'unclassified_failure':
        value.update(category='unclassified_failure', reason='Unclassified failure requires operator review.')
        return value
    try:
        if row['taxon_group'] == 'plants':
            # Full producer validation includes native exit/completion, mappings,
            # all original records and the profile contract, including zero calls.
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
            from plantismash_native import read_native
            directory = results / 'plantismash' / genome
            native = read_native(json.loads((directory / 'original-identity.json').read_text()), directory / 'native')
            outcome = json.loads((directory / 'outcome.json').read_text())
            if not native['valid'] or outcome['genome_id'] != genome or outcome['state'] != native['outcome'] or outcome['calls'] != len(native['calls']):
                raise GateError('Invalid plant native output')
            counts = {'plantismash': len(native['calls'])}
        else:
            if row['antismash_status'] not in SUCCESS:
                raise GateError('Detector did not finish successfully')
            counts = microbial_count(results, row)
        if not row['gbk_used'] or not (results / 'input_gbks' / (genome + '.gbk')).is_file():
            raise GateError('Missing admitted annotation input')
        value.update(state='successful_empty' if not any(counts.values()) else 'success',
                     category='validated_output', reason='Validated detector outputs available.', counts=counts)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        value['reason'] = 'Scientific output validation failed: ' + (str(exc) if isinstance(exc, GateError) else type(exc).__name__)
    return value


def downstream_plan(outcomes, settings):
    valid = [r for r in outcomes if r['state'] in {'success', 'successful_empty'}]
    has_calls = any(any((r['counts'] or {}).values()) for r in valid)
    plan = {}
    for key in ('bigscape', 'summary', 'clinker', 'figures', 'phylogeny', 'nplinker', 'cross_kingdom_evidence'):
        enabled = str(settings.get('run_' + key, key in {'bigscape', 'summary', 'clinker', 'figures'})).lower() in {'1', 'true', 'yes', 'auto'}
        if not enabled:
            plan[key] = 'skipped: not selected'
        elif not valid:
            plan[key] = 'blocked: no eligible cohort'
        elif key != 'summary' and not has_calls:
            plan[key] = 'skipped: successful zero-BGC cohort'
        elif key == 'nplinker' and settings.get('target_genome') not in {r['genome_id'] for r in valid}:
            plan[key] = 'blocked: target genome excluded or unavailable'
        elif key == 'cross_kingdom_evidence' and len({r['taxon_group'] for r in valid}) < 2:
            plan[key] = 'skipped: fewer than two retained taxa'
        else:
            plan[key] = 'will run: validated cohort; later stages still require their upstream outputs'
    return plan


def build_gate(results, control, identity, settings, exit_code=0, *, publish=True):
    results = Path(results).resolve()
    _, manifest = rows(results / 'summary_tables/run_manifest.tsv')
    _, routes = rows(results / 'summary_tables/genome_taxon_manifest.tsv')
    active = [r for r in routes if r.get('route_status') not in {'excluded', 'rejected', 'unresolved'}]
    ids = [r['genome_id'] for r in manifest]
    expected = [r['genome_id'] for r in active]
    if not ids or len(ids) != len(set(ids)) or set(ids) != set(expected) or len(expected) != len(set(expected)) or any(not GENOME.fullmatch(g) or g in {'.', '..'} for g in ids):
        raise GateError('Every genome must have one outcome row before continuation')
    routes_by_id = {r['genome_id']: r for r in active}
    if any(r['taxon_group'] != routes_by_id[r['genome_id']]['taxon_group'] for r in manifest):
        raise GateError('Taxon identity mismatch')
    receipt_dir = results / 'reproducibility/genome_attempts'
    receipt_rows = {}
    for receipt in receipt_dir.glob('*.tsv'):
        line = receipt.read_text().rstrip('\n').split('\t')
        if len(line) != len(manifest[0]) or line[0] in receipt_rows:
            raise GateError('Invalid per-genome attempt receipt')
        code = int(receipt.with_suffix('.tsv.exit').read_text())
        receipt_rows[line[0]] = (dict(zip(manifest[0], line)), code)
    if set(receipt_rows) != set(ids) or any(receipt_rows[r['genome_id']][0] != r for r in manifest):
        raise GateError('Missing or changed per-genome attempt receipts')
    outcomes = [genome_outcome(results, r) for r in manifest]
    for outcome in outcomes:
        route = routes_by_id[outcome['genome_id']]
        outcome['source_accession'] = route.get('source_accession', '')
        outcome['organism_name'] = route.get('organism_name', '')
    for outcome in outcomes:
        code = receipt_rows[outcome['genome_id']][1]
        outcome['exit_code'] = code
        if outcome['state'] in {'success', 'successful_empty'} and code != 0:
            outcome.update(state='failed', excludable=False, counts=None,
                           category='execution_failure', reason='Native task did not exit successfully.')
    included = sorted(r['genome_id'] for r in outcomes if r['state'] in {'success', 'successful_empty'})
    excluded = sorted(set(ids) - set(included))
    eligible = bool(included and excluded and all(r['excludable'] for r in outcomes if r['genome_id'] in excluded))
    if exit_code and not excluded:
        raise GateError('Shared annotation stage failed; no exclusion can override it')
    paths = ['input_gbks', 'antismash', 'funbgcex', 'plantismash', 'summary_tables/run_manifest.tsv', 'summary_tables/genome_taxon_manifest.tsv', 'summary_tables/bacterial_record_maps', 'reproducibility/genome_attempts']
    gate = {'schema': SCHEMA, 'attempt': uuid.uuid4().hex, 'identity': identity,
            'results': str(results), 'outcomes': outcomes, 'included': included, 'excluded': excluded,
            'eligible': eligible, 'state': 'awaiting_decision' if eligible else 'failed' if excluded else 'complete',
            'plan': downstream_plan(outcomes, settings), 'paths': paths,
            'receipts': inventory(results, paths)}
    if excluded and not eligible:
        gate['plan'] = {k: ('blocked: genome validation must be resolved' if v.startswith('will run') else v) for k,v in gate['plan'].items()}
    gate['annotation_exit_code'] = exit_code
    gate['decision_id'] = fingerprint(gate)
    if publish:
        publish_gate(control, gate)
    return gate


def publish_gate(control, gate):
    # Publish the pointer last; a crash cannot expose an incomplete binding.
    atomic_json(Path(control).parent / ('attempt-' + gate['attempt'] + '.json'), gate)
    atomic_json(control, gate)


def load_gate(control):
    value = json.loads(Path(control).read_text())
    if value.get('schema') != SCHEMA:
        raise GateError('Unsupported cohort decision')
    body = {k: v for k, v in value.items() if k not in {'decision_id', 'acceptance'}}
    if fingerprint(body) != value.get('decision_id'):
        raise GateError('Outcome decision identity differs')
    return value


def verify_gate(gate):
    if inventory(gate['results'], gate['paths']) != gate['receipts']:
        raise GateError('Scientific outputs or outcome receipts changed; decision is stale')


def accept(control, decision_id, included, excluded, *, attempt_identity):
    """Caller holds the ordinary queue admission lock through metadata enqueue."""
    gate = load_gate(control)
    if gate['identity'] != attempt_identity or decision_id != gate['decision_id']:
        raise GateError('Decision belongs to a different attempt')
    if included != gate['included'] or excluded != gate['excluded']:
        raise GateError('Included and excluded genome IDs must match exactly')
    if gate['state'] != 'awaiting_decision' or not gate['eligible'] or not gate['included']:
        raise GateError('No eligible cohort can continue')
    verify_gate(gate)
    if 'acceptance' not in gate:
        gate['acceptance'] = {'decision_id': decision_id, 'included': included, 'excluded': excluded}
        atomic_json(control, gate)
        atomic_json(Path(control).parent / ('accepted-' + gate['attempt'] + '.json'), gate)
    return gate


def public_gate(gate):
    if not gate:
        return None
    return {k: gate[k] for k in ('schema', 'attempt', 'decision_id', 'state', 'eligible', 'included', 'excluded', 'outcomes', 'plan')}


def materialize(gate, destination):
    """Copy only admitted native outputs into a separate downstream workspace."""
    if 'acceptance' not in gate:
        raise GateError('Explicit exclusion acceptance required')
    verify_gate(gate)
    source = Path(gate['results'])
    destination = Path(destination)
    marker = destination / 'reproducibility/cohort_origin.json'
    if destination.exists():
        if not marker.is_file() or json.loads(marker.read_text())['decision_id'] != gate['decision_id']:
            raise GateError('Unrecognized continuation workspace')
        expected = {p: v for p, v in gate['receipts'].items() if p.split('/')[0] in {'antismash','funbgcex','plantismash','input_gbks'} and (Path(p).stem in gate['included'] if p.startswith('input_gbks/') else p.split('/')[1] in gate['included'])}
        if inventory(destination, ['antismash','funbgcex','plantismash','input_gbks']) != expected:
            raise GateError('Materialized scientific outputs changed')
        return
    temporary = destination.with_name(destination.name + '.building')
    # An interrupted materialization is never used as a completed cohort.
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    for genome in gate['included']:
        for category in ('input_gbks', 'antismash', 'funbgcex', 'plantismash'):
            relative = Path(category) / (genome + '.gbk' if category == 'input_gbks' else genome)
            src = source / relative
            dst = temporary / relative
            if src.is_dir():
                shutil.copytree(src, dst)
            elif src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    # Only tables with explicit genome ownership are admitted. Derived tables
    # are regenerated by downstream tools using this restricted cohort.
    for path in (source / 'summary_tables').glob('*.tsv'):
        fields, values = rows(path)
        key = next((k for k in ('genome_id', 'genome_id_current', 'fungal_id', 'bacteria_id') if k in fields), None)
        if key:
            chosen = [dict(r) for r in values if r[key] in gate['included']]
            for row in chosen:
                if row.get('gbk_used'):
                    row['gbk_used'] = str(destination / 'input_gbks' / (row[key] + '.gbk'))
            write_rows(temporary / 'summary_tables' / path.name, fields, chosen)
    for genome in gate['included']:
        relative = Path('summary_tables/bacterial_record_maps') / (genome + '.record_map.tsv')
        if (source / relative).is_file():
            (temporary / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, temporary / relative)
    # This public provenance states all failures and the exact changed denominator.
    atomic_json(temporary / 'reproducibility/cohort_origin.json', {**public_gate(gate), 'accepted': True, 'original_attempt_failed': True})
    atomic_json(temporary / 'summary/cohort_outcomes.json', {**public_gate(gate), 'accepted': True, 'original_attempt_failed': True})
    verify_gate(gate)
    os.replace(temporary, destination)


def asset_bindings(environment):
    """Hash the selected read-only external resources only at a decision boundary."""
    paths = []
    for key in ('ANTISMASH_DB_DIR', 'PFAM_DIR', 'FUNANNOTATE_DB'):
        value = environment.get(key)
        if value and Path(value).exists():
            paths.append(Path(value))
    software = environment.get('SOFTWARE_ROOT')
    if software and Path(software).is_dir():
        paths.extend(sorted(Path(software).rglob('*.sif')))
    bindings = {}
    for path in paths:
        if path.is_file():
            if path.is_symlink():
                raise GateError('Linked runtime identity')
            bindings[str(path)] = {'kind':'file','sha256':digest(path)}
        else:
            bindings[str(path)] = {'kind':'directory','sha256':fingerprint(inventory(path, ['.']))}
    return bindings


def verify_assets(bindings):
    for name, value in bindings.items():
        path = Path(name)
        actual = digest(path) if value['kind'] == 'file' else fingerprint(inventory(path, ['.']))
        if actual != value['sha256']:
            raise GateError('Runtime/database identity changed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['evaluate'])
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--exit-code', type=int, default=0)
    args = parser.parse_args()
    context = json.loads(args.context.read_text())
    gate = build_gate(args.results, args.control, context['identity'], context['settings'], args.exit_code, publish=False)
    if gate['state'] == 'awaiting_decision':
        gate['assets'] = asset_bindings({**context.get('asset_environment', {}), **os.environ})
        gate['decision_id'] = fingerprint({k:v for k,v in gate.items() if k != 'decision_id'})
    publish_gate(args.control, gate)
    print('COHORT_OUTCOME ' + json.dumps(public_gate(gate), sort_keys=True))
    if gate['state'] == 'awaiting_decision':
        print(f"Explicit decision required: Continue with {len(gate['included'])} genome(s); exclude {len(gate['excluded'])}. Successful annotation/detection will not rerun.")
        return 75
    if gate['state'] == 'failed':
        failures = '; '.join(r['genome_id'] + ': ' + r['reason'] for r in gate['outcomes'] if r['state'] == 'failed')
        print('ERROR: Genome outcome validation failed. ' + failures)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
