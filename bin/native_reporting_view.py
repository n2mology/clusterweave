"""Materialize reversible reporting keys over retained BiG-SCAPE TSV output."""
from pathlib import Path
import csv,json,hashlib,re

def materialize(raw_root, destination, records):
    raw_root, destination = Path(raw_root), Path(destination)
    by_gbk, by_record, canonical = {}, {}, set()
    for row in records:
        for field in ('genome_id','region_id'):
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,240}',row[field]):
                raise ValueError('Invalid reporting identity')
        key = row['genome_id'] + '__' + row['region_id']
        if row['raw_gbk'] in by_gbk or row['raw_record'] in by_record or key in canonical:
            raise ValueError('Ambiguous native reporting join')
        by_gbk[row['raw_gbk']] = row
        by_record[row['raw_record']] = row
        canonical.add(key)
    payloads, seen = [], set()
    for source in sorted(raw_root.rglob('*.tsv')):
        with source.open(newline='') as handle:
            reader=csv.DictReader(handle,delimiter='\t');fields=reader.fieldnames;rows=list(reader)
        if not fields or 'Record' not in fields or 'GBK' not in fields:
            continue
        output=[]
        for old in rows:
            row=dict(old);match=by_record.get(row['Record'])
            if match:
                if match['raw_gbk'] != row['GBK']:
                    raise ValueError('Conflicting record/GBK join')
                key=match['genome_id']+'__'+match['region_id']
                row['Record']=key+'.gbk_region_1';row['GBK']=key
                seen.add(match['raw_record'])
            elif row['GBK'] in by_gbk:
                raise ValueError('Unmapped raw record in mapped GBK')
            row['Raw_Record']=old['Record'];row['Raw_GBK']=old['GBK']
            assert all(row[k]==old[k] for k in fields if k not in ('Record','GBK'))
            output.append(row)
        target=destination/source.relative_to(raw_root);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('w',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=fields+['Raw_Record','Raw_GBK'],delimiter='\t');writer.writeheader();writer.writerows(output)
        payloads.append({'relative_path':str(source.relative_to(raw_root)),'rows':len(rows),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'view_sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    if seen != set(by_record):
        raise ValueError('Reporting map contains missing raw records')
    receipt={'schema':'native-reporting-view-v1','records':records,'tables':payloads,'scientific_columns_unchanged':True,'identity_columns':'Record/GBK are presentation aliases only; Raw_Record/Raw_GBK and this map preserve the engine keys. Native files and engine database remain unchanged.','compatibility_columns':'Existing antismash_region/antismash_bgc_id fields are internal consumer column names; producer fields identify actual plantiSMASH or imported reference evidence.'}
    (destination/'native-reporting-view.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def bind_public_records(view, raw_database, public_database, results=None):
    """Bind sanitized download names through unchanged engine GBK identifiers."""
    import sqlite3, copy
    result = copy.deepcopy(view)
    with sqlite3.connect(Path(public_database).resolve().as_uri()+"?mode=ro", uri=True) as public:
        public_rows = dict(public.execute("SELECT id,path FROM gbk"))
    used = set()
    for row, gid in resolve_engine_records(result, raw_database, results):
        if gid is None:
            row['runtime_gbk_id'] = None
            row['public_gbk'] = None
            continue
        if gid in used or gid not in public_rows:
            raise join_error(row, "missing or duplicated public GBK identity", [gid])
        used.add(gid)
        row['runtime_gbk_id'] = gid
        row['public_gbk'] = Path(public_rows[gid]).name
    result['public_identity_join'] = 'Engine gbk.id preserved by sanitizer; public_gbk joins viewer downloads to raw keys and original producer/native identity. Paths are not scientific keys.'
    return result


def join_error(row, reason, candidates=()):
    return ValueError(f"Native identity join: genome={row.get('genome_id')} "
                      f"record={row.get('original_record_id')} cluster={row.get('region_id')} "
                      f"raw_gbk={row.get('raw_gbk')}: {reason}; candidates={list(candidates)}")


def native_record(results, row):
    from Bio import SeqIO
    path = Path(results) / 'native_bgc' / row['genome_id'] / (row['region_id'] + '.gbk')
    if hashlib.sha256(path.read_bytes()).hexdigest() != row['native_sha256']:
        raise join_error(row, 'native SHA256 differs')
    records = list(SeqIO.parse(path, 'genbank'))
    if len(records) != 1:
        raise join_error(row, 'expected exactly one native cluster record')
    return records[0]


def length_exclusion(database, results, row):
    """Explain absence only from the completed engine run's retained policy.

    No default cutoff or absence-as-zero inference is allowed. BiG-SCAPE beta.6
    applies strict min < length < max; the original native slice stays retained.
    """
    import sqlite3
    if results is None:
        raise join_error(row, 'missing engine GBK; retained native and run policy required')
    with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as db:
        runs = list(db.execute('SELECT label,end_time,min_bgc_length FROM run'))
    if len(runs) != 1 or not runs[0][1] or not re.fullmatch(r'[A-Za-z0-9_.-]+', runs[0][0]):
        raise join_error(row, 'missing engine GBK without a unique completed run', runs)
    label, _, minimum = runs[0]
    config = Path(database).parent / (label + '.config.log')
    log = Path(database).parent / (label + '.log')
    text = config.read_text()
    limits = {}
    for key in ('MIN_BGC_LENGTH', 'MAX_BGC_LENGTH'):
        values = re.findall(r'^' + key + r': ([0-9]+)$', text, re.M)
        if len(values) != 1:
            raise join_error(row, 'missing or ambiguous retained length policy', values)
        limits[key] = int(values[0])
    lo, hi = limits['MIN_BGC_LENGTH'], limits['MAX_BGC_LENGTH']
    if minimum != lo or not 0 <= lo < hi:
        raise join_error(row, 'conflicting run/config length policy')
    if f'length constraint of min {lo} to max {hi} bp' not in log.read_text():
        raise join_error(row, 'length exclusion not corroborated by engine log')
    record = native_record(results, row)
    if lo < len(record) < hi:
        raise join_error(row, 'missing engine GBK inside admitted length range')
    return {'reason': 'engine_length_filter', 'length_bp': len(record),
            'min_exclusive_bp': lo, 'max_exclusive_bp': hi, 'run_label': label,
            'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
            'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}


def resolve_engine_records(view, database, results=None):
    """Record-scoped identities; missing records require positive exclusion evidence."""
    import sqlite3
    with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as db:
        rows = list(db.execute('SELECT id,path,hash FROM gbk'))
    used = set()
    for row in view['records']:
        matches = [(gid, path, digest) for gid, path, digest in rows if Path(path).stem == row['raw_gbk']]
        if len(matches) > 1:
            raise join_error(row, 'ambiguous engine GBK', matches)
        if not matches:
            row['comparison_exclusion'] = length_exclusion(database, results, row)
            row['comparison_status'] = 'excluded_length'
            yield row, None
            continue
        gid, _, digest = matches[0]
        if row.get('stage_sha256') and digest != row['stage_sha256']:
            raise join_error(row, 'engine GBK hash differs from canonical staged input', matches)
        if gid in used:
            raise join_error(row, 'engine GBK assigned more than once', matches)
        used.add(gid)
        row['comparison_status'] = 'included'
        row.pop('comparison_exclusion', None)
        yield row, gid
