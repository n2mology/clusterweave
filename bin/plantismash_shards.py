"""Bounded whole-record plant detection and deterministic native-evidence join.

Like antiSMASH's record runner, no successful genome is published until every
supplied-CDS record has completed and its native output has been validated.
Native child files and completion receipts remain intact; the outer assembly is
explicitly a ClusterWeave product, not a forged native whole-genome execution.
"""
from pathlib import Path
import copy
import hashlib
import html
import json
import os
import signal
import subprocess
import time
import zipfile

SCHEMA = 'clusterweave-plant-record-merge-v1'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def raw_records(source):
    """Split on GenBank record terminators, retaining the original record bytes."""
    buffer = bytearray()
    with Path(source).open('rb') as stream:
        for line in stream:
            buffer.extend(line)
            if line.strip() == b'//':
                yield bytes(buffer)
                buffer.clear()
    if buffer.strip():
        raise ValueError('Unterminated original GenBank record')


def pack(folder, name='records.zip'):
    folder = Path(folder)
    paths = sorted((p for p in folder.rglob('*') if p.is_file() and p != folder / name and p != folder / 'native-completion.json'), key=lambda p:p.relative_to(folder).as_posix())
    with zipfile.ZipFile(folder / name, 'w', allowZip64=True) as archive:
        for p in paths:
            if p.is_symlink():
                raise ValueError('Symlink in plant shard output')
            info = zipfile.ZipInfo(p.relative_to(folder).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with p.open('rb') as src, archive.open(info, 'w', force_zip64=True) as dst:
                import shutil
                shutil.copyfileobj(src, dst, 1024 * 1024)


def validate_join(original, folder, completion):
    """Prove complete original-record coverage against every retained native child."""
    from plantismash_native import read_native, PRODUCER, recorded_profile
    from Bio import SeqIO
    folder = Path(folder)
    if completion.get('assembler') != 'ClusterWeave' or completion.get('producer') != PRODUCER or completion.get('completed') is not True:
        raise ValueError('Invalid plant record assembly')
    parent_profile = recorded_profile(folder)
    parent_source = folder.parent / 'original.gbk'
    if sha(parent_source) != original['source_file_sha256']:
        raise ValueError('Whole original plant input identity differs')
    source_hashes = {i:hashlib.sha256(raw).hexdigest() for i, raw in enumerate(raw_records(parent_source), 1)}
    if len(source_hashes) != len(original['records']):
        raise ValueError('Whole original plant record coverage differs')
    expected = [r for r in original['records'] if r['CDS']]
    rows = completion['shards']
    if len(rows) != len(expected):
        raise ValueError('Missing or extra plant shard')
    links, ids, searches = [], set(), 0
    merged = iter(SeqIO.parse(str(folder / 'records.final.gbk'), 'genbank'))
    for old, row in zip(expected, rows):
        ordinal = old['original_record_ordinal']
        rel = f'shards/{ordinal:06d}'
        if row['ordinal'] != ordinal or row['root'] != rel:
            raise ValueError('Plant shard order or path differs')
        child = folder / rel
        for name, value in row['evidence'].items():
            if name not in {'original.gbk','original-identity.json','native-exit.json','native/native-completion.json','execution.json'} or sha(child / name) != value:
                raise ValueError('Plant shard receipt identity differs')
        if set(row['evidence']) != {'original.gbk','original-identity.json','native-exit.json','native/native-completion.json','execution.json'}:
            raise ValueError('Missing plant shard evidence')
        inventory = json.loads((child / 'original-identity.json').read_text())
        if inventory['records'] != [old] or inventory['source_file_sha256'] != source_hashes[ordinal] or inventory['source_file_sha256'] != sha(child / 'original.gbk'):
            raise ValueError('Plant shard original mapping differs')
        native_completion = json.loads((child / 'native/native-completion.json').read_text())
        if native_completion['schema'] != 'plantismash-private-completion-v1':
            raise ValueError('Nested plant assembly is not a native shard')
        result = read_native(inventory, child / 'native')
        if not result['valid']:
            raise ValueError('Invalid plant shard: ' + '; '.join(result['reasons']))
        if result['profile_id'] != parent_profile:
            raise ValueError('Mixed plant execution profiles in record assembly')
        native_path, = (child / 'native').glob('*.final.gbk')
        record, = SeqIO.parse(str(native_path), 'genbank')
        canonical = next(merged, None)
        if canonical is None or record.format('genbank') != canonical.format('genbank'):
            raise ValueError('Merged plant record differs from native shard')
        if record.id in ids:
            raise ValueError('Native record identity collision between shards')
        ids.add(record.id)
        for call in result['calls']:
            name = f'r{ordinal:06d}_' + call['native_cluster_gbk']
            if sha(folder / name) != sha(child / 'native' / call['native_cluster_gbk']):
                raise ValueError('Merged cluster differs from native shard')
        links.extend(native_completion['records'])
        searches += native_completion['successful_hmm_searches']
    if next(merged, None) is not None or completion['records'] != links or completion['evaluated_records'] != [r['native_id'] for r in links] or completion['successful_hmm_searches'] != searches:
        raise ValueError('Plant assembly coverage differs')
    return searches


def merge(original, root, completed):
    from plantismash_native import PRODUCER
    import shutil
    root = Path(root)
    folder = root / 'native.pending'
    folder.mkdir()
    (root / 'shards').rename(folder / 'shards')
    links, rows, searches = [], [], 0
    with (folder / 'records.final.gbk').open('wb') as combined:
        for old in original['records']:
            if not old['CDS']:
                continue
            ordinal = old['original_record_ordinal']
            child = folder / 'shards' / f'{ordinal:06d}'
            result = completed[ordinal]
            path, = (child / 'native').glob('*.final.gbk')
            with path.open('rb') as stream:
                shutil.copyfileobj(stream, combined)
            for call in result['calls']:
                shutil.copyfile(child / 'native' / call['native_cluster_gbk'], folder / (f'r{ordinal:06d}_' + call['native_cluster_gbk']))
            completion = json.loads((child / 'native/native-completion.json').read_text())
            links.extend(completion['records'])
            searches += completion['successful_hmm_searches']
            evidence = {name: sha(child / name) for name in ['original.gbk','original-identity.json','execution.json','native-exit.json','native/native-completion.json']}
            rows.append({'ordinal':ordinal, 'original_id':old['original_id'], 'root':f'shards/{ordinal:06d}', 'evidence':evidence})
    index = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>plantiSMASH records</title><style>body{font:16px Arial,sans-serif;margin:0;padding:24px;color:#263529;background:#f7faf7}h1{color:#35683d}ul{padding:0;list-style:none;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}a{display:block;padding:14px;background:white;border:1px solid #acbfaf;border-radius:4px;color:#265b35}a:focus,a:hover{background:#e4f0e5}</style><h1>plantiSMASH</h1><p>Select a record to open its report.</p><ul>'
    index += ''.join(f'<li><a href="{r["root"]}/native/index.html">{html.escape(r["original_id"])}</a></li>' for r in rows) + '</ul>'
    (folder / 'index.html').write_text(index)
    receipt = {'schema':SCHEMA,'assembler':'ClusterWeave','hmm_search_scope':'original_record; native E-values retain shard search-space size','producer':PRODUCER,'completed':True,'records':links,'evaluated_records':[r['native_id'] for r in links],'successful_hmm_searches':searches,'shards':rows}
    save(folder / 'native-completion.json', receipt)
    print('PLANT_PHASE phase=validating', flush=True)
    validate_join(original, folder, receipt)
    print('PLANT_PHASE phase=exporting', flush=True)
    pack(folder)
    folder.rename(root / 'native')
    save(root / 'native-exit.json', {'exit_code':0,'producer':PRODUCER,'execution_kind':'validated_record_assembly','native_exits':'native/shards/*/native-exit.json'})


def execute(args, original, root, command_factory):
    """Run at most record_parallelism children and reap process groups on failure."""
    from plantismash_native import read_native, PRODUCER
    root = Path(root)
    shards = root / 'shards'
    shards.mkdir()
    todo = []
    count = 0
    for count, raw in enumerate(raw_records(args.input), 1):
        old = original['records'][count - 1]
        if not old['CDS']:
            continue
        child = shards / f'{count:06d}'
        child.mkdir()
        (child / 'original.gbk').write_bytes(raw)
        inventory = {'admitted':True,'records':[old],'source_file_sha256':sha(child / 'original.gbk'),'parent_source_sha256':original['source_file_sha256']}
        save(child / 'original-identity.json', inventory)
        todo.append((count, child, inventory))
    if count != len(original['records']) or not todo:
        raise ValueError('Original plant record count differs')
    active, complete, events = {}, {}, []
    def event(ordinal, state, **extra):
        events.append({'time':time.time(),'ordinal':ordinal,'state':state,**extra})
        save(root / 'shard-execution.json', {'record_parallelism':args.record_parallelism,'cpus_per_shard':args.cpus,'events':events,'completed':len(complete),'total':len(todo)})
        print(f'PLANT_SHARD ordinal={ordinal} state={state} completed={len(complete)}/{len(todo)}', flush=True)
    def cancel(signum, frame):
        raise InterruptedError('Plant shard execution cancelled')
    previous = {sig:signal.signal(sig,cancel) for sig in [signal.SIGTERM, signal.SIGINT]}
    pending = iter(todo)
    exhausted = False
    try:
        while active or not exhausted:
            while not exhausted and len(active) < args.record_parallelism:
                item = next(pending, None)
                if item is None:
                    exhausted = True
                    break
                ordinal, child, inventory = item
                cmd, env = command_factory(child, child / 'original.gbk', inventory)
                stdout = (child / 'stdout.log').open('wb')
                stderr = (child / 'stderr.log').open('wb')
                try:
                    process = subprocess.Popen(cmd, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
                finally:
                    stdout.close();stderr.close()
                active[process.pid] = (process, ordinal, child, inventory)
                event(ordinal,'running',pid=process.pid)
            for pid, (process, ordinal, child, inventory) in list(active.items()):
                code = process.poll()
                if code is None:
                    continue
                process.wait()
                del active[pid]
                save(child / 'native-exit.json', {'exit_code':code,'producer':PRODUCER})
                if code:
                    event(ordinal,'failed',exit_code=code)
                    raise ValueError(f'plantiSMASH record {ordinal} exited {code}; genome merge refused')
                result = read_native(inventory, child / 'native')
                if not result['valid']:
                    event(ordinal,'invalid')
                    raise ValueError(f'plantiSMASH record {ordinal} invalid: {result["reasons"]}')
                complete[ordinal] = result
                event(ordinal,'complete',exit_code=0)
            if active:
                time.sleep(0.1)
    finally:
        for process, ordinal, child, inventory in active.values():
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        for process, ordinal, child, inventory in active.values():
            process.wait()
            save(child / 'native-exit.json', {'exit_code':process.returncode,'producer':PRODUCER,'cancelled':True})
            event(ordinal,'cancelled',exit_code=process.returncode)
        for sig, handler in previous.items():signal.signal(sig,handler)
    print('PLANT_PHASE phase=merging', flush=True)
    merge(original, root, complete)
